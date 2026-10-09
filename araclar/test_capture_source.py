import datetime as dt
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import capture_source as c
import konsolidasyon as k
import codex_hafiza as hook


class NativeOriginTests(unittest.TestCase):
    def test_interruption_notices_preserve_attached_request(self):
        for notice in ('[Request interrupted by user]', '[Request interrupted by user for tool use]'):
            self.assertEqual(c.clean_user(notice), '')
            self.assertEqual(c.clean_user(notice+'\nGerçek istek'), 'Gerçek istek')
            self.assertEqual(c.clean_user('Gerçek istek\n'+notice), 'Gerçek istek')

    def test_t30_delivery_and_attachment_metadata(self):
        # T30 B:9318/9330/9481/9545 and B:9445, synthetic bodies.
        for metadata in (
                '[Cross-session delivery notice] Synthetic delivery status.',
                '[Image: source: /tmp/synthetic.png]',
                '[Image: source: /tmp/synthetic.png]\n[Image: source: /tmp/other.png]'):
            with self.subTest(metadata=metadata):
                self.assertEqual(c.clean_user(metadata), '')
                self.assertEqual(c.clean_user(metadata + '\nReal task'), 'Real task')
                self.assertEqual(c.clean_user('Real task\n' + metadata), 'Real task')
        self.assertEqual(c.clean_user('Real task'), 'Real task')

    def test_t30_command_invocation_and_expanded_body(self):
        # Invocation A:2938, separate expansion A:2939.
        body = '# /loop — schedule a recurring or self-paced prompt\nForeign task body'
        wrappers = '<command-message>loop</command-message><command-name>/loop</command-name>'
        for args in ('', 'Real task'):
            with self.subTest(args=args):
                self.assertEqual(c.clean_user(wrappers + '<command-args>' + args
                                 + '</command-args>\n' + body), args)
        self.assertEqual(c.clean_user(wrappers), '')
        self.assertEqual(c.clean_user(body), '')
        self.assertEqual(c.clean_user(wrappers + '<command-args>unclosed'), '')
        self.assertEqual(c.clean_user(wrappers + '<command-args>Real task'
                         '<task-notification>Foreign</task-notification></command-args>'), 'Real task')

    def test_installation_version_only_reads_runtime_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            script = root / 'capture_source.py'
            script.write_text('runtime')
            (root / 'test_private.py').write_text('private fixture')
            (root / 'private.md').write_text('private prompt')
            with patch.object(c, '__file__', str(script)):
                first = c.installation_version()
                self.assertRegex(first, r'^araclar-sha256:[0-9a-f]{64}$')
                (root / 'private.md').write_text('different private prompt')
                (root / 'test_private.py').write_text('different fixture')
                self.assertEqual(first, c.installation_version())
                script.write_text('new runtime')
                self.assertNotEqual(first, c.installation_version())


