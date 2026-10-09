"""Native completed-prefix queue and source-bound episodic candidate receipts.

No canonical or Mem0 writes. Public operations serialize on the portable lock.
Persistent state contains identifiers and hashes only; review packets are ephemeral.
"""
import argparse
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import sys
import time

from platform_lock import exclusive_lock
from hafiza import add_candidate, category_errors, contains_secret, valid_candidate_scope
from client_transcripts import CLIENTS, SourceError, parse, private, read_bytes, safe_path, sha, strict_json

INBOX = Path('gelen-kutusu/ajan-oturumlari')
MAX_REGISTRY = 5000
# Hard bound includes policies and junk; archive contents are never enumerated.
MAX_STATE_ENTRIES = 20000
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


def semantic_results(decision, source, vault=None):
    candidates = decision.get('semantic_candidates', [])
    if not isinstance(candidates, list):
        raise SourceError('invalid_semantic_candidates')
    user_texts = [entry['quote'] for entry in source['entries'] if entry['role'] == 'user']
    results = []
    for index, candidate in enumerate(candidates):
        reasons, drop_category = [], False
        if index >= 5:
            reasons.append('candidate_limit')
        if not isinstance(candidate, dict) or set(candidate) - {'statement', 'subject_key', 'evidence', 'category', 'scope'}:
            reasons.append('invalid_candidate_schema')
        else:
            if not valid_candidate_scope(vault, candidate.get('scope', 'user')):
                reasons.append('invalid_scope')
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


def project_state_result(decision, source):
    """Operational evidence is assistant-authored; semantic gates stay separate."""
    if 'project_state' not in decision:
        return None
    value = decision['project_state']
    fields = {'project_id', 'outcome', 'rationale', 'open_items', 'next_step', 'evidence'}
    if not isinstance(value, dict) or set(value) != fields:
        raise SourceError('invalid_project_state')
    if value['project_id'] is not None and (not isinstance(value['project_id'], str) or
            not re.fullmatch(r'[\w-]{1,100}', value['project_id'])):
        raise SourceError('invalid_project_state')
    texts = [value[k] for k in ('outcome', 'rationale', 'next_step')]
    items = value['open_items']
    if not isinstance(items, list) or len(items) > 20:
        raise SourceError('invalid_project_state')
    texts += items
    if any(not isinstance(t, str) or not t.strip() or len(t) > 1000 for t in texts):
        raise SourceError('invalid_project_state')
    if any(private(t) for t in texts):
        raise SourceError('unsafe_project_state')
    ref = value['evidence']
    if (not isinstance(ref, dict) or set(ref) != {'line', 'line_sha256', 'quote'} or
            type(ref['line']) is not int or not isinstance(ref['quote'], str) or
            not 10 <= len(ref['quote']) <= 6000):
        raise SourceError('invalid_project_state_evidence')
    entry = next((e for e in source['entries'] if e['line'] == ref['line']), None)
    if (not entry or entry['role'] != 'assistant' or ref['quote'] not in entry['quote'] or
            ref['line_sha256'] != entry['line_sha256'] or private(ref['quote'])):
        raise SourceError('project_state_evidence_mismatch')
    return dict(value, assertion_kind='assistant_report')


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
        policy.pop('session_project_id', None)
        policy.update(client=client, session=session, excluded=True)
        atomic(target, policy)
    if policy.get('excluded'):
        raise SourceError('privacy_blocked')


def source_with_policy(state, client, session, path, end_line=None):
    enforce_policy(state, client, session)
    try:
        return parse(client, session, path, end_line, reject_workers=True)
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
    if source['prefix_sha256'] != item['prefix_sha256'] or snapshot_id(source) != item['id']:
        raise SourceError('source_mutated')
    def counts_match(parsed):
        return (parsed['count'] == item['count'] and
                sha(json.dumps(parsed['message_ids']).encode()) == item['message_ids_sha256'])
    if not counts_match(source):
        # Compatibility is limited to old metadata, never threshold/evidence.
        # Recheck prefix/identity on this second read before matching any IDs.
        legacy = parse(item['client'], item['session'], item['path'], item['end_line'],
                       reject_workers=True, _receipt_metadata=True)
        if (legacy['prefix_sha256'] != item['prefix_sha256'] or
                snapshot_id(legacy) != item['id'] or
                not any(counts_match(counts) for counts in legacy['_receipt_counts'])):
            raise SourceError('source_mutated')
    return source


