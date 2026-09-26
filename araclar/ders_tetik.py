#!/usr/bin/env python3
"""Measure lexical lesson triggers; harness failures never become zero recall."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import ders_baglam
import hafiza as h
import is_ve_ders
from gelisim_dongusu import validate_review, write, snapshot_valid, digest

VERSION = 1
BUDGET = 200000


class HarnessError(Exception):
    pass


def validate(spec):
    if not isinstance(spec,dict) or type(spec.get('schema')) is not int or spec['schema']!=VERSION:
        raise ValueError('schema_invalid')
    validate_review(spec)
    try: serialized=json.dumps(spec,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError): raise ValueError('spec_invalid') from None
    if h.contains_secret(serialized): raise ValueError('spec_contains_secret')
    cases=spec.get('cases')
    if not isinstance(cases,list) or not 1<=len(cases)<=50: raise ValueError('cases_invalid')
    seen=set()
    for case in cases:
        if not isinstance(case,dict) or not isinstance(case.get('lesson_id'),str) or not case['lesson_id'].strip():
            raise ValueError('lesson_id_invalid')
        if case['lesson_id'] in seen: raise ValueError('duplicate_lesson_id')
        seen.add(case['lesson_id'])
        if case.get('project_id') is not None and not isinstance(case['project_id'],str):
            raise ValueError('project_id_invalid')
        workflows=case.get('workflow_ids',[])
        if not isinstance(workflows,list) or any(not isinstance(w,str) for w in workflows):
            raise ValueError('workflow_ids_invalid')
        for field in ('should_trigger','should_not_trigger'):
            prompts=case.get(field)
            if (not isinstance(prompts,list) or not 3<=len(prompts)<=10
                    or any(not isinstance(p,str) or not p.strip() or len(p)>1500 for p in prompts)
                    or len(prompts)!=len(set(prompts))):
                raise ValueError(field+'_invalid')
        if set(case['should_trigger']) & set(case['should_not_trigger']): raise ValueError('prompt_overlap')


def _eligible(vault, row, case):
    ident=case['lesson_id']; reason=None
    if row.get('status')=='rejected': reason='rejected'
    elif 'review_required' in row: reason='review_required'
    elif row.get('outcome_id') and row.get('status')!='verified': reason='outcome_unverified'
    else:
        try:
            reason=ders_baglam._integrity(vault,row)
            allowed={case.get('project_id'),*case.get('workflow_ids',[])}-{None}
            owner=row.get('project_id'); scope=row.get('scope','global' if not owner else 'project:'+owner)
            if not reason and (owner and owner not in allowed or scope not in {'global','user'}
                    and not (scope.startswith('project:') and scope[8:] in allowed)):
                reason='scope_mismatch'
        except (OSError,ValueError,KeyError,TypeError,AttributeError): reason='lesson_invalid'
    if reason: raise HarnessError(f'lesson_ineligible:{ident}:{reason}')


def _snapshot_check(vault, versions):
    try: valid=snapshot_valid(vault,versions)
    except (OSError,ValueError): valid=False
    if not valid: raise HarnessError('snapshot_changed')


def _hit(vault, prompt, case, versions):
    ident=case['lesson_id']
    try:
        details=ders_baglam.context_details(vault,prompt,budget=BUDGET,
            project_id=case.get('project_id'),workflow_ids=case.get('workflow_ids',[]))
        if (not isinstance(details,dict) or not isinstance(details.get('text'),str)
                or not isinstance(details.get('lessons'),list) or not isinstance(details.get('diagnostics'),list)
                or any(not isinstance(r,dict) or not isinstance(r.get('id'),str)
                       or not {'id','version','status'}<=r.keys() for r in details['lessons'])
                or any(not isinstance(r,dict) or not isinstance(r.get('id'),str)
                       or not isinstance(r.get('reason'),str) for r in details['diagnostics'])):
            raise ValueError('context_result_invalid')
    except Exception as exc:
        raise HarnessError(f'context_failed:{ident}:{type(exc).__name__}') from exc
    reasons=[r['reason'] for r in details['diagnostics'] if r['id']==ident]
    if 'budget' in reasons: raise HarnessError('budget_interference:'+ident)
    if reasons:
        _snapshot_check(vault,versions)
        raise HarnessError(f'lesson_ineligible:{ident}:{reasons[0]}')
    return any(r['id']==ident for r in details['lessons'])


def _publish(output, report):
    # Stage with the shared atomic writer, then publish without replacing any winner.
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent,prefix='.ders-tetik-') as tmp:
        staged=Path(tmp)/'report.json'; write(staged,report)
        try: os.link(staged,output)
        except FileExistsError: raise ValueError('output_exists') from None


def run(vault, spec, output):
    output=Path(output)
    if output.exists() or output.is_symlink(): raise ValueError('output_exists')
    validate(spec); spec=copy.deepcopy(spec); vault=Path(vault).resolve()
    ledger=vault/is_ve_ders.LESSONS
    try:
        # Pin before latest() so a concurrent ledger edit cannot bless stale rows.
        versions={is_ve_ders.LESSONS.as_posix():hashlib.sha256(h.source_file(vault,str(is_ve_ders.LESSONS)).read_bytes()).hexdigest()} if ledger.exists() else {}
        rows=is_ve_ders.latest(vault,'lesson')
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise HarnessError('ledger_failed:'+type(exc).__name__) from exc
    for case in spec['cases']:
        ident=case['lesson_id']
        if ident not in rows: raise HarnessError('lesson_missing:'+ident)
    if not versions: raise HarnessError('snapshot_changed')
    for case in spec['cases']:
        ident=case['lesson_id']; row=rows[ident]
        for field,reason in [('source_path','source_changed'),('method_path','method_missing'),('verification_path','verification_changed')]:
            if not row.get(field): continue
            try:
                path=h.source_file(vault,row[field])
                name=Path(os.path.abspath(vault/row[field])).relative_to(vault).as_posix()
                sha=hashlib.sha256(path.read_bytes()).hexdigest()
            except (OSError,ValueError,TypeError) as exc:
                raise HarnessError(f'lesson_ineligible:{ident}:{reason}') from exc
            if name in versions and versions[name]!=sha: raise HarnessError('snapshot_changed')
            versions[name]=sha
    _snapshot_check(vault,versions)
    for case in spec['cases']: _eligible(vault,rows[case['lesson_id']],case)
    lessons=[]
    for case in spec['cases']:
        ident=case['lesson_id']; result=dict(lesson_id=ident,version=rows[ident].get('version'))
        for field in ('should_trigger','should_not_trigger'):
            hits=[_hit(vault,p,case,versions) for p in case[field]]
            errors=[p for p,hit in zip(case[field],hits) if hit==(field=='should_not_trigger')]
            result[field]=dict(total=len(hits),hits=sum(hits),**{('missed' if field=='should_trigger' else 'false_triggers'):errors})
        result.update(recall=result['should_trigger']['hits']/result['should_trigger']['total'],
                      false_trigger_rate=result['should_not_trigger']['hits']/result['should_not_trigger']['total'])
        lessons.append(result)
    _snapshot_check(vault,versions)
    report=dict(schema=VERSION,status='measured',spec_digest=digest(spec),label_review=copy.deepcopy(spec['label_review']),
        source_versions=versions,generated_at=datetime.now(timezone.utc).isoformat(),lessons=lessons,
        recall=sum(r['should_trigger']['hits'] for r in lessons)/sum(r['should_trigger']['total'] for r in lessons),
        false_trigger_rate=sum(r['should_not_trigger']['hits'] for r in lessons)/sum(r['should_not_trigger']['total'] for r in lessons),
        note='Bu bir sözcük tetiği ölçümüdür; dersin faydasının kanıtı değildir. Toplam oranlar micro ortalamadır.')
    try: _publish(output,report)
    except OSError as exc: raise HarnessError('output_failed:'+type(exc).__name__) from exc
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    command=commands.add_parser('run')
    for name in ('vault','spec','output'): command.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:
        try: spec=json.loads(args.spec.read_text(encoding='utf-8'))
        except (OSError,ValueError): raise ValueError('spec_invalid') from None
        report=run(args.vault,spec,args.output)
    except (HarnessError,ValueError) as exc:
        print(json.dumps(dict(status='error',error=str(exc)),ensure_ascii=False),file=sys.stderr)
        return 2
    print(json.dumps(report,ensure_ascii=False))
    return 0


if __name__=='__main__':
    sys.exit(main())
