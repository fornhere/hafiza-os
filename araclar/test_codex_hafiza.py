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
        self.assertEqual(result, {})
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 0)

    def test_duplicate_prompt_and_resume_keep_count(self):
        for _ in range(8):
            self.event('UserPromptSubmit', 't1', prompt='Tek mesaj')
            self.event('SessionStart', source='resume')
        self.assertEqual(self.event('Stop'), {})

    def test_continuation_does_not_count_or_loop(self):
        self.six()
        reason = h.CONTINUATION + ' eski hook devamı'
        self.event('UserPromptSubmit', 'continuation', prompt=reason)
        out = self.event('Stop', 'continuation', stop_hook_active=True)
        self.assertNotIn('decision', out)
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 0)
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
        self.assertEqual(len(list(self.vault.rglob('*.pending.json'))), 0)

    def test_sessions_isolated(self):
        self.six()
        self.assertEqual(h.hook(self.vault, dict(session_id='other', turn_id='t1', hook_event_name='Stop')), {})

    def test_opening_includes_priorities_and_first_prompt_fallback(self):
        (self.vault / 'komuta').mkdir()
        (self.vault / 'zihin').mkdir()
        (self.vault / 'komuta/bu-hafta.md').write_text('# Öncelik\nKaynaklı işi bitir')
        (self.vault / 'zihin/açık-işler.md').write_text('# Açık\nGerçek uygulama testi bekliyor')
        start = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertNotIn('Kaynaklı işi bitir', start)
        self.assertNotIn('Gerçek uygulama testi bekliyor', start)
        first = self.event('UserPromptSubmit', 't1', prompt='selam')
        self.assertIn('AÇILIŞ HATIRLATMASI', first['hookSpecificOutput']['additionalContext'])
        self.assertEqual(self.event('UserPromptSubmit', 't2', prompt='devam'), {})
        self.assertEqual(self.event('Stop', 't2'), {})

    def test_missing_priorities_do_not_invent_work(self):
        out = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('eski işi kendiliğinden açma', out)

    def test_reject_secrets_and_replacement(self):
        for i in range(6):
            h.hook(self.vault, dict(session_id="s", turn_id="t" if i == 5 else str(i), hook_event_name="UserPromptSubmit", prompt="Gerçek test isteği"))
        with self.assertRaises(ValueError):
            h.record(self.vault, 's', 't', 'API key: ' + 'x' * 40)
        h.record(self.vault, 's', 't', 'Bu kayıt yeterince uzun olan ilk test makbuzudur.')
        with self.assertRaises(ValueError):
            h.record(self.vault, 's', 't', 'Mevcut makbuzun üzerine yazılması reddedilmelidir.')


    def test_package_repeat_refresh_and_source_invalidation(self):
        from unittest.mock import patch
        package={'text':'Güncel karar ve kaynak.', 'source_versions':{'karar.md':'v1'}}
        with patch('gorev_baglam.build_task_package',return_value=package):
            a=self.event('UserPromptSubmit','t1',prompt='aynı görev')
            b=self.event('UserPromptSubmit','t2',prompt='aynı görev')
            c=self.event('UserPromptSubmit','t3',prompt='aynı görev')
            self.assertIn(package['text'],a['hookSpecificOutput']['additionalContext'])
            self.assertEqual({},b)
            self.assertIn(package['text'],c['hookSpecificOutput']['additionalContext'])
            package['source_versions']['karar.md']='v2'
            d=self.event('UserPromptSubmit','t4',prompt='aynı görev')
            self.assertIn(package['text'],d['hookSpecificOutput']['additionalContext'])
        state=json.loads(next(self.vault.rglob('.state/*.json')).read_text())
        self.assertEqual(len(package['text']),state['context_usage']['suppressed_chars'])
        self.assertIsNone(state['context_usage']['token_count'])

    def test_resume_compaction_resets_package_cache(self):
        from unittest.mock import patch
        with patch('gorev_baglam.build_task_package',return_value={'text':'Korunacak önemli bağlam'}):
            for i,source in enumerate(('startup','resume','compact')):
                self.event('UserPromptSubmit',f'before-{i}',prompt='iş')
                self.event('SessionStart',source=source)
                result=self.event('UserPromptSubmit',f'after-{i}',prompt='iş')
                self.assertIn('Korunacak önemli bağlam',result['hookSpecificOutput']['additionalContext'])

    def test_latest_section_is_bounded_and_date_selected(self):
        (self.vault/'zihin').mkdir()
        path=self.vault/'zihin/son-oturum.md'
        path.write_text('## 2026-09-16 — güncel\n'+('güncel '*1000)+'\n## 2026-01-01 — eski\nESKİ BİLGİ')
        text=h.latest_session_section(self.vault)
        self.assertLessEqual(len(text),2500)
        self.assertNotIn('ESKİ BİLGİ',text)
        self.assertIn('Kesildi',text)
        opening=self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('latest-session',opening)
        self.assertIn('Diğer ajan açılış yönergeleri geçerlidir',opening)

if __name__ == '__main__':
    unittest.main()
