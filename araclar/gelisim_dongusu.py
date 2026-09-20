"""Bounded retrieval calibration experiments; immutable shadow reports, no promotion."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import jev_client
from platform_lock import exclusive_lock

VERSION = 1
THRESHOLDS = (1.3, 1.7, 1.9)
BASELINE = 1.5
MAX_CALLS = 60
MAX_SECONDS = 240
MAX_TOKENS = 200000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.experiment-')
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def snapshot_valid(vault, versions):
    base=Path(vault).resolve()
    for name,sha in versions.items():
        p=(base/name).resolve()
        if not p.is_relative_to(base) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            return False
    return True


def freeze(vault, labels):
    """Only source-eligible current knowledge cards; labels stay explicitly agent/human."""
    import bilgi_agi as b
    import jev_retrieval as r
    rows,_=b._rows(Path(vault))
    # This experiment only exports vault-contained evidence; external assets stay out.
    rows=[x for x in rows if snapshot_valid(vault,r.versions(Path(vault),[x]))]
    versions=r.versions(Path(vault),rows)
    candidates=[{**{k:x[k] for k in ('id','title','statement','scope','domains')},
                 'families':sorted({s['path'] for s in x['sources']})} for x in rows]
    by_id={x['id']:x for x in candidates}
    cases=[]
    for c in labels['cases']:
        if not set(c['expected_ids']+c['relevant_ids']) <= set(by_id):
            raise ValueError('label_source_missing')
        cases.append(dict(id=c['id'],query=c['query'],scope='project:'+c['project_id'] if c.get('project_id') else 'user',
                          expected=c['expected_ids'],allowed=c['relevant_ids'],
                          origin=c.get('origin','unspecified'),
                          families=sorted({f for i in c['relevant_ids'] for f in by_id[i]['families']}) or ['negative:'+c['id']]))
    corpus=dict(schema=VERSION,candidates=candidates,cases=cases,source_versions=versions,
                label_status=labels.get('label_status','unreviewed'))
    validate(corpus)
    if not snapshot_valid(vault,versions): raise ValueError('snapshot_changed')
    return corpus


def validate(corpus):
    if corpus.get('schema')!=VERSION: raise ValueError('schema_invalid')
    candidates=corpus.get('candidates',[]); cases=corpus.get('cases',[])
    if not 1<=len(candidates)<=32 or not 4<=len(cases)<=40: raise ValueError('corpus_budget')
    if not corpus.get('source_versions'): raise ValueError('sources_required')
    ids=[r['id'] for r in candidates]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate_candidate')
    by_id={r['id']:r for r in candidates}
    seen=set()
    for c in cases:
        if c['id'] in seen: raise ValueError('duplicate_case')
        seen.add(c['id'])
        if not isinstance(c['query'],str) or not c['query'].strip() or len(c['query'])>1500: raise ValueError('query_invalid')
        if not c.get('families') or any(not isinstance(f,str) or not f for f in c['families']): raise ValueError('families_required')
        if not set(c['expected'])<=set(c['allowed'])<=set(ids): raise ValueError('labels_invalid')
        if any(by_id[i]['scope'] not in ('user',c['scope']) for i in c['allowed']): raise ValueError('label_scope_violation')
        actual={f for i in c['allowed'] for f in by_id[i]['families']}
        if not actual<=set(c['families']): raise ValueError('family_provenance_missing')


def split(cases):
    # Transitive source-family components stay together, including all later mutations.
    groups=[]
    for c in cases:
        group=[c]; families=set(c['families']); rest=[]
        for old in groups:
            if families & {f for x in old for f in x['families']}:
                group+=old; families.update(f for x in old for f in x['families'])
            else: rest.append(old)
        # Revisit after union; a bridge can connect earlier retained components.
        changed=True
        while changed:
            changed=False
            for old in rest[:]:
                if families & {f for x in old for f in x['families']}:
                    group+=old; families.update(f for x in old for f in x['families']); rest.remove(old); changed=True
        groups=rest+[group]
    if len(groups)<4: raise ValueError('insufficient_independent_families')
    groups.sort(key=lambda g:digest(sorted(f for c in g for f in c['families'])))
    count=max(2,len(groups)//3)
    positive=[g for g in groups if any(c['expected'] for c in g)]
    negative=[g for g in groups if all(not c['expected'] for c in g)]
    if len(positive)<2 or len(negative)<2: raise ValueError('positive_negative_coverage_required')
    held=[positive[0],negative[0]]
    held += [g for g in groups if g not in held][:count-2]
    holdout=[c for g in held for c in g]
    dev=[c for g in groups if g not in held for c in g]
    return dev,holdout


def synthesize(cases):
    # Conservative surface mutations. No invented facts, free paraphrases or new labels.
    variants=[]
    for c in cases:
        for name,q in [('original',c['query']),('spacing','  '+c['query'].replace(' ','  ')+'  '),
                       ('request','Şu soruyu mevcut kaynaklardan yanıtla: '+c['query'])]:
            variants.append(dict(c,id=c['id']+':'+name,query=q,parent_id=c['id'],synthetic=name!='original'))
    return variants


def metrics(rows, threshold):
    missing=extra=exact=0
    for row in rows:
        chosen={i for i,s in row['scores'].items() if s>=threshold}
        expected=set(row['expected']); allowed=set(row['allowed'])
        missing+=len(expected-chosen); extra+=len(chosen-allowed)
        exact+=int(expected<=chosen<=allowed)
    return dict(cases=len(rows),missing=missing,extra=extra,acceptable=exact)


def improves(a,b):
    return a['missing']<=b['missing'] and a['extra']<=b['extra'] and (a['missing']<b['missing'] or a['extra']<b['extra'])


def run(vault, corpus, output, evaluate=None, resume=False):
    validate(corpus); output=Path(output); output.mkdir(parents=True,exist_ok=True)
    evaluate=evaluate or jev_client.evaluate
    identity=digest(corpus); target=output/(identity+'.json')
    with exclusive_lock(output/'.lock',timeout=0):
        previous=None
        if target.exists():
            previous=json.loads(target.read_text())
            if not resume:
                return dict(status='unchanged',report=str(target),previous_status=previous['status'])
            if previous['status']!='failed' or previous.get('attempts',1)>=2 or 'selected_before_holdout' in previous or previous.get('last_inference',{}).get('diagnostics')!=['deadline_exceeded']:
                raise ValueError('resume_not_eligible')
        elif resume: raise ValueError('resume_missing')
        if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_stale')
        dev,holdout=split(corpus['cases']); dev=synthesize(dev)
        families={f for c in holdout for f in c['families']}
        # Holdout is single-use even after code/config changes or dataset repackaging.
        for old in output.glob('*.json'):
            if old==target: continue
            prior=json.loads(old.read_text())
            if families & set(prior.get('holdout_families',[])):
                raise ValueError('holdout_already_consumed')
        if len(dev)+len(holdout)+(previous or {}).get('calls',0)>MAX_CALLS: raise ValueError('call_budget_preflight')
        report=dict(schema=VERSION,status='started',corpus_digest=identity,label_status=corpus['label_status'],
                    holdout_families=sorted(families),baseline=BASELINE,candidates=list(THRESHOLDS),
                    calls=(previous or {}).get('calls',0),usage_tokens=(previous or {}).get('usage_tokens',0),
                    attempts=(previous or {}).get('attempts',0)+1,previous_attempt=previous,production_changed=False,shadow_candidate=None,
                    limits=dict(calls=MAX_CALLS,seconds=MAX_SECONDS,tokens=MAX_TOKENS),results={})
        write(target,report) # A crash consumes the campaign; no invisible paid replay.
        started=time.monotonic()
        config_hash=digest(jev_client.load_config(vault))
        report['config_digest']=config_hash
        report['runner_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        def score(cases):
            rows=[]
            for c in cases:
                if report['calls']>=MAX_CALLS or time.monotonic()-started>=MAX_SECONDS or report['usage_tokens']>=MAX_TOKENS:
                    raise ValueError('budget_exhausted')
                if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_changed')
                if digest(jev_client.load_config(vault))!=config_hash: raise ValueError('config_changed')
                eligible=[r for r in corpus['candidates'] if r['scope'] in ('user',c['scope'])]
                report['calls']+=1; write(target,report)
                result=evaluate(vault,c['query'],eligible,scope=c['scope'],source_versions=corpus['source_versions'])
                report['last_inference']={k:result.get(k) for k in ('mode','degraded','diagnostics','latency_ms','request_hash','reported_model')}
                report['usage_tokens']+=sum(result.get('usage',{}).get(k,0) for k in ('input_tokens','output_tokens'))
                write(target,report)
                if result.get('mode')=='off' or result.get('degraded') or set(result.get('scores',{}))!={r['id'] for r in eligible}:
                    raise ValueError('inference_unavailable')
                if any(type(s) not in (int,float) or not math.isfinite(s) or not 0<=s<=2 for s in result['scores'].values()):
                    raise ValueError('scores_invalid')
                if time.monotonic()-started>=MAX_SECONDS or report['usage_tokens']>MAX_TOKENS: raise ValueError('budget_exhausted')
                if digest(jev_client.load_config(vault))!=config_hash: raise ValueError('config_changed')
                rows.append(dict(c,scores=result['scores'],latency_ms=result.get('latency_ms'),cache_hit=result.get('cache_hit',False)))
                if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_changed')
                report['results']['partial']=rows; write(target,report)
            report['results'].pop('partial',None)
            return rows
        try:
            dev_rows=score(dev); report['results']['development']=dev_rows
            base=metrics(dev_rows,BASELINE)
            trials={str(t):metrics(dev_rows,t) for t in THRESHOLDS}
            winners=[t for t in THRESHOLDS if improves(trials[str(t)],base)]
            report['development']=dict(baseline=base,candidates=trials)
            if not winners:
                report['status']='no_improvement'
            else:
                winner=min(winners,key=lambda t:(trials[str(t)]['missing'],trials[str(t)]['extra'],abs(t-BASELINE)))
                report['selected_before_holdout']=winner; write(target,report)
                test_rows=score(holdout); report['results']['holdout']=test_rows
                b=metrics(test_rows,BASELINE); a=metrics(test_rows,winner)
                report['holdout']=dict(baseline=b,candidate=a)
                # Candidate must be non-regressive on unseen source families.
                passes=a['missing']<=b['missing'] and a['extra']<=b['extra']
                report['status']='shadow_candidate' if passes else 'holdout_rejected'
                if passes: report['shadow_candidate']=dict(threshold=winner,automatic_promotion=False,
                    scope='isolated_score_selector_only',requires='fresh real-task evaluation of full delivered context')
        except (ValueError,OSError,TimeoutError) as error:
            report['status']='failed'; report['error']=str(error) if isinstance(error,ValueError) else type(error).__name__
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        write(target,report)
        return dict(status=report['status'],report=str(target),calls=report['calls'],shadow_candidate=report['shadow_candidate'])


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--vault',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze'); f.add_argument('--labels',type=Path,required=True); f.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('run'); r.add_argument('--corpus',type=Path,required=True); r.add_argument('--output-dir',type=Path,required=True); r.add_argument('--resume-timeout',action='store_true')
    a=p.parse_args()
    if a.command=='freeze':
        if a.output.exists(): p.error('refuse_overwrite')
        write(a.output,freeze(a.vault,json.loads(a.labels.read_text()))); print(json.dumps({'status':'frozen','path':str(a.output)}))
    else:
        print(json.dumps(run(a.vault,json.loads(a.corpus.read_text()),a.output_dir,resume=a.resume_timeout),ensure_ascii=False))

if __name__=='__main__': main()
