"""Offline failure-path regressions; no provider credentials or live calls."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import gelisim_dongusu as g
import jev_client
import test_gelisim_dongusu as fixtures


class SafetyTests(unittest.TestCase):
    setUp = fixtures.LoopTests.setUp
    evaluate = fixtures.LoopTests.evaluate

    def timeout(self, *args, **kwargs):
        return dict(mode='shadow', degraded=True, scores={}, diagnostics=['deadline_exceeded'])

    def report(self, result):
        return json.loads(Path(result['report']).read_text(encoding='utf-8'))

    def test_unreviewed_labels_never_reach_inference(self):
        self.c.pop('label_review', None)
        self.c['label_status'] = 'unreviewed'
        with self.assertRaisesRegex(ValueError, 'review'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_resume_rejects_config_revision(self):
        first = g.run(self.v, self.c, self.out, self.timeout)
        before = Path(first['report']).read_bytes()
        (self.v / 'komuta').mkdir()
        (self.v / 'komuta/jev.json').write_text('{"mode":"shadow"}')
        with self.assertRaisesRegex(ValueError, 'resume_revision_changed'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(Path(first['report']).read_bytes(), before)
        self.assertEqual(self.calls, 0)

    def test_resume_rejects_runner_revision(self):
        first = g.run(self.v, self.c, self.out, self.timeout)
        report = self.report(first)
        report['runner_sha256'] = '0' * 64
        g.write(first['report'], report)
        with self.assertRaisesRegex(ValueError, 'resume_revision_changed'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(self.calls, 0)

    def test_malformed_response_has_terminal_report(self):
        result = g.run(self.v, self.c, self.out, lambda *a, **k: [])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'response_invalid')
        self.assertEqual(result['calls'], 1)

    def test_negative_usage_cannot_reduce_budget(self):
        def negative(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result['usage'] = {'input_tokens': -100}
            return result
        result = g.run(self.v, self.c, self.out, negative)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'usage_invalid')
        self.assertGreaterEqual(self.report(result)['usage_tokens'], 0)
        self.assertEqual(self.calls, 1)

    def test_unknown_mode_not_a_quality_result(self):
        def bad_mode(*args, **kwargs):
            return dict(self.evaluate(*args, **kwargs), mode='surprise')
        result = g.run(self.v, self.c, self.out, bad_mode)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['shadow_candidate'])

    def test_provider_exception_text_is_not_persisted(self):
        def broken(*args, **kwargs):
            raise ValueError('private-provider-response-sentinel')
        result = g.run(self.v, self.c, self.out, broken)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('private-provider-response-sentinel', Path(result['report']).read_text())

    def test_invalid_initial_config_leaves_failed_not_started(self):
        (self.v / 'komuta').mkdir()
        (self.v / 'komuta/jev.json').write_text('{broken')
        result = g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'config_invalid')
        self.assertEqual(self.calls, 0)

    def test_previous_development_cannot_become_holdout(self):
        g.run(self.v, self.c, self.out, self.evaluate)
        dev, _ = g.split(self.c['cases'])
        repacked = copy.deepcopy(self.c)
        repacked['cases'] = copy.deepcopy(dev)
        repacked['cases'].append(dict(id='fresh-negative', query='new unknown 9', scope='user',
            expected=[], allowed=[], families=['negative:fresh'], origin='synthetic'))
        before = self.calls
        with self.assertRaisesRegex(ValueError, 'holdout_already_consumed'):
            g.run(self.v, repacked, self.out, self.evaluate)
        self.assertEqual(self.calls, before)

    def test_duplicate_queries_cannot_cross_split(self):
        dev, held = g.split(self.c['cases'])
        held[0]['query'] = '  ' + dev[0]['query'].upper().replace(' ', '  ') + '  '
        dev, held = g.split(self.c['cases'])
        normalize = lambda c: ' '.join(c['query'].casefold().split())
        self.assertFalse({normalize(c) for c in dev} & {normalize(c) for c in held})

    def cli(self):
        corpus = self.v / 'corpus.json'
        g.write(corpus, self.c)
        return subprocess.run([sys.executable, str(Path(g.__file__)), '--vault', str(self.v),
            'run', '--corpus', str(corpus), '--output-dir', str(self.out)],
            capture_output=True, text=True, timeout=10)

    def test_cli_review_rejection_is_actionable(self):
        self.c.pop('label_review')
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error'], 'label_review_required')

    def test_failed_cli_returns_nonzero(self):
        result = self.cli()
        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
        self.assertNotEqual(result.returncode, 0)

    def test_freeze_requires_review_before_reading_sources(self):
        with self.assertRaisesRegex(ValueError, 'label_review_required'):
            g.freeze(self.v, {'cases': []})

    def test_review_kinds_remain_distinct(self):
        for kind in ('human', 'agent', 'fixture'):
            with self.subTest(kind=kind):
                self.c['label_review']['kind'] = kind
                g.validate(self.c)
        self.c['label_review']['kind'] = 'automatic_acceptance'
        with self.assertRaisesRegex(ValueError, 'review'):
            g.validate(self.c)

    def test_malformed_corpus_rejected_before_any_call(self):
        for field, value in [('source_versions', []), ('candidates', None), ('cases', {}), ('label_status', None)]:
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    g.run(self.v, dict(self.c, **{field: value}), self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_candidate_families_must_have_source_hashes(self):
        self.c['candidates'][0]['families'] = ['invented-source']
        self.c['cases'][0]['families'] = ['invented-source']
        with self.assertRaisesRegex(ValueError, 'provenance'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_copied_source_content_cannot_cross_split(self):
        dev, held = g.split(self.c['cases'])
        a = next(c for c in dev if c['allowed'])
        b = next(c for c in held if c['allowed'])
        versions = dict(self.c['source_versions'])
        versions[b['families'][0]] = versions[a['families'][0]]
        dev, held = g.split(self.c['cases'], versions)
        left = {versions[f] for c in dev for f in c['families'] if f in versions}
        right = {versions[f] for c in held for f in c['families'] if f in versions}
        self.assertFalse(left & right)

    def test_source_renaming_does_not_reset_history(self):
        g.run(self.v, self.c, self.out, self.evaluate)
        corpus = copy.deepcopy(self.c)
        for candidate in corpus['candidates']:
            old = candidate['families'][0]
            new = 'copy-' + old
            (self.v / new).write_bytes((self.v / old).read_bytes())
            corpus['source_versions'][new] = corpus['source_versions'][old]
            candidate['families'] = [new]
        for case in corpus['cases']:
            case['query'] = 'different prompt ' + case['query']
            case['families'] = [('copy-' if case['allowed'] else 'fresh-') + f for f in case['families']]
        before = self.calls
        with self.assertRaisesRegex(ValueError, 'consumed'):
            g.run(self.v, corpus, self.out, self.evaluate)
        self.assertEqual(self.calls, before)

    def test_resume_rejects_limit_revision(self):
        g.run(self.v, self.c, self.out, self.timeout)
        with patch.object(g, 'MAX_TOKENS', g.MAX_TOKENS - 1):
            with self.assertRaisesRegex(ValueError, 'revision'):
                g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(self.calls, 0)

    def test_resume_does_not_reset_elapsed_budget(self):
        result = g.run(self.v, self.c, self.out, self.timeout)
        report = self.report(result)
        report['elapsed_seconds'] = g.MAX_SECONDS
        g.write(result['report'], report)
        with self.assertRaisesRegex(ValueError, 'budget'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(self.calls, 0)

    def test_malformed_usage_types_fail_closed(self):
        for index, usage in enumerate((None, [], {'input_tokens': True}, {'input_tokens': 1.5},
                                      {'output_tokens': float('nan')}, {'input_tokens': '10'})):
            with self.subTest(usage=usage):
                def bad(*args, **kwargs):
                    return dict(self.evaluate(*args, **kwargs), usage=usage)
                result = g.run(self.v, self.c, self.out / str(index), bad)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(self.report(result)['error'], 'usage_invalid')
                self.assertEqual(result['calls'], 1)

    def test_invalid_scores_still_account_reported_usage(self):
        for index, value in enumerate((True, -1, 2.1, float('nan'), float('inf'), '1.4')):
            with self.subTest(value=value):
                def bad(*args, **kwargs):
                    result = self.evaluate(*args, **kwargs)
                    result['scores']['0'] = value
                    return result
                result = g.run(self.v, self.c, self.out / str(index), bad)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(self.report(result)['error'], 'scores_invalid')
                self.assertEqual(self.report(result)['usage_tokens'], 10)
                self.assertEqual(result['calls'], 1)

    def test_metadata_does_not_persist_arbitrary_provider_text(self):
        sentinel = 'private metadata with spaces and a newline\n'
        def metadata(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result.update(diagnostics=[sentinel], request_hash=sentinel, reported_model=sentinel)
            return result
        result = g.run(self.v, self.c, self.out, metadata)
        report = self.report(result)
        self.assertNotIn(sentinel, json.dumps(report, ensure_ascii=False))
        self.assertEqual(report['last_inference']['diagnostics'], ['provider_diagnostic'])
        self.assertNotIn('reported_model', report['last_inference'])
        self.assertNotIn('request_hash', report['last_inference'])

    def test_missing_usage_is_visible_not_claimed_free(self):
        def unknown(*args, **kwargs):
            return dict(self.evaluate(*args, **kwargs), usage={})
        result = g.run(self.v, self.c, self.out, unknown)
        report = self.report(result)
        self.assertEqual(report['usage_unreported_calls'], report['calls'])
        self.assertEqual(report['usage_tokens'], 0)

    def test_code_change_during_call_fails(self):
        revision = g.code_revision()
        different = dict(revision, **{'jev_client.py': '0' * 64})
        with patch.object(g, 'code_revision', side_effect=[revision, revision, different]):
            result = g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'code_changed')
        self.assertEqual(self.calls, 1)

    def test_callback_cannot_mutate_frozen_labels(self):
        expected = {c['id']: list(c['expected']) for c in self.c['cases']}
        def mutate(*args, **kwargs):
            for case in self.c['cases']:
                case['expected'].clear()
            return self.evaluate(*args, **kwargs)
        result = g.run(self.v, self.c, self.out, mutate)
        self.assertEqual(result['status'], 'shadow_candidate')
        for row in self.report(result)['results']['development']:
            self.assertEqual(row['expected'], expected[row['parent_id']])

    def test_callback_cannot_shrink_required_score_ids(self):
        def mutate(vault, query, rows, **kwargs):
            rows.clear()
            return dict(mode='shadow', scores={}, usage={})
        result = g.run(self.v, self.c, self.out, mutate)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'scores_invalid')

    def test_incomplete_or_corrupt_ledger_is_not_ignored(self):
        self.out.mkdir()
        (self.out / ('a' * 64 + '.json')).write_text('{broken')
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_failed_replay_cli_still_returns_nonzero(self):
        g.run(self.v, self.c, self.out, self.timeout)
        result = self.cli()
        self.assertEqual(json.loads(result.stdout)['status'], 'unchanged')
        self.assertEqual(json.loads(result.stdout)['previous_status'], 'failed')
        self.assertNotEqual(result.returncode, 0)

    def test_real_adapter_and_runtime_with_offline_transport(self):
        (self.v / 'komuta').mkdir()
        (self.v / 'komuta/jev.json').write_text('{"mode":"shadow","timeout":3}')
        before = {name: (self.v / name).read_bytes() for name in self.c['source_versions']}
        def transport(endpoint, body, key, timeout):
            ident = body['state']['query'].strip()[-1]
            return dict(answers={f'f0_c{i}': dict(type='score', score=1.4 if c['id']==ident else 0)
                for i, c in enumerate(body['state']['candidates'])},
                usage=dict(input_tokens=10, output_tokens=3), model='offline-fixture')
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'offline-test-placeholder'}):
            with patch.object(jev_client, '_transport', side_effect=transport) as mocked:
                result = g.run(self.v, self.c, self.out)
                calls = mocked.call_count
                replay = g.run(self.v, self.c, self.out)
                self.assertEqual(mocked.call_count, calls)
        self.assertEqual(result['status'], 'shadow_candidate')
        self.assertEqual(replay['status'], 'unchanged')
        self.assertEqual(calls, result['calls'])
        self.assertEqual(self.report(result)['usage_tokens'], 13 * calls)
        self.assertEqual(self.report(result)['usage_unreported_calls'], 0)
        for name, contents in before.items():
            self.assertEqual((self.v / name).read_bytes(), contents)

    def test_exception_leaves_usage_explicitly_unknown(self):
        def broken(*args, **kwargs):
            raise RuntimeError('provider-failure')
        result = g.run(self.v, self.c, self.out, broken)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['usage_unreported_calls'], 1)
        self.assertEqual(result['calls'], 1)

    def test_invalid_cache_flag_cannot_claim_free(self):
        def invalid(*args, **kwargs):
            return dict(self.evaluate(*args, **kwargs), cache_hit='yes', usage={})
        result = g.run(self.v, self.c, self.out, invalid)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['usage_unreported_calls'], 1)

    def test_final_checkpoint_source_change_cannot_publish_candidate(self):
        original_write = g.write
        _, held = g.split(self.c['cases'], self.c['source_versions'])
        def checkpoint(path, report):
            original_write(path, report)
            if ('selected_before_holdout' in report
                    and len(report['results'].get('partial', [])) == len(held)):
                (self.v / 'source').write_text('changed at final checkpoint')
        with patch.object(g, 'write', side_effect=checkpoint):
            result = g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['shadow_candidate'])
        self.assertEqual(self.report(result)['error'], 'snapshot_changed')

    def test_legacy_corpus_is_not_silently_marked_reviewed(self):
        self.c['schema'] = 1
        with self.assertRaisesRegex(ValueError, 'schema_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_request_payload_excludes_labels_and_families(self):
        def inspect(vault, query, rows, **kwargs):
            for row in rows:
                self.assertEqual(set(row), {'id', 'title', 'statement', 'scope', 'domains'})
            self.assertEqual(set(kwargs), {'scope', 'source_versions'})
            return self.evaluate(vault, query, rows, **kwargs)
        result = g.run(self.v, self.c, self.out, inspect)
        self.assertEqual(result['status'], 'shadow_candidate')

    def test_both_partitions_keep_positive_and_negative_coverage(self):
        # Larger corpora must not spend the last negative component on holdout.
        for count in range(4, 33):
            cases = [dict(id=str(i), query='independent '+str(i), scope='user',
                families=['f'+str(i)], expected=[str(i)] if i>=2 else []) for i in range(count)]
            dev, held = g.split(cases)
            for rows in (dev, held):
                self.assertTrue(any(c['expected'] for c in rows))
                self.assertTrue(any(not c['expected'] for c in rows))

    def test_unsafe_source_paths_rejected_before_inference(self):
        for name in ('../outside', '/outside', 'C:/outside', 'a\\b', 'a/./b', 'a\0b'):
            with self.subTest(name=name):
                corpus = copy.deepcopy(self.c)
                corpus['source_versions'][name] = '0'*64
                with self.assertRaisesRegex(ValueError, 'source_version_invalid'):
                    g.run(self.v, corpus, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_legacy_incomplete_ledger_fails_closed(self):
        self.out.mkdir()
        ident='a'*64
        g.write(self.out/(ident+'.json'), dict(schema=1, corpus_digest=ident, status='failed',
            calls=1, usage_tokens=0, results={}, holdout_families=['legacy-held']))
        with self.assertRaisesRegex(ValueError, 'legacy_ledger_incomplete'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_disk_config_change_detected_inside_frozen_context(self):
        def mutate(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            (self.v/'komuta').mkdir()
            (self.v/'komuta/jev.json').write_text('{"mode":"shadow"}')
            return result
        with jev_client.evaluation_context(self.v):
            result = g.run(self.v, self.c, self.out, mutate)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'config_changed')
        self.assertEqual(self.calls, 1)


if __name__ == '__main__':
    unittest.main()
