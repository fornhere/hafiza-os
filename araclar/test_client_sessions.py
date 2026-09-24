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
from client_transcripts import MAX_LINE, MAX_LINES, MAX_SOURCE, SourceError, parse


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

    def semantic_decision(self, ident, count=1, record=True):
        decision = self.judgment(ident, record=record)
        decision['semantic_candidates'] = [
            {'statement': f'Kullanıcı kalıcı tercih {index} belirtti.',
             'subject_key': f'user.preference.{index}',
             'evidence': 'Kalıcı tercih: kısa özet kullan.'}
            for index in range(count)]
        return decision

    def cli(self, event, payload=None):
        process = subprocess.run([sys.executable, '-X', 'utf8', str(Path(hooks.__file__)),
                                  '--vault', str(self.vault), '--client', self.client, '--event', event],
                                 input=json.dumps(payload or self.payload()), capture_output=True,
                                 text=True, encoding='utf-8', timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout), process.stderr


class NativeSessions(NativeFixture):
    def test_verified_semantic_candidate_queues_and_source_note_replays(self):
        from hafiza import CANDIDATE_PATH, load_jsonl
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        decision = self.semantic_decision(ident)
        self.assertEqual(sessions.review(self.vault, ident, decision)['semantic_candidates'][0]['status'], 'accepted')
        result = sessions.review(self.vault, ident, decision, True)
        self.assertEqual(result['semantic_candidates'][0]['queue_result'], 'queued')
        note = self.vault / sessions.INBOX / (ident + '.md')
        self.assertIn('Durum: episodik makbuz; kanonik değil', note.read_text(encoding='utf-8'))
        self.assertIn(decision['semantic_candidates'][0]['evidence'], note.read_text(encoding='utf-8'))
        queued = load_jsonl(self.vault / CANDIDATE_PATH)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]['source_path'], str(note.relative_to(self.vault)))
        self.assertEqual(queued[0]['source_anchor'], 'Kullanıcı beyanı')
        self.assertEqual(queued[0]['proposed_by'], 'claude-review')
        self.assertNotIn('evidence_source', queued[0])
        self.assertTrue(sessions.review(self.vault, ident, decision, True)['replay'])
        self.assertEqual(load_jsonl(self.vault / CANDIDATE_PATH), queued)
        note.write_text(note.read_text(encoding='utf-8') + 'tampered', encoding='utf-8')
        self.assertEqual(sessions.recall(self.vault), '')
        with self.assertRaisesRegex(SourceError, 'receipt_mutated'):
            sessions.review(self.vault, ident, decision, True)

    def test_claude_candidate_promotes_only_with_intact_user_evidence(self):
        import hafiza as h
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        sessions.review(self.vault, ident, self.semantic_decision(ident), True)
        candidate = h.load_jsonl(self.vault / h.CANDIDATE_PATH)[0]
        self.assertTrue(sessions.verify_candidate_evidence(self.vault, candidate['source_path'], candidate['evidence']))
        with self.assertRaisesRegex(SourceError, 'evidence_not_user_message'):
            sessions.verify_candidate_evidence(self.vault, candidate['source_path'], 'Gerçek kullanıcı görevi yok')
        with self.assertRaisesRegex(SourceError, 'claude_evidence_source_required'):
            sessions.verify_candidate_evidence(self.vault, 'zihin/baska.md', candidate['evidence'])
        h.promote_candidate(self.vault, candidate['candidate_id'], memory_id='claude-short-summary',
                            reviewed_by='codex-consolidator', apply=True)
        self.assertEqual(['claude-short-summary'], [r['memory_id'] for r in h.load_catalog(self.vault)])

    def test_claude_candidate_promotion_blocked_after_source_mutation(self):
        import hafiza as h
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        sessions.review(self.vault, ident, self.semantic_decision(ident), True)
        candidate = h.load_jsonl(self.vault / h.CANDIDATE_PATH)[0]
        self.rows[0]['message']['content'] = 'Tamamen farklı istek.'
        self.write()
        with self.assertRaisesRegex(ValueError, 'Claude adayının'):
            h.promote_candidate(self.vault, candidate['candidate_id'], memory_id='claude-short-summary',
                                reviewed_by='codex-consolidator', apply=True)
        self.assertEqual([], h.load_catalog(self.vault))

    def test_invalid_category_is_dropped_not_rejected(self):
        from hafiza import CANDIDATE_PATH, load_jsonl
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        decision = self.semantic_decision(ident)
        decision['semantic_candidates'][0]['category'] = 'uydurma-kategori'
        result = sessions.review(self.vault, ident, decision, True)
        self.assertEqual('accepted', result['semantic_candidates'][0]['status'])
        self.assertTrue(result['semantic_candidates'][0]['category_dropped'])
        self.assertIsNone(load_jsonl(self.vault / CANDIDATE_PATH)[0].get('category'))

    def test_semantic_rejects_assistant_quote_but_keeps_valid_candidate(self):
        from hafiza import CANDIDATE_PATH, load_jsonl
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        decision = self.semantic_decision(ident)
        decision['semantic_candidates'].append(dict(statement='Asistanın sözünü kullanıcı tercihi say.',
            subject_key='user.invalid', evidence='Uygulama sonucu 5'))
        result = sessions.review(self.vault, ident, decision, True)['semantic_candidates']
        self.assertEqual([item['status'] for item in result], ['accepted', 'rejected'])
        self.assertIn('evidence_not_user_message', result[1]['reasons'])
        self.assertEqual(len(load_jsonl(self.vault / CANDIDATE_PATH)), 1)

    def test_semantic_skip_limit_and_secret_are_individual_rejections(self):
        from hafiza import CANDIDATE_PATH, load_jsonl
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        decision = self.semantic_decision(ident, record=False)
        result = sessions.review(self.vault, ident, decision, True)['semantic_candidates']
        self.assertIn('skip_decision', result[0]['reasons'])
        self.assertFalse((self.vault / CANDIDATE_PATH).exists())
        self.assertFalse((self.vault / sessions.INBOX / (ident + '.md')).exists())
        self.rows = self.claude_rows()
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.rows[-1]['message']['content'][1]['text'] = 'Yeni tamamlanan iş'
        self.write()
        ident = self.register()['id']
        decision = self.semantic_decision(ident, count=6)
        decision['semantic_candidates'][1]['statement'] = 'sk-' + 'a' * 48
        result = sessions.review(self.vault, ident, decision, True)['semantic_candidates']
        self.assertIn('secret_candidate', result[1]['reasons'])
        self.assertIn('candidate_limit', result[5]['reasons'])
        self.assertEqual(len(load_jsonl(self.vault / CANDIDATE_PATH)), 4)

    def test_semantic_source_note_conflict_blocks_queue(self):
        from hafiza import CANDIDATE_PATH
        self.rows[0]['message']['content'] = 'Kalıcı tercih: kısa özet kullan.'
        self.write()
        ident = self.register()['id']
        note = self.vault / sessions.INBOX / (ident + '.md')
        note.write_text('another decision', encoding='utf-8')
        with self.assertRaisesRegex(SourceError, 'receipt_conflict'):
            sessions.review(self.vault, ident, self.semantic_decision(ident), True)
        self.assertFalse((self.vault / CANDIDATE_PATH).exists())

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
            {'source': 'SYSTEM_SDK', 'type': 'EPHEMERAL_MESSAGE', 'status': 'DONE', 'content': 'NEVER_COPY_INJECTED_CONTEXT'},
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

    def test_actual_preinvocation_output_is_not_user_or_review_evidence(self):
        self.agy()
        out, _ = self.cli('PreInvocation')
        context = out['injectSteps'][0]['ephemeralMessage']
        injected = {'source': 'SYSTEM_SDK', 'type': 'EPHEMERAL_MESSAGE',
                    'status': 'DONE', 'content': context}
        self.rows.insert(-1, injected)
        for index, row in enumerate(self.rows): row['step_index'] = index * 2
        self.write()
        out, diagnostic = self.cli('Stop')
        self.assertEqual(out, {})
        self.assertIn('pending', diagnostic)
        ident = sessions.pending(self.vault)[0]['id']
        material = sessions.packet(self.vault, ident)
        self.assertEqual(material['user_count'], 6)
        self.assertNotIn(context, [e['quote'] for e in material['evidence']])
        decision = self.judgment(ident)
        sessions.review(self.vault, ident, decision, True)
        self.assertIn(decision['summary'], sessions.recall(self.vault))
        for change in ({'source': 'UNKNOWN_SDK'}, {'type': 'UNKNOWN_MESSAGE'}, {'status': 'ERROR'}):
            original = dict(injected)
            injected.update(change)
            self.write()
            with self.subTest(change=change), self.assertRaises(SourceError):
                parse(self.client, self.session, self.path)
            injected.clear(); injected.update(original)

    def test_review_cli_accepts_documented_file_and_existing_inline_json(self):
        ident = self.register()['id']
        decision = self.judgment(ident)
        decision_path = self.root / 'Türkçe karar.json'
        decision_path.write_text(json.dumps(decision, ensure_ascii=False), encoding='utf-8')
        command = [sys.executable, '-X', 'utf8', sessions.__file__, '--vault', str(self.vault),
                   'review', '--id', ident, '--input-json']
        for value in (str(decision_path), decision_path.name, json.dumps(decision, ensure_ascii=False)):
            result = subprocess.run(command + [value], cwd=self.root, text=True, encoding='utf-8', capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'dry_run')
            self.assertEqual(sessions.recall(self.vault), '')
        result = subprocess.run(command + [str(decision_path), '--apply'], text=True,
                                encoding='utf-8', capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'record')
        self.assertIn(decision['summary'], sessions.recall(self.vault))

    def test_observed_claude_administrative_rows_are_not_evidence(self):
        for kind in ('attachment', 'atis-latch', 'last-prompt'):
            self.rows.insert(1, {'type': kind, 'sessionId': self.session, 'content': 'NEVER_COPY_ADMIN'})
        self.write()
        material = sessions.packet(self.vault, self.register()['id'])
        self.assertEqual(material['user_count'], 6)
        self.assertNotIn('NEVER_COPY', json.dumps(material))

    def test_claude_new_metadata_types_and_boundary_preserve_terminal(self):
        kinds = ('custom-title', 'bridge-session', 'agent-name', 'ai-title', 'mode',
                 'pr-link', 'file-history-delta', 'permission-mode', 'relocated',
                 'cost-state', 'future-meta')
        self.rows = self.claude_rows()
        self.rows[1:1] = [
            {'type': kind, 'sessionId': self.session, 'content': 'NEVER_COPY_METADATA'}
            for kind in kinds
        ]
        self.rows.append({'type': 'future-meta', 'sessionId': self.session,
                          'content': 'NEVER_COPY_TRAILING_METADATA'})
        self.write()
        source = parse(self.client, self.session, self.path)
        self.assertEqual(source['count'], 6)
        self.assertTrue(source['terminal'])
        self.assertEqual(source['total_lines'], 2 * 6 + len(kinds) + 1)
        self.assertNotIn('NEVER_COPY', json.dumps(source))
        prefix = parse(self.client, self.session, self.path, end_line=2)
        self.assertEqual(prefix['count'], 1)
        self.assertFalse(prefix['terminal'])
        self.assertEqual(self.register()['status'], 'pending')

    def test_claude_image_and_document_blocks_keep_only_text(self):
        self.rows[0]['message']['content'] = [
            {'type': 'image', 'source': {'type': 'base64', 'data': 'NEVER_COPY_IMAGE'}},
            {'type': 'document', 'source': 'NEVER_COPY_DOCUMENT'},
            {'type': 'text', 'text': 'Görseli özetle'},
        ]
        self.rows[-1]['message']['content'].insert(1, {'type': 'image', 'source': 'NEVER_COPY_IMAGE'})
        self.rows[-1]['message']['content'].insert(2, {'type': 'document', 'source': 'NEVER_COPY_DOCUMENT'})
        self.write()
        source = parse(self.client, self.session, self.path)
        self.assertEqual(source['count'], 6)
        self.assertEqual(source['latest_user']['quote'], 'Gerçek kullanıcı görevi 5')
        self.assertEqual(source['entries'][0]['quote'], 'Görseli özetle')
        self.assertNotIn('NEVER_COPY', json.dumps(source))
        self.assertEqual(self.register()['status'], 'pending')

    def test_claude_task_notification_is_not_a_user_message(self):
        self.rows.insert(1, {'type': 'user', 'uuid': 'notice-1', 'sessionId': self.session,
                             'isSidechain': False, 'message': {'role': 'user', 'content':
                             '<task-notification>\n<task-id>x</task-id>\n<status>completed</status>\n</task-notification>'}})
        self.write()
        source = parse(self.client, self.session, self.path)
        self.assertEqual(source['count'], 6)
        self.assertNotIn('task-notification', json.dumps([e['quote'] for e in source['entries'] if e['role'] == 'user']))

    def test_claude_large_tool_result_and_source_limits(self):
        self.rows.insert(1, {'type': 'user', 'uuid': 'tool-large', 'sessionId': self.session,
                             'isSidechain': False, 'message': {'role': 'user', 'content': [
                                 {'type': 'tool_result', 'content': 'x' * (1024 * 1024)}]}})
        self.rows.insert(2, {'type': 'future-meta', 'sessionId': self.session,
                             'content': 'y' * (8 * 1024 * 1024)})
        self.write()
        self.assertGreater(self.path.stat().st_size, 9 * 1024 * 1024)
        source = parse(self.client, self.session, self.path)
        self.assertEqual(source['count'], 6)
        self.assertTrue(source['terminal'])
        self.assertEqual(self.register()['status'], 'pending')
        self.rows[2]['content'] = 'y' * MAX_LINE
        self.write()
        with self.assertRaisesRegex(SourceError, '^line_too_large$'):
            parse(self.client, self.session, self.path)
        with self.path.open('wb') as stream:
            stream.truncate(MAX_SOURCE + 1)
        with self.assertRaisesRegex(SourceError, '^source_size_or_type$'):
            parse(self.client, self.session, self.path)
        with patch('client_transcripts.read_bytes', return_value=b'{"type":"future-meta"}\n' * (MAX_LINES + 1)):
            with self.assertRaisesRegex(SourceError, '^invalid_source_boundary$'):
                parse(self.client, self.session, self.path)

    def test_claude_metadata_and_message_security_guards(self):
        mutations = (
            (0, {'isSidechain': True}, 'subagent_source'),
            (0, {'sessionId': 'wrong'}, 'source_identity_mismatch'),
            (0, {'message': {'role': 'assistant', 'content': 'wrong'}}, 'unknown_claude_message'),
        )
        for index, change, error in mutations:
            self.rows = self.claude_rows()
            self.rows[index].update(change)
            self.write()
            with self.subTest(error=error), self.assertRaisesRegex(SourceError, '^' + error + '$'):
                parse(self.client, self.session, self.path)
        for change, error in (({'isSidechain': True}, 'subagent_source'),
                              ({'sessionId': 'wrong'}, 'source_identity_mismatch'),
                              ({'truncated': True}, 'truncated_record')):
            self.rows = self.claude_rows()
            self.rows.insert(1, dict({'type': 'future-meta', 'sessionId': self.session}, **change))
            self.write()
            with self.subTest(metadata=error), self.assertRaisesRegex(SourceError, '^' + error + '$'):
                parse(self.client, self.session, self.path)
        self.rows = self.claude_rows()
        self.rows[0]['message']['content'] = [
            {'type': 'text', 'text': 'Gerçek istek'}, {'type': 'future-block', 'data': 'ignored?'}]
        self.write()
        with self.assertRaisesRegex(SourceError, '^unknown_content_block$'):
            parse(self.client, self.session, self.path)
        self.rows = self.claude_rows()
        self.write()
        with self.path.open('ab') as stream:
            stream.write(b'{"type":"future-meta","type":"future-meta"}\n')
        with self.assertRaisesRegex(SourceError, '^invalid_json$'):
            parse(self.client, self.session, self.path)

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
                             ('summary', 'sk-' + 'a'*48), ('evidence', []), ('semantic_candidates', {})):
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
        self.rows.append({'type': 'user', 'sessionId': self.session, 'isSidechain': False,
                          'message': {'role': 'user', 'content': 'missing uuid'}}); self.write()
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

    def test_recall_skips_own_session_and_stale_receipts(self):
        ident = self.register()['id']; decision = self.judgment(ident)
        sessions.review(self.vault, ident, decision, True)
        self.assertIn(decision['summary'], sessions.recall(self.vault))
        self.assertEqual(sessions.recall(self.vault, exclude=(self.client, self.session)), '')
        self.assertEqual(sessions.recall(self.vault, max_age_days=0), '')

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
