"""Synthetic genuine user turn selection for native client hooks."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import client_hafiza
import gorev_baglam
import jev_client


class HistoryTests(unittest.TestCase):
    def test_syn_lagging_transcript_refresh(self):
        """SYN-lagging-transcript-refresh: stale native IDs cannot stop renewal."""
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            package = dict(text='Kaynaklı bellek', selected_ids=[],
                           delivered_segments={'card-a':'Kaynaklı bellek'})
            source = dict(latest_user=dict(quote='Kaynağı incele', message_id='old-native'), entries=[])
            with (patch.object(client_hafiza, 'claude_task_package', return_value=package),
                  patch('codex_hafiza.opening_brief', return_value=''),
                  patch('codex_hafiza.latest_session_section', return_value=''),
                  patch.object(client_hafiza, 'recall', return_value='')):
                def event(prompt):
                    return client_hafiza.context(vault, 'claude', 'fixture', source,
                                                {'prompt':prompt}, 'UserPromptSubmit')
                self.assertIn(package['text'], event('Kaynağı incele'))
                for n in range(client_hafiza.REFRESH_TURNS):
                    self.assertEqual(event('devam' if n % 2 else 'tamam'), '')
                self.assertIn(package['text'], event('devam'))
                state_path = next(vault.rglob('context-*.json'))
                self.assertEqual(json.loads(state_path.read_text())['user_turns'], 10)
                # Repeated payloads with the stale ID still represent ID-less events.
                self.assertEqual(event('devam'), '')
                self.assertEqual(json.loads(state_path.read_text())['user_turns'], 11)
                source['latest_user'] = dict(quote='devam\n<task-notification>harness</task-notification>',
                                             message_id='current-native')
                event('devam')
                before = state_path.read_bytes()
                self.assertEqual(event('devam'), '')
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(json.loads(before)['user_turns'], 12)

    def test_syn_no_transcript_refresh(self):
        """SYN-no-transcript-refresh: identical events are genuine turns without IDs."""
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            package = dict(text='Kaynaklı bellek', selected_ids=[],
                           delivered_segments={'card-a':'Kaynaklı bellek'})
            with (patch.object(client_hafiza, 'claude_task_package', return_value=package),
                  patch('codex_hafiza.opening_brief', return_value=''),
                  patch('codex_hafiza.latest_session_section', return_value=''),
                  patch.object(client_hafiza, 'recall', return_value='')):
                def event(source=None):
                    return client_hafiza.context(vault, 'claude', 'fixture', source,
                                                {'prompt':'devam'}, 'UserPromptSubmit')
                self.assertIn(package['text'], event())
                for _ in range(client_hafiza.REFRESH_TURNS):
                    self.assertEqual(event(), '')
                self.assertIn(package['text'], event())
                state_path = next(vault.rglob('context-*.json'))
                self.assertEqual(json.loads(state_path.read_text())['user_turns'], 10)
                with patch.object(client_hafiza.time, 'time', return_value=10**12):
                    self.assertIn(package['text'], event())
                source = dict(latest_user=dict(quote='devam', message_id='native'), entries=[])
                event(source)
                before = state_path.read_bytes()
                self.assertEqual(event(source), '')
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(json.loads(before)['user_turns'], 12)

    def test_final_lesson_receipts_both_clients(self):
        import codex_hafiza as codex
        import fayda_olc
        for client in ('claude', 'codex'):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                vault = Path(directory)
                package = dict(text='', selected_ids=[], delivered_segments={},
                               delivered_lessons=[], delivered_lesson_segments={})
                def lesson(version, repeats=10):
                    segment = (f'Ders {version}\nKaynak: sentetik.md\n' + 'Ayrıntı ' * repeats).rstrip()
                    package.update(text=segment, delivered_segments={'methods':segment},
                        delivered_lessons=[dict(id='l1',version=version)],
                        delivered_lesson_segments={'l1':segment})
                def event(n):
                    if client == 'claude':
                        return client_hafiza.context(vault, client, 'fixture', None,
                            {'prompt':f'Dersi incele {n}'}, 'UserPromptSubmit')
                    return codex.hook(vault, dict(session_id='fixture', turn_id=str(n),
                        prompt=f'Dersi incele {n}', hook_event_name='UserPromptSubmit')).get(
                            'hookSpecificOutput', {}).get('additionalContext', '')
                with (patch.object(client_hafiza, 'claude_task_package', return_value=package),
                      patch.object(gorev_baglam, 'build_task_package', return_value=package),
                      patch.object(codex, 'opening_brief', return_value=''),
                      patch.object(codex, 'latest_session_section', return_value=''),
                      patch.object(codex, 'shared_reviewed_context', return_value=''),
                      patch.object(client_hafiza, 'recall', return_value=''),
                      patch.object(fayda_olc, 'record_delivery') as record):
                    lesson(1)
                    self.assertIn(package['text'], event(1))
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [dict(id='l1',version=1)])
                    self.assertEqual(event(2), '')
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [])
                    lesson(2)
                    updated = event(3)
                    self.assertIn('Güncellendi: Ders 2', updated)
                    self.assertNotIn(package['text'], updated)
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [dict(id='l1',version=2)])
                    self.assertEqual(event(4), '')
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [])
                    lesson(3)
                    if client == 'claude':
                        with patch.object(client_hafiza, 'CONTEXT_BUDGET', 120):
                            event(5)
                    else:
                        # The final Codex output cannot restore a package-budget cut unit.
                        package['text'] = package['text'][:40]
                        event(5)
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [])
                    lesson(3)
                    self.assertIn('Güncellendi: Ders 3', event(6))
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [dict(id='l1',version=3)])
                    lesson(4, repeats=100)
                    shortened = event(7)
                    self.assertIn('[ayrıntıyı kaynaktan doğrula]', shortened)
                    self.assertNotIn(' '.join(package['text'].split()), shortened)
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [])
                    state_path = (next(vault.rglob('context-*.json')) if client == 'claude'
                                  else vault / codex.INBOX / '.state' / (codex.key('fixture', 'state') + '.json'))
                    self.assertEqual(json.loads(state_path.read_text())['delivered_lessons'], [])
                    # The abbreviated presentation still suppresses identical delta output.
                    self.assertEqual(event(8), '')
                    self.assertEqual(record.call_args.kwargs['delivered_lessons'], [])

    def test_previous_turn_ignores_peer_and_attached_notifications(self):
        source = {'entries': [dict(role='user', quote='Earlier task\n'
            '<task-notification>Foreign project</task-notification>'),
            dict(role='user', quote='<cross-session-message from="peer">'
                 'Foreign project</cross-session-message>'),
            dict(role='user', quote='Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')

    def test_previous_turn_ignores_t30_metadata_and_expansions(self):
        source = {'entries': [dict(role='user', quote=quote) for quote in (
            'Earlier task',
            '[Cross-session delivery notice] Synthetic delivery.',
            '[Image: source: /tmp/synthetic.png]',
            '# /loop — schedule a recurring or self-paced prompt\nForeign body',
            'Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')

    def test_delivery_receipt_contains_content_free_installation_version(self):
        import fayda_olc
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            lesson = dict(id='synthetic', version=1)
            with patch.object(fayda_olc.h, 'load_jsonl', return_value=[lesson]):
                receipt = fayda_olc._record_delivery(vault, client='claude', session_id='synthetic',
                    package_id='synthetic', delivered_lessons=[lesson], turn_id='synthetic')
            self.assertRegex(receipt['installation_version'], r'^araclar-sha256:[0-9a-f]{64}$')
            self.assertNotIn('prompt', receipt)
            self.assertNotIn('content', receipt)
            self.assertEqual(json.loads((vault / fayda_olc.DELIVERIES).read_text()), receipt)

    def test_previous_turn_attached_secret_still_blocks_context(self):
        source = {'entries': [dict(role='user', quote='Earlier task\n'
            '<task-notification>api_key=sk-' + 'x' * 48 + '</task-notification>'),
            dict(role='user', quote='Current task')]}
        self.assertIsNone(client_hafiza.previous_user(source, 'Current task'))

    def test_opening_budget_and_first_prompt_do_not_repeat_delivered_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            source = dict(latest_user=dict(quote='First task', message_id='u1'), entries=[])
            with (patch('codex_hafiza.opening_brief', return_value='B'*1800),
                  patch('codex_hafiza.latest_session_section', return_value='L'*1800),
                  patch.object(client_hafiza, 'recall', side_effect=lambda *a, **k: 'R'*k['budget']),
                  patch.object(client_hafiza, 'claude_task_package', return_value={
                      'text':'Current task evidence\n'+'P'*1950,'selected_ids':[]})):
                text = client_hafiza.context(vault,'claude','fixture',source,{},'SessionStart')
                self.assertLessEqual(len(text),3500)
                self.assertIn('Current task evidence',text)
                first = client_hafiza.context(vault,'claude','fixture',source,
                                             {'prompt':'Different first task'},'UserPromptSubmit')
                self.assertIn('Current task evidence',first)
                # Açılışta teslim edilmiş satır oturum boyunca tekrar gelmez.
                later = client_hafiza.context(vault,'claude','fixture',source,
                                             {'prompt':'Another task'},'UserPromptSubmit')
                self.assertNotIn('Current task evidence',later)

    def test_session_delta_versions_restart_and_independent_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            package = dict(text='Kart bilgisi', project_id='proj-a', selected_ids=['card-a'],
                           delivered_segments={'card-a':'Kart bilgisi'}, delivery_versions={'card-a':'v1'})
            with (patch.object(client_hafiza, 'claude_task_package', return_value=package),
                  patch.object(client_hafiza, 'local_task_package', return_value=package),
                  patch('codex_hafiza.opening_brief', return_value=''),
                  patch('codex_hafiza.latest_session_section', return_value=''),
                  patch.object(client_hafiza, 'recall', return_value='')):
                for client in ('claude', 'antigravity'):
                    def turn(n, session='fixture'):
                        source = dict(latest_user=dict(quote='Görevi incele '+str(n), message_id=str(n)), entries=[])
                        return client_hafiza.context(vault,client,session,source,
                            {'prompt':'Görevi incele '+str(n)},'UserPromptSubmit' if client=='claude' else 'PreInvocation')
                    self.assertIn('Kart bilgisi', turn(1))
                    self.assertEqual(turn(2), '')
                    self.assertEqual(turn(3), '')
                    package['delivery_versions']['card-a']='v2'
                    package['text']='Yeni kart bilgisi'
                    package['delivered_segments']['card-a']=package['text']
                    self.assertIn('Güncellendi: Yeni kart bilgisi', turn(4))
                    self.assertEqual(turn(5), '')
                    self.assertIn('Yeni kart bilgisi', turn(1, 'other'))
                    package.update(text='Kart bilgisi')
                    package['delivered_segments']['card-a']=package['text']
                    package['delivery_versions']['card-a']='v1'
                text=client_hafiza.context(vault,'claude','fixture',None,{},'SessionStart')
                self.assertEqual(text, '')
                source=dict(latest_user=dict(quote='Yeni görev',message_id='6'),entries=[])
                self.assertIn('Kart bilgisi',client_hafiza.context(vault,'claude','fixture',source,
                    {'prompt':'Yeni görev'},'UserPromptSubmit'))

    def test_memoryless_gate_first_genuine_turn_and_references(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory).resolve()
            package=dict(text='Bellek',selected_ids=[],delivered_segments={})
            with (patch.object(client_hafiza,'claude_task_package',return_value=package) as build,
                  patch('codex_hafiza.opening_brief',return_value=''),
                  patch('codex_hafiza.latest_session_section',return_value=''),
                  patch.object(client_hafiza,'recall',return_value=''),
                  patch.object(gorev_baglam,'config',return_value={'projects':[
                      dict(id='proj-a',aliases=['alt iş'])]})):
                client_hafiza.context(vault,'claude','fixture',None,{},'SessionStart')
                self.assertIn('Bellek', client_hafiza.context(vault,'claude','fixture',None,
                    {'prompt':'tamam'},'UserPromptSubmit'))
                for query in ('ok','evet','hayır','go','devam','sil','kısalt','sadece örnek yaz'):
                    build.reset_mock()
                    self.assertEqual(client_hafiza.context(vault,'claude','fixture',None,
                        {'prompt':query},'UserPromptSubmit'),'')
                    build.assert_not_called()
                for query in ('dün tamam','önceki kayıt','hafızayı hatırla','proj-a devam','alt iş devam'):
                    build.reset_mock()
                    client_hafiza.context(vault,'claude','fixture',None,{'prompt':query},'UserPromptSubmit')
                    build.assert_called_once()

    def test_empty_harness_does_not_consume_first_turn_for_any_client(self):
        with tempfile.TemporaryDirectory() as directory:
            for client,event in (('claude','UserPromptSubmit'),('antigravity','PreInvocation')):
                source=dict(latest_user=dict(quote='[Request interrupted by user]',message_id='u1'),entries=[])
                with patch.object(client_hafiza,'local_task_package') as build:
                    self.assertEqual(client_hafiza.context(Path(directory),client,'fixture',source,
                        {'prompt':source['latest_user']['quote']},event),'')
                    build.assert_not_called()
            self.assertFalse(list(Path(directory).rglob('context-*.json')))

    def test_knowledge_and_lesson_units_do_not_repeat_siblings(self):
        package=dict(delivered_segments={'knowledge':'Bilgi [a]: bir\nBilgi [b]: iki',
            'methods':'Yöntem\nDers bir\nDers iki'}, knowledge={'records':[
                dict(id='n1',statement='bir'),dict(id='n2',statement='iki')]},
            delivered_lessons=[dict(id='l1',version=1),dict(id='l2',version=2)],
            delivered_lesson_segments={'l1':'Ders bir','l2':'Ders iki'})
        units=client_hafiza.delivery_units(package)
        self.assertEqual([u[0] for u in units],['knowledge:n1','knowledge:n2','lesson:l1','lesson:l2','methods-header'])

    def test_update_is_short_and_keeps_source_reference(self):
        text=client_hafiza.updated_line('Kart '+('uzun bilgi '*100)+' (kaynak: kaynak.md)')
        self.assertLessEqual(len(text),510)
        self.assertTrue(text.startswith('Güncellendi: '))
        self.assertIn('kaynak.md',text)

    def test_truncated_card_is_not_marked_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory).resolve()
            package=dict(text='X'*1500+'\n'+'Y'*400,selected_ids=['a','b'],
                delivered_segments={'a':'X'*1500,'b':'Y'*400}, delivery_versions={'a':'1','b':'1'})
            with (patch.object(client_hafiza,'claude_task_package',return_value=package),
                  patch.object(client_hafiza,'CONTEXT_BUDGET',1700),
                  patch('codex_hafiza.opening_brief',return_value=''),
                  patch('codex_hafiza.latest_session_section',return_value=''),
                  patch.object(client_hafiza,'recall',return_value='')):
                client_hafiza.context(vault,'claude','fixture',None,{'prompt':'İlk görev'},'UserPromptSubmit')
                text=client_hafiza.context(vault,'claude','fixture',None,{'prompt':'İkinci görev'},'UserPromptSubmit')
                self.assertNotIn('X'*1500,text)
                self.assertIn('Y'*400,text)

    def test_generation_and_bounded_refresh_both_clients(self):
        import codex_hafiza as codex
        import client_sessions as sessions
        package = dict(text='Kaynaklı eşik değeri 42.', project_id='proj-a', selected_ids=['card-a'],
            delivered_segments={'card-a':'Kaynaklı eşik değeri 42.'}, delivery_versions={'card-a':'v1'})
        for client in ('claude', 'codex'):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                vault = Path(directory)
                def event(name, n, prompt='devam', source=None):
                    if client == 'codex':
                        out = codex.hook(vault, dict(session_id='fixture', hook_event_name=name,
                            turn_id=str(n), prompt=prompt, source=source))
                        return out.get('hookSpecificOutput', {}).get('additionalContext', '')
                    src = dict(latest_user=dict(quote=prompt, message_id=str(n)), entries=[])
                    return client_hafiza.context(vault, client, 'fixture', src,
                        dict(prompt=prompt, source=source), name)
                with (patch.object(client_hafiza, 'claude_task_package', return_value=package),
                      patch.object(gorev_baglam, 'build_task_package', return_value=package),
                      patch.object(codex, 'opening_brief', return_value=''),
                      patch.object(codex, 'latest_session_section', return_value=''),
                      patch.object(codex, 'shared_reviewed_context', return_value=''),
                      patch.object(client_hafiza, 'recall', return_value='')):
                    self.assertIn(package['text'], event('UserPromptSubmit', 1, 'İncele'))
                    for n, mode in enumerate(('resume','compact','clear','restart','unknown'), 2):
                        event('SessionStart', n, source=mode)
                        self.assertIn(package['text'], event('UserPromptSubmit', n))
                        self.assertNotIn('Güncellendi:', event('UserPromptSubmit', n))
                    # Eight genuine turns can be suppressed; the ninth renews even "devam".
                    for n in range(7, 15):
                        self.assertEqual(event('UserPromptSubmit', n), '')
                    self.assertIn(package['text'], event('UserPromptSubmit', 15))
                    with patch.object(client_hafiza.time, 'time', return_value=10**12):
                        self.assertIn(package['text'], event('UserPromptSubmit', 16))
                state_path = next(vault.rglob('context-*.json')) if client == 'claude' else next(vault.rglob('.state/*.json'))
                state = sessions.load(state_path)
                self.assertEqual(state['context_generation'], 5)
                self.assertEqual(state['user_turns' if client == 'claude' else 'count'], 16)

    def test_syn_truncated_report_is_retried_both_clients(self):
        import codex_hafiza as codex
        segment = 'Kart kanıtı: raporu ölçümü kaynağı bağımsız doğrulayarak sonucu tekrar kontrol et'
        card = dict(id='card-a', project_id='proj-a', assertion_kind='assistant_report',
                    next_step='Raporu ölçümü kaynağı bağımsız doğrulayarak sonucu tekrar kontrol et')
        package = dict(text=segment, selected_ids=['card-a'], project_id='proj-a',
            delivered_segments={'card-a':segment}, delivery_versions={'card-a':'v1'})
        for client in ('claude','codex'):
            with self.subTest(client=client), tempfile.TemporaryDirectory() as directory:
                vault = Path(directory)
                with (patch.object(client_hafiza,'claude_task_package',return_value=package),
                      patch.object(gorev_baglam,'build_task_package',return_value=package),
                      patch.object(codex,'opening_brief',return_value=''),
                      patch.object(codex,'latest_session_section',return_value=''),
                      patch.object(codex,'shared_reviewed_context',return_value=''),
                      patch.object(client_hafiza,'recall',return_value=''),
                      patch('is_ve_ders.brief',return_value=[card])):
                    if client == 'claude':
                        with patch.object(client_hafiza,'CONTEXT_BUDGET',100):
                            first=client_hafiza.context(vault,client,'fixture',None,{'prompt':'İlk görev'},'UserPromptSubmit')
                        second=client_hafiza.context(vault,client,'fixture',None,{'prompt':'İkinci görev'},'UserPromptSubmit')
                    else:
                        # Package budget cuts a unit before the Codex final output is built.
                        package['text']=segment[:30]
                        first=str(codex.hook(vault,dict(session_id='fixture',hook_event_name='UserPromptSubmit',turn_id='1',prompt='İlk görev')))
                        package['text']=segment
                        second=str(codex.hook(vault,dict(session_id='fixture',hook_event_name='UserPromptSubmit',turn_id='2',prompt='İkinci görev')))
                    self.assertNotIn(segment,first)
                    self.assertIn(segment,second)

    def test_previous_genuine_user_turn_only(self):
        source = {'entries': [dict(role='user', quote='Earlier task'),
                              dict(role='assistant', quote='response'),
                              dict(role='user', quote='Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        source['entries'].pop()
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        with patch.object(gorev_baglam, 'build_task_package', return_value={}) as build:
            client_hafiza.local_task_package('/tmp/example', 'Current task', previous_user='Earlier task')
        self.assertEqual(build.call_args.kwargs['previous_user'], 'Earlier task')

    def test_private_previous_turn_is_excluded(self):
        source = {'entries': [dict(role='user', quote='Do not save this private request'),
                              dict(role='user', quote='Current task')]}
        self.assertIsNone(client_hafiza.previous_user(source, 'Current task'))

    def test_claude_shadow_logs_hash_without_prompt_and_keeps_local_text(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory).resolve()
            local={'text':'local context','selected_ids':['local']}
            shadow={'text':'remote context','selected_ids':['memory:m1'],
                    'jev':{'gate':{'scores':{},'diagnostics':[]},
                           'catalog':{'scores':{'memory:m1':1.8},'diagnostics':[]}}}
            with (patch.object(jev_client,'load_config',return_value=dict(jev_client.DEFAULTS,mode='shadow',claude_hook_mode='shadow')),
                  patch.object(client_hafiza,'local_task_package',return_value=local),
                  patch.object(gorev_baglam,'build_task_package',return_value=shadow) as build):
                result=client_hafiza.claude_task_package(vault,'Synthetic writing request',previous_user='Earlier synthetic task')
            self.assertIs(result,local)
            build.assert_called_once()
            lines=list((vault/'.cache/jev-golge').glob('*.jsonl'))
            self.assertEqual(len(lines),1)
            raw=lines[0].read_text()
            self.assertNotIn('Synthetic writing request',raw)
            self.assertNotIn('Earlier synthetic task',raw)
            self.assertEqual(json.loads(raw)['selected_ids'],['memory:m1'])


    def test_global_off_prevents_claude_shadow_and_on_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            local = {'text': 'Local task context'}
            for hook_mode in ('shadow', 'on'):
                with self.subTest(hook_mode=hook_mode):
                    with (patch.object(jev_client, 'load_config', return_value=dict(
                              jev_client.DEFAULTS, mode='off', claude_hook_mode=hook_mode)),
                          patch.object(client_hafiza, 'local_task_package', return_value=local),
                          patch.object(gorev_baglam, 'build_task_package') as build):
                        self.assertIs(client_hafiza.claude_task_package(vault, 'Synthetic task'), local)
                    build.assert_not_called()
            self.assertFalse((vault / '.cache/jev-golge').exists())

    def test_claude_shadow_does_not_reenable_global_off_during_request(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory).resolve()
            seen_modes = []
            def build(path, *args, **kwargs):
                seen_modes.append(jev_client.load_config(path)['mode'])
                return {'text': ''}
            enabled = dict(jev_client.DEFAULTS, mode='shadow', claude_hook_mode='shadow')
            disabled = dict(enabled, mode='off')
            with (patch.object(jev_client, 'load_config', side_effect=[enabled, disabled]),
                  patch.object(client_hafiza, 'local_task_package', return_value={'text': 'local'}),
                  patch.object(gorev_baglam, 'build_task_package', side_effect=build)):
                client_hafiza.claude_task_package(vault, 'Synthetic task')
            self.assertEqual(seen_modes, ['off'])


class HookHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()

    def fail(self, event='Stop', error=None):
        from client_transcripts import SourceError
        error = error or SourceError('registry_limit')
        with patch.object(client_hafiza, '_hook', side_effect=error):
            with self.assertRaises(type(error)):
                client_hafiza.hook(self.vault, 'claude', event, {'prompt': 'NEVER STORE THIS'})

    def opening(self):
        with patch.object(client_hafiza, '_hook', return_value=({}, {'status': 'context_suppressed'})):
            return client_hafiza.hook(self.vault, 'claude', 'SessionStart', {})[0]

    def test_registry_failure_records_only_health_fields_and_warns(self):
        import hook_health as health
        self.fail()
        row = health.read_events(self.vault)[0]
        self.assertEqual(set(row), {'at', 'client', 'event_type', 'error_code', 'installation_version'})
        self.assertEqual(row['error_code'], 'registry_limit')
        self.assertEqual(row['event_type'], 'Stop')
        self.assertNotIn('NEVER STORE THIS', (self.vault / health.PATH).read_text())
        text = self.opening()['hookSpecificOutput']['additionalContext']
        self.assertIn('oturum yakalama 1 kez başarısız (registry_limit)', text)
        self.assertLessEqual(len(text), 241)

    def test_expected_source_rejections_do_not_warn(self):
        import hook_health as health
        from client_transcripts import SourceError
        for code in ('privacy_blocked', 'source_validation_failed', 'source_identity_mismatch', 'threshold_or_incomplete'):
            self.fail(error=SourceError(code))
        self.assertEqual(health.read_events(self.vault), [])
        self.assertEqual(self.opening(), {})

    def test_prompt_threshold_and_24_hour_window(self):
        import datetime as dt
        import hook_health as health
        for _ in range(2):
            self.fail('UserPromptSubmit')
        self.assertEqual(self.opening(), {})
        self.fail('UserPromptSubmit')
        self.assertIn('hook çalışması 3 kez', self.opening()['hookSpecificOutput']['additionalContext'])
        self.assertEqual(health.warning(self.vault, dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=25)), '')

    def test_telemetry_io_failure_keeps_original_hook_error(self):
        import hook_health as health
        with patch.object(health, 'exclusive_lock', side_effect=OSError('NEVER STORE THIS')):
            self.fail()
        self.assertEqual(health.read_events(self.vault), [])
        with patch.object(health, 'read_events', side_effect=OSError('NEVER STORE THIS')):
            self.assertEqual(health.warning(self.vault), '')

    def test_cli_failed_opening_still_shows_warning(self):
        import io
        import sys
        from client_transcripts import SourceError
        payload = {'session_id': 'synthetic', 'prompt': 'NEVER STORE THIS'}
        with patch.object(client_hafiza, '_hook', side_effect=SourceError('registry_limit')), \
             patch.object(sys, 'argv', ['client_hafiza.py', '--vault', str(self.vault),
                                      '--client', 'claude', '--event', 'SessionStart']), \
             patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()))), \
             patch.object(sys, 'stdout', io.StringIO()) as out, \
             patch.object(sys, 'stderr', io.StringIO()) as err:
            # This is the third same-code opening failure, with no normal context.
            self.fail('SessionStart')
            self.fail('SessionStart')
            self.assertEqual(client_hafiza.main(), 0)
            self.assertIn('hook çalışması 3 kez başarısız (registry_limit)',
                          json.loads(out.getvalue())['hookSpecificOutput']['additionalContext'])
            self.assertNotIn('NEVER STORE THIS', err.getvalue())

    def test_retention_and_nonblocking_lock(self):
        import hook_health as health
        from client_transcripts import SourceError
        from platform_lock import exclusive_lock
        health.record_failure(self.vault, 'claude', 'Stop', SourceError('registry_limit'))
        path = self.vault / health.PATH
        original = path.read_bytes()
        with exclusive_lock(path.with_suffix('.lock')):
            health.record_failure(self.vault, 'claude', 'Stop', SourceError('registry_limit'))
        self.assertEqual(path.read_bytes(), original)
        with patch.object(health, 'MAX_EVENTS', 3):
            for _ in range(6):
                health.record_failure(self.vault, 'claude', 'Stop', RuntimeError('NEVER STORE THIS'))
            self.assertEqual(len(health.read_events(self.vault)), 3)
        self.assertNotIn('NEVER STORE THIS', path.read_text())


if __name__ == '__main__':
    unittest.main()