def registry_path(state, ident):
    target = state / (ident + '.json')
    if target.exists():
        return target
    archive = safe_path(state / 'arsiv')
    if archive.exists():
        with os.scandir(archive) as months:
            for index, month in enumerate(months):
                if index >= 1200:
                    registry_diagnostic('registry_archive_lookup_limit')
                    raise SourceError('archive_lookup_limit')
                if re.fullmatch(r'\d{4}-\d{2}', month.name):
                    candidate = safe_path(archive / month.name / target.name)
                    if candidate.exists():
                        return candidate
    return target


def _item(state, ident):
    if not isinstance(ident, str) or len(ident) != 64 or any(c not in '0123456789abcdef' for c in ident):
        raise SourceError('invalid_snapshot_id')
    return load(registry_path(state, ident))


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
        target = registry_path(state, ident)
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


def registry_diagnostic(reason):
    print(json.dumps({'diagnostic': reason}, ensure_ascii=False), file=sys.stderr)


def archive_terminal(state, path, item, apply=True):
    """Caller holds the state lock. A durable intent receipt precedes atomic rename.

    The receipt plus the byte-identical archived file also supports undo after a
    crash between receipt creation and rename. Never overwrite differing bytes.
    Skip stays active to preserve reviewed replay semantics.
    """
    if item.get('status') != 'superseded':
        return None
    stamp = item.get('created_ns')
    if type(stamp) is not int or stamp < 0:
        raise SourceError('invalid_archive_timestamp')
    month = datetime.fromtimestamp(stamp / 1e9, timezone.utc).strftime('%Y-%m')
    destination = safe_path(state / 'arsiv' / month / path.name)
    receipt_path = safe_path(destination.with_suffix('.move.json'))
    digest = sha(read_bytes(path, 128000))
    receipt = dict(version=1, source=path.name,
                   destination=str(destination.relative_to(state)), sha256=digest)
    if not apply:
        return receipt
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and sha(read_bytes(destination, 128000)) != digest:
        raise SourceError('archive_conflict')
    if receipt_path.exists() and load(receipt_path) != receipt:
        raise SourceError('archive_receipt_conflict')
    atomic(receipt_path, receipt)
    os.replace(safe_path(path), destination)
    return receipt


def state_entries(state):
    # scandir's iterator is closed even when the hard limit is hit.
    with os.scandir(safe_path(state)) as entries:
        for index, entry in enumerate(entries):
            if index >= MAX_STATE_ENTRIES:
                registry_diagnostic('registry_scan_limit_partial')
                break
            path = state / entry.name
            if re.fullmatch(r'[0-9a-f]{64}\.json', entry.name):
                yield path


def maintain(vault, apply=False):
    """Bounded, locked, idempotent maintenance; defaults to a dry run."""
    with locked(vault) as (_, state):
        receipts = []
        for path in state_entries(state):
            receipt = archive_terminal(state, path, load(path), apply)
            if receipt:
                receipts.append(receipt)
        return {'status': 'archived' if apply else 'dry_run', 'receipts': receipts}


