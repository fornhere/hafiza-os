#!/usr/bin/env python3
"""İncelenmiş makbuzlardan Obsidian görünümü üretir; varsayılan dry-run.

Kanıtlar ve .state yalnız okunur. Transcript, hafıza kuyruğu ve Mem0 kullanılmaz.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata

from client_transcripts import SourceError, private, read_bytes, safe_path, strict_json
from hafiza import contains_secret
from platform_lock import exclusive_lock

INBOX = Path('gelen-kutusu/ajan-oturumlari')
OUTPUT = Path('günlük/oturumlar')
INDEX = OUTPUT / 'Oturum Kayıtları.md'
PROJECT_MAPPING = OUTPUT / '.proje-eslemesi.json'
HOME_LINK = '[[günlük/oturumlar/Oturum Kayıtları]]'
IDENT = re.compile(r'[a-f0-9]{64}')


def read_text(path):
    return read_bytes(path, 2 * 1024 * 1024).decode('utf-8')


def load(path):
    value = strict_json(read_bytes(path, 2 * 1024 * 1024))
    if not isinstance(value, dict):
        raise SourceError('invalid_object')
    return value


def write_text(path, text):
    """Atomik yazım; yalnız render'ın belirlediği hedeflerde kullanılır."""
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix='.render-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text)
        safe_path(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def normalize(text):
    return unicodedata.normalize('NFKC', text).casefold().replace('i\u0307', 'i')


def short_title(summary):
    # Noktalama, Obsidian link ayraçları ve platforma özgü yasak karakterler yok.
    words = re.findall(r'[^\W_]+(?:[-’\'][^\W_]+)*', summary, re.UNICODE)
    if len(words) < 4:
        words = ['Oturum', 'kayıt', 'özeti', *words] if words else ['İncelenen', 'oturum', 'kaydının', 'özeti']
    title = ' '.join(word.encode('utf-8')[:24].decode('utf-8', errors='ignore') for word in words[:7])
    return title.encode('utf-8')[:170].decode('utf-8', errors='ignore').rstrip(' .')


def project_catalog(vault):
    config = vault / 'komuta/gorev-baglam.json'
    definitions = load(config).get('projects', []) if config.exists() else []
    projects = {}
    for item in definitions:
        if isinstance(item, dict) and isinstance(item.get('id'), str):
            projects[item['id']] = item
    root = vault / 'projeler'
    if root.exists():
        for folder in sorted(root.iterdir()):
            safe_path(folder)
            if folder.is_dir():
                projects.setdefault(folder.name, {'id': folder.name})
    centers = {}
    preferred = ('ana', 'ana sayfa', 'oku', 'index', 'readme', 'durum')
    for ident in projects:
        if not re.fullmatch(r'[\w-]+', ident):
            continue
        folder = safe_path(root / ident)
        if not folder.is_dir():
            continue
        notes = sorted(folder.glob('*.md'))
        for name in (*preferred, normalize(ident)):
            matches = [p for p in notes if normalize(p.stem) == name]
            if len(matches) == 1:
                safe_path(matches[0])
                centers[ident] = matches[0].relative_to(vault).with_suffix('').as_posix()
                break
    return projects, centers


def project_ids(receipt, projects):
    candidates = receipt.get('semantic_candidates', [])
    explicit = set()
    for candidate in candidates if isinstance(candidates, list) else []:
        if not isinstance(candidate, dict) or candidate.get('status') == 'rejected':
            continue
        scope = candidate.get('scope', '')
        if isinstance(scope, str) and re.fullmatch(r'project:[\w-]+', scope):
            explicit.add(scope.split(':', 1)[1])
    if explicit:
        return sorted(explicit), 'scope'
    summary = normalize(receipt['summary'])
    matched = set()
    for ident, project in projects.items():
        names = {normalize(ident), normalize(ident.replace('-', ' '))}
        aliases = project.get('aliases', [])
        aliases = [normalize(a) for a in aliases if isinstance(a, str)] if isinstance(aliases, list) else []
        if ident == 'dizi':
            # projeler/OKU'daki komedi projesi: tweet dizisi aynı proje değildir.
            names = {'ai dizi', 'ai-dizi', 'dizi projesi', 'mahalle komedisi', 'garabetler'}
        def mentions(term):
            return len(term) >= 3 and re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', summary) is not None
        # Tek genel anahtar kelime (kapak, maskot vb.) yeterli değildir.
        hits = {a for a in aliases if mentions(a)}
        if any(mentions(n) for n in names) or any(' ' in a or '-' in a for a in hits) or len(hits) >= 2:
            matched.add(ident)
    # Birden çok proje adı geçmesi, bu oturumun hepsine ait olduğunu kanıtlamaz.
    return (sorted(matched), 'summary') if len(matched) == 1 else ([], 'ambiguous' if matched else 'none')


def manual_project_mapping(vault, centers):
    """Elle verilen liste (boş olsa da) otomatik eşlemenin yerine geçer."""
    path = safe_path(vault / PROJECT_MAPPING)
    if not path.exists():
        return {}
    mapping = load(path)
    # Bozuk dosyada render'ı durdur; mevcut görünümleri kısmen yenileme.
    for ident, names in mapping.items():
        if (not IDENT.fullmatch(ident) or not isinstance(names, list) or
                any(not isinstance(name, str) for name in names)):
            raise SourceError('invalid_project_mapping')
    valid = {}
    for ident, names in mapping.items():
        valid[ident] = sorted({name for name in names if name in centers})
        for name in sorted(set(names) - centers.keys()):
            print('oturum_gorunumu: proje merkezi olmayan elle eşleme yok sayıldı: '
                  + ident + ' / ' + json.dumps(name, ensure_ascii=False), file=sys.stderr)
    return valid


def policy_blocked(item):
    return bool(item.get('excluded') or item.get('privacy') or item.get('privacy_blocked') or
                item.get('policy') in ('do-not-record', 'do_not_record', 'excluded', 'privacy', 'private') or
                item.get('status') in ('excluded', 'privacy_blocked'))


def user_statements(receipt, note):
    blocks = []
    # semantic_note'ın açık kullanıcı beyanı bölümleri; özet ikinci kez alınmaz.
    for match in re.finditer(r'^## Kullanıcı beyanı[^\n]*\n(.*?)(?=^## |\Z)', note, re.M | re.S):
        if match.group(1).strip():
            blocks.append(match.group(1).strip())
    for candidate in receipt.get('semantic_candidates', []):
        if not isinstance(candidate, dict) or candidate.get('status') == 'rejected':
            continue
        for field in ('statement', 'evidence'):
            value = candidate.get(field)
            if isinstance(value, str) and value.strip() and not any(value.strip() in b for b in blocks):
                blocks.append(value.strip())
    return blocks


def frontmatter_id(text):
    if not text.startswith('---\n'):
        return None
    header = text.split('\n---', 1)[0]
    match = re.search(r'^oturum_id:\s*(.*?)\s*$', header, re.M)
    if match:
        value = match.group(1).strip('"\'')
        if IDENT.fullmatch(value):
            return value
    return None


def plan(vault):
    root = safe_path(vault / INBOX)
    if not root.is_dir():
        raise SourceError('missing_receipt_directory')
    output = safe_path(vault / OUTPUT)
    state = safe_path(root / '.state')
    projects, centers = project_catalog(vault)
    manual_projects = manual_project_mapping(vault, centers)
    policies = set()
    if state.exists():
        for path in sorted(state.glob('context-*.json')):
            policy = load(path)
            if policy_blocked(policy):
                policies.add((policy.get('client'), policy.get('session')))
    existing, occupied = {}, set()
    if output.exists():
        for path in sorted(output.glob('*.md')):
            content = read_text(path)
            occupied.add(normalize(path.name))
            ident = frontmatter_id(content)
            if ident:
                if ident in existing:
                    raise SourceError('duplicate_view_id')
                existing[ident] = path
    changes, sessions, skipped, missing = [], [], [], Counter()
    distribution, matching = Counter(), Counter()
    linked_notes = 0
    sources = sorted(root.glob('*.json'))
    for path in sources:
        ident = path.stem
        try:
            if not IDENT.fullmatch(ident):
                raise SourceError('invalid_record_filename')
            receipt = load(path)
            if receipt.get('decision') != 'record':
                raise SourceError('decision_not_record')
            if receipt.get('meaningful') is not True:
                raise SourceError('not_meaningful')
            if receipt.get('id') != ident or not isinstance(receipt.get('summary'), str) or not receipt['summary'].strip():
                raise SourceError('invalid_record')
            registry_path = safe_path(state / (ident + '.json'))
            registry = load(registry_path) if registry_path.exists() else {}
            client = receipt.get('client') or registry.get('client')
            session = receipt.get('session') or registry.get('session')
            if policy_blocked(receipt) or policy_blocked(registry) or (client, session) in policies:
                raise SourceError('excluded_privacy')
            reviewed = receipt.get('reviewed_ns')
            if type(reviewed) is not int or reviewed <= 0:
                raise SourceError('invalid_date')
            # Yerel saat; ns değerini tam saniyeye indirerek sınır yuvarlamasını önle.
            date = datetime.fromtimestamp(reviewed // 1_000_000_000).astimezone().date().isoformat()
            title = short_title(receipt['summary'])
            if ident in manual_projects:
                project_list, method = manual_projects[ident], 'manual'
            else:
                project_list, method = project_ids(receipt, projects)
            source_note = safe_path(path.with_suffix('.md'))
            statements = user_statements(receipt, read_text(source_note) if source_note.exists() else '')
            scalar = lambda value: json.dumps(value, ensure_ascii=False)
            lines = ['---', 'oturum_id: ' + scalar(ident), 'tarih: ' + scalar(date)]
            if isinstance(client, str) and client:
                lines.append('istemci: ' + scalar(client))
            lines += ['projeler: ' + scalar(project_list), 'tur: oturum-kaydi', 'kanonik: false', '---', '',
                      '# ' + title, '', 'Türetilmiş oturum görünümü; kanonik kayıt değildir.', '',
                      '## Özet', '', receipt['summary'].strip(), '']
            if statements:
                lines += ['## Kullanıcı beyanları', '', '\n\n'.join(statements), '']
            if source_note.exists():
                lines += [f'Kaynak: [[{INBOX.as_posix()}/{ident}]]', '']
            else:
                lines += [f'Kaynak: [{ident}.json](../../{INBOX.as_posix()}/{ident}.json)', '']
            linked = [p for p in project_list if p in centers]
            if linked:
                lines += ['Proje merkezi: ' + ' · '.join(f'[[{centers[p]}]]' for p in linked), '']
            lines += [f'Günlük merkezi: {HOME_LINK}', '']
            text = '\n'.join(lines)
            if contains_secret(text):
                raise SourceError('secret_pattern')
            if private(receipt['summary']) or any(private(s) for s in statements):
                raise SourceError('privacy_text')
            target = existing.get(ident)
            if target is None:
                basename = date + ' ' + title
                target = output / (basename + '.md')
                if normalize(target.name) in occupied:
                    # Önceden ayrılmış adları koru; id öneki de çakışırsa uzat.
                    for size in range(8, 65, 4):
                        target = output / (basename + ' ' + ident[:size] + '.md')
                        if normalize(target.name) not in occupied:
                            break
                    else:
                        raise SourceError('filename_collision')
                occupied.add(normalize(target.name))
            safe_path(target)
            sessions.append((date, target, ident))
            for project in project_list:
                if project not in centers:
                    missing[project] += 1
            distribution.update(linked)
            linked_notes += bool(linked)
            matching[method] += 1
            changes.append((target, text))
        except (SourceError, UnicodeError, ValueError, OverflowError, OSError, TypeError) as error:
            reason = str(error) if isinstance(error, SourceError) else 'invalid_or_unreadable_record'
            skipped.append({'id': ident, 'reason': reason})
    eligible = {ident for _, _, ident in sessions}
    # Sonradan dışlanan kayıt eski görünümde veya dizinde de kalmamalı.
    removals = [path for ident, path in existing.items() if ident not in eligible]
    lines = ['---', 'tur: oturum-dizini', 'kanonik: false', '---', '', '# Oturum Kayıtları', '',
             'İnceleme kayıtlarından türetilmiş görünüm; kanonik değildir.', '', '[[Ana Sayfa]]', '']
    months = defaultdict(list)
    for date, path, ident in sessions:
        months[date[:7]].append((date, path, ident))
    for month in sorted(months, reverse=True):
        lines += ['## ' + month, '']
        for date, path, ident in sorted(months[month], key=lambda s: (s[0], s[2]), reverse=True):
            lines.append('- [[' + path.relative_to(vault).with_suffix('').as_posix() + ']]')
        lines.append('')
    changes.append((vault / INDEX, '\n'.join(lines)))
    home = safe_path(vault / 'Ana Sayfa.md')
    home_text = read_text(home) if home.exists() else ''
    if not re.search(r'\[\[günlük/oturumlar/Oturum Kayıtları(?:\|[^\]]*)?\]\]', home_text):
        changes.append((home, home_text + ('' if not home_text or home_text.endswith('\n') else '\n') + '- ' + HOME_LINK + '\n'))
    actions = []
    for path, text in changes:
        exists = path.exists()
        action = 'unchanged' if exists and read_text(path) == text else 'update' if exists else 'create'
        actions.append({'path': path.relative_to(vault).as_posix(), 'action': action})
    actions += [{'path': p.relative_to(vault).as_posix(), 'action': 'remove'} for p in removals]
    view_actions = Counter(a['action'] for a in actions if a['path'].startswith(OUTPUT.as_posix() + '/') and a['path'] != INDEX.as_posix())
    return changes, removals, {'records': len(sources), 'notes': len(sessions),
        'linked_notes': linked_notes,
        'projects': dict(sorted(distribution.items())), 'matching': dict(sorted(matching.items())),
        'missing_centers': dict(sorted(missing.items())), 'skipped': skipped,
        'skip_reasons': dict(sorted(Counter(s['reason'] for s in skipped).items())),
        'view_actions': dict(view_actions), 'actions': actions}


def render(vault, apply=False):
    vault = safe_path(Path(vault).absolute())
    def perform():
        changes, removals, report = plan(vault)
        if apply:
            for (path, text), action in zip(changes, report['actions']):
                if action['action'] != 'unchanged':
                    write_text(path, text)
            for path in removals:
                safe_path(path).unlink()
        return dict(report, mode='apply' if apply else 'dry-run')
    if not apply:
        return perform()
    output = safe_path(vault / OUTPUT)
    output.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(safe_path(output / '.render.lock'), timeout=10):
        return perform()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['render'])
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(render(args.vault, args.apply), ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        diagnostic = str(error) if isinstance(error, SourceError) else type(error).__name__
        print('oturum_gorunumu: ' + diagnostic, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
