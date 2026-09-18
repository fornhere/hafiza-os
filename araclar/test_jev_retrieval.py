import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bilgi_agi as b
import hafiza as h
import jev_client
import jev_retrieval as j
import konu_sentezi as k


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        (self.v / 'komuta').mkdir()
        self.source = self.v / 'source.md'
        self.source.write_text('Sunumda kısa cümle kullan; kapakta büyük yazı kullan.')
        self.record = dict(id='short', title='Kısa anlatım', kind='preference',
                           statement='Sunumda kısa cümle kullan.', scope='user',
                           domains=['sunum'], status='reviewed',
                           sources=[dict(path='source.md', sha256=b.digest(self.source),
                                         evidence=self.source.read_text())],
                           reviewed_by='test', review_note='Kaynak doğrudan incelendi.')
        self.add()

    def add(self, **changes):
        row = copy.deepcopy(self.record)
        row.update(changes)
        b.register(self.v, row, True)

    def config(self, mode):
        (self.v / 'komuta/jev.json').write_text(json.dumps({'mode': mode}))

    def high(self, vault, query, candidates, **kw):
        scores = {r['id']: 2.0 for r in candidates}
        return dict(mode=j.mode(vault), scores=scores,
                    facet_scores={i: dict(scores) for i in range(len(kw['facets']))},
                    diagnostics=[], degraded=False)

    def test_off_identical_without_evaluation(self):
        for reader, query in [(b, 'sunum'), (k, 'anlatım tercihlerimi özetle')]:
            with self.subTest(reader=reader.__name__), patch.object(jev_client, 'evaluate') as call:
                self.assertEqual(reader.retrieve(self.v, query), reader._retrieve_local(self.v, query))
                call.assert_not_called()

    def test_shadow_preserves_baseline_and_synthesis_calls_once(self):
        self.config('shadow')
        for reader, query in [(b, 'sunum'), (k, 'anlatım tercihlerimi özetle')]:
            expected = reader._retrieve_local(self.v, query)
            with self.subTest(reader=reader.__name__), patch.object(jev_client, 'evaluate', side_effect=self.high) as call:
                actual = reader.retrieve(self.v, query)
                self.assertEqual(call.call_count, 1)
                self.assertIn('jev', actual)
                self.assertEqual({key: value for key, value in actual.items() if key != 'jev'}, expected)

    def test_on_can_find_implicit_query(self):
        query = 'İzleyiciyle samimi olmak için eski geri bildirimim neydi?'
        self.assertFalse(b._retrieve_local(self.v, query)['records'])
        self.config('on')
        with patch.object(jev_client, 'evaluate', side_effect=self.high):
            result = b.retrieve(self.v, query)
        self.assertEqual([r['id'] for r in result['records']], ['short'])
        self.assertEqual(result['source_versions']['source.md'], b.digest(self.source))

    def test_compound_domain_mask_rejects_wrong_facet_high_score(self):
        self.config('on')
        with patch.object(jev_client, 'evaluate', side_effect=self.high):
            result = b.retrieve(self.v, 'sunum ve kapak tercihleri', budget=3000)
        self.assertEqual(result['jev']['coverage'], {'0': 'covered', '1': 'unresolved'})
        self.assertEqual(result['jev']['facet_scores'][1]['short'], 0)
        self.assertIn('eksikliği varsayımla doldurma', result['text'])

    def test_scope_proposed_and_stale_rows_never_sent(self):
        self.add(id='private', scope='project:other')
        self.add(id='proposed', status='proposed')
        self.add(id='stale')
        note = self.v / 'bilgi/stale.md'
        note.write_text(note.read_text() + 'manual change')
        self.config('on')
        with patch.object(jev_client, 'evaluate', side_effect=self.high) as call:
            b.retrieve(self.v, 'sunum', project_id='current')
        self.assertEqual([r['id'] for r in call.call_args.args[2]], ['short'])

    def test_changed_or_deleted_source_during_call_is_excluded(self):
        for deletion in (False, True):
            with self.subTest(deletion=deletion):
                self.source.write_text('Sunumda kısa cümle kullan; kapakta büyük yazı kullan.')
                self.config('on')
                def mutate(*args, **kw):
                    result = self.high(*args, **kw)
                    if deletion:
                        self.source.unlink()
                    else:
                        self.source.write_text('Başka kaynak sürümü')
                    return result
                with patch.object(jev_client, 'evaluate', side_effect=mutate):
                    result = b.retrieve(self.v, 'sunum')
                self.assertFalse(result['records'])
                self.assertTrue(result['jev']['degraded'])

    def test_tight_budget_reports_omission_not_false_coverage(self):
        self.config('on')
        with patch.object(jev_client, 'evaluate', side_effect=self.high):
            result = b.retrieve(self.v, 'sunum', budget=1)
        self.assertLessEqual(len(result['text']), 1)
        self.assertFalse(result['records'])
        self.assertFalse(result['source_versions'])
        self.assertEqual(result['jev']['coverage'], {'0': 'budget_exceeded'})
        self.assertEqual(result['omitted_record_ids'], ['short'])

    # Frozen before the routing fix and before any new live call. The three
    # validation failures are development regressions, not independent holdout.
    MIXED_CASES = (
        'Sözcük seçimindeki sadelik ile kapaktaki fazladan beden itirazımın kaynakları ne?',
        'Cümleleri bağlamak ve eski kapak tarzına dönmek için hangi notlarım var?',
        'Anlatımın mesafeli olmaması ile eldeki cismin küçültülmesi taleplerini ayrı ayrı bul.',
        'Sözlerin anlaşılır olması ile kapak kimliğinin korunmasına dair kaynakları ayrı ayrı getir.',
    )

    def test_mixed_explicit_implicit_candidates_and_facets(self):
        self.add(id='cover', domains=['thumbnail'], title='Kapak',statement='Kapakta büyük yazı kullan.')
        self.config('on')
        for query in self.MIXED_CASES:
            with self.subTest(query=query), patch.object(jev_client,'evaluate',side_effect=self.high) as call:
                out=b.retrieve(self.v,query,budget=3000)
                self.assertEqual({r['id'] for r in call.call_args.args[2]}, {'short','cover'})
                self.assertEqual(len(call.call_args.kwargs['facets']),2)
                self.assertEqual({r['id'] for r in out['records']},{'short','cover'})
                self.assertEqual(set(out['jev']['coverage'].values()),{'covered'})

    def test_single_domain_stays_guarded_against_wrong_domain_score(self):
        self.config('on')
        for query in ('Site için renk ve font seç.', 'Sitedeki renkler için hangi notlarım var?', 'Site için renk ve font kaynaklarını bul.'):
            with self.subTest(query=query),patch.object(jev_client,'evaluate',side_effect=self.high):
                out=b.retrieve(self.v,query,budget=3000)
                self.assertFalse(out['records'])

    def test_facets_never_silently_drop_fourth_clause(self):
        query='Sunum için notlar ve kapak için notlar ve site için notlar ve eski yöntem için kaynakları bul.'
        plan=j.facet_plan(query)
        self.assertLessEqual(len(plan),3)
        self.assertTrue(any('eski yöntem' in f['text'] for f in plan))

    def catalog_row(self):
        statement = 'Sunumda kısa cümle kullan.'
        row = dict(memory_id='workflow', kind='semantic', scope='project:workflow',
                    subject_key='sunum', statement=statement, status='active',
                    source_path='source.md', source_content_hash=h.statement_hash(self.source.read_text()),
                    source_anchor='sunum', source_hash=h.statement_hash(statement),
                    observed_at='2026-01-01', valid_from='2026-01-01', valid_to=None,
                    confidence='explicit-user', sensitivity='normal', mem0_id=None,
                    supersedes=None, reviewed_by='test', schema_version=1)
        path = self.v / h.CATALOG_PATH
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(row) + '\n')
        return row

    def test_catalog_retains_prevalidated_workflow_scope(self):
        row = self.catalog_row()
        self.assertFalse(h.context_record_errors(self.v, row))
        self.config('shadow')
        with patch.object(jev_client, 'evaluate', side_effect=self.high):
            selected, result = j.catalog(self.v, 'sunum', [row], lambda rows, query: rows, 'project:current')
        self.assertEqual(selected, [row])
        self.assertFalse(result['degraded'])

    def test_catalog_source_deleted_during_call_returns_empty_fallback(self):
        row = self.catalog_row()
        self.config('on')
        def mutate(*args, **kw):
            result = self.high(*args, **kw)
            self.source.unlink()
            return result
        with patch.object(jev_client, 'evaluate', side_effect=mutate):
            selected, result = j.catalog(self.v, 'sunum', [row], lambda rows, query: rows, 'project:current')
        self.assertEqual(selected, [])
        self.assertTrue(result['degraded'])

    def test_catalog_revoked_during_call_never_delivered(self):
        row = self.catalog_row()
        self.config('on')
        def revoke(*args, **kw):
            result = self.high(*args, **kw)
            revoked = dict(row, status='superseded')
            (self.v / h.CATALOG_PATH).write_text(json.dumps(revoked) + '\n')
            return result
        with patch.object(jev_client, 'evaluate', side_effect=revoke):
            selected, result = j.catalog(self.v, 'sunum', [row], lambda rows, query: rows, 'project:current')
        self.assertEqual(selected, [])
        self.assertTrue(result['degraded'])


if __name__ == '__main__':
    unittest.main()
