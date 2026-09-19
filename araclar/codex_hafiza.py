#!/usr/bin/env python3
"""Codex lifecycle -> yerel görev makbuzu. Kataloğa veya Mem0'a yazmaz."""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
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
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with temp.open('w', encoding='utf-8') as out:
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
            scope='user', subject_key=candidate['subject_key'],
            source_path=str(note.relative_to(vault)), source_anchor='Kullanıcı beyanı',
            confidence='explicit-user', sensitivity='normal', proposed_by='codex-receipt',
            evidence=candidate['evidence'], evidence_source=candidate['evidence_source']))
    waiting.unlink(missing_ok=True)
    return {'saved': str(note), 'candidates': queued}


def latest_session_section(vault, limit=2500):
    """Read the newest dated section without sending the whole journal to the model."""
    path = vault / 'zihin/son-oturum.md'
    if not path.exists(): return 'Son oturum notu yok.'
    text = path.read_text(encoding='utf-8')
    matches = list(re.finditer(r'^## (\d{4}-\d{2}-\d{2})[^\n]*', text, re.M))
    if not matches: return 'Tarihli son oturum bölümü bulunamadı; gerekirse kaynakta ara.'
    index = max(range(len(matches)), key=lambda i: (matches[i].group(1), i))
    section = text[matches[index].start():matches[index+1].start() if index+1<len(matches) else len(text)].strip()
    if len(section)>limit:
        section=section[:max(0,limit-90)]+'\n[Kesildi; yalnız gereken ayrıntı için kaynak bölümü aç.]'
    return section


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


def hook(vault, data):
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
        package = build_task_package(vault, clean_user(str(data.get('prompt', ''))), cwd=data.get('cwd'))
        lesson_text = package['text']
        # One consecutive repeat may be omitted; the next prompt refreshes it.
        # Hash includes source versions, not only rendered prose.
        package_hash = hashlib.sha256(json.dumps(package, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cache = state.get('package_cache', {})
        suppress = bool(lesson_text and package_hash == cache.get('hash') and not cache.get('suppressed'))
        original_chars = len(lesson_text)
        if suppress: lesson_text = ''
        state['package_cache'] = {'hash': package_hash, 'suppressed': suppress}
        parts = ([opening_brief(vault)] if state['count'] == 1 else [])
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
        queue = vault / INBOX
        missing = len(list(queue.glob('*.pending.json')))
        latest = sorted(queue.glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True)
        recent = '\n'.join(str(p) for p in latest if p.name != 'README.md')[:1800]
        from hafiza_saglik import notice
        health_notice = notice(vault)
        context = (f'Hafıza kasası: {vault}. Önce {vault}/agents.md ve '
            f'{vault}/zihin/son-oturum.md dosyasının yalnız en yeni bölümünü oku. '
            f'Bütçeli okuma ({"PowerShell" if os.name == "nt" else "POSIX shell"}):\n'
            f'{latest_session_command(vault)}\n'
            f'Diğer ajan açılış yönergeleri geçerlidir. Yeni Codex görev makbuzları: {recent or "yok"}. '
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
    queue = args.vault / INBOX
    queue.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(queue / '.lock'):
        if args.cmd == 'record':
            data = json.loads(args.input_json.read_text(encoding='utf-8'))
            if 'semantic_candidates' not in data:
                raise ValueError('semantic_candidates gerekli; kalıcı bilgi yoksa [] kullan')
            result = record(args.vault, data['session_id'], data['turn_id'], data['summary'], data['semantic_candidates'], data.get('source_snapshot'))
        else:
            result = hook(args.vault, json.load(sys.stdin))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('Hafıza makbuzu kaydedilemedi: ' + str(error), file=sys.stderr)
        sys.exit(1)
