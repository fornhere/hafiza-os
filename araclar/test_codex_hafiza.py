import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def transcript(self, payload):
        path = self.vault / 'transcript.jsonl'
        path.write_text(json.dumps({'type': 'session_meta', 'payload': payload}) + '\n',
                        encoding='utf-8')
        return path

    def assert_no_hook_state(self):
        self.assertFalse((self.vault / h.INBOX / '.state').exists())
        self.assertFalse(list((self.vault / h.INBOX).glob('*.pending.json')))

    def test_prompt_package_runs_without_remote_advisor_unless_opted_in(self):
        import gorev_baglam, jev_client
        seen = []
        def fake(vault, query, **kwargs):
            seen.append(jev_client.load_config(vault)['mode'])
            return {'text': '', 'source_versions': {}, 'selected_ids': []}
        with patch.object(gorev_baglam, 'build_task_package', fake), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('HAFIZA_HOOK_JEV', None)
            self.event('UserPromptSubmit', turn='t1', prompt='Gerçek görev isteği burada')
            os.environ['HAFIZA_HOOK_JEV'] = '1'
            self.event('UserPromptSubmit', turn='t2', prompt='İkinci gerçek görev isteği')
        self.assertEqual('off', seen[0])
        self.assertEqual(2, len(seen))

    def test_worker_environment_skips_all_events_without_state(self):
        for name in ('HAFIZA_ISCI', 'CODEX_WORKER'):
            with self.subTest(name=name), patch.dict(os.environ, {name: '1'}):
                for event in ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt'):
                    with patch('capture_source.apply_prompt_policy') as policy:
                        self.assertEqual(self.event(event, prompt='gerçek görev'), {})
                        policy.assert_not_called()
                self.assert_no_hook_state()

    def test_worker_environment_cli_creates_no_queue_or_lock(self):
        env = os.environ.copy()
        env.update(HAFIZA_ISCI='1')
        for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
            data = dict(session_id='worker', turn_id='t1', hook_event_name=event,
                        prompt='gerçek görev')
            proc = subprocess.run([sys.executable, str(Path(h.__file__)),
                                   '--vault', str(self.vault), 'hook'],
                                  input=json.dumps(data), text=True, capture_output=True,
                                  env=env, check=True)
            self.assertEqual(json.loads(proc.stdout), {})
            self.assertEqual(proc.stderr, '')
        self.assertFalse((self.vault / h.INBOX).exists())

    def test_worker_prompt_and_transcript_cli_create_no_queue_or_lock(self):
        transcript = self.transcript({'originator': 'codex_exec', 'source': 'exec'})
        env = os.environ.copy()
        for name in ('HAFIZA_ISCI', 'CODEX_WORKER',
                     'HAFIZA_EXEC_BAGLAM'):
            env.pop(name, None)
        for extra in ({'prompt': 'İŞÇİ KOŞUSU: görev'},
                      {'prompt': 'görev', 'transcript_path': str(transcript)}):
            data = dict(session_id='worker', turn_id='t1',
                        hook_event_name='UserPromptSubmit', **extra)
            proc = subprocess.run([sys.executable, str(Path(h.__file__)),
                                   '--vault', str(self.vault), 'hook'],
                                  input=json.dumps(data), text=True, capture_output=True,
                                  env=env, check=True)
            self.assertEqual(json.loads(proc.stdout), {})
            self.assertEqual(proc.stderr, '')
        self.assertFalse((self.vault / h.INBOX).exists())

    def test_worker_prompt_prefix_skips_policy_and_state(self):
        for prefix in ('İŞÇİ KOŞUSU', 'işçi koşusu', 'IŞÇI KOŞUSU'):
            with self.subTest(prefix=prefix):
                with patch('capture_source.apply_prompt_policy') as policy:
                    self.assertEqual(self.event('UserPromptSubmit', prompt='  \n' + prefix + ': görev'), {})
                    policy.assert_not_called()
                self.assert_no_hook_state()

    def test_worker_transcript_and_explicit_exec_override(self):
        transcript = self.transcript({'originator': 'codex_exec', 'source': 'exec'})
        for event in ('SessionStart', 'UserPromptSubmit', 'Stop'):
            self.assertEqual(self.event(event, prompt='görev', transcript_path=str(transcript)), {})
        self.assert_no_hook_state()
        with patch.dict(os.environ, {'HAFIZA_EXEC_BAGLAM': '1'}):
            result = self.event('SessionStart', transcript_path=str(transcript))
        self.assertIn('additionalContext', result['hookSpecificOutput'])
        self.assertTrue(list((self.vault / h.INBOX / '.state').glob('*.json')))

    def test_worker_transcript_source_dict_and_first_meta_only(self):
        path = self.transcript({'source': {'subagent': {}}})
        self.assertTrue(h.worker_run({'transcript_path': str(path)}, {}))
        self.transcript({'originator': 'Codex Desktop', 'source': 'exec'})
        self.assertTrue(h.worker_run({'transcript_path': str(path)}, {}))
        path.write_text(json.dumps({'type': 'session_meta', 'payload': {'source': 'vscode'}})
                        + '\n' + json.dumps({'type': 'session_meta',
                                              'payload': {'originator': 'codex_exec'}}) + '\n')
        self.assertFalse(h.worker_run({'transcript_path': str(path)}, {}))

    def test_exec_override_only_disables_transcript_detection(self):
        path = self.transcript({'originator': 'codex_exec'})
        data = {'transcript_path': str(path)}
        self.assertFalse(h.worker_run(data, {'HAFIZA_EXEC_BAGLAM': '1'}))
        self.assertTrue(h.worker_run(data, {'HAFIZA_EXEC_BAGLAM': '1', 'HAFIZA_ISCI': '1'}))
        self.assertTrue(h.worker_run({**data, 'prompt': 'işçi koşusu: görev'},
                                     {'HAFIZA_EXEC_BAGLAM': '1'}))

    def test_normal_and_bad_transcripts_keep_hook_active(self):
        normal = self.transcript({'originator': 'Codex Desktop', 'source': 'vscode'})
        bad = self.vault / 'bad.jsonl'
        bad.write_text('{broken\n', encoding='utf-8')
        link = self.vault / 'linked.jsonl'
        link.symlink_to(normal)
        for path in (normal, bad, self.vault / 'missing.jsonl', link, self.vault):
            with self.subTest(path=path):
                result = self.event('SessionStart', transcript_path=str(path))
                self.assertIn('additionalContext', result['hookSpecificOutput'])

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

    def test_session_start_prevents_first_prompt_opening_repeat(self):
        (self.vault / 'komuta').mkdir()
        (self.vault / 'zihin').mkdir()
        (self.vault / 'komuta/bu-hafta.md').write_text('# Öncelik\nKaynaklı işi bitir')
        (self.vault / 'zihin/açık-işler.md').write_text('# Açık\nGerçek uygulama testi bekliyor')
        start = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertNotIn('Kaynaklı işi bitir', start)
        self.assertNotIn('Gerçek uygulama testi bekliyor', start)
        self.assertIn('AÇILIŞ HATIRLATMASI', start)
        first = self.event('UserPromptSubmit', 't1', prompt='selam')
        self.assertNotIn('AÇILIŞ HATIRLATMASI', first.get('hookSpecificOutput', {}).get('additionalContext', ''))
        self.assertEqual(self.event('UserPromptSubmit', 't2', prompt='devam'), {})
        self.assertEqual(self.event('Stop', 't2'), {})

    def test_first_prompt_without_session_start_keeps_opening_fallback(self):
        first = self.event('UserPromptSubmit', 't1', prompt='selam')
        self.assertIn('AÇILIŞ HATIRLATMASI', first['hookSpecificOutput']['additionalContext'])

    def test_opening_size_does_not_grow_with_receipt_history(self):
        queue = self.vault / h.INBOX
        queue.mkdir(parents=True)
        before = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        for n in range(200):
            (queue / f'private-session-{n}.md').write_text('private note')
        after = self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertLess(abs(len(after) - len(before)), 10)
        self.assertNotIn('private-session-', after)
        self.assertNotIn('private note', after)
        self.assertIn('200 görev makbuzu', after)
        self.assertIn('latest-session', after)

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
            self.assertIn('HAFIZA GÖRÜNÜRLÜĞÜ',a['hookSpecificOutput']['additionalContext'])
            self.assertIn('kullanım kanıtı değildir',a['hookSpecificOutput']['additionalContext'])
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
        text=h.latest_session_section(self.vault, today=h.dt.date(2026, 9, 18))
        self.assertLessEqual(len(text),2500)
        self.assertNotIn('ESKİ BİLGİ',text)
        self.assertIn('Kesildi',text)
        opening=self.event('SessionStart')['hookSpecificOutput']['additionalContext']
        self.assertIn('latest-session',opening)
        self.assertIn('Kısa agents.md açılış sözleşmesi geçerlidir',opening)

    def test_latest_section_old_date_returns_one_line_and_cli_agrees(self):
        import contextlib
        import io
        (self.vault/'zihin').mkdir()
        (self.vault/'zihin/son-oturum.md').write_text('## 2000-01-01 — eski\nÖzel eski içerik\n')
        message=h.latest_session_section(self.vault, today=h.dt.date(2000, 1, 5))
        self.assertEqual('Son oturum kaydı 2000-01-01 tarihli (4 gün eski); güncel durum kanıtı değil, açık işler özetini kullan.', message)
        self.assertNotIn('Özel eski içerik', message)
        output=io.StringIO()
        from unittest.mock import patch
        with contextlib.redirect_stdout(output), patch.object(h.sys, 'argv', ['codex_hafiza.py', '--vault', str(self.vault), 'latest-session']):
            self.assertIsNone(h.main())
        self.assertIn('Son oturum kaydı 2000-01-01 tarihli (', output.getvalue())
        self.assertNotIn('Özel eski içerik', output.getvalue())

    def test_old_session_uses_recent_codex_receipt(self):
        (self.vault/'zihin').mkdir()
        (self.vault/'zihin/son-oturum.md').write_text('## 2026-09-10\nEski ayrıntı')
        queue = self.vault/h.INBOX
        queue.mkdir(parents=True)
        (queue/'README.md').write_text('# Codex görev makbuzu — 2026-09-23T10:00:00+00:00\nDurum: test\nYANLIŞ')
        (queue/'fresh.md').write_text('# Codex görev makbuzu — 2026-09-22T10:00:00+00:00\n\nDurum: görev özeti\n\nGerçek görev özeti.\n\n[[gelen-kutusu/codex-oturumları/README]]')
        result = h.latest_session_section(self.vault, today=h.dt.date(2026, 9, 24))
        self.assertIn('2026-09-22 Codex: Gerçek görev özeti.', result)
        self.assertNotIn('Eski ayrıntı', result)
        self.assertNotIn('YANLIŞ', result)

    def test_invalid_claude_receipt_is_skipped(self):
        queue = self.vault/'gelen-kutusu/ajan-oturumlari'
        state = queue/'.state'
        state.mkdir(parents=True)
        receipt = dict(id='abc', decision='record', meaningful=True,
                       decision_sha256='decision', summary='Bozuk makbuz özeti',
                       reviewed_ns=1760000000000000000)
        (queue/'abc.json').write_text(json.dumps(receipt))
        (state/'abc.json').write_text(json.dumps(dict(status='record',
            decision_sha256='decision', receipt_sha256='wrong')))
        self.assertEqual(h.latest_session_section(self.vault, today=h.dt.date(2025, 10, 9)),
                         'Son oturum notu yok.')

    def test_valid_claude_receipt_is_included(self):
        import hashlib
        queue = self.vault/'gelen-kutusu/ajan-oturumlari'
        state = queue/'.state'
        state.mkdir(parents=True)
        timestamp = int(h.dt.datetime(2026, 9, 23, tzinfo=h.dt.timezone.utc).timestamp()*1_000_000_000)
        receipt = dict(id='abc', decision='record', meaningful=True,
                       decision_sha256='decision', summary='Claude görev özeti', reviewed_ns=timestamp)
        raw = json.dumps(receipt).encode()
        (queue/'abc.json').write_bytes(raw)
        (state/'abc.json').write_text(json.dumps(dict(status='record',
            decision_sha256='decision', receipt_sha256=hashlib.sha256(raw).hexdigest())))
        result = h.latest_session_section(self.vault, today=h.dt.date(2026, 9, 24))
        self.assertIn('2026-09-23 Claude: Claude görev özeti', result)

    def test_receipt_summary_obeys_budget(self):
        queue = self.vault/h.INBOX
        queue.mkdir(parents=True)
        (queue/'fresh.md').write_text('# Codex görev makbuzu — 2026-09-24T10:00:00+00:00\n\nDurum: görev özeti\n\n' + 'A'*1000)
        result = h.latest_session_section(self.vault, limit=140, today=h.dt.date(2026, 9, 24))
        self.assertLessEqual(len(result), 140)
        self.assertIn('2026-09-24 Codex:', result)

    def test_fresh_session_section_takes_priority_over_receipts(self):
        (self.vault/'zihin').mkdir()
        (self.vault/'zihin/son-oturum.md').write_text('## 2026-09-23\nTaze bölüm')
        queue = self.vault/h.INBOX
        queue.mkdir(parents=True)
        (queue/'fresh.md').write_text('# Codex görev makbuzu — 2026-09-24T10:00:00+00:00\n\nDurum: görev özeti\n\nMakbuz özeti')
        result = h.latest_session_section(self.vault, today=h.dt.date(2026, 9, 24))
        self.assertIn('Taze bölüm', result)
        self.assertNotIn('Makbuz özeti', result)

if __name__ == '__main__':
    unittest.main()
