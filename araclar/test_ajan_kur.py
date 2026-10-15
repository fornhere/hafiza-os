"""Isolated bridge tests: no real home, vault, hooks, network or client process."""
import contextlib
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

import ajan_kur as bridge


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vault = self.root / "Türkçe kasa ' $(not-a-command)"
        for name in bridge.REQUIRED:
            path = self.vault / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n', encoding='utf-8')
        self.home = self.root / 'test home'
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'USERPROFILE': str(self.home)}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def install(self, agent='all', **kwargs):
        return bridge.install(self.vault, agent, self.home, **kwargs)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_dry_run_has_no_writes_or_directories(self):
        before = self.snapshot()
        result = self.install()
        self.assertEqual(len(result['targets']), 3)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.home.exists())
        self.install(remove=True, apply=True)
        self.assertFalse(self.home.exists())

    def test_same_vault_preservation_idempotence_and_remove(self):
        paths = bridge.targets('all', self.home)
        old = b'Existing instructions\r\n\r\nNo final newline'
        for path in paths:
            path.parent.mkdir(parents=True)
            path.write_bytes(old)
        settings = self.home / '.claude/settings.json'
        settings.write_bytes(b'{"hooks":{"untouched":true}}')
        trust = self.home / '.codex/config.toml'
        trust.write_bytes(b'trust_level = "trusted"\n')
        result = self.install(apply=True)
        for row in result['targets']:
            data = Path(row['path']).read_text(encoding='utf-8')
            self.assertIn(json.dumps(str(self.vault), ensure_ascii=False), data)
            self.assertIn('latest-session', data)
            self.assertIn(bridge.command(['--char-budget', '1200'], os.name == 'nt').removeprefix('& '), data)
            self.assertTrue(Path(row['path']).read_bytes().endswith(old))
            self.assertEqual(Path(row['backup']).read_bytes(), old)
        before = self.snapshot()
        stats = {str(p): p.stat().st_mtime_ns for p in paths}
        self.assertTrue(all(not r['changed'] for r in self.install(apply=True)['targets']))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(stats, {str(p): p.stat().st_mtime_ns for p in paths})
        self.install(remove=True, apply=True)
        for path in paths:
            self.assertEqual(path.read_bytes(), old)
        self.assertEqual(settings.read_bytes(), b'{"hooks":{"untouched":true}}')
        self.assertEqual(trust.read_bytes(), b'trust_level = "trusted"\n')
        before = self.snapshot()
        self.install(remove=True, apply=True)
        self.assertEqual(before, self.snapshot())

    def test_update_only_own_block_with_timestamped_backup(self):
        self.install('claude', apply=True)
        path = self.home / '.claude/CLAUDE.md'
        old = path.read_bytes().replace(b'ortak', b'old')
        path.write_bytes(b'prefix\n' + old + b'suffix')
        result = self.install('claude', apply=True)
        self.assertEqual(Path(result['targets'][0]['backup']).read_bytes(), b'prefix\n' + old + b'suffix')
        self.assertTrue(path.read_bytes().startswith(b'prefix\n'))
        self.assertTrue(path.read_bytes().endswith(b'suffix'))
        self.assertEqual(path.read_text().count(bridge.START), 1)

    def test_claude_legacy_migration_preserves_bytes_and_is_idempotent(self):
        path = self.home / '.claude/CLAUDE.md'
        path.parent.mkdir(parents=True)
        prefix = '# Git kimliği\r\nKişisel yönerge.\r\n\r\n'.encode('utf-8')
        suffix = ('# Jev\r\nYerel tercih.\r\n\r\n# Paralel ajan işi\n'
                  'Kullanıcı metni; son satırda newline yok').encode('utf-8')
        legacy = (bridge.LEGACY_CLAUDE_START + '\r\n# Hafıza OS — global başlangıç\r\n'
                  'Eski açılış ve makbuz talimatı.\r\n' + bridge.LEGACY_CLAUDE_END + '\r\n').encode('utf-8')
        shared = bridge.instruction_block(self.vault).encode('utf-8')
        for agent in ('claude', 'all'):
            for existing_shared in (b'', shared):
                with self.subTest(agent=agent, existing_shared=bool(existing_shared)):
                    # Even repeated complete legacy blocks have one deterministic migration.
                    original = prefix + existing_shared + legacy + b'\r\n' + legacy + suffix
                    path.write_bytes(original)
                    before = self.snapshot()
                    self.assertTrue(self.install(agent)['targets'][0]['changed'])
                    self.assertEqual(before, self.snapshot())
                    result = self.install(agent, apply=True)
                    expected = (prefix + shared if existing_shared else shared + prefix) + b'\r\n' + suffix
                    self.assertEqual(path.read_bytes(), expected)
                    self.assertEqual(Path(result['targets'][0]['backup']).read_bytes(), original)
                    self.assertEqual(path.read_text(encoding='utf-8').count(bridge.START), 1)
                    before = self.snapshot()
                    mtime = path.stat().st_mtime_ns
                    self.assertTrue(all(not row['changed'] for row in self.install(agent, apply=True)['targets']))
                    self.assertEqual(before, self.snapshot())
                    self.assertEqual(path.stat().st_mtime_ns, mtime)

    def test_claude_remove_also_migrates_legacy_and_preserves_unmarked_heading(self):
        path = self.home / '.claude/CLAUDE.md'
        path.parent.mkdir(parents=True)
        personal = '# Hafıza OS — global başlangıç\r\nİşaretsiz kişisel metin'.encode('utf-8')
        legacy = (bridge.LEGACY_CLAUDE_START + '\nobsolete\n' + bridge.LEGACY_CLAUDE_END + '\n').encode('utf-8')
        for shared in (b'', bridge.instruction_block(self.vault).encode('utf-8')):
            with self.subTest(existing_shared=bool(shared)):
                path.write_bytes(legacy + shared + personal)
                self.install('claude', remove=True, apply=True)
                self.assertEqual(path.read_bytes(), personal)
                before = self.snapshot()
                self.install('claude', remove=True, apply=True)
                self.assertEqual(before, self.snapshot())

    def test_malformed_legacy_claude_markers_abort_all_before_mutation(self):
        start, end = bridge.LEGACY_CLAUDE_START, bridge.LEGACY_CLAUDE_END
        variants = [start, end, end + '\n' + start,
                    start + '\n' + start + '\n' + end,
                    'prefix ' + start + '\n' + end,
                    start + '\n' + end + ' suffix',
                    start + '\n' + bridge.START + '\n' + bridge.END + '\n' + end,
                    start + '\nold\n' + end + '\n' + start]
        path = self.home / '.claude/CLAUDE.md'
        path.parent.mkdir(parents=True)
        for bad in variants:
            with self.subTest(bad=bad):
                path.write_text(bad + '\n# Git kimliği\nKoru', encoding='utf-8')
                before = self.snapshot()
                for remove in (False, True):
                    with self.assertRaises(ValueError):
                        self.install(apply=True, remove=remove)
                    self.assertEqual(before, self.snapshot())
                    self.assertFalse((self.home / '.codex').exists())

    def test_legacy_claude_migration_does_not_own_other_clients_or_exports(self):
        legacy = (bridge.LEGACY_CLAUDE_START + '\r\nA user example\r\n' + bridge.LEGACY_CLAUDE_END).encode('utf-8')
        for agent in ('codex', 'antigravity', 'generic'):
            kwargs = {'export': self.root / 'export.md'} if agent == 'generic' else {}
            path = bridge.targets(agent, self.home, **kwargs)[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(legacy)
            self.install(agent, apply=True, **kwargs)
            self.assertTrue(path.read_bytes().endswith(legacy))
            self.install(agent, remove=True, apply=True, **kwargs)
            self.assertEqual(path.read_bytes(), legacy)

    def test_legacy_migration_still_preflights_all_targets(self):
        claude = self.home / '.claude/CLAUDE.md'
        claude.parent.mkdir(parents=True)
        claude.write_text(bridge.LEGACY_CLAUDE_START + '\nold\n' + bridge.LEGACY_CLAUDE_END,
                          encoding='utf-8')
        other = self.home / '.gemini/GEMINI.md'
        other.parent.mkdir(parents=True)
        other.write_text(bridge.START, encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.install(apply=True)
        self.assertEqual(before, self.snapshot())

    def test_malformed_markers_abort_all_before_mutation(self):
        variants = [bridge.START, bridge.END, bridge.END + '\n' + bridge.START,
                    bridge.START + '\n' + bridge.START + '\n' + bridge.END,
                    'prefix ' + bridge.START + '\n' + bridge.END,
                    bridge.PREFIX + 'BROKEN -->',
                    bridge.START + '\n' + bridge.END + ' suffix']
        path = self.home / '.gemini/GEMINI.md'
        path.parent.mkdir(parents=True)
        for bad in variants:
            with self.subTest(bad=bad):
                path.write_text(bad)
                before = self.snapshot()
                for remove in (False, True):
                    with self.assertRaises(ValueError):
                        self.install(apply=True, remove=remove)
                    self.assertEqual(before, self.snapshot())
                    self.assertFalse((self.home / '.claude').exists())

    def test_links_and_parent_links_rejected_without_mutation(self):
        outside = self.root / 'outside'
        outside.mkdir()
        target = outside / 'AGENTS.md'
        target.write_text('do not touch')
        self.home.mkdir()
        try:
            (self.home / '.codex').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlink permission unavailable: {exc}')
        with self.assertRaises(ValueError):
            self.install(apply=True)
        self.assertEqual(target.read_text(), 'do not touch')
        self.assertFalse((self.home / '.claude').exists())
        (self.home / '.codex').unlink()
        (self.home / '.codex').mkdir()
        for destination in (target, outside / 'missing'):
            link = self.home / '.codex/AGENTS.md'
            link.symlink_to(destination)
            with self.assertRaises(ValueError):
                self.install(apply=True)
            link.unlink()
        self.assertEqual(target.read_text(), 'do not touch')

    def test_vault_parent_link_and_hardlinked_target_rejected(self):
        alias = self.root / 'alias'
        try:
            alias.symlink_to(self.vault, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlink permission unavailable: {exc}')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            bridge.install(alias, 'all', self.home, apply=True)
        self.assertEqual(before, self.snapshot())
        path = self.home / '.claude/CLAUDE.md'
        path.parent.mkdir(parents=True)
        original = self.root / 'original.md'
        original.write_text('protected')
        try:
            os.link(original, path)
        except OSError as exc:
            self.skipTest(f'Hardlink unavailable: {exc}')
        with self.assertRaises(ValueError):
            self.install(apply=True)
        self.assertEqual(original.read_text(), 'protected')
        self.assertFalse((self.home / '.codex').exists())

    def test_invalid_utf8_and_control_paths_do_not_write(self):
        path = self.home / '.gemini/GEMINI.md'
        path.parent.mkdir(parents=True)
        path.write_bytes(bytes([255]))
        before = self.snapshot()
        with self.assertRaises(UnicodeError):
            self.install(apply=True)
        self.assertEqual(before, self.snapshot())
        for value in ('bad\npath', 'a/../b'):
            with self.assertRaises(ValueError):
                bridge.safe_path(value)

    def test_legacy_blocks_preserved_and_new_file_remove_leaves_empty(self):
        path = self.home / '.codex/AGENTS.md'
        path.parent.mkdir(parents=True)
        legacy = '<!-- HAFIZA-OS:CODEX:START -->\nlegacy\n<!-- HAFIZA-OS:CODEX:END -->'
        path.write_text(legacy)
        self.install('codex', apply=True)
        self.install('codex', remove=True, apply=True)
        self.assertEqual(path.read_text(), legacy)
        self.install('antigravity', apply=True)
        self.install('antigravity', remove=True, apply=True)
        empty = self.home / '.gemini/GEMINI.md'
        self.assertTrue(empty.exists())
        self.assertEqual(empty.read_bytes(), b'')

    def test_codex_overrides(self):
        env_home = self.root / 'env codex'
        explicit = self.root / 'explicit codex'
        with patch.dict(os.environ, {'CODEX_HOME': str(env_home)}):
            self.assertEqual(self.install('codex')['targets'][0]['path'], str(env_home / 'AGENTS.md'))
            self.assertEqual(self.install('codex', codex_home=explicit)['targets'][0]['path'], str(explicit / 'AGENTS.md'))
        self.assertFalse(env_home.exists())

    def test_generic_is_managed_and_non_destructive(self):
        dest = self.root / 'handoff.md'
        dest.write_bytes(b'Manual notes\n')
        self.install('generic', export=dest, apply=True)
        self.assertIn(bridge.START, dest.read_text())
        self.install('generic', export=dest, remove=True, apply=True)
        self.assertEqual(dest.read_bytes(), b'Manual notes\n')
        for bad in (self.vault / 'agents.md', self.root / 'settings.json'):
            with self.assertRaises(ValueError):
                self.install('generic', export=bad, apply=True)

    def test_missing_vault_file_and_non_file_target(self):
        (self.vault / 'agents.md').unlink()
        with self.assertRaises(ValueError):
            self.install(apply=True)
        self.assertFalse(self.home.exists())
        (self.vault / 'agents.md').write_text('fixture')
        (self.home / '.claude/CLAUDE.md').mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.install(apply=True)

    def test_path_quoting(self):
        argv = ['python3', str(self.vault / 'araclar/hafiza.py'), '--vault', str(self.vault), 'context', 'soru']
        self.assertEqual(shlex.split(bridge.command(argv)), argv)
        self.assertEqual(bridge.command(['python', "C:\\Kişi'nin kasası\\hafiza.py"], True),
                         "& 'python' 'C:\\Kişi''nin kasası\\hafiza.py'")

    def test_windows_instructions_use_native_utf8_python(self):
        vault = self.vault
        with patch.object(bridge.os, 'name', 'nt'):
            block = bridge.instruction_block(vault)
        for value in ('powershell', 'latest-session', "'-X' 'utf8'", '--vault'):
            self.assertIn(value, block)
        self.assertNotIn('desteklenmez', block)

    def test_posix_instructions_keep_bounded_cli_commands(self):
        vault = self.vault
        with patch.object(bridge.os, 'name', 'posix'):
            block = bridge.instruction_block(vault)
        commands = [part.split('\n```', 1)[0]
                    for part in block.split('```sh\n')[1:]]
        self.assertEqual([shlex.split(cmd) for cmd in commands], [
            [sys.executable, '-X', 'utf8', str(vault / 'araclar/codex_hafiza.py'), '--vault',
             str(vault), 'latest-session'],
            [sys.executable, '-X', 'utf8', str(vault / 'araclar/hafiza.py'), '--vault', str(vault),
             'context', 'göreve ilişkin soru', '--limit', '5', '--char-budget', '1200'],
        ])
        self.assertNotIn('Yerel Windows', block)

    def test_instruction_block_starts_access_with_worker_exception(self):
        block = bridge.instruction_block(self.vault)
        exception = "Otomatik işçi koşusunda (codex exec işçisi, alt ajan veya istem 'İŞÇİ KOŞUSU'"
        self.assertIn(exception, block)
        self.assertIn('açılış okuması, latest-session, context ve kayıt yapma;',
                      block.replace('\n', ' '))
        self.assertLess(block.index(exception), block.index('Yeni ana oturumda'))

    def test_cli_invalid_inputs(self):
        base = ['--vault', str(self.vault), '--home', str(self.home)]
        for tail in ([], ['--agent', 'unknown'], ['--agent', 'generic'],
                     ['--agent', 'all', '--export', str(self.root / 'a.md')],
                     ['--agent', 'claude', '--apply', '--dry-run'],
                     ['--agent', 'claude', '--codex-home', str(self.root / 'c')]):
            with self.subTest(tail=tail), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    bridge.main(base + tail)
                self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.home.exists())


if __name__ == '__main__':
    unittest.main()
