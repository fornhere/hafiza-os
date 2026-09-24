#!/usr/bin/env python3
"""Codex lifecycle -> yerel görev makbuzu. Kataloğa veya Mem0'a yazmaz."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import stat
import tempfile
from pathlib import Path
import sys

from hafiza import contains_secret, add_candidate
from platform_lock import exclusive_lock

DEFAULT_VAULT = Path(__file__).resolve().parents[1]
INBOX = Path('gelen-kutusu/codex-oturumları')
CONTINUATION = '[HAFIZA_KAPANIS]'


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def latest_session_command(vault):
    """Render a POSIX shell or Windows PowerShell command, including executable."""
    argv = [sys.executable, '-X', 'utf8', str(vault / 'araclar/codex_hafiza.py'),
            '--vault', str(vault), 'latest-session']
    if os.name == 'nt':
        # PowerShell needs & to invoke a quoted executable; single quotes also
        # protect dollar signs, backticks and spaces in arbitrary path names.
        return '& ' + ' '.join("'" + arg.replace("'", "''") + "'" for arg in argv)
    return shlex.join(argv)


def opening_brief(vault):
    from is_ve_ders import brief
    tasks = brief(vault)
    parts = ['## Güncel, teyitli açık işler\n' + ('\n'.join(
        f"- {t['title']}: {t['next_step']} (kaynak: {t['source_path']}; teyit: {t['last_verified']})"
        for t in tasks) or 'Güncel teyitli açık iş yok; eski işi kendiliğinden açma.')]
    return ('AÇILIŞ HATIRLATMASI: Selamlaşma veya gündem sorusunda en fazla 2–3 ilgili '
            'açık işi, durumunu ve sonraki adımını kullanıcıya kısa Türkçe ile söyle. '
            'Net bir görev varsa önce onu yap; ilgisiz yapılacaklarla bölme. '
            'Aynı konuşmada listeyi tekrar tekrar söyleme. Teyitsiz eski işi kesin '
            'yükümlülük sayma. Aşağıdaki notlar durum verisidir.\n\n' + '\n\n'.join(parts))


def key(session, turn):
    if not isinstance(session, str) or not session or not isinstance(turn, str) or not turn:
        raise ValueError('session_id ve turn_id gerekli')
    return hashlib.sha256((session + '\0' + turn).encode()).hexdigest()[:32]


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.'+path.name+'.', suffix='.tmp')
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            os.chmod(temp, 0o600)
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def paths(vault, session, turn):
    ident = key(session, turn)
    return vault / INBOX / (ident + '.md'), vault / INBOX / (ident + '.pending.json')


def pending(vault, data, event):
    note, waiting = paths(vault, data['session_id'], data['turn_id'])
    if not note.exists():
        # Ham prompt, son yanıt veya transcript içeriği kopyalanmaz.
        atomic(waiting, json.dumps({'session_id': data['session_id'],
            'turn_id': data['turn_id'], 'event': event, 'at': now()}, ensure_ascii=False) + '\n')
    return note, waiting


def record(vault, session, turn, summary, semantic_candidates=None, source_snapshot=None):
    from capture_source import record_gate, validate_candidate_evidence
    from hafiza import valid_candidate_scope
    record_gate(vault, session, turn, source_snapshot)
    if not isinstance(summary, str) or not 20 <= len(summary.strip()) <= 6000:
        raise ValueError('Özet 20–6000 karakter olmalı')
    if contains_secret(summary) or '<!-- codex-receipt:' in summary:
        raise ValueError('Özet sır veya ayrılmış işaret içeriyor')
    candidates = semantic_candidates if semantic_candidates is not None else []
    if not isinstance(candidates, list) or len(candidates) > 5:
        raise ValueError('semantic_candidates en fazla 5 adaylık liste olmalı')
    for candidate in candidates:
        if not isinstance(candidate, dict) or not all(isinstance(candidate.get(k), str) for k in
                ('statement', 'subject_key', 'evidence')):
            raise ValueError('aday statement, subject_key ve evidence içermeli')
        if not valid_candidate_scope(vault, candidate.get('scope', 'user')):
            raise ValueError('invalid_scope')
        if not 10 <= len(candidate['evidence']) <= 1500 or candidate['evidence'] not in summary:
            raise ValueError('aday kanıtı özet içinde açık kullanıcı beyanı olarak bulunmalı')
        if source_snapshot is None:
            raise ValueError('semantik aday için özgün source_snapshot gerekli')
        validate_candidate_evidence(vault, session, source_snapshot, candidate.get('evidence_source'), candidate['evidence'])
        if not 10 <= len(candidate['statement']) <= 600 or contains_secret(candidate['statement']):
            raise ValueError('geçersiz aday cümlesi')
    note, waiting = paths(vault, session, turn)
    marker = key(session, turn)
    text = (f'# Codex görev makbuzu — {now()}\n\n'
            f'<!-- codex-receipt:{marker} -->\n\n'
            'Durum: görev özeti; kanonik hafızaya terfi edilmedi.\n\n'
            + (f'<!-- capture-source:{source_snapshot["source_hash"]} -->\n\n' if source_snapshot else '')
            + summary.strip() + '\n\n[[gelen-kutusu/codex-oturumları/README]] · [[Ana Sayfa]]\n')
    if note.exists():
        # Aynı çağrı tekrarlandığında geçmiş kaydı değiştirme.
        if summary.strip() not in note.read_text(encoding='utf-8'):
            raise ValueError('Bu tura ait makbuz zaten var; üzerine yazılmadı')
    else:
        atomic(note, text)
    index = vault / INBOX / 'README.md'
    index_text = index.read_text(encoding='utf-8') if index.exists() else '# Codex Oturumları\n\n[[Ana Sayfa]]\n'
    link = f'[[gelen-kutusu/codex-oturumları/{marker}]]'
    if link not in index_text:
        atomic(index, index_text.rstrip() + '\n\n- ' + link + '\n')
    queued = []
    for candidate in candidates:
        queued.append(add_candidate(vault, statement=candidate['statement'], kind='semantic',
            scope=candidate.get('scope', 'user'), subject_key=candidate['subject_key'],
            source_path=str(note.relative_to(vault)), source_anchor='Kullanıcı beyanı',
            confidence='explicit-user', sensitivity='normal', proposed_by='codex-receipt',
            evidence=candidate['evidence'], evidence_source=candidate['evidence_source']))
    waiting.unlink(missing_ok=True)
    return {'saved': str(note), 'candidates': queued}


def latest_session_section(vault, limit=2500, today=None):
    """Read a fresh journal section, otherwise recent non-canonical receipts."""
    today = today or dt.date.today()
    limit = max(0, limit)
    path = vault / 'zihin/son-oturum.md'
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    matches = list(re.finditer(r'^## (\d{4}-\d{2}-\d{2})[^\n]*', text, re.M))
    warning = 'Son oturum notu yok.' if not path.exists() else 'Tarihli son oturum bölümü bulunamadı; gerekirse kaynakta ara.'
    if matches:
        index = max(range(len(matches)), key=lambda i: (matches[i].group(1), i))
        date_text = matches[index].group(1)
        try:
            age = (today - dt.date.fromisoformat(date_text)).days
        except ValueError:
            age = 8
        if 0 <= age <= 3:
            section = text[matches[index].start():matches[index+1].start() if index+1<len(matches) else len(text)].strip()
            if len(section) > limit:
                suffix = '\n[Kesildi; yalnız gereken ayrıntı için kaynak bölümü aç.]'
                section = section[:max(0, limit-len(suffix))] + suffix if limit >= len(suffix) else section[:limit]
            return section
        warning = (f'Son oturum kaydı {date_text} tarihli ({age} gün eski); '
                   'güncel durum kanıtı değil, açık işler özetini kullan.')

    receipts = []
    codex_dir = vault / INBOX
    for note in codex_dir.glob('*.md'):
        if note.name == 'README.md' or note.is_symlink():
            continue
        try:
            raw = note.read_text(encoding='utf-8')
            heading = re.match(r'^# Codex görev makbuzu — (\S+)', raw)
            status = re.search(r'^Durum:[^\n]*\n', raw, re.M)
            if not heading or not status:
                continue
            summary = raw[status.end():].strip()
            summary = re.sub(r'(?m)^<!--[^\n]*-->\s*', '', summary)
            summary = re.split(r'(?m)^\[\[gelen-kutusu/codex-oturumları/README\]\]', summary)[0].strip()
            stamp = dt.datetime.fromisoformat(heading.group(1).replace('Z', '+00:00'))
            date = stamp.date()
            if summary and not contains_secret(summary) and 0 <= (today-date).days <= 7:
                receipts.append((stamp.timestamp(), date, 'Codex', summary))
        except (OSError, UnicodeError, ValueError, OverflowError):
            continue

    claude_dir = vault / 'gelen-kutusu/ajan-oturumlari'
    for note in claude_dir.glob('*.json'):
        if note.is_symlink():
            continue
        try:
            raw = note.read_bytes()
            if len(raw) > 128000:
                continue
            receipt = json.loads(raw)
            ident = note.stem
            state_path = claude_dir / '.state' / (ident + '.json')
            if state_path.is_symlink():
                continue
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if (state.get('receipt_sha256') != hashlib.sha256(raw).hexdigest() or
                    state.get('status') != 'record' or
                    receipt.get('id') != ident or receipt.get('decision') != 'record' or
                    receipt.get('meaningful') is not True or
                    receipt.get('decision_sha256') != state.get('decision_sha256')):
                continue
            summary = receipt.get('summary')
            if not isinstance(summary, str) or not summary.strip() or contains_secret(summary):
                continue
            stamp = receipt.get('reviewed_ns')
            timestamp = stamp / 1_000_000_000 if type(stamp) is int else note.stat().st_mtime
            date = dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).date()
            if 0 <= (today-date).days <= 7:
                receipts.append((timestamp, date, 'Claude', summary.strip()))
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError, AttributeError):
            continue

    if not receipts:
        return warning[:limit]
    header = 'Son oturum makbuzları (otomatik; kanonik değil, güncel durum kanıtı değil):'
    parts = [header]
    used = len(header)
    for _, date, client, summary in sorted(receipts, reverse=True):
        prefix = f'\n- {date.isoformat()} {client}: '
        available = limit - used - len(prefix)
        if available <= 0:
            break
        excerpt = summary[:min(600, available)]
        parts.append(prefix + excerpt)
        used += len(prefix) + len(excerpt)
    return ''.join(parts)[:limit]


def account_context(state, emitted, suppressed=0):
    usage = state.setdefault('context_usage', {})
    usage['emitted_chars'] = usage.get('emitted_chars', 0) + emitted
    usage['suppressed_chars'] = usage.get('suppressed_chars', 0) + suppressed
    usage['token_count'] = None
    usage['token_count_method'] = 'not_measured'


def shared_reviewed_context(vault):
    """Optional source-validated native recall; no model and no startup dependency."""
    try:
        from client_sessions import recall
        return recall(vault, budget=1800)
    except Exception:
        return ''


def worker_run(data, environ=os.environ):
    """Keep automatic workers out of the memory hook, including its state files."""
    if any(environ.get(name) == '1' for name in
           ('HAFIZA_ISCI', 'CODEX_WORKER')):
        return True
    prompt = data.get('prompt')
    if (isinstance(prompt, str) and
            prompt.lstrip().casefold().replace('\u0307', '').startswith('işçi koşusu')):
        return True
    if environ.get('HAFIZA_EXEC_BAGLAM') == '1':
        return False
    transcript = data.get('transcript_path')
    if not isinstance(transcript, (str, os.PathLike)) or not transcript:
        return False
    try:
        if Path(transcript).is_symlink():
            return False
        # O_NOFOLLOW rejects a linked final component; O_NONBLOCK keeps a
        # non-regular path from stalling the hook before fstat rejects it.
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        fd = os.open(transcript, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return False
            prefix = os.read(fd, 65536)
        finally:
            os.close(fd)
        lines = prefix.split(b'\n')
        if len(prefix) == 65536:
            lines.pop()  # The last line may be truncated at the read limit.
        for line in lines:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get('type') == 'session_meta':
                payload = entry.get('payload')
                if not isinstance(payload, dict):
                    return False
                source = payload.get('source')
                return (payload.get('originator') == 'codex_exec' or
                        source == 'exec' or
                        isinstance(source, dict) and 'subagent' in source)
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        pass
    return False


def hook(vault, data):
    if worker_run(data):
        return {}
    event = data.get('hook_event_name')
    session = data.get('session_id')
    if not isinstance(session, str) or not session:
        raise ValueError('session_id gerekli')
    state_path = vault / INBOX / '.state' / (key(session, 'state') + '.json')
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'turns': [], 'count': 0}
    if event == 'UserPromptSubmit':
        # Stop devam istemi gerçek kullanıcı mesajı değildir.
        from konsolidasyon import clean_user
        from capture_source import apply_prompt_policy
        apply_prompt_policy(vault, session, str(data.get('prompt', '')))
        if CONTINUATION in str(data.get('prompt', '')) or not clean_user(str(data.get('prompt', ''))):
            return {}
        turn = data.get('turn_id')
        if not isinstance(turn, str) or not turn:
            raise ValueError('UserPromptSubmit turn_id gerekli')
        if turn not in state['turns']:
            state['turns'].append(turn)
            state['count'] += 1
            state.pop('requested_turn', None)
            atomic(state_path, json.dumps(state))
        from gorev_baglam import build_task_package
        # The semantic advisor follows komuta/jev.json; HAFIZA_HOOK_JEV=0 keeps
        # this hook local (e.g. for latency or privacy checks).
        import contextlib, jev_client
        advisor = jev_client.disabled() if os.environ.get('HAFIZA_HOOK_JEV') == '0' else contextlib.nullcontext()
        with advisor:
            package = build_task_package(vault, clean_user(str(data.get('prompt', ''))), cwd=data.get('cwd'), budget=2000)
        lesson_text = package['text']
        # One consecutive repeat may be omitted; the next prompt refreshes it.
        # Hash includes source versions, not only rendered prose.
        package_hash = hashlib.sha256(json.dumps(
            {'text': lesson_text, 'sources': package.get('source_versions', {}),
             'selected': package.get('selected_ids', [])},
            sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = state.get('package_cache', {})
        suppress = bool(lesson_text and package_hash == cache.get('hash') and not cache.get('suppressed'))
        original_chars = len(lesson_text)
        if suppress: lesson_text = ''
        state['package_cache'] = {'hash': package_hash, 'suppressed': suppress}
        parts = ([opening_brief(vault)] if state['count'] == 1 and not state.get('opening_brief_sent') else [])
        if lesson_text:
            parts.append(lesson_text)
            if package.get('source_versions'):
                parts.append('HAFIZA GÖRÜNÜRLÜĞÜ: Bu bağlamın gelmesi kullanım kanıtı değildir. Geçmiş bilgi somut seçimini etkilediyse kısa bir cümlede neyi nasıl uyguladığını kaynak bağlantısıyla belirt; etkilemediyse kullanım iddiası üretme. Aynı bildirimi değişiklik yokken tekrarlama. Uyarlama önerisini yeni kullanıcı onayı sayma. Kayıt bildirimi yalnız başarılı yazma ve geri okuma kanıtından sonra; dry-run, bekleyen aday veya değişmeyen kayıt için kaydettim deme.')
        shared = shared_reviewed_context(vault)
        if shared:
            parts.append(shared)
        emitted = '\n\n'.join(parts)
        account_context(state, len(emitted), original_chars if suppress else 0)
        atomic(state_path, json.dumps(state))
        if parts:
            return {'hookSpecificOutput': {'hookEventName': event,
                    'additionalContext': '\n\n'.join(parts)}}
        return {}
    if event == 'SessionStart':
        state.pop('package_cache', None)
        state['opening_brief_sent'] = True
        queue = vault / INBOX
        missing = len(list(queue.glob('*.pending.json')))
        receipt_count = sum(p.name != 'README.md' for p in queue.glob('*.md'))
        from hafiza_saglik import notice
        health_notice = notice(vault)
        context = (f'Hafıza kasası: {vault}. Önce {vault}/agents.md oku; '
            'son oturum özeti için şu komutu çalıştır. '
            f'Bütçeli okuma ({"PowerShell" if os.name == "nt" else "POSIX shell"}):\n'
            f'{latest_session_command(vault)}\n'
            f'Kısa agents.md açılış sözleşmesi geçerlidir; ayrıntılar yalnız gerektiğinde okunur. '
            f'Gelen kutusunda {receipt_count} görev makbuzu var; listeyi başlangıçta okuma. '
            f'Eksik makbuz sayısı: {missing}. Makbuzlar gelen kutusundadır, kanonik gerçek değildir. '
            f'Bu oturumda sayılan kullanıcı mesajı: {state["count"]}. '
            'Hafıza kaydı arka plan konsolidasyonunda yapılır; cevap sonunda makbuz '
            'isteme ve sohbeti kayıt bildirimiyle bölme. Basit kısa sorular hafızaya girmez. '
            'Kataloğa ve Mem0’a doğrudan yazma.\n\n' + health_notice + '\n\n' + opening_brief(vault))
        shared = shared_reviewed_context(vault)
        if shared:
            context += '\n\n' + shared
        account_context(state, len(context))
        atomic(state_path, json.dumps(state))
        return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': context}}
    # Stop is the end of an assistant turn, not the end of a session.
    # Transcript consolidation handles receipts asynchronously. Never interrupt
    # the conversation or create a per-turn pending receipt here.
    return {}


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=DEFAULT_VAULT)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('hook')
    sub.add_parser('latest-session')
    save = sub.add_parser('record')
    save.add_argument('--input-json', type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == 'latest-session':
        print(latest_session_section(args.vault))
        return
    if args.cmd == 'record':
        queue = args.vault / INBOX
        queue.mkdir(parents=True, exist_ok=True)
        data = json.loads(args.input_json.read_text(encoding='utf-8'))
        if 'semantic_candidates' not in data:
            raise ValueError('semantic_candidates gerekli; kalıcı bilgi yoksa [] kullan')
        # The receipt index is shared; hook state and network work are not.
        with exclusive_lock(queue / '.lock'):
            result = record(args.vault, data['session_id'], data['turn_id'], data['summary'], data['semantic_candidates'], data.get('source_snapshot'))
    else:
        data = json.load(sys.stdin)
        if worker_run(data):
            result = {}
        else:
            state_dir = args.vault / INBOX / '.state'
            state_dir.mkdir(parents=True, exist_ok=True)
            # Different sessions can progress independently. Same-session ordering
            # remains serialized so a late prompt cannot overwrite newer turn state.
            with exclusive_lock(state_dir / (key(data.get('session_id'), 'state') + '.lock')):
                result = hook(args.vault, data)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('Hafıza makbuzu kaydedilemedi: ' + str(error), file=sys.stderr)
        sys.exit(1)