class HeartbeatThreads(unittest.TestCase):
    def check_config(self, content, expected):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / 'automations/hb/automation.toml'
            path.parent.mkdir(parents=True)
            path.write_bytes(content.encode('utf-8') if isinstance(content, str) else content)
            for fallback in (False, True):
                with self.subTest(fallback=fallback):
                    context = patch.dict(sys.modules, {'tomllib': None}) if fallback else nullcontext()
                    with context:
                        self.assertEqual(expected, k.heartbeat_threads(root))

    def test_toml_string_forms_and_unrelated_values(self):
        for content in (
            'kind = "heartbeat"\ntarget_thread_id = "s" # comment\n',
            "'kind' = 'heartbeat'\n\"target_thread_id\" = 's'\n",
            'kind = """\nheartbeat"""\ntarget_thread_id = \'\'\'s\'\'\'\n',
            'kind = "heart\\u0062eat"\ntarget_thread_id = "s\\U00000023x"\n',
        ):
            with self.subTest(content=content):
                expected = {'s#x'} if '\\U' in content else {'s'}
                self.check_config(content + 'created_at = 2026-09-01T12:00:00Z\n'
                                  'options = { enabled = true, values = [1, 2.5] }\n', expected)

    def test_multiline_prompt_and_nested_metadata_do_not_supply_root_fields(self):
        self.check_config('kind = "scheduled"\ntarget_thread_id = "ordinary"\n'
                          'prompt = \'\'\'\nkind = "heartbeat"\ntarget_thread_id = "fake"\n\'\'\'\n'
                          '[metadata]\nkind = "heartbeat"\ntarget_thread_id = "nested"\n', set())
        self.check_config('kind = "heartbeat"\ntarget_thread_id = "root"\n'
                          'prompt = """\nkind = \\"scheduled\\"\n"""\n'
                          '[[metadata]]\nkind = "scheduled"\ntarget_thread_id = "nested"\n', {'root'})

    def test_invalid_documents_and_non_string_ids_are_ignored(self):
        valid = 'kind = "heartbeat"\ntarget_thread_id = "s"\n'
        for content in (
            valid + 'kind = "heartbeat"\n',
            valid + 'unrelated = [1,\n',
            valid + '[metadata]\n[metadata]\n',
            valid + 'prompt = "unterminated\n',
            'kind = "heartbeat"\ntarget_thread_id = 123\n',
            'kind = "heartbeat"\n',
            valid.encode('utf-8') + b'\xff',
        ):
            with self.subTest(content=content):
                self.check_config(content, set())