def registry_status(vault):
    """Read-only counts; active means files in the root, including terminals.

    Do not call layout/scan here: status must neither create nor archive files.
    Counts are lower bounds when directory enumeration reaches its hard budget.
    """
    state = safe_path(Path(vault) / INBOX / '.state')
    counts = dict(active_count=0, archive_count=0, complete=True)

    def count(directory, key, budget):
        if not directory.exists():
            return
        with os.scandir(safe_path(directory)) as entries:
            for entry in entries:
                if budget[0] <= 0:
                    counts['complete'] = False
                    break
                budget[0] -= 1
                if re.fullmatch(r'[0-9a-f]{64}\.json', entry.name):
                    safe_path(directory / entry.name)
                    if entry.is_file(follow_symlinks=False):
                        counts[key] += 1

    count(state, 'active_count', [MAX_STATE_ENTRIES])
    archive = safe_path(state / 'arsiv')
    if archive.exists():
        budget = [MAX_STATE_ENTRIES]
        with os.scandir(archive) as months:
            for index, month in enumerate(months):
                if index >= 1200 or budget[0] <= 0:
                    counts['complete'] = False
                    break
                if re.fullmatch(r'\d{4}-\d{2}', month.name):
                    count(archive / month.name, 'archive_count', budget)
    counts.update(max_registry=MAX_REGISTRY,
                  occupancy_ratio=counts['active_count'] / MAX_REGISTRY,
                  maintenance_due=counts['active_count'] * 10 > MAX_REGISTRY * 7,
                  capacity_warning=counts['active_count'] * 10 > MAX_REGISTRY * 9)
    return counts


def registry_warning(data):
    if not data['capacity_warning']:
        return ''
    return (f"Hafıza uyarısı: oturum kayıt dizini %{data['occupancy_ratio'] * 100:.1f} dolu "
            '(registry_capacity_high); bakım: python3 araclar/client_sessions.py '
            '--vault /KASA maintain --apply')


def restore_archive(vault, relative):
    with locked(vault) as (_, state):
        parts = Path(relative).parts
        if (len(parts) != 3 or parts[0] != 'arsiv' or
                not re.fullmatch(r'\d{4}-\d{2}', parts[1]) or
                not re.fullmatch(r'[0-9a-f]{64}\.move\.json', parts[2])):
            raise SourceError('invalid_archive_receipt')
        receipt = load(safe_path(state / relative))
        name = parts[2].replace('.move.json', '.json')
        destination = state / 'arsiv' / parts[1] / name
        target = state / name
        if (receipt.get('source') != name or
                receipt.get('destination') != str(destination.relative_to(state))):
            raise SourceError('invalid_archive_receipt')
        if target.exists():
            if sha(read_bytes(target, 128000)) != receipt['sha256']:
                raise SourceError('archive_conflict')
        else:
            if sha(read_bytes(destination, 128000)) != receipt['sha256']:
                raise SourceError('archive_mutated')
            os.replace(safe_path(destination), safe_path(target))
        return {'status': 'restored', 'id': target.stem}


def scan(state):
    """Called under the state lock; terminal history is drained, not counted.

    The soft active limit is diagnostic, never a hook outage. Enumeration and
    JSON reads remain capped by MAX_STATE_ENTRIES even for hostile directories.
    """
    paths, terminal_count = [], 0
    for path in state_entries(state):
        try:
            item = load(path)
            if item.get('status') == 'superseded':
                terminal_count += 1
                try:
                    archive_terminal(state, path, item)
                except (ValueError, OSError, KeyError, TypeError, OverflowError):
                    registry_diagnostic('registry_archive_failed')
                continue
        except (ValueError, OSError, KeyError, TypeError):
            pass  # Existing consumers handle invalid active records.
        paths.append(path)
    if len(paths) + terminal_count > MAX_REGISTRY:
        registry_diagnostic('registry_limit_terminal_skipped' if terminal_count
                            else 'registry_active_limit_exceeded')
    return sorted(paths)


