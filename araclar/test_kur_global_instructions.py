"""Exercise kur.sh instruction migration in a minimal vault and isolated HOME."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import ajan_kur as bridge


ROOT = Path(__file__).resolve().parents[1]
LEGACY_START = '<!-- HAFIZA-OS:BAŞLA -->'.encode('utf-8')
LEGACY_END = '<!-- HAFIZA-OS:BİTİR -->'.encode('utf-8')
SHARED_START = b'<!-- HAFIZA-OS:SHARED:START -->'
SHARED_END = b'<!-- HAFIZA-OS:SHARED:END -->'


@unittest.skipIf(os.name == 'nt', 'kur.sh is the optional POSIX installer')
class GlobalInstructionShellTests(unittest.TestCase):
    def setUp(self):
        for command in ('bash', 'python3', 'jq', 'git'):
            if shutil.which(command) is None:
                self.skipTest(f'{command} is required for the shell installer')
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.vault = self.root / "Türkçe kasa ' $literal"
        for name in bridge.REQUIRED:
            path = self.vault / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture\n', encoding='utf-8')
        shutil.copyfile(ROOT / 'kur.sh', self.vault / 'kur.sh')
        shutil.copyfile(ROOT / 'araclar/ajan_kur.py', self.vault / 'araclar/ajan_kur.py')
        for name in ('komuta', 'projeler', 'günlük', 'arşiv', 'gelen-kutusu'):
            (self.vault / name).mkdir(exist_ok=True)
        hooks = self.vault / '.claude/hooks'
        hooks.mkdir(parents=True)
        for name in ('oturum-basla', 'mesaj-say', 'hafiza-kontrol', 'oturum-bitir'):
            # The installer may register these paths, but must never execute them.
            (hooks / (name + '.sh')).write_text('#!/usr/bin/env bash\nexit 99\n')
        self.home = self.root / 'temporary home'
        self.claude = self.home / '.claude/CLAUDE.md'
        self.claude.parent.mkdir(parents=True)
        self.settings = self.claude.with_name('settings.json')
        self.settings.write_bytes(b'{"fixture_setting": "preserve me"}\n')
        # Do not inherit Git overrides, client paths or other user configuration.
        self.env = {
            'HOME': str(self.home),
            'USERPROFILE': str(self.home),
            'PATH': os.environ.get('PATH', os.defpath),
            'PYTHONUTF8': '1',
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': str(self.root / 'unused-gitconfig'),
        }

    def run_installer(self, *args, succeeds=True):
        result = subprocess.run(
            [shutil.which('bash'), str(self.vault / 'kur.sh'), *args],
            cwd=self.root, env=self.env, capture_output=True, timeout=30,
        )
        output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
        if succeeds:
            self.assertEqual(result.returncode, 0, output)
        else:
            self.assertNotEqual(result.returncode, 0, output)
        return result

    def mixed_instructions(self):
        prefix = '# Git kimliği\r\nAd: Örnek Kullanıcı\r\n\r\n'.encode('utf-8')
        middle = '# Jev\r\nSahte test yönergesi.\r\n\r\n'.encode('utf-8')
        suffix = '# Paralel ajan işi\r\nKullanıcı metni; son satırda newline yok'.encode('utf-8')
        shared = SHARED_START + b'\r\nExisting shared instructions\r\n' + SHARED_END + b'\r\n'
        legacy = (LEGACY_START + b'\r\n' + '# Hafıza OS — global başlangıç\r\n'.encode('utf-8')
                  + b'Obsolete instructions\r\n' + LEGACY_END + b'\r\n')
        return prefix + shared + middle + legacy + suffix, prefix + middle + suffix

    def without_shared(self, data):
        self.assertEqual(data.count(SHARED_START), 1)
        self.assertEqual(data.count(SHARED_END), 1)
        prefix, _, following = data.partition(SHARED_START)
        _, _, suffix = following.partition(SHARED_END)
        self.assertTrue(suffix.startswith(b'\n'))
        return prefix + suffix[1:]

    def claude_backups(self):
        return {path.name: path.read_bytes()
                for path in self.claude.parent.glob('CLAUDE.md.backup-*')}

    def assert_second_install_is_unchanged(self):
        before = self.claude.read_bytes()
        backups = self.claude_backups()
        # A fixed old timestamp detects even a rewrite with identical bytes.
        os.utime(self.claude, ns=(1_000_000_000_000, 1_000_000_000_000))
        modified = self.claude.stat().st_mtime_ns
        self.run_installer()
        self.assertEqual(self.claude.read_bytes(), before)
        self.assertEqual(self.claude.stat().st_mtime_ns, modified)
        self.assertEqual(self.claude_backups(), backups)

    def test_migration_preserves_user_bytes_and_reinstall_is_idempotent(self):
        original, user_content = self.mixed_instructions()
        self.claude.write_bytes(original)
        self.run_installer()
        updated = self.claude.read_bytes()
        self.assertNotIn(LEGACY_START, updated)
        self.assertNotIn(LEGACY_END, updated)
        self.assertNotIn('global başlangıç'.encode('utf-8'), updated)
        self.assertIn('ortak yönerge erişimi'.encode('utf-8'), updated)
        self.assertEqual(self.without_shared(updated), user_content)
        self.assertEqual(list(self.claude_backups().values()), [original])
        self.assert_second_install_is_unchanged()

    def test_fresh_install_twice_has_one_shared_block_and_no_legacy(self):
        self.run_installer()
        updated = self.claude.read_bytes()
        self.assertNotIn(LEGACY_START, updated)
        self.assertNotIn(LEGACY_END, updated)
        self.assertEqual(self.without_shared(updated), b'')
        self.assertEqual(self.claude_backups(), {})
        self.assert_second_install_is_unchanged()

    def test_uninstall_removes_both_owned_blocks_and_preserves_user_bytes(self):
        original, user_content = self.mixed_instructions()
        self.claude.write_bytes(original)
        self.run_installer('--kaldir')
        self.assertEqual(self.claude.read_bytes(), user_content)
        self.assertEqual(list(self.claude_backups().values()), [original])
        backups = self.claude_backups()
        self.run_installer('--kaldir')
        self.assertEqual(self.claude.read_bytes(), user_content)
        self.assertEqual(self.claude_backups(), backups)

    def test_malformed_legacy_aborts_install_and_uninstall_before_settings_change(self):
        variants = (
            LEGACY_START + b'\r\nMissing closing marker\r\nDo not delete me',
            LEGACY_START + b'\r\n' + LEGACY_END + b' user suffix\r\nPreserve me',
        )
        for malformed in variants:
            for args in ((), ('--kaldir',)):
                with self.subTest(malformed=malformed, args=args):
                    self.claude.write_bytes(malformed)
                    before = {path.name: path.read_bytes() for path in self.claude.parent.iterdir()}
                    self.run_installer(*args, succeeds=False)
                    after = {path.name: path.read_bytes() for path in self.claude.parent.iterdir()}
                    self.assertEqual(after, before)


if __name__ == '__main__':
    unittest.main()
