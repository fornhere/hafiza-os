#!/usr/bin/env python3
"""Append-only, source-backed task and procedural lesson ledger."""
import argparse
import datetime as dt
import json
from pathlib import Path

import hafiza as h
from codex_hafiza import atomic

TASKS = Path('zihin/is-durumu.jsonl')
LESSONS = Path('zihin/ders-durumu.jsonl')


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
    if kind == 'task':
        if data['status'] not in ('active', 'blocked', 'needs_confirmation', 'done', 'cancelled'):
            raise ValueError('geçersiz iş durumu')
        if data['status'] in ('active', 'blocked') and not data.get('next_step'):
            raise ValueError('açık işin sonraki adımı gerekli')
        if data.get('last_verified'):
            date = dt.date.fromisoformat(data['last_verified'])
            if date > dt.date.today(): raise ValueError('gelecek teyit tarihi olamaz')
    else:
        if data['status'] not in ('proposed', 'verified', 'rejected'):
            raise ValueError('geçersiz ders durumu')
        if data['status'] == 'verified':
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
    for row in latest(vault, 'task').values():
        if row['status'] not in ('active', 'blocked'): continue
        verified = row.get('last_verified')
        if not verified or (dt.date.today() - dt.date.fromisoformat(verified)).days > 14:
            continue
        result.append(row)
    return sorted(result, key=lambda r: r['updated_at'], reverse=True)[:limit]


@h.serialized
def render(vault):
    if not (vault / TASKS).exists():
        raise ValueError('Önce kaynaklı iş defteri oluştur; mevcut liste korunuyor')
    tasks = latest(vault, 'task')
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
