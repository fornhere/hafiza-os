#!/usr/bin/env python3
"""Source-linked project views and conservative project discovery."""
import argparse
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

import bilgi_agi
import capture_source
import client_transcripts
import gorev_baglam
import hafiza
import is_ve_ders

PROJECT_START = '<!-- hafiza-os:proje-uretilmis:basla -->'
PROJECT_END = '<!-- hafiza-os:proje-uretilmis:bitir -->'
HOME_START = '<!-- hafiza-os:ana-sayfa-projeler:basla -->'
HOME_END = '<!-- hafiza-os:ana-sayfa-projeler:bitir -->'
CANDIDATE_START = '<!-- hafiza-os:proje-adaylari:basla -->'
CANDIDATE_END = '<!-- hafiza-os:proje-adaylari:bitir -->'
OPEN = {'active', 'blocked', 'needs_confirmation'}


def _date(value):
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value / 1e9, dt.timezone.utc).date()
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).date()
    except (ValueError, TypeError):
        return None


def _safe_line(value, limit=100):
    line = re.sub(r'\s+', ' ', str(value or '')).strip()
    if (not line or hafiza.contains_secret(line) or client_transcripts.private(line)
            or line.startswith(('İŞÇİ KOŞUSU', 'ISCI KOSUSU'))):
        return '[gizlendi]'
    return line[:limit].replace('[[', '[').replace(']]', ']')


def _link(path):
    return f'[[{Path(path).with_suffix("").as_posix()}]]'


def _matches(text, project):
    lower = str(text or '').casefold()
    for alias in project.get('aliases', []):
        if alias and re.search(r'(?<!\w)' + re.escape(alias.casefold()) + r'(?!\w)', lower):
            return True
    return any(root and root.casefold() in lower for root in project.get('roots', []))


def _root_matches(cwd, project):
    if not cwd or not Path(cwd).is_absolute():
        return False
    return any(Path(cwd) == Path(root) or Path(root) in Path(cwd).parents
               for root in project.get('roots', []) if root and Path(root).is_absolute())


def _claude_cwd(path):
    parts = Path(path).parts
    if '.claude' not in parts or 'projects' not in parts:
        return ''
    index = parts.index('projects')
    if index + 1 >= len(parts):
        return ''
    encoded = parts[index + 1]
    return encoded.replace('-', '/') if encoded.startswith('-') else ''


def _claude_root_score(source_path, project):
    parts = Path(source_path).parts
    if 'projects' not in parts:
        return 0
    index = parts.index('projects')
    if index + 1 >= len(parts):
        return 0
    encoded = parts[index + 1]
    return max((len(root) for root in project.get('roots', [])
                if root and Path(root).is_absolute() and
                (encoded == root.replace('/', '-') or encoded.startswith(root.replace('/', '-') + '-'))),
               default=0)


def _receipts(vault):
    rows = []
    folder = vault / 'gelen-kutusu/codex-oturumları'
    for path in sorted(folder.glob('*.md')):
        if path.is_symlink():
            continue
        body = path.read_text(encoding='utf-8')
        first = body.splitlines()[0] if body else ''
        match = re.search(r'\d{4}-\d\d-\d\d', first)
        rows.append(dict(client='codex', path=path.relative_to(vault), text=body,
                         first=_safe_line(first), date=_date(match.group() if match else None), cwd=''))
    folder = vault / 'gelen-kutusu/ajan-oturumlari'
    for path in sorted(folder.glob('*.json')):
        state = folder / '.state' / path.name
        if path.is_symlink() or not state.is_file() or state.is_symlink():
            continue
        try:
            receipt = json.loads(path.read_text(encoding='utf-8'))
            source = json.loads(state.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if source.get('client') != 'claude' or source.get('count', 0) <= 5:
            continue
        summary = receipt.get('summary', '')
        rows.append(dict(client='claude', path=path.relative_to(vault), text=summary,
                         first=_safe_line(str(summary).splitlines()[0] if summary else ''),
                         date=_date(receipt.get('reviewed_ns') or source.get('created_ns')),
                         cwd=_claude_cwd(source.get('path', '')),
                         source_path=source.get('path', '')))
    return rows


def _replace_block(original, start, end, body):
    block = start + '\n' + body.rstrip() + '\n' + end
    if start in original and end in original:
        before, rest = original.split(start, 1)
        _, after = rest.split(end, 1)
        return before + block + after
    return original + ('' if not original or original.endswith('\n\n') else '\n' if original.endswith('\n') else '\n\n') + block + '\n'


def _put(vault, relative, start, end, body, write, heading=''):
    path = vault / relative
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('unsafe output: ' + str(relative))
    old = path.read_text(encoding='utf-8') if path.exists() else heading
    new = _replace_block(old, start, end, body)
    status = 'create' if not path.exists() else 'change' if old != new else 'same'
    if write and status != 'same':
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding='utf-8')
    return {'path': relative.as_posix(), 'action': status}


