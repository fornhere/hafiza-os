#!/usr/bin/env python3
"""Read-only weekly inventory of the local memory vault."""
import argparse
import datetime as dt
import json
import re
import statistics
from collections import Counter
from pathlib import Path


UTC = dt.timezone.utc
HEX_STATE = re.compile(r'[0-9a-f]{64}\.json\Z')
TERMINAL = {'candidate.promoted', 'candidate.rejected', 'candidate.duplicate'}


def rows(path):
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    result.append(item)
            except (ValueError, TypeError):
                continue
    return result


def stamp(value):
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value, UTC)
        if isinstance(value, str) and value:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def within(value, cutoff, now):
    parsed = stamp(value)
    return parsed is not None and cutoff <= parsed <= now


def recent_file(path, cutoff, now):
    try:
        return cutoff <= dt.datetime.fromtimestamp(path.stat().st_mtime, UTC) <= now
    except OSError:
        return False


def json_file(path):
    try:
        item = json.loads(path.read_text(encoding='utf-8'))
        return item if isinstance(item, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def report(vault, days=7, now=None):
    now = now or dt.datetime.now(UTC)
    cutoff = now - dt.timedelta(days=days)
    events = rows(vault / 'günlük/hafıza-olayları.jsonl')
    inspected = [e for e in events if e.get('event_type') == 'session.inspected.v2'
                 and within(e.get('at'), cutoff, now)]
    outcomes = Counter(e.get('outcome') for e in inspected)
    codex_notes = vault / 'gelen-kutusu/codex-oturumları'
    agent_notes = vault / 'gelen-kutusu/ajan-oturumlari'
    agent_state = agent_notes / '.state'
    queue = Counter()
    for path in agent_state.glob('*.json'):
        if HEX_STATE.fullmatch(path.name):
            status = json_file(path).get('status')
            if status in ('pending', 'record', 'skip', 'superseded'):
                queue[status] += 1
    capture = {
        'inspected': len(inspected),
        'outcomes': {key: outcomes[key] for key in ('recorded', 'no_relevant_change', 'excluded')},
        'unique_sessions': len({e['session_id'] for e in inspected if e.get('session_id')}),
        'new_codex_receipts': sum(recent_file(p, cutoff, now) for p in codex_notes.glob('*.md')
                                  if p.name != 'README.md'),
        'claude_queue': {key: queue[key] for key in ('pending', 'record', 'skip', 'superseded')},
        'new_claude_source_notes': sum(recent_file(p, cutoff, now) for p in agent_notes.glob('*.md')
                                       if p.name != 'README.md'),
    }

    candidates = rows(vault / 'gelen-kutusu/hafıza-adayları.jsonl')
    added = [c for c in candidates if within(c.get('created_at'), cutoff, now)]
    promoted = {e.get('candidate_id') for e in events if e.get('event_type') == 'candidate.promoted'
                and within(e.get('at'), cutoff, now)}
    closed = {e.get('candidate_id') for e in events if e.get('event_type') in TERMINAL}
    pending = [c for c in candidates if c.get('candidate_id') not in closed]
    ages = [(now - created).total_seconds() / 86400 for c in pending
            if (created := stamp(c.get('created_at'))) is not None and created <= now]
    proposals = Counter(c.get('proposed_by') or 'unknown' for c in added)
    candidate_report = {
        'added': len(added), 'proposed_by': dict(sorted(proposals.items())),
        'promoted': len(promoted), 'pending': len(pending),
        'oldest_pending_days': round(max(ages), 2) if ages else None,
    }

    catalog = rows(vault / 'zihin/hafıza-kataloğu.jsonl')
    statuses = Counter(r.get('status') for r in catalog)
    added_ids = {r.get('memory_id') for r in catalog if within(r.get('valid_from'), cutoff, now)}
    added_ids.update(e.get('memory_id') for e in events if e.get('event_type') == 'candidate.promoted'
                     and within(e.get('at'), cutoff, now))
    added_ids.discard(None)
    changed_ids = {r.get('memory_id') for r in catalog if within(r.get('valid_to'), cutoff, now)}
    changed_ids.discard(None)
    catalog_report = {
        'status': {key: statuses[key] for key in ('active', 'quarantined', 'superseded')},
        'added': len(added_ids), 'changed': len(changed_ids),
        'change_basis': 'valid_from and promotion events; valid_to for changes',
    }

    total_chars = total_turns = 0
    per_session = []
    for path in (codex_notes / '.state').glob('*.json'):
        if not recent_file(path, cutoff, now):
            continue
        data = json_file(path)
        usage = data.get('context_usage')
        turns = data.get('count')
        if not isinstance(usage, dict) or not isinstance(turns, int) or turns <= 0:
            continue
        chars = usage.get('emitted_chars')
        if not isinstance(chars, int) or chars < 0:
            continue
        total_chars += chars
        total_turns += turns
        per_session.append(chars / turns)
    context = {
        'codex_sessions': len(per_session), 'turns': total_turns,
        'emitted_chars': total_chars,
        'per_turn_mean_chars': round(total_chars / total_turns, 2) if total_turns else 0,
        'per_turn_median_chars': round(statistics.median(per_session), 2) if per_session else 0,
        'per_turn_max_chars': round(max(per_session), 2) if per_session else 0,
        'method': 'recently modified cumulative session totals; median and max use session means, not individual turns',
        'claude_context_files': sum(recent_file(p, cutoff, now) for p in agent_state.glob('context-*.json')),
    }

    task_rows = rows(vault / 'zihin/is-durumu.jsonl')
    latest = {r['id']: r for r in task_rows if r.get('id')}
    task_status = Counter(r.get('status') for r in latest.values())
    closed_tasks = {r.get('id') for r in task_rows if r.get('status') in ('done', 'cancelled')
                    and within(r.get('updated_at'), cutoff, now)}
    tasks = {
        'status': {key: task_status[key] for key in ('active', 'needs_confirmation', 'done', 'cancelled')},
        'closed_in_period': len(closed_tasks),
    }
    try:
        from konsolidasyon import status
        health = status(vault)['operational_health']['status']
    except Exception:
        health = 'unknown'
    return {
        'generated_at': now.isoformat(), 'days': days, 'period_start': cutoff.isoformat(),
        'capture': capture, 'candidates': candidate_report, 'catalog': catalog_report,
        'context': context, 'tasks': tasks, 'health': {'status': health},
    }


def markdown(data):
    capture, candidates, catalog = data['capture'], data['candidates'], data['catalog']
    context, tasks = data['context'], data['tasks']
    lines = ['# Hafıza Raporu', '', f"Üretim zamanı: {data['generated_at']}",
             f"Dönem: son {data['days']} gün · [[Ana Sayfa]]", '',
             '## Yakalama', '',
             f"- İncelenen olay: {capture['inspected']}; benzersiz oturum: {capture['unique_sessions']}",
             '- Sonuçlar: ' + ', '.join(f'{k}={v}' for k, v in capture['outcomes'].items()),
             f"- Yeni Codex makbuzu: {capture['new_codex_receipts']}; yeni Claude kaynak notu: {capture['new_claude_source_notes']}",
             '- Claude kuyruk durumu: ' + ', '.join(f'{k}={v}' for k, v in capture['claude_queue'].items()),
             '', '## Adaylar', '',
             f"- Eklenen: {candidates['added']}; terfi edilen: {candidates['promoted']}; bekleyen: {candidates['pending']}",
             '- Öneren: ' + (', '.join(f'{k}={v}' for k, v in candidates['proposed_by'].items()) or 'yok'),
             f"- En eski bekleyen (gün): {candidates['oldest_pending_days'] if candidates['oldest_pending_days'] is not None else 'bilinmiyor'}",
             '', '## Katalog', '',
             '- Durum: ' + ', '.join(f'{k}={v}' for k, v in catalog['status'].items()),
             f"- Dönemde eklenen: {catalog['added']}; değişen: {catalog['changed']}",
             '', '## Bağlam enjeksiyonu', '',
             f"- Codex oturumu: {context['codex_sessions']}; tur: {context['turns']}; gönderilen karakter: {context['emitted_chars']}",
             f"- Tur başına ortalama/medyan/maks tahmin: {context['per_turn_mean_chars']}/{context['per_turn_median_chars']}/{context['per_turn_max_chars']}",
             f"- Claude context dosyası: {context['claude_context_files']}",
             f"- Ölçüm sınırı: {context['method']}", '', '## İş defteri', '',
             '- Durum: ' + ', '.join(f'{k}={v}' for k, v in tasks['status'].items()),
             f"- Dönemde kapanan: {tasks['closed_in_period']}", '', '## Sağlık', '',
             f"- İşletim durumu: {data['health']['status']}", '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--codex-home', type=Path, default=Path('~/.codex').expanduser())
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    if args.days < 1:
        parser.error('--days pozitif olmalı')
    data = report(args.vault, args.days)
    if args.write:
        target = args.vault / 'komuta/hafıza-raporu.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown(data), encoding='utf-8')
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
