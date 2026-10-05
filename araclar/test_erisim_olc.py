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
        clock = patch.object(measure, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = self.now

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

    def test_assist_hints_are_measured_only_when_delivered_and_never_as_claims(self):
        labels = [dict(id='delivered', relevant_memory_ids=['m1'], relevant_notes=['n1']),
                  dict(id='omitted', relevant_memory_ids=['m1'], relevant_notes=['n1'])]
        packages = [dict(selected_ids=['m2', 'jev-reading:m1', 'knowledge'], text='claim and hints',
                         delivered_segments={'m2': 'claim', 'jev-reading:m1': 'catalog hint', 'knowledge': 'note hint'},
                         knowledge=dict(records=[], suggested_ids=['n1', 'unknown']),
                         jev=dict(catalog=dict(suggested_ids=['m1']), knowledge=dict(suggested_ids=['n1']))),
                    dict(selected_ids=[], text='',
                         delivered_segments={'jev-reading:m1': 'stale hint', 'knowledge': 'stale hint'},
                         knowledge=dict(records=[], suggested_ids=['n1']),
                         jev=dict(catalog=dict(suggested_ids=['m1']), knowledge=dict(suggested_ids=['n1'])))]
        report = self.evaluate_packages(labels, packages, jev_mode='assist')
        self.assertEqual((report['metrics']['tp'], report['metrics']['fp'], report['metrics']['fn']), (0, 1, 4))
        self.assertEqual(report['results'][0]['reading_candidates'], ['memory:m1', 'note:n1'])
        self.assertEqual(report['results'][1]['reading_candidates'], [])
        self.assertEqual(report['results'][1]['suggested'], ['memory:m1', 'note:n1'])
        expected = dict(prompts=1, candidates=2, gold_hits=2, non_gold=0,
                        additional_gold=2, delivered_or_hint_recall=0.5)
        self.assertEqual(report['metrics']['reading_candidates'], expected)
        self.assertEqual(report['metrics']['certain_only']['reading_candidates'], expected)
        md = (self.root / 'erisim-degerlendirme-2026-09-24.md').read_text(encoding='utf-8')
        for heading in ('## Jev okuma önerileri', '## Okuma adayları', '## Önbellek gözlemleri'):
            self.assertIn(heading, md)

    def test_reading_metrics_do_not_double_count_delivered_claims(self):
        metrics = measure._reading_metrics([dict(tp=['memory:m1'], fn=['note:n1'],
                          reading_candidates=['memory:m1', 'memory:m2'],
                          reading_candidate_hits=['memory:m1'])])
        self.assertEqual(metrics, dict(prompts=1, candidates=2, gold_hits=1, non_gold=1,
                                       additional_gold=0, delivered_or_hint_recall=0.5))

    def test_cache_reports_prompt_observations_without_inventing_request_counts(self):
        labels = [dict(id=ident) for ident in ('mixed', 'uncached', 'unmeasured')]
        packages = [dict(selected_ids=[], text='', jev=dict(
                        catalog=dict(cache_hit=True, cache_lookup=True),
                        knowledge=dict(cache_hit=False, packages=[
                            dict(cache_lookup=True, cache_hit=True), dict(cache_lookup=True, cache_hit=False)]))),
                    dict(selected_ids=[], text='', jev=dict(gate=dict(cache_hit=False, cache_lookup=True))),
                    dict(selected_ids=[], text='', jev=dict(catalog=dict(cache_hit=False, degraded=True)))]
        report = self.evaluate_packages(labels, packages)
        self.assertEqual(report['metrics']['cache'],
                         dict(prompts_observed=2, prompts_with_hits=1, prompts_with_misses=2))
        self.assertEqual(report['results'][0]['cache_observations'],
                         dict(catalog='hit', knowledge='not_all_hit'))
        self.assertEqual(report['results'][2]['cache_observations'], {})
        self.assertEqual(report['metrics']['live_requests'], 0)

    def test_unqueried_subpackages_are_not_cache_misses(self):
        labels = [dict(id=ident) for ident in ('unqueried', 'partial_hit', 'partial_miss')]
        skipped = dict(cache_lookup=False, cache_hit=False, request_hash='assigned',
                       degraded=True, diagnostics=['capacity_exceeded'])
        evaluations = [dict(cache_hit=False, packages=[skipped, dict(diagnostics=['private_input'])]),
                       dict(cache_hit=False, packages=[skipped, dict(cache_lookup=True, cache_hit=True)]),
                       dict(cache_hit=False, packages=[skipped, dict(cache_lookup=True, cache_hit=False)])]
        report = self.evaluate_packages(labels, [dict(selected_ids=[], text='', jev=dict(catalog=e))
                                                for e in evaluations])
        self.assertEqual([r['cache_observations'] for r in report['results']],
                         [{}, dict(catalog='all_hit'), dict(catalog='not_all_hit')])
        self.assertEqual(report['metrics']['cache'],
                         dict(prompts_observed=2, prompts_with_hits=1, prompts_with_misses=1))

    def test_real_unqueried_multi_package_does_not_report_cache_miss(self):
        import jev_retrieval
        cards = self.client_fixture()
        cards.append(dict(cards[0], id='two'))
        (self.vault / 'komuta/jev.json').write_text(
            json.dumps(dict(mode='shadow', max_candidates=1)), encoding='utf-8')
        for query, rejection in (('Bunu kaydetme', None), ('Synthetic task', 'capacity_exceeded')):
            with self.subTest(query=query), patch.object(measure.jev_client, '_cache_path') as lookup:
                if rejection:
                    with patch('jev_runtime.run', side_effect=ValueError(rejection)):
                        evaluation = jev_retrieval.packaged_evaluate(self.vault, query, cards, facets=[query])
                else:
                    evaluation = jev_retrieval.packaged_evaluate(self.vault, query, cards, facets=[query])
                self.assertEqual(len(evaluation['packages']), 2)
                self.assertTrue(evaluation['degraded'])
                lookup.assert_not_called()
                report = self.evaluate_packages([dict(id='unqueried')],
                                                [dict(selected_ids=[], text='', jev=dict(catalog=evaluation))])
                self.assertEqual(report['results'][0]['cache_observations'], {})
                self.assertEqual(report['metrics']['cache']['prompts_with_misses'], 0)

    def client_fixture(self):
        (self.vault / 'komuta').mkdir(exist_ok=True)
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(mode='shadow')), encoding='utf-8')
        return [dict(id='one', title='A', statement='B', scope='user', domains=['all'])]

    def test_hash_assigned_but_coordinator_rejected_is_not_cache_miss(self):
        cards = self.client_fixture()
        with patch('jev_runtime.run', side_effect=ValueError('capacity_exceeded')), \
             patch.object(measure.jev_client, '_cache_path') as lookup:
            evaluation = measure.jev_client.evaluate(self.vault, 'Synthetic task', cards)
        self.assertTrue(evaluation['request_hash'])
        self.assertFalse(evaluation['cache_lookup'])
        self.assertTrue(evaluation['degraded'])
        self.assertEqual(evaluation['diagnostics'], ['capacity_exceeded'])
        lookup.assert_not_called()
        report = self.evaluate_packages([dict(id='rejected')],
                                        [dict(selected_ids=[], text='', jev=dict(catalog=evaluation))])
        self.assertEqual(report['results'][0]['cache_observations'], {})
        self.assertEqual(report['metrics']['cache'],
                         dict(prompts_observed=0, prompts_with_hits=0, prompts_with_misses=0))

    def test_client_marks_only_actual_cache_lookups_including_failure_after_lookup(self):
        cards = self.client_fixture()
        def transport(url, body, key, timeout):
            return dict(answers={q: dict(type='score', score=1.8) for q in body['questions']})
        def failed_transport(*args):
            raise ValueError('deadline_exceeded')
        with patch.object(measure.jev_client, '_environment', return_value={'TYPESAFE_API_KEY': 'synthetic'}):
            cold = measure.jev_client.evaluate(self.vault, 'Synthetic task', cards, transport=transport)
            warm = measure.jev_client.evaluate(self.vault, 'Synthetic task', cards, transport=transport)
            failed = measure.jev_client.evaluate(self.vault, 'Another task', cards,
                                                 transport=failed_transport)
        self.assertTrue(cold['cache_lookup'])
        self.assertFalse(cold['cache_hit'])
        self.assertFalse(cold['degraded'])
        self.assertTrue(warm['cache_lookup'])
        self.assertTrue(warm['cache_hit'])
        self.assertTrue(failed['cache_lookup'])
        self.assertTrue(failed['degraded'])
        self.assertEqual(measure._cache_observations(dict(catalog=failed)), dict(catalog='miss'))
        with patch.object(measure.jev_client, '_cache_path') as lookup:
            private = measure.jev_client.evaluate(self.vault, 'Bunu kaydetme', cards)
        self.assertIn('private_input', private['diagnostics'])
        self.assertFalse(private['cache_lookup'])
        lookup.assert_not_called()

    def test_report_uses_run_date_and_fingerprints_inputs(self):
        self.clock.now.return_value = datetime(2027, 2, 3, 4, 5, tzinfo=timezone.utc)
        report = self.evaluate_packages([dict(id='one')], [dict(selected_ids=[], text='')])
        self.assertEqual(report['generated_at'], '2027-02-03T04:05:00+00:00')
        for extension in ('md', 'json'):
            self.assertTrue((self.root / ('erisim-degerlendirme-2027-02-03.' + extension)).is_file())
            self.assertFalse((self.root / ('erisim-degerlendirme-2026-09-24.' + extension)).exists())
        import hashlib
        self.assertEqual(report['input_sha256']['set'], hashlib.sha256((self.root / 'set.jsonl').read_bytes()).hexdigest())
        self.assertEqual(report['input_sha256']['labels'], hashlib.sha256((self.root / 'labels.jsonl').read_bytes()).hexdigest())

    def test_report_hashes_evaluated_snapshot_and_write_false_has_no_output(self):
        self.evaluate_packages([dict(id='one')], [dict(selected_ids=[], text='')])
        set_bytes = (self.root / 'set.jsonl').read_bytes()
        label_bytes = (self.root / 'labels.jsonl').read_bytes()
        def build(*args, **kwargs):
            (self.root / 'set.jsonl').write_text('changed during evaluation', encoding='utf-8')
            (self.root / 'labels.jsonl').write_text('changed during evaluation', encoding='utf-8')
            return dict(selected_ids=[], text='')
        with patch.object(measure.gorev_baglam, 'build_task_package', side_effect=build):
            report = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                      self.root / 'not-created', write=False)
        import hashlib
        self.assertEqual(report['input_sha256']['set'], hashlib.sha256(set_bytes).hexdigest())
        self.assertEqual(report['input_sha256']['labels'], hashlib.sha256(label_bytes).hexdigest())
        self.assertFalse((self.root / 'not-created').exists())

    def test_duplicate_labels_cannot_silently_replace_reviewed_judgment(self):
        self.evaluate_packages([dict(id='one')], [dict(selected_ids=[], text='')])
        self.write_rows(self.root / 'labels.jsonl', [dict(id='one'), dict(id='one', relevant_memory_ids=['m1'])])
        with patch.object(measure.gorev_baglam, 'build_task_package') as build:
            with self.assertRaisesRegex(ValueError, 'exactly once'):
                measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl', self.root)
        build.assert_not_called()

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

    def test_assist_suggestions_diagnostics_and_live_requests_are_separate(self):
        labels = [dict(id='a', relevant_memory_ids=['m1', 'm2'], relevant_notes=['n1']), dict(id='b')]
        def package(jev, selected):
            return dict(selected_ids=selected, text='x', jev=jev)
        packages = [package(dict(catalog=dict(suggested_ids=['m2', 'unknown'], diagnostics=['quantized_probability'], degraded=False),
                                 knowledge=dict(suggested_ids=['n1'], diagnostics=[], degraded=False)), ['m1']),
                    package(dict(catalog=dict(diagnostics=['budget_exceeded'], degraded=True),
                                 knowledge=dict(suggested_ids=[], diagnostics=['assist_pool_empty'], degraded=False)), [])]
        def build(*args, **kwargs):
            measure.jev_client._transport('http://127.0.0.1:1/v1/systemone', {}, 'k', 1)
            return packages.pop(0)
        (self.vault / 'zihin').mkdir(exist_ok=True)
        (self.vault / 'bilgi').mkdir(exist_ok=True)
        self.write_rows(self.vault / 'zihin/hafıza-kataloğu.jsonl',
                        [dict(memory_id=ident, status='active') for ident in ('m1', 'm2')])
        (self.vault / 'bilgi/n1.md').write_text('synthetic', encoding='utf-8')
        self.write_rows(self.root / 'set.jsonl', [dict(id=l['id'], client='codex', prompt='Synthetic task') for l in labels])
        self.write_rows(self.root / 'labels.jsonl', labels)
        with patch.object(measure.jev_client, '_transport', return_value={}), \
             patch.object(measure.gorev_baglam, 'build_task_package', side_effect=build):
            report = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                      self.root, jev_mode='assist')
        metrics = report['metrics']
        # Suggestions are never counted as delivered TP.
        self.assertEqual((metrics['tp'], metrics['fn']), (1, 2))
        self.assertEqual(metrics['suggestions'], dict(tp=2, fp=0, precision=1.0, prompts=1, recall_with_suggestions=1.0))
        self.assertEqual(report['results'][0]['suggested'], ['memory:m2', 'note:n1'])
        self.assertEqual(metrics['degraded_count'], 1)
        self.assertEqual(metrics['degraded_diagnostics'], {'catalog:budget_exceeded': 1})
        self.assertEqual(metrics['diagnostic_counts']['knowledge:assist_pool_empty'], 1)
        self.assertEqual((metrics['live_requests'], metrics['live_request_failures']), (2, 0))

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
