import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ShellGuards(unittest.TestCase):
    def test_fallback_checks_unusual_filenames_and_staged_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            # Only expose the fallback's dependencies, never a local sir-tara.
            binaries = repo / 'bin'
            binaries.mkdir()
            for name in ('git', 'grep', 'head'):
                (binaries / name).symlink_to(shutil.which(name))
            env = dict(os.environ, PATH=str(binaries))
            def git(*args):
                subprocess.run([shutil.which('git'), '-C', tmp, *args], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            git('init')
            for name in ('plain.txt', 'sample note.txt', 'Türkçe.txt', 'line\nbreak.txt', '-option.txt'):
                with self.subTest(name=name):
                    git('read-tree', '--empty')
                    path = repo / name
                    path.write_text('sk-' + 'A' * 24 + '\n')
                    git('add', '--', name)
                    path.write_text('clean unstaged content\n')
                    result = subprocess.run([shutil.which('bash'), str(ROOT / '.githooks/pre-commit')],
                                            cwd=repo, env=env, capture_output=True)
                    self.assertEqual(result.returncode, 1)
            git('read-tree', '--empty')
            git('add', '--', 'plain.txt')
            result = subprocess.run([shutil.which('bash'), str(ROOT / '.githooks/pre-commit')],
                                    cwd=repo, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0)

    def test_install_reinstall_execute_and_uninstall_with_shell_characters(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vault = base / "memory space 'quote $dollar"
            shutil.copytree(ROOT, vault, ignore=shutil.ignore_patterns('.git', '__pycache__'))
            home = base / 'isolated-home'
            home.mkdir()
            env = dict(os.environ, HOME=str(home))
            settings = home / '.claude/settings.json'
            settings.parent.mkdir()
            settings.write_text(json.dumps({'hooks': {'SessionStart': [{'hooks': [
                {'type': 'command', 'command': 'echo unrelated'},
                {'type': 'command', 'command': '/old/.claude/hooks/oturum-basla.sh'}]}]}}))
            def install(*args):
                subprocess.run(['bash', str(vault / 'kur.sh'), *args], env=env,
                               check=True, capture_output=True)
            install()
            install()
            hooks = json.loads(settings.read_text())['hooks']
            commands = [h['command'] for rows in hooks.values() for row in rows for h in row['hooks']]
            self.assertEqual(len(commands), 6)
            self.assertIn('echo unrelated', commands)
            for command in commands:
                if command == 'echo unrelated':
                    continue
                result = subprocess.run(['bash', '-c', command], env=env,
                                        input='{"session_id":"test","source":"startup"}',
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            install('--kaldir')
            hooks = json.loads(settings.read_text())['hooks']
            self.assertEqual(hooks, {'SessionStart': [{'hooks': [
                {'type': 'command', 'command': 'echo unrelated'}]}]})
