"""Native synthetic fixtures only; no personal history, services or networking."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import client_hafiza as hooks
import client_sessions as sessions
from client_transcripts import SourceError, parse


class NativeFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.vault = self.root / 'Türkçe kasa'
        self.vault.mkdir()
        self.session = 'conversation-123'
        self.client = 'claude'
        self.path = self.root / (self.session + '.jsonl')
        self.rows = self.claude_rows()
        self.write()

    def claude_rows(self, count=6):
        rows = []
        for index in range(count):
            rows.extend([
                {'type': 'user', 'uuid': f'u{index}', 'sessionId': self.session,
                 'isSidechain': False, 'message': {'role': 'user', 'content': f'Gerçek kullanıcı görevi {index}'}},
                {'type': 'assistant', 'uuid': f'a{index}', 'sessionId': self.session,
                 'isSidechain': False, 'message': {'role': 'assistant', 'model': 'claude-fixture',
                 'content': [{'type': 'thinking', 'thinking': 'NEVER_COPY_REASONING'},
                             {'type': 'text', 'text': f'Uygulama sonucu {index}'}], 'stop_reason': 'end_turn'}}])
        return rows

    def agy(self, count=6):
        self.client = 'antigravity'
        self.path = self.root / 'brain' / self.session / '.system_generated/logs/transcript_full.jsonl'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.rows = []
        for index in range(count):
            self.rows.extend([
                {'step_index': 2*index, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT', 'status': 'DONE',
                 'content': f'<USER_REQUEST>\nGerçek kullanıcı görevi {index}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>NEVER_COPY_METADATA</ADDITIONAL_METADATA>'},
                {'step_index': 2*index+1, 'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE',
                 'content': f'Uygulama sonucu {index}', 'thinking': 'NEVER_COPY_REASONING'}])
        self.write()

    def write(self):
        self.path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in self.rows), encoding='utf-8')

    def payload(self):
        if self.client == 'claude':
            return {'session_id': self.session, 'transcript_path': str(self.path)}
        return {'conversationId': self.session, 'transcriptPath': str(self.path), 'fullyIdle': True,
                'terminationReason': 'NO_TOOL_CALL', 'error': '', 'invocationNum': 999,
                'initialNumSteps': len(self.rows), 'workspacePaths': []}

    def register(self):
        return sessions.register(self.vault, self.client, self.session, self.path, self.payload())

    def judgment(self, ident, record=True):
        evidence = sessions.packet(self.vault, ident)['evidence'][-1]
        return {'decision': 'record' if record else 'skip', 'meaningful': record,
                'reviewer_role': 'independent-episodic-reviewer', 'reason': 'Tamamlanan iş incelendi.' if record else 'Basit soru.',
                'summary': 'Yerel uygulama tamamlandı; kullanıcı kabulü bekleniyor.',
                'evidence': [{k: evidence[k] for k in ('line', 'line_sha256', 'quote')}]}

    def cli(self, event, payload=None):
        process = subprocess.run([sys.executable, '-X', 'utf8', str(Path(hooks.__file__)),
                                  '--vault', str(self.vault), '--client', self.client, '--event', event],
                                 input=json.dumps(payload or self.payload()), capture_output=True,
                                 text=True, encoding='utf-8', timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout), process.stderr


class NativeSessions(NativeFixture):
    def test_six_messages_pending_review_reopen_both_clients(self):
        for client in ('claude', 'antigravity'):
            with self.subTest(client=client):
                if client == 'antigravity': self.agy()
                result = self.register()
                ident = result['id']
                self.assertEqual(result['status'], 'pending')
                self.assertEqual(self.register()['id'], ident)
                material = sessions.packet(self.vault, ident)
                self.assertEqual(material['user_count'], 6)
                self.assertNotIn('NEVER_COPY', json.dumps(material))
                decision = self.judgment(ident)
                self.assertEqual(sessions.review(self.vault, ident, decision)['status'], 'dry_run')
                self.assertEqual(sessions.recall(self.vault), '' if client == 'claude' else previous)
                self.assertEqual(sessions.review(self.vault, ident, decision, True)['status'], 'record')
                self.assertTrue(sessions.review(self.vault, ident, decision, True)['replay'])
                previous = sessions.recall(self.vault)
                self.assertIn(decision['summary'], previous)
                fresh = 'fresh-' + client
                if client == 'claude':
                    payload = {'session_id': fresh, 'transcript_path': str(self.root / (fresh + '.jsonl'))}
                    out, _ = self.cli('SessionStart', payload)
                    self.assertIn(decision['summary'], out['hookSpecificOutput']['additionalContext'])
                    again, _ = self.cli('SessionStart', payload)
                    self.assertEqual(again, {})
                else:
                    payload = dict(self.payload(), conversationId=fresh, initialNumSteps=0,
                                   transcriptPath=str(self.root / 'brain' / fresh / '.system_generated/logs/transcript_full.jsonl'))
                    out, _ = self.cli('PreInvocation', payload)
                    self.assertIn(decision['summary'], out['injectSteps'][0]['ephemeralMessage'])
                stored = '\n'.join(p.read_text(encoding='utf-8') for p in (self.vault / sessions.INBOX / '.state').glob('*.json'))
                self.assertNotIn('Gerçek kullanıcı', stored)
                self.assertNotIn('NEVER_COPY', stored)
        self.assertFalse((self.vault / 'zihin').exists())
        self.assertFalse((self.vault / 'günlük').exists())

    def test_observed_native_history_can_reach_review_and_shared_codex_recall(self):
        self.agy()
        self.rows[0]['content'] = '<USER_REQUEST>/plan gerçek görev</USER_REQUEST>'
        extra = [
            {'source': 'MODEL', 'type': 'PLANNER_RESPONSE', 'status': 'DONE', 'tool_calls': [{'name': 'fixture'}]},
            {'source': 'MODEL', 'type': 'GENERIC', 'status': 'ERROR'},
            {'source': 'SYSTEM', 'type': 'SYSTEM_MESSAGE', 'status': 'DONE', 'content': 'NEVER_COPY_SYSTEM'},
        ]
        self.rows[1:1] = extra
        for index, row in enumerate(self.rows): row['step_index'] = index * 3
        self.write()
        source = parse(self.client, self.session, self.path)
        self.assertEqual(source['count'], 6)
        self.assertEqual(source['entries'][0]['quote'], 'gerçek görev')
        self.assertNotIn('NEVER_COPY', json.dumps(source))
        ident = self.register()['id']
        decision = self.judgment(ident)
        sessions.review(self.vault, ident, decision, True)
        from codex_hafiza import shared_reviewed_context
        self.assertIn(decision['summary'], shared_reviewed_context(self.vault))
        self.path.unlink()
        self.assertEqual(shared_reviewed_context(self.vault), '')

    def test_observed_claude_administrative_rows_are_not_evidence(self):
        for kind in ('attachment', 'atis-latch', 'last-prompt'):
            self.rows.insert(1, {'type': kind, 'sessionId': self.session, 'content': 'NEVER_COPY_ADMIN'})
        self.write()
        material = sessions.packet(self.vault, self.register()['id'])
        self.assertEqual(material['user_count'], 6)
        self.assertNotIn('NEVER_COPY', json.dumps(material))

    def test_first_five_and_no_invocation_inflation(self):
        for count in range(1, 6):
            self.rows = self.claude_rows(count); self.write()
            self.assertEqual(self.register()['status'], 'below_threshold')
        self.agy(5)
        for _ in range(3):
            self.assertEqual(self.register()['count'], 5)
        self.assertEqual(sessions.pending(self.vault), [])

    def test_duplicate_ids_count_once_conflicts_fail(self):
        self.rows.insert(1, self.rows[0]); self.write()
        self.assertEqual(parse(self.client, self.session, self.path)['count'], 6)
        self.rows[1] = dict(self.rows[0], message={'role': 'user', 'content': 'different'})
        self.write()
        with self.assertRaises(SourceError): self.register()

    def test_ag_duplicate_reordered_unknown_truncated_steps(self):
        for mutation in ('duplicate', 'reordered', 'unknown', 'truncated', 'not_done', 'generated'):
            self.agy()
            if mutation == 'duplicate': self.rows.append(self.rows[-1])
            if mutation == 'reordered': self.rows[1], self.rows[2] = self.rows[2], self.rows[1]
            if mutation == 'unknown': self.rows[-1]['type'] = 'NEW_SCHEMA'
            if mutation == 'truncated': self.rows[-1]['truncated'] = True
            if mutation == 'not_done': self.rows[-1]['status'] = 'RUNNING'
            if mutation == 'generated': self.rows[0]['source'] = 'MODEL'
            self.write()
            with self.subTest(mutation=mutation), self.assertRaises(SourceError): self.register()

    def test_successful_stop_required_and_lagging_claude_not_fabricated(self):
        self.rows.pop(); self.write()
        out, diagnostic = self.cli('Stop', dict(self.payload(), last_assistant_message='completed'))
        self.assertEqual(out, {}); self.assertIn('unready', diagnostic)
        self.assertEqual(sessions.pending(self.vault), [])
        self.agy()
        for bad in ({'fullyIdle': False}, {'terminationReason': 'ERROR'}, {'error': 'failure'}):
            with self.assertRaises(SourceError):
                sessions.register(self.vault, self.client, self.session, self.path, dict(self.payload(), **bad))
        self.assertEqual(sessions.pending(self.vault), [])

    def test_synthetic_api_error_and_tool_call_not_terminal(self):
        for change in ({'model': '<synthetic>'}, {'stop_reason': 'tool_use'}, {'isApiErrorMessage': True}):
            self.rows = self.claude_rows()
            self.rows[-1]['message'].update(change); self.write()
            with self.assertRaises(SourceError): self.register()
        self.rows = self.claude_rows()
        self.rows[-1]['message']['content'].append({'type': 'tool_use', 'name': 'tool'})
        self.write()
        with self.assertRaises(SourceError): self.register()

    def test_meta_and_tool_result_not_human_messages(self):
        self.rows = self.claude_rows(5)
        self.rows.insert(0, {'type': 'user', 'uuid': 'meta', 'sessionId': self.session,
                            'isSidechain': False, 'isMeta': True, 'message': {'role': 'user', 'content': 'generated'}})
        self.rows.insert(0, {'type': 'user', 'uuid': 'tool', 'sessionId': self.session,
                            'isSidechain': False, 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'content': 'NEVER_COPY_TOOL'}]}})
        self.write()
        self.assertEqual(self.register()['status'], 'below_threshold')

    def test_active_suffix_excluded_and_privacy_suffix_blocks_existing_receipt(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        self.rows.append({'type': 'user', 'uuid': 'u7', 'sessionId': self.session,
                          'isSidechain': False, 'message': {'role': 'user', 'content': 'NEW_ACTIVE_SUFFIX'}})
        self.write()
        self.assertNotIn('NEW_ACTIVE_SUFFIX', json.dumps(sessions.packet(self.vault, ident)))
        sessions.review(self.vault, ident, decision, True)
        self.assertIn(decision['summary'], sessions.recall(self.vault))
        self.rows[-1]['message']['content'] = 'bu konuşmayı kaydetme'; self.write()
        self.assertEqual(sessions.recall(self.vault), '')
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, decision, True)

    def test_changed_prefix_evidence_and_review_gates(self):
        ident = self.register()['id']; original = self.judgment(ident)
        for field, value in (('meaningful', False), ('reviewer_role', ''), ('summary', 'x'*4001),
                             ('summary', 'sk-' + 'a'*48), ('evidence', []), ('semantic_candidates', [])):
            decision = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaises(SourceError): sessions.review(self.vault, ident, decision, True)
        bad = dict(original, evidence=[dict(original['evidence'][0], quote='not present')])
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, bad, True)
        self.rows[0]['message']['content'] += ' changed'; self.write()
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, original, True)
        self.assertEqual(sessions.pending(self.vault)[0]['status'], 'unready')

    def test_simple_skip_is_reviewer_decision_and_replay_safe(self):
        ident = self.register()['id']; decision = self.judgment(ident, record=False)
        self.assertEqual(sessions.review(self.vault, ident, decision, True)['status'], 'skip')
        self.assertTrue(sessions.review(self.vault, ident, decision, True)['replay'])
        self.assertEqual(self.register()['status'], 'skip')
        self.assertEqual(sessions.pending(self.vault), [])
        self.assertEqual(sessions.recall(self.vault), '')
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, dict(decision, summary='changed'), True)

    def test_subagent_identity_malformed_and_symlink_guards(self):
        for change in ({'isSidechain': True}, {'sessionId': 'other'}, {'agentId': 'worker'}):
            self.rows = self.claude_rows(); self.rows[0].update(change); self.write()
            with self.assertRaises(SourceError): self.register()
        self.rows = self.claude_rows(); self.write()
        self.path.write_bytes(self.path.read_bytes().rstrip(b'\n'))
        with self.assertRaises(SourceError): self.register()
        self.write()
        with self.path.open('a', encoding='utf-8') as stream: stream.write('{broken}\n')
        with self.assertRaises(SourceError): self.register()
        self.write()
        link = self.root / 'link'
        try: link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError): return
        with self.assertRaises(SourceError): parse(self.client, self.session, link / self.path.name)

    def test_stop_cli_and_actual_preiinvocation_json(self):
        self.agy()
        out, diagnostic = self.cli('Stop')
        self.assertEqual(out, {}); self.assertIn('pending', diagnostic)
        out, _ = self.cli('PreInvocation')
        context = out['injectSteps'][0]['ephemeralMessage']
        self.assertLessEqual(len(context), hooks.CONTEXT_BUDGET)
        self.assertNotIn('NEVER_COPY', context)
        out, _ = self.cli('PreInvocation', dict(self.payload(), invocationNum=10000))
        self.assertEqual(out, {})

    def test_receipt_tamper_and_source_mutation_before_publish(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        sessions.review(self.vault, ident, decision, True)
        path = self.vault / sessions.INBOX / (ident + '.json')
        receipt = json.loads(path.read_text(encoding='utf-8')); receipt['summary'] = 'forged'
        path.write_text(json.dumps(receipt), encoding='utf-8')
        self.assertEqual(sessions.recall(self.vault), '')

    def test_private_prompt_lag_blocks_existing_pending_without_persisting_prompt(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        output, diagnostic = self.cli('UserPromptSubmit', dict(self.payload(), prompt='bunu hafızaya kaydetme'))
        self.assertEqual(output, {})
        self.assertIn('privacy_blocked', diagnostic)
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, decision, True)
        state = self.vault / sessions.INBOX / '.state'
        self.assertNotIn('bunu hafızaya', ''.join(p.read_text(encoding='utf-8') for p in state.glob('*.json')))

    def test_secret_source_and_direct_threshold_gate(self):
        self.rows[0]['message']['content'] = 'api_key=fixture-secret'; self.write()
        with self.assertRaises(SourceError): self.register()
        self.rows = self.claude_rows(5); self.write()
        source = parse(self.client, self.session, self.path)
        ident = sessions.snapshot_id(source)
        item = {k: source[k] for k in ('client', 'session', 'path', 'end_line', 'prefix_sha256', 'count', 'message_ids')}
        item.update(version=1, id=ident, status='pending', created_ns=1)
        with sessions.locked(self.vault) as (_, state): sessions.atomic(state / (ident + '.json'), item)
        with self.assertRaises(SourceError): sessions.packet(self.vault, ident)
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, {}, True)

    def test_bad_line_hash_and_wrong_source_line_rejected(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        for changed in ({'line_sha256': '0'*64}, {'line': 999}, {'line': True}):
            bad = dict(decision, evidence=[dict(decision['evidence'][0], **changed)])
            with self.assertRaises(SourceError): sessions.review(self.vault, ident, bad, True)

    def test_unknown_hook_schema_is_visible_and_stop_never_blocks(self):
        self.rows.append({'type': 'future-schema'}); self.write()
        output, diagnostic = self.cli('Stop')
        self.assertEqual(output, {})
        self.assertIn('unready', diagnostic)
        self.assertNotIn('decision', output)
        self.assertEqual(sessions.pending(self.vault), [])

    def test_claude_prompt_context_format_and_model_advisor_off(self):
        import jev_retrieval
        import jev_client
        original = jev_retrieval.mode
        (self.vault / 'komuta').mkdir()
        (self.vault / 'bilgi').mkdir()
        (self.vault / 'komuta/jev.json').write_text('{"mode":"on"}', encoding='utf-8')
        with patch.object(jev_client, 'evaluate', side_effect=AssertionError('model forbidden')):
            out, _ = hooks.hook(self.vault, self.client, 'UserPromptSubmit', dict(self.payload(), prompt='Yerel işte devam edelim'))
        self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
        self.assertIs(jev_retrieval.mode, original)

    def test_symlink_queue_rejected_without_outside_write(self):
        outside = self.root / 'outside'; outside.mkdir()
        inbox = self.vault / sessions.INBOX
        inbox.parent.mkdir(parents=True)
        try: inbox.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError): return
        with self.assertRaises(SourceError): self.register()
        self.assertEqual(list(outside.iterdir()), [])

    def test_new_completed_prefix_supersedes_only_pending(self):
        old = self.register()['id']
        self.rows = self.claude_rows(7); self.write()
        new = self.register()['id']
        self.assertNotEqual(new, old)
        self.assertEqual([row['id'] for row in sessions.pending(self.vault)], [new])
        with self.assertRaises(SourceError): sessions.packet(self.vault, old)

    def test_antigravity_identity_and_privacy_suffix(self):
        self.agy()
        ident = self.register()['id']; decision = self.judgment(ident)
        self.rows.append({'step_index': 12, 'source': 'USER_EXPLICIT', 'type': 'USER_INPUT',
                          'status': 'DONE', 'content': '<USER_REQUEST>bunu hafızaya kaydetme</USER_REQUEST>'})
        self.write()
        with self.assertRaises(SourceError): sessions.review(self.vault, ident, decision, True)
        with self.assertRaises(SourceError): parse(self.client, 'wrong-session', self.path)


    def test_long_review_summary_recalled_as_bounded_excerpt(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        decision['summary'] = 'Anlamlı sonuç. ' * 250
        sessions.review(self.vault, ident, decision, True)
        recalled = sessions.recall(self.vault, budget=600)
        self.assertIn('Anlamlı sonuç.', recalled)
        self.assertIn('summary truncated', recalled)
        self.assertLessEqual(len(recalled), 600)

    def test_new_actual_user_turn_reopens_context_without_invocation_inflation(self):
        self.agy()
        out, _ = self.cli('PreInvocation')
        self.assertIn('injectSteps', out)
        repeated = dict(self.rows[-2], step_index=12)
        self.rows.append(repeated); self.write()
        out, _ = self.cli('PreInvocation')
        self.assertIn('injectSteps', out)
        self.assertEqual(parse(self.client, self.session, self.path)['count'], 7)

    def test_terminal_metadata_error_cannot_register_success(self):
        self.rows.append({'type': 'system', 'sessionId': self.session, 'subtype': 'api_error', 'error': 'fixture failure'})
        self.write()
        with self.assertRaises(SourceError): self.register()



if __name__ == '__main__':
    unittest.main()