def pending(vault):
    with locked(vault) as (_, state):
        result = []
        for path in scan(state):
            try:
                item = load(path)
                if item.get('status') != 'pending':
                    continue
                source = _validate(item, state)
                result.append(dict({k: item[k] for k in ('id', 'client', 'session', 'end_line', 'prefix_sha256', 'status')},
                                   count=source['count']))
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
    try:
        registry = json.loads((state.parents[2] / 'komuta/gorev-baglam.json').read_text(encoding='utf-8'))
        active_projects = sorted(p['id'] for p in registry.get('projects', [])
                                 if p.get('status', 'active') == 'active')
    except (OSError, ValueError, KeyError, TypeError):
        active_projects = []
    return dict(id=item['id'], client=item['client'], session=item['session'],
                active_projects=active_projects,
                source_path=item['path'], prefix_sha256=item['prefix_sha256'],
                end_line=item['end_line'], user_count=source['count'], evidence=evidence,
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
        if not isinstance(decision, dict) or set(decision) - {'decision', 'meaningful', 'reviewer_role', 'reason', 'summary', 'evidence', 'semantic_candidates', 'project_state'}:
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
        operational = project_state_result(decision, source)
        candidate_results = semantic_results(decision, source, vault)
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
        operational = project_state_result(decision, source)
        candidate_results = semantic_results(decision, source, vault)
        note = semantic_note(ident, decision, candidate_results)
        receipt = dict(version=1, id=ident, scope='episodic_candidate', decision=decision['decision'],
                       meaningful=decision['meaningful'], reviewer_role=decision['reviewer_role'],
                       reason=decision['reason'], summary=decision['summary'], evidence=refs,
                       semantic_candidates=[dict(result) for result in candidate_results],
                       decision_sha256=decision_hash, reviewed_ns=time.time_ns())
        if operational is not None:
            receipt['project_state'] = operational
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
                    kind='semantic', scope=candidate.get('scope', 'user'), subject_key=candidate['subject_key'],
                    source_path=str(note_path.relative_to(Path(vault).absolute())), source_anchor='Kullanıcı beyanı',
                    confidence='explicit-user', sensitivity='normal', proposed_by='claude-review',
                    evidence=candidate['evidence'], category=None if result.get('category_dropped') else candidate.get('category'))
                result['queue_result'] = queued['result']
        if operational is not None and decision['decision'] == 'record':
            # Immutable source note for the existing ledger source/hash contract.
            project_path = root / (ident + '.project.md')
            project_text = ('# Proje durumu — asistan bildirimi\n\n'
                            + json.dumps(operational, ensure_ascii=False, sort_keys=True)
                            + '\n\n' + operational['evidence']['quote'] + '\n')
            if project_path.exists():
                if read_bytes(project_path, 128000) != project_text.encode('utf-8'):
                    raise SourceError('project_state_source_mutated')
            else:
                atomic_text(project_path, project_text)
            from is_ve_ders import put_project_state
            put_project_state(Path(vault).absolute(), operational, ident,
                              project_path.relative_to(Path(vault).absolute()).as_posix(),
                              dict(client=item['client'], session=item['session'],
                                   path=item['path'], end_line=item['end_line'],
                                   prefix_sha256=item['prefix_sha256']))
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


def state_values(card):
    report = card.get('assistant_report') or card.get('project_state') or {}
    return [str(v) for v in (card.get('goal'), card.get('last_result') or report.get('outcome'),
            card.get('open_work') or '; '.join(report.get('open_items') or []),
            card.get('blocker'), card.get('next_step') or report.get('next_step'))
            if v and not contains_secret(str(v)) and not private(str(v))]


def state_warnings(vault, card):
    """Independent uncertainty notices, with their own source basis.

    Callers have validated the card source. An inherited decision additionally
    needs its original source checked; matching report prose cannot resolve it.
    """
    notices = []
    decision = card.get('decision_required')
    origin = card.get('decision_source') or card
    if isinstance(decision, str) and decision and not contains_secret(decision) and not private(decision):
        try:
            import hafiza as h
            content = h.source_file(vault, origin['source_path']).read_text()
            if (origin.get('evidence') and origin['evidence'] in content
                    and origin.get('source_content_hash') == h.statement_hash(content)):
                notices.append(('karar bekliyor: ' + decision, origin))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    if card.get('outcome_unverified') is True:
        notices.append(('sonuç teyitsiz', card))
    return notices


