#!/usr/bin/env python3
"""Review queue and missed-session inventory. No automatic model inference here."""
import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import hafiza as h

ACTOR = 'codex-consolidator'


def pending(vault):
    events = h.load_jsonl(vault / h.EVENT_PATH)
    closed = {e.get('candidate_id') for e in events if e.get('event_type') in
              ('candidate.promoted', 'candidate.rejected', 'candidate.duplicate')}
    records = h.load_catalog(vault)
    result = []
    for candidate in h.load_jsonl(vault / h.CANDIDATE_PATH):
        if candidate['candidate_id'] not in closed:
            result.append(dict(candidate, assessment=h.assess_candidate(candidate, records)))
    return result


def review(vault, decision, apply=False):
    candidates = pending(vault)
    candidate = next((c for c in candidates if c['candidate_id'] == decision['candidate_id']), None)
    if candidate is None:
        raise ValueError('aday bekleyenler arasında değil')
    if decision.get('reviewed_by') != ACTOR or len(decision.get('reason', '')) < 20:
        raise ValueError('gerçek inceleyen ve gerekçe gerekli')
    action = decision.get('decision')
    if action == 'approve':
        required = ('source_checked', 'explicit_user', 'durable', 'normal_sensitivity', 'no_semantic_duplicate')
        if not all(decision.get(k) is True for k in required):
            raise ValueError('beş inceleme koşulu olumlu olmalı')
        if candidate.get('kind') != 'semantic' or not candidate.get('evidence'):
            raise ValueError('yalnız kanıtlı semantik aday otomatik incelemeden geçebilir')
        if candidate['assessment']['result'] != 'eligible':
            raise ValueError('çelişki veya tekrar otomatik terfi edemez')
        result = h.promote_candidate(vault, candidate['candidate_id'],
            memory_id='memory-auto-' + candidate['candidate_id'], reviewed_by=ACTOR, apply=apply)
    elif action in ('reject', 'duplicate', 'defer'):
        result = {'result': action, 'candidate_id': candidate['candidate_id']}
    else:
        raise ValueError('decision approve/reject/duplicate/defer olmalı')
    if apply:
        save_review(vault, candidate['candidate_id'], action, decision)
    return result


