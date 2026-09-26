"""Synthetic collection and scoring; no private transcripts or catalog data."""
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import erisim_olc as measure


class AccessMeasure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.claude = self.root / 'claude' / 'project'
        self.claude.mkdir(parents=True)
        self.codex = self.root / 'codex' / '2026' / '09'
        self.codex.mkdir(parents=True)
        self.now = datetime(2026, 9, 24, tzinfo=timezone.utc)

    def write_rows(self, path, rows):
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')

    def evaluate_packages(self, labels, packages, *, jev_mode='rerank'):
        (self.vault / 'zihin').mkdir(exist_ok=True)
        (self.vault / 'bilgi').mkdir(exist_ok=True)
        self.write_rows(self.vault / 'zihin/hafıza-kataloğu.jsonl',
                        [dict(memory_id=ident, status='active') for ident in ('m1', 'm2')])
        (self.vault / 'bilgi/n1.md').write_text('synthetic', encoding='utf-8')
        self.write_rows(self.root / 'set.jsonl',
                        [dict(id=label['id'], client='codex', prompt='Synthetic task') for label in labels])
        self.write_rows(self.root / 'labels.jsonl', labels)
        with patch.object(measure.gorev_baglam, 'build_task_package', side_effect=packages):
            return measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                    self.root, jev_mode=jev_mode)

    def test_collect_balances_genuine_prompts_and_filters_private_worker(self):
        session = 'session1'
        def user(i, text):
            return dict(type='user', uuid=f'u{i}', sessionId=session, isSidechain=False,
                        timestamp='2026-09-23T12:00:00Z', cwd='/work',
                        message=dict(role='user', content=text))
        rows = [user(1, 'Please summarize the project history.'),
                user(2, '<task-notification>Background job finished.</task-notification>'),
                user(3, 'İŞÇİ KOŞUSU — otomatik işçi için test metni.'),
                user(4, 'Please summarize the project history.')]
        self.write_rows(self.claude / f'{session}.jsonl', rows)
        codex_rows = [dict(type='session_meta', payload=dict(id='codex1', source='vscode', cwd='/code')),
                      dict(type='response_item', timestamp='2026-09-23T13:00:00Z',
                           payload=dict(type='message', role='user', content=[dict(type='input_text', text='Help me update the deployment script.')]))]
        self.write_rows(self.codex / 'codex1.jsonl', codex_rows)
        out = self.root / 'set.jsonl'
        got = measure.collect(claude_root=self.claude.parent, codex_root=self.codex.parent.parent,
                              out=out, now=self.now)
        self.assertEqual([x['client'] for x in got], ['claude', 'codex'])
        self.assertEqual([x['cwd'] for x in got], ['/work', '/code'])
        self.assertEqual(len(measure._jsonl(out)), 2)

    def test_evaluate_scores_only_delivered_records_and_empty_gold(self):
        (self.vault / 'zihin').mkdir()
        (self.vault / 'bilgi').mkdir()
        self.write_rows(self.vault / 'zihin/hafıza-kataloğu.jsonl',
                        [dict(memory_id='m1', status='active'), dict(memory_id='old', status='superseded')])
        (self.vault / 'bilgi/n1.md').write_text('synthetic')
        prompts = [dict(id='a', client='claude', cwd='/tmp/project', prompt='Plan the next release.'),
                   dict(id='b', client='codex', cwd='', prompt='Explain a generic formula.')]
        labels = [dict(id='a', relevant_memory_ids=['m1'], relevant_notes=['n1']),
                  dict(id='b', relevant_memory_ids=[], relevant_notes=[])]
        self.write_rows(self.root / 'set.jsonl', prompts)
        self.write_rows(self.root / 'labels.jsonl', labels)
        packages = [dict(selected_ids=['m1', 'old'], knowledge=dict(records=[]), text='context'),
                    dict(selected_ids=[], knowledge=None, text='workflow note')]
        with patch.object(measure.gorev_baglam, 'build_task_package', side_effect=packages) as build:
            report = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl', self.root)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(build.call_args.kwargs['budget'], 2000)
        self.assertEqual((report['metrics']['tp'], report['metrics']['fp'], report['metrics']['fn']), (1, 0, 1))
        self.assertEqual(report['metrics']['certain_only']['recall'], 0.5)
        self.assertEqual(report['metrics']['empty_return_rate'], 0)
        self.assertEqual(report['metrics']['empty_memory_return_rate'], 1)
        self.assertTrue((self.root / 'erisim-degerlendirme-2026-09-24.md').exists())

    def test_evaluate_pool_coverage_separates_pool_and_delivery_losses(self):
        labels = [dict(id='lost', relevant_memory_ids=['m1'], relevant_notes=['note:n1']),
                  dict(id='miss', relevant_memory_ids=['memory:m1']),
                  dict(id='delivered', relevant_notes=['n1'], uncertain=True),
                  dict(id='unmeasured', relevant_memory_ids=['m1']),
                  dict(id='no_gold'),
                  dict(id='empty_pool', relevant_memory_ids=['m1'])]
        packages = [dict(selected_ids=['m1'], text='memory',
                         jev=dict(catalog=dict(pool_ids=['note:n1', 'memory:m2', 'memory:m1']))),
                    dict(selected_ids=[], text='', jev=dict(catalog=dict(pool_ids=['memory:m2']))),
                    dict(selected_ids=[], text='note', knowledge=dict(records=[dict(id='n1')]),
                         jev=dict(catalog=dict(pool_ids=['note:n1']))),
                    dict(selected_ids=['m1'], text='memory'),
                    dict(selected_ids=[], text='', jev=dict(catalog=dict(pool_ids=['memory:m1']))),
                    dict(selected_ids=[], text='', jev=dict(catalog=dict(pool_ids=[])))]
        report = self.evaluate_packages(labels, packages)
        self.assertEqual(report['metrics']['pool_coverage'],
                         dict(prompts=4, gold=5, in_pool=3, recall=3/5, delivered=2,
                              delivered_recall=2/5, lost_after_pool=1))
        self.assertEqual(report['metrics']['certain_only']['pool_coverage'],
                         dict(prompts=3, gold=4, in_pool=2, recall=1/2, delivered=1,
                              delivered_recall=1/4, lost_after_pool=1))
        lost, miss, delivered, unmeasured, no_gold, empty_pool = report['results']
        self.assertEqual(lost['pool_ids'], ['memory:m1', 'memory:m2', 'note:n1'])
        self.assertEqual(lost['pool_hits'], ['memory:m1', 'note:n1'])
        self.assertEqual(lost['pool_misses'], [])
        self.assertEqual(miss['pool_hits'], [])
        self.assertEqual(miss['pool_misses'], ['memory:m1'])
        self.assertEqual(delivered['pool_hits'], delivered['tp'])
        for key in ('pool_ids', 'pool_hits', 'pool_misses'):
            self.assertIsNone(unmeasured[key])
        self.assertEqual(no_gold['pool_hits'], [])
        self.assertEqual(empty_pool['pool_ids'], [])
        self.assertEqual(empty_pool['pool_misses'], ['memory:m1'])
        md = (self.root / 'erisim-degerlendirme-2026-09-24.md').read_text(encoding='utf-8')
        self.assertIn('## Havuz kapsaması', md)
        self.assertIn('Recall: 0.6; delivered_recall: 0.4; lost_after_pool: 1', md)

    def test_evaluate_degraded_pool_counts_delivery_outside_pool(self):
        labels = [dict(id='fallback', relevant_memory_ids=['m1'], relevant_notes=['n1'])]
        packages = [dict(selected_ids=['m1'], text='fallback memory',
                         jev=dict(catalog=dict(degraded=True, pool_ids=['note:n1'])))]
        report = self.evaluate_packages(labels, packages)
        self.assertEqual(report['metrics']['pool_coverage'],
                         dict(prompts=1, gold=2, in_pool=1, recall=1/2, delivered=1,
                              delivered_recall=1/2, lost_after_pool=1))
        self.assertIsNone(report['results'][0]['gate'])

    def test_evaluate_gate_false_negatives_overrides_bypass_and_degraded(self):
        labels = [dict(id='fn', needs_memory=True),
                  dict(id='override', needs_memory=True),
                  dict(id='bypass', needs_memory=True),
                  dict(id='fallback', needs_memory=True),
                  dict(id='gate_degraded', needs_memory=True),
                  dict(id='not_needed', needs_memory=False, relevant_memory_ids=['m1']),
                  dict(id='yes', relevant_memory_ids=['m1']),
                  dict(id='abstain', relevant_notes=['n1'], uncertain=True)]
        evaluations = [dict(gate=dict(needed=False, effective_needed=False)),
                       dict(gate=dict(needed=False, effective_needed=True, diagnostics=['lexical_override'])),
                       dict(gate=dict(needed=True, effective_needed=True, diagnostics=['explicit_recall_bypass'])),
                       dict(rerank=dict(needed=False, effective_needed=False, degraded=True)),
                       dict(gate=dict(needed=False, degraded=True)),
                       dict(gate=dict(needed=True)),
                       dict(gate=dict(needed=True)),
                       dict(gate=dict(needed=False, diagnostics=['abstain']))]
        packages = [dict(selected_ids=[], text='', jev=evaluation) for evaluation in evaluations]
        report = self.evaluate_packages(labels, packages)
        self.assertEqual(report['metrics']['gate_false_negative'],
                         dict(labeled_needed=7, evaluated=4, jev_no=3, jev_rate=3/4,
                              effective_no=2, effective_rate=1/2, overrides=1, bypass=1, degraded=2,
                              labeled_not_needed=1, jev_yes_on_not_needed=1))
        self.assertEqual(report['metrics']['certain_only']['gate_false_negative'],
                         dict(labeled_needed=6, evaluated=3, jev_no=2, jev_rate=2/3,
                              effective_no=1, effective_rate=1/3, overrides=1, bypass=1, degraded=2,
                              labeled_not_needed=1, jev_yes_on_not_needed=1))
        rows = {row['id']: row for row in report['results']}
        self.assertEqual(rows['fn']['gate'],
                         dict(evaluated=True, needed=False, effective_needed=False, override=False,
                              bypass=False, abstain=False, degraded=False))
        self.assertTrue(rows['override']['gate']['override'])
        self.assertTrue(rows['override']['gate']['effective_needed'])
        for ident in ('bypass', 'fallback', 'gate_degraded'):
            self.assertFalse(rows[ident]['gate']['evaluated'])
        self.assertTrue(rows['bypass']['gate']['bypass'])
        self.assertTrue(rows['fallback']['gate']['degraded'])
        self.assertFalse(rows['not_needed']['needs_memory'])
        self.assertTrue(rows['yes']['needs_memory'])
        self.assertTrue(rows['yes']['gate']['effective_needed'])
        self.assertTrue(rows['abstain']['needs_memory'])
        self.assertTrue(rows['abstain']['gate']['abstain'])
        self.assertFalse(rows['abstain']['gate']['effective_needed'])
        md = (self.root / 'erisim-degerlendirme-2026-09-24.md').read_text(encoding='utf-8')
        self.assertIn('## Kapı yanlış negatifi', md)
        self.assertIn('Jev yanlış negatif oranı: 0.75; etkili yanlış negatif oranı: 0.5', md)

    def test_evaluate_gate_false_positives_exclude_unmeasured_decisions(self):
        labels = [dict(id=ident) for ident in ('yes', 'override', 'bypass', 'degraded', 'missing')]
        evaluations = [dict(gate=dict(needed=True)),
                       dict(gate=dict(needed=False, effective_needed=True, diagnostics=['lexical_override'])),
                       dict(gate=dict(needed=True, diagnostics=['explicit_recall_bypass'])),
                       dict(rerank=dict(needed=True, degraded=True)),
                       {}]
        report = self.evaluate_packages(labels, [dict(selected_ids=[], text='', jev=e) for e in evaluations])
        self.assertEqual(report['metrics']['gate_false_negative'],
                         dict(labeled_needed=0, evaluated=0, jev_no=0, jev_rate=None,
                              effective_no=0, effective_rate=None, overrides=0, bypass=0, degraded=0,
                              labeled_not_needed=5, jev_yes_on_not_needed=1))
        self.assertTrue(all(not row['needs_memory'] for row in report['results']))

    def test_evaluate_rejects_non_bool_needs_memory(self):
        for value in (None, 0, 1, 'false', [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'needs_memory must be a bool: invalid'):
                self.evaluate_packages([dict(id='invalid', needs_memory=value)], [])

    def test_evaluate_without_rerank_diagnostics_leaves_metrics_unmeasured(self):
        labels = [dict(id='needed', relevant_memory_ids=['m1']), dict(id='not_needed')]
        packages = [dict(selected_ids=[], text=''), dict(selected_ids=[], text='')]
        empty_pool = dict(prompts=0, gold=0, in_pool=0, recall=None, delivered=0,
                          delivered_recall=None, lost_after_pool=0)
        empty_gate = dict(labeled_needed=1, evaluated=0, jev_no=0, jev_rate=None,
                          effective_no=0, effective_rate=None, overrides=0, bypass=0, degraded=0,
                          labeled_not_needed=1, jev_yes_on_not_needed=0)
        for mode in ('local', 'assist', 'on', 'rerank'):
            with self.subTest(mode=mode):
                report = self.evaluate_packages(labels, packages, jev_mode=mode)
                for metrics in (report['metrics'], report['metrics']['certain_only']):
                    self.assertEqual(metrics['pool_coverage'], empty_pool)
                    self.assertEqual(metrics['gate_false_negative'], empty_gate)
                for row in report['results']:
                    self.assertIsNone(row['gate'])
                    self.assertIsNone(row['pool_ids'])
                md = (self.root / 'erisim-degerlendirme-2026-09-24.md').read_text(encoding='utf-8')
                self.assertIn('## Havuz kapsaması\n\nhavuz ölçülmedi (rerank modu değil)', md)
                self.assertIn('## Kapı yanlış negatifi\n\nkapı ölçülmedi', md)

    def test_seeded_halves_are_disjoint(self):
        (self.vault / 'zihin').mkdir()
        (self.vault / 'bilgi').mkdir()
        (self.vault / 'zihin/hafıza-kataloğu.jsonl').write_text('')
        prompts = [dict(id=str(i), client='codex', cwd='', prompt='A synthetic task') for i in range(6)]
        labels = [dict(id=str(i), relevant_memory_ids=[], relevant_notes=[]) for i in range(6)]
        self.write_rows(self.root / 'set.jsonl', prompts)
        self.write_rows(self.root / 'labels.jsonl', labels)
        package = dict(selected_ids=[], knowledge=None, text='')
        with patch.object(measure.gorev_baglam, 'build_task_package', return_value=package):
            first = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                     self.root, split_seed=7, split_half='first', write=False)
            second = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                      self.root, split_seed=7, split_half='second', write=False)
        self.assertEqual({r['id'] for r in first['results']} & {r['id'] for r in second['results']}, set())
        self.assertEqual(len(first['results']) + len(second['results']), 6)

    def test_short_collection_and_prefixed_v2_labels(self):
        self.assertFalse(measure._valid('Devam'))
        self.assertTrue(measure._valid('Devam', include_short=True))
        (self.vault/'zihin').mkdir(); (self.vault/'bilgi').mkdir()
        self.write_rows(self.vault/'zihin/hafıza-kataloğu.jsonl',[dict(memory_id='m1',status='active')])
        (self.vault/'bilgi/n1.md').write_text('synthetic')
        self.write_rows(self.root/'set.jsonl',[dict(id='a',client='claude',cwd='',prompt='Devam',previous_user='Synthetic planning request')])
        self.write_rows(self.root/'labels.jsonl',[dict(id='a',relevant_memory_ids=['memory:m1'],relevant_notes=['note:n1'])])
        package=dict(text='memory\nnote\nprocedure\nproject',selected_ids=['m1','knowledge','procedure-reading','p1'],project_id='p1',
                     summary={'task_ids':[]},knowledge={'records':[{'id':'n1'}]},
                     delivered_segments={'m1':'memory','knowledge':'note','procedure-reading':'procedure','p1':'project'})
        with patch.object(measure.gorev_baglam,'build_task_package',return_value=package) as build:
            report=measure.evaluate(self.vault,self.root/'set.jsonl',self.root/'labels.jsonl',self.root,write=False)
        self.assertEqual(build.call_args.kwargs['previous_user'],'Synthetic planning request')
        self.assertEqual(report['metrics']['tp'],2)
        self.assertEqual(report['metrics']['requested_mode_counts'],{'local':1})
        self.assertEqual(report['metrics']['effective_mode_counts'],{'local':1})
        self.assertEqual(report['metrics']['channel_chars'],{'catalog':6,'note':4,'procedure':9,'project':7,'other':0})


if __name__ == '__main__':
    unittest.main()
