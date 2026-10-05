"""Bounded, content-free hook failures; telemetry must never break a hook.

Atomic replacement retains the last 256 events. A busy lock or I/O failure drops
telemetry rather than delaying the hook; counts are retained observations, not
an exhaustive audit. No session identifiers, paths, prompts or error messages.
"""
from collections import Counter
import datetime as dt
import json
import os
import re
from pathlib import Path
import tempfile

from client_transcripts import SourceError, safe_path
from platform_lock import exclusive_lock

PATH = Path('.cache/hook-health/events.json')
MAX_EVENTS = 256
MAX_BYTES = 131072
EVENTS = {'Stop', 'UserPromptSubmit', 'SessionStart'}
# SourceError is normally a deliberate source/privacy refusal. Only these
# operational failures are promoted to health events, never arbitrary messages.
RUNTIME_CODES = {'registry_limit', 'invalid_registry', 'invalid_registry_version',
                 'archive_lookup_limit', 'state_entry_limit'}


def error_code(error):
    if str(error) in RUNTIME_CODES:
        return str(error)
    if isinstance(error, SourceError) or str(error) == 'source_validation_failed':
        return None
    if isinstance(error, OSError):
        return 'hook_io_failed'
    return 'hook_runtime_failed'


def read_events(vault):
    path = safe_path(Path(vault) / PATH)
    if not path.exists():
        return []
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('health_size_limit')
    rows = json.loads(raw)
    if not isinstance(rows, list) or len(rows) > MAX_EVENTS:
        raise ValueError('health_schema_invalid')
    valid = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) !=
                {'at', 'client', 'event_type', 'error_code', 'installation_version'}):
            continue
        if (row['client'] not in {'claude', 'codex'} or row['event_type'] not in EVENTS
                or row['error_code'] not in RUNTIME_CODES | {'hook_io_failed', 'hook_runtime_failed'}):
            continue
        version = row['installation_version']
        if not isinstance(version, str) or not re.fullmatch(r'araclar-sha256:[0-9a-f]{64}', version):
            continue
        stamp = dt.datetime.fromisoformat(row['at'])
        if stamp.tzinfo is not None:
            valid.append(row)
    return valid


def record_failure(vault, client, event, error):
    try:
        code = error_code(error)
        if code is None or client not in {'claude', 'codex'} or event not in EVENTS:
            return
        path = safe_path(Path(vault) / PATH)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with exclusive_lock(safe_path(path.with_suffix('.lock')), timeout=0):
            try:
                rows = read_events(vault)
            except (ValueError, TypeError, KeyError):
                rows = []
            from capture_source import installation_version
            rows.append(dict(at=dt.datetime.now(dt.timezone.utc).isoformat(),
                             client=client, event_type=event, error_code=code,
                             installation_version=installation_version()))
            fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.health-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump(rows[-MAX_EVENTS:], stream, ensure_ascii=False)
                safe_path(path)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    except Exception:
        pass


def summary(vault, now=None, hours=24):
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        rows = [r for r in read_events(vault)
                if 0 <= (now - dt.datetime.fromisoformat(r['at'])).total_seconds() <= hours * 3600]
        codes = Counter(r['error_code'] for r in rows)
        stops = Counter(r['error_code'] for r in rows if r['event_type'] == 'Stop')
        return dict(total=len(rows), by_code=dict(sorted(codes.items())),
                    stop_failures=sum(stops.values()), stop_by_code=dict(sorted(stops.items())),
                    by_client=dict(sorted(Counter(r['client'] for r in rows).items())),
                    read_failed=False, retention_limit=MAX_EVENTS)
    except Exception:
        return dict(total=0, by_code={}, stop_failures=0, stop_by_code={},
                    by_client={}, read_failed=True, retention_limit=MAX_EVENTS)


def warning(vault, now=None):
    data = summary(vault, now)
    eligible = {code: count for code, count in data['by_code'].items()
                if count >= 3 or code in data['stop_by_code']}
    if not eligible:
        try:
            from client_sessions import registry_status, registry_warning
            return registry_warning(registry_status(vault))[:240]
        except Exception:
            return ''  # Capacity telemetry must never interrupt a hook.
    code = max(eligible, key=lambda c: (c in data['stop_by_code'], eligible[c], c))
    count = data['stop_by_code'].get(code, eligible[code])
    activity = 'oturum yakalama' if code in data['stop_by_code'] else 'hook çalışması'
    return (f'Hafıza uyarısı: {activity} {count} kez başarısız ({code}); '
            'bakım: python3 araclar/konsolidasyon.py status')[:240]
