#!/usr/bin/env python3
"""Salt okunur katalog denetimleri; kayıt yazmaz, supersede etmez."""

import argparse
import json
from pathlib import Path

import hafiza


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('kapsam')
    args = parser.parse_args()
    print(json.dumps(scope_audit(args.vault), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
