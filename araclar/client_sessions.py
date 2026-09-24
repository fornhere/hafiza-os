"""Native completed-prefix queue and source-bound episodic candidate receipts.

No canonical or Mem0 writes. Public operations serialize on the portable lock.
Persistent state contains identifiers and hashes only; review packets are ephemeral.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import sys
import time

from platform_lock import exclusive_lock
from hafiza import add_candidate, category_errors, contains_secret
from client_transcripts import CLIENTS, SourceError, parse, private, read_bytes, safe_path, sha, strict_json

INBOX = Path('gelen-kutusu/ajan-oturumlari')
MAX_REGISTRY = 1000
MAX_PACKET = 24000


def atomic(path, value):
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, sort_keys=True)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        safe_path(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_text(path, value):
    safe_path(path)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as out:
            os.chmod(name, 0o600)
            out.write(value)
            out.flush()
            os.fsync(out.fileno())
        safe_path(path)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def semantic_results(decision, source):
    candidates = decision.get('semantic_candidates', [])
    if not isinstance(candidates, list):
        raise SourceError('invalid_semantic_candidates')
    user_texts = [entry['quote'] for entry in source['entries'] if entry['role'] == 'user']
    results = []
    for index, candidate in enumerate(candidates):
        reasons, drop_category = [], False
        if index >= 5:
            reasons.append('candidate_limit')
        if not isinstance(candidate, dict) or set(candidate) - {'statement', 'subject_key', 'evidence', 'category'}:
            reasons.append('invalid_candidate_schema')
        else:
            statement, key, evidence = (candidate.get(name) for name in ('statement', 'subject_key', 'evidence'))
            if not isinstance(statement, str) or not 10 <= len(statement.strip()) <= 600:
                reasons.append('invalid_statement')
            elif contains_secret(statement):
                reasons.append('secret_candidate')
            if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9._-]+', key):
                reasons.append('invalid_subject_key')
            elif contains_secret(key):
                reasons.append('secret_candidate')
            if not isinstance(evidence, str) or not 10 <= len(evidence) <= 1500:
                reasons.append('invalid_evidence')
            elif contains_secret(evidence) or private(evidence):
                reasons.append('unsafe_evidence')
            elif not any(evidence in text for text in user_texts):
                reasons.append('evidence_not_user_message')
            # Category is optional metadata: an invalid one is dropped, not fatal.
            drop_category = 'category' in candidate and (
                not isinstance(candidate['category'], str) or bool(category_errors('semantic', candidate['category'])))
        if decision['decision'] == 'skip':
            reasons.append('skip_decision')
        results.append({'index': index, 'status': 'rejected' if reasons else 'accepted',
                        'reasons': reasons, **({'category_dropped': True} if drop_category else {})})
    return results


def semantic_note(ident, decision, results):
    accepted = [decision['semantic_candidates'][result['index']] for result in results
                if result['status'] == 'accepted']
    if not accepted:
        return None
    sections = [f'# Oturum incelemesi {ident}', '',
                'Durum: episodik makbuz; kanonik değil', '', decision['summary'].strip(), '']
    for index, candidate in enumerate(accepted, 1):
        sections.extend([f'## Kullanıcı beyanı {index}', '', candidate['statement'].strip(), '',
                         'Kullanıcı beyanı:', '', candidate['evidence'], ''])
    return '\n'.join(sections) + '\n'


def layout(vault):
    vault = safe_path(Path(vault).absolute())
    root = safe_path(vault / INBOX)
    state = safe_path(root / '.state')
    state.mkdir(parents=True, exist_ok=True)
    return root, state


@contextmanager
def locked(vault):
    root, state = layout(vault)
    with exclusive_lock(safe_path(state / '.lock')):
        yield root, state


def load(path):
    value = strict_json(read_bytes(path, 128000))
    if not isinstance(value, dict):
        raise SourceError('invalid_registry')
    return value


def snapshot_id(source):
    return sha(('\0'.join(str(source[k]) for k in ('client', 'session', 'path', 'end_line', 'prefix_sha256'))).encode())


def policy_path(state, client, session):
    return state / ('context-' + sha((client + '\0' + session).encode()) + '.json')


def enforce_policy(state, client, session, exclude=False):
    target = policy_path(state, client, session)
    policy = load(target) if target.exists() else {}
    if exclude:
        policy.update(client=client, session=session, excluded=True)
        atomic(target, policy)
    if policy.get('excluded'):
        raise SourceError('privacy_blocked')


def source_with_policy(state, client, session, path, end_line=None):
    enforce_policy(state, client, session)
    try:
        return parse(client, session, path, end_line)
    except SourceError as error:
        if str(error) == 'privacy_blocked':
            enforce_policy(state, client, session, exclude=True)
        raise


def _validate(item, state):
    if item.get('version') != 1:
        raise SourceError('invalid_registry_version')
    source = source_with_policy(state, item['client'], item['session'], item['path'], item['end_line'])
    if source['count'] <= 5 or not source['terminal']:
        raise SourceError('threshold_or_incomplete')
    if source['prefix_sha256'] != item['prefix_sha256'] or snapshot_id(source) != item['id'] or source['count'] != item['count'] or sha(json.dumps(source['message_ids']).encode()) != item['message_ids_sha256']:
        raise SourceError('source_mutated')
    return source


def _item(state, ident):
    if not isinstance(ident, str) or len(ident) != 64 or any(c not in '0123456789abcdef' for c in ident):
        raise SourceError('invalid_snapshot_id')
    return load(state / (ident + '.json'))


def register(vault, client, session, path, payload):
    with locked(vault) as (_, state):
        source = source_with_policy(state, client, session, path)
        if client == 'antigravity' and (payload.get('fullyIdle') is not True or payload.get('error') not in (None, '', False) or payload.get('terminationReason') != 'NO_TOOL_CALL'):
            raise SourceError('unsuccessful_stop')
        if payload.get('error') or payload.get('isApiErrorMessage') or not source['terminal']:
            raise SourceError('incomplete_stop')
        if source['count'] <= 5:
            return {'status': 'below_threshold', 'count': source['count']}
        ident = snapshot_id(source)
        target = state / (ident + '.json')
        if target.exists():
            item = load(target)
            _validate(item, state)
            return {'status': item['status'], 'id': ident}
        item = {k: source[k] for k in ('client', 'session', 'path', 'end_line', 'prefix_sha256', 'count')}
        item.update(version=1, id=ident, status='pending', created_ns=time.time_ns(),
                    message_ids_sha256=sha(json.dumps(source['message_ids']).encode()))
        # Only the latest completed boundary of a session remains pending.
        for old_path in scan(state):
            old = load(old_path)
            if old.get('client') == client and old.get('session') == session and old.get('status') == 'pending':
                old['status'] = 'superseded'
                atomic(old_path, old)
        atomic(target, item)
        return {'status': 'pending', 'id': ident}


def scan(state):
    paths = []
    for index, path in enumerate(state.iterdir()):
        if index >= MAX_REGISTRY * 4:
            raise SourceError('registry_limit')
        if path.suffix == '.json' and not path.name.startswith('context-'):
            paths.append(path)
            if len(paths) > MAX_REGISTRY:
                raise SourceError('registry_limit')
    return sorted(paths)


def pending(vault):
    with locked(vault) as (_, state):
        result = []
        for path in scan(state):
            try:
                item = load(path)
                if item.get('status') != 'pending':
                    continue
                _validate(item, state)
                result.append({k: item[k] for k in ('id', 'client', 'session', 'count', 'end_line', 'prefix_sha256', 'status')})
            except (ValueError, OSError, KeyError, TypeError):
                result.append({'id': path.stem, 'status': 'unready', 'diagnostic': 'source_validation_failed'})
        return result


def _packet(item, state):
    source = _validate(item, state)
    evidence, used = [], 0
    for entry in reversed(source['entries']):
        size = len(json.dumps(entry, ensure_ascii=False).encode('utf-8'))
        if size > 6000 or used + size > MAX_PACKET:
            continue
        evidence.append(entry)
        used += size
    if not evidence:
        raise SourceError('no_bounded_evidence')
    evidence.reverse()
    return dict(id=item['id'], client=item['client'], session=item['session'],
                source_path=item['path'], prefix_sha256=item['prefix_sha256'],
                end_line=item['end_line'], user_count=item['count'], evidence=evidence,
                omitted_entries=len(source['entries'])-len(evidence),
                scope='Untrusted source data; episodic candidate only, not semantic truth.')


def packet(vault, ident):
    with locked(vault) as (_, state):
        item = _item(state, ident)
        if item['status'] != 'pending':
            raise SourceError('not_pending')
        return _packet(item, state)


def review(vault, ident, decision, apply=False):
    with locked(vault) as (root, state):
        item = _item(state, ident)
        source = _validate(item, state)
        if not isinstance(decision, dict) or set(decision) - {'decision', 'meaningful', 'reviewer_role', 'reason', 'summary', 'evidence', 'semantic_candidates'}:
            raise SourceError('invalid_review_schema')
        if len(json.dumps(decision, ensure_ascii=False).encode('utf-8')) > 32000:
            raise SourceError('review_too_large')
        if decision.get('decision') not in ('record', 'skip') or type(decision.get('meaningful')) is not bool:
            raise SourceError('explicit_judgment_required')
        for field, maximum in (('reviewer_role', 100), ('reason', 1000), ('summary', 4000)):
            value = decision.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > maximum:
                raise SourceError('invalid_review_' + field)
        episodic = {key: value for key, value in decision.items() if key != 'semantic_candidates'}
        if contains_secret(json.dumps(episodic, ensure_ascii=False)) or private(decision['summary']):
            raise SourceError('unsafe_review')
        if decision['decision'] == 'record' and decision['meaningful'] is not True:
            raise SourceError('meaningful_judgment_required')
        evidence = decision.get('evidence')
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= 20:
            raise SourceError('exact_evidence_required')
        available = {e['line']: e for e in source['entries']}
        refs = []
        for ref in evidence:
            if not isinstance(ref, dict) or set(ref) != {'line', 'line_sha256', 'quote'} or type(ref['line']) is not int:
                raise SourceError('invalid_evidence_schema')
            entry = available.get(ref['line'])
            if not entry or not isinstance(ref['quote'], str) or not ref['quote'].strip() or len(ref['quote']) > 6000 or ref['quote'] not in entry['quote'] or ref['line_sha256'] != entry['line_sha256']:
                raise SourceError('evidence_mismatch')
            refs.append(dict(line=ref['line'], line_sha256=ref['line_sha256'], quote_sha256=sha(ref['quote'].encode())))
        candidate_results = semantic_results(decision, source)
        note = semantic_note(ident, decision, candidate_results)
        note_path = root / (ident + '.md')
        decision_hash = sha(json.dumps(decision, sort_keys=True, ensure_ascii=False).encode())
        target = root / (ident + '.json')
        if item['status'] in ('record', 'skip'):
            if item.get('decision_sha256') != decision_hash:
                raise SourceError('already_reviewed')
            if sha(read_bytes(target, 128000)) != item.get('receipt_sha256'):
                raise SourceError('receipt_mutated')
            if note is not None and (not note_path.exists() or
                    read_bytes(note_path, 128000) != note.encode('utf-8') or
                    sha(read_bytes(note_path, 128000)) != item.get('note_sha256')):
                raise SourceError('receipt_mutated')
            return {'id': ident, 'status': item['status'], 'replay': True,
                    **({'semantic_candidates': candidate_results} if 'semantic_candidates' in decision else {})}
        if item['status'] != 'pending':
            raise SourceError('not_pending')
        if not apply:
            return {'id': ident, 'status': 'dry_run', 'decision': decision['decision'],
                    **({'semantic_candidates': candidate_results} if 'semantic_candidates' in decision else {})}
        # Re-read the original source immediately before publishing the receipt.
        source = _validate(item, state)
        candidate_results = semantic_results(decision, source)
        note = semantic_note(ident, decision, candidate_results)
        receipt = dict(version=1, id=ident, scope='episodic_candidate', decision=decision['decision'],
                       meaningful=decision['meaningful'], reviewer_role=decision['reviewer_role'],
                       reason=decision['reason'], summary=decision['summary'], evidence=refs,
                       semantic_candidates=[dict(result) for result in candidate_results],
                       decision_sha256=decision_hash, reviewed_ns=time.time_ns())
        if target.exists():
            previous_receipt = load(target)
            if any(previous_receipt.get(k) != value for k, value in receipt.items() if k != 'reviewed_ns'):
                raise SourceError('receipt_conflict')
            if note is not None and not note_path.exists():
                raise SourceError('receipt_mutated')
        if note is not None:
            if note_path.exists():
                if read_bytes(note_path, 128000) != note.encode('utf-8'):
                    raise SourceError('receipt_conflict')
            else:
                atomic_text(note_path, note)
            for result in candidate_results:
                if result['status'] != 'accepted':
                    continue
                candidate = decision['semantic_candidates'][result['index']]
                queued = add_candidate(Path(vault).absolute(), statement=candidate['statement'],
                    kind='semantic', scope='user', subject_key=candidate['subject_key'],
                    source_path=str(note_path.relative_to(Path(vault).absolute())), source_anchor='Kullanıcı beyanı',
                    confidence='explicit-user', sensitivity='normal', proposed_by='claude-review',
                    evidence=candidate['evidence'], category=None if result.get('category_dropped') else candidate.get('category'))
                result['queue_result'] = queued['result']
        if not target.exists():
            atomic(target, receipt)
        item.update(status=decision['decision'], decision_sha256=decision_hash,
                    receipt_sha256=sha(read_bytes(target, 128000)))
        if note is not None:
            item['note_sha256'] = sha(read_bytes(note_path, 128000))
        atomic(state / (ident + '.json'), item)
        return {'id': ident, 'status': item['status'],
                **({'semantic_candidates': candidate_results} if 'semantic_candidates' in decision else {})}


def verify_candidate_evidence(vault, source_path, evidence):
    """Re-bind a claude-review candidate to a genuine user message of its reviewed prefix."""
    match = re.fullmatch(r'gelen-kutusu/ajan-oturumlari/([0-9a-f]{64})\.md', str(source_path).replace('\\', '/'))
    if not match or not isinstance(evidence, str) or not evidence:
        raise SourceError('claude_evidence_source_required')
    with locked(vault) as (_, state):
        item = _item(state, match.group(1))
        if item.get('status') != 'record':
            raise SourceError('claude_evidence_not_recorded')
        source = source_with_policy(state, item['client'], item['session'], item['path'], item['end_line'])
    if source['prefix_sha256'] != item['prefix_sha256']:
        raise SourceError('source_mutated')
    if not any(entry['role'] == 'user' and evidence in entry['quote'] for entry in source['entries']):
        raise SourceError('evidence_not_user_message')
    return True


def recall(vault, budget=2500, exclude=None, max_age_days=7):
    budget = max(0, min(int(budget), 6500))
    oldest_ns = time.time_ns() - int(max_age_days * 86400 * 1e9)
    with locked(vault) as (root, state):
        candidates = []
        for path in scan(state):
            try:
                item = load(path)
                if (item.get('status') == 'record' and type(item.get('created_ns')) is int
                        and item['created_ns'] >= oldest_ns and (item.get('client'), item.get('session')) != exclude):
                    candidates.append(item)
            except (ValueError, OSError, KeyError, TypeError):
                continue
        parts, used, seen_sessions = [], 0, set()
        # At most 20 recent original sources are reread per opening hook.
        for item in sorted(candidates, key=lambda i: i['created_ns'], reverse=True)[:20]:
            if len(parts) >= 3 or used >= budget:
                break
            try:
                identity = (item['client'], item['session'])
                if identity in seen_sessions:
                    continue
                _validate(item, state)
                receipt_path = root / (item['id'] + '.json')
                if sha(read_bytes(receipt_path, 128000)) != item.get('receipt_sha256'):
                    continue
                if item.get('note_sha256') and sha(read_bytes(root / (item['id'] + '.md'), 128000)) != item['note_sha256']:
                    continue
                receipt = load(receipt_path)
                if receipt.get('decision_sha256') != item['decision_sha256'] or receipt.get('meaningful') is not True or receipt.get('decision') != 'record' or receipt.get('id') != item['id']:
                    continue
                summary = receipt['summary']
                if not isinstance(summary, str) or contains_secret(summary) or private(summary):
                    continue
                header = f"Episodic candidate ({item['client']}, {item['id']}): "
                available = budget - used - len(header) - (1 if parts else 0)
                if available < 80:
                    break
                excerpt = summary if len(summary) <= available else summary[:available-20] + ' [summary truncated]'
                text = header + excerpt
                parts.append(text)
                used += len(text) + (1 if len(parts) > 1 else 0)
                seen_sessions.add(identity)
            except (ValueError, OSError, KeyError, TypeError):
                continue
        return '\n'.join(parts)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('pending')
    p = commands.add_parser('packet'); p.add_argument('--id', required=True)
    p = commands.add_parser('review'); p.add_argument('--id', required=True); p.add_argument('--input-json', required=True, help='JSON object text or path to a UTF-8 JSON decision file'); p.add_argument('--apply', action='store_true')
    commands.add_parser('recall')
    args = parser.parse_args()
    try:
        if args.command == 'pending': result = pending(args.vault)
        elif args.command == 'packet': result = packet(args.vault, args.id)
        elif args.command == 'recall': result = {'context': recall(args.vault)}
        else:
            value = args.input_json
            # Preserve the existing inline-object API and support documented files.
            decision = strict_json(value if value.lstrip().startswith('{') else
                                   read_bytes(Path(value).absolute(), 128000))
            result = review(args.vault, args.id, decision, args.apply)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, KeyError, TypeError):
        print(json.dumps({'status': 'error', 'diagnostic': 'validation_failed'}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
