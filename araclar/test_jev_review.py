import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bilgi_agi as b
import jev_client
import jev_review as r


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        (self.v / 'komuta').mkdir()
        (self.v / 'komuta/jev.json').write_text(json.dumps({'mode':'on'}))
        self.quote = 'Sunumda kısa cümle kullan.'
        self.source = self.v / 'source.md'
        self.source.write_text('SURROUNDING_NOT_FOR_EXPORT\n' + self.quote + '\nUNRELATED_PRIVATE_CONTEXT')
        self.row = dict(id='anchor', title='Anlatım', statement=self.quote, kind='preference',
                        scope='user', domains=['sunum'], status='reviewed',
                        sources=[dict(path='source.md', sha256=b.digest(self.source), evidence=self.quote)],
                        reviewed_by='test', review_note='Doğrudan alıntı incelendi.')
        self.add()

    def add(self, **kw):
        row = copy.deepcopy(self.row)
        row.update(kw)
        b.register(self.v, row, True)

    def response(self, cards, facets, values=None):
        values = values or [2, 0]
        return dict(mode='on', degraded=False, diagnostics=[], scores={},
                    facet_scores={i:{c['id']:values[i] for c in cards} for i in range(len(facets))})

    def fake(self, vault, query, cards, **kw):
        values = [0, 0, 2] if kw['purpose'] == 'memory_review' else [2, 0]
        return self.response(cards, kw['facets'], values)

    def snapshot(self):
        return {str(p.relative_to(self.v)):p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

    def test_exact_evidence_only_and_no_canonical_writes(self):
        before = self.snapshot()
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as call:
            result = r.audit(self.v)
        payload = json.dumps(call.call_args.args, ensure_ascii=False, default=str)
        self.assertIn(self.quote, payload)
        self.assertNotIn('SURROUNDING_NOT_FOR_EXPORT', payload)
        self.assertNotIn('UNRELATED_PRIVATE_CONTEXT', payload)
        self.assertEqual(result['support_checks'][0]['verdict'], 'supported')
        self.assertFalse(result['canonical_writes'])
        self.assertEqual(before, self.snapshot())

    def test_status_scope_and_stale_excluded_before_send(self):
        self.add(id='proposal', status='proposed')
        self.add(id='other', scope='project:other')
        self.add(id='stale')
        path = self.v / 'bilgi/stale.md'
        path.write_text(path.read_text() + 'unreviewed modification')
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as call:
            r.audit(self.v, project_id='current')
        self.assertEqual([c['id'] for c in call.call_args.args[2]], ['anchor'])
        with self.assertRaises(ValueError):
            r.audit(self.v, card_ids=['proposal'])

    def test_support_insufficient_contradicted_and_ambiguous(self):
        for values, expected in [([2,0],'supported'), ([0,0],'insufficient'),
                                 ([0,2],'contradicted'), ([2,2],'uncertain')]:
            with self.subTest(expected=expected):
                def answer(vault, query, cards, **kw):
                    return self.response(cards, kw['facets'], values)
                with patch.object(jev_client, 'evaluate', side_effect=answer):
                    result = r.audit(self.v)
                self.assertEqual(result['support_checks'][0]['verdict'], expected)
                self.assertTrue(result['requires_review'])

    def test_relation_direction_and_multiple_highs_ambiguous(self):
        self.add(id='candidate', statement='Teknik sunumda kısa cümle kullan.')
        for scores, expected in [([0,0,2], 'narrows'), ([2,2,0], 'uncertain'), ([0,0,0], 'uncertain')]:
            def answer(vault, query, cards, **kw):
                return self.response(cards, kw['facets'], scores if kw['purpose']=='memory_review' else [2,0])
            with self.subTest(expected=expected), patch.object(jev_client, 'evaluate', side_effect=answer):
                result = r.audit(self.v, card_ids=['candidate'], anchor_id='anchor')
            relation = result['relation_candidates'][0]
            self.assertEqual((relation['source_id'],relation['target_id']), ('candidate','anchor'))
            self.assertEqual(relation['relation'], expected)
            self.assertEqual(relation['status'], 'proposed')

    def test_cross_domain_and_scope_pairs_not_sent(self):
        self.add(id='cover', domains=['thumbnail'])
        self.add(id='project', scope='project:current')
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as call:
            result = r.audit(self.v, project_id='current', anchor_id='anchor')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['relation_candidates'], [])

    def test_source_mutation_between_calls_clears_all_scores(self):
        self.add(id='candidate')
        def answer(vault, query, cards, **kw):
            result = self.fake(vault, query, cards, **kw)
            if kw['purpose'] == 'evidence_review':
                self.source.write_text('changed source')
            return result
        with patch.object(jev_client, 'evaluate', side_effect=answer):
            result = r.audit(self.v, anchor_id='anchor')
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(result['support_checks'])
        self.assertFalse(result['relation_candidates'])
        self.assertFalse(result['source_versions'])
        for evaluation in result['evaluations'].values():
            self.assertFalse(evaluation['facet_scores'])

    def test_disabled_does_not_call_transport(self):
        (self.v / 'komuta/jev.json').write_text(json.dumps({'mode':'off'}))
        self.add(id='candidate')
        with patch.object(jev_client, '_transport') as transport:
            result = r.audit(self.v, anchor_id='anchor')
        transport.assert_not_called()
        self.assertEqual(result['status'], 'disabled')
        self.assertFalse(result['support_checks'])
        self.assertFalse(result['relation_candidates'])

    def test_service_failure_not_insufficient_evidence(self):
        with patch.object(jev_client, 'evaluate', return_value=dict(mode='on', degraded=True,
                          diagnostics=['request_failed'], scores={}, facet_scores={})):
            result = r.audit(self.v)
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(result['support_checks'])
        self.assertIn('request_failed', result['diagnostics'])

    def test_failed_support_skips_relation_cost(self):
        self.add(id='candidate')
        with patch.object(jev_client, 'evaluate', return_value=dict(mode='on', degraded=True,
                          diagnostics=['request_failed'], scores={}, facet_scores={})) as call:
            result = r.audit(self.v, anchor_id='anchor')
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(result['relation_candidates'])

    def test_invalid_config_is_degraded_not_disabled(self):
        (self.v / 'komuta/jev.json').write_text('{bad')
        result = r.audit(self.v)
        self.assertEqual(result['status'], 'degraded')
        self.assertIn('config_invalid', result['diagnostics'])


if __name__ == '__main__':
    unittest.main()
