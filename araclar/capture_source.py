"""Versioned, local transcript snapshots. Transcript formats are not a stable API."""
import hashlib
import json
import re
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def clean_user(text):
    for tag in ('recommended_plugins', 'environment_context', 'permissions instructions', 'in-app-browser-context'):
        text = re.sub(r'<' + tag + r'(?:\s[^>]*)?>.*?</' + tag + r'>', '', text, flags=re.S)
    text = text.strip()
    if text.startswith('## My request:'):
        text = text[len('## My request:'):].strip()
    excluded = ('# AGENTS.md instructions', '<subagent_notification', '<turn_aborted',
        '<hook_prompt', '[HAFIZA_KAPANIS]', '[HAFIZA_OTOMASYON]', '<system-reminder', '<goal>',
        '<heartbeat', '<collaboration', '<codex_internal_context', '<in-app-browser-context')
    return '' if text.startswith(excluded) else text


def snapshot(path):
    path = Path(path)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('transcript okuma sırasında değişti')
    owner = None; users = {}; results = []; active = set(); completed = []; malformed = False; latest_turn = None; awaiting_result = False; final_since_terminal = False
    for line in raw.decode('utf-8').splitlines():
        try: item = json.loads(line)
        except json.JSONDecodeError:
            malformed = True; continue
        p = item.get('payload', {})
        if item.get('type') == 'session_meta' and owner is None: owner = p
        if item.get('type') == 'response_item' and p.get('type') == 'message':
            text = '\n'.join(c.get('text', '') for c in p.get('content', []) if isinstance(c, dict))
            if p.get('role') == 'user':
                text = clean_user(text)
                if text:
                    users[p.get('id') or str(item.get('timestamp')) + text] = text
                    awaiting_result = True
            elif p.get('role') == 'assistant' and (p.get('phase') == 'final_answer' or p.get('channel') == 'final'):
                results.append(text)
                final_since_terminal = True
        if item.get('type') == 'event_msg':
            turn = p.get('turn_id')
            if p.get('type') == 'task_started' and turn:
                latest_turn = turn
                active.add(turn)
            if p.get('type') == 'task_complete' and turn:
                if not final_since_terminal and isinstance(p.get('last_agent_message'), str):
                    results.append(p['last_agent_message'])
                final_since_terminal = False
                awaiting_result = False
                active.discard(turn)
                if latest_turn is None: latest_turn = turn
                if turn not in completed: completed.append(turn)
    if not owner or owner.get('source') not in ('cli', 'vscode') or not owner.get('id'):
        raise ValueError('desteklenmeyen veya alt ajan transcript sahibi')
    state = ('unknown' if malformed else 'active' if latest_turn in active or awaiting_result
             else 'completed' if completed else 'unknown')
    # Terminal result and user content change the revision; token/commentary noise does not.
    revision = digest([owner['id'], users, results, completed])
    return dict(schema_version=2, session_id=owner['id'], path=str(path.resolve()),
        user_count=len(users), parse_status='malformed' if malformed else 'ok', source_hash=revision, user_digest=digest(users),
        result_digest=digest([results, completed]), activity_state=state,
        last_completed_turn_id=completed[-1] if completed else None,
        observed_size=after.st_size, observed_mtime_ns=after.st_mtime_ns,
        last_modified=after.st_mtime)


def excluded(vault, session):
    import hafiza as h
    return any(e.get('event_type') == 'session.policy' and e.get('session_id') == session
               and e.get('policy') == 'do-not-record' for e in h.load_jsonl(vault / h.EVENT_PATH))


def validate_source(vault, session, source):
    if excluded(vault, session): raise ValueError('oturum kaydetmeme politikasıyla dışlandı')
    actual = snapshot(source['path'])
    if actual['session_id'] != session or actual['source_hash'] != source.get('source_hash'):
        raise ValueError('kaynak oturum veya revision uyuşmuyor')
    if actual['user_count'] <= 5: raise ValueError('ilk beş gerçek mesaj kaydedilmez')
    if actual['activity_state'] != 'completed': raise ValueError('tamamlanmış kaynak turu gerekli')
    return actual


def record_gate(vault, session, turn, source=None):
    from codex_hafiza import INBOX, key
    if excluded(vault, session): raise ValueError('oturum kaydetmeme politikasıyla dışlandı')
    if source is not None:
        actual = validate_source(vault, session, source)
        if turn != 'recovery-v2-' + actual['source_hash']:
            raise ValueError('recovery tur kimliği kaynak revision ile eşleşmeli')
        return actual
    if turn.startswith('recovery-'): raise ValueError('recovery kaydı source_snapshot gerektirir')
    path = vault / INBOX / '.state' / (key(session, 'state') + '.json')
    state = json.loads(path.read_text()) if path.exists() else {}
    turns = state.get('turns', [])
    if state.get('count', 0) <= 5 or turn not in turns or turns.index(turn) < 5:
        raise ValueError('kayıt için altıncı veya sonraki gerçek hook turu gerekli')


def exclusion_evidence(path, evidence):
    if len(evidence) < 10: return False
    for line in Path(path).read_text().splitlines():
        try: item = json.loads(line)
        except json.JSONDecodeError: continue
        p = item.get('payload', {})
        if item.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
            text = clean_user('\n'.join(c.get('text', '') for c in p.get('content', []) if isinstance(c, dict)))
            if evidence in text: return True
    return False


from hafiza import serialized


@serialized
def apply_prompt_policy(vault, session, prompt):
    """Conservative exact commands; nuanced privacy decisions need reviewer context."""
    import hafiza as h
    import datetime as dt
    text = clean_user(prompt).casefold().strip().rstrip('.!')
    text = re.sub(r'^kanka[, ]+', '', text)
    if text not in ('bu oturumu kaydetme', 'bu konuşmayı hafızaya kaydetme',
                    'bu oturumu hafızaya kaydetme', 'hafızaya kaydetme'):
        return False
    if not excluded(vault, session):
        h._append_jsonl(vault / h.EVENT_PATH, dict(event_type='session.policy',
            session_id=session, policy='do-not-record', actor='explicit-user-hook',
            at=dt.datetime.now(dt.timezone.utc).isoformat()))
    return True
