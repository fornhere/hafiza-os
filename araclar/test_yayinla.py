import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import io
import tarfile
import yayinla as y

class Publication(unittest.TestCase):
    def test_parity_rejects_unreviewed_variants_and_unlisted_runtime(self):
        with tempfile.TemporaryDirectory() as d:
            repo=Path(d)/'public'; vault=Path(d)/'local'
            for p in (repo,vault): (p/'araclar').mkdir(parents=True)
            a=vault/'araclar/a.py'; b=repo/'araclar/a.py'
            a.write_text('personal = 1'); b.write_text('personal = 2')
            manifest=repo/'publication-manifest.json'
            manifest.write_text(json.dumps({'files':[{'path':'araclar/a.py','mode':'shared'}]}))
            with self.assertRaises(ValueError): y.parity(repo,vault)
            row={'path':'araclar/a.py','mode':'reviewed-variant','reason':'Reviewed configurable identity defaults.',
                 'local_sha256':y.digest(a),'public_sha256':y.digest(b)}
            manifest.write_text(json.dumps({'files':[row]})); y.parity(repo,vault)
            a.write_text('changed=3')
            with self.assertRaises(ValueError): y.parity(repo,vault)
            row['local_sha256']=y.digest(a); manifest.write_text(json.dumps({'files':[row]}))
            (repo/'araclar/missing.py').write_text('')
            with self.assertRaises(ValueError): y.parity(repo,vault)

    def scan_tree(self, name, body):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repo = Path(directory.name)
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body, encoding='utf-8')
        return repo

    def test_scan_rejects_personal_email_and_absolute_home_paths(self):
        # Literals are assembled at runtime so this file stays publishable itself.
        rejected = {'note.md': 'yazan ada.lovelace' + '@' + 'mail.gorunur.tr adresi',
                    'mac.md': 'kasa /Users' + '/someone/Hafiza altinda',
                    'linux.md': 'kasa /home' + '/someone/Hafiza altinda',
                    'aws.txt': 'anahtar AKIA' + 'IOSFODNN7GORUNUR burada'}
        for name, body in rejected.items():
            with self.subTest(name=name):
                repo = self.scan_tree(name, body)
                with self.assertRaisesRegex(ValueError, 'publication scan rejected'):
                    y.scan(repo, [name])

    def test_scan_allows_placeholder_and_noreply_addresses(self):
        body = ('test@example.invalid ve 1+kullanici@users.noreply.github.com ve '
                'noreply@anthropic.com adresleri paylasilabilir')
        repo = self.scan_tree('ok.md', body)
        y.scan(repo, ['ok.md'])
        self.assertEqual(y.findings(body), [])

    def test_scan_skips_its_own_detector_source(self):
        repo = self.scan_tree(y.SELF_PATH, Path(y.__file__).read_text(encoding='utf-8'))
        y.scan(repo, [y.SELF_PATH])

    def test_dirty_tree_is_rejected_before_tests(self):
        from unittest.mock import patch
        with patch.object(y,'run',return_value=' M file'):
            with self.assertRaisesRegex(ValueError,'commit'): y.validate_committed(Path('.'))

    def test_apply_requires_local_parity(self):
        with self.assertRaises(ValueError): y.publish(Path('.'),None,True)

    def publish_mocks(self, remote_sha='head'):
        def git(repo,*args):
            if args[0]=='remote': return 'https://github.com/example/memory.git'
            if args[0]=='rev-parse': return 'head'
            if args[0]=='status': return ''
            if 'ls-remote' in args: return remote_sha+'\trefs/heads/main'
            raise AssertionError(args)
        return git

    def test_failed_push_never_reports_published(self):
        def command(args,**kwargs):
            if 'push' in args: raise subprocess.CalledProcessError(1,args)
        with patch.object(y,'parity') as parity, patch.object(y,'validate_committed',return_value='head'), \
             patch.object(y,'run',side_effect=self.publish_mocks()), patch.object(y.subprocess,'run',side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError): y.publish(Path('.'),Path('local'),True)
            self.assertEqual(parity.call_count,2)

    def test_remote_mismatch_is_failure(self):
        with patch.object(y,'parity'), patch.object(y,'validate_committed',return_value='head'), \
             patch.object(y,'run',side_effect=self.publish_mocks('different')), patch.object(y.subprocess,'run'):
            with self.assertRaisesRegex(ValueError,'remote commit differs'): y.publish(Path('.'),Path('local'),True)

    def test_local_drift_after_tests_prevents_push(self):
        with patch.object(y,'parity',side_effect=[None,ValueError('local drift')]), \
             patch.object(y,'validate_committed',return_value='head'), patch.object(y,'run',side_effect=self.publish_mocks()), \
             patch.object(y.subprocess,'run') as command:
            with self.assertRaisesRegex(ValueError,'local drift'): y.publish(Path('.'),Path('local'),True)
            self.assertFalse(any('push' in c.args[0] for c in command.call_args_list))

    def test_source_changed_during_validation_rejected(self):
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w'): pass
        # Initial status/head/list then changed HEAD after the committed-tree tests.
        with patch.object(y,'run',side_effect=['','before','','after']), \
             patch.object(y.subprocess,'check_output',return_value=data.getvalue()), \
             patch.object(y.subprocess,'run'), patch.object(y,'scan'):
            with self.assertRaisesRegex(ValueError,'changed during validation'): y.validate_committed(Path('.'))
