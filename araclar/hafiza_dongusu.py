#!/usr/bin/env python3
"""Explicit, bounded maintenance entrypoint; never called by synchronous hooks."""
import argparse
import datetime as dt
import hashlib
import json
import unicodedata
from pathlib import Path
import hafiza as h
import bilgi_agi as b
import jev_review
import jev_client

RECEIPTS = Path('günlük/hafıza-makbuzları/lifecycle-review.jsonl')
OUTCOMES = Path('gelen-kutusu/lesson-outcomes.jsonl')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@h.serialized
def append_once(vault, path, row):
    existing = h.load_jsonl(vault/path)
    old = next((r for r in reversed(existing) if r['receipt_id'] == row['receipt_id']), None)
    if old and not (path == RECEIPTS and old.get('status') in ('degraded','disabled')):
        return dict(row=old, changed=False)
    if path == RECEIPTS: row = dict(row, attempt=1+sum(r['receipt_id']==row['receipt_id'] for r in existing))
    h._append_jsonl(vault/path, row)
    return dict(row=row, changed=True)


def catalog_relations(vault, candidate, proposal):
    """Bounded semantic comparison to current, exact-quoted canonical peers."""
    peers=[]
    catalog_path=vault/h.CATALOG_PATH
    catalog_before=b.digest(catalog_path) if catalog_path.is_file() else None
    for row in h.load_catalog(vault):
        if row.get('scope')!=candidate['scope'] or not h.retrievable(row,candidate['scope']):continue
        if h.context_record_errors(vault,row):continue
        try:
            source=b._safe(vault,row['source_path']);content=source.read_text(encoding='utf-8')
            quote=row.get('evidence','')
            if len(quote)<10 or quote not in content or h.contains_secret(content):continue
            if row.get('source_content_hash')!=h.statement_hash(content) and not h.current_source_binding(vault,row,content):continue
        except (ValueError,OSError):continue
        peer=dict(id=row['memory_id'],title=row['subject_key'],kind='decision',statement=row['statement'],scope=row['scope'],domains=['all'],sources=[dict(path=row['source_path'],sha256=b.digest(source),evidence=quote)])
        for field in ('rationale','conditions'):
            if isinstance(row.get(field),str) and row[field] in content:peer[field]=row[field]
        peers.append(peer)
    peers.sort(key=lambda r:(r['title']!=candidate['subject_key'],r['id']))
    omitted=max(0,len(peers)-8);peers=peers[:8]
    result=dict(comparisons=[],omitted_count=omitted,checked_count=0,status='not_needed')
    if not peers:return result
    versions={h.CATALOG_PATH.as_posix():catalog_before}
    for row in peers+[proposal]:versions.update({r['path']:r['sha256'] for r in row['sources']})
    try:unchanged=all(b.digest(b._safe(vault,path))==sha for path,sha in versions.items())
    except (ValueError,OSError):unchanged=False
    if not unchanged:
        result.update(status='degraded',diagnostics=['source_changed_before_evaluation']);return result
    evaluation=jev_client.evaluate(vault,json.dumps(dict(anchor=jev_review.packet(proposal)),ensure_ascii=False),[jev_review.packet(r) for r in peers],source_versions=versions,scope=candidate['scope'],facets=jev_review.RELATIONS,purpose='memory_review')
    try:unchanged=all(b.digest(b._safe(vault,path))==sha for path,sha in versions.items())
    except (ValueError,OSError):unchanged=False
    if not unchanged or evaluation.get('degraded'):
        result.update(status='degraded',diagnostics=['source_changed_or_service_failure']);return result
    if evaluation.get('mode')=='off':result['status']='disabled';return result
    values=evaluation.get('facet_scores',{})
    for row in peers:
        scores={label:(values.get(i) or values.get(str(i)) or {}).get(row['id'],0) for i,label in enumerate(('same_claim','incompatible','narrows'))}
        hits=[k for k,v in scores.items() if v>=1.5]
        result['comparisons'].append(dict(source_id=row['id'],target_id=candidate['candidate_id'],relation=hits[0] if len(hits)==1 else 'uncertain',scores=scores))
    result.update(status='advisory',checked_count=len(peers));return result