def same_state(left, right):
    """Only a report can collapse a card; shared projects alone prove nothing."""
    if not left.get('project_id') or left.get('project_id') != right.get('project_id'):
        return False
    if not any(c.get('assertion_kind') == 'assistant_report' for c in (left, right)):
        return False
    a, b = state_values(left), state_values(right)
    if not a or not b:
        return False
    words = lambda values: set(re.findall(r'\w+', ' '.join(values).casefold()))
    wa, wb = words(a), words(b)
    overlap = len(wa & wb) / max(1, len(wa | wb))
    origins = [c.get('transcript_source') or {} for c in (left, right)]
    same_origin = (bool(left.get('receipt_id')) and left.get('receipt_id') == right.get('receipt_id')) or (
        bool(origins[0].get('session')) and
        (origins[0].get('client'), origins[0].get('session')) ==
        (origins[1].get('client'), origins[1].get('session')))
    same_source = bool(left.get('source_path')) and left.get('source_path') == right.get('source_path')
    # Different tasks in one session must retain their independent next steps.
    steps = [c.get('next_step') or (c.get('assistant_report') or {}).get('next_step') for c in (left, right)]
    step_words = [set(re.findall(r'\w+', str(step or '').casefold())) for step in steps]
    step_overlap = len(step_words[0] & step_words[1]) / max(1, len(step_words[0] | step_words[1]))
    matching_step = bool(steps[0]) and (steps[0] == steps[1] or (
        len(step_words[0] & step_words[1]) >= 4 and step_overlap >= .8))
    return matching_step and (((same_origin or same_source) and overlap >= .5) or (
        len(wa & wb) >= 6 and overlap >= .9))


def state_signature(card):
    """Content-free delivery marker for the first prompt after an opening."""
    report = card.get('assistant_report') or {}
    step = card.get('next_step') or report.get('next_step') or ''
    return dict(project_id=card.get('project_id'),
                report=card.get('assertion_kind') == 'assistant_report',
                step=sha(step.encode()),
                words=sorted({sha(w.encode()) for w in re.findall(r'\w+', ' '.join(state_values(card)).casefold())}))


def unique_states(cards):
    """Newest representative plus older, source-validated supplements."""
    groups = []
    for card in sorted(cards, key=lambda c: str(c.get('updated_at', '')), reverse=True):
        group = next((g for g in groups if same_state(g[0], card)), None)
        if group is None:
            groups.append([card])
        else:
            group.append(card)
    return groups


def receipt_project_matches(vault, receipt, project_id):
    """Called only after receipt/source hashes pass; explicit IDs take precedence."""
    report = receipt.get('project_state') or {}
    if report.get('project_id'):
        return report['project_id'] == project_id
    from gorev_baglam import config
    project = next((p for p in config(vault).get('projects', []) if p['id'] == project_id), {})
    names = [project_id, *project.get('aliases', [])]
    # Ownership must be explicit in the reviewed rationale/note, not free agenda.
    text = '\n'.join(str(x or '') for x in (receipt.get('reason'), report.get('rationale')))
    return any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.IGNORECASE)
               for name in names if isinstance(name, str) and name)


