"""Isolated native installer contracts; never change the real home."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ajan_kur
import agent_hooks


class Hooks(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.vault = self.root / 'Türkçe vault'
        self.home = self.root / 'home'
        for name in ajan_kur.REQUIRED + ('araclar/client_hafiza.py',):
            path = self.vault / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('import json,sys\njson.load(sys.stdin)\nprint("{}")\n', encoding='utf-8')
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.home / '.codex')})
        self.env.start(); self.addCleanup(self.env.stop)

    def install(self, **kw):
        return ajan_kur.install(self.vault, 'all', self.home, with_hooks=True, hook_shell='cmd' if os.name == 'nt' else 'posix', **kw)

    def snapshot(self):
        return {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_preserve_idempotence_remove_and_execute(self):
        path = self.home / '.claude/settings.json'
        path.parent.mkdir(parents=True)
        original = {'permissions': {'defaultMode': 'default'}, 'hooks': {'Stop': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'echo other'}]}]}}
        path.write_text(json.dumps(original), encoding='utf-8')
        trust = self.home / '.codex/config.toml'
        trust.parent.mkdir(); trust.write_bytes(b'# do not modify trust\n')
        before = self.snapshot(); self.install(); self.assertEqual(before, self.snapshot())
        self.install(apply=True)
        saved = self.snapshot(); self.install(apply=True); self.assertEqual(saved, self.snapshot())
        config = json.loads(path.read_text(encoding='utf-8'))
        h = config['hooks']['Stop'][-1]['hooks'][0]
        result = subprocess.run([h['command'], *h['args']], input='{}', text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
        agy = json.loads((self.home / '.gemini/config/hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(agy['hafiza-os']['Stop'][0]['type'], 'command')
        self.assertNotIn('hooks', agy['hafiza-os'])
        self.install(remove=True, apply=True)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), original)
        self.assertEqual(trust.read_bytes(), b'# do not modify trust\n')

    def test_preflight_malformed_and_edited_ownership_no_writes(self):
        path = self.home / '.gemini/config/hooks.json'
        path.parent.mkdir(parents=True); path.write_text('{broken', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError): self.install(apply=True)
        self.assertEqual(before, self.snapshot())
        path.unlink(); self.install(apply=True)
        config = json.loads(path.read_text(encoding='utf-8'))
        config['hafiza-os']['Stop'][0]['timeout'] = 99
        path.write_text(json.dumps(config), encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError): self.install(remove=True, apply=True)
        self.assertEqual(before, self.snapshot())

    def test_exact_legacy_migration_requires_flag_and_preserves_other_vault(self):
        path = self.home / '.claude/settings.json'; path.parent.mkdir(parents=True)
        own = str(self.vault / '.claude/hooks/hafiza-kontrol.sh')
        other = str(self.root / 'other/.claude/hooks/hafiza-kontrol.sh')
        path.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': own}, {'type': 'command', 'command': other}]}], 'PreCompact': [{'hooks': [{'type': 'command', 'command': own}]}]}}), encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError): self.install(apply=True)
        self.assertEqual(before, self.snapshot())
        self.install(apply=True, migrate_legacy=True)
        config = json.loads(path.read_text(encoding='utf-8'))
        self.assertNotIn('PreCompact', config['hooks'])
        self.assertEqual(config['hooks']['Stop'][0]['hooks'][0]['command'], other)
        self.assertNotIn(own, path.read_text(encoding='utf-8'))

    def test_codex_exact_legacy_upgrade(self):
        import shlex
        path = self.home / '.codex/hooks.json'; path.parent.mkdir(parents=True)
        command = 'python3 ' + shlex.quote(str(self.vault / 'araclar/codex_hafiza.py')) + ' hook'
        path.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': command}]}]}}), encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError): self.install(apply=True)
        self.assertEqual(before, self.snapshot())
        self.install(migrate_legacy=True, apply=True)
        config = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(config['hooks']['Stop']), 1)
        self.assertNotEqual(config['hooks']['Stop'][0]['hooks'][0]['command'], command)

    def test_quoting_and_generic_rejection(self):
        import shlex
        args = [sys.executable, 'a b', "Türkçe'$(echo bad)"]
        self.assertEqual(shlex.split(agent_hooks.shell_command(args, 'posix')), args)
        for bad in ('a%PATH%', 'a!b', 'a&b', 'a"b'):
            with self.assertRaises(ValueError): agent_hooks.shell_command(['python', bad], 'cmd')
        with self.assertRaises(ValueError):
            ajan_kur.install(self.vault, 'generic', self.home, export=self.root / 'a.md', with_hooks=True, apply=True)
        self.assertFalse((self.root / 'a.md').exists())

    def test_concurrent_change_refused_before_instruction_write(self):
        original = ajan_kur.read_target
        calls = {}
        def racing(path):
            calls[str(path)] = calls.get(str(path), 0) + 1
            if path.name == 'CLAUDE.md' and calls[str(path)] == 2:
                return b'concurrent change'
            return original(path)
        before = self.snapshot()
        with patch.object(ajan_kur, 'read_target', side_effect=racing), self.assertRaises(ValueError):
            self.install(apply=True)
        self.assertEqual(before, self.snapshot())
