"""Native Windows/macOS/Linux core checks; synthetic sources, no network.

Run with: python -m unittest discover -s araclar -p test_platform_runtime.py
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import codex_hafiza
from platform_lock import exclusive_lock


class PlatformRuntime(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name).resolve() / "Hafıza örnek kasa 'alıntı'"
        self.scripts = self.vault / 'araclar'
        self.scripts.mkdir(parents=True)
        # Copy code only, never repository/personal vault data or configuration.
        for source in Path(__file__).resolve().parent.glob('*.py'):
            if not source.name.startswith('test_'):
                shutil.copyfile(source, self.scripts / source.name)
        (self.vault / 'zihin').mkdir()
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith(('HAFIZA_', 'MEM0_', 'PYTHON'))}
        self.environment.update(HOME=str(self.vault), USERPROFILE=str(self.vault))

    def command(self, code, *args):
        # -I excludes user packages/PYTHONPATH. Block network even if a regression
        # accidentally reaches a remote path. UTF-8 makes captured CLI I/O portable.
        # Keep socket.socket a class so ssl can subclass it. Audit events block
        # connections, DNS and datagram traffic, including direct _socket calls.
        # Socket construction itself is harmless and required by some imports.
        guard = '''import sys, socket
sys.path.insert(0, sys.argv.pop(1))
def forbid_network(event, args):
    if event.startswith('socket.') and event != 'socket.__new__':
        raise AssertionError('network forbidden in fixture')
sys.addaudithook(forbid_network)
'''
        return [sys.executable, '-I', '-X', 'utf8', '-c', guard + code,
                str(self.scripts), *map(str, args)]

    def run_code(self, code, *args):
        result = subprocess.run(self.command(code, *args), cwd=self.vault,
                                env=self.environment, capture_output=True,
                                text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def start(self, code, *args, input_text=None):
        process = subprocess.Popen(self.command(code, *args), cwd=self.vault,
                                   env=self.environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf-8')
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)
        self.addCleanup(cleanup)
        if input_text is not None:
            process.stdin.write(input_text)
            process.stdin.flush()
        return process

    def wait_ready(self, path, process):
        deadline = time.monotonic() + 15
        while not path.exists():
            self.assertIsNone(process.poll(), 'worker exited before readiness')
            if time.monotonic() > deadline:
                self.fail('worker readiness timeout')
            time.sleep(0.01)

    def finish(self, process):
        stdout, stderr = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, stderr)
        return stdout

    def test_imports_and_cli_help(self):
        self.run_code('import platform_lock, hafiza, codex_hafiza')
        for script in ('hafiza.py', 'codex_hafiza.py'):
            output = self.run_code(
                "import runpy; script = sys.argv.pop(1); "
                "sys.argv[0] = script; runpy.run_path(script, run_name='__main__')",
                self.scripts / script, '--help')
            self.assertIn('--vault', output)

    def test_network_guard_preserves_ssl_and_blocks_network(self):
        output = self.run_code('''
import ssl
import _socket
assert issubclass(ssl.SSLSocket, socket.socket)
def expect_blocked(operation):
    try:
        operation()
    except AssertionError as error:
        assert str(error) == 'network forbidden in fixture'
    else:
        raise AssertionError('network guard did not block operation')
expect_blocked(lambda: socket.getaddrinfo('localhost', 0))
expect_blocked(lambda: socket.create_connection(('127.0.0.1', 0)))
# Restricted runners may prohibit even socket creation. Still verify every
# guarded audit event there; exercise actual socket methods on native runners.
for event in ('socket.connect', 'socket.sendto', 'socket.sendmsg'):
    expect_blocked(lambda: sys.audit(event, None, ('127.0.0.1', 0)))
try:
    stream = socket.socket()
except PermissionError:
    print('Socket construction denied by sandbox; transport checks unavailable')
else:
    with stream:
        expect_blocked(lambda: stream.connect(('127.0.0.1', 0)))
        expect_blocked(lambda: stream.connect_ex(('127.0.0.1', 0)))
    datagram = _socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        expect_blocked(lambda: datagram.sendto(b'fixture', ('127.0.0.1', 0)))
    finally:
        datagram.close()
''')
        if 'Socket construction denied by sandbox' in output:
            self.skipTest('SSL/DNS/audit checks exercised; native socket checks require socket creation')

    def test_multiprocess_serialized_contention(self):
        directory = self.vault / 'günlük/hafıza-makbuzları'
        directory.mkdir(parents=True)
        lock = directory / '.writer.lock'
        lock.write_bytes(b'keep this lockfile')
        counter = self.vault / 'sayaç.json'
        counter.write_text('0', encoding='utf-8')
        code = '''
from pathlib import Path
import time
import hafiza
vault, ready = map(Path, sys.argv[1:])
@hafiza.serialized
def increment(vault):
    counter = vault / 'sayaç.json'
    value = int(counter.read_text(encoding='utf-8'))
    time.sleep(0.005)
    counter.write_text(str(value + 1), encoding='utf-8')
ready.touch()
for _ in range(12):
    increment(vault)
'''
        workers = []
        with exclusive_lock(lock):
            for index in range(3):
                ready = self.vault / f'ready-{index}'
                worker = self.start(code, self.vault, ready)
                workers.append(worker)
                self.wait_ready(ready, worker)
            time.sleep(0.2)
            self.assertEqual(counter.read_text(encoding='utf-8'), '0')
            self.assertTrue(all(worker.poll() is None for worker in workers))
        for worker in workers:
            self.finish(worker)
        self.assertEqual(counter.read_text(encoding='utf-8'), '36')
        self.assertEqual(lock.read_bytes(), b'keep this lockfile')

    def test_exception_releases_empty_lock_and_process_exit_releases(self):
        lock = self.vault / 'boş kilit'
        with self.assertRaisesRegex(RuntimeError, 'deliberate'):
            with exclusive_lock(lock):
                raise RuntimeError('deliberate')
        self.run_code('''
from platform_lock import exclusive_lock
with exclusive_lock(sys.argv[1]):
    print('acquired')
''', lock)
        self.assertEqual(lock.read_bytes(), b'')
        self.run_code('''
from platform_lock import exclusive_lock
import os
with exclusive_lock(sys.argv[1]):
    os._exit(0)
''', lock)
        self.run_code('''
from platform_lock import exclusive_lock
with exclusive_lock(sys.argv[1]):
    pass
''', lock)

    @unittest.skipUnless(os.name == 'posix', 'POSIX flock interoperability')
    def test_interoperates_with_legacy_flock(self):
        import fcntl
        lock = self.vault / 'legacy.lock'
        ready = self.vault / 'legacy.ready'
        entered = self.vault / 'legacy.entered'
        with lock.open('a') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            worker = self.start('''
from pathlib import Path
from platform_lock import exclusive_lock
Path(sys.argv[2]).touch()
with exclusive_lock(sys.argv[1]):
    Path(sys.argv[3]).touch()
''', lock, ready, entered)
            self.wait_ready(ready, worker)
            time.sleep(0.2)
            self.assertFalse(entered.exists())
        self.finish(worker)
        self.assertTrue(entered.exists())

    def test_codex_cli_uses_existing_lock_and_renders_latest_command(self):
        directory = self.vault / codex_hafiza.INBOX
        directory.mkdir(parents=True)
        ready = self.vault / 'hook.ready'
        with exclusive_lock(directory / '.lock'):
            worker = self.start('''
from pathlib import Path
import codex_hafiza
Path(sys.argv.pop(1)).touch()
codex_hafiza.main()
''', ready, '--vault', self.vault, 'hook', input_text=json.dumps({
                'session_id': 'synthetic', 'hook_event_name': 'SessionStart'}) + '\n')
            self.wait_ready(ready, worker)
            time.sleep(0.2)
            self.assertIsNone(worker.poll())
            self.assertFalse((directory / '.state').exists())
        result = json.loads(self.finish(worker))
        context = result['hookSpecificOutput']['additionalContext']
        command = context.split('Bütçeli okuma (', 1)[1].split('\n')[1]
        self.assertEqual(command, codex_hafiza.latest_session_command(self.vault))
        self.assertNotIn('latest-session .', command)
        self.assertTrue(list((directory / '.state').glob('*.json')))

    def test_command_quoting_both_shells(self):
        argv = [sys.executable, str(self.scripts / 'codex_hafiza.py'),
                '--vault', str(self.vault), 'latest-session']
        with patch.object(codex_hafiza.os, 'name', 'posix'):
            self.assertEqual(shlex.split(codex_hafiza.latest_session_command(self.vault)), argv)
        with patch.object(codex_hafiza.os, 'name', 'nt'):
            rendered = codex_hafiza.latest_session_command(self.vault)
        self.assertEqual(rendered, '& ' + ' '.join(
            "'" + arg.replace("'", "''") + "'" for arg in argv))

    def test_source_backed_local_context_and_latest_session_cli(self):
        statement = 'Örnek kullanıcı taşınabilir kilitleme testlerini tercih eder.'
        source = self.vault / 'zihin/örnek kaynak.md'
        source.write_text(statement + '\n', encoding='utf-8')
        digest = lambda text: 'sha256:' + hashlib.sha256(text.encode('utf-8')).hexdigest()
        record = dict(memory_id='synthetic-portability', kind='semantic', scope='user',
                      subject_key='test.portability', statement=statement, status='active',
                      source_path='zihin/örnek kaynak.md', source_anchor='örnek',
                      source_hash=digest(statement), source_content_hash=digest(statement + '\n'),
                      observed_at='2026-09-19', valid_from='2026-09-19', valid_to=None,
                      confidence='explicit-user', sensitivity='normal', mem0_id=None,
                      supersedes=None, reviewed_by='fixture', schema_version=1)
        (self.vault / 'zihin/hafıza-kataloğu.jsonl').write_text(
            json.dumps(record, ensure_ascii=False) + '\n', encoding='utf-8')
        output = self.run_code('import hafiza; sys.exit(hafiza.main(sys.argv[1:]))',
                               '--vault', self.vault, 'context', 'taşınabilir kilitleme')
        result = json.loads(output)
        self.assertEqual(result['mode'], 'local')
        self.assertEqual(result['memory_ids'], ['synthetic-portability'])
        self.assertIn('zihin/örnek kaynak.md', result['text'])
        self.assertEqual(result['catalog_errors'], [])
        (self.vault / 'zihin/son-oturum.md').write_text(
            '## 2026-09-19 — Güncel\nÖrnek doğrulama.\n'
            '## 2026-01-01 — Eski\nESKİ İÇERİK\n', encoding='utf-8')
        output = self.run_code('import codex_hafiza; codex_hafiza.main()',
                               '--vault', self.vault, 'latest-session')
        self.assertIn('Örnek doğrulama.', output)
        self.assertNotIn('ESKİ İÇERİK', output)
        self.assertLessEqual(len(output.strip()), 2500)
        with (self.vault / 'zihin/son-oturum.md').open('a', encoding='utf-8') as journal:
            journal.write('## 2026-09-20 — Uzun bölüm\n' + 'Taşınabilir örnek. ' * 500)
        output = self.run_code('import codex_hafiza; codex_hafiza.main()',
                               '--vault', self.vault, 'latest-session')
        self.assertIn('Kesildi', output)
        self.assertNotIn('Örnek doğrulama.', output)
        self.assertLessEqual(len(output.strip()), 2500)


if __name__ == '__main__':
    unittest.main()