def recall(vault, budget=2500, exclude=None, max_age_days=7, exclude_cards=(), delivered_cards=None, project_id=None, query=None):
    budget = max(0, min(int(budget), 6500))
    oldest_ns = time.time_ns() - int(max_age_days * 86400 * 1e9)
    if query is not None:
        from gorev_baglam import config, project_terms, rank_records, content_words, word_match
        project = next((p for p in config(vault).get('projects', [])
                        if p['id'] == project_id), dict(id=project_id or ''))
        ignored = project_terms(project)
        # Proje adı sahipliktir; tek başına görev alakası değildir.
        topic = ' '.join(sorted(w for w in content_words(query)
                              if not any(word_match(w, term) for term in ignored)))
        if not topic: return ''

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
        parts, used, seen_sessions, seen_cards = [], 0, set(), list(exclude_cards)
        # Inspect at most 20 bounded receipts; only relevant candidates reread sources.
        for item in sorted(candidates, key=lambda i: i['created_ns'], reverse=True)[:20]:
            if len(parts) >= 3 or used >= budget:
                break
            try:
                identity = (item['client'], item['session'])
                header = f"Episodic candidate ({item['client']}, {item['id']}): "
                available = budget - used - len(header) - (1 if parts else 0)
                if available < 80:
                    break
                receipt_path = root / (item['id'] + '.json')
                receipt_bytes = read_bytes(receipt_path, 128000)
                receipt = strict_json(receipt_bytes)
                summary = receipt['summary']
                report = receipt.get('project_state')
                if not isinstance(summary, str):
                    continue
                if query is not None:
                    # Untrusted receipt text is only an exclusion hint. Never rank
                    # rendered schema labels, and validate every delivered source.
                    values = [summary]
                    if isinstance(report, dict):
                        values.extend(report.get(k, '') for k in ('outcome', 'rationale', 'next_step'))
                        values.extend(report.get('open_items', []))
                    content = '\n'.join(v for v in values if isinstance(v, str))
                    if not rank_records([dict(statement=content)], topic):
                        continue
                _validate(item, state)
                if sha(receipt_bytes) != item.get('receipt_sha256'):
                    continue
                if item.get('note_sha256') and sha(read_bytes(root / (item['id'] + '.md'), 128000)) != item['note_sha256']:
                    continue
                if receipt.get('decision_sha256') != item['decision_sha256'] or receipt.get('meaningful') is not True or receipt.get('decision') != 'record' or receipt.get('id') != item['id']:
                    continue
                summary = receipt['summary']
                if not isinstance(summary, str) or contains_secret(summary) or private(summary):
                    continue
                report = receipt.get('project_state')
                if project_id and not receipt_project_matches(vault, receipt, project_id):
                    continue
                if not isinstance(report, dict) and identity in seen_sessions:
                    continue
                if isinstance(report, dict) and report.get('assertion_kind') == 'assistant_report':
                    # Shown by session recall independent of the next user's question.
                    card = dict(project_id=report.get('project_id'), assertion_kind='assistant_report',
                                assistant_report=report, transcript_source=item)
                    if any(same_state(card, seen) for seen in seen_cards):
                        continue
                    report_text = ('Asistan bildirimi (doğrulanmış sonuç değildir) — proje: '
                                   + str(report.get('project_id')) + '\nSonuç: ' + report['outcome']
                                   + '\nGerekçe: ' + report['rationale']
                                   + '\nAçık işler: ' + '; '.join(report['open_items'])
                                   + '\nSonraki adım: ' + report['next_step'])
                    if contains_secret(report_text) or private(report_text):
                        continue
                    if project_id and not report.get('project_id'):
                        # Put the reviewed task details before verbose state fields.
                        summary = 'Proje kimliği yok; kapsam gerekçeden eşleşti.\n' + summary + '\n' + report_text
                    else:
                        summary = report_text + '\n' + summary
                excerpt = summary if len(summary) <= available else summary[:available-20] + ' [summary truncated]'
                text = header + excerpt
                parts.append(text)
                used += len(text) + (1 if len(parts) > 1 else 0)
                seen_sessions.add(identity)
                if isinstance(report, dict) and report.get('assertion_kind') == 'assistant_report':
                    seen_cards.append(card)
                    if delivered_cards is not None and report_text in excerpt:
                        delivered_cards.append(card)
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
    p = commands.add_parser('maintain'); p.add_argument('--apply', action='store_true')
    p = commands.add_parser('restore-archive'); p.add_argument('--receipt', required=True)
    p = commands.add_parser('packet'); p.add_argument('--id', required=True)
    p = commands.add_parser('review'); p.add_argument('--id', required=True); p.add_argument('--input-json', required=True, help='JSON object text or path to a UTF-8 JSON decision file'); p.add_argument('--apply', action='store_true')
    commands.add_parser('recall')
    args = parser.parse_args()
    try:
        if args.command == 'maintain': result = maintain(args.vault, args.apply)
        elif args.command == 'restore-archive': result = restore_archive(args.vault, args.receipt)
        elif args.command == 'pending': result = pending(args.vault)
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
