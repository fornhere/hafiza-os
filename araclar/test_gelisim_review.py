"""PR re-review regressions; synthetic sources and offline transports only."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import types
import unittest
from unittest.mock import patch

import gelisim_dongusu as g
import jev_client
import test_gelisim_dongusu as fixtures


PREFIX = 'Şu soruyu mevcut kaynaklardan yanıtla: '


class ReviewTests(unittest.TestCase):
    setUp = fixtures.LoopTests.setUp
    evaluate = fixtures.LoopTests.evaluate

    def timeout(self, *args, **kwargs):
        return dict(mode='shadow', degraded=True, scores={},
                    diagnostics=['deadline_exceeded'])

    def report(self, result):
        return json.loads(Path(result['report']).read_text(encoding='utf-8'))

    def test_generated_request_cannot_overlap_holdout_seed(self):
        dev, held = g.split(self.c['cases'], self.c['source_versions'])
        original = next(c for c in dev if not c['allowed'])
        target = next(c for c in held if not c['allowed'])
        target['query'] = PREFIX + original['query']
        # These are now one negative family, not two independent negatives.
        with self.assertRaisesRegex(ValueError, 'positive_negative_coverage_required'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_variants_reserved_even_before_first_result(self):
        dev, _ = g.split(self.c['cases'], self.c['source_versions'])
        result = g.run(self.v, self.c, self.out, self.timeout)
        actual = self.report(result)['development_keys']
        for case in g.synthesize(dev):
            normalized = ' '.join(case['query'].casefold().split())
            self.assertIn('query:' + g.digest([case['scope'], normalized]), actual)

    def test_prior_development_variant_cannot_be_new_holdout(self):
        dev, _ = g.split(self.c['cases'], self.c['source_versions'])
        old_negative = next(c for c in dev if not c['allowed'])
        g.run(self.v, self.c, self.out, self.timeout)
        corpus = copy.deepcopy(self.c)
        for candidate in corpus['candidates']:
            old = candidate['families'][0]
            name = 'fresh-' + old
            data = ('genuinely fresh evidence ' + name).encode()
            (self.v / name).write_bytes(data)
            corpus['source_versions'][name] = hashlib.sha256(data).hexdigest()
            candidate['families'] = [name]
        for case in corpus['cases']:
            case['families'] = ['fresh-' + f for f in case['families']]
            case['query'] = 'fresh question ' + case['id']
        _, held = g.split(corpus['cases'], corpus['source_versions'])
        target = next(c for c in held if not c['allowed'])
        target['query'] = PREFIX + old_negative['query']
        with self.assertRaisesRegex(ValueError, 'holdout_already_consumed'):
            g.run(self.v, corpus, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_optional_evidence_is_not_an_unsupported_negative(self):
        for case in self.c['cases']:
            if case['allowed']:
                continue
            ident = case['id']
            family = 'family' + ident
            data = ('optional independent source ' + ident).encode()
            (self.v / family).write_bytes(data)
            self.c['source_versions'][family] = hashlib.sha256(data).hexdigest()
            self.c['candidates'].append(dict(id=ident, title=ident, statement='optional fact',
                scope='user', domains=[], families=[family]))
            case.update(allowed=[ident], families=[family])
        g.validate(self.c)
        with self.assertRaisesRegex(ValueError, 'positive_negative_coverage_required'):
            g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(self.calls, 0)

    def test_resume_missing_elapsed_cannot_reset_budget(self):
        result = g.run(self.v, self.c, self.out, self.timeout)
        report = self.report(result)
        report.pop('elapsed_seconds')
        g.write(result['report'], report)
        before = Path(result['report']).read_bytes()
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(Path(result['report']).read_bytes(), before)
        self.assertEqual(self.calls, 0)

    def test_resume_missing_attempt_elapsed_is_incomplete(self):
        result = g.run(self.v, self.c, self.out, self.timeout)
        report = self.report(result)
        report.pop('attempt_elapsed_seconds')
        g.write(result['report'], report)
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(self.calls, 0)

    def test_final_checkpoint_time_overrun_is_not_success(self):
        clock = [0.0]
        real_write = g.write
        _, held = g.split(self.c['cases'], self.c['source_versions'])
        def write(path, report):
            real_write(path, report)
            if ('selected_before_holdout' in report
                    and len(report['results'].get('partial', [])) == len(held)):
                clock[0] = g.MAX_SECONDS + 1
        with patch.object(g, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])):
            with patch.object(g, 'write', side_effect=write):
                result = g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['shadow_candidate'])
        self.assertEqual(self.report(result)['error'], 'budget_exhausted')

    def test_last_development_checkpoint_overrun_is_not_no_improvement(self):
        clock = [0.0]
        real_write = g.write
        dev, _ = g.split(self.c['cases'], self.c['source_versions'])
        def write(path, report):
            real_write(path, report)
            if len(report['results'].get('partial', [])) == len(g.synthesize(dev)):
                clock[0] = g.MAX_SECONDS + 1
        def perfect(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result['scores'] = {k: 2 if v else 0 for k, v in result['scores'].items()}
            return result
        with patch.object(g, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])):
            with patch.object(g, 'write', side_effect=write):
                result = g.run(self.v, self.c, self.out, perfect)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.report(result)['error'], 'budget_exhausted')

    def test_expired_call_reservation_does_not_start_inference(self):
        clock = [0.0]
        real_write = g.write
        def write(path, report):
            real_write(path, report)
            if report['calls'] == 1:
                clock[0] = g.MAX_SECONDS
        with patch.object(g, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])):
            with patch.object(g, 'write', side_effect=write):
                result = g.run(self.v, self.c, self.out, self.evaluate)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.calls, 0)

    def test_failure_diagnostic_with_complete_scores_is_not_success(self):
        def contradictory(*args, **kwargs):
            return dict(self.evaluate(*args, **kwargs), degraded=False,
                        diagnostics=['deadline_exceeded'])
        result = g.run(self.v, self.c, self.out, contradictory)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['shadow_candidate'])
        self.assertEqual(self.calls, 1)

    def test_empty_success_results_are_not_a_successful_replay(self):
        result = g.run(self.v, self.c, self.out, self.evaluate)
        report = self.report(result)
        report['results'] = {}
        g.write(result['report'], report)
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate)

    def test_inconsistent_success_metrics_are_rejected(self):
        result = g.run(self.v, self.c, self.out, self.evaluate)
        report = self.report(result)
        report['holdout']['candidate']['extra'] += 1
        g.write(result['report'], report)
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate)

    def test_corrupt_success_cli_returns_nonzero(self):
        result = g.run(self.v, self.c, self.out, self.evaluate)
        report = self.report(result)
        report['results'] = {}
        g.write(result['report'], report)
        corpus = self.v / 'input.json'
        g.write(corpus, self.c)
        reply = subprocess.run([sys.executable, str(Path(g.__file__)), '--vault', str(self.v),
            'run', '--corpus', str(corpus), '--output-dir', str(self.out)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(reply.returncode, 2)
        self.assertEqual(json.loads(reply.stdout)['error'], 'ledger_invalid')

    def test_real_timeout_late_result_cannot_rewrite_report(self):
        (self.v / 'komuta').mkdir()
        (self.v / 'komuta/jev.json').write_text('{"mode":"shadow","timeout":0.1}')
        release = threading.Event()
        entered = threading.Event()
        workers = []
        def transport(endpoint, body, key, timeout):
            workers.append(threading.current_thread())
            entered.set()
            release.wait(5)
            return dict(answers={name: dict(type='score', score=2)
                                for name in body['questions']},
                        usage=dict(input_tokens=10, output_tokens=2))
        try:
            with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'offline-test-placeholder'}):
                with patch.object(jev_client, '_transport', side_effect=transport):
                    result = g.run(self.v, self.c, self.out)
            self.assertTrue(entered.is_set())
            self.assertEqual(result['status'], 'failed')
            report = self.report(result)
            self.assertEqual(report['last_inference']['diagnostics'], ['deadline_exceeded'])
            self.assertEqual(report['usage_unreported_calls'], 1)
            before = Path(result['report']).read_bytes()
        finally:
            release.set()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive())
        self.assertEqual(Path(result['report']).read_bytes(), before)
        self.assertFalse(list((self.v / '.cache/jev').glob('*.json')))

    def test_resume_cumulative_reported_tokens_and_time(self):
        clock = [0.0]
        def timeout(*args, **kwargs):
            clock[0] = 7.0
            return dict(self.timeout(), usage=dict(input_tokens=17, output_tokens=3))
        with patch.object(g, 'time', types.SimpleNamespace(monotonic=lambda: clock[0])):
            first = g.run(self.v, self.c, self.out, timeout)
            clock[0] = 1000.0  # Idle time between attempts is deliberately not charged.
            def score(*args, **kwargs):
                clock[0] += 1.0
                return dict(self.evaluate(*args, **kwargs), usage=dict(input_tokens=10, output_tokens=2))
            second = g.run(self.v, self.c, self.out, score, resume=True)
        before, after = self.report(first)['previous_attempt'], self.report(second)
        self.assertEqual(after['calls'], self.calls + 1)
        self.assertEqual(after['usage_tokens'], 20 + self.calls * 12)
        self.assertEqual(after['elapsed_seconds'], 7 + self.calls)
        self.assertEqual(before['elapsed_seconds'], 7)
        self.assertEqual(after['status'], 'shadow_candidate')

    def test_resume_token_cap_cannot_reset(self):
        def charged_timeout(*args, **kwargs):
            return dict(self.timeout(), usage=dict(input_tokens=g.MAX_TOKENS, output_tokens=0))
        first = g.run(self.v, self.c, self.out, charged_timeout)
        with self.assertRaisesRegex(ValueError, 'budget_exhausted'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.report(first)['usage_tokens'], g.MAX_TOKENS)

    def test_fatal_holdout_result_cannot_be_retried(self):
        count = len(g.synthesize(g.split(self.c['cases'], self.c['source_versions'])[0]))
        def timeout_holdout(*args, **kwargs):
            if self.calls == count:
                return self.timeout()
            return self.evaluate(*args, **kwargs)
        result = g.run(self.v, self.c, self.out, timeout_holdout)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('selected_before_holdout', self.report(result))
        with self.assertRaisesRegex(ValueError, 'resume_not_eligible'):
            g.run(self.v, self.c, self.out, self.evaluate, resume=True)

    def test_completed_report_with_contaminated_holdout_is_rejected(self):
        result = g.run(self.v, self.c, self.out, self.evaluate)
        report = self.report(result)
        # Keep metrics/scores intact: the label-group collision alone invalidates it.
        report['results']['holdout'][0]['query'] = PREFIX + report['results']['development'][0]['query']
        g.write(result['report'], report)
        with self.assertRaisesRegex(ValueError, 'ledger_invalid'):
            g.run(self.v, self.c, self.out, self.evaluate)

    def test_valid_no_improvement_report_still_replays_without_calls(self):
        def perfect(*args, **kwargs):
            result = self.evaluate(*args, **kwargs)
            result['scores'] = {k: 2 if v else 0 for k, v in result['scores'].items()}
            return result
        first = g.run(self.v, self.c, self.out, perfect)
        self.assertEqual(first['status'], 'no_improvement')
        before = self.calls
        replay = g.run(self.v, self.c, self.out, perfect)
        self.assertEqual(replay['previous_status'], 'no_improvement')
        self.assertEqual(self.calls, before)

    def test_valid_holdout_rejection_still_replays_without_calls(self):
        _, held = g.split(self.c['cases'], self.c['source_versions'])
        identities = {c['id'] for c in held}
        def bad(vault, query, rows, **kwargs):
            result = self.evaluate(vault, query, rows, **kwargs)
            if query.strip()[-1] in identities:
                result['scores'] = {row['id']: 1.4 for row in rows}
            return result
        first = g.run(self.v, self.c, self.out, bad)
        self.assertEqual(first['status'], 'holdout_rejected')
        before = self.calls
        replay = g.run(self.v, self.c, self.out, bad)
        self.assertEqual(replay['previous_status'], 'holdout_rejected')
        self.assertEqual(self.calls, before)


if __name__ == '__main__':
    unittest.main()
