import argparse
import contextlib
import importlib.util
import io
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('baslat', ROOT / 'baslat.py')
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
import hafiza
import jev_client

class SetupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.args = argparse.Namespace(agent='codex', vault=str(self.root / 'örnek kasa'),
            client_home=str(self.root / 'client'), config_home=None, revision='a' * 40,
            non_interactive=True, skip_obsidian=True, configure_services=False, verify_services=False)
        self.archive = self.root / 'fixture.zip'
        with zipfile.ZipFile(self.archive, 'w') as z:
            for base in ['agents.md', 'araclar', 'zihin', 'komuta']:
                path = ROOT / base
                for f in ([path] if path.is_file() else path.rglob('*')):
                    if f.is_file() and '__pycache__' not in str(f) and f.suffix != '.pyc' and f.name not in ['jev.json','mem0.json','kurulum-sonucu.json']:
                        z.write(f, 'repo/' + f.relative_to(ROOT).as_posix())

    def install(self):
        def fake_download(url, destination, **kwargs): shutil.copyfile(self.archive, destination)
        with patch.object(b, 'download', side_effect=fake_download), contextlib.redirect_stdout(io.StringIO()):
            return b.run(self.args)

    def test_install_three_agents_and_preserve_instructions(self):
        for agent, rel in [('codex','.codex/AGENTS.md'),('claude','.claude/CLAUDE.md'),('antigravity','.gemini/GEMINI.md')]:
            with self.subTest(agent=agent):
                self.args.agent = agent; self.args.vault = str(self.root / agent)
                self.args.client_home = str(self.root / ('client-' + agent))
                target = Path(self.args.client_home) / rel
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text('Keep my instructions\n')
                with patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'wrong')}): self.install()
                self.assertIn('Keep my instructions', target.read_text())
                self.assertIn(self.args.vault, target.read_text())
                self.assertFalse((self.root/'wrong').exists())
                self.assertFalse((Path(self.args.vault)/'komuta/mem0.json').exists())

    def test_existing_bridge_rejected_before_network_or_new_vault(self):
        for agent, rel in [('codex', '.codex/AGENTS.md'),
                           ('claude', '.claude/CLAUDE.md'),
                           ('antigravity', '.gemini/GEMINI.md')]:
            with self.subTest(agent=agent):
                self.args.vault = str(self.root / ('new-' + agent))
                target = Path(self.args.client_home) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                original = '<!-- HAFIZA-OS:SHARED:START -->\nExisting vault\n<!-- HAFIZA-OS:SHARED:END -->\nPersonal instructions\n'
                target.write_text(original, encoding='utf-8')
                with patch.object(b, 'download') as download:
                    with self.assertRaisesRegex(ValueError, 'Mevcut'):
                        b.run(self.args)
                    download.assert_not_called()
                self.assertFalse(Path(self.args.vault).exists())
                self.assertEqual(target.read_text(encoding='utf-8'), original)
                target.unlink()

    def test_existing_default_vault_aliases_are_detected(self):
        home = Path(self.args.client_home)
        for name in ('Hafiza', 'Hafıza'):
            with self.subTest(name=name):
                vault = home / name
                (vault / 'araclar').mkdir(parents=True)
                (vault / 'agents.md').write_text('personal')
                (vault / 'araclar/hafiza.py').write_text('')
                with patch.object(b, 'download') as download:
                    with self.assertRaisesRegex(ValueError, 'Mevcut'):
                        b.run(self.args)
                    download.assert_not_called()
                self.assertFalse(Path(self.args.vault).exists())
                shutil.rmtree(vault)

    def test_custom_codex_home_is_detected_but_isolated_demo_is_allowed(self):
        custom = self.root / 'custom-codex'
        custom.mkdir()
        (custom / 'AGENTS.md').write_text('<!-- HAFIZA-OS:SHARED:START -->')
        with patch.dict(os.environ, {'CODEX_HOME': str(custom)}):
            with self.assertRaisesRegex(ValueError, 'Mevcut'):
                b.check_existing_installation(Path(self.args.client_home))
            self.install()
        self.assertIn('SHARED', (custom / 'AGENTS.md').read_text())

    def test_existing_target_and_symlink_rejected_before_network(self):
        vault = Path(self.args.vault); vault.mkdir(); (vault/'keep').write_text('mine')
        with self.assertRaises(ValueError): self.install()
        self.assertEqual((vault/'keep').read_text(),'mine')
        link = self.root/'link'
        try: link.symlink_to(vault, target_is_directory=True)
        except OSError: return  # Windows runner may not have symlink permission.
        self.args.vault = str(link/'new')
        with self.assertRaises(ValueError): self.install()
        self.assertFalse((vault/'new').exists())

    def test_keys_saved_outside_vault_and_used_by_actual_clients(self):
        vault=Path(self.args.vault);vault.mkdir();config=self.root/'secrets'
        with patch.object(b,'ask_mem0',return_value=('dummy-mem0','tester')), patch.object(b,'ask_jev',return_value=('dummy-jev','typesafe')):
            status=b.optional_services(vault,config)
        self.assertEqual(status['jev'],'configured_unverified')
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(hafiza.load_api_key(vault),'dummy-mem0')
            c=jev_client.load_config(vault)
            self.assertEqual(c['mode'],'on')
            self.assertEqual(jev_client._environment(c)['TYPESAFE_API_KEY'],'dummy-jev')
        for f in vault.rglob('*'):
            if f.is_file(): self.assertNotIn('dummy-',f.read_text())
        if os.name!='nt':
            for f in config.rglob('*.json'): self.assertEqual(stat.S_IMODE(f.stat().st_mode),0o600)

    def test_each_service_can_be_skipped_independently(self):
        for i,keys in enumerate([['',''],['dummy-mem0',''],['','dummy-jev']]):
            vault=self.root/str(i);vault.mkdir()
            with patch.object(b,'ask_mem0',return_value=(keys[0],'tester')),patch.object(b,'ask_jev',return_value=(keys[1],'typesafe')):
                b.optional_services(vault,self.root/'secrets')
            self.assertEqual((vault/'komuta/mem0.json').exists(),bool(keys[0]))
            self.assertEqual((vault/'komuta/jev.json').exists(),bool(keys[1]))

    def test_get_keys_opens_official_pages_and_returns_to_hidden_input(self):
        with patch('builtins.input',side_effect=['2','tester','2']), patch.object(b,'secret',side_effect=['dummy-mem0','dummy-jev']), patch.object(b,'open_site') as opened:
            self.assertEqual(b.ask_mem0(),('dummy-mem0','tester'))
            self.assertEqual(b.ask_jev(),('dummy-jev','vercel'))
        self.assertEqual([c.args[0] for c in opened.call_args_list],[b.MEM0_KEYS_URL,b.VERCEL_FREE_URL,b.VERCEL_KEYS_URL])

    def test_skip_never_opens_browser_or_asks_secret(self):
        with patch('builtins.input',return_value=''), patch.object(b,'secret') as secret, patch.object(b,'open_site') as opened:
            self.assertEqual(b.ask_mem0(),('',None))
            self.assertEqual(b.ask_jev(),('',None))
            secret.assert_not_called(); opened.assert_not_called()

    def test_existing_provider_selection_and_invalid_menu(self):
        for inputs,provider in [(['invalid','1',''],'vercel'),(['1','2'],'typesafe')]:
            with patch('builtins.input',side_effect=inputs), patch.object(b,'secret',return_value='dummy'), patch.object(b,'open_site') as opened:
                self.assertEqual(b.ask_jev(),('dummy',provider)); opened.assert_not_called()

    def test_browser_failure_keeps_manual_url(self):
        output=io.StringIO()
        with patch.object(b.webbrowser,'open_new_tab',side_effect=OSError), contextlib.redirect_stdout(output):
            b.open_site(b.MEM0_KEYS_URL)
        self.assertIn(b.MEM0_KEYS_URL,output.getvalue())

    def test_vercel_credentials_reach_only_vercel_endpoint(self):
        vault=self.root/'vercel';vault.mkdir()
        with patch.object(b,'ask_mem0',return_value=('',None)), patch.object(b,'ask_jev',return_value=('dummy-vercel','vercel')):
            b.optional_services(vault,self.root/'secrets')
        calls=[]
        def transport(url,body,key,timeout):
            calls.append((url,body['model'],key))
            return {'answers':{q:{'type':'score','score':1.8} for q in body['questions']}}
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'wrong-provider'},clear=True):
            result=jev_client.evaluate(vault,'q',[{'id':'one','title':'A','statement':'B','scope':'user','domains':['all']}],transport=transport)
        self.assertFalse(result['degraded'])
        self.assertEqual(calls,[('https://ai-gateway.vercel.sh/typesafe/v1/systemone','typesafe-ai/jev','dummy-vercel')])

    def test_source_traversal_and_untrusted_symlink_rejected(self):
        for i,name in enumerate(['repo/../../escape','repo/evil']):
            archive=self.root/f'bad{i}.zip'
            with zipfile.ZipFile(archive,'w') as z:
                item=zipfile.ZipInfo(name)
                if name.endswith('evil'):item.external_attr=(stat.S_IFLNK|0o777)<<16
                z.writestr(item,'/outside')
            with self.assertRaises(ValueError): b.extract_source(archive,self.root/f'out{i}')
        self.assertFalse((self.root/'escape').exists())

    def test_template_claude_link_materialized_as_safe_regular_file(self):
        archive=self.root/'link.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('repo/agents.md','instructions')
            z.writestr('repo/araclar/ajan_kur.py','')
            item=zipfile.ZipInfo('repo/CLAUDE.md');item.external_attr=(stat.S_IFLNK|0o777)<<16
            z.writestr(item,'agents.md')
        source=b.extract_source(archive,self.root/'out')
        self.assertFalse((source/'CLAUDE.md').is_symlink())
        self.assertEqual((source/'CLAUDE.md').read_text(),'instructions')

    def test_desktop_assets_ignore_mobile_only_latest_and_match_arch(self):
        def asset(name):return {'name':name,'browser_download_url':'https://github.com/obsidianmd/obsidian-releases/releases/download/v1/'+name,'digest':'sha256:'+'a'*64}
        releases=[{'assets':[asset('Obsidian.apk')]},{'assets':[asset('Obsidian-arm64.AppImage'),asset('Obsidian.AppImage'),asset('Obsidian.dmg'),asset('Obsidian.exe')]}]
        for system,machine,name in [('Linux','aarch64','Obsidian-arm64.AppImage'),('Linux','x86_64','Obsidian.AppImage'),('Darwin','arm64','Obsidian.dmg'),('Windows','AMD64','Obsidian.exe')]:
            self.assertEqual(b.asset_for(releases,system,machine)['name'],name)
        with self.assertRaises(ValueError):b.asset_for(releases,'Linux','riscv64')

    def test_download_failure_preserves_existing_file(self):
        target=self.root/'existing';target.write_text('keep')
        with self.assertRaises(ValueError):b.download('https://example.com/',target)
        self.assertEqual(target.read_text(),'keep')

    def test_config_directory_inside_vault_rejected(self):
        self.args.config_home=str(Path(self.args.vault)/'keys')
        with self.assertRaises(ValueError):self.install()
        self.assertFalse(Path(self.args.vault).exists())

    def test_noninteractive_requires_agent(self):
        self.args.agent=None
        with self.assertRaises(ValueError):self.install()

