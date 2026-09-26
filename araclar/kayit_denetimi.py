#!/usr/bin/env python3
"""Salt okunur katalog denetimleri; kayıt yazmaz, supersede etmez."""

import argparse
import json
from itertools import combinations
from pathlib import Path

import bilgi_agi
import gorev_baglam
import hafiza
import jev_client
import jev_review


def _project_ids(vault):
    registry = json.loads((vault / 'komuta/gorev-baglam.json').read_text(encoding='utf-8'))
    if not isinstance(registry, dict) or not isinstance(registry.get('projects'), list):
        raise ValueError('projects listesi gerekli')
    projects = registry['projects']
    if any(not isinstance(project, dict) or not isinstance(project.get('id'), str)
           or not project['id'] for project in projects):
        raise ValueError('proje kimliği gerekli')
    return {project['id'] for project in projects}


def _scope_suspect(row, project_ids):
    source = row.get('source_path')
    if row.get('scope') != 'user' or not isinstance(source, str):
        return None
    source = source.replace('\\', '/')
    while source.startswith('./'):
        source = source[2:]
    parts = source.split('/')
    if (len(parts) < 3 or parts[0] != 'projeler' or not all(parts[1:])
            or any(part in {'.', '..'} for part in parts[1:])):
        return None
    project_dir = parts[1]
    return dict(subject_key=row.get('subject_key'), source_path=source,
                project_dir=project_dir,
                suggested_scope=f'project:{project_dir}' if project_dir in project_ids else None)


def scope_audit(vault) -> dict:
    import konsolidasyon

    vault = Path(vault)
    catalog = hafiza.load_catalog(vault)
    diagnostics = []
    try:
        project_ids = _project_ids(vault)
    except (OSError, ValueError):
        project_ids = set()
        diagnostics.append('project_registry_unreadable')

    suspects = []
    for row in catalog:
        suspect = _scope_suspect(row, project_ids)
        if suspect is not None:
            suspects.append(dict(memory_id=row.get('memory_id'), status=row.get('status'),
                                 **suspect,
                                 registered_project=suspect['project_dir'] in project_ids,
                                 reason=f"scope=user ama kaynak projeler/{suspect['project_dir']}/ altında"))

    pending_candidates = []
    for row in konsolidasyon.candidate_states(vault)['pending']:
        suspect = _scope_suspect(row, project_ids)
        if suspect is not None:
            pending_candidates.append(dict(candidate_id=row.get('candidate_id'), **suspect))

    return dict(
        check='scope_audit',
        checked_records=len(catalog),
        suspects=sorted(suspects, key=lambda row: row['memory_id'] or ''),
        active_suspect_count=sum(row['status'] == 'active' for row in suspects),
        pending_candidates=sorted(pending_candidates, key=lambda row: row['candidate_id'] or ''),
        diagnostics=diagnostics,
        canonical_writes=False,
        note='Salt okunur şüphe listesi; kapsam değişikliği insan incelemesi ve yeni aday/supersede akışıyla yapılır.',
    )


def _concepts(statement):
    # Keep the concept vocabulary aligned with hafiza.assess_candidate; only
    # this advisory audit's overlap threshold differs from candidate admission.
    ignored = ('kullanıcı', 'tercih', 'eder', 'ister', 'istiyor', 'istiyorum',
               'kullanır', 'kullanıyor')
    text = statement.casefold().replace('arka plan', 'zemin').replace('karanlık', 'koyu')
    return {word for word in gorev_baglam.content_words(text)
            if not any(gorev_baglam.inflected(base, word) for base in ignored)}


def _evidence_packet(vault, row):
    """Use catalog_relations' exact quote, revision and source secrecy gates."""
    try:
        source = bilgi_agi._safe(vault, row['source_path'])
        version = bilgi_agi.digest(source)
        content = source.read_text(encoding='utf-8')
        quote = row.get('evidence', '')
        if (not isinstance(quote, str) or len(quote) < 10 or quote not in content
                or hafiza.contains_secret(content)):
            return None
        if (row.get('source_content_hash') != hafiza.statement_hash(content)
                and not hafiza.current_source_binding(vault, row, content)):
            return None
    except (ValueError, OSError):
        return None
    peer = dict(id=row['memory_id'], title=row['subject_key'], kind='decision',
                statement=row['statement'], scope=row['scope'], domains=['all'],
                sources=[dict(path=row['source_path'], sha256=version, evidence=quote)])
    for field in ('rationale', 'conditions'):
        if isinstance(row.get(field), str) and row[field] in content:
            peer[field] = row[field]
    return jev_review.packet(peer), version


def _versions_unchanged(vault, versions):
    try:
        return all(bilgi_agi.digest(bilgi_agi._safe(vault, path)) == version
                   for path, version in versions.items())
    except (ValueError, OSError):
        return False


