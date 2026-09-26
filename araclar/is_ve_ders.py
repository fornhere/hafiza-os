#!/usr/bin/env python3
"""Append-only, source-backed task and procedural lesson ledger."""
import argparse
import datetime as dt
from fnmatch import fnmatchcase
import json
from pathlib import Path, PurePosixPath

import hafiza as h
from codex_hafiza import atomic

TASKS = Path('zihin/is-durumu.jsonl')
LESSONS = Path('zihin/ders-durumu.jsonl')


STALE_DAYS = 7


def is_instruction_target(vault, path):
    if not path: return False
    path = PurePosixPath(str(path).replace('\\', '/')).as_posix().lower()
    patterns = ['claude.md', 'claude.local.md', 'agents.md', 'gemini.md', 'skill.md', '.cursorrules', 'hooks.json',
                '.claude/*', '.codex/*', '.agents/*', 'skills/*', 'hooks/*']
    try:
        config = json.loads((vault / 'komuta/talimat-dosyalari.json').read_text(encoding='utf-8'))
        extra = config.get('extra_patterns', []) if isinstance(config, dict) else []
        if isinstance(extra, list): patterns += [p.replace('\\', '/').lower() for p in extra if isinstance(p, str) and p.strip()]
    except (OSError, ValueError): pass
    return any(fnmatchcase(path, p) or fnmatchcase(path, '*/' + p) for p in patterns)


def has_user_acceptance(data):
    source = data.get('acceptance_source')
    return (data.get('verification_kind') == 'user_acceptance' and data.get('observed_result') == 'accepted'
        and isinstance(source, dict) and isinstance(source.get('session_id'), str) and bool(source['session_id'].strip())
        and isinstance(source.get('source_snapshot'), dict) and isinstance(source.get('evidence_source'), dict)
        and isinstance(source.get('evidence'), str) and len(source['evidence']) >= 10)


def validate_acceptance_source(vault, source):
    from capture_source import validate_candidate_evidence
    if (not isinstance(source, dict) or not isinstance(source.get('session_id'), str) or not source['session_id'].strip()
        or not isinstance(source.get('source_snapshot'), dict) or not isinstance(source.get('evidence_source'), dict)
        or not isinstance(source.get('evidence'), str) or len(source['evidence']) < 10):
        raise ValueError('acceptance_source_invalid')
    try:
        validate_candidate_evidence(vault, source['session_id'], source['source_snapshot'], source['evidence_source'], source['evidence'])
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError('acceptance_source_invalid') from exc


def latest(vault, kind):
    rows = h.load_jsonl(vault / (TASKS if kind == 'task' else LESSONS))
    return {r['id']: r for r in rows}


@h.serialized
def put(vault, kind, data):
    data = dict(data)
    for name in ('id', 'title', 'status', 'source_path', 'evidence', 'actor'):
        if not isinstance(data.get(name), str) or not data[name].strip():
            raise ValueError(f'{name} gerekli')
    if h.contains_secret(json.dumps(data, ensure_ascii=False)):
        raise ValueError('sır kaydedilemez')
    source = h.source_file(vault, data['source_path'])
    if len(data['evidence']) < 10 or data['evidence'] not in source.read_text():
        raise ValueError('kanıt kaynak notta aynen bulunmalı')
    data['source_content_hash'] = h.statement_hash(source.read_text())
    if kind == 'task':
        if data.get('project_id') is not None:
            registry = vault / 'komuta/gorev-baglam.json'
            try:
                projects = json.loads(registry.read_text(encoding='utf-8'))['projects']
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError('proje kayıt defteri okunamadı')
            if not isinstance(data['project_id'], str) or data['project_id'] not in {p.get('id') for p in projects}:
                raise ValueError('project_id kayıt defterinde yok')
        if data['status'] not in ('active', 'blocked', 'needs_confirmation', 'done', 'cancelled'):
            raise ValueError('geçersiz iş durumu')
        if data['status'] in ('active', 'blocked') and not data.get('next_step'):
            raise ValueError('açık işin sonraki adımı gerekli')
        if data.get('last_verified'):
            date = dt.date.fromisoformat(data['last_verified'])
            if date > dt.date.today(): raise ValueError('gelecek teyit tarihi olamaz')
        if 'outputs' in data:
            from cikti_kayit import validate_outputs
            data['outputs'] = validate_outputs(vault, data.get('project_id'), data['outputs'])
    else:
        if data['status'] not in ('proposed', 'verified', 'rejected'):
            raise ValueError('geçersiz ders durumu')
        if data['status'] == 'verified':
            if any(is_instruction_target(vault, data.get(k)) for k in ('target_path', 'method_path')):
                try:
                    if not has_user_acceptance(data): raise ValueError('acceptance_source_required')
                    validate_acceptance_source(vault, data['acceptance_source'])
                except ValueError as exc:
                    raise ValueError('talimat dosyası dersi kullanıcı kabulü gerektirir') from exc
            target = h.source_file(vault, data.get('target_path', ''))
            if data.get('target_hash') != h.statement_hash(target.read_text()):
                raise ValueError('dersin uygulandığı dosya hash ile doğrulanmalı')
            verification = h.source_file(vault, data.get('verification_path', ''))
            quote = data.get('verification_evidence', '')
            if len(quote) < 20 or quote not in verification.read_text():
                raise ValueError('test makbuzu gerekli')
    previous = latest(vault, kind).get(data['id'])
    if previous and data.pop('expected_version', None) != previous['version']:
        raise ValueError('kayıt değişmiş; mevcut sürümü okuyup expected_version ile yeniden dene')
    data.update(version=previous['version'] + 1 if previous else 1,
        updated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        evidence_hash=h.statement_hash(data['evidence']))
    h._append_jsonl(vault / (TASKS if kind == 'task' else LESSONS), data)
    return data


