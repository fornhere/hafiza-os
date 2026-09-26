#!/usr/bin/env python3
"""Deterministic reflection skeletons for a reviewer; no distillation or promotion."""
import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import bilgi_agi as b
import hafiza as h
import hafiza_dongusu as d
from is_ve_ders import latest, is_instruction_target
from platform_lock import exclusive_lock

REFLECTIONS = Path('gelen-kutusu/lesson-reflections.jsonl')


def _pattern(vault, row, tasks):
    fields=('receipt_id','task_id','scope','method_path','verification_kind','verification_path','verification_hash')
    if any(not isinstance(row.get(k),str) or not row[k].strip() for k in fields):raise ValueError('invalid_outcome')
    session=row.get('actor_session_id')
    if 'actor_session_id' in row:
        if not isinstance(session,str) or not session.strip() or len(session)>200:raise ValueError('invalid_session_key')
    else:
        task=tasks.get(row['task_id'])
        if not task or not isinstance(task.get('source_path'),str) or not task['source_path'].strip():raise ValueError('missing_task_source')
        session='source:'+task['source_path']
    kind=row['verification_kind']
    if (kind,row['observed_result']) not in (('test_result','failed'),('user_acceptance','rejected')):raise ValueError('invalid_result_kind')
    try:raw=b._safe(vault,row['verification_path']).read_bytes()
    except (OSError,ValueError):raise ValueError('verification_unreadable') from None
    if hashlib.sha256(raw).hexdigest()!=row['verification_hash']:raise ValueError('verification_hash_mismatch')
    signature='user_rejected'
    if kind=='test_result':
        try:receipt=json.loads(raw)
        except (ValueError,UnicodeError):raise ValueError('verification_unreadable') from None
        command=receipt.get('command') if isinstance(receipt,dict) else None
        if not isinstance(command,list) or not command or any(not isinstance(s,str) for s in command) or not command[0].strip():raise ValueError('verification_command_invalid')
        signature=' '.join(command)
    occurrence={k:row[k] for k in ('receipt_id','task_id','observed_result','verification_path','verification_hash')}
    occurrence['session_key']=session
    return (row['scope'],row['method_path'],kind,signature),occurrence


def _reflect(vault, apply, limit, min_sessions):
    tasks=latest(vault,'task');lessons=latest(vault,'lesson');counts=Counter();groups={}
    path=b._safe(vault,d.OUTCOMES.as_posix());lines=[]
    if path.exists():
        with path.open(encoding='utf-8') as stream:lines=deque(stream,maxlen=limit)
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith('#'):continue
        try:row=json.loads(raw)
        except ValueError:counts['invalid_outcome']+=1;continue
        if not isinstance(row,dict):counts['invalid_outcome']+=1;continue
        if row.get('observed_result') not in ('failed','rejected'):continue
        try:key,occurrence=_pattern(vault,row,tasks)
        except ValueError as exc:counts[str(exc)]+=1;continue
        groups.setdefault(key,{})[occurrence['receipt_id']]=occurrence
    previous=h.load_jsonl(b._safe(vault,REFLECTIONS.as_posix()));proposals=[]
    for key,entries in sorted(groups.items()):
        sessions={r['session_key'] for r in entries.values()}
        if len(sessions)<min_sessions or len({r['task_id'] for r in entries.values()})<2:continue
        pattern=list(key);history=[r for r in previous if r.get('pattern_key')==pattern]
        seen={o['receipt_id'] for r in history for o in r.get('occurrences',[])}
        occurrences=[entries[ident] for ident in sorted(entries) if ident not in seen]
        if not occurrences:continue
        scope,method,kind,signature=key
        condition=f'Kapsam {scope}, yöntem {method}: `{signature}` {len(sessions)} bağımsız oturumda olumsuz sonuçlandı.'
        proposal=dict(receipt_id=d.fingerprint(dict(pattern_key=pattern,occurrence_ids=[r['receipt_id'] for r in occurrences])),
                      pattern_key=pattern,status='proposed',canonical_writes=False,format='condition→action→rationale',
                      condition=condition,action=None,rationale=None,needs_distillation=True,occurrences=occurrences,
                      instruction_target=is_instruction_target(vault,method),kind='delta' if history else 'new')
        if history:proposal['base_receipt_id']=history[-1]['receipt_id']
        # When several lessons match, choose the most recently updated one, then ID.
        matches=[r for r in lessons.values() if r.get('scope')==scope and r.get('method_path')==method]
        if matches:
            base=max(matches,key=lambda r:(r.get('updated_at',''),r['id']))
            proposal.update(kind='delta',base_lesson_id=base['id'],base_lesson_version=base['version'])
        if proposal['kind']=='delta':proposal['append']=dict(occurrences=occurrences,condition=condition)
        if proposal['instruction_target']:proposal['application']='gap_noted_not_applied'
        if h.contains_secret(json.dumps(proposal,ensure_ascii=False)):
            counts['restricted_pattern']+=1;continue
        if apply and not d.append_once(vault,REFLECTIONS,proposal)['changed']:continue
        proposals.append(proposal)
    return dict(proposals=proposals,diagnostics=[dict(reason=k,count=v) for k,v in sorted(counts.items())],
                applied=apply,canonical_writes=False,distillation='reviewer')


def reflect(vault, apply=False, limit=200, min_sessions=2):
    if type(min_sessions) is not int or min_sessions<2:raise ValueError('min_sessions_invalid')
    if type(limit) is not int or limit<1:raise ValueError('limit_invalid')
    vault=Path(vault)
    if not apply:return _reflect(vault,False,limit,min_sessions)
    # Serialize history selection as well as append, without nesting writer locks.
    path=b._safe(vault,'gelen-kutusu/.lesson-reflections.lock');path.parent.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(path):return _reflect(vault,True,limit,min_sessions)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--vault',type=Path,required=True)
    sub=p.add_subparsers(dest='cmd',required=True);r=sub.add_parser('reflect')
    r.add_argument('--apply',action='store_true');r.add_argument('--limit',type=int,default=200);r.add_argument('--min-sessions',type=int,default=2)
    a=p.parse_args(argv)
    print(json.dumps(reflect(a.vault.resolve(),a.apply,a.limit,a.min_sessions),ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