class ServiceTests(unittest.TestCase):
    """Service regressions use small local fixtures and fake carriers only."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.args = argparse.Namespace(agent='codex', vault=str(self.root / 'örnek kasa'),
            client_home=str(self.root / 'client'), config_home=str(self.root / 'secrets'),
            revision='a' * 40, non_interactive=True, skip_obsidian=True,
            configure_services=False, verify_services=False)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def _fixture_vault(self, name):
        vault = self.root / name
        (vault / 'araclar').mkdir(parents=True)
        (vault / 'agents.md').write_text('personal')
        (vault / 'araclar/hafiza.py').write_text('')
        return vault

    def test_configure_services_rejects_non_vault_target(self):
        target = self.root / 'not-a-vault'; target.mkdir()
        with self.assertRaisesRegex(ValueError, 'Geçerli bir Hafıza OS kasası'):
            b.configure_services(target, self.root / 'secrets')

    def test_configure_services_updates_only_provided_service(self):
        vault = self._fixture_vault('mevcut')
        report = vault / 'komuta/kurulum-sonucu.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'agent': 'codex', 'services': {'mem0': 'skipped', 'jev': 'configured_unverified'}}))
        with patch.object(b, 'ask_mem0', return_value=('dummy-mem0', 'tester')), patch.object(b, 'ask_jev', return_value=('', None)):
            b.configure_services(vault, self.root / 'secrets')
        updated = json.loads(report.read_text())
        self.assertEqual(updated['services']['mem0'], 'configured_unverified')
        self.assertEqual(updated['services']['jev'], 'configured_unverified')  # untouched, not downgraded
        self.assertEqual(updated['agent'], 'codex')  # unrelated fields preserved

    def test_configure_services_overwrites_existing_key(self):
        vault = self._fixture_vault('yeniden')
        config = self.root / 'secrets'
        with patch.object(b, 'ask_mem0', return_value=('eski-anahtar', 'tester')), patch.object(b, 'ask_jev', return_value=('', None)):
            b.configure_services(vault, config)
        with patch.object(b, 'ask_mem0', return_value=('yeni-anahtar', 'tester')), patch.object(b, 'ask_jev', return_value=('', None)):
            b.configure_services(vault, config)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(hafiza.load_api_key(vault), 'yeni-anahtar')

    def test_configure_services_skipping_both_makes_no_changes(self):
        vault = self._fixture_vault('degismez')
        with patch.object(b, 'ask_mem0', return_value=('', None)), patch.object(b, 'ask_jev', return_value=('', None)):
            b.configure_services(vault, self.root / 'secrets')
        self.assertFalse((vault / 'komuta/kurulum-sonucu.json').exists())
        self.assertFalse((vault / 'komuta/mem0.json').exists())

    def test_configure_services_via_run_skips_download_and_agent(self):
        self.args.configure_services = True
        self.args.non_interactive = False
        self.args.agent = None
        vault = Path(self.args.vault)
        (vault / 'araclar').mkdir(parents=True)
        (vault / 'agents.md').write_text('personal')
        (vault / 'araclar/hafiza.py').write_text('')
        with patch.object(b, 'ask_mem0', return_value=('dummy-mem0', 'tester')), patch.object(b, 'ask_jev', return_value=('', None)):
            with patch.object(b, 'download') as download, patch.object(b, 'get_json') as get_json, \
                 patch.object(b.sys.stdin, 'isatty', return_value=True):
                with contextlib.redirect_stdout(io.StringIO()):
                    b.run(self.args)
                download.assert_not_called(); get_json.assert_not_called()
        self.assertTrue((vault / 'komuta/mem0.json').exists())

    def test_configure_services_rejects_noninteractive(self):
        self.args.configure_services = True
        self.args.non_interactive = True
        with self.assertRaisesRegex(ValueError, 'configure-services'):
            b.run(self.args)

    def test_verify_services_rejects_non_vault_target(self):
        target = self.root / 'not-a-vault'; target.mkdir()
        with self.assertRaisesRegex(ValueError, 'Geçerli bir Hafıza OS kasası'):
            b.verify_services(target)

    def test_verify_services_reports_not_configured(self):
        vault = self._fixture_vault('bos')
        results = b.verify_services(vault)
        self.assertEqual(results, {'mem0': {'status': 'not_configured'}, 'jev': {'status': 'not_configured'}})

    def test_verify_mem0_reports_success_and_extracts_http_status_on_failure(self):
        vault = self._fixture_vault('mem0lu')
        with patch.object(b, 'ask_mem0', return_value=('dummy-mem0', 'tester')), patch.object(b, 'ask_jev', return_value=('', None)):
            b.configure_services(vault, self.root / 'secrets')

        class OkClient:
            def __init__(self, key, user_id=None): self.user_id = user_id
            def search_memories(self, *a, **k): return []
        with patch.object(hafiza, 'Mem0HttpClient', OkClient):
            self.assertEqual(b._mem0_verification(vault), {'status': 'verified', 'credential_source': 'file'})

        class FailingClient:
            def __init__(self, key, user_id=None): self.user_id = user_id
            def search_memories(self, *a, **k): raise RuntimeError('Mem0 HTTP 401: {"detail":"Invalid API key."}')
        with patch.object(hafiza, 'Mem0HttpClient', FailingClient):
            self.assertEqual(b._mem0_verification(vault)['status'], 'verification_failed:http_401')

    def test_verify_jev_reports_success_and_failure_without_leaking_key(self):
        vault = self._fixture_vault('jevli')
        with patch.object(b, 'ask_mem0', return_value=('', None)), patch.object(b, 'ask_jev', return_value=('dummy-jev-key', 'typesafe')):
            b.configure_services(vault, self.root / 'secrets')

        def ok_transport(url, body, key, timeout):
            self.assertNotIn('dummy-jev-key', json.dumps(body))
            return {'answers': {q: {'type': 'score', 'score': 1.0} for q in body['questions']}}
        with patch.object(jev_client, '_transport', side_effect=ok_transport):
            self.assertEqual(b._jev_verification(vault), {'status': 'verified', 'credential_source': 'file'})

        def failing_transport(url, body, key, timeout):
            raise self._http_error(url, 401)
        with patch.object(jev_client, '_transport', side_effect=failing_transport):
            result = b._jev_verification(vault)
        self.assertEqual(result['status'], 'verification_failed:http_unauthorized')
        self.assertNotIn('dummy-jev-key', json.dumps(result))

    def test_report_verification_updates_only_verified_services(self):
        vault = self._fixture_vault('rapor')
        report = vault / 'komuta/kurulum-sonucu.json'
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({'services': {'mem0': 'configured_unverified', 'jev': 'skipped'}}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            b.report_verification(vault, {'mem0': {'status': 'verified', 'credential_source': 'file'}, 'jev': {'status': 'not_configured'}})
        updated = json.loads(report.read_text())['services']
        self.assertEqual(updated['mem0'], 'verified')
        self.assertEqual(updated['jev'], 'not_configured')  # stale service state must not survive verification
        self.assertIn('canlı doğrulama başarılı', output.getvalue())

    def test_verify_services_flag_via_run_does_not_require_agent_or_download(self):
        self.args.verify_services = True
        self.args.agent = None
        vault = self._fixture_vault(Path(self.args.vault).name)
        with patch.object(b, 'download') as download, patch.object(b, 'get_json') as get_json:
            with contextlib.redirect_stdout(io.StringIO()):
                b.run(self.args)
            download.assert_not_called(); get_json.assert_not_called()

    def _write_json(self, path, value, mode=0o600):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        path.chmod(mode)
        return path

    def _managed_dir(self, vault, config_home=None):
        ident = hashlib.sha256(str(vault).encode()).hexdigest()[:16]
        return (config_home or self.root / 'secrets') / 'hafiza-os' / ident

    def _configured_vault(self, name='configured', *, jev_mode='shadow', retrieval_mode='off'):
        vault = self._fixture_vault(name)
        keys = self._managed_dir(vault)
        mem0_key = self._write_json(keys / 'mem0.json', {'MEM0_API_KEY': 'old-mem0'})
        jev_key = self._write_json(keys / 'jev.json', {'TYPESAFE_API_KEY': 'old-jev'})
        self._write_json(vault / 'komuta/mem0.json',
                         {'enabled': True, 'user_id': 'existing-user', 'credentials_file': str(mem0_key)}, 0o640)
        self._write_json(vault / 'komuta/jev.json',
                         {'mode': jev_mode, 'retrieval_mode': retrieval_mode, 'provider': 'typesafe',
                          'model': 'jev-latest', 'credentials_file': str(jev_key)}, 0o640)
        self._write_json(vault / 'komuta/kurulum-sonucu.json',
                         {'agent': 'codex', 'custom': {'preserve': [1, 'ı']},
                          'services': {'mem0': 'verified', 'jev': 'verified'}}, 0o640)
        return vault

    def _configure(self, vault, *, mem0='new-mem0', jev='new-jev', provider='typesafe'):
        with patch.object(b, 'ask_mem0', return_value=(mem0, 'existing-user')), \
             patch.object(b, 'ask_jev', return_value=(jev, provider)), \
             contextlib.redirect_stdout(io.StringIO()):
            return b.configure_services(vault, self.root / 'secrets')

    def _file_snapshot(self):
        return {str(path.relative_to(self.root)): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for path in self.root.rglob('*') if path.is_file() and not path.is_symlink()}

    @staticmethod
    def _ok_jev_transport(url, body, key, timeout):
        return {'answers': {question: {'type': 'score', 'score': 1.0} for question in body['questions']}}

    @staticmethod
    def _http_error(url, status, message='Unauthorized'):
        error = urllib.error.HTTPError(url, status, message, {}, None)
        error.close()
        return error

    def test_rotation_preserves_all_custom_jev_settings_and_existing_modes(self):
        custom = dict(jev_client.DEFAULTS, mode='shadow', retrieval_mode='assist', procedure_mode='shadow',
                      claude_hook_mode='off', task_mapping_mode='shadow', base_url='https://custom.invalid/jev',
                      model='jev-custom-model', rubric_version='custom-v2', timeout=4.75, cache_ttl=7200,
                      max_candidates=7, max_questions=21, max_input_chars=18000,
                      rerank_threshold=1.2, rerank_p2=0.4, rerank_gate_threshold=0.3,
                      rerank_gate_scope='all', rerank_limit=2, rerank_candidates=12, rerank_facets=False,
                      env_file=str(self.root / 'user.env'))
        for mode in ('off', 'shadow', 'on'):
            with self.subTest(mode=mode):
                vault = self._configured_vault('custom-' + mode)
                path = vault / 'komuta/jev.json'
                before = json.loads(path.read_text()) | custom | {'mode': mode}
                self._write_json(path, before)
                self._configure(vault, mem0='')
                after = json.loads(path.read_text())
                self.assertEqual({k: v for k, v in after.items() if k != 'credentials_file'},
                                 {k: v for k, v in before.items() if k != 'credentials_file'})
                self.assertEqual(json.loads(Path(after['credentials_file']).read_text()),
                                 {'TYPESAFE_API_KEY': 'new-jev'})

    def test_rotation_preserves_disabled_mem0_and_defaults_to_existing_user_id(self):
        vault = self._configured_vault()
        path = vault / 'komuta/mem0.json'
        original = json.loads(path.read_text()) | {'enabled': False}
        self._write_json(path, original)
        output = io.StringIO()
        with patch('builtins.input', side_effect=['1', '']) as ask, \
             patch.object(b, 'secret', return_value='new-mem0'), \
             patch.object(b, 'ask_jev', return_value=('', None)), contextlib.redirect_stdout(output):
            b.configure_services(vault, self.root / 'secrets')
        updated = json.loads(path.read_text())
        self.assertEqual(updated['user_id'], 'existing-user')
        self.assertFalse(updated['enabled'])
        self.assertIn('existing-user', ask.call_args_list[-1].args[0])

    def test_configure_new_jev_in_existing_vault_never_enables_on_mode(self):
        vault = self._fixture_vault('no-existing-config')
        self._configure(vault, mem0='')
        config = json.loads((vault / 'komuta/jev.json').read_text())
        self.assertNotEqual(config.get('mode'), 'on')
        self.assertFalse(any(value == 'on' for key, value in config.items() if key.endswith('_mode')))

    def test_rotation_preserves_missing_jev_settings_and_implicit_disabled_mode(self):
        vault = self._configured_vault()
        ref = vault / 'komuta/jev.json'
        self._write_json(ref, {'retrieval_mode': 'off'})
        self._configure(vault, mem0='')
        config = json.loads(ref.read_text())
        self.assertNotIn('mode', config)
        self.assertNotIn('model', config)
        self.assertNotIn('base_url', config)
        self.assertEqual(config['retrieval_mode'], 'off')
        self.assertEqual(b._jev_verification(vault)['status'], 'disabled')

    def test_existing_unicode_mem0_user_id_is_accepted_on_enter(self):
        vault = self._configured_vault()
        ref = vault / 'komuta/mem0.json'
        original = json.loads(ref.read_text()) | {'user_id': 'kullanıcı@example.com'}
        self._write_json(ref, original)
        with patch('builtins.input', side_effect=['1', '']), \
             patch.object(b, 'secret', return_value='new-mem0'), \
             patch.object(b, 'ask_jev', return_value=('', None)), contextlib.redirect_stdout(io.StringIO()):
            b.configure_services(vault, self.root / 'secrets')
        self.assertEqual(json.loads(ref.read_text())['user_id'], 'kullanıcı@example.com')

    def test_every_private_json_stage_failure_preserves_old_files_and_modes(self):
        self._assert_each_transaction_stage_rolls_back('private_json')

    def test_every_replace_stage_failure_preserves_old_files_and_modes(self):
        self._assert_each_transaction_stage_rolls_back('replace')

    def test_every_backup_fsync_failure_preserves_old_files_and_modes(self):
        vault = self._configured_vault('baseline-fsync')
        original = os.fsync
        with patch.object(b.os, 'fsync', wraps=original) as wrapped:
            self._configure(vault)
        self.assertGreaterEqual(wrapped.call_count, 3)
        for ordinal in range(1, wrapped.call_count + 1):
            with self.subTest(ordinal=ordinal):
                vault = self._configured_vault('fsync-' + str(ordinal))
                before = self._file_snapshot()
                calls = 0
                def injected(fd):
                    nonlocal calls
                    calls += 1
                    if calls == ordinal:
                        raise OSError('simulated backup flush failure')
                    return original(fd)
                with patch.object(b.os, 'fsync', side_effect=injected):
                    with self.assertRaises(OSError):
                        self._configure(vault)
                self.assertEqual(self._file_snapshot(), before)

    def _assert_each_transaction_stage_rolls_back(self, operation):
        owner = b if operation == 'private_json' else b.os
        original = getattr(owner, operation)
        vault = self._configured_vault('baseline-' + operation)
        with patch.object(owner, operation, wraps=original) as wrapped:
            self._configure(vault)
        count = wrapped.call_count
        self.assertGreaterEqual(count, 5, 'both credential files, both references and report must be staged/replaced')
        for ordinal in range(1, count + 1):
            for after_partial_write in (False, True):
                with self.subTest(operation=operation, ordinal=ordinal, partial=after_partial_write):
                    vault = self._configured_vault(f'{operation}-{ordinal}-{after_partial_write}')
                    before = self._file_snapshot()
                    calls = 0
                    def injected(*args, **kwargs):
                        nonlocal calls
                        calls += 1
                        if calls == ordinal:
                            if after_partial_write:
                                original(*args, **kwargs)
                            raise OSError('simulated disk failure')
                        return original(*args, **kwargs)
                    with patch.object(owner, operation, side_effect=injected):
                        with self.assertRaises((OSError, ValueError, RuntimeError)) as raised:
                            self._configure(vault)
                    self.assertEqual(self._file_snapshot(), before)
                    self.assertNotIn('new-mem0', str(raised.exception))
                    self.assertNotIn('new-jev', str(raised.exception))

    def test_failed_rollback_retains_original_backups_and_reports_recovery_needed(self):
        vault = self._configured_vault()
        ref = vault / 'komuta/jev.json'
        original_bytes = ref.read_bytes()
        old_key = Path(json.loads(original_bytes)['credentials_file'])
        original_replace = os.replace
        def disk_failure(source, destination):
            if Path(destination).name == 'kurulum-sonucu.json' or '.backup-' in Path(source).name:
                raise OSError('simulated commit and rollback failure')
            return original_replace(source, destination)
        with patch.object(b.os, 'replace', side_effect=disk_failure):
            with self.assertRaisesRegex(ValueError, 'geri alma tamamlanamadı') as error:
                self._configure(vault)
        self.assertTrue(old_key.exists())
        self.assertTrue(any(path.read_bytes() == original_bytes for path in ref.parent.glob('*.backup-*')))
        self.assertNotIn('new-jev', str(error.exception))
        self.assertNotIn('new-mem0', str(error.exception))

    def test_credential_reference_and_report_are_replaced_from_same_directory(self):
        vault = self._configured_vault()
        old = [Path(json.loads((vault / f'komuta/{service}.json').read_text())['credentials_file'])
               for service in ('mem0', 'jev')]
        original_replace = os.replace
        destinations = []
        def observe(source, destination):
            source, destination = Path(source), Path(destination)
            self.assertEqual(source.parent, destination.parent)
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)
            # Old credentials cannot be deleted until every replacement has committed.
            self.assertTrue(all(path.exists() for path in old))
            destinations.append(destination)
            return original_replace(source, destination)
        with patch.object(b.os, 'replace', side_effect=observe):
            self._configure(vault)
        self.assertTrue({vault / 'komuta/mem0.json', vault / 'komuta/jev.json',
                         vault / 'komuta/kurulum-sonucu.json'}.issubset(destinations))
        self.assertEqual(sum(path.parent == self._managed_dir(vault) for path in destinations), 2)
        self.assertTrue(all(not path.exists() for path in old))

    def test_invalid_existing_report_fails_before_any_write_or_delete(self):
        for content in ('{broken', '[]', '{"services": []}'):
            with self.subTest(content=content):
                vault = self._configured_vault('report-' + str(len(content)))
                (vault / 'komuta/kurulum-sonucu.json').write_text(content)
                before = self._file_snapshot()
                with patch.object(b, 'private_json') as write, patch.object(b.os, 'replace') as replace, \
                     patch.object(Path, 'unlink') as unlink:
                    with self.assertRaises((ValueError, OSError)):
                        self._configure(vault)
                    write.assert_not_called(); replace.assert_not_called(); unlink.assert_not_called()
                self.assertEqual(self._file_snapshot(), before)

    def test_invalid_existing_service_config_fails_before_other_service_write(self):
        invalid = [('mem0', '{broken'), ('jev', '{broken'),
                   ('mem0', '{"enabled": "yes", "user_id": "tester"}'), ('jev', '{"mode": "banana"}')]
        for index, (service, content) in enumerate(invalid):
            with self.subTest(service=service, content=content):
                vault = self._configured_vault('invalid-' + str(index))
                (vault / f'komuta/{service}.json').write_text(content)
                before = self._file_snapshot()
                with patch.object(b, 'private_json') as write:
                    with self.assertRaises((ValueError, OSError)):
                        self._configure(vault)
                    write.assert_not_called()
                self.assertEqual(self._file_snapshot(), before)

    def test_old_managed_credentials_removed_only_after_success_unmanaged_retained(self):
        for managed in (True, False):
            with self.subTest(managed=managed):
                vault = self._configured_vault('old-location-' + str(managed))
                old_path = (self.root / 'secrets/hafiza-os/0123456789abcdef/legacy.json' if managed
                            else self.root / 'user-managed/legacy.json')
                self._write_json(old_path, {'TYPESAFE_API_KEY': 'old-other-key'})
                ref_path = vault / 'komuta/jev.json'
                self._write_json(ref_path, json.loads(ref_path.read_text()) | {'credentials_file': str(old_path)})
                self._configure(vault, mem0='')
                self.assertEqual(old_path.exists(), not managed)
                if not managed:
                    self.assertEqual(json.loads(old_path.read_text()), {'TYPESAFE_API_KEY': 'old-other-key'})

    def test_postcommit_cleanup_failure_keeps_new_settings_and_reports_truthfully(self):
        vault = self._configured_vault()
        ref = vault / 'komuta/jev.json'
        old = Path(json.loads(ref.read_text())['credentials_file'])
        original_unlink = Path.unlink
        def blocked_cleanup(path, *args, **kwargs):
            if path == old:
                raise PermissionError('old credential cannot be removed')
            return original_unlink(path, *args, **kwargs)
        output = io.StringIO()
        with patch.object(Path, 'unlink', blocked_cleanup), contextlib.redirect_stderr(output):
            self._configure(vault, mem0='')
        self.assertTrue(old.exists())
        self.assertEqual(json.loads(Path(json.loads(ref.read_text())['credentials_file']).read_text()),
                         {'TYPESAFE_API_KEY': 'new-jev'})
        self.assertEqual(json.loads((vault / 'komuta/kurulum-sonucu.json').read_text())['services']['jev'],
                         'configured_unverified')
        self.assertIn('güncellendi', output.getvalue())
        self.assertIn('temizlenemedi', output.getvalue())
        self.assertNotIn('new-jev', output.getvalue())

    def test_symlink_preflight_prevents_all_writes_and_deletes(self):
        for component in ('komuta', 'credential_dir', 'credential_file', 'reference', 'report', 'config_home'):
            with self.subTest(component=component):
                vault = self._configured_vault('link-' + component)
                keys = self._managed_dir(vault)
                target = {'komuta': vault / 'komuta', 'credential_dir': keys,
                          'credential_file': keys / 'jev.json', 'reference': vault / 'komuta/jev.json',
                          'report': vault / 'komuta/kurulum-sonucu.json', 'config_home': self.root / 'secrets'}[component]
                outside = self.root / ('outside-' + component)
                target.rename(outside)
                try:
                    target.symlink_to(outside, target_is_directory=outside.is_dir())
                except OSError:
                    outside.rename(target)
                    self.skipTest('symlink creation is unavailable on this platform')
                before = self._file_snapshot()
                try:
                    with patch.object(b, 'private_json') as write, patch.object(b.os, 'replace') as replace, \
                         patch.object(Path, 'unlink') as unlink:
                        with self.assertRaises((ValueError, OSError)):
                            self._configure(vault)
                        write.assert_not_called(); replace.assert_not_called(); unlink.assert_not_called()
                    self.assertEqual(self._file_snapshot(), before)
                finally:
                    target.unlink()
                    outside.rename(target)

    def test_cached_success_cannot_verify_rotated_bad_key_and_carrier_is_called(self):
        vault = self._configured_vault(jev_mode='on', retrieval_mode='inherit')
        probe = [{'id': 'verify', 'title': 'verify', 'statement': 'Hafiza OS service verification probe.',
                  'scope': 'user', 'domains': []}]
        observed = []
        def carrier(url, body, key, timeout):
            observed.append(key)
            if key == 'bad-new-key':
                raise self._http_error(url, 401)
            return self._ok_jev_transport(url, body, key, timeout)
        with patch.object(jev_client, '_transport', side_effect=carrier):
            cached = jev_client.evaluate(vault, 'hafiza-os configure-services verify', probe)
            self.assertFalse(cached['degraded']); self.assertFalse(cached['cache_hit'])
            self.assertTrue(list((vault / '.cache/jev').glob('*.json')))
            self._configure(vault, mem0='', jev='bad-new-key')
            still_cached = jev_client.evaluate(vault, 'hafiza-os configure-services verify', probe)
            self.assertTrue(still_cached['cache_hit'])
            result = b._jev_verification(vault)
        self.assertEqual(observed, ['old-jev', 'bad-new-key'])
        self.assertEqual(result['status'], 'verification_failed:http_unauthorized')

    def test_shadow_and_assist_retrieval_modes_make_real_calls_without_cache(self):
        for mode, retrieval in [('shadow', 'off'), ('on', 'off'), ('on', 'assist'), ('shadow', 'assist')]:
            with self.subTest(mode=mode, retrieval=retrieval):
                vault = self._configured_vault(mode + '-' + retrieval, jev_mode=mode, retrieval_mode=retrieval)
                before = self._file_snapshot()
                with patch.object(jev_client, '_transport', side_effect=self._ok_jev_transport) as carrier, \
                     patch.object(jev_client, '_cache_path', side_effect=AssertionError('verification must not use cache')):
                    result = b._jev_verification(vault)
                self.assertEqual(result['status'], 'verified')
                carrier.assert_called_once()
                self.assertEqual(carrier.call_args.args[2], 'old-jev')
                self.assertEqual(self._file_snapshot(), before)

    def test_disabled_services_are_distinct_and_make_no_carrier_calls(self):
        vault = self._configured_vault(jev_mode='off')
        mem0 = vault / 'komuta/mem0.json'
        self._write_json(mem0, json.loads(mem0.read_text()) | {'enabled': False})
        with patch.object(hafiza, 'Mem0HttpClient') as mem0_carrier, \
             patch.object(jev_client, '_transport') as jev_carrier:
            result = b.verify_services(vault)
        self.assertEqual(result['mem0']['status'], 'disabled')
        self.assertEqual(result['jev']['status'], 'disabled')
        mem0_carrier.assert_not_called(); jev_carrier.assert_not_called()

    def test_broken_mem0_config_does_not_prevent_jev_verification(self):
        for content in ('{broken', '[]', '{"enabled": "yes", "user_id": "test"}'):
            with self.subTest(content=content):
                vault = self._configured_vault('broken-mem0-' + str(len(content)))
                (vault / 'komuta/mem0.json').write_text(content)
                with patch.object(jev_client, '_transport', side_effect=self._ok_jev_transport) as carrier:
                    result = b.verify_services(vault)
                self.assertEqual(result['mem0']['status'], 'config_invalid')
                self.assertEqual(result['jev']['status'], 'verified')
                carrier.assert_called_once()

    def test_invalid_and_missing_configs_replace_stale_verified_report(self):
        vault = self._configured_vault()
        (vault / 'komuta/mem0.json').unlink()
        (vault / 'komuta/jev.json').write_text('{broken')
        with contextlib.redirect_stdout(io.StringIO()):
            b.report_verification(vault, b.verify_services(vault))
        report = json.loads((vault / 'komuta/kurulum-sonucu.json').read_text())
        self.assertEqual(report['services'], {'mem0': 'not_configured', 'jev': 'config_invalid'})
        self.assertEqual(report['custom'], {'preserve': [1, 'ı']})

    def test_configure_then_verify_uses_new_files_for_all_providers(self):
        for provider, variable in [('typesafe', 'TYPESAFE_API_KEY'), ('vercel', 'AI_GATEWAY_API_KEY')]:
            with self.subTest(provider=provider):
                vault = self._configured_vault('new-file-' + provider)
                self.args.vault = str(vault)
                self.args.configure_services = self.args.verify_services = True
                self.args.non_interactive = False
                observed = []
                class Mem0Client:
                    def __init__(self, key, user_id=None):
                        self.user_id = user_id; observed.append(('mem0', key))
                    def search_memories(self, *args, **kwargs): return []
                def jev_carrier(url, body, key, timeout):
                    observed.append(('jev', key))
                    return self._ok_jev_transport(url, body, key, timeout)
                output = io.StringIO()
                with patch.dict(os.environ, {'MEM0_API_KEY': 'stale-env-mem0', variable: 'stale-env-jev'}), \
                     patch.object(b, 'ask_mem0', return_value=('new-file-mem0', 'existing-user')), \
                     patch.object(b, 'ask_jev', return_value=('new-file-jev', provider)), \
                     patch.object(b.sys.stdin, 'isatty', return_value=True), \
                     patch.object(hafiza, 'Mem0HttpClient', Mem0Client), \
                     patch.object(jev_client, '_transport', side_effect=jev_carrier), contextlib.redirect_stdout(output):
                    b.run(self.args)
                self.assertEqual(observed, [('mem0', 'new-file-mem0'), ('jev', 'new-file-jev')])
                for secret in ('stale-env-mem0', 'stale-env-jev', 'new-file-mem0', 'new-file-jev'):
                    self.assertNotIn(secret, output.getvalue())
                    self.assertNotIn(secret, (vault / 'komuta/kurulum-sonucu.json').read_text())

    def test_standalone_verify_reports_file_and_environment_sources_without_secrets(self):
        for use_environment in (False, True):
            with self.subTest(use_environment=use_environment):
                vault = self._configured_vault('source-' + str(use_environment))
                observed = []
                class Mem0Client:
                    def __init__(self, key, user_id=None):
                        self.user_id = user_id; observed.append(key)
                    def search_memories(self, *args, **kwargs): return []
                def carrier(url, body, key, timeout):
                    observed.append(key)
                    return self._ok_jev_transport(url, body, key, timeout)
                values = {'MEM0_API_KEY': 'env-mem0-secret', 'TYPESAFE_API_KEY': 'env-jev-secret'} if use_environment else {}
                output = io.StringIO()
                with patch.dict(os.environ, values, clear=True), patch.object(hafiza, 'Mem0HttpClient', Mem0Client), \
                     patch.object(jev_client, '_transport', side_effect=carrier), contextlib.redirect_stdout(output):
                    result = b.verify_services(vault)
                    b.report_verification(vault, result)
                source = 'environment' if use_environment else 'file'
                self.assertEqual([result[s]['credential_source'] for s in ('mem0', 'jev')], [source, source])
                self.assertEqual(observed, ['env-mem0-secret', 'env-jev-secret'] if use_environment else ['old-mem0', 'old-jev'])
                self.assertIn('ortam' if use_environment else 'dosya', output.getvalue().lower())
                for secret in observed:
                    self.assertNotIn(secret, json.dumps(result) + output.getvalue() +
                                     (vault / 'komuta/kurulum-sonucu.json').read_text())

    def test_actual_jev_failure_code_is_not_an_informational_cache_diagnostic(self):
        vault = self._configured_vault()
        # Legacy evaluate would add cache_unavailable before its actual HTTP error.
        cache = vault / '.cache'; cache.mkdir(); (cache / 'jev').write_text('blocked-cache-directory')
        def fail(url, body, key, timeout):
            raise self._http_error(url, 429, 'credential value must never be echoed: ' + key)
        with patch.object(jev_client, '_transport', side_effect=fail) as carrier:
            result = b._jev_verification(vault)
        carrier.assert_called_once()
        self.assertEqual(result['status'], 'verification_failed:http_rate_limited')
        self.assertNotIn('cache_unavailable', json.dumps(result))
        self.assertNotIn('quantized_probability', json.dumps(result))
        self.assertNotIn('old-jev', json.dumps(result))

    def test_standalone_jev_source_tracks_actual_key_in_env_file(self):
        for includes_key in (False, True):
            with self.subTest(includes_key=includes_key):
                vault = self._configured_vault('env-file-' + str(includes_key))
                env_file = self.root / ('key-' + str(includes_key) + '.env')
                env_file.write_text('TYPESAFE_BASE_URL=https://api.typesafe.ai\n' +
                                    ('TYPESAFE_API_KEY=dotenv-key\n' if includes_key else ''))
                ref = vault / 'komuta/jev.json'
                self._write_json(ref, json.loads(ref.read_text()) | {'env_file': str(env_file)})
                with patch.object(jev_client, '_transport', side_effect=self._ok_jev_transport) as carrier:
                    result = b._jev_verification(vault)
                self.assertEqual(result['status'], 'verified')
                self.assertEqual(result['credential_source'], 'env_file' if includes_key else 'file')
                self.assertEqual(carrier.call_args.args[2], 'dotenv-key' if includes_key else 'old-jev')

    def test_vercel_provider_with_legacy_env_file_key_matches_runtime_client(self):
        # Runtime evaluate() accepts TYPESAFE_API_KEY from env_file for provider=vercel;
        # verification must resolve the same key and base URL instead of reporting it missing.
        vault = self._fixture_vault('vercel-env-file')
        env_file = self.root / 'gateway.env'
        env_file.write_text('TYPESAFE_API_KEY=gateway-key\nTYPESAFE_BASE_URL=http://127.0.0.1:18760\n')
        self._write_json(vault / 'komuta/jev.json',
                         {'mode': 'shadow', 'retrieval_mode': 'assist', 'provider': 'vercel',
                          'model': 'jev-latest', 'base_url': 'http://127.0.0.1:18760', 'env_file': str(env_file)}, 0o640)
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(jev_client, '_transport', side_effect=self._ok_jev_transport) as carrier:
            result = b._jev_verification(vault)
        self.assertEqual(result['status'], 'verified')
        self.assertEqual(result['credential_source'], 'env_file')
        self.assertEqual(carrier.call_args.args[0], 'http://127.0.0.1:18760/v1/systemone')
        self.assertEqual(carrier.call_args.args[2], 'gateway-key')
        self.assertNotIn('gateway-key', json.dumps(result))

    def test_cached_evaluation_context_does_not_hide_new_jev_configuration(self):
        vault = self._configured_vault(jev_mode='off')
        with jev_client.evaluation_context(vault), jev_client.disabled():
            ref = vault / 'komuta/jev.json'
            self._write_json(ref, json.loads(ref.read_text()) | {'mode': 'shadow'})
            with patch.object(jev_client, '_transport', side_effect=self._ok_jev_transport) as carrier:
                result = b._jev_verification(vault)
        self.assertEqual(result['status'], 'verified')
        carrier.assert_called_once()

    def test_client_loader_prefers_bundled_code_and_supports_standalone_installer(self):
        for bundled in (False, True):
            with self.subTest(bundled=bundled):
                vault = self._fixture_vault('loader-' + str(bundled))
                installer = self.root / ('installer-' + str(bundled))
                installer.mkdir()
                for name in ('hafiza.py', 'jev_client.py'):
                    (vault / 'araclar' / name).write_text("ORIGIN = 'selected-vault'\n")
                if bundled:
                    (installer / 'araclar').mkdir()
                    for name in ('hafiza.py', 'jev_client.py'):
                        (installer / 'araclar' / name).write_text("ORIGIN = 'bundled'\n")
                with patch.object(b, '__file__', str(installer / 'baslat.py')), \
                     patch.object(b.sys, 'path', list(b.sys.path)), patch.dict(b.sys.modules):
                    # Cached test imports must not conceal the standalone import path.
                    b.sys.modules.pop('hafiza', None)
                    b.sys.modules.pop('jev_client', None)
                    clients = b._service_clients(vault)
                    expected = installer / 'araclar' if bundled else vault / 'araclar'
                    self.assertTrue(all(Path(client.__file__).parent == expected for client in clients))
                    self.assertEqual([client.ORIGIN for client in clients],
                                     ['bundled', 'bundled'] if bundled else ['selected-vault', 'selected-vault'])

    def test_invalid_jev_response_is_not_verified_after_carrier_completes(self):
        vault = self._configured_vault()
        with patch.object(jev_client, '_transport', return_value={'answers': {}}) as carrier:
            result = b._jev_verification(vault)
        carrier.assert_called_once()
        self.assertEqual(result['status'], 'verification_failed:answers_invalid')

    def test_missing_service_config_does_not_import_vault_code(self):
        vault = self._fixture_vault('missing-configs')
        with patch.object(b, '_service_clients', side_effect=AssertionError('no client needed')) as clients:
            result = b.verify_services(vault)
        self.assertEqual(result, {'mem0': {'status': 'not_configured'},
                                  'jev': {'status': 'not_configured'}})
        clients.assert_not_called()

    def test_mem0_verification_preserves_existing_inside_vault_credential_rejection(self):
        vault = self._configured_vault()
        credential = self._write_json(vault / 'key.json', {'MEM0_API_KEY': 'local-key'})
        ref = vault / 'komuta/mem0.json'
        self._write_json(ref, json.loads(ref.read_text()) | {'credentials_file': str(credential)})
        for prefer_file in (False, True):
            with self.subTest(prefer_file=prefer_file), patch.object(hafiza, 'Mem0HttpClient') as carrier:
                result = b._mem0_verification(vault, prefer_file=prefer_file)
            self.assertEqual(result, {'status': 'verification_failed:env_file_invalid',
                                      'credential_source': 'file'})
            carrier.assert_not_called()


class SecurityRegressionTests(unittest.TestCase):
    """Kol güvenlik: sentetik yollar, sahte taşıyıcılar; ağ veya gerçek anahtar yok."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def _vault(self, path):
        (path / 'araclar').mkdir(parents=True)
        (path / 'agents.md').write_text('personal')
        (path / 'araclar/hafiza.py').write_text('')
        return path

    def _args(self, vault, config_home, **kw):
        return argparse.Namespace(**dict(dict(
            agent='codex', vault=str(vault), client_home=str(self.root / 'client'),
            config_home=str(config_home), revision='a' * 40, non_interactive=True, skip_obsidian=True,
            configure_services=False, verify_services=False), **kw))

    # 1. Hesaplanan anahtar dizini kasanın içine düşmemeli.
    def test_computed_credential_dir_inside_vault_rejected_on_first_install(self):
        vault = self.root / 'x' / 'hafiza-os'  # config_home/hafiza-os/<hash> == vault/<hash>
        with patch.object(b, 'download', side_effect=AssertionError('no network')), \
             patch.object(b, 'get_json', side_effect=AssertionError('no network')), \
             self.assertRaisesRegex(ValueError, 'kasasının dışında'):
            b.run(self._args(vault, self.root / 'x'))
        self.assertFalse(vault.exists())

    def test_computed_credential_dir_inside_vault_rejected_on_configure_services(self):
        vault = self._vault(self.root / 'x' / 'hafiza-os')
        before = sorted(str(p) for p in self.root.rglob('*'))
        args = self._args(vault, self.root / 'x', non_interactive=False, configure_services=True)
        with patch.object(b, 'ask_mem0', side_effect=AssertionError('asked before path check')), \
             patch.object(b, 'ask_jev', side_effect=AssertionError('asked before path check')), \
             patch.object(b.sys.stdin, 'isatty', return_value=True), \
             self.assertRaisesRegex(ValueError, 'kasasının dışında'):
            b.run(args)
        # optional_services itself (configure_services entry) also refuses before prompting.
        with patch.object(b, 'ask_mem0', side_effect=AssertionError('asked')), \
             self.assertRaisesRegex(ValueError, 'kasasının dışında'):
            b.configure_services(vault, self.root / 'x')
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*')), before)

    def test_credential_target_checked_after_resolution(self):
        vault = self._vault(self.root / 'kasa')
        with self.assertRaises(ValueError):
            b._outside_vault(vault / 'a' / '..' / 'b' / 'mem0.json', vault)
        with self.assertRaises(ValueError):
            b._outside_vault(vault, vault)
        outside = self.root / 'secrets' / 'hafiza-os' / 'x' / 'mem0.json'
        self.assertEqual(b._outside_vault(outside, vault), outside)
        # Legitimate separate config home keeps working.
        self.assertFalse(b._credential_dir(vault, self.root / 'secrets').is_relative_to(vault))

    # 3. Sağlayıcı değişince eski sağlayıcının resmi host'u yeni anahtarı almamalı.
    def test_provider_switch_moves_only_default_endpoint_and_keeps_local_gateway(self):
        for old, expected in (({}, ('https://ai-gateway.vercel.sh/typesafe', 'typesafe-ai/jev')),
                              ({'base_url': 'http://127.0.0.1:18760', 'model': 'jev-latest'},
                               ('http://127.0.0.1:18760', 'typesafe-ai/jev')),
                              ({'base_url': 'http://127.0.0.1:18760', 'model': 'benim-modelim'},
                               ('http://127.0.0.1:18760', 'benim-modelim'))):
            with self.subTest(old=old):
                vault = self._vault(self.root / ('switch-' + str(len(list(self.root.iterdir())))))
                ref = vault / 'komuta/jev.json'; ref.parent.mkdir()
                ref.write_text(json.dumps(dict({'mode': 'shadow', 'provider': 'typesafe'}, **old)))
                with patch.object(b, 'ask_mem0', return_value=('', 'ben')), \
                     patch.object(b, 'ask_jev', return_value=('new-gateway-key', 'vercel')), \
                     contextlib.redirect_stdout(io.StringIO()):
                    b.configure_services(vault, self.root / 'secrets')
                config = json.loads(ref.read_text())
                self.assertEqual((config['base_url'], config['model'], config['provider']), expected + ('vercel',))
                jev_client._resolve_endpoint(jev_client._read_config(vault), {})

    def test_verification_never_sends_key_to_unbound_remote_host(self):
        for extra, env in (({'base_url': 'https://evil.example/jev'}, None),
                           ({'provider': 'vercel', 'base_url': 'https://api.typesafe.ai'}, None),
                           ({'base_url': 'http://ai-gateway.example'}, None),
                           ({}, 'TYPESAFE_BASE_URL=https://evil.example\nTYPESAFE_API_KEY=file-key\n')):
            with self.subTest(extra=extra, env=bool(env)):
                vault = self._vault(self.root / ('bound-' + str(len(list(self.root.iterdir())))))
                config = dict({'mode': 'shadow', 'provider': 'typesafe'}, **extra)
                if env:
                    env_file = self.root / (vault.name + '.env'); env_file.write_text(env)
                    config['env_file'] = str(env_file)
                (vault / 'komuta').mkdir(); (vault / 'komuta/jev.json').write_text(json.dumps(config))
                os.environ['TYPESAFE_API_KEY'] = os.environ['AI_GATEWAY_API_KEY'] = 'env-key'
                with patch.object(jev_client, '_transport', side_effect=AssertionError('key sent')) as carrier:
                    result = b._jev_verification(vault)
                carrier.assert_not_called()
                self.assertEqual(result['status'], 'verification_failed:endpoint_invalid')

    def test_verification_allows_explicit_custom_https_endpoint(self):
        vault = self._vault(self.root / 'custom')
        (vault / 'komuta').mkdir()
        (vault / 'komuta/jev.json').write_text(json.dumps(
            {'mode': 'shadow', 'provider': 'typesafe', 'base_url': 'https://jev.example/v1', 'allow_custom_endpoint': True}))
        os.environ['TYPESAFE_API_KEY'] = 'env-key'
        ok = lambda url, body, key, timeout: {'answers': {q: {'type': 'score', 'score': 1.0} for q in body['questions']}}
        with patch.object(jev_client, '_transport', side_effect=ok) as carrier:
            self.assertEqual(b._jev_verification(vault)['status'], 'verified')
        self.assertEqual(carrier.call_args.args[0], 'https://jev.example/v1/systemone')

    def test_verification_fails_closed_with_old_unbound_client(self):
        vault = self._vault(self.root / 'old-client')
        (vault / 'komuta').mkdir()
        (vault / 'komuta/jev.json').write_text(json.dumps({'mode': 'shadow', 'provider': 'typesafe'}))
        os.environ['TYPESAFE_API_KEY'] = 'env-key'
        old = type('OldClient', (), {name: staticmethod(getattr(jev_client, name))
                                     for name in ('_read_config', '_environment', '_scores', '_transport')})
        old._endpoint = staticmethod(lambda base: base + '/v1/systemone')
        with patch.object(b, '_service_clients', return_value=(hafiza, old)), \
             patch.object(old, '_transport', side_effect=AssertionError('key sent')):
            self.assertEqual(b._jev_verification(vault)['status'], 'verification_failed:endpoint_invalid')

    # 4. private_json: önce ACL, sonra içerik; her hata yolunda dosya kalmaz.
    def test_private_json_restricts_windows_acl_before_any_content(self):
        target = self.root / 'keys' / 'jev.json'
        seen = []
        def restrict(path):
            seen.append((path, path.stat().st_size))
        with patch.object(b, '_is_windows', return_value=True), \
             patch.object(b, '_restrict_windows_acl', side_effect=restrict):
            b.private_json(target, {'TYPESAFE_API_KEY': 'synthetic-secret'})
        self.assertEqual(seen, [(target, 0)])
        self.assertEqual(json.loads(target.read_text(encoding='utf-8')), {'TYPESAFE_API_KEY': 'synthetic-secret'})

    def test_private_json_windows_acl_failures_leave_no_file(self):
        failures = {
            'whoami_missing': dict(check_output=FileNotFoundError('whoami')),
            'whoami_failed': dict(check_output=b.subprocess.CalledProcessError(1, 'whoami')),
            'whoami_empty': dict(check_output=''),
            'icacls_missing': dict(check_output='host\\user', run=FileNotFoundError('icacls')),
            'icacls_failed': dict(check_output='host\\user', run=b.subprocess.CompletedProcess([], 5)),
        }
        for name, behaviour in failures.items():
            with self.subTest(name):
                target = self.root / 'acl' / (name + '.json')
                def output(*args, **kwargs):
                    value = behaviour['check_output']
                    if isinstance(value, BaseException): raise value
                    return value
                def run(*args, **kwargs):
                    value = behaviour.get('run', b.subprocess.CompletedProcess([], 0))
                    if isinstance(value, BaseException): raise value
                    return value
                with patch.object(b, '_is_windows', return_value=True), \
                     patch.object(b.subprocess, 'check_output', side_effect=output), \
                     patch.object(b.subprocess, 'run', side_effect=run), \
                     self.assertRaisesRegex(ValueError, 'Windows erişimi sınırlandırılamadı'):
                    b.private_json(target, {'MEM0_API_KEY': 'synthetic-secret'})
                self.assertFalse(target.exists())

    def test_private_json_icacls_grants_only_current_identity(self):
        target = self.root / 'acl-ok.json'
        with patch.object(b, '_is_windows', return_value=True), \
             patch.object(b.subprocess, 'check_output', return_value='host\\user\r\n'), \
             patch.object(b.subprocess, 'run', return_value=b.subprocess.CompletedProcess([], 0)) as run:
            b.private_json(target, {'k': 'v'})
        self.assertEqual(run.call_args.args[0], ['icacls', str(target), '/inheritance:r', '/grant:r', 'host\\user:F'])

    def test_private_json_write_or_serialization_failure_leaves_no_file(self):
        target = self.root / 'fail' / 'secret.json'
        with patch.object(b.os, 'fsync', side_effect=OSError('disk')), self.assertRaises(OSError):
            b.private_json(target, {'MEM0_API_KEY': 'synthetic-secret'})
        self.assertFalse(target.exists())
        with self.assertRaises(TypeError):
            b.private_json(target, {'bad': object()})
        self.assertFalse(target.exists())

    @unittest.skipIf(os.name != 'nt', 'Windows ACL yalnız Windows üzerinde doğrulanır')
    def test_private_json_real_windows_acl(self):
        target = self.root / 'win' / 'secret.json'
        b.private_json(target, {'k': 'v'})
        identity = b.subprocess.check_output(['whoami'], text=True).strip()
        acl = b.subprocess.run(['icacls', str(target)], capture_output=True, text=True).stdout
        self.assertIn(identity.lower(), acl.lower())
        self.assertNotIn('(I)', acl)  # inheritance removed
        self.assertEqual(json.loads(target.read_text()), {'k': 'v'})


if __name__=='__main__':unittest.main()
