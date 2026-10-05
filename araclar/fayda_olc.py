"""Compare labeled real-task observations; never invent missing measurements."""
import sys
import argparse
import json
import math
import statistics
import datetime as dt

import hafiza as h
import capture_source as capture
from pathlib import Path


OBSERVATIONS = Path('zihin/fayda-gozlemleri.jsonl')
METRICS = ('repeat_explanations','correction_rounds','elapsed_seconds','maintenance_seconds')
OUTCOMES = ('accepted','rejected','abandoned','unknown')

DELIVERIES = Path('günlük/hafıza-makbuzları/lesson-deliveries.jsonl')
UTILITY_RECEIPTS = Path('günlük/hafıza-makbuzları/lesson-utility.jsonl')


def record_delivery(vault, **data):
    """Hook-safe: a receipt problem is a diagnostic, never a lost context."""
    if not data.get('delivered_lessons'):
        return None
    try:
        from is_ve_ders import LESSONS
        known = {(r['id'], r['version']) for r in h.load_jsonl(Path(vault) / LESSONS)
                 if type(r.get('version')) is int}
        data['delivered_lessons'] = [r for r in data['delivered_lessons'] if isinstance(r, dict)
                                     and (r.get('id'), r.get('version')) in known]
        if not data['delivered_lessons']:
            return None
        return _record_delivery(vault, **data)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f'hafiza: ders teslim makbuzu yazılamadı: {type(error).__name__}', file=sys.stderr)
        return None