def active_conflict_audit(vault, scopes=None, jev_pairs=3, max_candidates=20) -> dict:
    """Find same-scope review pairs; advice never authorizes a catalog change."""
    vault = Path(vault)
    jev_pairs = max(0, min(10, int(jev_pairs)))
    max_candidates = max(0, int(max_candidates))
    catalog_path = vault / hafiza.CATALOG_PATH
    catalog_before = bilgi_agi.digest(catalog_path) if catalog_path.is_file() else None
    groups = {}
    excluded = 0
    for row in hafiza.load_catalog(vault):
        scope = row.get('scope')
        if (row.get('status') != 'active' or not hafiza.retrievable(row, scope)
                or (scopes is not None and scope not in scopes)
                or hafiza.contains_secret(row.get('statement', ''))):
            continue
        try:
            invalid = hafiza.context_record_errors(vault, row)
        except (ValueError, OSError):
            invalid = True
        if invalid:
            excluded += 1
            continue
        groups.setdefault(scope, []).append((row, _concepts(row['statement'])))

    candidates = []
    for scope, documents in groups.items():
        if len(documents) >= 4:
            # As in rank_records' informative terms, common names cannot turn
            # unrelated claims into matches. Count documents, not occurrences.
            vocabulary = set().union(*(words for _, words in documents))
            common = {word for word in vocabulary
                      if sum(any(gorev_baglam.word_match(word, other) for other in terms)
                             for _, terms in documents) > len(documents) / 2}
            documents = [(row, words - common) for row, words in documents]
        documents.sort(key=lambda item: item[0]['memory_id'])
        for (a, a_words), (b, b_words) in combinations(documents, 2):
            if a['memory_id'] >= b['memory_id']:
                continue
            shared = sorted(word for word in a_words
                            if any(gorev_baglam.word_match(word, other) for other in b_words))
            overlap = len(shared)
            minimum = min(len(a_words), len(b_words))
            ratio = overlap / max(1, minimum)
            same_subject = a['subject_key'] == b['subject_key']
            if not same_subject and not (minimum >= 2 and overlap >= 1 and ratio >= 0.5):
                continue
            pair = dict(scope=scope, a_id=a['memory_id'], b_id=b['memory_id'],
                        a_subject=a['subject_key'], b_subject=b['subject_key'],
                        a_statement=a['statement'], b_statement=b['statement'],
                        reason='same_subject_key' if same_subject else 'word_overlap',
                        shared_words=shared, overlap=overlap, ratio=round(ratio, 2), jev=None)
            key = (not same_subject, -overlap, -ratio, a['memory_id'], b['memory_id'])
            candidates.append((key, pair, a, b))
    candidates.sort(key=lambda item: item[0])
    selected = candidates[:max_candidates]
    checked = 0
    for _, pair, a, b in selected:
        if checked >= jev_pairs:
            break
        anchor, peer = _evidence_packet(vault, a), _evidence_packet(vault, b)
        if anchor is None or peer is None:
            pair['jev'] = dict(status='not_eligible', reason='exact_quote_evidence_missing')
            continue
        versions = {hafiza.CATALOG_PATH.as_posix(): catalog_before,
                    a['source_path']: anchor[1], b['source_path']: peer[1]}
        changed = dict(status='degraded', diagnostics=['source_changed_during_evaluation'])
        if (a['source_path'] == b['source_path'] and anchor[1] != peer[1]
                or not _versions_unchanged(vault, versions)):
            pair['jev'] = changed
            continue
        checked += 1
        try:
            evaluation = jev_client.evaluate(
                vault, json.dumps(dict(anchor=anchor[0]), ensure_ascii=False), [peer[0]],
                source_versions=versions, scope=pair['scope'], facets=jev_review.RELATIONS,
                purpose='memory_review')
        except Exception:
            evaluation = dict(degraded=True, diagnostics=['jev_evaluation_failed'])
        if not _versions_unchanged(vault, versions):
            pair['jev'] = changed
        elif evaluation.get('degraded'):
            pair['jev'] = dict(status='degraded', diagnostics=evaluation.get('diagnostics', []))
        elif evaluation.get('mode') == 'off':
            pair['jev'] = dict(status='disabled')
        else:
            values = evaluation.get('facet_scores', {})
            scores = {label: (values.get(i) or values.get(str(i)) or {}).get(b['memory_id'], 0)
                      for i, label in enumerate(('same_claim', 'incompatible', 'narrows'))}
            hits = [label for label, score in scores.items() if score >= 1.5]
            pair['jev'] = dict(status='advisory', scores=scores,
                               relation=hits[0] if len(hits) == 1 else 'uncertain')
    pairs = [pair for _, pair, _, _ in selected]
    return dict(check='active_conflict_audit',
                status='advisory' if any((pair['jev'] or {}).get('status') == 'advisory'
                                        for pair in pairs) else 'cheap_only',
                pairs=pairs, candidate_count=len(candidates),
                omitted_count=len(candidates) - len(selected), jev_checked=checked,
                jev_pair_limit=jev_pairs,
                diagnostics=[f'excluded_invalid_source:{excluded}'] if excluded else [],
                canonical_writes=False, requires_reviewer=True, auto_supersede=False,
                note='Yalnız inceleme adayı; supersede kararı insanda. Jev puanı onay değildir.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('kapsam')
    conflict = sub.add_parser('celiski')
    conflict.add_argument('--project-id')
    conflict.add_argument('--jev-pairs', type=int, default=3)
    args = parser.parse_args()
    if args.cmd == 'celiski':
        scopes = {'user', 'project:' + args.project_id} if args.project_id else None
        result = active_conflict_audit(args.vault, scopes=scopes, jev_pairs=args.jev_pairs)
    else:
        result = scope_audit(args.vault)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
