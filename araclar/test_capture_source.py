import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import capture_source as c
import konsolidasyon as k
import codex_hafiza as hook

class Capture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);self.root=self.v/'codex';(self.root/'sessions').mkdir(parents=True)
        self.p=self.root/'sessions/a.jsonl'
        self.rows=[dict(type='session_meta',payload=dict(id='s',source='vscode'))]
        self.rows += [dict(type='response_item',timestamp=str(i),payload=dict(type='message',role='user',content=[dict(text='Gerçek istek '+str(i))])) for i in range(6)]
    def save(self): self.p.write_text('\n'.join(map(json.dumps,self.rows)))
    def event(self,typ,turn='t6'): self.rows.append(dict(type='event_msg',payload=dict(type=typ,turn_id=turn)))
    def test_wrapper(self):
        self.assertEqual('kapak yap',c.clean_user('<in-app-browser-context source="ambient">OBS</in-app-browser-context>\n## My request:\nkapak yap'))
        self.assertEqual('',c.clean_user('<task-notification>\n<task-id>x</task-id>\n<output-file>/tmp/-home-u-ikinci-beyin/x.output</output-file>\n</task-notification>'))
        self.assertEqual('',c.clean_user('<in-app-browser-context>OBS</in-app-browser-context>'))
    def test_late_result_noise_and_gate(self):
        self.event('task_started');self.save();before=c.snapshot(self.p)
        with self.assertRaises(ValueError): c.validate_source(self.v,'s',before)
        self.event('task_complete');self.save();after=c.snapshot(self.p)
        self.assertNotEqual(before['source_hash'],after['source_hash'])
        self.event('token_count');self.save();self.assertEqual(after['source_hash'],c.snapshot(self.p)['source_hash'])
        c.validate_source(self.v,'s',after)
    def test_earlier_unresolved_does_not_block_later_complete(self):
        self.event('task_started','old');self.event('task_started');self.event('task_complete');self.save()
        self.assertEqual('completed',c.snapshot(self.p)['activity_state'])
    def test_checkpoint_receipt_and_changed_source(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p)
        data=dict(snap,outcome='recorded',reason='Anlamlı sonuç kaynakta kontrol edildi.')
        with self.assertRaises(ValueError): k.checkpoint(self.v,data)
        hook.record(self.v,'s','recovery-v2-'+snap['source_hash'],'Anlamlı iş sonucu ve kontrol edilen kalan işler.',[],snap)
        k.checkpoint(self.v,data)
        self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0))
        self.event('task_started','new');self.event('task_complete','new');self.save()
        with self.assertRaises(ValueError): k.checkpoint(self.v,data)
    def test_threshold_and_policy(self):
        with self.assertRaises(ValueError): hook.record(self.v,'s','t','Eşik aşılmadan kayıt yapılmamalıdır.')
        self.assertFalse(c.apply_prompt_policy(self.v,'s','"hafızaya kaydetme" komutu nasıl çalışır?'))
        self.assertTrue(c.apply_prompt_policy(self.v,'s','Kanka, bu oturumu kaydetme.'))
        self.event('task_complete');self.save()
        with self.assertRaises(ValueError): c.validate_source(self.v,'s',c.snapshot(self.p))
    def test_legacy_and_malformed_diagnostics(self):
        self.event('task_complete');self.save()
        rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0)
        self.assertEqual(1,len(rows))
        self.p.write_text(self.p.read_text()+'\n{broken')
        diagnostics=[];rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,diagnostics)
        self.assertEqual('malformed',rows[0]['suffix_parse_status'])

    def test_user_after_terminal_without_start_is_active(self):
        self.event('task_complete');self.rows.append(dict(type='response_item',timestamp='later',payload=dict(type='message',role='user',content=[dict(text='Yeni gerçek istek')])));self.save()
        self.assertEqual('active',c.snapshot(self.p)['activity_state'])
    def test_legacy_terminal_final_edit_changes_hash(self):
        self.event('task_complete');self.rows[-1]['payload']['last_agent_message']='İlk gerçek sonuç';self.save();before=c.snapshot(self.p)
        self.rows[-1]['payload']['last_agent_message']='Düzeltilmiş gerçek sonuç';self.save()
        self.assertNotEqual(before['source_hash'],c.snapshot(self.p)['source_hash'])
    def test_empty_receipt_and_wrong_recovery_key_rejected(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p)
        with self.assertRaises(ValueError): hook.record(self.v,'s','recovery-wrong','Anlamlı gerçek iş sonucu kaydı.',[],snap)
        path,_=hook.paths(self.v,'s','recovery-v2-'+snap['source_hash']);path.parent.mkdir(parents=True);path.write_text('')
        with self.assertRaises(ValueError): k.checkpoint(self.v,dict(snap,outcome='recorded',reason='Gerçek makbuz kontrolü gereklidir.'))
    def test_malformed_utf8_reported(self):
        self.save();self.p.write_bytes(self.p.read_bytes()+b'\xff')
        errors=[];self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors));self.assertTrue(errors)

    def test_empty_started_session_is_not_parser_failure(self):
        self.rows=self.rows[:1];self.event('task_started');self.save()
        errors=[];rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors)
        self.assertEqual([],rows);self.assertEqual([],errors)
    def test_actionable_rows_precede_old_active_rows(self):
        from unittest.mock import patch
        for i in range(12): (self.root/'sessions'/f'{i}.jsonl').write_text('{}')
        def fake(path, **kwargs):
            i=int(path.stem)
            return dict(session_id=str(i),source_hash=str(i),user_count=6,
                        activity_state='completed' if i==11 else 'active',last_modified=i)
        with patch.object(k,'snapshot',side_effect=fake):
            rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0)
        self.assertEqual('11',rows[0]['session_id']);self.assertEqual(10,len(rows))
    def test_ambiguity_survives_third_identical_copy(self):
        from unittest.mock import patch
        for i in range(3): (self.root/'sessions'/f'{i}.jsonl').write_text('{}')
        calls=iter(['A','B','B'])
        def fake(path, **kwargs):
            return dict(session_id='s',source_hash=next(calls),user_count=6,
                        activity_state='completed',last_modified=1)
        with patch.object(k,'snapshot',side_effect=fake):
            rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0)
        self.assertEqual('ambiguous',rows[0]['activity_state'])

    def test_completed_prefix_stays_valid_when_suffix_grows(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        self.rows.append(dict(type='response_item',timestamp='later',payload=dict(type='message',role='user',content=[dict(text='AKTIF SUFFIX OZETLENMEMELI')])));self.event('task_started','next');self.save()
        self.assertEqual(snap['source_hash'],c.snapshot(self.p,completed_prefix=True)['source_hash'])
        c.validate_source(self.v,'s',snap)
        self.assertNotIn('AKTIF SUFFIX',c.read_completed_prefix(self.v,'s',snap))
        hook.record(self.v,'s','recovery-v2-'+snap['source_hash'],'Yalnız tamamlanmış iş sonucu kaydı.',[],snap)
        k.checkpoint(self.v,dict(snap,outcome='recorded',reason='Tamamlanmış prefix kaynakta incelendi.'))
        self.event('task_complete','next');self.save()
        self.assertNotEqual(snap['source_hash'],c.snapshot(self.p,completed_prefix=True)['source_hash'])
    def test_prefix_must_end_at_terminal_and_preserve_threshold(self):
        self.rows=self.rows[:6];self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        with self.assertRaises(ValueError): c.validate_source(self.v,'s',snap)
        with self.assertRaises(ValueError): c.snapshot(self.p,end_line=2)
    def test_prefix_mutation_invalidates_read(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        self.rows[1]['payload']['content'][0]['text']='Değişmiş kaynak kullanıcı isteği';self.save()
        with self.assertRaises(ValueError): c.read_completed_prefix(self.v,'s',snap)

    def test_partial_suffix_does_not_poison_completed_prefix(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        self.p.write_text(self.p.read_text()+'\n{"partial":')
        actual=c.validate_source(self.v,'s',snap)
        self.assertEqual('malformed',actual['suffix_parse_status'])
        self.assertNotIn('partial',c.read_completed_prefix(self.v,'s',snap))
    def test_privacy_suffix_blocks_prefix_without_hook(self):
        self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        self.rows.append(dict(type='response_item',timestamp='privacy',payload=dict(type='message',role='user',content=[dict(text='Bu oturumu kaydetme')])));self.save()
        with self.assertRaises(ValueError): c.validate_source(self.v,'s',snap)

    def test_exec_requires_user_ownership(self):
        self.rows[0]['payload'].update(source='exec', thread_source='user')
        self.event('task_complete'); self.save()
        self.assertEqual('completed', c.snapshot(self.p)['activity_state'])
        for source in ({'subagent': {}}, 'agent', None):
            self.rows[0]['payload']['thread_source'] = source; self.save()
            with self.assertRaises(ValueError): c.snapshot(self.p)

    def test_desktop_created_task_is_known_main_source(self):
        self.rows[0]['payload'].update(source='vscode', thread_source='agent_created_thread', originator='Codex Desktop')
        self.event('task_complete'); self.save()
        self.assertEqual('completed', c.snapshot(self.p)['activity_state'])
        errors=[]
        rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors)
        self.assertEqual(['s'], [row['session_id'] for row in rows])
        self.assertEqual([], errors)
        # Known ownership does not bypass the first-five-message gate.
        self.rows=self.rows[:6]+[self.rows[-1]]; self.save()
        snap=c.snapshot(self.p)
        with self.assertRaises(ValueError): c.validate_source(self.v,'s',snap)

    def test_chatgpt_handoff_uses_codex_user_messages(self):
        self.event('task_complete')
        for originator in ('codex_work_desktop', 'Codex Desktop'):
            with self.subTest(originator=originator):
                self.rows[0]['payload'].update(source='vscode', thread_source='chatgpt_handoff', originator=originator)
                self.save(); errors=[]
                rows=k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors)
                self.assertEqual(['s'], [row['session_id'] for row in rows])
                self.assertEqual(6,rows[0]['user_count'])
                self.assertEqual([],errors)
        self.rows=self.rows[:3]+[self.rows[-1]]; self.save(); errors=[]
        self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors))
        self.assertEqual([],errors)

    def test_unknown_handoff_owner_remains_diagnostic(self):
        self.event('task_complete')
        for source, originator in (('exec','codex_work_desktop'), ('vscode','unknown'), ('vscode',None)):
            with self.subTest(source=source,originator=originator):
                self.rows[0]['payload'].update(source=source, thread_source='chatgpt_handoff', originator=originator)
                self.save(); errors=[]
                self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors))
                self.assertEqual(1,len(errors))

    def test_unknown_created_task_producer_remains_diagnostic(self):
        self.event('task_complete')
        for source, origin in [('exec','Codex Desktop'), ('vscode','unknown'), ('vscode',None)]:
            with self.subTest(source=source,origin=origin):
                self.rows[0]['payload'].update(source=source, thread_source='agent_created_thread', originator=origin)
                self.save(); errors=[]
                self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors))
                self.assertEqual(1,len(errors))

    def test_desktop_origin_does_not_promote_collaboration_worker(self):
        self.event('task_complete')
        for owner in ['subagent','agent',{'subagent': {'parent_thread_id':'parent'}}]:
            with self.subTest(owner=owner):
                self.rows[0]['payload'].update(source='vscode', thread_source=owner, originator='Codex Desktop')
                self.save(); errors=[]
                self.assertEqual([],k.sessions(self.v,self.root,dt.datetime(1970,1,1,tzinfo=dt.timezone.utc),0,errors))
                self.assertEqual([],errors)
                with self.assertRaises(ValueError): c.snapshot(self.p)

    def test_original_evidence_rejects_fabricated_summary(self):
        self.event('task_complete'); self.save(); snap=c.snapshot(self.p, completed_prefix=True)
        quote='Gerçek istek 5'
        evidence=dict(snap, line=7, message_hash=c.digest(quote), quote=quote)
        c.validate_candidate_evidence(self.v, 's', snap, evidence, quote)
        with self.assertRaises(ValueError):
            c.validate_candidate_evidence(self.v,'s',snap,dict(evidence,quote='Uydurulmuş tercih'), 'Uydurulmuş tercih')
        with self.assertRaises(ValueError):
            c.validate_candidate_evidence(self.v,'s',snap,dict(evidence,line=8),quote)

    def test_natural_privacy_defers_without_copying(self):
        self.rows[6]['payload']['content'][0]['text']='Şu anlattığımı hafızaya kaydetme lütfen'
        self.event('task_complete'); self.save(); snap=c.snapshot(self.p,completed_prefix=True)
        with self.assertRaises(ValueError): c.read_completed_prefix(self.v,'s',snap)
        self.assertFalse(c.privacy_command('Kanka bunu hatırlama.'))
        self.assertTrue(c.privacy_ambiguous('Kanka bunu hatırlama.'))
        self.assertFalse(c.apply_prompt_policy(self.v,'s','Şu anlattığımı hafızaya kaydetme lütfen'))

    def test_concurrent_suffix_append_preserves_snapshot(self):
        from unittest.mock import patch
        self.event('task_complete'); self.save(); snap=c.snapshot(self.p,completed_prefix=True)
        original=Path.read_bytes
        def growing(path):
            raw=original(path)
            if path==self.p:
                with path.open('ab') as out: out.write(b'\n{"partial":')
            return raw
        with patch.object(Path,'read_bytes',growing):
            self.assertEqual(snap['prefix_hash'], c.snapshot(self.p,completed_prefix=True)['prefix_hash'])

    def test_privacy_common_holdouts_and_quoted_examples(self):
        requests = ['Bunu hafızaya alma lütfen.', 'Şu bilgiyi kayıt altına almayalım.',
            'Lütfen bunu saklama, örnek vermiştim.', 'Bunları bellekte tutma.',
            'Söylediğimi not olarak yazma.', 'Bunu kaydetmeni istemiyorum.',
            'Bu bilgiyi hafızaya almayın.', 'Bunu kaydetmeyelim.', 'Bu bilgiyi saklamayalım.', 'Hafızanda kalmasın.', 'Aramızda kalsın.', 'Hafızaya alınmasın.']
        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(c.privacy_ambiguous(request))
                self.assertFalse(c.apply_prompt_policy(self.v,'s',request))
        discussions = ['Bana önceki kaydetme hatasını açıkla.',
            '"Bunu hafızaya alma" komutu nasıl çalışır?',
            'Örnek: `bunu kaydetme`. Bu komutun testini yaz.',
            'Belgede “bu oturumu kaydetme” yazıyor; belgenin üslubunu incele.']
        for request in discussions:
            with self.subTest(request=request): self.assertFalse(c.privacy_ambiguous(request))
        self.assertTrue(c.privacy_ambiguous('"Bunu kaydetme" örneğini açıkladım. Şu bilgiyi hafızaya alma.'))
        self.assertTrue(c.privacy_command('Kanka, bu sohbeti kaydetme lütfen.'))

if __name__=='__main__':unittest.main()
