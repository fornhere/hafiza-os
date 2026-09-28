"""Reserved opt-out marker tests use synthetic native transcripts only."""
import json
from pathlib import Path
import tempfile
import unittest

import capture_source as capture
import client_transcripts as native


class PrivacyMarkerTests(unittest.TestCase):
    MARKERS = (
        '[kaydetme]',
        '[kaydetme] Bu konuşmayı kalıcı hafızaya aktarma.',
        'Sentetik bilgi hazır.\n  [KAYDETME]\nİncelemeye devam et.',
    )
    EXAMPLES = (
        '`[kaydetme]`',
        '```text\n[kaydetme]\n```',
        '"[kaydetme]"',
        '“[kaydetme]”',
        '> [kaydetme]',
        'Belgede `[kaydetme]` yazıyor; etiketin anlamını açıkla.',
        'Örnek:\n> [kaydetme]\nBu alıntının biçimini incele.',
        'Bu [kaydetme] işareti nasıl çalışır?',
        '[kaydetme]ci',
    )

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.vault = self.root / 'kasa'
        self.vault.mkdir()

    def codex_source(self, prompt, count=6):
        path = self.root / 'codex.jsonl'
        rows = [dict(type='session_meta', payload=dict(id='sentetik', source='vscode'))]
        rows += [dict(type='response_item', timestamp=str(index), payload=dict(
            type='message', role='user', content=[dict(text=prompt if index == count - 1
                                                      else f'Sentetik görev {index}')]))
                 for index in range(count)]
        rows.append(dict(type='event_msg', payload=dict(type='task_complete', turn_id='son-tur')))
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        return capture.snapshot(path)

    def claude_source(self, prompt):
        path = self.root / 'sentetik.jsonl'
        rows = []
        for index in range(6):
            rows.extend([
                dict(type='user', uuid=f'u{index}', sessionId='sentetik', isSidechain=False,
                     message=dict(role='user', content=prompt if index == 5 else f'Sentetik görev {index}')),
                dict(type='assistant', uuid=f'a{index}', sessionId='sentetik', isSidechain=False,
                     message=dict(role='assistant', model='fixture-model', content=f'Sentetik sonuç {index}',
                                  stop_reason='end_turn')),
            ])
        path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
        return path

    def test_reserved_markers_block_capture_without_persisting_session_policy(self):
        for prompt in self.MARKERS:
            with self.subTest(prompt=prompt):
                self.assertTrue(capture.privacy_ambiguous(prompt))
                self.assertTrue(native.private(prompt))
                self.assertFalse(capture.privacy_command(prompt))
                self.assertFalse(capture.apply_prompt_policy(self.vault, 'sentetik', prompt))
                self.assertFalse(capture.excluded(self.vault, 'sentetik'))

    def test_quoted_code_and_mid_sentence_examples_do_not_block(self):
        for prompt in self.EXAMPLES:
            with self.subTest(prompt=prompt):
                self.assertFalse(capture.privacy_ambiguous(prompt))
                self.assertFalse(native.private(prompt))

    def test_codex_completed_six_user_source_checks_marker(self):
        ordinary = self.codex_source('Sentetik karar açıklandı.')
        self.assertEqual(6, capture.validate_source(self.vault, 'sentetik', ordinary)['user_count'])
        for prompt in self.MARKERS:
            with self.subTest(prompt=prompt):
                source = self.codex_source(prompt)
                self.assertEqual(6, source['user_count'])
                self.assertEqual('completed', source['activity_state'])
                with self.assertRaisesRegex(ValueError, 'kaydetmeme'):
                    capture.validate_source(self.vault, 'sentetik', source)
        quoted = self.codex_source('Belgede `[kaydetme]` yazıyor; açıklamasını incele.')
        self.assertEqual(6, capture.validate_source(self.vault, 'sentetik', quoted)['user_count'])

    def test_claude_completed_six_user_source_checks_marker(self):
        ordinary = native.parse('claude', 'sentetik', self.claude_source('Sentetik karar açıklandı.'))
        self.assertEqual(6, ordinary['count'])
        self.assertTrue(ordinary['terminal'])
        for prompt in self.MARKERS:
            with self.subTest(prompt=prompt):
                with self.assertRaisesRegex(native.SourceError, '^privacy_blocked$'):
                    native.parse('claude', 'sentetik', self.claude_source(prompt))
        quoted = native.parse('claude', 'sentetik', self.claude_source('Belgede `[kaydetme]` yazıyor.'))
        self.assertEqual(6, quoted['count'])

    def test_existing_quote_handling_and_first_five_gate_remain(self):
        quote = '"Bunu kaydetme"'
        self.assertEqual(quote.casefold(), capture.privacy_text(quote))
        self.assertFalse(capture.privacy_text(quote, retain_standalone_quote=False).strip())
        source = self.codex_source('Sentetik karar açıklandı.', count=5)
        with self.assertRaisesRegex(ValueError, 'ilk beş'):
            capture.validate_source(self.vault, 'sentetik', source)


if __name__ == '__main__':
    unittest.main()
