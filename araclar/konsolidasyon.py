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
    # Claim, revalidation, promotion and terminal audit are one local transaction.
    # Inference is performed before this entry point, never under this lock.
    if apply: return h.serialized(_review)(vault, decision, True)
    return _review(vault, decision, False)


def _review(vault, decision, apply=False):
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
        result = h.promote_candidate.__wrapped__(vault, candidate['candidate_id'],
            memory_id='memory-auto-' + candidate['candidate_id'], reviewed_by=ACTOR, apply=apply)
    elif action in ('reject', 'duplicate', 'defer'):
        result = {'result': action, 'candidate_id': candidate['candidate_id']}
    else:
        raise ValueError('decision approve/reject/duplicate/defer olmalı')
    if apply:
        save_review.__wrapped__(vault, candidate['candidate_id'], action, decision)
    return result


@h.serialized
def save_review(vault, candidate_id, action, decision):
    event = {'event_type': {'approve': 'candidate.reviewed', 'reject': 'candidate.rejected',
             'duplicate': 'candidate.duplicate', 'defer': 'candidate.deferred'}[action],
             'candidate_id': candidate_id, 'actor': ACTOR,
             'at': dt.datetime.now(dt.timezone.utc).isoformat(), 'review': decision}
    h._append_jsonl(vault / h.EVENT_PATH, event)


from capture_source import clean_user, snapshot, excluded, validate_source


def sessions(vault, root, since, quiet_minutes=20, diagnostics=None):
    diagnostics = diagnostics if diagnostics is not None else []
    events = h.load_jsonl(vault / h.EVENT_PATH)
    seen = {(e.get('session_id'), e.get('source_hash')) for e in events
            if e.get('event_type') == 'session.inspected.v2'}
    legacy = {e.get('session_id') for e in events if e.get('event_type') == 'session.inspected'}
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    grouped = {}
    for directory in ('sessions', 'archived_sessions'):
        for path in (root / directory).rglob('*.jsonl'):
            if path.stat().st_mtime < since.timestamp():
                continue
            try: row = snapshot(path, completed_prefix=True)
            except (ValueError, OSError, UnicodeError) as error:
                # Subagent ownership is an intentional filter; all other failure is observable.
                if 'transcript sahibi' in str(error):
                    try:
                        first = next(json.loads(line).get('payload', {}) for line in path.read_text().splitlines()
                                     if json.loads(line).get('type') == 'session_meta')
                    except (ValueError, StopIteration, OSError): first = {}
                    if any((isinstance(first.get(field), dict) and 'subagent' in first[field])
                           or first.get(field) in ('subagent', 'agent')
                           for field in ('source', 'thread_source')): continue
                diagnostics.append({'path': str(path), 'error': str(error)})
                continue
            if row.get('parse_status') == 'malformed' or (row['activity_state'] == 'unknown' and row['user_count'] > 5):
                diagnostics.append({'path': str(path), 'error': 'unknown lifecycle or malformed transcript'})
            if excluded(vault, row['session_id']) or row['user_count'] <= 5: continue
            if (row['session_id'], row['source_hash']) in seen: continue
            row['legacy_review_needed'] = row['session_id'] in legacy
            old = grouped.get(row['session_id'])
            if old and (old['source_hash'] != row['source_hash'] or old['activity_state'] == 'ambiguous'):
                # Divergent copies are never silently resolved by mtime alone.
                row['activity_state'] = 'ambiguous'
            grouped[row['session_id']] = row
    return sorted(grouped.values(), key=lambda r: (r['activity_state'] != 'completed', r['last_modified']))[:10]


@h.serialized
def checkpoint(vault, data):
    session = data.get('session_id')
    if not session or not data.get('source_hash') or len(data.get('reason', '')) < 10:
        raise ValueError('oturum, kaynak hash ve inceleme sonucu gerekli')
    actual = snapshot(data['path'], end_line=data.get('prefix_end_line'))
    if data.get('prefix_end_line') is not None and actual['prefix_hash'] != data.get('prefix_hash'):
        raise ValueError('checkpoint prefix değişti')
    if actual['session_id'] != session or actual['source_hash'] != data['source_hash']:
        raise ValueError('checkpoint kaynak görüntüsü değişti')
    outcome = data.get('outcome')
    if outcome not in ('recorded', 'no_relevant_change', 'excluded'):
        raise ValueError('outcome recorded/no_relevant_change/excluded olmalı')
    if outcome == 'excluded':
        evidence = data.get('exclusion_evidence', '')
        from capture_source import exclusion_evidence
        if not exclusion_evidence(data['path'], evidence):
            raise ValueError('kaydetmeme isteği için kaynak kanıtı gerekli')
        h._append_jsonl(vault / h.EVENT_PATH, dict(event_type='session.policy',
            session_id=session, policy='do-not-record', actor=ACTOR,
            at=dt.datetime.now(dt.timezone.utc).isoformat()))
    else:
        validate_source(vault, session, data)
        if outcome == 'recorded':
            from codex_hafiza import paths
            expected, _ = paths(vault, session, 'recovery-v2-' + actual['source_hash'])
            if not expected.is_file(): raise ValueError('doğrulanmış recovery makbuzu gerekli')
            receipt = expected.read_text()
            if (f'<!-- codex-receipt:{expected.stem} -->' not in receipt or
                    f'<!-- capture-source:{actual["source_hash"]} -->' not in receipt or len(receipt) < 100):
                raise ValueError('recovery makbuzu kimlik/kaynak işaretleri geçersiz')
            from capture_source import digest
            data = dict(data, receipt_hash=digest(receipt), receipt_path=str(expected.relative_to(vault)))
    h._append_jsonl(vault / h.EVENT_PATH, dict(data, schema_version=2,
        event_type='session.inspected.v2', actor=ACTOR, at=dt.datetime.now(dt.timezone.utc).isoformat()))


