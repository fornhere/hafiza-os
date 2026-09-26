"""Synthetic gate and mixed ranking checks; no personal source data."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import bilgi_agi
import gorev_baglam
import hafiza
import jev_client
import jev_retrieval


class RerankTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'komuta').mkdir()
        self.config()

    def config(self, **changes):
        values = dict(mode='on', retrieval_mode='rerank', procedure_mode='off')
        values.update(changes)
        (self.vault / 'komuta/jev.json').write_text(json.dumps(values))

    def memory_rows(self, count):
        return [dict(memory_id=f'm{i}', subject_key='Writing style', statement=f'Writing style {i}',
                     scope='user', source_path=f'm{i}.md') for i in range(count)]

    @staticmethod
    def high_answer(vault, query, cards, **kwargs):
        return dict(mode='rerank', scores={card['id']: 2 for card in cards},
                    distributions={card['id']: {'0': 0, '1': 0, '2': 1} for card in cards},
                    degraded=False, diagnostics=[])

    @staticmethod
    def facet_answer(cards, p2_by_facet):
        distributions = {j: {card['id']: {'0': 1 - values.get(card['id'], 0), '1': 0,
                                         '2': values.get(card['id'], 0)} for card in cards}
                         for j, values in enumerate(p2_by_facet)}
        return dict(mode='rerank', degraded=False, diagnostics=[],
                    scores={card['id']: max(values[card['id']]['2'] * 2 for values in distributions.values())
                            for card in cards},
                    distributions=dict(distributions[len(p2_by_facet) - 1]),
                    facet_distributions=distributions)

    def rerank_rows(self, rows, answer=None, state=None, query='Writing style'):
        with patch.object(hafiza, 'load_catalog', return_value=rows), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(jev_client, 'evaluate', side_effect=answer or self.high_answer) as evaluate:
            selected, knowledge, result = jev_retrieval.rerank(
                self.vault, query, rows, None, state if state is not None else {}, 2000)
        return selected, knowledge, result, evaluate

    def test_facet_first_order_covers_then_fills_with_stable_ties(self):
        ids = ['note:z', 'memory:b', 'memory:a', 'note:a', 'memory:low', 'memory:missing']
        values = {0: {'memory:b': 1.98, 'memory:a': 1.98, 'memory:low': 1.49},
                  1: {'note:z': 1.5, 'note:a': 1.5, 'outside-pool': 2},
                  2: {'memory:a': 2}, 3: {}}
        self.assertEqual(jev_retrieval.facet_first_order(values, ids, 1.5),
                         ['memory:a', 'note:a', 'memory:b', 'note:z'])

    def test_multi_facet_request_uses_one_full_query_pool(self):
        query = 'site için renk ve font kaynakları'
        rows = self.memory_rows(3)
        plan = jev_retrieval.facet_plan(query)
        self.assertEqual(len(plan), 2)
        with patch.object(jev_retrieval, 'loose_candidates', wraps=jev_retrieval.loose_candidates) as loose:
            _, _, result, evaluate = self.rerank_rows(rows, query=query)
        # Preserve the existing full-query + previous_user preselection input.
        loose.assert_called_once_with(query + ' ', rows, [], 24)
        evaluate.assert_called_once()
        self.assertEqual(evaluate.call_args.args[1], query)
        self.assertEqual(evaluate.call_args.kwargs['purpose'], 'retrieval_rerank_facets')
        self.assertEqual(evaluate.call_args.kwargs['facets'], [p['text'] for p in plan])
        self.assertEqual(result['facet_count'], 2)
        self.assertEqual(result['rerank_purpose'], 'retrieval_rerank_facets')

    def test_single_facet_keeps_legacy_request_and_order(self):
        rows = list(reversed(self.memory_rows(3)))
        selected, _, result, evaluate = self.rerank_rows(rows)
        self.assertEqual(evaluate.call_args.kwargs['purpose'], 'retrieval_rerank')
        self.assertEqual(evaluate.call_args.kwargs['facets'], ['Writing style'])
        self.assertEqual([row['memory_id'] for row in selected], ['m0', 'm1', 'm2'])
        self.assertEqual(result['facet_count'], 1)
        self.assertEqual(result['rerank_purpose'], 'retrieval_rerank')
        self.assertNotIn('coverage', result)

    def test_disabled_facets_keep_legacy_request(self):
        self.config(rerank_facets=False)
        query = 'site için renk ve font kaynakları'
        self.assertGreater(len(jev_retrieval.facet_plan(query)), 1)
        selected, _, result, evaluate = self.rerank_rows(self.memory_rows(3), query=query)
        self.assertEqual(evaluate.call_args.kwargs['purpose'], 'retrieval_rerank')
        self.assertEqual(evaluate.call_args.kwargs['facets'], [query])
        self.assertEqual([row['memory_id'] for row in selected], ['m0', 'm1', 'm2'])
        self.assertEqual(result['facet_count'], 1)
        self.assertEqual(result['rerank_purpose'], 'retrieval_rerank')
        self.assertNotIn('coverage', result)

    def test_multi_facet_limit_preserves_each_best_candidate(self):
        self.config(rerank_limit=2)
        def answer(vault, query, cards, **kwargs):
            return self.facet_answer(cards, [{'memory:m0': .99, 'memory:m1': .98}, {'memory:m2': .8}])
        selected, _, result, _ = self.rerank_rows(self.memory_rows(3), answer,
                                                query='site için renk ve font kaynakları')
        self.assertEqual([row['memory_id'] for row in selected], ['m0', 'm2'])
        self.assertEqual(result['proposed_ids'], ['memory:m0', 'memory:m2'])
        self.assertEqual(result['coverage'], {'0': 'covered', '1': 'covered'})

    def test_three_facet_requests_split_within_question_budget(self):
        self.config(max_questions=7)
        query = 'site için renk ve font ve düzen kaynakları'
        plan = jev_retrieval.facet_plan(query)
        self.assertEqual(len(plan), 3)
        def answer(vault, query, cards, **kwargs):
            return self.facet_answer(cards, [{card['id']: .8 for card in cards}] * 3)
        _, _, result, evaluate = self.rerank_rows(self.memory_rows(7), answer, query=query)
        self.assertEqual([package['size'] for package in result['packages']], [2, 2, 2, 1])
        self.assertEqual(evaluate.call_count, 4)
        self.assertEqual(result['facet_count'], 3)
        for call in evaluate.call_args_list:
            self.assertEqual(call.kwargs['facets'], [p['text'] for p in plan])
            self.assertEqual(call.kwargs['purpose'], 'retrieval_rerank_facets')
            self.assertLessEqual(len(call.args[2]) * len(call.kwargs['facets']), 7)
        for j in range(3):
            self.assertEqual(set(result['facet_distributions'][j]), set(result['pool_ids']))
            self.assertTrue(all(p['2'] == .8 for p in result['facet_distributions'][j].values()))

    def test_multi_facet_question_budget_too_small_never_evaluates(self):
        self.config(max_questions=2)
        selected, knowledge, result, evaluate = self.rerank_rows(
            self.memory_rows(2), query='site için renk ve font ve düzen kaynakları')
        evaluate.assert_not_called()
        self.assertIsNone(selected)
        self.assertIsNone(knowledge)
        self.assertTrue(result['degraded'])
        self.assertEqual(result['diagnostics'], ['budget_exceeded'])
        self.assertEqual(result['facet_count'], 3)
        self.assertEqual(result['coverage'], {'0': 'unresolved', '1': 'unresolved', '2': 'unresolved'})

    def test_multi_facet_character_budget_uses_facet_rubric(self):
        query = 'site için renk ve font kaynakları'
        rows = self.memory_rows(2)
        _, _, _, evaluate = self.rerank_rows(rows, query=query)
        cards = evaluate.call_args.args[2]
        facets = evaluate.call_args.kwargs['facets']
        config = jev_client.load_config(self.vault)
        body = jev_retrieval._rerank_body(config, query, facets, cards, {}, 'retrieval_rerank_facets')
        limit = len(json.dumps(body, ensure_ascii=False))
        for char_budget, sizes in ((limit, [2]), (limit - 1, [1, 1])):
            with self.subTest(char_budget=char_budget):
                self.config(max_input_chars=char_budget)
                _, _, result, evaluate = self.rerank_rows(rows, query=query)
                self.assertEqual([package['size'] for package in result['packages']], sizes)
                for call in evaluate.call_args_list:
                    payload = jev_retrieval._rerank_body(config, query, facets, call.args[2], {},
                                                        call.kwargs['purpose'])
                    self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), char_budget)

    def test_multi_facet_degraded_distributions_do_not_cover_fallback(self):
        self.config(max_candidates=1, rerank_limit=2)
        def answer(vault, query, cards, **kwargs):
            result = self.facet_answer(cards, [{'memory:m0': .9}, {'memory:m1': 1}])
            if cards[0]['id'] == 'memory:m1':
                result.update(degraded=True, diagnostics=['request_failed'])
            return result
        rows = self.memory_rows(2)
        with patch.object(gorev_baglam, 'rank_records', return_value=rows):
            selected, _, result, _ = self.rerank_rows(rows, answer,
                                                    query='site için renk ve font kaynakları')
        self.assertEqual(selected, rows)
        self.assertEqual(result['fallback_ids'], ['memory:m1'])
        self.assertEqual(result['coverage'], {'0': 'covered', '1': 'unresolved'})
        for values in result['facet_distributions'].values():
            self.assertEqual(set(values), {'memory:m0'})

    def test_multi_facet_coverage_uses_delivered_notes_and_limit(self):
        (self.vault / 'bilgi').mkdir()
        rows = self.memory_rows(1)
        note = dict(id='n1', title='Font', statement='Font note', scope='user', domains=['site'],
                    kind='preference', sources=[])
        def answer(vault, query, cards, **kwargs):
            return self.facet_answer(cards, [{'memory:m0': .9}, {'note:n1': .75}])
        for limit, budget, coverage in ((2, 2000, 'covered'), (2, 1, 'unresolved'), (1, 2000, 'unresolved')):
            self.config(rerank_limit=limit)
            with self.subTest(limit=limit, budget=budget), \
                 patch.object(bilgi_agi, '_rows', return_value=([note], [])), \
                 patch.object(bilgi_agi, 'note_version', return_value='note-sha'), \
                 patch.object(hafiza, 'load_catalog', return_value=rows), \
                 patch.object(hafiza, 'context_record_errors', return_value=[]), \
                 patch.object(jev_client, 'evaluate', side_effect=answer):
                selected, knowledge, result = jev_retrieval.rerank(
                    self.vault, 'site için renk ve font kaynakları', rows, None, {}, budget)
            self.assertEqual(selected, rows)
            self.assertEqual(knowledge['records'], [note] if coverage == 'covered' else [])
            self.assertEqual(result['coverage'], {'0': 'covered', '1': coverage})

    def test_gate_no_preserves_non_memory_package(self):
        answer = dict(choices={'need':'no_memory'}, distributions={'need':{'search_memory':.01,'no_memory':.98,'insufficient_context':.01}}, degraded=False, diagnostics=[])
        minimal = dict(text='project and procedure', selected_ids=['project','procedure-reading'], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate', return_value=answer) as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=minimal) as build:
            result = gorev_baglam.build_task_package(self.vault, 'Explain addition')
        self.assertEqual(result['text'], 'project and procedure')
        self.assertTrue(build.call_args.args[-1])
        self.assertEqual(evaluate.call_args.kwargs['purpose'], 'retrieval_gate')

    def test_gate_yes_passes_previous_turn_and_error_uses_local(self):
        minimal = dict(text='', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate', return_value=dict(choices={'need':'search_memory'}, distributions={'need':{'search_memory':.9,'no_memory':.05,'insufficient_context':.05}}, degraded=False)) as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=dict(minimal)) as build:
            gorev_baglam.build_task_package(self.vault, 'Use my preference', previous_user='Earlier task', cwd='/work')
        self.assertEqual(evaluate.call_args.kwargs['state']['previous_user'], 'Earlier task')
        self.assertEqual(build.call_args.args[-2]['previous_user'], 'Earlier task')
        self.assertNotIn('cwd', build.call_args.args[-2])
        def local_build(*args):
            self.assertEqual(jev_client.load_config(self.vault)['mode'], 'off')
            return dict(minimal)
        with patch.object(jev_client, 'evaluate', return_value=dict(scores={}, degraded=True, diagnostics=['deadline_exceeded'])), \
             patch.object(gorev_baglam, '_build_task_package', side_effect=local_build) as build:
            result = gorev_baglam.build_task_package(self.vault, 'Use my preference')
            self.assertEqual(jev_client.load_config(self.vault)['mode'], 'on')
        self.assertIsNone(build.call_args.args[-1])
        self.assertTrue(result['jev']['rerank']['degraded'])

    def test_private_prompt_never_reaches_jev(self):
        minimal = dict(text='', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate') as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=minimal):
            result = gorev_baglam.build_task_package(self.vault, 'Do not save this private request')
        evaluate.assert_not_called()
        self.assertTrue(result['jev']['rerank']['degraded'])

    def test_explicit_recall_skips_gate_but_builds_memory(self):
        minimal = dict(text='stored decision', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client,'evaluate') as evaluate, \
             patch.object(gorev_baglam,'_build_task_package',return_value=minimal) as build:
            result=gorev_baglam.build_task_package(self.vault,'Neye karar vermiştik?')
        evaluate.assert_not_called()
        self.assertFalse(build.call_args.args[-1])
        self.assertIn('explicit_recall_bypass',result['jev']['gate']['diagnostics'])

    def test_rerank_selects_at_most_configured_limit(self):
        self.config(rerank_limit=2)
        rows = [dict(memory_id=f'm{i}', subject_key='style', statement=f'Writing style {i}',
                     scope='user', source_path=f'm{i}.md') for i in range(5)]
        def answer(vault, query, cards, **kwargs):
            return dict(scores={card['id']: 2 for card in cards}, distributions={card['id']:{'0':0,'1':0,'2':1} for card in cards}, degraded=False, diagnostics=[])
        with patch.object(bilgi_agi, '_rows', return_value=([], [])), \
             patch.object(hafiza, 'load_catalog', return_value=rows), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(jev_client, 'evaluate', side_effect=answer):
            selected, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Writing style', rows, None, {}, 2000)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(result['proposed_ids']), 2)
        self.assertEqual(knowledge['records'], [])

    def test_default_pool_evaluates_twenty_candidates(self):
        rows = self.memory_rows(20)
        _, _, result, evaluate = self.rerank_rows(rows)
        config = jev_client.load_config(self.vault)
        self.assertEqual(config['rerank_candidates'], 24)
        self.assertEqual(config['max_candidates'], 32)
        self.assertEqual(sum(len(call.args[2]) for call in evaluate.call_args_list), 20)
        self.assertEqual(len(result['pool_ids']), 20)
        self.assertEqual(result['pool_ids'], sorted('memory:' + row['memory_id'] for row in rows))
        self.assertEqual(result['fallback_ids'], [])

    def test_configured_pool_limit_is_respected(self):
        rows = self.memory_rows(32)
        for limit in (4, 24, 32):
            with self.subTest(limit=limit):
                self.config(rerank_candidates=limit)
                _, _, result, evaluate = self.rerank_rows(rows)
                self.assertEqual(len(result['pool_ids']), limit)
                self.assertEqual(sum(len(call.args[2]) for call in evaluate.call_args_list), limit)

    def test_input_budget_splits_packages_without_losing_candidates(self):
        self.config(max_input_chars=1200)
        rows = [dict(memory_id=f'm{i}', subject_key='style', statement='Writing style ' + 'x'*180,
                     conditions='Only for this writing style', scope='user', source_path=f'm{i}.md')
                for i in range(8)]
        state = dict(previous_user='Önceki yazı', project='Deneme')
        _, _, result, evaluate = self.rerank_rows(rows, state=state)
        self.assertGreater(evaluate.call_count, 1)
        sent = [card['id'] for call in evaluate.call_args_list for card in call.args[2]]
        self.assertCountEqual(sent, result['pool_ids'])
        self.assertEqual(len(sent), len(rows))
        self.assertFalse(result['degraded'])
        self.assertEqual(result['fallback_ids'], [])
        self.assertEqual(len(result['packages']), evaluate.call_count)
        config = jev_client.load_config(self.vault)
        versions = {'memory:' + row['memory_id']: hafiza.statement_hash(str(row)) for row in rows}
        for call in evaluate.call_args_list:
            cards = call.args[2]
            self.assertEqual(cards[0]['scope'], 'user')
            self.assertEqual(cards[0]['conditions'], 'Only for this writing style')
            self.assertEqual(call.kwargs['purpose'], 'retrieval_rerank')
            self.assertIs(call.kwargs['state'], state)
            self.assertEqual(call.kwargs['source_versions'], {card['id']: versions[card['id']] for card in cards})
            body = jev_retrieval._rerank_body(config, call.args[1], call.kwargs['facets'], cards, state)
            self.assertLessEqual(len(json.dumps(body, ensure_ascii=False)), config['max_input_chars'])

    def test_candidate_and_question_limits_bound_packages(self):
        rows = self.memory_rows(8)
        for candidates, questions, sizes in ((3, 96, [3, 3, 2]), (32, 2, [2, 2, 2, 2]),
                                              (3, 2, [2, 2, 2, 2])):
            with self.subTest(candidates=candidates, questions=questions):
                self.config(max_candidates=candidates, max_questions=questions)
                _, _, result, evaluate = self.rerank_rows(rows)
                self.assertEqual([package['size'] for package in result['packages']], sizes)
                self.assertEqual(evaluate.call_count, len(sizes))
                self.assertCountEqual([card['id'] for call in evaluate.call_args_list for card in call.args[2]],
                                      result['pool_ids'])

    def test_multi_facet_packages_respect_question_budget(self):
        config = dict(jev_client.DEFAULTS, max_questions=5)
        cards = [dict(id=f'memory:m{i}', title='Yazı', statement='Kısa yazı', scope='user', domains=[])
                 for i in range(7)]
        facets = ['Writing', 'Style']
        state = dict(previous_user='Önceki istek')
        packages, oversized = jev_retrieval._rerank_packages(config, 'Writing style', facets, cards, state)
        self.assertEqual([len(package) for package in packages], [2, 2, 2, 1])
        self.assertEqual([card for package in packages for card in package], cards)
        self.assertEqual(oversized, [])
        body = jev_retrieval._rerank_body(config, 'Writing style', facets, packages[0], state)
        self.assertEqual(body, dict(model=config['model'], state=dict(query='Writing style', facets=facets,
                              candidates=cards[:2], **state), questions={
                              f'f{j}_c{i}': jev_client._question('retrieval_rerank', i, j)
                              for j in range(2) for i in range(2)}))

    def test_character_budget_boundary_is_inclusive(self):
        config = dict(jev_client.DEFAULTS)
        cards = [dict(id=f'memory:m{i}', title='Yazı', statement='Ölçülü yazı', scope='user', domains=[])
                 for i in range(2)]
        body = jev_retrieval._rerank_body(config, 'Yazı', ['Yazı'], cards, {})
        config['max_input_chars'] = len(json.dumps(body, ensure_ascii=False))
        self.assertEqual(jev_retrieval._rerank_packages(config, 'Yazı', ['Yazı'], cards, {}), ([cards], []))
        config['max_input_chars'] -= 1
        self.assertEqual(jev_retrieval._rerank_packages(config, 'Yazı', ['Yazı'], cards, {}),
                         ([[cards[0]], [cards[1]]], []))

    def test_degraded_package_uses_full_pool_local_ranking_without_retry(self):
        self.config(max_candidates=3)
        rows = self.memory_rows(6)
        for row, statement in zip(rows, ['Writing', 'Writing style', 'Cooking', 'Implicit preference', 'Other', 'Unrelated']):
            row['statement'] = statement
        def answer(vault, query, cards, **kwargs):
            result = self.high_answer(vault, query, cards, **kwargs)
            if cards[0]['id'] == 'memory:m0':
                return dict(result, degraded=True, diagnostics=['request_failed'], request_hash='failed')
            result['distributions']['memory:m4']['2'] = .1
            result['distributions']['memory:m5']['2'] = .1
            return dict(result, request_hash='successful')
        with patch.object(gorev_baglam, 'rank_records', wraps=gorev_baglam.rank_records) as rank:
            selected, _, result, evaluate = self.rerank_rows(rows, answer)
        rank.assert_called_once_with(rows, 'Writing style')
        self.assertEqual([row['memory_id'] for row in selected], ['m3', 'm1', 'm0'])
        self.assertEqual(result['proposed_ids'], ['memory:m3', 'memory:m1', 'memory:m0'])
        self.assertEqual(result['fallback_ids'], ['memory:m0', 'memory:m1', 'memory:m2'])
        self.assertEqual(result['diagnostics'], ['request_failed', 'package_fallback'])
        self.assertEqual(result['request_hash'], 'successful')
        self.assertEqual(result['requested_mode'], 'rerank')
        self.assertEqual(result['effective_mode'], 'rerank')
        self.assertFalse(result['degraded'])
        self.assertEqual(evaluate.call_count, 2)
        self.assertEqual(result['packages'], [dict(size=3, degraded=True, diagnostics=['request_failed']),
                                              dict(size=3, degraded=False, diagnostics=[])])

    def test_all_packages_degraded_returns_full_local_fallback(self):
        self.config(max_candidates=2)
        rows = self.memory_rows(5)
        def answer(*args, **kwargs):
            return dict(degraded=True, diagnostics=['deadline_exceeded'], scores={})
        selected, knowledge, result, evaluate = self.rerank_rows(rows, answer)
        self.assertIsNone(selected)
        self.assertIsNone(knowledge)
        self.assertTrue(result['degraded'])
        self.assertEqual(result['diagnostics'], ['deadline_exceeded'])
        self.assertEqual(evaluate.call_count, 3)
        self.assertEqual(result['fallback_ids'], result['pool_ids'])
        self.assertEqual(len(result['pool_ids']), 5)
        self.assertTrue(all(package['degraded'] for package in result['packages']))

    def test_oversized_candidate_falls_back_without_being_sent(self):
        self.config(max_input_chars=2000)
        rows = self.memory_rows(3)
        rows[1]['statement'] += ' x' * 2000
        selected, _, result, evaluate = self.rerank_rows(rows)
        self.assertEqual([row['memory_id'] for row in selected], ['m0', 'm2', 'm1'])
        self.assertEqual(result['pool_ids'], ['memory:m0', 'memory:m1', 'memory:m2'])
        self.assertEqual(result['fallback_ids'], ['memory:m1'])
        self.assertCountEqual([card['id'] for call in evaluate.call_args_list for card in call.args[2]],
                              ['memory:m0', 'memory:m2'])
        self.assertEqual(result['diagnostics'], ['budget_exceeded', 'package_fallback'])
        self.assertFalse(result['degraded'])

    def test_no_candidate_fits_budget_returns_degraded(self):
        self.config(max_input_chars=1)
        selected, knowledge, result, evaluate = self.rerank_rows(self.memory_rows(3))
        evaluate.assert_not_called()
        self.assertIsNone(selected)
        self.assertIsNone(knowledge)
        self.assertTrue(result['degraded'])
        self.assertEqual(result['diagnostics'], ['budget_exceeded'])
        self.assertEqual(result['packages'], [])
        self.assertEqual(result['fallback_ids'], result['pool_ids'])
        self.assertEqual(len(result['pool_ids']), 3)

    def test_parallel_packages_share_evaluation_deadline(self):
        self.config(max_candidates=1)
        rows = self.memory_rows(4)
        barrier = threading.Barrier(3, timeout=5)
        caller_thread = threading.get_ident()
        def answer(vault, query, cards, **kwargs):
            self.assertNotEqual(threading.get_ident(), caller_thread)
            self.assertEqual(jev_client._CONTEXT.get()['deadline'], context['deadline'])
            self.assertEqual(jev_client._CONTEXT.get()['vault'], context['vault'])
            if cards[0]['id'] != 'memory:m3': barrier.wait()
            return self.high_answer(vault, query, cards, **kwargs)
        with jev_client.evaluation_context(self.vault):
            context = dict(jev_client._CONTEXT.get())
            _, _, result, evaluate = self.rerank_rows(rows, answer)
        self.assertEqual(evaluate.call_count, 4)
        self.assertFalse(result['degraded'])

    def test_package_metadata_is_merged_in_pool_order(self):
        self.config(max_candidates=1)
        rows = self.memory_rows(3)
        for all_cached in (True, False):
            with self.subTest(all_cached=all_cached):
                def answer(vault, query, cards, **kwargs):
                    index = int(cards[0]['id'][-1])
                    result = self.high_answer(vault, query, cards, **kwargs)
                    return dict(result, facet_scores={0: dict(result['scores'])},
                                diagnostics=['shared', f'package_{index}', 'shared'],
                                usage=dict(input_tokens=index + 1, output_tokens=2 * (index + 1)),
                                latency_ms=[10, 30, 20][index], cache_hit=all_cached or index != 1,
                                request_hash=f'hash_{index}')
                _, _, result, _ = self.rerank_rows(rows, answer)
                expected_scores = {f'memory:m{i}': 2 for i in range(3)}
                self.assertEqual(result['scores'], expected_scores)
                self.assertEqual(set(result['distributions']), set(expected_scores))
                self.assertEqual(result['facet_scores'], {0: expected_scores})
                self.assertEqual(result['usage'], dict(input_tokens=6, output_tokens=12))
                self.assertEqual(result['latency_ms'], 30)
                self.assertEqual(result['cache_hit'], all_cached)
                self.assertEqual(result['request_hash'], 'hash_0')
                self.assertEqual(result['diagnostics'], ['shared', 'package_0', 'package_1', 'package_2'])

    def test_degraded_package_usage_and_latency_are_retained(self):
        self.config(max_candidates=1)
        def answer(vault, query, cards, **kwargs):
            result = self.high_answer(vault, query, cards, **kwargs)
            if cards[0]['id'] == 'memory:m0':
                return dict(result, degraded=True, usage=dict(input_tokens=5), latency_ms=50,
                            diagnostics=['answers_invalid'], cache_hit=False)
            return dict(result, usage=dict(input_tokens=2, output_tokens=3), latency_ms=10, cache_hit=True)
        _, _, result, _ = self.rerank_rows(self.memory_rows(2), answer)
        self.assertEqual(result['usage'], dict(input_tokens=7, output_tokens=3))
        self.assertEqual(result['latency_ms'], 50)
        self.assertFalse(result['cache_hit'])
        self.assertEqual(result['scores'], {'memory:m1': 2})

    def test_source_change_in_fallback_pool_invalidates_entire_result(self):
        for oversized in (False, True):
            with self.subTest(oversized=oversized):
                self.config(max_candidates=1, max_input_chars=2000)
                rows = self.memory_rows(2)
                if oversized: rows[1]['statement'] += ' x' * 2000
                fresh = [rows[0], dict(rows[1], statement='Changed source')]
                def answer(vault, query, cards, **kwargs):
                    result = self.high_answer(vault, query, cards, **kwargs)
                    if cards[0]['id'] == 'memory:m1':
                        return dict(result, degraded=True, diagnostics=['request_failed'])
                    return result
                with patch.object(hafiza, 'load_catalog', return_value=fresh), \
                     patch.object(hafiza, 'context_record_errors', return_value=[]), \
                     patch.object(jev_client, 'evaluate', side_effect=answer):
                    selected, knowledge, result = jev_retrieval.rerank(
                        self.vault, 'Writing style', rows, None, {}, 2000)
                self.assertIsNone(selected)
                self.assertIsNone(knowledge)
                self.assertTrue(result['degraded'])
                self.assertIn('source_changed_during_evaluation', result['diagnostics'])
                self.assertEqual(result['pool_ids'], ['memory:m0', 'memory:m1'])
                self.assertEqual(result['fallback_ids'], ['memory:m1'])

    def test_note_fallback_preserves_budget_and_source_versions(self):
        self.config(max_candidates=1)
        (self.vault / 'bilgi').mkdir()
        rows = self.memory_rows(1)
        note = dict(id='n1', title='Writing style', statement='Writing style note', scope='user',
                    domains=['writing'], kind='preference', conditions='Only drafts',
                    sources=[dict(path='source.md', sha256='source-sha')],
                    examples=[dict(path='example.md', sha256='example-sha')])
        def answer(vault, query, cards, **kwargs):
            result = self.high_answer(vault, query, cards, **kwargs)
            if cards[0]['id'] == 'note:n1':
                self.assertEqual(kwargs['source_versions'], {'note:n1': 'note-sha'})
                return dict(result, degraded=True, diagnostics=['request_failed'])
            self.assertEqual(set(kwargs['source_versions']), {'memory:m0'})
            return result
        for budget in (2000, 1):
            with self.subTest(budget=budget), \
                 patch.object(bilgi_agi, '_rows', return_value=([note], ['note-diagnostic'])), \
                 patch.object(bilgi_agi, 'note_version', return_value='note-sha'), \
                 patch.object(hafiza, 'load_catalog', return_value=rows), \
                 patch.object(hafiza, 'context_record_errors', return_value=[]), \
                 patch.object(jev_client, 'evaluate', side_effect=answer) as evaluate:
                selected, knowledge, result = jev_retrieval.rerank(
                    self.vault, 'Writing style', rows, None, {}, budget)
            self.assertEqual(selected, rows)
            self.assertEqual(evaluate.call_count, 2)
            self.assertEqual(result['pool_ids'], ['memory:m0', 'note:n1'])
            self.assertEqual(result['proposed_ids'], ['memory:m0', 'note:n1'])
            self.assertEqual(result['fallback_ids'], ['note:n1'])
            self.assertEqual(knowledge['diagnostics'], ['note-diagnostic'])
            if budget == 1:
                self.assertEqual(knowledge['text'], '')
                self.assertEqual(knowledge['records'], [])
                self.assertEqual(knowledge['source_versions'], {})
            else:
                self.assertEqual(knowledge['records'], [note])
                self.assertIn('Koşul: Only drafts', knowledge['text'])
                self.assertEqual(knowledge['source_versions'], {'bilgi/n1.md': 'note-sha',
                                                               'source.md': 'source-sha', 'example.md': 'example-sha'})

    def test_source_change_before_evaluation_reports_pool(self):
        (self.vault / 'bilgi').mkdir()
        note = dict(id='n1', title='Writing style', statement='Writing style note', scope='user')
        with patch.object(bilgi_agi, '_rows', return_value=([note], [])), \
             patch.object(bilgi_agi, 'note_version', side_effect=ValueError('source_changed')), \
             patch.object(jev_client, 'evaluate') as evaluate:
            selected, knowledge, result = jev_retrieval.rerank(self.vault, 'Writing style', [], None, {}, 2000)
        evaluate.assert_not_called()
        self.assertIsNone(selected)
        self.assertIsNone(knowledge)
        self.assertTrue(result['degraded'])
        self.assertEqual(result['diagnostics'], ['source_changed_before_evaluation'])
        self.assertEqual(result['pool_ids'], ['note:n1'])

    def test_notes_and_catalog_share_the_same_limit(self):
        self.config(rerank_limit=2)
        (self.vault / 'bilgi').mkdir()
        memory = dict(memory_id='m1', subject_key='writing', statement='Writing style preference',
                      scope='user', source_path='m1.md')
        note = dict(id='n1', title='Writing guidance', statement='Writing style note',
                    scope='user', domains=['writing'], kind='preference',
                    conditions='Only for drafts', rationale='Reviewed example', exceptions='None', sources=[])
        def answer(vault, query, cards, **kwargs):
            self.assertEqual(next(c for c in cards if c['id'] == 'note:n1')['conditions'], 'Only for drafts')
            return dict(scores={card['id']: 2 for card in cards}, distributions={card['id']:{'0':0,'1':0,'2':1} for card in cards}, degraded=False, diagnostics=[])
        with patch.object(bilgi_agi, '_rows', return_value=([note], [])), \
             patch.object(bilgi_agi, 'note_version', return_value='note-sha'), \
             patch.object(hafiza, 'load_catalog', return_value=[memory]), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(jev_client, 'evaluate', side_effect=answer):
            catalog, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Writing style', [memory], None, {}, 2000)
        self.assertEqual(len(catalog) + len(knowledge['records']), 2)
        self.assertEqual(knowledge['records'][0]['id'], 'n1')
        self.assertEqual(len(result['proposed_ids']), 2)

    def test_no_eligible_candidates_stays_empty_without_rank_call(self):
        with patch.object(jev_client, 'evaluate') as evaluate:
            catalog, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Recall a missing preference', [], None, {}, 2000)
        evaluate.assert_not_called()
        self.assertEqual(catalog, [])
        self.assertEqual(knowledge['text'], '')
        self.assertFalse(result['degraded'])
        self.assertEqual(result['pool_ids'], [])
        self.assertEqual(result['packages'], [])
        self.assertEqual(result['fallback_ids'], [])

    def test_p2_threshold_excludes_high_expected_score(self):
        self.config(rerank_p2=.75)
        row=dict(memory_id='m1',subject_key='style',statement='Writing style',scope='user',source_path='m1.md')
        def answer(*args,**kwargs):
            return dict(scores={'memory:m1':1.6},distributions={'memory:m1':{'0':0,'1':.4,'2':.6}},degraded=False,diagnostics=[])
        with patch.object(bilgi_agi,'_rows',return_value=([],[])), \
             patch.object(hafiza,'load_catalog',return_value=[row]), \
             patch.object(hafiza,'context_record_errors',return_value=[]), \
             patch.object(jev_client,'evaluate',side_effect=answer):
            selected,_,_=jev_retrieval.rerank(self.vault,'Writing style',[row],None,{},2000)
        self.assertEqual(selected,[])


if __name__ == '__main__':
    unittest.main()
