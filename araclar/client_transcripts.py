"""Bounded readers for original native client sources; never retain reasoning."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from capture_source import privacy_command, privacy_ambiguous
from hafiza import contains_secret

MAX_SOURCE = 8 * 1024 * 1024
MAX_LINE = 256 * 1024
CLIENTS = ('claude', 'antigravity')


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


def parse(client, session, path, end_line=None):
    path = source_path(client, session, path)
    data = read_bytes(path)
    if not data or not data.endswith(b'\n'):
        raise SourceError('truncated_source')
    lines = data.splitlines(keepends=True)
    if len(lines) > 30000 or (end_line is not None and (type(end_line) is not int or not 1 <= end_line <= len(lines))):
        raise SourceError('invalid_source_boundary')
    boundary = end_line or len(lines)
    entries, ids, seen, user_count, prefix_count = [], [], {}, 0, 0
    terminal, prefix_terminal, previous_step = False, False, -1
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
            if kind in ('system', 'progress', 'file-history-snapshot', 'queue-operation', 'summary', 'attachment', 'atis-latch', 'last-prompt'):
                if row.get('error') or row.get('subtype') in ('api_error', 'error'):
                    terminal = False
                if number == boundary:
                    prefix_terminal, prefix_count = terminal, user_count
                continue
            if kind not in ('user', 'assistant') or row.get('sessionId') != session or row.get('isSidechain') is not False:
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
            genuine = kind == 'user' and not row.get('isMeta') and not tools
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
        if role and contains_secret(text):
            raise SourceError('secret_source')
        if number <= boundary and role and text:
            entries.append(dict(line=number, line_sha256=sha(raw), role=role, quote=text, message_id=ident))
            if genuine:
                ids.append(ident)
        if number == boundary:
            prefix_terminal, prefix_count = terminal, user_count
    return dict(client=client, session=session, path=str(path), end_line=boundary,
                prefix_sha256=sha(b''.join(lines[:boundary])), count=prefix_count,
                message_ids=ids, terminal=prefix_terminal, entries=entries,
                total_lines=len(lines), latest_user=next((e for e in reversed(entries) if e['role'] == 'user'), None))