def status(vault):
    receipts = sorted((vault / 'günlük/hafıza-makbuzları').glob('*-sync-*.json'))
    applied = [json.loads(p.read_text()) for p in receipts]
    applied = [r for r in applied if r.get('payload', {}).get('apply')]
    last = applied[-1] if applied else None
    return {'pending_candidates': len(pending(vault)),
        'missing_receipts': len(list((vault / 'gelen-kutusu/codex-oturumları').glob('*.pending.json'))),
        'last_sync': last, 'catalog_count': len(h.load_catalog(vault)),
        'lesson_backlog': __import__('ders_baglam').backlog(vault),
        'knowledge': __import__('bilgi_agi').status(vault),
        'operational_health': __import__('hafiza_saglik').snapshot(vault)}


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
        f"| İşletim durumu | {report['operational_health']['status']} |",
        f"| Katalog | {report['catalog_count']} kayıt |",
        f"| Bekleyen semantik aday | {report['pending_candidates']} |",
        f"| Eksik işaretli makbuz | {report['missing_receipts']} |",
        f"| Hook sayaç dosyası | {len(hook_states)} — sıfırsa canlı çalıştığı doğrulanmış değildir |",
        f"| Son uygulanan Mem0 senkronu | {report['last_sync']['at'] if report['last_sync'] else 'Yok'} |"]
    lines += [f"| Kaynaklı bilgi notu | {report['knowledge']['eligible']} |",
        f"| Bilgi incelemesi bekleyen kaynak | {len(report['knowledge']['unreviewed_sources'])} |",
        f"| Ertelenen bilgi kaynağı | {len(report['knowledge']['deferred_sources'])} |"]
    for check in report['operational_health']['checks']:
        lines.append(f"| {check['name']} | {check['status']}: {check['reason']} |")
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
    from hafiza_git import commit_memory
    return {'rendered': 'komuta/hafıza-sagligi.md', 'operational_health': report['operational_health'], 'git': commit_memory(vault)}



def scan_with_receipt(vault, root, since, scheduled=False):
    """Operational receipt only: no transcript or user text is persisted."""
    from codex_hafiza import atomic
    from hafiza_saglik import RUN_PATH
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    atomic(vault / RUN_PATH, json.dumps(dict(status='running', started_at=started)))
    try:
        diagnostics = []
        rows = sessions(vault, root, since, diagnostics=diagnostics)
        errors = max(len(diagnostics), sum(r.get('activity_state') in ('unknown', 'ambiguous') for r in rows))
        eligible = [r for r in rows if r.get('activity_state') == 'completed']
        oldest = min((r['last_modified'] for r in eligible), default=None)
        receipt = dict(status='complete', started_at=started, since=since.isoformat(),
            finished_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            parse_errors=errors, eligible_count=len(eligible),
            unresolved_count=sum(r.get('activity_state') != 'completed' for r in rows),
            oldest_eligible_at=dt.datetime.fromtimestamp(oldest, dt.timezone.utc).isoformat() if oldest else None)
        atomic(vault / RUN_PATH, json.dumps(receipt))
        if scheduled:
            atomic(vault / RUN_PATH.with_name("scheduled-scan.json"), json.dumps(receipt))
        return rows
    except Exception as error:
        atomic(vault / RUN_PATH, json.dumps(dict(status='failed', started_at=started,
            finished_at=dt.datetime.now(dt.timezone.utc).isoformat(), error_code=type(error).__name__)))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('pending'); sub.add_parser('status')
    p = sub.add_parser('review-pending'); p.add_argument('--project-id'); p.add_argument('--limit',type=int,default=5); p.add_argument('--apply',action='store_true')
    p = sub.add_parser('health'); p.add_argument('--check', action='store_true')
    p = sub.add_parser('review'); p.add_argument('--input-json', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('sessions'); p.add_argument('--since')
    p.add_argument('--codex-root', type=Path, default=Path.home() / '.codex')
    p.add_argument('--scheduled', action='store_true', help='Only the scheduled maintenance role uses this flag')
    p = sub.add_parser('checkpoint'); p.add_argument('--input-json', type=Path, required=True)
    args = parser.parse_args(); vault = args.vault.resolve()
    if args.cmd == 'pending': result = pending(vault)
    elif args.cmd == 'review-pending':
        from hafiza_dongusu import review_pending
        result = review_pending(vault,args.project_id,args.limit,args.apply)
    elif args.cmd == 'status': result = status(vault)
    elif args.cmd == 'health': result = health(vault)
    elif args.cmd == 'review': result = review(vault, json.loads(args.input_json.read_text()), args.apply)
    elif args.cmd == 'checkpoint': result = checkpoint(vault, json.loads(args.input_json.read_text()))
    else:
        since = (dt.datetime.fromisoformat(args.since).replace(tzinfo=dt.timezone.utc) if args.since
                 else dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=21))
        result = scan_with_receipt(vault, args.codex_root, since, scheduled=args.scheduled)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.cmd == 'health' and args.check:
        raise SystemExit({'healthy': 0, 'failed': 1, 'stale': 2, 'unknown': 3}[result['operational_health']['status']])


if __name__ == '__main__':
    main()