def review_pending(vault, project_id=None, limit=5, apply=False, conflict_pairs=3):
    from konsolidasyon import pending
    vault=Path(vault); limit=max(1,min(20,int(limit)))
    scopes={'user', 'project:'+project_id if project_id else 'user'}
    proposals=[]
    for c in pending(vault):
        if c['scope'] not in scopes: continue
        proposals.append(('catalog',c['candidate_id'],c))
    for path in sorted((vault/'bilgi').glob('*.md')):
        if path.name=='README.md':continue
        try: c=b._read(path)
        except (ValueError,KeyError,OSError):continue
        if c['status']=='proposed' and c['scope'] in scopes:proposals.append(('knowledge',c['id'],c))
    prior=h.load_jsonl(vault/RECEIPTS)
    last_attempt={r['candidate_id']:r.get('at','') for r in prior}
    proposals.sort(key=lambda item:(last_attempt.get(item[1],''),item[1]))
    done={r['receipt_id'] for r in prior if r.get('status') not in ('degraded','disabled')}
    results=[]; skipped=0
    # Config and comparison corpus invalidate previous advice, as do source revisions.
    corpus={p.relative_to(vault).as_posix():b.digest(p) for p in sorted((vault/'bilgi').glob('*.md'))}
    if (vault/h.CATALOG_PATH).exists():corpus[h.CATALOG_PATH.as_posix()]=b.digest(vault/h.CATALOG_PATH)
    # Peer eligibility depends on source files too, not only stored pinned hashes.
    peer_paths=set()
    for path in sorted((vault/'bilgi').glob('*.md')):
        if path.name=='README.md':continue
        try:
            peer=b._read(path)
            peer_paths.update(source['path'] for source in peer['sources'])
            peer_paths.update(example['path'] for example in peer.get('examples',[]))
        except (ValueError,KeyError,OSError):continue
    peer_paths.update(row['source_path'] for row in h.load_catalog(vault))
    for path in sorted(peer_paths):
        try:
            target=Path(path) if Path(path).is_absolute() else b._safe(vault,path)
            corpus['source:'+path]=b.digest(target)
        except (ValueError,OSError):corpus['source:'+path]='unavailable'
    config=jev_client.inspect_config(vault)
    config_path=vault/'komuta/jev.json'
    config['revision']=b.digest(config_path) if config_path.is_file() else 'default'
    for kind,ident,c in proposals:
        versions={}
        try:
            paths=[s['path'] for s in c['sources']] if kind=='knowledge' else [c['source_path']]
            versions={path:b.digest(b._safe(vault,path)) for path in paths}
        except (ValueError,OSError):pass
        key=fingerprint(dict(candidate=c,versions=versions,corpus=corpus,config=config))
        if key in done: skipped+=1;continue
        if len(results)>=limit:break
        try:
            if kind=='catalog':
                source=b._safe(vault,c['source_path']); text=source.read_text(encoding='utf-8')
                if h.statement_hash(text)!=c.get('source_content_hash') or c.get('evidence','') not in text or len(c.get('evidence',''))<10:raise ValueError('candidate_source_changed_or_unquoted')
                if c.get('evidence_source'):
                    from capture_source import validate_candidate_evidence
                    origin=c['evidence_source'];validate_candidate_evidence(vault,origin.get('session_id'),origin,origin,c['evidence'])
                proposal=dict(id='candidate-'+ident,title=c['subject_key'],kind='decision',statement=c['statement'],scope=c['scope'],domains=['all'],status='proposed',sources=[dict(path=c['source_path'],sha256=b.digest(source),evidence=c['evidence'])])
                for field in ('rationale','conditions'):
                    if field in c:proposal[field]=c[field]
            else:proposal=c
            # Registered proposed notes use exact same gate without temporary deletion.
            advice=jev_review.audit_proposed(vault,proposal,project_id,allow_registered=(kind=='knowledge'))
            if kind=='catalog' and advice['status'] not in ('degraded','disabled'):
                advice['catalog_relations']=catalog_relations(vault,c,proposal)
                if advice['catalog_relations']['status']=='degraded':advice['status']='degraded'
        except (ValueError,OSError,KeyError,TypeError):advice=dict(status='degraded',diagnostics=['source_or_policy_validation_failed'])
        row=dict(receipt_id=key,candidate_id=ident,queue=kind,deterministic_assessment=c.get('assessment'),status=advice['status'],advice=advice,at=dt.datetime.now(dt.timezone.utc).isoformat(),canonical_writes=False)
        results.append(append_once(vault,RECEIPTS,row) if apply else dict(row=row,changed=False))
    result=dict(reviews=results,already_reviewed=skipped,limit=limit,pending_total=len(proposals),applied=apply,requires_reviewer=True)
    try:
        from kayit_denetimi import active_conflict_audit
        result['active_conflicts']=active_conflict_audit(vault,scopes=scopes,jev_pairs=max(0,min(10,int(conflict_pairs))))
    except Exception:
        result['active_conflicts']=dict(status='degraded',diagnostics=['conflict_audit_failed'],pairs=[],canonical_writes=False)
    return result