@h.serialized
def save_review(vault, candidate_id, action, decision):
    event = {'event_type': {'approve': 'candidate.reviewed', 'reject': 'candidate.rejected',
             'duplicate': 'candidate.duplicate', 'defer': 'candidate.deferred'}[action],
             'candidate_id': candidate_id, 'actor': ACTOR,
             'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'review': decision}
    h._append_jsonl(vault / h.EVENT_PATH, event)


def clean_user(text):
    for tag in ('recommended_plugins', 'environment_context', 'permissions instructions'):
        text = re.sub(r'<' + tag + r'>.*?</' + tag + '>', '', text, flags=re.S)
    text = text.strip()
    excluded = ('# AGENTS.md instructions', '<subagent_notification', '<turn_aborted',
        '<hook_prompt', '[HAFIZA_KAPANIS]', '[HAFIZA_OTOMASYON]', '<system-reminder', '<goal>',
        '<collaboration', '<codex_internal_context', '<in-app-browser-context')
    return '' if text.startswith(excluded) else text


def sessions(vault, root, since, quiet_minutes=20):
    """Only paths/counts/hashes escape: never copy raw conversations into memory."""
    seen = {e.get('source_hash') for e in h.load_jsonl(vault / h.EVENT_PATH)
            if e.get('event_type') == 'session.inspected'}
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    grouped = {}
    for directory in ('sessions', 'archived_sessions'):
        for path in (root / directory).rglob('*.jsonl'):
            if path.stat().st_mtime < since.timestamp() or now - path.stat().st_mtime < quiet_minutes * 60:
                continue
            meta = {}; users = {}
            for raw in path.read_text(encoding='utf-8').splitlines():
                try:
                    item = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                p = item.get('payload', {})
                if item.get('type') == 'session_meta':
                    meta = p
                if item.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
                    text = clean_user('\n'.join(c.get('text', '') for c in p.get('content', []) if isinstance(c, dict)))
                    if text:
                        identity = p.get('id') or str(item.get('timestamp')) + text
                        users[identity] = text
            if meta.get('source') not in ('cli', 'vscode') or not meta.get('id'):
                continue
            if len(users) <= 5:
                continue
            digest = h.statement_hash(json.dumps(users, ensure_ascii=False, sort_keys=True))
            if digest in seen:
                continue
            row = {'session_id': meta['id'], 'path': str(path), 'user_count': len(users),
                   'source_hash': digest, 'last_modified': path.stat().st_mtime}
            old = grouped.get(meta['id'])
            if not old or old['user_count'] < row['user_count']:
                grouped[meta['id']] = row
    return sorted(grouped.values(), key=lambda r: r['last_modified'])


@h.serialized
def checkpoint(vault, data):
    if not data.get('session_id') or not data.get('source_hash') or len(data.get('reason', '')) < 10:
        raise ValueError('oturum, kaynak hash ve inceleme sonucu gerekli')
    h._append_jsonl(vault / h.EVENT_PATH, dict(data, event_type='session.inspected',
        actor=ACTOR, at=dt.datetime.now(dt.timezone.utc).isoformat()))


def status(vault):
    receipts = sorted((vault / 'günlük/hafıza-makbuzları').glob('*-sync-*.json'))
    applied = [json.loads(p.read_text()) for p in receipts]
    applied = [r for r in applied if r.get('payload', {}).get('apply')]
    last = applied[-1] if applied else None
    return {'pending_candidates': len(pending(vault)),
        'missing_receipts': len(list((vault / 'gelen-kutusu/codex-oturumları').glob('*.pending.json'))),
        'last_sync': last, 'catalog_count': len(h.load_catalog(vault))}


def health(vault):
    from codex_hafiza import atomic
    from is_ve_ders import latest, brief
    report = status(vault)
    directory = vault / 'günlük/hafıza-makbuzları'
    def last(operation):
        files = sorted(directory.glob('*-' + operation + '-*.json'))
        return json.loads(files[-1].read_text()) if files else None
    evaluation = last('eval'); audit = last('audit'); consolidation = last('consolidation')
    hook_states = list((vault / 'gelen-kutusu/codex-oturumları/.state').glob('*.json'))
    lines = ['# Hafıza sağlığı', '', 'Üretildi: ' + dt.datetime.now(dt.timezone.utc).isoformat(), '',
        '| Kontrol | Sonuç |', '|---|---|',
        f"| Katalog | {report['catalog_count']} kayıt |",
        f"| Bekleyen semantik aday | {report['pending_candidates']} |",
        f"| Eksik işaretli makbuz | {report['missing_receipts']} |",
        f"| Hook sayaç dosyası | {len(hook_states)} — sıfırsa canlı çalıştığı doğrulanmış değildir |",
        f"| Son uygulanan Mem0 senkronu | {report['last_sync']['at'] if report['last_sync'] else 'Yok'} |"]
    if evaluation:
        e = evaluation['payload']
        lines += [f"| Arama testi | {e['passed']}/{e['total']} |",
                  f"| Bağlam paketine ulaşan | {e.get('context_passed', 'ölçülmedi')}/{e['total']} |"]
    if audit:
        a = audit['payload']
        lines += [f"| Son denetim | {audit['at']} |", f"| Kayıp / fark / yetim | {len(a['missing_remote'])} / {len(a['drifted'])} / {len(a['orphan_remote_ids'])} |"]
    if consolidation:
        lines += [f"| Son konsolidasyon kontrolü | {consolidation['at']} — {consolidation['payload'].get('trigger', 'belirtilmedi')} |"]
    lines += ['', '## Gündem', '']
    for task in brief(vault): lines.append(f"- {task['title']}: {task['next_step']}")
    lines += ['', '## Prosedürel dersler', '']
    for lesson in latest(vault, 'lesson').values():
        label = lesson['status']
        if label == 'verified':
            target = vault / lesson.get('target_path', '')
            if not target.is_file() or h.statement_hash(target.read_text()) != lesson.get('target_hash'):
                label += ' (yöntem dosyası değişti; yeniden doğrula)'
        lines.append(f"- {lesson['title']} — {label}")
    lines += ['', 'Bu sayfa manuel çalıştırma ile zamanlanmış çalışmayı birbirine eşitlemez.',
        'Yeni pencere açılışı ve gerçek altıncı mesaj hook’u ayrıca canlı doğrulanmalıdır.',
        '', '[[Ana Sayfa]] · [[komuta/hafıza-konsolidasyonu]] · [[zihin/açık-işler]]']
    atomic(vault / 'komuta/hafıza-sagligi.md', '\n'.join(lines) + '\n')
    return {'rendered': 'komuta/hafıza-sagligi.md'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('pending'); sub.add_parser('status'); sub.add_parser('health')
    p = sub.add_parser('review'); p.add_argument('--input-json', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('sessions'); p.add_argument('--since', default=dt.date.today().isoformat())
    p.add_argument('--codex-root', type=Path, default=Path.home() / '.codex')
    p = sub.add_parser('checkpoint'); p.add_argument('--input-json', type=Path, required=True)
    args = parser.parse_args(); vault = args.vault.resolve()
    if args.cmd == 'pending': result = pending(vault)
    elif args.cmd == 'status': result = status(vault)
    elif args.cmd == 'health': result = health(vault)
    elif args.cmd == 'review': result = review(vault, json.loads(args.input_json.read_text()), args.apply)
    elif args.cmd == 'checkpoint': result = checkpoint(vault, json.loads(args.input_json.read_text()))
    else: result = sessions(vault, args.codex_root, dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