@h.serialized
def _record_delivery(vault, *, client, session_id, package_id, delivered_lessons,
                    turn_id, task_id=None, source_end_line=None):
    """Persist final-text delivery identity, never application or benefit."""
    if not delivered_lessons:
        return None
    from is_ve_ders import LESSONS
    versions = {(r['id'], r['version']) for r in h.load_jsonl(vault / LESSONS) if type(r.get('version')) is int}
    if any(not isinstance(r, dict) or set(r) != {'id', 'version'}
           or type(r['version']) is not int or (r['id'], r['version']) not in versions
           for r in delivered_lessons):
        raise ValueError('delivered_lessons_invalid')
    if not all(isinstance(x, str) and x.strip() for x in (client, session_id, package_id, turn_id)):
        raise ValueError('delivery_identity_required')
    row = dict(client=client, session_id=session_id, package_id=package_id,
               turn_id=turn_id, task_id=task_id, source_end_line=source_end_line,
               delivered_lessons=sorted(delivered_lessons, key=lambda r:r['id']))
    row['receipt_id'] = capture.digest(row)
    old = next((r for r in h.load_jsonl(vault / DELIVERIES)
                if r.get('receipt_id') == row['receipt_id']), None)
    if old:
        return old
    row['at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    h._append_jsonl(vault / DELIVERIES, row)
    return row


def _precedes(delivered, outcome):
    try:
        start=dt.datetime.fromisoformat(delivered.replace('Z','+00:00'))
        end=dt.datetime.fromisoformat(outcome.replace('Z','+00:00'))
        return bool(start.tzinfo and end.tzinfo and start <= end)
    except (ValueError,TypeError,AttributeError):
        return False


def read_lesson_results(vault):
    """Shared, source-checked adapter for both historical utility schemas.

    Legacy versioned application assertions remain distinct from delivery links.
    ID-only observations never acquire today's lesson version implicitly.
    """
    from is_ve_ders import TASKS, LESSONS
    from bilgi_agi import _safe, digest
    versions = {(r['id'], r['version']) for r in h.load_jsonl(vault / LESSONS) if type(r.get('version')) is int}
    deliveries = h.load_jsonl(vault / DELIVERIES)
    observations = latest_observations(h.load_jsonl(vault / OBSERVATIONS))
    events = []; seen = set(); used = set(); unlinked = 0
    rows = [('outcome', r) for r in h.load_jsonl(vault / Path('gelen-kutusu/lesson-outcomes.jsonl'))]
    rows += [('observation', r) for r in observations]
    prior = {}
    for r in h.load_jsonl(vault / TASKS):
        old = prior.get(r['id']); prior[r['id']] = r
        if old and old['status'] != r['status'] and r['status'] in ('done', 'cancelled'):
            rows.append(('transition', dict(r, task_id=r['id'], outcome='accepted' if r['status']=='done' else 'abandoned')))
    for schema, row in rows:
        result = row.get('observed_result', row.get('outcome', 'unknown'))
        session = row.get('actor_session_id', row.get('session_id'))
        if isinstance(row.get('acceptance_source'), dict):
            session = row['acceptance_source'].get('session_id')
        evidence = None
        at = row.get('recorded_at', row.get('updated_at', row.get('at')))
        try:
            if schema == 'observation':
                capture.validate_candidate_evidence(vault, session, row['source_snapshot'],
                                                    row['evidence_source'], row['evidence'])
                evidence = dict(schema=schema, source=row['evidence_source'])
            elif schema == 'transition':
                if row.get('assertion_kind') == 'assistant_report':
                    raise ValueError('assistant_report_not_result')
                path = h.source_file(vault, row['source_path']); content = path.read_text(encoding='utf-8')
                if h.statement_hash(content) != row['source_content_hash'] or row['evidence'] not in content:
                    raise ValueError('task_source_changed')
                evidence = dict(schema=schema, path=row['source_path'], sha256=row['source_content_hash'], task_version=row['version'])
            else:
                path = _safe(vault, row['verification_path']); content = path.read_text(encoding='utf-8')
                if digest(path) != row['verification_hash'] or len(row['verification_evidence']) < 20 or row['verification_evidence'] not in content:
                    raise ValueError('verification_source_changed')
                if row['verification_kind'] == 'test_result':
                    receipt = json.loads(content); success = result == 'passed'
                    at = receipt.get('finished_at')
                    if result not in ('passed','failed') or receipt.get('task_id') != row['task_id'] or type(receipt.get('exit_code')) is not int or (receipt['exit_code']==0) != success or receipt.get('passed') is not success or not receipt.get('command') or not receipt.get('finished_at'):
                        raise ValueError('runner_receipt_result_mismatch')
                elif row['verification_kind'] == 'user_acceptance':
                    if result not in ('accepted','rejected'): raise ValueError('user_acceptance_required')
                    if not row.get('acceptance_source') and not row.get('applied_lessons'):
                        raise ValueError('acceptance_source_required')
                    if row.get('acceptance_source'):
                        from is_ve_ders import validate_acceptance_source
                        validate_acceptance_source(vault, row['acceptance_source'])
                else: raise ValueError('external_result_required')
                evidence = dict(schema=schema, path=row['verification_path'], sha256=row['verification_hash'])
        except (ValueError, OSError, KeyError, TypeError):
            unlinked += 1; continue
        identity = row.get('receipt_id', row.get('observation_hash', capture.digest(row)))
        evidence_key = evidence.get('sha256', capture.digest(evidence))
        if schema == 'transition':
            evidence_key = capture.digest(evidence)
        if schema == 'observation' or row.get('acceptance_source'):
            origin = row['evidence_source'] if schema == 'observation' else row['acceptance_source']['evidence_source']
            evidence_key = capture.digest({k:origin.get(k) for k in ('session_id','path','line','message_hash')})
        matches = [r for r in deliveries if
                   ((r.get('task_id') and r['task_id'] == row.get('task_id')) or
                    (not r.get('task_id') and session and r.get('session_id') == session))
                   and at and _precedes(r['at'],at)
                   and (schema != 'outcome' or row.get('verification_kind') != 'user_acceptance' or row.get('acceptance_source'))
                   and (schema != 'observation' or
                        (r.get('source_end_line') is not None and row['evidence_source']['line'] > r['source_end_line']) or
                        (r.get('task_id') and r['task_id'] == row['task_id'] and r.get('source_end_line') is None))]
        links = []
        for delivery in matches:
            for item in delivery['delivered_lessons']:
                if (item['id'], item['version']) in versions:
                    links.append(dict(item, delivery_id=delivery['receipt_id'], attribution='delivered'))
        # The old outcome writer already validates explicit ID+version assertions.
        if schema == 'outcome':
            for item in row.get('applied_lessons', []):
                if isinstance(item, dict) and type(item.get('version')) is int and (item.get('id'), item['version']) in versions:
                    links.append(dict(item, attribution='legacy_applied'))
        if not links:
            unlinked += 1; continue
        for item in links:
            key = (item['id'], item['version'], row['task_id'], evidence_key)
            if item.get('delivery_id') and result != 'unknown': used.add(item['delivery_id'])
            if key in seen: continue
            seen.add(key)
            events.append(dict(item, task_id=row['task_id'], result=result,
                               outcome_id=identity, evidence_source=evidence, evidence_hash=evidence_key))
    unknown = [dict(r, result='unknown') for r in deliveries if r['receipt_id'] not in used]
    return dict(events=events, unknown_deliveries=unknown,
                linked_results=len({r['outcome_id'] for r in events}), unlinked_results=unlinked,
                unknown_deliveries_count=len(unknown))


@h.serialized
def record(vault, data, apply=False):
    """Review-only natural outcome ledger; no inferred quantities or ABC assignment."""
    allowed = {'task_id','condition','workflow','model','protocol_version','outcome',
               'session_id','source_snapshot','evidence_source','evidence','reviewed_by',
               'expected_version','applied_lessons', *METRICS}
    if set(data) - allowed: raise ValueError('unknown observation fields')
    if data.get('reviewed_by') != 'codex-consolidator':
        raise ValueError('approved reviewer codex-consolidator required')
    for name in ('task_id','workflow','model','protocol_version','session_id','evidence'):
        if not isinstance(data.get(name),str) or not data[name].strip():
            raise ValueError(name + ' required')
    if data.get('condition') != 'observational' or data.get('outcome') not in OUTCOMES:
        raise ValueError('natural outcome requires observational condition')
    if any(data.get(field) is not None for field in METRICS):
        raise ValueError('outcome-only writer: human measurements must remain null')
    if h.contains_secret(json.dumps(data,ensure_ascii=False)):
        raise ValueError('secrets cannot be recorded')
    if 'applied_lessons' in data:
        from is_ve_ders import latest, LESSONS
        applied=data['applied_lessons'];lessons=latest(vault,'lesson')
        versions={(r['id'],r['version']) for r in h.load_jsonl(vault/LESSONS) if type(r.get('version')) is int}
        if not isinstance(applied,list) or len(applied)>20:raise ValueError('applied_lessons_invalid')
        seen=set()
        for item in applied:
            if isinstance(item,str):
                ident=item;valid=bool(item.strip()) and item in lessons
            elif isinstance(item,dict):
                ident=item.get('id');valid=(set(item)=={'id','version'} and isinstance(ident,str)
                    and type(item['version']) is int and (ident,item['version']) in versions)
            else: ident=None;valid=False
            if not valid or ident in seen:raise ValueError('applied_lessons_invalid')
            seen.add(ident)
    source = data.get('source_snapshot')
    if not isinstance(source,dict) or type(source.get('prefix_end_line')) is not int:
        raise ValueError('completed prefix source_snapshot required')
    capture.validate_candidate_evidence(vault,data['session_id'],source,
                                        data.get('evidence_source'),data['evidence'])
    # Persist only stable source identity, excluding incidental file-size/timing noise.
    source_keys = ('session_id','path','prefix_end_line','prefix_hash','source_hash')
    row = {k: data[k] for k in ('task_id','condition','workflow','model','protocol_version',
                                'outcome','session_id','evidence','reviewed_by')}
    row['source_snapshot'] = {k:source[k] for k in source_keys}
    row['evidence_source'] = {k:data['evidence_source'][k]
                             for k in (*source_keys,'line','message_hash','quote')}
    row.update({field:None for field in METRICS})
    if 'applied_lessons' in data:row['applied_lessons']=sorted(data['applied_lessons'],key=lambda r:r if isinstance(r,str) else r['id'])
    row['observation_hash'] = capture.digest(row)
    history = h.load_jsonl(vault / OBSERVATIONS)
    task_rows = [r for r in history if r['task_id']==row['task_id']]
    for previous in task_rows:
        if previous['observation_hash']==row['observation_hash']:
            return dict(status='unchanged',observation=previous)
    previous = task_rows[-1] if task_rows else None
    expected = data.get('expected_version',0)
    if type(expected) is not int or expected != (previous['version'] if previous else 0):
        raise ValueError('expected_version does not match current observation')
    if previous and any(previous[k]!=row[k] for k in ('workflow','model','protocol_version')):
        raise ValueError('task observation identity cannot change')
    row.update(version=expected+1,updated_at=dt.datetime.now(dt.timezone.utc).isoformat())
    if apply: h._append_jsonl(vault / OBSERVATIONS,row)
    return dict(status='recorded' if apply else 'dry_run',observation=row)


def latest_observations(rows):
    latest = {}
    for row in rows:
        if not isinstance(row,dict) or not row.get('task_id') or not row.get('condition'):
            raise ValueError('observation task identity required')
        key = (row['task_id'],row['condition'])
        previous = latest.get(key)
        if previous:
            if (row.get('condition') != 'observational' or
                type(previous.get('version')) is not int or
                type(row.get('version')) is not int or
                row['version'] != previous['version']+1):
                raise ValueError('duplicate or nonsequential task observation')
            if any(previous.get(k)!=row.get(k) for k in ('workflow','model','protocol_version')):
                raise ValueError('observation identity changed')
        latest[key]=row
    return list(latest.values())


def summarize(rows, vault=None):
    rows = latest_observations(rows)
    groups = {}; identities = set(); lessons = {}
    for row in rows:
        required = ('task_id','condition','workflow','model','protocol_version','outcome','evidence_source')
        if any(not row.get(k) for k in required):
            raise ValueError('observation identity, protocol and evidence source required')
        if row['condition'] not in ('A','B','C','observational') or row['outcome'] not in ('accepted','rejected','abandoned','unknown'):
            raise ValueError('invalid condition/outcome')
        key = (row['task_id'],row['condition'])
        if key in identities: raise ValueError('duplicate task observation')
        identities.add(key)
        for field in ('repeat_explanations','correction_rounds','elapsed_seconds','maintenance_seconds'):
            value = row.get(field)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                raise ValueError('invalid measurement: '+field)
        group_key = (row['workflow'],row['model'],row['protocol_version'],row['condition'])
        groups.setdefault(group_key,[]).append(row)
        for item in row.get('applied_lessons',[]):
            ident=item if isinstance(item,str) else item['id']
            lessons.setdefault(ident,{outcome:0 for outcome in OUTCOMES})[row['outcome']]+=1
    output=[]
    for (workflow,model,protocol,condition), tasks in sorted(groups.items()):
        counts={outcome:sum(t['outcome']==outcome for t in tasks) for outcome in ('accepted','rejected','abandoned','unknown')}
        result=dict(workflow=workflow,model=model,protocol_version=protocol,condition=condition,
                    tasks=len(tasks),outcomes=counts,measurements={})
        for field in ('repeat_explanations','correction_rounds','elapsed_seconds','maintenance_seconds'):
            values=[t[field] for t in tasks if t.get(field) is not None]
            result['measurements'][field]=dict(observed=len(values),missing=len(tasks)-len(values),
                total=sum(values) if values else None,median=statistics.median(values) if values else None)
        output.append(result)
    summary = dict(status='no_observations' if not rows else 'descriptive_only',groups=output,
                lessons=lessons,
                observational_groups=[g for g in output if g['condition']=='observational'],
                experiment_groups=[g for g in output if g['condition']!='observational'],
                conclusion='Henüz fayda sonucu yok.' if not rows else
                'Ham sayımlar; koşullar ve görev zorluğu eşlenmeden nedensel kazanım iddia edilmez. Başarısız işler dahil.')
    if vault is not None: summary['lesson_results'] = read_lesson_results(vault)
    return summary


if __name__=='__main__':
    import sys
    p=argparse.ArgumentParser()
    if len(sys.argv)>1 and sys.argv[1]=='record':
        p.add_argument('command',choices=['record'])
        p.add_argument('--vault',type=Path,required=True)
        p.add_argument('--input-json',type=Path,required=True)
        p.add_argument('--apply',action='store_true')
        a=p.parse_args()
        result=record(a.vault,json.loads(a.input_json.read_text()),a.apply)
    else:
        p.add_argument('--vault',type=Path)
        p.add_argument('--observations',type=Path)
        a=p.parse_args()
        if not a.observations and not a.vault:p.error('--vault or --observations required')
        rows=h.load_jsonl(a.observations or a.vault.resolve()/OBSERVATIONS)
        result=summarize(rows,vault=a.vault.resolve() if a.vault else None)
    print(json.dumps(result,ensure_ascii=False,indent=2))