def outcome(vault,data,apply=False):
    """Queue externally verifiable work evidence; never self-promote lessons."""
    from is_ve_ders import latest, validate_acceptance_source
    vault=Path(vault)
    required=('task_id','title','lesson','conditions','method_path','verification_path','verification_evidence','verification_hash','verification_kind','observed_result','actor')
    if any(not isinstance(data.get(k),str) or not data[k].strip() for k in required):raise ValueError('outcome_fields_required')
    if h.contains_secret(json.dumps(data,ensure_ascii=False)):raise ValueError('restricted_outcome')
    if 'actor_session_id' in data and (not isinstance(data['actor_session_id'],str) or not data['actor_session_id'].strip() or len(data['actor_session_id'])>200):raise ValueError('actor_session_id_invalid')
    if 'acceptance_source' in data:validate_acceptance_source(vault,data['acceptance_source'])
    if 'applied_lessons' in data:
        lessons=latest(vault,'lesson');applied=data['applied_lessons'];seen=set()
        if not isinstance(applied,list) or len(applied)>20:raise ValueError('applied_lessons_invalid')
        for item in applied:
            if (not isinstance(item,dict) or set(item)!={'id','version'} or not isinstance(item['id'],str)
                or item['id'] in seen or item['id'] not in lessons or type(item['version']) is not int
                or not 1<=item['version']<=lessons[item['id']]['version']):raise ValueError('applied_lessons_invalid')
            seen.add(item['id'])
        data=dict(data,applied_lessons=sorted(applied,key=lambda r:r['id']))
    task=latest(vault,'task').get(data['task_id'])
    if not task or task['status']!='done':raise ValueError('completed_task_required')
    source=h.source_file(vault,task['source_path']); text=source.read_text(encoding='utf-8')
    if h.statement_hash(text)!=task.get('source_content_hash') or task['evidence'] not in text:raise ValueError('task_source_changed')
    verification=b._safe(vault,data['verification_path']); content=verification.read_text(encoding='utf-8')
    if b.digest(verification)!=data['verification_hash'] or len(data['verification_evidence'])<20 or data['verification_evidence'] not in content:raise ValueError('verification_source_changed')
    if data['verification_kind'] not in ('test_result','user_acceptance') or data['observed_result'] not in ('passed','accepted','failed','rejected'):raise ValueError('observed_external_result_required')
    if data['verification_kind']=='test_result':
        # A structured runner receipt, not the agent's self-rating or a log file name.
        receipt=json.loads(content)
        if data['observed_result'] not in ('passed','failed'):raise ValueError('test_result_polarity_required')
        success=data['observed_result']=='passed'
        if receipt.get('task_id')!=data['task_id'] or not isinstance(receipt.get('exit_code'),int) or isinstance(receipt.get('exit_code'),bool) or (receipt['exit_code']==0)!=success or receipt.get('passed') is not success or not receipt.get('command') or not receipt.get('finished_at'):raise ValueError('runner_receipt_result_mismatch')
    elif data['observed_result'] not in ('accepted','rejected'):raise ValueError('user_acceptance_required')
    method=b._safe(vault,data['method_path'])
    if h.contains_secret(content) or h.contains_secret(method.read_text()):raise ValueError('restricted_source')
    row=dict(data,task_version=task['version'],scope=task.get('scope','project:'+task['project_id'] if task.get('project_id') else 'user'),project_id=task.get('project_id'),method_hash=h.statement_hash(method.read_text()),source_path=task['source_path'],source_content_hash=task['source_content_hash'],evidence=task['evidence'],status='proposed')
    row['receipt_id']=fingerprint(row)
    return append_once(vault,OUTCOMES,row) if apply else dict(row=row,changed=False)


