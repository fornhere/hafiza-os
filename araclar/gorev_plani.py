"""Advisory conflict waves. Never executes tasks or grants a filesystem lease."""
import argparse
import hashlib
import json
from pathlib import Path
import jev_client


def validate(document):
    if not isinstance(document, dict):
        raise ValueError('plan_invalid')
    scope = document.get('scope')
    resources, tasks = document.get('resources'), document.get('tasks')
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError('scope_required')
    if not isinstance(resources, list) or not 1 <= len(resources) <= 32:
        raise ValueError('resources_budget')
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 32:
        raise ValueError('tasks_budget')
    def indexed(rows):
        if any(not isinstance(r, dict) or not isinstance(r.get('id'), str) or not r['id'] for r in rows):
            raise ValueError('id_invalid')
        result = {r['id']: r for r in rows}
        if len(result) != len(rows): raise ValueError('duplicate_id')
        return result
    resource_map, task_map = indexed(resources), indexed(tasks)
    for r in resources:
        if not isinstance(r.get('description'), str) or not r['description'].strip():
            raise ValueError('description_required')
        # Canonical logical namespace: caller must assign the same identity to aliases.
        key = r.get('key')
        if not isinstance(key, str) or not key or any(p in ('', '.', '..') for p in key.split('/')) or '\\' in key:
            raise ValueError('resource_key_invalid')
    for task in tasks:
        if not isinstance(task.get('description'), str) or not task['description'].strip():
            raise ValueError('description_required')
        if type(task.get('complete')) is not bool: raise ValueError('complete_required')
        for field, allowed in [('reads', resource_map), ('writes', resource_map), ('after', task_map)]:
            values = task.get(field)
            if not isinstance(values, list) or any(not isinstance(v, str) or v not in allowed for v in values):
                raise ValueError(field + '_invalid')
        if task['id'] in task['after']: raise ValueError('dependency_cycle')
    remaining = set(task_map)
    while remaining:
        ready = {i for i in remaining if not set(task_map[i]['after']) & remaining}
        if not ready: raise ValueError('dependency_cycle')
        remaining -= ready
    return resource_map, task_map


def overlap(a, b):
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def plan(document):
    resources, tasks = validate(document)
    blocked = {t['id'] for t in tasks.values() if not t['complete']}
    while True:
        expanded = blocked | {t['id'] for t in tasks.values() if set(t['after']) & blocked}
        if expanded == blocked: break
        blocked = expanded
    conflicts = []
    pairs = set()
    rows = list(tasks.values())
    for i, a in enumerate(rows):
        for b in rows[i+1:]:
            reasons = []
            for x in set(a['reads'] + a['writes']):
                for y in set(b['reads'] + b['writes']):
                    if (x in a['writes'] or y in b['writes']) and overlap(resources[x]['key'], resources[y]['key']):
                        reasons.append([x, y])
            if reasons:
                pairs.add(frozenset((a['id'], b['id'])))
                conflicts.append(dict(tasks=[a['id'], b['id']], resources=sorted(reasons)))
    waves, done = [], set()
    remaining = [i for i in tasks if i not in blocked]
    while remaining:
        wave = []
        for i in remaining:
            if set(tasks[i]['after']) <= done and all(frozenset((i, j)) not in pairs for j in wave):
                wave.append(i)
        if not wave: raise ValueError('dependency_unresolved')
        waves.append(wave)
        done.update(wave)
        remaining = [i for i in remaining if i not in done]
    digest = hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return dict(status='advisory', input_digest=digest, scope=document['scope'], waves=waves,
                blocked=sorted(blocked), conflicts=conflicts, execution_authorized=False,
                assumptions=['Caller supplied complete read/write sets and canonical resource aliases.',
                             'Input digest versions declarations only; no live source or lock verification.'])


def advise(vault, document, transport=None):
    resources, tasks = validate(document)
    if len(tasks) > 3: raise ValueError('mapping_task_budget')
    candidates = [dict(id=r['id'], title=r['id'], statement=r['description'],
                       scope=document['scope'], domains=[]) for r in resources.values()]
    result = jev_client.evaluate(vault, 'Map tasks to known resources; no execution authority.', candidates,
                                facets=[t['description'] for t in tasks.values()],
                                scope=document['scope'], source_versions={'plan': plan(document)['input_digest']},
                                purpose='task_resource_mapping', transport=transport)
    # Advisory output deliberately has no path into plan() declarations.
    suggestions = {}
    for n, task in enumerate(tasks.values()):
        scores = result.get('facet_scores', {}).get(n, {})
        suggestions[task['id']] = [i for i in resources if scores.get(i, 0) >= 1.5]
    return dict(suggestions=suggestions, jev=result, execution_authorized=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-json', type=Path, required=True)
    parser.add_argument('--vault', type=Path)
    parser.add_argument('--jev', action='store_true')
    args = parser.parse_args()
    if args.input_json.stat().st_size > 100000: parser.error('input_budget')
    doc = json.loads(args.input_json.read_text())
    output = plan(doc)
    if args.jev:
        if not args.vault: parser.error('--jev requires --vault')
        output['mapping'] = advise(args.vault, doc)
    print(json.dumps(output, ensure_ascii=False, indent=2))
