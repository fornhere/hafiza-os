"""Explicit subprocess reviewer tests using local Python fixture commands."""
import json
import os
import subprocess
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

from test_client_sessions import NativeFixture
import client_review as runner
import client_sessions as sessions
from client_transcripts import SourceError


class ReviewerRunner(NativeFixture):
    def command(self, body):
        return [sys.executable, '-X', 'utf8', '-c', body]

    def test_dry_run_never_starts_process(self):
        self.register()
        with patch.object(runner.subprocess, 'Popen', side_effect=AssertionError('must not launch')):
            result = runner.run(self.vault, self.command('raise SystemExit(1)'))
        self.assertFalse(result[0]['process_started'])
        self.assertEqual(result[0]['status'], 'dry_run')

    def test_apply_reads_bounded_packet_and_records(self):
        ident = self.register()['id']
        code = '''import json,sys
text=sys.stdin.read()
assert 'untrusted data' in text
packet=json.loads(text.split('BEGIN_UNTRUSTED_PACKET\\n',1)[1].rsplit('\\nEND_UNTRUSTED_PACKET',1)[0])
assert 'NEVER_COPY_REASONING' not in text
entry=packet['evidence'][-1]
print(json.dumps(dict(decision='record',meaningful=True,reviewer_role='fixture-reviewer',reason='Completed result',summary='Completed local result, acceptance pending.',evidence=[{k:entry[k] for k in ('line','line_sha256','quote')}])))
'''
        result = runner.run(self.vault, self.command(code), apply=True)
        self.assertEqual(result, [{'id': ident, 'status': 'record'}])
        self.assertIn('Completed local result', sessions.recall(self.vault))
        self.assertEqual(runner.run(self.vault, self.command(code), apply=True), [])

    def test_failure_timeout_invalid_json_and_output_limit_leave_pending(self):
        ident = self.register()['id']
        for code, timeout, diagnostic in (
                ('import sys;sys.stderr.write("private error");sys.exit(2)', 2, 'reviewer_failed'),
                ('import time;time.sleep(2)', 0.05, 'reviewer_timeout'),
                ('print("not JSON")', 2, 'reviewer_invalid_output'),
                (f'print("x"*{runner.MAX_OUTPUT + 1000})', 2, 'reviewer_output_limit')):
            result = runner.run(self.vault, self.command(code), True, timeout)
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(result[0]['status'], 'failed')
                self.assertEqual(result[0]['diagnostic'], diagnostic)
                self.assertNotIn('private error', json.dumps(result))
                self.assertEqual(sessions.pending(self.vault)[0]['id'], ident)

    def test_placeholder_shell_characters_are_literal(self):
        marker = self.root / 'must-not-exist'
        prompt = '$(touch ' + str(marker) + '); `touch nope` | & %VALUE% Türkçe'
        code = 'import json,sys;print(json.dumps({"seen":sys.argv[1]}))'
        result = runner.invoke(self.command(code) + ['{prompt}'], prompt, 3)
        self.assertEqual(result['seen'], prompt)
        self.assertFalse(marker.exists())
        for bad in ('echo hi', [], ['echo', '{prompt}', '{prompt}'], ['{prompt}'], ['echo', '\0']):
            with self.assertRaises(SourceError): runner.validate_argv(bad)

    def test_source_changed_while_reviewer_runs_cannot_record(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        def mutate(*args):
            self.rows[0]['message']['content'] = 'mutated source'; self.write()
            return decision
        with patch.object(runner, 'invoke', side_effect=mutate):
            result = runner.run(self.vault, ['fixture-reviewer'], True)
        self.assertEqual(result[0]['status'], 'failed')
        self.assertEqual(sessions.recall(self.vault), '')

    def test_malformed_decision_does_not_record(self):
        self.register()
        for value in ('[]', '{}', '{"decision":"record","meaningful":true}'):
            result = runner.run(self.vault, self.command('print(' + repr(value) + ')'), True)
            self.assertEqual(result[0]['status'], 'failed')
        self.assertEqual(sessions.recall(self.vault), '')

    def test_runner_cli_dry_run_contract(self):
        self.register()
        result = subprocess.run([sys.executable, '-X', 'utf8', str(Path(runner.__file__)),
                                 '--vault', str(self.vault), '--reviewer-argv-json',
                                 json.dumps(self.command('raise SystemExit(99)'))],
                                capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['status'], 'dry_run')

    def test_reviewer_argv_environment_fallback_and_missing_error(self):
        self.register()
        command = [sys.executable, '-X', 'utf8', str(Path(runner.__file__)),
                   '--vault', str(self.vault)]
        env = dict(os.environ, HAFIZA_REVIEWER_ARGV=json.dumps(self.command('raise SystemExit(99)')))
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['status'], 'dry_run')
        env.pop('HAFIZA_REVIEWER_ARGV')
        result = subprocess.run(command, env=env, capture_output=True, text=True, encoding='utf-8', timeout=15)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['diagnostic'], 'missing_reviewer_argv')

    def test_invoke_uses_last_complete_json_from_noisy_stdout(self):
        code = '''import json
print('startup text')
print(json.dumps({'decision': 'old'}))
print('progress {not json}')
print(json.dumps({'decision': 'record', 'nested': {'value': 1}}, indent=2))
print('finished')
'''
        self.assertEqual(runner.invoke(self.command(code), 'prompt', 3),
                         {'decision': 'record', 'nested': {'value': 1}})


class WindowsCommandBudget(unittest.TestCase):
    def test_placeholder_limit_before_spawn(self):
        import client_review
        from unittest.mock import patch
        with patch.object(client_review.os, 'name', 'nt'), patch.object(client_review.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(client_review.SourceError, 'command_limit'):
                client_review.invoke(['reviewer', '{prompt}'], 'x' * 31000, 10)
            spawn.assert_not_called()
