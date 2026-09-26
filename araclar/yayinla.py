#!/usr/bin/env python3
"""Validate a reviewed committed tree, then optionally publish without force."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

from hafiza import SECRET_RULES


def run(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parity(repo, vault):
    manifest = json.loads((repo / 'publication-manifest.json').read_text(encoding='utf-8'))
    covered = set()
    for row in manifest['files']:
        name = row['path']; covered.add(name)
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('unsafe manifest path')
        public = repo / name; local = vault / name
        if public.is_symlink() or local.is_symlink():
            raise ValueError('symlink in shared code')
        a, b = digest(local), digest(public)
        if row['mode'] == 'shared':
            valid = a == b
        elif row['mode'] == 'reviewed-variant':
            valid = (len(row.get('reason', '')) >= 20 and a == row.get('local_sha256')
                     and b == row.get('public_sha256'))
        else:
            valid = False
        if not valid:
            raise ValueError('unreviewed local/public difference: ' + name)
    required = {p.relative_to(repo).as_posix() for p in (repo / 'araclar').glob('*.py')
                if not p.name.startswith('test_') and p.name != 'codex_kur.py'}
    if required - covered:
        raise ValueError('runtime missing from manifest: ' + ', '.join(sorted(required - covered)))


# Secret-shaped literals must not reach the public tree. Keep the historical
# self-exclusion; other source/tests must assemble synthetic examples at runtime.
SELF_PATH = 'araclar/yayinla.py'
# The legacy assignment heuristic accepts ANY non-space word, including source
# expressions/placeholders. Publication uses the shared provider/shape rules.
SECRET_PATTERNS = tuple((name, pattern) for name, pattern in SECRET_RULES
                        if name != 'legacy_assignment') + (
    ('home_path_linux', re.compile(r'/home/[A-Za-z0-9._-]+/')),
    ('home_path_macos', re.compile(r'/Users/[A-Za-z0-9._-]+/')),
)
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')


def email_allowed(address):
    # Placeholder and GitHub no-reply addresses carry no personal contact detail.
    local, _, domain = address.rpartition('@')
    local, domain = local.lower(), domain.lower()
    return (local == 'noreply' or domain == 'noreply.github.com'
            or domain.endswith('.noreply.github.com') or domain.startswith('example.'))


def findings(text):
    hits = [name for name, pattern in SECRET_PATTERNS if pattern.search(text)]
    hits += ['email:' + a for a in EMAIL_PATTERN.findall(text) if not email_allowed(a)]
    return hits


PRIVATE_TERMS_PATH = 'komuta/yayin-yasak-terimler.txt'


def private_terms(vault):
    """Private vault list of personal/channel words that must never be published.

    One case-insensitive whole-word term per line; 'izin: <path>' exempts a file.
    """
    terms, allowed = [], set()
    path = Path(vault) / PRIVATE_TERMS_PATH if vault else None
    if not path or not path.is_file():
        return {'patterns': [], 'allowed': allowed}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('izin:'):
            allowed.add(line[5:].strip()); continue
        terms.append(re.compile(r'(?<!\w)' + re.escape(line) + r'(?!\w)', re.IGNORECASE))
    return {'patterns': terms, 'allowed': allowed}


def scan(repo, names=None, private=None):
    for name in names if names is not None else run(repo, 'ls-files', '-z').split('\0'):
        if not name: continue
        path = repo / name
        if path.is_symlink() and (not path.resolve().is_relative_to(repo.resolve()) or not path.is_file()):
            raise ValueError('unsafe public symlink: ' + name)
        if Path(name).as_posix() == SELF_PATH: continue
        data = path.read_bytes()
        if b'\0' in data: continue
        text = data.decode('utf-8', errors='replace')
        found = findings(text)
        if found:
            raise ValueError('publication scan rejected file: ' + name + ' (' + found[0] + ')')
        if private and Path(name).as_posix() not in private['allowed']:
            for index, pattern in enumerate(private['patterns'], 1):
                if pattern.search(text):
                    # The term itself stays private; report only its list position.
                    raise ValueError('publication scan rejected file: ' + name + f' (private term #{index})')


def validate_committed(repo, private=None):
    if run(repo, 'status', '--porcelain'):
        raise ValueError('review and commit all publication changes first')
    head = run(repo, 'rev-parse', 'HEAD')
    archive = subprocess.check_output(['git', '-C', str(repo), 'archive', head])
    names = run(repo, 'ls-tree', '-r', '--name-only', '-z', head).split('\0')
    with tempfile.TemporaryDirectory(prefix='memory-publish-') as tmp:
        tree = Path(tmp)
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tree, filter='data')
        scan(tree, names, private)
        # Test exactly the committed source; bytecode remains only in temporary tree.
        subprocess.run(['python3', '-m', 'unittest', 'discover', '-s', 'araclar', '-p', 'test_*.py'],
                       cwd=tree, check=True)
    if run(repo, 'rev-parse', 'HEAD') != head or run(repo, 'status', '--porcelain'):
        raise ValueError('publication tree changed during validation')
    return head


def publish(repo, vault, apply=False):
    if apply and vault is None: raise ValueError('--vault required for publish parity')
    if vault: parity(repo, vault)
    head = validate_committed(repo, private_terms(vault))
    if not apply: return {'status': 'validated', 'commit': head}
    remote = run(repo, 'remote', 'get-url', 'origin')
    if not re.fullmatch(r'(https://github\.com/|git@github\.com:)[\w.-]+/[\w.-]+(?:\.git)?', remote):
        raise ValueError('origin must be reviewed GitHub repository')
    # Explicit current gh helper bypasses a stale system credential-helper path.
    config = ['-c', 'credential.helper=', '-c', 'credential.helper=!gh auth git-credential']
    subprocess.run(['gh', 'auth', 'status', '--hostname', 'github.com'], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    parity(repo, vault)
    if run(repo, 'rev-parse', 'HEAD') != head or run(repo, 'status', '--porcelain'):
        raise ValueError('publication tree changed before push')
    subprocess.run(['git', '-C', str(repo), *config, 'push', 'origin', head + ':refs/heads/main'], check=True)
    actual = run(repo, *config, 'ls-remote', 'origin', 'refs/heads/main').split()[0]
    if actual != head: raise ValueError('remote commit differs after push')
    return {'status': 'published', 'commit': head, 'remote_commit': actual}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--vault', type=Path)
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    print(json.dumps(publish(a.repo.resolve(), a.vault.resolve() if a.vault else None, a.apply)))
