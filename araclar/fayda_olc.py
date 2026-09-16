"""Compare labeled real-task observations; never invent missing measurements."""
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


@h.serialized
def record(vault, data, apply=False):
    """Review-only natural outcome ledger; no inferred quantities or ABC assignment."""
    allowed = {'task_id','condition','workflow','model','protocol_version','outcome',
               'session_id','source_snapshot','evidence_source','evidence','reviewed_by',
               'expected_version', *METRICS}
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


def summarize(rows):
    rows = latest_observations(rows)
    groups = {}; identities = set()
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
    return dict(status='no_observations' if not rows else 'descriptive_only',groups=output,
                observational_groups=[g for g in output if g['condition']=='observational'],
                experiment_groups=[g for g in output if g['condition']!='observational'],
                conclusion='Henüz fayda sonucu yok.' if not rows else
                'Ham sayımlar; koşullar ve görev zorluğu eşlenmeden nedensel kazanım iddia edilmez. Başarısız işler dahil.')


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
        p.add_argument('--observations',type=Path,required=True)
        a=p.parse_args()
        rows=[json.loads(line) for line in a.observations.read_text().splitlines() if line.strip()]
        result=summarize(rows)
    print(json.dumps(result,ensure_ascii=False,indent=2))
