import argparse
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
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
            non_interactive=True, skip_obsidian=True)
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
                target = Path(self.args.client_home) / rel
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text('Keep my instructions\n')
                with patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'wrong')}): self.install()
                self.assertIn('Keep my instructions', target.read_text())
                self.assertIn(self.args.vault, target.read_text())
                self.assertFalse((self.root/'wrong').exists())
                self.assertFalse((Path(self.args.vault)/'komuta/mem0.json').exists())

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
        with patch.object(b,'secret',side_effect=['dummy-mem0','dummy-jev']), patch('builtins.input',return_value='tester'):
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
            with patch.object(b,'secret',side_effect=keys),patch('builtins.input',return_value='tester'):
                b.optional_services(vault,self.root/'secrets')
            self.assertEqual((vault/'komuta/mem0.json').exists(),bool(keys[0]))
            self.assertEqual((vault/'komuta/jev.json').exists(),bool(keys[1]))

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

if __name__=='__main__':unittest.main()