class Capture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name).resolve();self.root=self.v/'codex';(self.root/'sessions').mkdir(parents=True)
        self.p=self.root/'sessions/a.jsonl'
        self.rows=[dict(type='session_meta',payload=dict(id='s',source='vscode'))]
        self.rows += [dict(type='response_item',timestamp=str(i),payload=dict(type='message',role='user',content=[dict(text='Gerçek istek '+str(i))])) for i in range(6)]
    def save(self): self.p.write_text('\n'.join(map(json.dumps,self.rows)))
    def event(self,typ,turn='t6'): self.rows.append(dict(type='event_msg',payload=dict(type=typ,turn_id=turn)))
    def test_codex_command_wrapper_snapshot_and_evidence_remain_unchanged(self):
        quote='<local-command-stdout>Native Codex text</local-command-stdout>'
        self.rows[6]['payload']['content'][0]['text']=quote
        self.event('task_complete'); self.save(); snap=c.snapshot(self.p,completed_prefix=True)
        self.assertEqual(6,snap['user_count'])
        evidence=dict(snap,line=7,message_hash=c.digest(quote),quote=quote)
        self.assertEqual(evidence,c.validate_candidate_evidence(self.v,'s',snap,evidence,quote))

    def category_candidate(self, category):
        quote='Sunumlarda kısa ve açık başlıklar tercih ediyorum.'
        self.rows[6]['payload']['content'][0]['text']=quote
        self.event('task_complete');self.save();snap=c.snapshot(self.p,completed_prefix=True)
        candidate=dict(statement=quote,subject_key='slides.titles',evidence=quote,
                       evidence_source=dict(snap,line=7,message_hash=c.digest(quote),quote=quote))
        if category is not None: candidate['category']=category
        return snap,candidate

    def test_record_preserves_optional_candidate_category(self):
        import hafiza
        for category in ('preference',None):
            with self.subTest(category=category):
                snap,candidate=self.category_candidate(category)
                vault=self.v/('categorized' if category else 'legacy')
                hook.record(vault,'s','recovery-v2-'+snap['source_hash'],candidate['evidence'],[candidate],snap)
                queued=hafiza.load_jsonl(vault/hafiza.CANDIDATE_PATH)
                self.assertEqual(1,len(queued))
                self.assertEqual(category,queued[0].get('category'))
                self.assertEqual(category is not None,'category' in queued[0])

    def test_record_rejects_invalid_category_before_writing_receipt(self):
        for category in ('unknown','case',[],{},1):
            with self.subTest(category=category):
                snap,candidate=self.category_candidate(category)
                with self.assertRaisesRegex(ValueError,'category'):
                    hook.record(self.v,'s','recovery-v2-'+snap['source_hash'],candidate['evidence'],[candidate],snap)
                self.assertFalse((self.v/hook.INBOX).exists())

    def test_wrapper(self):
        self.assertEqual('kapak yap',c.clean_user('<in-app-browser-context source="ambient">OBS</in-app-browser-context>\n## My request:\nkapak yap'))
        self.assertEqual('',c.clean_user('<task-notification>\n<task-id>x</task-id>\n<output-file>/tmp/-home-u-ikinci-beyin/x.output</output-file>\n</task-notification>'))
        self.assertEqual('',c.clean_user('<in-app-browser-context>OBS</in-app-browser-context>'))

    def test_harness_wrappers_preserve_only_real_user_text(self):
        for tag in ('task-notification', 'cross-session-message', 'system-reminder',
                    'heartbeat', 'goal', 'subagent_notification', 'collaboration',
                    'hook_prompt', 'turn_aborted', 'codex_internal_context'):
            wrapper = f'<{tag} source="synthetic">Foreign project</{tag}>'
            with self.subTest(tag=tag):
                self.assertEqual('', c.clean_user(wrapper))
                self.assertEqual('User request', c.clean_user('User request\n' + wrapper))
                self.assertEqual('User request', c.clean_user(wrapper + '\nUser request'))
                self.assertEqual('User request', c.clean_user('User ' + wrapper + 'request'))
                self.assertEqual('User request', c.clean_user('User request\n'
                                 f'<{tag}>incomplete notification'))
                self.assertEqual('User request', c.clean_user(f'<{tag}/>User request'))

    def test_nested_harness_and_normal_prompt(self):
        self.assertEqual('User request', c.clean_user('<task-notification>'
            '<task-notification>nested</task-notification>tail</task-notification>\nUser request'))
        self.assertEqual('Normal request about heartbeat and loops',
                         c.clean_user('Normal request about heartbeat and loops'))
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
    def test_heartbeat_thread_without_new_user_message_is_not_rescanned(self):
        (self.root/'automations/hb').mkdir(parents=True)
        (self.root/'automations/hb/automation.toml').write_text('kind = "heartbeat"\ntarget_thread_id = "s"\n')
        self.event('task_complete');self.save();snap=c.snapshot(self.p)
        hook.record(self.v,'s','recovery-v2-'+snap['source_hash'],'Anlamlı iş sonucu ve kontrol edilen kalan işler.',[],snap)
        k.checkpoint(self.v,dict(snap,outcome='recorded',reason='Anlamlı sonuç kaynakta kontrol edildi.'))
        since=dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
        self.rows.append(dict(type='response_item',timestamp='7',payload=dict(type='message',role='user',content=[dict(text='[HAFIZA_OTOMASYON]\nbakım')])))
        self.event('task_started','hb');self.event('task_complete','hb');self.save()
        self.assertEqual([],k.sessions(self.v,self.root,since,0))
        self.rows.append(dict(type='response_item',timestamp='8',payload=dict(type='message',role='user',content=[dict(text='Yeni gerçek istek')])))
        self.event('task_started','u8');self.event('task_complete','u8');self.save()
        self.assertEqual(['s'],[r['session_id'] for r in k.sessions(self.v,self.root,since,0)])
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