def build(vault, write=False, today=None):
    vault = Path(vault)
    today = today or dt.date.today()
    projects = gorev_baglam.config(vault).get('projects', [])
    tasks = list(is_ve_ders.latest(vault, 'task').values())
    notes, diagnostics = bilgi_agi._rows(vault)
    receipts = _receipts(vault)
    claude_scores = {str(r['path']): max((_claude_root_score(r['source_path'], p) for p in projects),
                                       default=0) for r in receipts if r['client'] == 'claude'}
    plan, summaries = [], []
    for project in projects:
        ident = project['id']
        matching_tasks = []
        for task in tasks:
            if task.get('status') not in OPEN:
                continue
            explicit = task.get('project_id')
            possible = not explicit and _matches(' '.join(str(task.get(k, '')) for k in
                ('title', 'next_step', 'source_path', 'evidence')), project)
            if explicit == ident or possible:
                matching_tasks.append((task, possible))
        matching_notes = [n for n in notes if n.get('scope') == 'project:' + ident]
        matching_receipts = [r for r in receipts if
            ((_claude_root_score(r['source_path'], project) > 0 and
              _claude_root_score(r['source_path'], project) == claude_scores[str(r['path'])])
             if r['client'] == 'claude' else _matches(r['text'], project))]
        matching_receipts.sort(key=lambda r: (r['date'] or dt.date.min, str(r['path'])), reverse=True)
        dates = [r['date'] for r in matching_receipts if r['date']]
        dates += [d for task, _ in matching_tasks if (d := _date(task.get('updated_at')))]
        last = max(dates) if dates else None
        active = bool(last and 0 <= (today - last).days <= 30)
        lines = [f'Üretim zamanı: {today.isoformat()}',
                 f'Kayıt: [[komuta/gorev-baglam]] · Takma adlar: {", ".join(project.get("aliases", [])) or "—"}',
                 'Kökler: ' + (', '.join(project.get('roots', [])) or '—'),
                 f'Durum: {"aktif" if active else "arşiv adayı"}',
                 f'Son etkinlik: {last.isoformat() if last else "bilinmiyor"}', '',
                 '### Açık işler']
        for task, possible in matching_tasks:
            source = task.get('source_path')
            link = _link(source) if source and not Path(source).is_absolute() else '[[zihin/is-durumu]]'
            lines.append(f'- {"olası · " if possible else ""}{_safe_line(task.get("title"))} ({task["status"]}) · {link}')
        if not matching_tasks:
            lines.append('- Yok')
        lines += ['', '### Bilgi notları']
        lines += [f'- [[bilgi/{n["id"]}]] · {_safe_line(n["title"])}' for n in matching_notes] or ['- Yok']
        lines += ['', '### Son oturum makbuzları']
        lines += [f'- {_link(r["path"])} · {r["date"].isoformat() if r["date"] else "tarih bilinmiyor"} · {r["first"]}'
                  for r in matching_receipts[:5]] or ['- Yok']
        relative = Path('projeler') / ident / 'DURUM.md'
        plan.append(_put(vault, relative, PROJECT_START, PROJECT_END, '\n'.join(lines), write,
                         f'# {ident} · Durum\n\n'))
        summaries.append(dict(id=ident, status='aktif' if active else 'arşiv adayı',
                              last_activity=last.isoformat() if last else None,
                              open_tasks=len(matching_tasks), notes=len(matching_notes),
                              receipts=len(matching_receipts)))
    lines = [f'Üretim zamanı: {today.isoformat()}', 'Kaynak: [[komuta/gorev-baglam]]', '']
    for status, title in [('aktif', 'Aktif projeler'), ('arşiv adayı', 'Arşiv adayları')]:
        lines += ['### ' + title]
        group = sorted((s for s in summaries if s['status'] == status),
                       key=lambda s: (s['last_activity'] or '', s['id']), reverse=True)
        lines += [f'- [[projeler/{s["id"]}/DURUM]] · {s["last_activity"] or "bilinmiyor"}' for s in group] or ['- Yok']
        lines.append('')
    plan.append(_put(vault, Path('Ana Sayfa.md'), HOME_START, HOME_END, '\n'.join(lines), write))
    return dict(files=plan, projects=summaries, diagnostics=diagnostics)


def _meaningful(text):
    text = capture_source.clean_user(text)
    return (bool(text.strip()) and not hafiza.contains_secret(text)
            and not client_transcripts.private(text)
            and not text.startswith(('İŞÇİ KOŞUSU', 'ISCI KOSUSU')))


def _candidate_root(cwd):
    path = Path(cwd)
    if not path.is_absolute() or '..' in path.parts:
        return None
    home = Path.home()
    if path == home or path == Path('/') or path.is_relative_to(Path('/tmp')) or path.is_relative_to(Path('/var/tmp')):
        return None
    if any(part.casefold() in {'scratch', 'scratchpad', 'workspaces', '.cache'} for part in path.parts):
        return None
    if path.name.casefold() in {'chatgpt', 'documents', 'projects'}:
        return None
    return path


