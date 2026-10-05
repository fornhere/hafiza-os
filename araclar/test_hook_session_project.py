"""Same-session delivered project scope in native hook state (synthetic vaults)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import client_hafiza as claude
import client_sessions
import codex_hafiza as codex
import gorev_baglam
from client_transcripts import SourceError


REAL_BUILD = gorev_baglam.build_task_package


class SessionProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()
        self.projects = [dict(id='x', aliases=['Atlas'], roots=[]),
                         dict(id='y', aliases=['Boreal'], roots=[str(self.vault / 'workspace')])]
        self.calls = []
        self.addCleanup(patch.stopall)
        patch.object(gorev_baglam, 'build_task_package', self.package).start()
        patch.object(codex, 'opening_brief', return_value='').start()
        patch.object(codex, 'latest_session_section', return_value='').start()
        patch.object(codex, 'shared_reviewed_context', return_value='').start()
        patch.object(claude, 'recall', return_value='').start()
        patch.dict(os.environ, {'HAFIZA_HOOK_JEV': '0', 'HAFIZA_ISCI': '0', 'CODEX_WORKER': '0'}).start()

    def package(self, vault, query, **kwargs):
        projects, reason = gorev_baglam.select_projects(
            self.projects, query, kwargs.get('cwd'), kwargs.get('previous_user'),
            kwargs.get('session_project_id'))
        project = projects[0]['id'] if len(projects) == 1 else None
        self.calls.append((kwargs.get('session_project_id'), project, reason))
        return dict(text=f'Context: {query} ({project})', project_id=project)

    def prompt(self, client, query, session='s1', turn='t1', **extra):
        if client == 'claude':
            return claude.hook(self.vault, client, 'UserPromptSubmit', dict(
                session_id=session, transcript_path=str(self.vault / (session + '.jsonl')), prompt=query, **extra))
        return codex.hook(self.vault, dict(hook_event_name='UserPromptSubmit',
                          session_id=session, turn_id=turn, prompt=query, **extra))

    def state_path(self, client, session='s1'):
        if client == 'claude':
            return client_sessions.policy_path(self.vault / client_sessions.INBOX / '.state', client, session)
        return self.vault / codex.INBOX / '.state' / (codex.key(session, 'state') + '.json')

    def test_same_session_and_other_session(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.prompt(client, 'Atlas ne durumda')
                self.assertEqual(json.loads(self.state_path(client).read_text())['session_project_id'], 'x')
                self.prompt(client, 'devam et', turn='t2')
                self.assertEqual(self.calls[-1], ('x', 'x', 'session_project'))
                self.prompt(client, 'devam et', session='s2')
                self.assertEqual(self.calls[-1], (None, None, 'unresolved'))

    def test_explicit_and_cwd_precedence(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.prompt(client, 'Atlas ne durumda')
                self.prompt(client, 'Boreal ne durumda', turn='t2')
                self.assertEqual(self.calls[-1], ('x', 'y', 'explicit'))
                self.prompt(client, 'Atlas ne durumda', turn='t3')
                self.prompt(client, 'devam et', turn='t4', cwd=str(self.vault / 'workspace'))
                self.assertEqual(self.calls[-1], ('x', 'y', 'cwd'))

    def test_archived_and_removed_project_not_inherited(self):
        for client in ('claude', 'codex'):
            for status in ('archived', 'arsiv', 'arşiv', 'removed'):
                with self.subTest(client=client, status=status):
                    session = client + str(('archived', 'arsiv', 'arşiv', 'removed').index(status))
                    self.projects[0]['status'] = 'aktif'
                    self.prompt(client, 'Atlas ne durumda', session=session)
                    original = list(self.projects)
                    if status == 'removed': self.projects = self.projects[1:]
                    else: self.projects[0]['status'] = status
                    self.prompt(client, 'devam et', session=session, turn='t2')
                    self.assertEqual(self.calls[-1], ('x', None, 'unresolved'))
                    self.projects = original

    def test_secret_clears_scope_and_next_prompt_does_not_inherit(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.prompt(client, 'Atlas ne durumda')
                try:
                    self.prompt(client, 'api_key=sk-' + 'x' * 48, turn='t2')
                except SourceError as error:
                    self.assertEqual(str(error), 'private_context')
                self.assertIsNone(json.loads(self.state_path(client).read_text()).get('session_project_id'))
                self.prompt(client, 'devam et', turn='t3')
                self.assertEqual(self.calls[-1], (None, None, 'unresolved'))

    def test_private_prompt_clears_scope_and_blocks_inheritance(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.prompt(client, 'Atlas ne durumda')
                for query, turn in [('Bu oturumu kaydetme.', 't2'), ('devam et', 't3')]:
                    try:
                        self.prompt(client, query, turn=turn)
                    except SourceError as error:
                        self.assertEqual(str(error), 'privacy_blocked')
                self.assertIsNone(json.loads(self.state_path(client).read_text()).get('session_project_id'))
                if client == 'codex': self.assertEqual(self.calls[-1], (None, None, 'unresolved'))

    def test_worker_prompt_does_not_read_or_write_scope(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.prompt(client, 'Atlas ne durumda')
                before = self.state_path(client).read_bytes()
                count = len(self.calls)
                self.prompt(client, 'İŞÇİ KOŞUSU. devam et', turn='t2')
                self.assertEqual(len(self.calls), count)
                self.assertEqual(self.state_path(client).read_bytes(), before)
                self.prompt(client, 'İŞÇİ KOŞUSU. devam et', session='worker')
                self.assertFalse(self.state_path(client, 'worker').exists())

    def notifications(self):
        # Synthetic bodies; tag/attribute shapes verified in T14 A:1867/2202.
        return [
            '<task-notification><task-id>t</task-id><tool-use-id>u</tool-use-id>'
            '<output-file>/tmp/task.output</output-file><status>completed</status>'
            '<summary>Boreal ne durumda</summary></task-notification>',
            '<cross-session-message from="peer" from-session="other" '
            'from-name="peer" from-mode="default">Boreal ne durumda</cross-session-message>',
            '<system-reminder>Boreal ne durumda</system-reminder>',
            '<heartbeat>Boreal ne durumda</heartbeat>',
            '<goal>Boreal ne durumda</goal>',
            '[HAFIZA_OTOMASYON] Boreal ne durumda',
        ]

    def test_claude_harness_has_no_context_or_scope_update(self):
        self.prompt('claude', 'Atlas ne durumda')
        before = self.state_path('claude').read_bytes()
        count = len(self.calls)
        for notification in self.notifications():
            with self.subTest(notification=notification):
                output, status = self.prompt('claude', notification)
                self.assertEqual(output, {})
                self.assertEqual(status['status'], 'context_suppressed')
                self.assertEqual(len(self.calls), count)
                self.assertEqual(self.state_path('claude').read_bytes(), before)
                self.prompt('claude', notification, session='fresh')
                self.assertFalse(self.state_path('claude', 'fresh').exists())

    def test_claude_mixed_prompt_uses_only_user_text(self):
        for index, notification in enumerate(self.notifications()):
            if notification.startswith('[HAFIZA_OTOMASYON]'):
                continue  # Legacy marker has no closing boundary for a mixed prompt.
            for position, prompt in enumerate(('Atlas ne durumda\n' + notification,
                           notification + '\nAtlas ne durumda',
                           'Atlas ' + notification + 'ne durumda')):
                with self.subTest(index=index, prompt=prompt):
                    session = 'mixed' + str(index)
                    # Reset duplicate suppression by using a fresh session.
                    with patch.object(claude, 'claude_task_package', wraps=claude.claude_task_package) as build:
                        self.prompt('claude', prompt, session=session + str(position))
                    self.assertEqual(build.call_args.args[1], 'Atlas ne durumda')
                    self.assertEqual(self.calls[-1][1], 'x')

    def test_claude_direct_context_notification_does_not_use_lagging_user(self):
        self.prompt('claude', 'Atlas ne durumda')
        before = self.state_path('claude').read_bytes()
        source = dict(latest_user=dict(quote='Boreal ne durumda', message_id='old'),
                      entries=[dict(role='user', quote='Boreal ne durumda')])
        self.assertEqual(claude.context(self.vault, 'claude', 's1', source,
                         dict(prompt=self.notifications()[1]), 'UserPromptSubmit'), '')
        self.assertEqual(self.state_path('claude').read_bytes(), before)

    def test_t30_native_meta_does_not_change_scope(self):
        meta = [
            '[Cross-session delivery notice] Boreal delivery completed.',
            '[Image: source: /tmp/synthetic.png]',
            '<command-message>loop</command-message><command-name>/loop</command-name>',
            '# /loop — schedule a recurring or self-paced prompt\nBoreal ne durumda',
        ]
        for client in ('claude', 'codex'):
            self.prompt(client, 'Atlas ne durumda')
            before = self.state_path(client).read_bytes()
            count = len(self.calls)
            for query in meta:
                with self.subTest(client=client, query=query):
                    output = self.prompt(client, query, turn='t2')
                    self.assertEqual(output[0] if client == 'claude' else output, {})
                    self.assertEqual(len(self.calls), count)
                    self.assertEqual(self.state_path(client).read_bytes(), before)
                    self.prompt(client, query, session='fresh-meta')
                    self.assertFalse(self.state_path(client, 'fresh-meta').exists())

    def test_t30_mixed_attachment_and_command_only_use_text(self):
        for client in ('claude', 'codex'):
            for index, query in enumerate([
                'Atlas ne durumda\n[Image: source: /tmp/synthetic.png]',
                '[Cross-session delivery notice] Boreal delivery.\nAtlas ne durumda',
                '<command-message>loop</command-message><command-name>/loop</command-name>'
                '<command-args>Atlas ne durumda</command-args>\n'
                '# /loop — schedule a recurring or self-paced prompt\nBoreal ne durumda',
            ]):
                with self.subTest(client=client, index=index):
                    with patch.object(gorev_baglam, 'build_task_package', wraps=self.package) as build:
                        output = self.prompt(client, query, session='text' + str(index))
                    self.assertEqual(build.call_args.args[1], 'Atlas ne durumda')
                    self.assertEqual(self.calls[-1][1], 'x')
                    if client == 'claude':
                        self.assertRegex(output[1]['installation_version'], r'^araclar-sha256:[0-9a-f]{64}$')

    def test_codex_suppressed_package_does_not_replace_last_delivered_scope(self):
        self.prompt('codex', 'Atlas ne durumda')
        with patch.object(gorev_baglam, 'build_task_package', return_value={
                'text': 'Context: Atlas ne durumda (x)', 'project_id': 'y'}):
            self.prompt('codex', 'Continue', turn='t2')
        self.assertEqual(json.loads(self.state_path('codex').read_text())['session_project_id'], 'x')

    def test_claude_modes_forward_scope_to_local_and_shadow(self):
        import jev_client
        for mode in ('off', 'on', 'shadow'):
            with self.subTest(mode=mode), patch.object(jev_client, 'load_config', return_value=dict(
                    jev_client.DEFAULTS, mode=mode, claude_hook_mode=mode)):
                claude.claude_task_package(self.vault, 'devam et', session_project_id='x')
                self.assertEqual(self.calls[-1], ('x', 'x', 'session_project'))

    def test_real_package_builder_continues_delivered_project(self):
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/gorev-baglam.json').write_text(
            json.dumps({'projects': self.projects}), encoding='utf-8')
        with patch.object(gorev_baglam, 'build_task_package', wraps=REAL_BUILD) as build:
            for client in ('claude', 'codex'):
                with self.subTest(client=client):
                    self.prompt(client, 'Atlas ne durumda')
                    self.prompt(client, 'devam et', turn='t2')
                    self.assertEqual(build.call_args.kwargs['session_project_id'], 'x')
                    self.assertEqual(json.loads(self.state_path(client).read_text())['session_project_id'], 'x')

    def test_claude_secret_cannot_reinherit_from_lagging_transcript(self):
        self.prompt('claude', 'Atlas ne durumda')
        with self.assertRaises(SourceError):
            self.prompt('claude', 'api_key=sk-' + 'x' * 48)
        source = dict(latest_user=dict(quote='Atlas ne durumda', message_id='old'),
                      entries=[dict(role='user', quote='Atlas ne durumda')])
        claude.context(self.vault, 'claude', 's1', source,
                       dict(prompt='devam et'), 'UserPromptSubmit')
        self.assertEqual(self.calls[-1], (None, None, 'unresolved'))
