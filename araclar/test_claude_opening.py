"""Claude opening delivery, retention, and sentence-safe synthetic fixtures."""
import datetime as dt
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import client_hafiza as hooks
import client_sessions as sessions
import codex_hafiza as codex
import test_client_sessions as native_fixtures


class ClaudeOpening(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.vault = Path(directory.name).resolve()
        self.sections = {
            'brief': 'AÇILIŞ HATIRLATMASI\n\n## Güncel, teyitli açık işler\n- Kaynağı doğrula.',
            'latest': 'Son oturum makbuzları:\n- Önceki görev tamamlandı.',
            'recall': 'Episodic candidate (claude, fixture): İncelenmiş oturum özeti.',
        }
        patches = [
            patch.object(codex, 'opening_brief', side_effect=lambda *a, **k: self.sections['brief']),
            patch.object(codex, 'latest_session_section', side_effect=lambda *a, **k: self.sections['latest']),
            patch.object(hooks, 'recall', side_effect=lambda *a, **k: self.sections['recall']),
            patch.object(hooks, 'claude_task_package', return_value={'text': '', 'selected_ids': []}),
            patch('fayda_olc.record_delivery'),
        ]
        for mock in patches:
            mock.start()
            self.addCleanup(mock.stop)

    def event(self, name, session='same-session', prompt='Kaynağı incele', source=None):
        payload = {'session_id': session, 'transcript_path': str(self.vault / (session + '.jsonl'))}
        if name == 'UserPromptSubmit':
            payload['prompt'] = prompt
        if source is not None:
            return hooks.context(self.vault, 'claude', session, source, payload, name)
        output, _ = hooks.hook(self.vault, 'claude', name, payload)
        return output.get('hookSpecificOutput', {}).get('additionalContext', '')

    def assert_full_opening(self, text):
        for section in self.sections.values():
            self.assertIn(section, text)
        self.assertLessEqual(len(text), hooks.CONTEXT_BUDGET)

    def test_session_start_without_prompt_suppresses_same_session_prompts(self):
        self.assert_full_opening(self.event('SessionStart'))
        self.assertEqual(self.event('UserPromptSubmit'), '')
        self.assertEqual(self.event('UserPromptSubmit', prompt='Başka bir görevi incele'), '')

    def test_lagging_transcript_does_not_repeat_opening(self):
        source = {'latest_user': {'quote': 'Önceki görev', 'message_id': 'old-turn'}, 'entries': []}
        self.assert_full_opening(self.event('SessionStart', source=source))
        self.assertEqual(self.event('UserPromptSubmit', source=source), '')
        self.assertEqual(self.event('UserPromptSubmit', source=source, prompt='Yeni görev'), '')

    def test_changed_section_updates_even_with_same_prompt_and_native_turn_id(self):
        source = {'latest_user': {'quote': 'Kaynağı incele', 'message_id': 'same-turn'}, 'entries': []}
        self.assert_full_opening(self.event('SessionStart', source=source))
        self.assertEqual(self.event('UserPromptSubmit', source=source), '')
        for key in self.sections:
            with self.subTest(section=key):
                old = self.sections[key]
                self.sections[key] = old + '\nYeni doğrulanan bilgi.'
                text = self.event('UserPromptSubmit', source=source)
                self.assertIn('Güncellendi', text)
                self.assertIn(self.sections[key], text)
                for other, section in self.sections.items():
                    if other != key:
                        self.assertNotIn(section, text)
                self.assertEqual(self.event('UserPromptSubmit', source=source), '')

    def test_first_prompt_without_session_start_receives_full_opening(self):
        self.assert_full_opening(self.event('UserPromptSubmit'))
        self.assertEqual(self.event('UserPromptSubmit'), '')

    def test_same_session_does_not_repeat_after_turn_or_time_refresh(self):
        self.assert_full_opening(self.event('SessionStart'))
        for turn in range(hooks.REFRESH_TURNS + 2):
            self.assertEqual(self.event('UserPromptSubmit', prompt=f'Kaynağı incele {turn}'), '')
        with patch.object(hooks.time, 'time', return_value=10**12):
            self.assertEqual(self.event('UserPromptSubmit', prompt='Son bir inceleme yap'), '')
        self.assert_full_opening(self.event('UserPromptSubmit', session='other-session'))


class ClaudeBoundaries(unittest.TestCase):
    def test_truncation_keeps_complete_lines_or_sentences(self):
        cases = [
            ('Tam ilk madde\nİkinci madde sığmayacak kadar uzun.', 'Tam ilk madde'),
            ('İlk cümle tamam. Sonraki cümle sığmayacak kadar uzun.', 'İlk cümle tamam.'),
            ('İlk cümle tamam! Sonraki cümle sığmayacak kadar uzun.', 'İlk cümle tamam!'),
        ]
        for text, complete in cases:
            with self.subTest(text=text):
                limit = len(complete) + 8
                shortened = hooks.boundary_text(text, limit)
                self.assertEqual(shortened, complete + '\n…')
                self.assertLessEqual(len(shortened), limit)
        self.assertEqual(hooks.boundary_text('Tek cümle içindeki kelimeyi bölme', 18), '…')

    def test_long_token_and_tiny_budgets_never_emit_partial_word(self):
        for limit in (0, 1, 2, 10, 40):
            with self.subTest(limit=limit):
                text = hooks.boundary_text('uzunkelime' * 20, limit)
                self.assertEqual(text, '…' if limit else '')
                self.assertLessEqual(len(text), limit)
        self.assertEqual(hooks.boundary_text('Tam cümle.', 10), 'Tam cümle.')

    def test_verified_task_larger_than_old_brief_budget_precedes_receipts(self):
        from is_ve_ders import put
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            evidence = 'Sentetik proje teslimindeki açık işi kaynak üzerinden doğrula.'
            (vault / 'kaynak.md').write_text(evidence, encoding='utf-8')
            step = 'Her kabul koşulunu kaynak kaydı ve teslim çıktısıyla karşılaştır. ' * 9
            verified = dt.date.today().isoformat()
            put(vault, 'task', dict(id='synthetic-task', title='Sentetik proje teslimi',
                status='active', next_step=step, source_path='kaynak.md', evidence=evidence,
                actor='test', last_verified=verified))
            task_line = f'- Sentetik proje teslimi: {step} (kaynak: kaynak.md; teyit: {verified})'
            brief = codex.opening_brief(vault)
            self.assertGreater(len(brief), 450)
            self.assertLess(len(brief), hooks.CONTEXT_BUDGET)
            history = 'Son oturum makbuzları:\n' + 'Önceki görev ayrıntısı tamamlandı. ' * 150
            with (patch.object(codex, 'latest_session_section', return_value=history),
                  patch.object(hooks, 'recall', return_value='Episodic candidate (claude, old): Eski özet.'),
                  patch('fayda_olc.record_delivery')):
                text = hooks.context(vault, 'claude', 'synthetic', None, {}, 'SessionStart')
            self.assertIn(task_line, text)
            self.assertLess(text.index(task_line), text.index('Son oturum makbuzları:'))
            self.assertLessEqual(len(text), hooks.CONTEXT_BUDGET)
            self.assertTrue(text.endswith('…'))

    def test_context_pruning_bounds_age_and_count_without_removing_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            _, state = sessions.layout(vault)
            now = 2_000_000_000

            def entry(session, age, client='claude', excluded=False):
                path = sessions.policy_path(state, client, session)
                sessions.atomic(path, dict(client=client, session=session, excluded=excluded))
                os.utime(path, (now - age, now - age))
                return path

            active = entry('active', 31 * 86400)
            expired = entry('expired', 31 * 86400)
            oldest = entry('oldest-recent', 3)
            recent = entry('recent', 2)
            newest = entry('newest', 1)
            privacy = entry('privacy', 31 * 86400, excluded=True)
            other_client = entry('other-client', 31 * 86400, client='antigravity')
            with (patch.object(hooks.time, 'time', return_value=now),
                  patch.object(hooks, 'CLAUDE_STATE_LIMIT', 3)):
                hooks.prune_claude_context(state, active)
            self.assertFalse(expired.exists())
            self.assertFalse(oldest.exists())
            for path in (active, recent, newest, privacy, other_client):
                self.assertTrue(path.exists(), path.name)
            self.assertTrue(sessions.load(privacy)['excluded'])

    def test_latest_session_reader_uses_boundary_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            (vault / 'zihin').mkdir()
            section = ('## 2026-10-15\nTamamlanan görev doğrulandı. '
                       'Sonraki açıklama bütçeye sığmayacak kadar uzatılan sözcüklerle devam eder. ' * 8)
            (vault / 'zihin/son-oturum.md').write_text(section, encoding='utf-8')
            limit = 130
            legacy = codex.latest_session_section(vault, limit=limit, today=dt.date(2026, 10, 15))
            text = codex.latest_session_section(vault, limit=limit, today=dt.date(2026, 10, 15),
                                                truncate=hooks.boundary_text)
            self.assertIn('[Kesildi;', legacy)
            self.assertNotIn('[Kesildi;', text)
            self.assertIn('Tamamlanan görev doğrulandı.', text)
            self.assertTrue(text.endswith('doğrulandı.\n…'))
            self.assertLessEqual(len(text), limit)


class ClaudeRecallBoundaries(native_fixtures.NativeFixture):
    def test_validated_recall_uses_boundary_callback_and_keeps_budget(self):
        ident = self.register()['id']
        decision = self.judgment(ident)
        decision['summary'] = 'İncelenen görev tamamlandı. ' * 100
        sessions.review(self.vault, ident, decision, True)
        legacy = sessions.recall(self.vault, budget=260)
        text = sessions.recall(self.vault, budget=260, truncate=hooks.boundary_text)
        self.assertIn('[summary truncated]', legacy)
        self.assertNotIn('[summary truncated]', text)
        self.assertIn('Episodic candidate (claude, ' + ident + '):', text)
        self.assertTrue(text.endswith('tamamlandı.\n…'))
        self.assertLessEqual(len(text), 260)
        self.rows[0]['message']['content'] += ' Kaynak değişti.'
        self.write()
        self.assertEqual(sessions.recall(self.vault, budget=260, truncate=hooks.boundary_text), '')


class ClaudeSnapshotDelivery(unittest.TestCase):
    def test_hidden_journal_change_updates_once_despite_identical_excerpt(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            (vault / 'zihin').mkdir()
            journal = vault / 'zihin/son-oturum.md'
            prefix = '## ' + dt.date.today().isoformat() + '\n' + 'Tamamlanan iş doğrulandı. ' * 40
            journal.write_text(prefix + 'Son aşama bekliyor.', encoding='utf-8')
            before = codex.latest_session_section(vault, limit=hooks.LATEST_SESSION_BUDGET,
                                                  truncate=hooks.boundary_text)
            source = {'latest_user': {'quote': 'Kaynağı incele', 'message_id': 'same-turn'}, 'entries': []}
            payload = {'prompt': 'Kaynağı incele'}
            with (patch.object(hooks, 'claude_task_package', return_value={'text': '', 'selected_ids': []}),
                  patch('fayda_olc.record_delivery')):
                opening = hooks.context(vault, 'claude', 'hidden-change', None, {}, 'SessionStart')
                self.assertIn(before, opening)
                self.assertEqual(hooks.context(vault, 'claude', 'hidden-change', source, payload,
                                               'UserPromptSubmit'), '')
                journal.write_text(prefix + 'Son aşama tamamlandı.', encoding='utf-8')
                after = codex.latest_session_section(vault, limit=hooks.LATEST_SESSION_BUDGET,
                                                     truncate=hooks.boundary_text)
                self.assertEqual(before, after, 'The changed sentence must be outside the rendered excerpt.')
                changed = hooks.context(vault, 'claude', 'hidden-change', source, payload, 'UserPromptSubmit')
                self.assertIn('Güncellendi — Son oturum özeti:', changed)
                self.assertIn(after, changed)
                self.assertNotIn('AÇILIŞ HATIRLATMASI', changed)
                self.assertEqual(hooks.context(vault, 'claude', 'hidden-change', source, payload,
                                               'UserPromptSubmit'), '')

    def test_interleaved_same_turn_commits_only_inner_current_snapshot(self):
        for change_snapshot in (False, True):
            with self.subTest(change_snapshot=change_snapshot), tempfile.TemporaryDirectory() as directory:
                vault = Path(directory).resolve()
                (vault / 'zihin').mkdir()
                journal = vault / 'zihin/son-oturum.md'
                prefix = '## ' + dt.date.today().isoformat() + '\n'
                old_text, new_text = 'İlk kaynak durumu bekliyor.', 'Yeni kaynak durumu tamamlandı.'
                journal.write_text(prefix + old_text, encoding='utf-8')
                source = {'latest_user': {'quote': 'Kaynağı incele', 'message_id': 'same-turn'}, 'entries': []}
                payload = {'prompt': 'Kaynağı incele'}
                session = 'interleaved'
                state = vault / sessions.INBOX / '.state'
                target = sessions.policy_path(state, 'claude', session)
                reader = hooks.claude_opening_parts
                snapshots, inner_outputs, inner_states = [], [], []

                def interleave(*args, **kwargs):
                    snapshot = reader(*args, **kwargs)
                    snapshots.append(snapshot)
                    if len(snapshots) == 1:
                        if change_snapshot:
                            journal.write_text(prefix + new_text, encoding='utf-8')
                        inner_outputs.append(hooks.context(vault, 'claude', session, source, payload,
                                                           'UserPromptSubmit'))
                        inner_states.append(target.read_bytes())
                    return snapshot

                with (patch.object(hooks, 'claude_task_package', return_value={'text': '', 'selected_ids': []}),
                      patch('fayda_olc.record_delivery'),
                      patch.object(hooks, 'claude_opening_parts', side_effect=interleave)):
                    outer = hooks.context(vault, 'claude', session, source, payload, 'UserPromptSubmit')
                expected_text = new_text if change_snapshot else old_text
                self.assertIn(expected_text, inner_outputs[0])
                self.assertEqual(outer, '')
                self.assertGreaterEqual(len(snapshots), 3, 'The outer reader must retry after the inner commit.')
                self.assertEqual(target.read_bytes(), inner_states[0], 'The outer call must not overwrite inner state.')
                final = sessions.load(target)
                self.assertEqual(final['user_turns'], 1)
                self.assertEqual(final['opening_hashes'], {key: version for key, _, version in snapshots[-1]})
                if change_snapshot:
                    old_version = next(version for key, _, version in snapshots[0] if key == 'latest')
                    self.assertNotEqual(final['opening_hashes']['latest'], old_version)
                    self.assertNotIn(old_text, inner_outputs[0])


if __name__ == '__main__':
    unittest.main()