def _native_sessions(days, now, claude_root=None, codex_root=None):
    cutoff = now - dt.timedelta(days=days)
    claude_root = Path(claude_root or Path.home() / '.claude/projects')
    codex_root = Path(codex_root or Path.home() / '.codex/sessions')
    for path in claude_root.glob('*/*.jsonl'):
        if path.is_symlink() or path.name.startswith('agent-'):
            continue
        try:
            if dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc) < cutoff:
                continue
            parsed = client_transcripts.parse('claude', path.stem, path)
            if parsed['count'] <= 5 or not parsed['terminal']:
                continue
            first = next((e['quote'] for e in parsed['entries'] if e['role'] == 'user'), '')
            if not _meaningful(first):
                continue
            dates = []
            cwd = ''
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get('type') == 'user':
                        dates.append(_date(row.get('timestamp')))
                        if isinstance(row.get('cwd'), str) and row['cwd']:
                            cwd = row['cwd']
            when = max((d for d in dates if d), default=None)
            cwd = cwd or _claude_cwd(path)
            if when and dt.datetime.combine(when, dt.time.min, dt.timezone.utc) >= cutoff - dt.timedelta(days=1):
                yield dict(cwd=cwd, date=when, first=_safe_line(first, 60), source=str(path))
        except (OSError, ValueError, UnicodeError, KeyError, TypeError):
            continue
    for path in codex_root.glob('**/*.jsonl'):
        if path.is_symlink():
            continue
        try:
            if dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc) < cutoff:
                continue
            parsed = capture_source.snapshot(path)
            if parsed['user_count'] <= 5 or parsed['activity_state'] != 'completed':
                continue
            cwd, first, when = '', '', None
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    payload = row.get('payload', {})
                    if row.get('type') == 'session_meta':
                        cwd = payload.get('cwd', '')
                    if row.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
                        text = '\n'.join(p.get('text', '') for p in payload.get('content', []) if isinstance(p, dict))
                        if _meaningful(text):
                            first = first or text
                            date = _date(row.get('timestamp'))
                            when = max((d for d in (when, date) if d), default=None)
            if first and when and dt.datetime.combine(when, dt.time.min, dt.timezone.utc) >= cutoff - dt.timedelta(days=1):
                yield dict(cwd=cwd, date=when, first=_safe_line(first, 60), source=str(path))
        except (OSError, ValueError, UnicodeError, KeyError, TypeError):
            continue


def detect(vault, days=14, write=False, now=None, sessions=None):
    if days < 1:
        raise ValueError('days must be positive')
    vault = Path(vault)
    now = now or dt.datetime.now(dt.timezone.utc)
    projects = gorev_baglam.config(vault).get('projects', [])
    grouped = defaultdict(list)
    for session in sessions if sessions is not None else _native_sessions(days, now):
        root = _candidate_root(session.get('cwd', ''))
        date = session.get('date')
        if root is None or not date or (now.date() - date).days not in range(days + 1):
            continue
        if any(_root_matches(str(root), p) for p in projects):
            continue
        grouped[root].append(session)
    # Merge sibling workspaces only below a named project directory. Generic
    # containers such as Documents and Projects must not become candidates.
    for root in sorted(list(grouped), key=lambda p: len(p.parts), reverse=True):
        parent = root.parent
        if (len(parent.parts) < 3 or parent.name.casefold() in
                {'chatgpt', 'documents', 'projects', 'work', 'code', 'repos'}
                or parent == Path.home()):
            continue
        siblings = [p for p in grouped if p.parent == parent]
        if len(siblings) > 1:
            grouped[parent] = [s for p in siblings for s in grouped.pop(p)]
    candidates = []
    for root, items in sorted(grouped.items(), key=lambda x: str(x[0])):
        unique = {item['source']: item for item in items}
        if len(unique) < 2:
            continue
        newest = max(unique.values(), key=lambda s: s['date'])
        slug = re.sub(r'[^a-z0-9]+', '-', root.name.casefold()).strip('-') or 'proje'
        candidates.append(dict(id=slug, root=str(root), sessions=len(unique),
                               last_activity=newest['date'].isoformat(),
                               example=_safe_line(newest['first'], 60)))
    result = dict(candidates=candidates)
    if write:
        lines = [f'Üretim zamanı: {now.date().isoformat()}', 'Kayıt defteri değiştirilmedi.', '']
        lines += [f'- `{c["id"]}` · `{c["root"]}` · {c["sessions"]} oturum · {c["last_activity"]} · {c["example"]}'
                  for c in candidates] or ['- Aday yok']
        result['file'] = _put(vault, Path('komuta/proje-adaylari.md'), CANDIDATE_START,
                              CANDIDATE_END, '\n'.join(lines), True, '# Proje adayları\n\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parent.parent)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('build').add_argument('--write', action='store_true')
    discovery = sub.add_parser('detect')
    discovery.add_argument('--days', type=int, default=14)
    discovery.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    result = build(args.vault, args.write) if args.command == 'build' else detect(args.vault, args.days, args.write)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
