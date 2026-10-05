#!/usr/bin/env python3
"""Read-only Claude/Codex skill parity; never copies, links or deletes skills.

Compares Claude's skill folder with the folders Codex reads, and with the skill
lists Codex actually injected into its recent sessions (a disabled plugin can
still be loaded). Only the skills section is parsed; no conversation text leaves
this module.
"""
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import sys

MAX_HEADER_LINES = 80
ENTRY = re.compile(r'^- ([^\s:`]+(?::[^\s:`]+)?): [^\n]*\(file: (r\d+)/([^)\n]+)\)[ \t]*$', re.M)
ROOT = re.compile(r'^- `(r\d+)` = `([^`]+)`', re.M)


def default_roots():
    home = Path.home()
    return home / '.claude/skills', [home / '.agents/skills', home / '.codex/skills'], home / '.codex/sessions'


def skill_dirs(root):
    """Direct children with SKILL.md; the child itself may be a symlink."""
    root = Path(root)
    if not root.is_dir():
        return {}
    return {p.name: p for p in sorted(root.iterdir())
            if not p.name.startswith('.') and p.is_dir() and (p / 'SKILL.md').is_file()}


def tree_hash(path):
    """Content hash of a skill folder; nested symlinked folders are not followed."""
    path = Path(path).resolve()
    digest = hashlib.sha256()
    for item in sorted(p for p in path.rglob('*') if p.is_file()):
        digest.update(item.relative_to(path).as_posix().encode() + b'\0')
        with open(item, 'rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        digest.update(b'\0')
    return digest.hexdigest()


def session_skills(sessions_root=None, session=None, limit=20):
    """[(session path, [(name, SKILL.md path)])] for the newest sessions with a skills block."""
    if session:
        candidates = [Path(session)]
    else:
        root = Path(sessions_root)
        candidates = sorted(root.glob('*/*/*/*.jsonl'), key=lambda p: p.stat().st_mtime,
                            reverse=True) if root.is_dir() else []
    found = []
    for path in candidates:
        if len(found) >= limit:
            break
        text = _skills_text(path)
        if text is None:
            continue
        roots = dict(ROOT.findall(text))
        found.append((path, [(name, Path(roots[ref]) / rel) for name, ref, rel in ENTRY.findall(text)
                             if ref in roots]))
    return found


def _skills_text(path):
    try:
        with open(path, encoding='utf-8') as stream:
            for index, line in enumerate(stream):
                if index >= MAX_HEADER_LINES:
                    return None
                if '### Skill roots' not in line:
                    continue
                for text in _strings(json.loads(line)):
                    if '### Skill roots' in text:
                        return text[text.index('### Skill roots'):]
    except (OSError, ValueError):
        return None
    return None


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _selected(name, patterns):
    return not patterns or any(fnmatch.fnmatchcase(name, p) for p in patterns)


def check(claude_root, codex_roots, sessions_root=None, session=None, patterns=(), limit=20):
    claude = {n: p for n, p in skill_dirs(claude_root).items() if _selected(n, patterns)}
    hashes = {}

    def digest(path):
        key = Path(path).resolve()
        if key not in hashes:
            hashes[key] = tree_hash(key)
        return hashes[key]

    issues = []
    codex = {}
    for root in codex_roots:
        for name, path in skill_dirs(root).items():
            codex.setdefault(name, []).append(path)
    for name, path in claude.items():
        copies = codex.get(name, [])
        if not copies:
            issues.append(dict(level='problem', code='missing_in_codex', skill=name))
            continue
        for copy in copies:
            if digest(copy) != digest(path):
                issues.append(dict(level='problem', code='content_drift', skill=name, path=str(copy)))
            elif copy.resolve() != path.resolve() and not copy.is_symlink():
                issues.append(dict(level='warning', code='copy_not_link', skill=name, path=str(copy)))

    sessions = session_skills(sessions_root, session, limit)
    loaded = {}
    for _, entries in sessions:
        groups = {}
        for name, skill_md in entries:
            base = name.split(':', 1)[-1]
            if _selected(base, patterns):
                groups.setdefault(base, []).append((name, skill_md.parent))
        for base, rows in groups.items():
            if len(rows) < 2:
                continue
            versions = {digest(folder) if folder.is_dir() else 'missing:' + str(folder)
                        for _, folder in rows}
            code = 'conflicting_versions_loaded' if len(versions) > 1 else 'duplicate_loaded'
            item = loaded.setdefault((code, base), dict(names=set(), paths=set(), sessions=0))
            item['names'].update(name for name, _ in rows)
            item['paths'].update(str(folder) for _, folder in rows)
            item['sessions'] += 1
    for (code, base), item in sorted(loaded.items(), key=lambda x: (x[0][1], x[0][0])):
        issues.append(dict(level='problem' if code == 'conflicting_versions_loaded' else 'warning',
                           code=code, skill=base, names=sorted(item['names']),
                           paths=sorted(item['paths']), sessions=item['sessions']))
    if not sessions:
        issues.append(dict(level='warning', code='codex_session_unavailable', skill=None))
    status = ('problem' if any(i['level'] == 'problem' for i in issues)
              else 'warning' if issues else 'healthy')
    return dict(status=status, claude_skills=len(claude), codex_sessions=len(sessions),
                newest_session=str(sessions[0][0]) if sessions else None, issues=issues)


MESSAGES = {
    'missing_in_codex': 'Codex klasörlerinde yok',
    'content_drift': 'Codex kopyasının içeriği Claude sürümünden farklı',
    'copy_not_link': 'içerik aynı ama bağlantı değil kopya; Claude sürümü güncellenince ayrışır',
    'conflicting_versions_loaded': 'Codex aynı skill\'in farklı içerikli sürümlerini birlikte yüklüyor',
    'duplicate_loaded': 'Codex aynı içeriği birden çok kez yüklüyor',
    'codex_session_unavailable': 'Codex oturumlarında skill listesi bulunamadı; yüklenen liste doğrulanmadı',
}


def render(result):
    lines = [f"Skill eşitliği: {result['status']} · Claude skill: {result['claude_skills']} · "
             f"incelenen Codex oturumu: {result['codex_sessions']}"]
    for issue in result['issues']:
        where = issue.get('path') or ', '.join(issue.get('paths', []))
        count = (f" [{issue['sessions']}/{result['codex_sessions']} oturum]"
                 if 'sessions' in issue else '')
        head = f"- [{issue['level']}] {issue['skill'] or '-'}: {MESSAGES[issue['code']]}{count}"
        lines.append(head + (f" ({where})" if where else ''))
    if not result['issues']:
        lines.append('- Sorun yok.')
    return '\n'.join(lines)


def main(argv=None):
    claude, codex, sessions = default_roots()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--skill', action='append', default=[],
                        help='Yalnız bu adları/kalıpları denetle (ör. "hyperframes*"); tekrarlanabilir')
    parser.add_argument('--claude-root', type=Path, default=claude)
    parser.add_argument('--codex-root', type=Path, action='append',
                        help='Codex skill klasörü; tekrarlanabilir (varsayılan: ~/.agents/skills, ~/.codex/skills)')
    parser.add_argument('--codex-sessions', type=Path, default=sessions)
    parser.add_argument('--codex-session', type=Path, help='Belirli bir Codex oturum dosyası')
    parser.add_argument('--sessions', type=int, default=20, help='İncelenecek en yeni Codex oturumu sayısı')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    result = check(args.claude_root, args.codex_root or codex, args.codex_sessions,
                   args.codex_session, args.skill, max(1, args.sessions))
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    return 1 if result['status'] == 'problem' else 0


if __name__ == '__main__':
    sys.exit(main())
