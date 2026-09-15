import subprocess
import tempfile
import unittest
from pathlib import Path
from hafiza_git import commit_memory

class MemoryGitTest(unittest.TestCase):
    def test_scope_noop_and_staged_guard(self):
        with tempfile.TemporaryDirectory() as root:
            v = Path(root)
            def git(*args):
                return subprocess.check_output(['git', '-C', root, *args], stderr=subprocess.PIPE).decode()
            git('init'); git('config', 'user.name', 'Test'); git('config', 'user.email', 'test@example.invalid')
            git('commit', '--allow-empty', '-m', 'init')
            (v/'komuta').mkdir(); (v/'zihin').mkdir()
            (v/'komuta/hafıza-sagligi.md').write_text('health')
            self.assertEqual(commit_memory(v)['status'], 'unchanged')
            (v/'zihin/is-durumu.jsonl').write_text('{}\n')
            (v/'personal.md').write_text('unrelated')
            self.assertEqual(commit_memory(v)['status'], 'committed')
            tracked = git('ls-files')
            self.assertIn('is-durumu.jsonl', tracked)
            self.assertNotIn('personal.md', tracked)
            self.assertEqual(commit_memory(v)['status'], 'unchanged')
            git('add', 'personal.md')
            with self.assertRaises(ValueError): commit_memory(v)
            self.assertIn('personal.md', git('diff', '--cached', '--name-only'))

    def test_deletion_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            v=Path(root)
            def git(*args):
                return subprocess.check_output(['git','-C',root,*args],stderr=subprocess.PIPE)
            git('init');git('config','user.name','Test');git('config','user.email','test@example.invalid')
            (v/'zihin').mkdir();p=v/'zihin/is-durumu.jsonl';p.write_text('{}\n')
            git('add','.');git('commit','-m','init');p.unlink()
            with self.assertRaises(ValueError):commit_memory(v)

if __name__ == '__main__': unittest.main()