def review_lesson(vault,data,apply=False):
    """Compare declared reviewer names/sessions; this is not identity authentication."""
    from is_ve_ders import put, is_instruction_target, has_user_acceptance
    row=next((r for r in h.load_jsonl(vault/OUTCOMES) if r['receipt_id']==data.get('receipt_id')),None)
    if not row:raise ValueError('outcome_missing')
    def identity(value):
        return ''.join(c for c in unicodedata.normalize('NFKC',value).casefold() if c.isalnum()) if isinstance(value,str) else ''
    reviewer=identity(data.get('reviewed_by'));actor=identity(row['actor'])
    if not reviewer or not actor or reviewer==actor or len(data.get('reason',''))<20 or data.get('evidence_checked') is not True or data.get('conditions_checked') is not True:raise ValueError('independent_review_required')
    if 'actor_session_id' in row and 'reviewer_session_id' not in data:raise ValueError('independent_review_required')
    if 'reviewer_session_id' in data and (not isinstance(data['reviewer_session_id'],str) or not data['reviewer_session_id'].strip() or len(data['reviewer_session_id'])>200 or data['reviewer_session_id']==row.get('actor_session_id')):raise ValueError('independent_review_required')
    if is_instruction_target(vault,row['method_path']) and not has_user_acceptance(row):raise ValueError('instruction_target_requires_user_acceptance')
    fresh=outcome(vault,{k:v for k,v in row.items() if k not in ('receipt_id','status','task_version','scope','project_id','method_hash','source_path','source_content_hash','evidence')})['row']
    if fresh['receipt_id']!=row['receipt_id']:raise ValueError('outcome_changed')
    lesson=dict(id='lesson-'+row['receipt_id'][:24],title=row['title'],status='verified',source_path=row['source_path'],evidence=row['evidence'],actor=data['reviewed_by'],reviewed_by=data['reviewed_by'],review_reason=data['reason'],scope=row['scope'],project_id=row.get('project_id'),proposal=row['lesson'],observed_result=row['observed_result'],conditions=row['conditions'],method_path=row['method_path'],target_path=row['method_path'],target_hash=row['method_hash'],verification_path=row['verification_path'],verification_evidence=row['verification_evidence'],verification_hash=row['verification_hash'],triggers=row.get('triggers',[row['title']]),outcome_id=row['receipt_id'])
    lesson['verification_kind']=row['verification_kind']
    if 'acceptance_source' in row:lesson['acceptance_source']=row['acceptance_source']
    if 'reviewer_session_id' in data:lesson['reviewer_session_id']=data['reviewer_session_id']
    from is_ve_ders import latest
    previous=latest(vault,'lesson').get(lesson['id'])
    if previous and previous.get('outcome_id')==row['receipt_id']:return dict(changed=False,lesson=previous)
    return dict(changed=apply,lesson=put(vault,'lesson',lesson) if apply else lesson)


