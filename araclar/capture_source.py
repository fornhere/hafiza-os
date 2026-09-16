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


def snapshot(path, completed_prefix=False, end_line=None):
    path = Path(path)
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    if not (completed_prefix or end_line is not None) and (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('transcript okuma sırasında değişti')
    lines = raw.decode('utf-8').splitlines()
    # Establish rollout ownership before examining copied history or its partial writes.
    for line in lines:
        try: first = json.loads(line)
        except json.JSONDecodeError: continue
        if first.get('type') == 'session_meta':
            meta = first.get('payload', {})
            if not main_owner(meta):
                raise ValueError('desteklenmeyen veya alt ajan transcript sahibi')
            break
    boundary = None; suffix_parse_status = "ok"
    if completed_prefix or end_line is not None:
        terminal_lines = []; malformed_lines = []
        for index, line in enumerate(lines, 1):
            try: event = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines.append(index)
                continue
            payload = event.get('payload', {})
            if event.get('type') == 'event_msg' and payload.get('type') == 'task_complete' and payload.get('turn_id'):
                terminal_lines.append(index)
        boundary = end_line if end_line is not None else (terminal_lines[-1] if terminal_lines else None)
        if boundary is not None:
            if type(boundary) is not int or boundary not in terminal_lines:
                raise ValueError('prefix sınırı gerçek task_complete olmalı')
            if any(index <= boundary for index in malformed_lines):
                raise ValueError('tamamlanmış prefix içinde bozuk JSON satırı')
            if malformed_lines: suffix_parse_status = 'malformed'
            lines = lines[:boundary]
    prefix_hash = hashlib.sha256(('\n'.join(lines)).encode()).hexdigest() if boundary else None
    owner = None; users = {}; results = []; active = set(); completed = []; malformed = False; latest_turn = None; awaiting_result = False; final_since_terminal = False
    for line in lines:
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
    if not owner or not main_owner(owner):
        raise ValueError('desteklenmeyen veya alt ajan transcript sahibi')
    state = ('unknown' if malformed else 'active' if latest_turn in active or awaiting_result
             else 'completed' if completed else 'unknown')
    # Terminal result and user content change the revision; token/commentary noise does not.
    revision = digest([owner['id'], users, results, completed])
    return dict(schema_version=2, session_id=owner['id'], path=str(path.resolve()),
        prefix_end_line=boundary, prefix_hash=prefix_hash, suffix_parse_status=suffix_parse_status,
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
    for line in Path(source['path']).read_text().splitlines():
        try: event = json.loads(line)
        except json.JSONDecodeError: continue
        payload = event.get('payload', {})
        if event.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
            text = '\n'.join(x.get('text', '') for x in payload.get('content', []) if isinstance(x, dict))
            if privacy_command(text) or privacy_ambiguous(text): raise ValueError('kaynak kullanıcı kaydetmeme isteği veya belirsiz gizlilik kapsamı içeriyor; inceleme gerekli')
    actual = snapshot(source['path'], end_line=source.get('prefix_end_line'))
    if source.get('prefix_end_line') is not None and actual['prefix_hash'] != source.get('prefix_hash'):
        raise ValueError('incelenen tamamlanmış prefix değişti')
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
    if not privacy_command(prompt): return False
    if not excluded(vault, session):
        h._append_jsonl(vault / h.EVENT_PATH, dict(event_type='session.policy',
            session_id=session, policy='do-not-record', actor='explicit-user-hook',
            at=dt.datetime.now(dt.timezone.utc).isoformat()))
    return True


def read_completed_prefix(vault, session, source):
    """Reviewer reads only this validated boundary, never an active suffix."""
    actual = validate_source(vault, session, source)
    if actual.get('prefix_end_line') is None:
        raise ValueError('sınırlı okuma için prefix snapshot gerekli')
    text = '\n'.join(Path(actual['path']).read_text().splitlines()[:actual['prefix_end_line']])
    if hashlib.sha256(text.encode()).hexdigest() != actual['prefix_hash']:
        raise ValueError('prefix okuma sırasında değişti')
    return text


def privacy_text(prompt):
    """Remove clearly quoted examples, preserving actual surrounding instructions."""
    text = clean_user(prompt).casefold()
    unquoted = re.sub(r'```.*?```|`[^`]*`|"[^"\n]*"|“[^”\n]*”', ' ', text, flags=re.S)
    unquoted = re.sub(r'^\s*>[^\n]*', ' ', unquoted, flags=re.M)
    # A standalone quote may itself be an instruction: defer instead of ignoring it.
    if not unquoted.strip(): return text
    return unquoted


def privacy_command(prompt):
    """Only explicit whole-session scope becomes a persistent exclusion policy."""
    text = privacy_text(prompt).strip().rstrip('.!')
    text = re.sub(r'^(?:(?:kanka|lütfen)[, ]+)+', '', text)
    text = re.sub(r'[, ]+lütfen$', '', text)
    return bool(re.fullmatch(
        r'(?:bu (?:oturumu|konuşmayı|sohbeti)(?: hafızaya)? (?:kaydetme|alma|saklama)'
        r'|bu (?:konuşma|sohbet) aramızda kalsın)', text))


def main_owner(meta):
    """Exec is a main conversation only with explicit user-thread ownership."""
    if not meta.get('id'): return False
    source = meta.get('source')
    # Desktop create_thread produces a standalone, user-visible task, not a
    # collaboration worker. Accept only the observed explicit metadata tuple;
    # unknown producers and subagent ownership must remain rejected.
    if meta.get('thread_source') == 'agent_created_thread':
        return source == 'vscode' and meta.get('originator') == 'Codex Desktop'
    if source == 'exec': return meta.get('thread_source') == 'user'
    return source in ('cli', 'vscode') and meta.get('thread_source', 'user') == 'user'


def validate_candidate_evidence(vault, session, source, evidence_source, evidence):
    """Bind the quoted statement to an immutable original user message."""
    if not isinstance(evidence_source, dict):
        raise ValueError('özgün kullanıcı mesajı kanıtı gerekli')
    actual = validate_source(vault, session, source)
    for field in ('session_id', 'path', 'prefix_end_line', 'prefix_hash', 'source_hash'):
        if evidence_source.get(field) != actual.get(field):
            raise ValueError('aday kanıtı kaynak snapshot ile uyuşmuyor')
    lines = read_completed_prefix(vault, session, source).splitlines()
    line = evidence_source.get('line')
    if type(line) is not int or not 1 <= line <= len(lines):
        raise ValueError('özgün kullanıcı mesaj satırı gerekli')
    item = json.loads(lines[line - 1]); p = item.get('payload', {})
    if item.get('type') != 'response_item' or p.get('type') != 'message' or p.get('role') != 'user':
        raise ValueError('kanıt özgün kullanıcı mesajı olmalı')
    text = clean_user('\n'.join(x.get('text', '') for x in p.get('content', []) if isinstance(x, dict)))
    if not text or evidence_source.get('message_hash') != digest(text):
        raise ValueError('kullanıcı mesaj hash uyuşmazlığı')
    if evidence_source.get('quote') != evidence or evidence not in text:
        raise ValueError('alıntı özgün kullanıcı mesajında yok')
    return evidence_source


def privacy_ambiguous(prompt):
    """Conservative review gate for local/unclear scope; not a session policy.

    This covers common Turkish forms, not arbitrary natural-language semantics.
    Instruction-vs-quotation and final scope still require reviewer judgment.
    """
    text = privacy_text(prompt)
    negative = r'(?:kaydetme(?:yin|yiniz|meni|ni|k|yelim)?|saklama(?:yın|manı|yalım)?|hatırlama(?:manı)?|unut|alma(?:yın|yalım)?|alınmasın|kalmasın|tutma|yazma|etmeyelim)'
    # Names of commands/errors are discussion, not imperatives. No blanket
    # exemption for a word such as "örnek" anywhere else in the request.
    text = re.sub(r'\b(?:kaydetme|hatırlama|saklama) (?:hatasını|hatası|komutu|komutunu|komutunun|işlemini|işlemi)\b', '', text)
    patterns = (
        r'\b(?:bunu|bunları|şunu|şunları|bu bilgiyi|şu bilgiyi|anlattığımı|söylediğimi|konuştuklarımızı)\b[^.!?\n]{0,90}\b'+negative+r'\b',
        r'\b(?:hafızaya|hafızanda|belleğe|bellekte|kayıt altına|not olarak)\b[^.!?\n]{0,50}\b'+negative+r'\b',
        r'\b(?:kaydetmeni|saklamanı|hatırlamanı) istemiyorum\b',
        r'\b(?:kaydedilmesin|kaydedilmesini istemiyorum|hafızaya alınmasın|aramızda kalsın)\b',
        r'^(?:\s*(?:kanka|lütfen)[, ]+)*(?:kaydetme|saklama|hatırlama)[.! ]*$',
    )
    return privacy_command(prompt) or any(re.search(pattern, text) for pattern in patterns)
