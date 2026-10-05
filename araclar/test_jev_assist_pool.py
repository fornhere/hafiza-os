"""Synthetic assist-pool and request-packaging checks; no personal data, no network."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import gorev_baglam
import jev_client
import jev_retrieval as j


def card(i, statement='Kısa yazı tercihi'):
    return dict(id=f'm{i:02}', title='yazı', statement=statement, scope='user', domains=['all'])


def answer(vault, query, cards, **kwargs):
    scores = {c['id']: 2.0 for c in cards}
    return dict(mode='assist', scores=scores, facet_scores={0: dict(scores)},
                distributions={c['id']: {'0': 0, '1': 0, '2': 1} for c in cards},
                facet_distributions={0: {c['id']: {'0': 0, '1': 0, '2': 1} for c in cards}},
                choices={}, diagnostics=['quantized_probability'], degraded=False, cache_hit=False,
                usage={'input_tokens': 10 * len(cards)}, latency_ms=len(cards),
                quantized_probability_count=len(cards))


class PackagedEvaluateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        (self.vault / 'komuta').mkdir()

    def config(self, **changes):
        values = dict(mode='shadow', retrieval_mode='assist')
        values.update(changes)
        (self.vault / 'komuta/jev.json').write_text(json.dumps(values))

    def run_pool(self, cards, side_effect=answer, order=None):
        with patch.object(jev_client, 'evaluate', side_effect=side_effect) as call:
            result = j.packaged_evaluate(self.vault, 'yazı', cards, facets=['yazı'], lexical_order=order)
        return result, call

    def test_fitting_pool_is_one_unchanged_request(self):
        self.config()
        cards = [card(i) for i in range(5)]
        result, call = self.run_pool(cards)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[2], cards)
        self.assertNotIn('packages', result)

    def test_pool_above_candidate_limit_is_split_not_degraded(self):
        # Previously a 42-card catalog failed locally as budget_exceeded.
        self.config(max_candidates=4)
        cards = [card(i) for i in range(10)]
        result, call = self.run_pool(cards)
        # Packages run in parallel; call order is not part of the contract.
        self.assertEqual(sorted(len(c.args[2]) for c in call.call_args_list), [2, 4, 4])
        self.assertEqual(sorted(x['id'] for c in call.call_args_list for x in c.args[2]), [c['id'] for c in cards])
        self.assertEqual([p['size'] for p in result['packages']], [4, 4, 2])
        self.assertFalse(result['degraded'])
        self.assertEqual(set(result['scores']), {c['id'] for c in cards})
        self.assertEqual(set(result['facet_scores'][0]), {c['id'] for c in cards})
        self.assertEqual(result['fallback_ids'], [])
        self.assertEqual(result['usage'], {'input_tokens': 100})
        self.assertEqual(result['quantized_probability_count'], 10)
        self.assertEqual(result['diagnostics'], ['quantized_probability'])

    def test_character_budget_splits_exactly(self):
        self.config()
        cards = [card(i, 'x' * 40) for i in range(3)]
        config = jev_client.load_config(self.vault)
        body = j._rerank_body(config, 'yazı', ['yazı'], cards[:2], {}, 'retrieval')
        self.config(max_input_chars=len(json.dumps(body, ensure_ascii=False)))
        result, call = self.run_pool(cards)
        self.assertEqual(sorted(len(c.args[2]) for c in call.call_args_list), [1, 2])
        # Every package sent must pass the client's own payload check.
        for c in call.call_args_list:
            sent = j._rerank_body(config, 'yazı', ['yazı'], c.args[2], {}, 'retrieval')
            self.assertLessEqual(len(json.dumps(sent, ensure_ascii=False)), len(json.dumps(body, ensure_ascii=False)))

    def test_too_many_packages_keep_lexical_leaders(self):
        self.config(max_candidates=2)
        cards = [card(i) for i in range(9)]
        order = ['m08', 'm07', 'm06', 'm05', 'm04', 'm03']
        result, call = self.run_pool(cards, order=order)
        self.assertEqual(call.call_count, j.MAX_PACKAGES)
        sent = [c['id'] for x in call.call_args_list for c in x.args[2]]
        self.assertEqual(sorted(sent), sorted(order))
        self.assertIn('pool_truncated', result['diagnostics'])
        self.assertEqual(sorted(result['fallback_ids']), ['m00', 'm01', 'm02'])

    def test_partial_failure_keeps_scored_packages_without_retry(self):
        self.config(max_candidates=3)
        cards = [card(i) for i in range(6)]
        def flaky(vault, query, package, **kwargs):
            if package[0]['id'] == 'm03':
                return dict(mode='assist', scores={}, degraded=True, diagnostics=['http_server_error'])
            return answer(vault, query, package, **kwargs)
        result, call = self.run_pool(cards, flaky)
        self.assertEqual(call.call_count, 2)
        self.assertFalse(result['degraded'])
        self.assertEqual(sorted(result['scores']), ['m00', 'm01', 'm02'])
        self.assertEqual(result['fallback_ids'], ['m03', 'm04', 'm05'])
        self.assertIn('package_fallback', result['diagnostics'])
        self.assertIn('http_server_error', result['diagnostics'])

    def test_all_packages_failed_is_degraded(self):
        self.config(max_candidates=2)
        result, _ = self.run_pool([card(i) for i in range(4)],
                                  lambda *a, **k: dict(scores={}, degraded=True, diagnostics=['deadline_exceeded']))
        self.assertTrue(result['degraded'])
        self.assertNotIn('package_fallback', result['diagnostics'])

    def test_packages_share_one_package_deadline(self):
        self.config(max_candidates=2)
        seen = []
        lock = threading.Lock()
        def record(vault, query, package, **kwargs):
            with lock: seen.append(jev_client._CONTEXT.get()['deadline'])
            return answer(vault, query, package, **kwargs)
        with jev_client.evaluation_context(self.vault):
            deadline = jev_client._CONTEXT.get()['deadline']
            self.run_pool([card(i) for i in range(6)], record)
        self.assertEqual(seen, [deadline] * 3)


class AssistPoolTests(unittest.TestCase):
    def rows(self):
        return [dict(memory_id='kapak', subject_key='kapak', statement='Kapaklarda büyük yazı kullan.'),
                dict(memory_id='ses', subject_key='ses', statement='Mikrofon kazancını düşük tut.'),
                dict(memory_id='sunum', subject_key='sunum', statement='Slaytlarda tek fikir göster.')]

    def test_pool_holds_only_lexically_touched_rows_in_loose_order(self):
        rows = self.rows()
        pool = j.assist_pool('Kapağın yazısı ve sunum', rows, [])
        self.assertEqual([row['memory_id'] for _, row in pool], ['kapak', 'sunum'])
        order = [row['memory_id'] for _, row in j.loose_candidates('Kapağın yazısı ve sunum', rows, [], 3)]
        self.assertEqual(order[:2], ['kapak', 'sunum'])
        self.assertEqual(j.assist_pool('Hava nasıl?', rows, []), [])
        self.assertEqual(len(j.assist_pool('yazı tek fikir mikrofon', rows, [], limit=2)), 2)

    def test_synonym_expansion_reaches_pool(self):
        rows = self.rows()
        self.assertEqual([row['memory_id'] for _, row in j.assist_pool('thumbnail', rows, [])], ['kapak'])

    def test_fast_matching_equals_word_match(self):
        vocabulary = {'kapak', 'kapağı', 'kapaklarda', 'thumbnail', 'beyni', 'beyin', 'kitabı',
                      'sunum', 'slayt', 'slaytlarda', 'ab', 'abc', 'yedeklemeleri', 'yedek'}
        for term in vocabulary | {'kitap', 'beyin', 'slideshow', 'yedekleme', 'kap'}:
            with self.subTest(term=term):
                self.assertEqual(j._matching_words(term, vocabulary),
                                 {w for w in vocabulary if gorev_baglam.word_match(term, w)})


class AssistCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(mode='shadow', retrieval_mode='assist')))
        self.rows = [dict(memory_id='kapak', subject_key='kapak', statement='Kapaklarda büyük yazı kullan.',
                          scope='user', status='active'),
                     dict(memory_id='ses', subject_key='ses', statement='Mikrofon kazancını düşük tut.',
                          scope='user', status='active')]

    def catalog(self, query, side_effect=answer):
        import hafiza
        with patch.object(hafiza, 'load_catalog', return_value=self.rows), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(hafiza, 'retrievable', return_value=True), \
             patch.object(jev_client, 'evaluate', side_effect=side_effect) as call:
            selected, result = j.catalog(self.vault, query, self.rows, lambda rows, q: [], 'user')
        return selected, result, call

    def test_empty_pool_keeps_local_result_without_network(self):
        selected, result, call = self.catalog('Hava nasıl olacak?')
        call.assert_not_called()
        self.assertEqual(selected, [])
        self.assertEqual(result['diagnostics'], ['assist_pool_empty'])
        self.assertFalse(result['degraded'])
        self.assertEqual(result['suggested_ids'], [])

    def test_pool_sends_only_touched_rows_and_suggests_from_them(self):
        selected, result, call = self.catalog('Kapak yazısı')
        self.assertEqual([c['id'] for c in call.call_args.args[2]], ['kapak'])
        self.assertEqual(selected, [])
        self.assertEqual(result['suggested_ids'], ['kapak'])
        self.assertEqual(result['pool_size'], 1)

    def test_on_mode_still_sees_whole_catalog(self):
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(mode='on')))
        _, _, call = self.catalog('Hava nasıl olacak?')
        self.assertEqual([c['id'] for c in call.call_args.args[2]], ['kapak', 'ses'])

    def test_on_mode_partial_packages_fall_back_to_local(self):
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(mode='on', max_candidates=1)))
        def flaky(vault, query, package, **kwargs):
            if package[0]['id'] == 'ses':
                return dict(scores={}, degraded=True, diagnostics=['http_server_error'])
            return answer(vault, query, package, **kwargs)
        selected, result, _ = self.catalog('Kapak yazısı', flaky)
        self.assertTrue(result['degraded'])
        self.assertEqual(selected, [])


if __name__ == '__main__':
    unittest.main()