def lesson_utility(vault, apply=False, min_harm=2):
    """Request review, never delete: one failure may be attribution noise.

    Count each task/verification once, after the last review-required version;
    harmless version updates do not reset accumulated observations.
    """
    from is_ve_ders import latest, put, LESSONS, is_instruction_target
    from codex_hafiza import atomic
    if type(min_harm) is not int or min_harm<1:raise ValueError('min_harm_invalid')
    vault=Path(vault);current=latest(vault,'lesson');cutoffs={}
    for row in h.load_jsonl(vault/LESSONS):
        if 'review_required' in row:cutoffs[row['id']]=max(cutoffs.get(row['id'],0),row['version'])
    lessons={ident:dict(help=0,harm=0,outcome_ids=[],action='none') for ident in sorted(current)}
    seen=set();review_required=[];failures=[]
    for row in h.load_jsonl(vault/OUTCOMES):
        result=row.get('observed_result')
        if result not in ('passed','accepted','failed','rejected'):continue
        for item in row.get('applied_lessons',[]):
            ident=item['id']
            if ident not in current or item['version']<=cutoffs.get(ident,0):continue
            if row['receipt_id']==current[ident].get('outcome_id'):continue
            key=(ident,row['task_id'],row['verification_hash'])
            if key in seen:continue
            seen.add(key);entry=lessons[ident]
            entry['help' if result in ('passed','accepted') else 'harm']+=1
            entry['outcome_ids'].append(row['receipt_id'])
    for ident,entry in lessons.items():
        entry['outcome_ids']=sorted(set(entry['outcome_ids']));row=current[ident]
        if any(is_instruction_target(vault,row.get(k)) for k in ('target_path','method_path')):entry['instruction_target']=True
        if ('review_required' in row or row['status'] not in ('verified','proposed')
            or entry['harm']<=entry['help'] or entry['harm']<min_harm):continue
        entry['action']='review_required'
        if apply:
            data={k:v for k,v in row.items() if k not in ('version','updated_at','evidence_hash','source_content_hash')}
            data.update(status='proposed',actor='lesson-utility',expected_version=row['version'],
                        review_required=dict(reason='harm_exceeds_help',help=entry['help'],harm=entry['harm'],outcome_ids=entry['outcome_ids']))
            try:
                source=h.source_file(vault,row['source_path'])
                if h.statement_hash(source.read_text())!=row.get('source_content_hash'):raise ValueError('lesson_source_changed')
                put(vault,'lesson',data)
            except ValueError as exc:
                entry['action']='demotion_failed:'+str(exc)
                failures.append(dict(id=ident,reason=entry['action']));continue
        review_required.append(ident)
    if apply:
        atomic(vault/'zihin/ders-faydasi.json',json.dumps(dict(generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),min_harm=min_harm,lessons=lessons),ensure_ascii=False,indent=2)+'\n')
    return dict(lessons=lessons,review_required=review_required,failures=failures,applied=apply,canonical_deletes=0)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vault',type=Path,required=True)
    sub=p.add_subparsers(dest='cmd',required=True)
    r=sub.add_parser('review-pending');r.add_argument('--project-id');r.add_argument('--limit',type=int,default=5);r.add_argument('--apply',action='store_true');r.add_argument('--conflict-pairs',type=int,default=3)
    for name in ('outcome','review-lesson','verify-answer'):
        r=sub.add_parser(name);r.add_argument('--input-json',type=Path,required=True)
        if name!='verify-answer':r.add_argument('--apply',action='store_true')
        else:r.add_argument('--project-id')
    r=sub.add_parser('context');r.add_argument('query');r.add_argument('--cwd');r.add_argument('--budget',type=int,default=5000)
    r=sub.add_parser('lesson-utility');r.add_argument('--apply',action='store_true');r.add_argument('--min-harm',type=int,default=2)
    a=p.parse_args(argv);v=a.vault.resolve()
    if a.cmd=='review-pending':result=review_pending(v,a.project_id,a.limit,a.apply,conflict_pairs=a.conflict_pairs)
    elif a.cmd=='lesson-utility':result=lesson_utility(v,a.apply,a.min_harm)
    elif a.cmd=='context':
        from gorev_baglam import build_task_package
        result=build_task_package(v,a.query,a.cwd,a.budget)
    else:
        if a.input_json.stat().st_size>64000:raise ValueError('input_budget_exceeded')
        data=json.loads(a.input_json.read_text(encoding='utf-8'))
        if a.cmd=='verify-answer':
            from jev_answer import verify
            result=verify(v,data,a.project_id)
        else:result=(outcome if a.cmd=='outcome' else review_lesson)(v,data,a.apply)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
