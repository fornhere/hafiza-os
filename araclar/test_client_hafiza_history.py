"""Synthetic genuine user turn selection for native client hooks."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import client_hafiza
import gorev_baglam
import jev_client


class HistoryTests(unittest.TestCase):
    def test_previous_turn_ignores_peer_and_attached_notifications(self):
        source = {'entries': [dict(role='user', quote='Earlier task\n'
            '<task-notification>Foreign project</task-notification>'),
            dict(role='user', quote='<cross-session-message from="peer">'
                 'Foreign project</cross-session-message>'),
            dict(role='user', quote='Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')

    def test_previous_turn_ignores_t30_metadata_and_expansions(self):
        source = {'entries': [dict(role='user', quote=quote) for quote in (
            'Earlier task',
            '[Cross-session delivery notice] Synthetic delivery.',
            '[Image: source: /tmp/synthetic.png]',
            '# /loop — schedule a recurring or self-paced prompt\nForeign body',
            'Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')

    def test_delivery_receipt_contains_content_free_installation_version(self):
        import fayda_olc
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            lesson = dict(id='synthetic', version=1)
            with patch.object(fayda_olc.h, 'load_jsonl', return_value=[lesson]):
                receipt = fayda_olc._record_delivery(vault, client='claude', session_id='synthetic',
                    package_id='synthetic', delivered_lessons=[lesson], turn_id='synthetic')
            self.assertRegex(receipt['installation_version'], r'^araclar-sha256:[0-9a-f]{64}$')
            self.assertNotIn('prompt', receipt)
            self.assertNotIn('content', receipt)
            self.assertEqual(json.loads((vault / fayda_olc.DELIVERIES).read_text()), receipt)

    def test_previous_turn_attached_secret_still_blocks_context(self):
        source = {'entries': [dict(role='user', quote='Earlier task\n'
            '<task-notification>api_key=sk-' + 'x' * 48 + '</task-notification>'),
            dict(role='user', quote='Current task')]}
        self.assertIsNone(client_hafiza.previous_user(source, 'Current task'))

    def test_opening_budget_and_first_prompt_do_not_repeat_delivered_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            source = dict(latest_user=dict(quote='First task', message_id='u1'), entries=[])
            with (patch('codex_hafiza.opening_brief', return_value='B'*1800),
                  patch('codex_hafiza.latest_session_section', return_value='L'*1800),
                  patch.object(client_hafiza, 'recall', side_effect=lambda *a, **k: 'R'*k['budget']),
                  patch.object(client_hafiza, 'claude_task_package', return_value={
                      'text':'Current task evidence\n'+'P'*1950,'selected_ids':[]})):
                text = client_hafiza.context(vault,'claude','fixture',source,{},'SessionStart')
                self.assertLessEqual(len(text),3500)
                self.assertIn('Current task evidence',text)
                first = client_hafiza.context(vault,'claude','fixture',source,
                                             {'prompt':'Different first task'},'UserPromptSubmit')
                self.assertNotIn('Current task evidence',first)
                # The suppression is scoped to the first prompt, not later requests.
                later = client_hafiza.context(vault,'claude','fixture',source,
                                             {'prompt':'Another task'},'UserPromptSubmit')
                self.assertIn('Current task evidence',later)

    def test_previous_genuine_user_turn_only(self):
        source = {'entries': [dict(role='user', quote='Earlier task'),
                              dict(role='assistant', quote='response'),
                              dict(role='user', quote='Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        source['entries'].pop()
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        with patch.object(gorev_baglam, 'build_task_package', return_value={}) as build:
            client_hafiza.local_task_package('/tmp/example', 'Current task', previous_user='Earlier task')
        self.assertEqual(build.call_args.kwargs['previous_user'], 'Earlier task')

    def test_private_previous_turn_is_excluded(self):
        source = {'entries': [dict(role='user', quote='Do not save this private request'),
                              dict(role='user', quote='Current task')]}
        self.assertIsNone(client_hafiza.previous_user(source, 'Current task'))

    def test_claude_shadow_logs_hash_without_prompt_and_keeps_local_text(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory).resolve()
            local={'text':'local context','selected_ids':['local']}
            shadow={'text':'remote context','selected_ids':['memory:m1'],
                    'jev':{'gate':{'scores':{},'diagnostics':[]},
                           'catalog':{'scores':{'memory:m1':1.8},'diagnostics':[]}}}
            with (patch.object(jev_client,'load_config',return_value=dict(jev_client.DEFAULTS,mode='shadow',claude_hook_mode='shadow')),
                  patch.object(client_hafiza,'local_task_package',return_value=local),
                  patch.object(gorev_baglam,'build_task_package',return_value=shadow) as build):
                result=client_hafiza.claude_task_package(vault,'Synthetic writing request',previous_user='Earlier synthetic task')
            self.assertIs(result,local)
            build.assert_called_once()
            lines=list((vault/'.cache/jev-golge').glob('*.jsonl'))
            self.assertEqual(len(lines),1)
            raw=lines[0].read_text()
            self.assertNotIn('Synthetic writing request',raw)
            self.assertNotIn('Earlier synthetic task',raw)
            self.assertEqual(json.loads(raw)['selected_ids'],['memory:m1'])


    def test_global_off_prevents_claude_shadow_and_on_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            local = {'text': 'Local task context'}
            for hook_mode in ('shadow', 'on'):
                with self.subTest(hook_mode=hook_mode):
                    with (patch.object(jev_client, 'load_config', return_value=dict(
                              jev_client.DEFAULTS, mode='off', claude_hook_mode=hook_mode)),
                          patch.object(client_hafiza, 'local_task_package', return_value=local),
                          patch.object(gorev_baglam, 'build_task_package') as build):
                        self.assertIs(client_hafiza.claude_task_package(vault, 'Synthetic task'), local)
                    build.assert_not_called()
            self.assertFalse((vault / '.cache/jev-golge').exists())

    def test_claude_shadow_does_not_reenable_global_off_during_request(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            seen_modes = []
            def build(path, *args, **kwargs):
                seen_modes.append(jev_client.load_config(path)['mode'])
                return {'text': ''}
            enabled = dict(jev_client.DEFAULTS, mode='shadow', claude_hook_mode='shadow')
            disabled = dict(enabled, mode='off')
            with (patch.object(jev_client, 'load_config', side_effect=[enabled, disabled]),
                  patch.object(client_hafiza, 'local_task_package', return_value={'text': 'local'}),
                  patch.object(gorev_baglam, 'build_task_package', side_effect=build)):
                client_hafiza.claude_task_package(vault, 'Synthetic task')
            self.assertEqual(seen_modes, ['off'])


class HookHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()

    def fail(self, event='Stop', error=None):
        from client_transcripts import SourceError
        error = error or SourceError('registry_limit')
        with patch.object(client_hafiza, '_hook', side_effect=error):
            with self.assertRaises(type(error)):
                client_hafiza.hook(self.vault, 'claude', event, {'prompt': 'NEVER STORE THIS'})

    def opening(self):
        with patch.object(client_hafiza, '_hook', return_value=({}, {'status': 'context_suppressed'})):
            return client_hafiza.hook(self.vault, 'claude', 'SessionStart', {})[0]

    def test_registry_failure_records_only_health_fields_and_warns(self):
        import hook_health as health
        self.fail()
        row = health.read_events(self.vault)[0]
        self.assertEqual(set(row), {'at', 'client', 'event_type', 'error_code', 'installation_version'})
        self.assertEqual(row['error_code'], 'registry_limit')
        self.assertEqual(row['event_type'], 'Stop')
        self.assertNotIn('NEVER STORE THIS', (self.vault / health.PATH).read_text())
        text = self.opening()['hookSpecificOutput']['additionalContext']
        self.assertIn('oturum yakalama 1 kez başarısız (registry_limit)', text)
        self.assertLessEqual(len(text), 241)

    def test_expected_source_rejections_do_not_warn(self):
        import hook_health as health
        from client_transcripts import SourceError
        for code in ('privacy_blocked', 'source_validation_failed', 'source_identity_mismatch', 'threshold_or_incomplete'):
            self.fail(error=SourceError(code))
        self.assertEqual(health.read_events(self.vault), [])
        self.assertEqual(self.opening(), {})

    def test_prompt_threshold_and_24_hour_window(self):
        import datetime as dt
        import hook_health as health
        for _ in range(2):
            self.fail('UserPromptSubmit')
        self.assertEqual(self.opening(), {})
        self.fail('UserPromptSubmit')
        self.assertIn('hook çalışması 3 kez', self.opening()['hookSpecificOutput']['additionalContext'])
        self.assertEqual(health.warning(self.vault, dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)), '')

    def test_telemetry_io_failure_keeps_original_hook_error(self):
        import hook_health as health
        with patch.object(health, 'exclusive_lock', side_effect=OSError('NEVER STORE THIS')):
            self.fail()
        self.assertEqual(health.read_events(self.vault), [])
        with patch.object(health, 'read_events', side_effect=OSError('NEVER STORE THIS')):
            self.assertEqual(health.warning(self.vault), '')

    def test_cli_failed_opening_still_shows_warning(self):
        import io
        import sys
        from client_transcripts import SourceError
        payload = {'session_id': 'synthetic', 'prompt': 'NEVER STORE THIS'}
        with patch.object(client_hafiza, '_hook', side_effect=SourceError('registry_limit')), \
             patch.object(sys, 'argv', ['client_hafiza.py', '--vault', str(self.vault),
                                      '--client', 'claude', '--event', 'SessionStart']), \
             patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()))), \
             patch.object(sys, 'stdout', io.StringIO()) as out, \
             patch.object(sys, 'stderr', io.StringIO()) as err:
            # This is the third same-code opening failure, with no normal context.
            self.fail('SessionStart')
            self.fail('SessionStart')
            self.assertEqual(client_hafiza.main(), 0)
            self.assertIn('hook çalışması 3 kez başarısız (registry_limit)',
                          json.loads(out.getvalue())['hookSpecificOutput']['additionalContext'])
            self.assertNotIn('NEVER STORE THIS', err.getvalue())

    def test_retention_and_nonblocking_lock(self):
        import hook_health as health
        from client_transcripts import SourceError
        from platform_lock import exclusive_lock
        health.record_failure(self.vault, 'claude', 'Stop', SourceError('registry_limit'))
        path = self.vault / health.PATH
        original = path.read_bytes()
        with exclusive_lock(path.with_suffix('.lock')):
            health.record_failure(self.vault, 'claude', 'Stop', SourceError('registry_limit'))
        self.assertEqual(path.read_bytes(), original)
        with patch.object(health, 'MAX_EVENTS', 3):
            for _ in range(6):
                health.record_failure(self.vault, 'claude', 'Stop', RuntimeError('NEVER STORE THIS'))
            self.assertEqual(len(health.read_events(self.vault)), 3)
        self.assertNotIn('NEVER STORE THIS', path.read_text())


if __name__ == '__main__':
    unittest.main()
