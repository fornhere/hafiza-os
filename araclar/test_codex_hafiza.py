import json
from pathlib import Path
import tempfile
import unittest

import codex_hafiza as h


class Hooks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)

    def event(self, name, turn='t6', **extra):
        return h.hook(self.vault, dict(session_id='session1', turn_id=turn,
                      hook_event_name=name, **extra))

    def six(self):
        for n in range(1, 7):
            self.event('UserPromptSubmit', f't{n}', prompt='Gerçek kullanıcı mesajı')

    def test_first_five_do_not_write_or_request_memory(self):
        for n in range(1, 6):
            self.event('UserPromptSubmit', f't{n}', prompt='Basit OBS sorusu')
            self.assertEqual(self.event('Stop', f't{n}'), {})
        self.assertFalse(list(self.vault.rglob('*.md')))
        self.assertFalse(list(self.vault.rglob('*.pending.json')))

    def test_sixth_requests_receipt_and_preserves_pending(self):
        self.six()
        result = self.event('Stop')
        self.assertEqual(result['decision'], 'block')
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 1)

    def test_duplicate_prompt_and_resume_keep_count(self):
        for _ in range(8):
            self.event('UserPromptSubmit', 't1', prompt='Tek mesaj')
            self.event('SessionStart', source='resume')
        self.assertEqual(self.event('Stop'), {})

    def test_continuation_does_not_count_or_loop(self):
        self.six()
        reason = self.event('Stop')['reason']
        self.event('UserPromptSubmit', 'continuation', prompt=reason)
        out = self.event('Stop', 'continuation', stop_hook_active=True)
        self.assertNotIn('decision', out)
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 1)
        state = json.loads(next(self.vault.rglob('.state/*.json')).read_text())
        self.assertEqual(state['count'], 6)

    def test_scheduled_and_synthetic_prompts_do_not_count(self):
        for i, prompt in enumerate(('[HAFIZA_OTOMASYON] saatlik kontrol', '<goal>devam</goal>',
                                    '<environment_context>otomatik</environment_context>')):
            self.event('UserPromptSubmit', f'auto-{i}', prompt=prompt)
        self.assertEqual(self.event('Stop'), {})
        self.assertFalse(list(self.vault.rglob('.state/*.json')))

    def test_receipt_unlocks_stop_and_is_idempotent(self):
        self.six()
        self.event('Stop')
        summary = 'Kodex bağlantısı onarıldı; eşik altı ve üstü davranışları test edildi.'
        h.record(self.vault, 'session1', 't6', summary)
        h.record(self.vault, 'session1', 't6', summary)
        self.assertEqual(self.event('Stop', 'continued', stop_hook_active=True), {})
        self.assertFalse(list(self.vault.rglob('*.pending.json')))
        self.assertEqual(len(list(self.vault.rglob('*.md'))), 2)

    def test_interrupt_preserves_long_session_only(self):
        self.assertEqual(self.event('Interrupt'), {})
        self.six()
        self.event('Interrupt')
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 1)

    def test_sessions_isolated(self):
        self.six()
        self.assertEqual(h.hook(self.vault, dict(session_id='other', turn_id='t1', hook_event_name='Stop')), {})

    def test_opening_includes_priorities_and_first_prompt_fallback(self):
        (self.vault / 'komuta').mkdir()
        (self.vault / 'zihin').mkdir()
        (self.vault / 'komuta/bu-hafta.md').write_text('# Öncelik\nKaynaklı işi bitir')
        (self.vault / 'zihin/açık-işler.md').write_text('# Açık\nGerçek uygulama testi bekliyor')
        start = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('Kaynaklı işi bitir', start)
        self.assertIn('Gerçek uygulama testi bekliyor', start)
        first = self.event('UserPromptSubmit', 't1', prompt='selam')
        self.assertIn('AÇILIŞ HATIRLATMASI', first['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.event('UserPromptSubmit', 't2', prompt='devam'), {})
        self.assertEqual(self.event('Stop', 't2'), {})

    def test_missing_priorities_do_not_invent_work(self):
        out = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('iş veya öncelik uydurma', out)

    def test_reject_secrets_and_replacement(self):
        with self.assertRaises(ValueError):
            h.record(self.vault, 's', 't', 'API key: ' + 'x' * 40)
        h.record(self.vault, 's', 't', 'Bu kayıt yeterince uzun olan ilk test makbuzudur.')
        with self.assertRaises(ValueError):
            h.record(self.vault, 's', 't', 'Mevcut makbuzun üzerine yazılması reddedilmelidir.')


if __name__ == '__main__':
    unittest.main()
