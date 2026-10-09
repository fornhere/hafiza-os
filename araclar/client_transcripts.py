"""Bounded readers for original native client sources; never retain reasoning."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from capture_source import clean_user, privacy_command, privacy_ambiguous
from hafiza import contains_secret
from jsonl_lines import split_jsonl

MAX_SOURCE = 64 * 1024 * 1024
MAX_LINE = 16 * 1024 * 1024
MAX_LINES = 200000
CLIENTS = ('claude', 'antigravity')
COUNT_VERSION = 'count_v1'
COUNT_VARIANTS = ('legacy_commands', 'legacy_interrupts',
                  'count_variant_5e735eb', 'count_variant_5c0fa24')


class SourceError(ValueError):
    """Safe diagnostic code, without source text."""


def sha(value):
    return hashlib.sha256(value).hexdigest()


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise SourceError('absolute_path_required')
    for item in (path, *path.parents):
        try:
            attributes = getattr(item.lstat(), 'st_file_attributes', 0)
        except FileNotFoundError:
            attributes = 0
        if (item.is_symlink() or getattr(item, 'is_junction', lambda: False)()
                or attributes & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)):
            raise SourceError('symlink_rejected')
    return path


def read_bytes(path, limit=MAX_SOURCE):
    path = safe_path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise SourceError('source_size_or_type')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        current = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise SourceError('source_changed_during_read')
        if (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino) or len(data) > limit:
            raise SourceError('source_replaced')
        return data
    finally:
        os.close(fd)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SourceError('duplicate_json_key')
            result[key] = value
        return result
    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(SourceError('invalid_json_number')))
    except (ValueError, TypeError, RecursionError) as exc:
        raise SourceError('invalid_json') from exc


def worker_prompt(text):
    """Explicit worker prefixes are operational instructions, never user memory."""
    return (isinstance(text, str) and clean_user(text).casefold().replace('\u0307', '')
            .startswith(('işçi koşusu', 'isci kosusu')))


def private(text):
    return privacy_command(text) or privacy_ambiguous(text) or bool(re.search(
        r"\b(?:do not|don't|never) (?:save|record|remember|store)|\b(?:off the record|keep this private|forget this)\b",
        text, re.I))


def _text(content, user=False):
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        raise SourceError('unknown_content_schema')
    texts, tools = [], False
    for block in content:
        if not isinstance(block, dict):
            raise SourceError('unknown_content_block')
        kind = block.get('type')
        if kind == 'text' and isinstance(block.get('text'), str):
            texts.append(block['text'])
        elif kind in ('tool_use', 'tool_result'):
            tools = True
        elif kind in ('image', 'document'):
            pass
        elif kind in ('thinking', 'redacted_thinking') and not user:
            pass
        else:
            raise SourceError('unknown_content_block')
    return '\n'.join(texts), tools


def source_path(client, session, path):
    if client not in CLIENTS or not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', session):
        raise SourceError('invalid_client_identity')
    path = safe_path(path)
    if any('subagent' in p.lower() for p in path.parts) or path.stem.startswith('agent-'):
        raise SourceError('subagent_source')
    if client == 'claude':
        if path.name != session + '.jsonl':
            raise SourceError('source_identity_mismatch')
    elif path.name not in ('transcript.jsonl', 'transcript_full.jsonl') or path.parent.name != 'logs' or path.parent.parent.name != '.system_generated' or path.parent.parent.parent.name != session or path.parent.parent.parent.parent.name != 'brain':
        raise SourceError('source_identity_mismatch')
    return path


def claude_user_text(text):
    """Exclude native command delivery bodies before extracting slash arguments.

    These tags belong to Claude's harness, not the shared Codex cleaner. A
    missing close consumes the tail; nested and case-varied tags stay excluded.
    command-name/message/args are deliberately outside this family.
    """
    token = re.compile(
        r'<(?P<end>/)?(?P<tag>(?:local-command|bash|command|shell|tool|exec)-'
        r'(?:stdout|stderr|output|caveat|warnings?|errors?|results?))'
        r'(?=\s|/?>)(?P<attrs>[^>]*)>', re.I)
    pieces, stack, cursor = [], [], 0
    for match in token.finditer(text):
        tag = match['tag'].lower()
        if not stack:
            pieces.append(text[cursor:match.start()])
        if match['end']:
            if stack and tag == stack[-1]:
                stack.pop()
        elif not match['attrs'].rstrip().endswith('/'):
            stack.append(tag)
        cursor = match.end()
    if not stack:
        pieces.append(text[cursor:])
    return clean_user(''.join(pieces))


# Kanıtlanmış tarihsel temizleyiciler; yalnız sayım metadata uyumluluğu.
def count_variant_5e735eb(text):
    for tag in ('recommended_plugins', 'environment_context', 'permissions instructions', 'in-app-browser-context'):
        text = re.sub(r'<' + tag + r'(?:\s[^>]*)?>.*?</' + tag + r'>', '', text, flags=re.S)
    text = text.strip()
    if text.startswith('## My request:'):
        text = text[len('## My request:'):].strip()
    excluded = ('# AGENTS.md instructions', '<subagent_notification', '<turn_aborted',
        '<hook_prompt', '[HAFIZA_KAPANIS]', '[HAFIZA_OTOMASYON]', '<system-reminder', '<goal>',
        '<heartbeat', '<collaboration', '<codex_internal_context', '<in-app-browser-context',
        '<task-notification')
    return '' if text.startswith(excluded) else text


def count_variant_5c0fa24(text):
    # Tarihsel harness temizliği: kapanmamış sarmalayıcı kalan metni tüketir.
    harness_tags = ('subagent_notification', 'turn_aborted', 'hook_prompt',
        'system-reminder', 'goal', 'heartbeat', 'collaboration',
        'codex_internal_context', 'task-notification', 'cross-session-message')
    token = re.compile(r'<(?P<end>/)?(?P<tag>' + '|'.join(harness_tags)
                       + r')(?=\s|/?>)(?P<attrs>[^>]*)>', re.I)
    pieces = []; stack = []; cursor = 0
    for match in token.finditer(text):
        tag = match['tag'].lower()
        if not stack:
            pieces.append(text[cursor:match.start()])
        if match['end']:
            if stack and tag == stack[-1]:
                stack.pop()
        elif not match['attrs'].rstrip().endswith('/'):
            stack.append(tag)
        cursor = match.end()
    if not stack:
        pieces.append(text[cursor:])
    text = ''.join(pieces)
    for tag in ('recommended_plugins', 'environment_context', 'permissions instructions', 'in-app-browser-context'):
        text = re.sub(r'<' + tag + r'(?:\s[^>]*)?>.*?</' + tag + r'>', '', text, flags=re.S)
    text = text.strip()
    if text.startswith('## My request:'):
        text = text[len('## My request:'):].strip()
    excluded = ('# AGENTS.md instructions', '<subagent_notification', '<turn_aborted',
        '<hook_prompt', '[HAFIZA_KAPANIS]', '[HAFIZA_OTOMASYON]', '<system-reminder', '<goal>',
        '<heartbeat', '<collaboration', '<codex_internal_context', '<in-app-browser-context',
        '<task-notification', '<cross-session-message')
    return '' if text.startswith(excluded) else text


def parse(client, session, path, end_line=None, *, reject_workers=False, legacy_interrupts=False,
          _receipt_metadata=False):
    # Capture rejects worker sessions; offline readers may filter individual turns.
    path = source_path(client, session, path)
    data = read_bytes(path)
    if not data or not data.endswith(b'\n'):
        raise SourceError('truncated_source')
    try: lines = [line.encode('utf-8') for line in split_jsonl(data.decode('utf-8'), keepends=True)]
    except UnicodeDecodeError as exc: raise SourceError('invalid_json') from exc
    if len(lines) > MAX_LINES or (end_line is not None and (type(end_line) is not int or not 1 <= end_line <= len(lines))):
        raise SourceError('invalid_source_boundary')
    boundary = end_line or len(lines)
    entries, ids, seen, user_count, prefix_count = [], [], {}, 0, 0
    # Historical Claude IDs are metadata only; never create legacy evidence.
    receipt_ids, receipt_interrupt_ids = [], []
    variant_ids = {name: [] for name in COUNT_VARIANTS[2:]}
    terminal, prefix_terminal, previous_step = False, False, -1
    worker = False
    for number, raw in enumerate(lines, 1):
        if len(raw) > MAX_LINE:
            raise SourceError('line_too_large')
        row = strict_json(raw)
        if not isinstance(row, dict):
            raise SourceError('unknown_record_schema')
        if any(row.get(k) for k in ('isSidechain', 'isSubagent', 'subagent', 'agentId', 'parentAgentId')):
            raise SourceError('subagent_source')
        if any(row.get(k) for k in ('truncated', 'isTruncated')):
            raise SourceError('truncated_record')
        if client == 'claude':
            kind = row.get('type')
            if row.get('sessionId', session) != session:
                raise SourceError('source_identity_mismatch')
            if kind not in ('user', 'assistant'):
                if not isinstance(kind, str) or not kind:
                    raise SourceError('unknown_claude_schema')
                if row.get('error') or row.get('subtype') in ('api_error', 'error'):
                    terminal = False
                if number == boundary:
                    prefix_terminal, prefix_count = terminal, user_count
                continue
            if row.get('sessionId') != session or row.get('isSidechain') is not False:
                raise SourceError('unknown_claude_schema')
            msg = row.get('message')
            ident = row.get('uuid')
            if not isinstance(msg, dict) or msg.get('role') != kind or not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', ident):
                raise SourceError('unknown_claude_message')
            fingerprint = sha(raw.rstrip(b'\r\n'))
            if ident in seen:
                if seen[ident] != fingerprint:
                    raise SourceError('conflicting_message_id')
                if number == boundary:
                    prefix_terminal, prefix_count = terminal, user_count
                continue
            seen[ident] = fingerprint
            text, tools = _text(msg.get('content'), user=kind == 'user')
            if _receipt_metadata and number <= boundary and kind == 'user' and not row.get('isMeta') and not tools:
                # T63 metadata desenleri ve kanıtlanmış tarihsel sayımlar.
                for name, cleaner in ((COUNT_VARIANTS[2], count_variant_5e735eb),
                                      (COUNT_VARIANTS[3], count_variant_5c0fa24)):
                    if cleaner(text):
                        variant_ids[name].append(ident)
                old_user = bool(clean_user(text))
                old_interrupt = bool(re.fullmatch(
                    r'\s*\[Request interrupted by user(?: for tool use)?\]\s*', text, re.I))
                if old_user:
                    receipt_ids.append(ident)
                if old_user or old_interrupt:
                    receipt_interrupt_ids.append(ident)
            interrupted = legacy_interrupts and bool(re.fullmatch(
                r'\s*\[Request interrupted by user(?: for tool use)?\]\s*', text, re.I))
            if kind == 'user' and not interrupted:
                text = claude_user_text(text)
            # Harness notifications arrive as user rows but are not user requests.
            genuine = kind == 'user' and not row.get('isMeta') and not tools and bool(text)
            usable = kind == 'assistant' and not tools and not row.get('isMeta') and not any(row.get(k) or msg.get(k) for k in ('error', 'isApiErrorMessage')) and isinstance(msg.get('model'), str) and msg['model'] not in ('<synthetic>', 'synthetic') and row.get('model') not in ('<synthetic>', 'synthetic')
            terminal = usable and bool(text.strip()) and msg.get('stop_reason') in ('end_turn', 'stop_sequence')
            role = 'user' if genuine else 'assistant' if usable else None
        else:
            step = row.get('step_index')
            if type(step) is not int or step <= previous_step:
                raise SourceError('duplicate_or_reordered_step')
            previous_step = step
            if any(row.get(k, session) != session for k in ('conversationId', 'conversation_id', 'sessionId')):
                raise SourceError('source_identity_mismatch')
            kind, origin = row.get('type'), row.get('source')
            historical_error = kind == 'GENERIC' and origin == 'MODEL' and row.get('status') == 'ERROR'
            tool_only = (kind == 'PLANNER_RESPONSE' and origin == 'MODEL'
                         and row.get('status') == 'DONE' and isinstance(row.get('tool_calls'), list)
                         and bool(row['tool_calls']) and row.get('content') in (None, ''))
            if historical_error or tool_only:
                terminal = False
                if number == boundary:
                    prefix_terminal, prefix_count = terminal, user_count
                continue
            if row.get('status') != 'DONE':
                raise SourceError('incomplete_or_unknown_step')
            ident = str(step)
            genuine = kind == 'USER_INPUT' and origin == 'USER_EXPLICIT'
            if genuine:
                if not isinstance(row.get('content'), str):
                    raise SourceError('unknown_user_wrapper')
                match = re.fullmatch(r'<USER_REQUEST>\s*([\s\S]*?)\s*</USER_REQUEST>(?:\s*<ADDITIONAL_METADATA>[\s\S]*?(?:</ADDITIONAL_METADATA>)?\s*)?', row['content'])
                if not match or '<USER_REQUEST>' in match[1] or '</USER_REQUEST>' in match[1]:
                    raise SourceError('unknown_user_wrapper')
                text = match[1]
                text = re.sub(r'^/plan(?: |\n)', '', text, count=1)
                role, terminal = 'user', False
            elif kind == 'PLANNER_RESPONSE' and origin == 'MODEL':
                if not isinstance(row.get('content'), str):
                    raise SourceError('unknown_model_content')
                if row.get('error') or row.get('isApiErrorMessage'):
                    raise SourceError('failed_model_step')
                has_tools = bool(row.get('tool_calls') or row.get('toolCalls'))
                text = '' if has_tools else row['content']
                role, terminal = (None if has_tools else 'assistant'), bool(text.strip())
            elif origin in ('TOOL', 'SYSTEM') and kind in ('TOOL_RESULT', 'TOOL_RESPONSE', 'SYSTEM_MESSAGE'):
                text, role, terminal = '', None, False
            elif origin == 'SYSTEM_SDK' and kind == 'EPHEMERAL_MESSAGE':
                # Observed PreInvocation context injection, never human evidence.
                text, role, terminal = '', None, False
            else:
                raise SourceError('unknown_antigravity_schema')
        if genuine:
            if not text.strip():
                raise SourceError('empty_user_message')
            user_count += 1
            if private(text):
                raise SourceError('privacy_blocked')
            worker = worker or (reject_workers and worker_prompt(text))
        if role and contains_secret(text):
            raise SourceError('secret_source')
        if number <= boundary and role and text:
            entries.append(dict(line=number, line_sha256=sha(raw), role=role, quote=text, message_id=ident))
            if genuine:
                ids.append(ident)
        if number == boundary:
            prefix_terminal, prefix_count = terminal, user_count
    # Scan the whole source first so later privacy requests remain sticky.
    if worker:
        raise SourceError('worker_source')
    result = dict(client=client, session=session, path=str(path), end_line=boundary,
                prefix_sha256=sha(b''.join(lines[:boundary])), count=prefix_count,
                message_ids=ids, terminal=prefix_terminal, entries=entries,
                total_lines=len(lines), latest_user=next((e for e in reversed(entries) if e['role'] == 'user'), None))

    if _receipt_metadata:
        result['_receipt_counts'] = [dict(count_version=name, count=len(old_ids), message_ids=old_ids)
            for name, old_ids in zip(COUNT_VARIANTS,
                (receipt_ids, receipt_interrupt_ids, *variant_ids.values()))]
    return result