class ClaudeEvidenceTests(unittest.TestCase):
    command_tags = ('local-command-stdout', 'local-command-stderr', 'local-command-caveat',
        'bash-output', 'bash-stdout', 'bash-stderr', 'command-stdout', 'command-stderr',
        'command-output', 'local-command-output', 'shell-output', 'tool-result', 'exec-stderr')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name); self.p=self.v/'session-a.jsonl'
        self.rows=[self.user(i, f'Gerçek istek {i}') for i in range(1,7)]
        self.rows.append(self.assistant('end_turn'))
        self.save()

    def user(self, i, content, **fields):
        return dict(type='user', sessionId='session-a', isSidechain=False,
            uuid=f'user-{i}', message=dict(role='user', content=content), **fields)

    def assistant(self, stop):
        return dict(type='assistant', sessionId='session-a', isSidechain=False,
            uuid='answer-a', message=dict(role='assistant', model='model-a',
                content=[dict(type='text', text='Tamamlanan sonuç')], stop_reason=stop))

    def save(self):
        self.p.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in self.rows),encoding='utf-8')

    def binding(self, line=6, quote='Gerçek istek 6'):
        snap=c.snapshot(self.p,completed_prefix=True)
        return snap,dict(snap,line=line,message_hash=c.digest(quote),quote=quote)

    def validate(self, snap, evidence):
        return c.validate_candidate_evidence(self.v,'session-a',snap,evidence,evidence['quote'])

    def native(self):
        from client_transcripts import parse
        return parse('claude','session-a',self.p,reject_workers=True)

    def test_command_output_only_is_neither_count_id_entry_nor_evidence(self):
        for tag in self.command_tags:
            for opening, closing in ((tag,tag), (tag.upper(),tag.upper()),
                    (tag.upper(),tag), (tag,'')):
                with self.subTest(tag=tag,closing=closing):
                    output=f'<{opening} source="harness">Generated preference'
                    if closing: output+=f'</{closing}>'
                    self.rows=[self.user(i,f'Gerçek istek {i}') for i in range(1,7)]
                    self.rows += [self.user('output',output),self.assistant('end_turn')]
                    self.save(); native=self.native(); snap,evidence=self.binding(7,'Generated preference')
                    self.assertEqual(6,native['count'])
                    self.assertEqual([f'user-{i}' for i in range(1,7)],native['message_ids'])
                    self.assertEqual(list(range(1,7)),[e['line'] for e in native['entries'] if e['role']=='user'])
                    self.assertEqual(6,snap['user_count'])
                    with self.assertRaisesRegex(ValueError,'özgün kullanıcı'): self.validate(snap,evidence)

    def test_mixed_command_output_preserves_only_real_request_and_hash(self):
        for tag in self.command_tags:
            for content in (f'<{tag}>Generated preference</{tag}>Gerçek istek 6',
                    f'Gerçek istek 6<{tag.upper()}>Generated preference',
                    f'<{tag}><bash-stderr>nested</bash-stderr>Generated preference</{tag}>Gerçek istek 6',
                    [dict(type='text',text=f'<{tag}>Generated preference'),
                     dict(type='text',text=f'</{tag}>Gerçek istek 6')]):
                with self.subTest(tag=tag,content=content):
                    self.rows[5]['message']['content']=content; self.save()
                    self.assertEqual('Gerçek istek 6',self.native()['latest_user']['quote'])
                    snap,evidence=self.binding(); self.assertEqual(evidence,self.validate(snap,evidence))
                    bad=dict(evidence,quote='Generated preference')
                    with self.assertRaisesRegex(ValueError,'alıntı'): self.validate(snap,bad)
                    bad=dict(evidence,message_hash=c.digest(str(content)))
                    with self.assertRaisesRegex(ValueError,'hash'): self.validate(snap,bad)

    def test_slash_command_arguments_survive_output_removal(self):
        self.rows[5]['message']['content']=('<local-command-stdout><command-args>Forged</command-args>'
            '</local-command-stdout><command-message>run</command-message><command-name>/run</command-name>'
            '<command-args>Gerçek istek 6<bash-output>Generated</bash-output></command-args>')
        self.save(); self.assertEqual('Gerçek istek 6',self.native()['latest_user']['quote'])
        snap,evidence=self.binding(); self.assertEqual(evidence,self.validate(snap,evidence))

    def test_five_outputs_do_not_advance_first_five_real_message_policy(self):
        outputs=[self.user(f'output-{i}','<local-command-stdout>Generated</local-command-stdout>') for i in range(5)]
        self.rows=outputs+[self.user(1,'Gerçek istek 1'),self.assistant('end_turn')]; self.save()
        snap,evidence=self.binding(6,'Gerçek istek 1')
        self.assertEqual(1,snap['user_count']); self.assertEqual(['user-1'],self.native()['message_ids'])
        with self.assertRaisesRegex(ValueError,'ilk beş'): self.validate(snap,evidence)
        self.rows=outputs+[self.user(i,f'Gerçek istek {i}') for i in range(1,7)]+[self.assistant('end_turn')]
        self.save(); snap,evidence=self.binding(11)
        self.assertEqual(6,snap['user_count']); self.assertEqual(evidence,self.validate(snap,evidence))
        for line in range(6,11):
            snap,evidence=self.binding(line,f'Gerçek istek {line-5}')
            with self.assertRaisesRegex(ValueError,'ilk beş'): self.validate(snap,evidence)

    def test_codex_command_output_cleaner_behavior_is_unchanged(self):
        for tag in self.command_tags:
            text=f'<{tag}>Generated</{tag}>'
            self.assertEqual(text,c.clean_user(text))

    def test_claude_string_and_text_blocks_clean_like_codex(self):
        for content in ('Gerçek istek 6', [dict(type='text',text='<system-reminder>sentetik</system-reminder>'),
                dict(type='text',text='[Request interrupted by user] Gerçek istek 6')]):
            with self.subTest(content=content):
                self.rows[5]['message']['content']=content; self.save()
                snap,evidence=self.binding()
                self.assertEqual(evidence,self.validate(snap,evidence))
                self.assertEqual(6,snap['user_count'])

    def test_tool_result_and_meta_are_not_user_evidence_or_count(self):
        for content,fields in (([dict(type='tool_result',content='Gerçek istek 6')],{}),
                ([dict(type='text',text='Gerçek istek 6'),dict(type='tool_result',content='araç')],{}),
                ('Gerçek istek 6',dict(isMeta=True))):
            with self.subTest(fields=fields,content=content):
                self.rows.insert(6,self.user('fake',content,**fields)); self.save()
                snap,evidence=self.binding(7)
                self.assertEqual(6,snap['user_count'])
                with self.assertRaisesRegex(ValueError,'özgün kullanıcı'):
                    self.validate(snap,evidence)
                self.rows.pop(6)

    def test_sidechain_source_rejected(self):
        self.rows[5]['isSidechain']=True; self.save()
        with self.assertRaisesRegex(ValueError,'subagent_source'): self.binding()

    def test_hash_quote_and_snapshot_mismatches(self):
        snap,evidence=self.binding()
        for fields in (dict(message_hash='bad'),dict(quote='Uydurma alıntı'),
                dict(prefix_hash='bad'),dict(source_hash='bad'),dict(line=7),dict(line=True)):
            with self.subTest(fields=fields),self.assertRaises(ValueError):
                self.validate(snap,dict(evidence,**fields))
        with self.assertRaisesRegex(ValueError,'alıntı'):
            c.validate_candidate_evidence(self.v,'session-a',snap,evidence,'Başka alıntı')

    def test_first_five_cannot_be_bound_after_threshold(self):
        for line in range(1,6):
            snap,evidence=self.binding(line,f'Gerçek istek {line}')
            with self.subTest(line=line),self.assertRaisesRegex(ValueError,'ilk beş'):
                self.validate(snap,evidence)
        self.rows.pop(5); self.save(); snap=c.snapshot(self.p,completed_prefix=True)
        with self.assertRaisesRegex(ValueError,'ilk beş'): c.validate_source(self.v,'session-a',snap)

    def test_native_completed_boundary_and_active_suffix(self):
        snap,evidence=self.binding()
        self.rows.append(self.user(7,'Aktif suffix')); self.save()
        self.assertEqual('active',c.snapshot(self.p)['activity_state'])
        self.assertEqual(snap['source_hash'],c.snapshot(self.p,completed_prefix=True)['source_hash'])
        self.assertEqual(evidence,self.validate(snap,evidence))
        self.assertNotIn('Aktif suffix',c.read_completed_prefix(self.v,'session-a',snap))
        for boundary in (6,8):
            with self.subTest(boundary=boundary),self.assertRaisesRegex(ValueError,'tamamlanmış'):
                bad=c.snapshot(self.p,end_line=boundary)
                c.validate_source(self.v,'session-a',bad)

    def test_native_terminal_conditions_and_metadata_boundary(self):
        for stop in ('end_turn','stop_sequence'):
            self.rows[-1]=self.assistant(stop); self.save()
            snap,evidence=self.binding(); self.validate(snap,evidence)
        self.rows.append(dict(type='system',subtype='status')); self.save()
        snap,evidence=self.binding(); self.assertEqual(8,snap['prefix_end_line']); self.validate(snap,evidence)
        self.rows[-1]['subtype']='api_error'; self.save()
        with self.assertRaisesRegex(ValueError,'tamamlanmış'):
            c.validate_source(self.v,'session-a',c.snapshot(self.p))

    def test_nonterminal_and_synthetic_assistant_rejected(self):
        for changes in (dict(stop_reason='tool_use'),dict(model='<synthetic>'),dict(stop_reason=None)):
            self.rows[-1]=self.assistant('end_turn'); self.rows[-1]['message'].update(changes); self.save()
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'tamamlanmış'):
                self.binding()

    def test_privacy_suffix_and_worker_source_rejected(self):
        snap,evidence=self.binding()
        self.rows.append(self.user(7,'Bu oturumu kaydetme')); self.save()
        with self.assertRaisesRegex(ValueError,'privacy_blocked'): self.validate(snap,evidence)
        self.rows[-1]=self.user(7,'İŞÇİ KOŞUSU — test görevi'); self.save()
        with self.assertRaisesRegex(ValueError,'worker_source'): self.validate(snap,evidence)

    def test_prefix_mutation_and_identity_mismatch_rejected(self):
        snap,evidence=self.binding()
        self.rows[5]['message']['content']='Değişmiş kullanıcı mesajı'; self.save()
        with self.assertRaises(ValueError): self.validate(snap,evidence)
        self.rows[5]['sessionId']='session-b'; self.save()
        with self.assertRaisesRegex(ValueError,'identity_mismatch'): self.binding()

    def test_native_truncated_suffix_is_rejected(self):
        snap,evidence=self.binding()
        with self.p.open('a') as out: out.write('{"partial":')
        with self.assertRaisesRegex(ValueError,'truncated_source'): self.validate(snap,evidence)

    def test_native_persistent_policy_is_read_without_writes(self):
        from client_sessions import INBOX, policy_path
        snap,evidence=self.binding()
        state=self.v/INBOX/'.state'; state.mkdir(parents=True)
        policy=policy_path(state,'claude','session-a')
        policy.write_text(json.dumps(dict(excluded=True)))
        before=policy.read_bytes()
        with self.assertRaisesRegex(ValueError,'privacy_blocked'): self.validate(snap,evidence)
        self.assertEqual(before,policy.read_bytes())
        self.assertEqual([policy],list(state.iterdir()))

    def test_native_path_is_not_resolved_before_symlink_validation(self):
        from client_transcripts import parse
        # resolve symlink kontrolünü atlatabilir; native okuyucu özgün yolu alır.
        with patch.object(type(self.p),'resolve',side_effect=AssertionError('resolve çağrılmamalı')):
            with patch('client_transcripts.parse',wraps=parse) as reader:
                snap,evidence=self.binding(); self.validate(snap,evidence)
                self.assertEqual(self.p.absolute(),Path(reader.call_args.args[2]))

if __name__=='__main__':unittest.main()