def brief(vault, limit=3):
    result = []
    try:
        registry = json.loads((vault / 'komuta/gorev-baglam.json').read_text(encoding='utf-8'))
        archived = {p['id'] for p in registry.get('projects', []) if p.get('status') == 'archived'}
    except (OSError, ValueError, KeyError, TypeError):
        archived = set()
    for row in latest(vault, 'task').values():
        if row['status'] not in ('active', 'blocked'): continue
        if row.get('project_id') in archived: continue
        try:
            source = h.source_file(vault, row['source_path'])
            content=source.read_text()
            if row.get('evidence', '') not in content: continue
            if row.get('source_content_hash') and row['source_content_hash'] != h.statement_hash(content): continue
        except (OSError, ValueError): continue
        verified = row.get('last_verified')
        # Kullanıcı kuralı (2026-09-24): bir haftadır teyit edilmeyen iş aktif sayılmaz.
        if not verified or (dt.date.today() - dt.date.fromisoformat(verified)).days > STALE_DAYS:
            continue
        result.append(row)
    return sorted(result, key=lambda r: r['updated_at'], reverse=True)[:limit]


@h.serialized
def render(vault):
    if not (vault / TASKS).exists():
        raise ValueError('Önce kaynaklı iş defteri oluştur; mevcut liste korunuyor')
    tasks = latest(vault, 'task')
    current_ids = {r['id'] for r in brief(vault, limit=10000)}
    tasks = {ident: dict(row, status='needs_confirmation') if row['status'] in ('active', 'blocked') and ident not in current_ids else row for ident, row in tasks.items()}
    lines = ['# Açık İşler', '', 'Kaynak: `zihin/is-durumu.jsonl`. Bu görünüm `araclar/is_ve_ders.py render` ile üretilir.',
             'Durum değişikliği deftere yeni sürüm ekler; geçmiş silinmez. Önceki liste: [[arşiv/is-listesi-oncesi]].', '']
    for statuses, title in [(('active', 'blocked'), 'Aktif İşler'), (('needs_confirmation',), 'Güncelliği teyit edilecek işler'), (('done', 'cancelled'), 'Kapanan işler')]:
        lines += ['## ' + title, '']
        for row in tasks.values():
            if row['status'] not in statuses: continue
            path = str(Path(row['source_path']).with_suffix(''))
            lines += ['### ' + row['title'], f"- Kimlik: `{row['id']}` · Durum: **{row['status']}** · Son teyit: {row.get('last_verified') or 'teyitsiz'}",
                      '- Sonraki adım: ' + row.get('next_step', 'Yok.'), f'- Kaynak: [[{path}]]', '']
    lines += ['[[Ana Sayfa]] · [[komuta/bu-hafta]]']
    atomic(vault / 'zihin/açık-işler.md', '\n'.join(lines) + '\n')
    return {'rendered': 'zihin/açık-işler.md', 'tasks': len(tasks)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='cmd', required=True)
    for kind in ('task', 'lesson'):
        p = sub.add_parser(kind); p.add_argument('--input-json', type=Path, required=True)
    sub.add_parser('brief'); sub.add_parser('render'); sub.add_parser('lessons')
    args = parser.parse_args(); v = args.vault.resolve()
    if args.cmd in ('task', 'lesson'): result = put(v, args.cmd, json.loads(args.input_json.read_text()))
    elif args.cmd == 'render': result = render(v)
    elif args.cmd == 'brief': result = brief(v)
    else: result = list(latest(v, 'lesson').values())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
