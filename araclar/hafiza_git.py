"""Commit only reviewed memory data; never push or include unrelated edits."""
import subprocess
import re
from pathlib import Path
import hafiza as h

EXACT = {'gelen-kutusu/codex-oturumları/README.md',
 'gelen-kutusu/hafıza-adayları.jsonl', 'günlük/hafıza-olayları.jsonl',
 'zihin/fayda-gozlemleri.jsonl', 'zihin/kaynak-surumleri.jsonl', 'zihin/hafıza-kataloğu.jsonl', 'zihin/is-durumu.jsonl', 'zihin/ders-durumu.jsonl',
 'zihin/açık-işler.md', 'komuta/bu-hafta.md', 'komuta/hafıza-sagligi.md'}

def allowed(name):
    p = Path(name)
    return name in EXACT or name == 'bilgi/.reviews.jsonl' or (p.parent.as_posix() == 'bilgi' and p.suffix == '.md' and (p.name == 'README.md' or re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}', p.stem))) or (len(p.parts) == 4 and p.parts[:2] == ('bilgi', '.history') and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}',p.parts[2]) and p.suffix == '.md' and re.fullmatch(r'[0-9a-f]{64}',p.stem)) or (p.parent.as_posix() == 'gelen-kutusu/codex-oturumları'
        and p.suffix == '.md' and len(p.stem) == 32
        and all(c in '0123456789abcdef' for c in p.stem))

@h.serialized
def commit_memory(vault):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(vault), *args], stderr=subprocess.PIPE).decode()
    if git('diff', '--cached', '--name-only').strip():
        raise ValueError('Git indexinde önceden hazırlanmış değişiklik var; otomatik commit ertelendi.')
    names = set(git('diff', '--name-only', '-z').split('\0'))
    names.update(git('ls-files', '--others', '--exclude-standard', '-z').split('\0'))
    selected = sorted(n for n in names if allowed(n))
    for name in selected:
        p = vault / name
        if p.is_symlink() or not p.is_file():
            raise ValueError('Silme veya sembolik bağ otomatik commit edilmez: ' + name)
        if h.contains_secret(p.read_text()):
            raise ValueError('Sır taraması commit işlemini durdurdu: ' + name)
    # Timestamp-only health refreshes do not create an hourly Git commit.
    if not set(selected) - {'komuta/hafıza-sagligi.md'}:
        return {'status': 'unchanged'}
    git('add', '--', *selected)
    git('commit', '--only', '-m', 'Anlamlı hafıza kayıtlarını ve iş durumunu kaydet', '--', *selected)
    return {'status': 'committed', 'commit': git('rev-parse', 'HEAD').strip(), 'files': len(selected)}
