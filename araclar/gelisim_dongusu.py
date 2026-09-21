"""Bounded retrieval calibration experiments; immutable shadow reports, no promotion."""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import unicodedata
from pathlib import Path, PurePosixPath
import tempfile
import time
import jev_client
from platform_lock import exclusive_lock

VERSION = 2
THRESHOLDS = (1.3, 1.7, 1.9)
BASELINE = 1.5
MAX_CALLS = 60
MAX_SECONDS = 240
MAX_TOKENS = 200000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def write(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix='.experiment-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
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
    validate_review(labels)
    import bilgi_agi as b
    import jev_retrieval as r
    rows,_=b._rows(Path(vault))
    # This experiment only exports vault-contained evidence; external assets stay out.
    rows=[x for x in rows if snapshot_valid(vault,r.versions(Path(vault),[x]))]
    relative=lambda name: (Path(vault)/name).resolve().relative_to(Path(vault).resolve()).as_posix()
    versions={relative(k):v for k,v in r.versions(Path(vault),rows).items()}
    candidates=[{**{k:x[k] for k in ('id','title','statement','scope','domains')},
                 'families':sorted({relative(s['path']) for s in x['sources']})} for x in rows]
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
                label_status=labels.get('label_status','reviewed'),label_review=copy.deepcopy(labels['label_review']))
    validate(corpus)
    if not snapshot_valid(vault,versions): raise ValueError('snapshot_changed')
    return corpus


def validate_review(value):
    review=value.get('label_review') if isinstance(value,dict) else None
    if (not isinstance(review,dict) or review.get('status')!='reviewed'
            or review.get('kind') not in ('human','agent','fixture')
            or not isinstance(review.get('reviewed_by'),str)
            or not 1<=len(review['reviewed_by'].strip())<=200):
        raise ValueError('label_review_required')


def strings(value, *, nonempty=False, max_items=1024, max_length=1500):
    return (isinstance(value,list) and (bool(value) or not nonempty)
            and len(value)<=max_items and all(isinstance(x,str) and 0<len(x)<=max_length for x in value)
            and len(value)==len(set(value)))


def valid_scope(value):
    return isinstance(value,str) and (value=='user' or value.startswith('project:') and 8<len(value)<=208)


def validate(corpus):
    if not isinstance(corpus,dict) or type(corpus.get('schema')) is not int or corpus['schema']!=VERSION:
        raise ValueError('schema_invalid')
    validate_review(corpus)
    if not isinstance(corpus.get('label_status'),str) or not 1<=len(corpus['label_status'])<=500:
        raise ValueError('label_status_invalid')
    candidates=corpus.get('candidates'); cases=corpus.get('cases')
    if not isinstance(candidates,list) or not isinstance(cases,list) or not 1<=len(candidates)<=32 or not 4<=len(cases)<=40:
        raise ValueError('corpus_budget')
    versions=corpus.get('source_versions')
    if not isinstance(versions,dict) or not 1<=len(versions)<=1024: raise ValueError('sources_required')
    for name,sha in versions.items():
        if (not isinstance(name,str) or not name or len(name)>1500 or '\\' in name or '\0' in name
                or re.match(r'^[A-Za-z]:',name) or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                or str(PurePosixPath(name))!=name or name=='.'
                or not isinstance(sha,str) or not re.fullmatch('[a-f0-9]{64}',sha)):
            raise ValueError('source_version_invalid')
    ids=[]
    for row in candidates:
        if (not isinstance(row,dict) or any(not isinstance(row.get(k),str) or not row[k].strip()
                for k in ('id','title','statement')) or len(row['id'])>200
                or len(row['title'])>1500 or len(row['statement'])>12000
                or not valid_scope(row.get('scope')) or not strings(row.get('domains'))):
            raise ValueError('candidate_invalid')
        if not strings(row.get('families'),nonempty=True) or not set(row['families'])<=set(versions):
            raise ValueError('family_provenance_missing')
        ids.append(row['id'])
    if len(ids)!=len(set(ids)): raise ValueError('duplicate_candidate')
    by_id={r['id']:r for r in candidates}; seen=set()
    for c in cases:
        if not isinstance(c,dict) or not isinstance(c.get('id'),str) or not 1<=len(c['id'])<=200:
            raise ValueError('case_invalid')
        if c['id'] in seen: raise ValueError('duplicate_case')
        seen.add(c['id'])
        if not isinstance(c.get('query'),str) or not c['query'].strip() or len(c['query'])>1500: raise ValueError('query_invalid')
        if not valid_scope(c.get('scope')): raise ValueError('scope_invalid')
        if not isinstance(c.get('origin'),str) or not 1<=len(c['origin'].strip())<=200: raise ValueError('origin_required')
        if not strings(c.get('families'),nonempty=True): raise ValueError('families_required')
        if not strings(c.get('expected')) or not strings(c.get('allowed')) or not set(c['expected'])<=set(c['allowed'])<=set(ids):
            raise ValueError('labels_invalid')
        if any(by_id[i]['scope'] not in ('user',c['scope']) for i in c['allowed']): raise ValueError('label_scope_violation')
        actual={f for i in c['allowed'] for f in by_id[i]['families']}
        if not actual<=set(c['families']): raise ValueError('family_provenance_missing')


def case_keys(case, versions=None):
    # IDs and cosmetic query edits cannot manufacture independent evidence.
    query=' '.join(unicodedata.normalize('NFKC',case['query']).casefold().split())
    keys={'query:'+digest([case['scope'],query])}
    keys.update('family:'+f for f in case['families'])
    keys.update('source:'+versions[f] for f in case['families'] if versions and f in versions)
    return keys


def partition_keys(cases, versions=None):
    return set().union(*(case_keys(c,versions) for c in cases))


def split(cases, versions=None):
    # Transitive source-family components stay together, including all later mutations.
    groups=[]
    for c in cases:
        group=[c]; families=case_keys(c,versions); rest=[]
        for old in groups:
            if families & partition_keys(old,versions):
                group+=old; families.update(partition_keys(old,versions))
            else: rest.append(old)
        # Revisit after union; a bridge can connect earlier retained components.
        changed=True
        while changed:
            changed=False
            for old in rest[:]:
                if families & partition_keys(old,versions):
                    group+=old; families.update(partition_keys(old,versions)); rest.remove(old); changed=True
        groups=rest+[group]
    if len(groups)<4: raise ValueError('insufficient_independent_families')
    groups.sort(key=lambda g:digest(sorted(f for c in g for f in c['families'])))
    count=max(2,len(groups)//3)
    positive=[g for g in groups if any(c['expected'] for c in g)]
    negative=[g for g in groups if all(not c['expected'] for c in g)]
    if len(positive)<2 or len(negative)<2: raise ValueError('positive_negative_coverage_required')
    held=[positive[0],negative[0]]
    # Keep one positive and one negative component in development as well.
    reserve=[positive[-1],negative[-1]]
    held += [g for g in groups if g not in held and g not in reserve][:count-2]
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


def read_report(path):
    try:
        report=json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(report,dict) or report.get('corpus_digest')!=path.stem
                or type(report.get('schema')) is not int or report['schema'] not in (1,VERSION)
                or report.get('status') not in ('started','failed','no_improvement','shadow_candidate','holdout_rejected')
                or not isinstance(report.get('results'),dict)):
            raise ValueError('ledger_invalid')
        for field in ('calls','usage_tokens'):
            if type(report.get(field)) is not int or report[field]<0: raise ValueError('ledger_invalid')
        for field in ('holdout_families','development_keys','holdout_keys'):
            if field in report and not strings(report[field],max_items=4096,max_length=1600): raise ValueError('ledger_invalid')
        if 'holdout_families' not in report: raise ValueError('ledger_invalid')
        if report['schema']==VERSION:
            if any(field not in report for field in ('development_keys','holdout_keys')): raise ValueError('ledger_invalid')
            if type(report.get('attempts')) is not int or not 1<=report['attempts']<=2: raise ValueError('ledger_invalid')
            if type(report.get('usage_unreported_calls')) is not int or not 0<=report['usage_unreported_calls']<=report['calls']:
                raise ValueError('ledger_invalid')
        return report
    except (ValueError,TypeError,KeyError):
        raise ValueError('ledger_invalid') from None


def history_keys(report, partition):
    keys=set(report.get(partition+'_keys',[]))
    keys.update('family:'+f for f in report.get(partition+'_families',[]))
    try:
        rows=report['results'].get(partition,[])
        if not isinstance(rows,list): raise ValueError('ledger_invalid')
        for case in rows: keys.update(case_keys(case))
    except (ValueError,TypeError,KeyError,AttributeError):
        raise ValueError('ledger_invalid') from None
    # An interrupted v1 report did not reserve all development identities.
    if (partition=='development' and report['schema']==1 and report['calls']
            and not report['results'].get('development')):
        raise ValueError('legacy_ledger_incomplete')
    return keys


def code_revision():
    folder=Path(__file__).resolve().parent
    return {name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in
            (Path(__file__).name,'jev_client.py','jev_runtime.py','platform_lock.py')}


def config_revision(vault):
    path=Path(vault)/'komuta/jev.json'
    return digest(dict(effective=jev_client.load_config(vault),
                       file_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None))


def inference_metadata(result):
    if (result.get('mode') not in ('off','shadow','on','assist')
            or type(result.get('degraded',False)) is not bool
            or type(result.get('cache_hit',False)) is not bool): raise ValueError('response_invalid')
    diagnostics=result.get('diagnostics',[])
    if not isinstance(diagnostics,list) or len(diagnostics)>32 or any(not isinstance(d,str) for d in diagnostics):
        raise ValueError('response_invalid')
    latency=result.get('latency_ms')
    if latency is not None and (type(latency) not in (int,float) or not math.isfinite(latency) or latency<0):
        raise ValueError('response_invalid')
    # Metadata is not permission to persist arbitrary provider/error text.
    known={'deadline_exceeded','credentials_missing','cache_unavailable','cache_write_failed',
           'capacity_exceeded','answers_invalid','request_failed','quantized_probability'}
    safe=dict(mode=result['mode'],degraded=result.get('degraded',False),latency_ms=latency,
              diagnostics=[d if d in known else 'provider_diagnostic' for d in diagnostics])
    for name,pattern in [('request_hash',r'[a-f0-9]{64}'),('reported_model',r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}')]:
        value=result.get(name)
        if isinstance(value,str) and re.fullmatch(pattern,value): safe[name]=value
    return safe


def run(vault, corpus, output, evaluate=None, resume=False):
    validate(corpus); corpus=copy.deepcopy(corpus)
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    evaluate=evaluate or jev_client.evaluate
    identity=digest(corpus); target=output/(identity+'.json')
    with exclusive_lock(output/'.lock',timeout=0):
        previous=read_report(target) if target.exists() else None
        if previous and not resume:
            return dict(status='unchanged',report=str(target),previous_status=previous['status'])
        if resume and not previous: raise ValueError('resume_missing')
        if previous and (previous['status']!='failed' or previous.get('attempts')!=1
                or 'selected_before_holdout' in previous
                or previous.get('error')!='inference_unavailable'
                or previous.get('last_inference',{}).get('diagnostics')!=['deadline_exceeded']):
            raise ValueError('resume_not_eligible')
        if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_stale')
        dev,holdout=split(corpus['cases'],corpus['source_versions'])
        dev_keys=partition_keys(dev,corpus['source_versions']); held_keys=partition_keys(holdout,corpus['source_versions'])
        for old in output.glob('*.json'):
            if old==target: continue
            prior=read_report(old)
            if ((dev_keys|held_keys) & history_keys(prior,'holdout')
                    or held_keys & history_keys(prior,'development')):
                raise ValueError('holdout_already_consumed')
        dev=synthesize(dev)
        limits=dict(calls=MAX_CALLS,seconds=MAX_SECONDS,tokens=MAX_TOKENS)
        baseline=BASELINE; thresholds=tuple(THRESHOLDS); revision=code_revision()
        if len(dev)+len(holdout)+(previous or {}).get('calls',0)>limits['calls']: raise ValueError('call_budget_preflight')
        elapsed=(previous or {}).get('elapsed_seconds',0)
        if type(elapsed) not in (int,float) or not math.isfinite(elapsed) or elapsed<0: raise ValueError('ledger_invalid')
        if previous:
            if (previous.get('schema')!=VERSION or previous.get('config_digest')!=config_revision(vault)
                    or previous.get('code_revision')!=revision or previous.get('runner_sha256')!=revision[Path(__file__).name]
                    or previous.get('limits')!=limits or previous.get('baseline')!=baseline
                    or previous.get('candidates')!=list(thresholds)):
                raise ValueError('resume_revision_changed')
            if elapsed>=limits['seconds'] or previous['usage_tokens']>=limits['tokens']: raise ValueError('budget_exhausted')
        report=dict(schema=VERSION,status='started',corpus_digest=identity,label_status=corpus['label_status'],
                    label_review=corpus['label_review'],development_keys=sorted(dev_keys),holdout_keys=sorted(held_keys),
                    holdout_families=sorted({f for c in holdout for f in c['families']}),baseline=baseline,candidates=list(thresholds),
                    calls=(previous or {}).get('calls',0),usage_tokens=(previous or {}).get('usage_tokens',0),
                    usage_unreported_calls=(previous or {}).get('usage_unreported_calls',0),
                    attempts=(previous or {}).get('attempts',0)+1,previous_attempt=previous,
                    production_changed=False,shadow_candidate=None,limits=limits,results={},
                    code_revision=revision,runner_sha256=revision[Path(__file__).name])
        write(target,report) # Reserve both partitions before any inference; crashes cannot silently replay.
        started=time.monotonic()
        def elapsed_total(): return elapsed+time.monotonic()-started
        def score(cases):
            rows=[]
            for c in cases:
                if report['calls']>=limits['calls'] or elapsed_total()>=limits['seconds'] or report['usage_tokens']>=limits['tokens']:
                    raise ValueError('budget_exhausted')
                if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_changed')
                if config_revision(vault)!=report['config_digest']: raise ValueError('config_changed')
                if code_revision()!=revision: raise ValueError('code_changed')
                eligible=[{k:copy.deepcopy(r[k]) for k in ('id','title','statement','scope','domains')}
                          for r in corpus['candidates'] if r['scope'] in ('user',c['scope'])]
                expected_score_ids={r['id'] for r in eligible}
                report['calls']+=1; report['usage_unreported_calls']+=1
                report.pop('last_inference',None); write(target,report)
                result=evaluate(vault,c['query'],eligible,scope=c['scope'],source_versions=dict(corpus['source_versions']))
                if not isinstance(result,dict): raise ValueError('response_invalid')
                usage=result.get('usage',{})
                if not isinstance(usage,dict) or any(type(usage[k]) is not int or usage[k]<0 for k in ('input_tokens','output_tokens') if k in usage):
                    raise ValueError('usage_invalid')
                report['usage_tokens']+=sum(usage.get(k,0) for k in ('input_tokens','output_tokens'))
                if result.get('cache_hit') is True or {'input_tokens','output_tokens'}<=set(usage): report['usage_unreported_calls']-=1
                report['last_inference']=inference_metadata(result); write(target,report)
                if result['mode']=='off' or result.get('degraded'): raise ValueError('inference_unavailable')
                scores=result.get('scores')
                if not isinstance(scores,dict) or set(scores)!=expected_score_ids: raise ValueError('scores_invalid')
                if any(type(s) not in (int,float) or not math.isfinite(s) or not 0<=s<=2 for s in scores.values()): raise ValueError('scores_invalid')
                if elapsed_total()>=limits['seconds'] or report['usage_tokens']>limits['tokens']: raise ValueError('budget_exhausted')
                if config_revision(vault)!=report['config_digest']: raise ValueError('config_changed')
                if code_revision()!=revision: raise ValueError('code_changed')
                if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_changed')
                rows.append(dict(c,scores=dict(scores),latency_ms=result.get('latency_ms'),cache_hit=result.get('cache_hit',False)))
                report['results']['partial']=rows; write(target,report)
            report['results'].pop('partial',None)
            return rows
        try:
            report['config_digest']=config_revision(vault); write(target,report)
            dev_rows=score(dev); report['results']['development']=dev_rows
            base=metrics(dev_rows,baseline)
            trials={str(t):metrics(dev_rows,t) for t in thresholds}
            winners=[t for t in thresholds if improves(trials[str(t)],base)]
            report['development']=dict(baseline=base,candidates=trials)
            if not winners:
                report['status']='no_improvement'
            else:
                winner=min(winners,key=lambda t:(trials[str(t)]['missing'],trials[str(t)]['extra'],abs(t-baseline)))
                report['selected_before_holdout']=winner; write(target,report)
                test_rows=score(holdout); report['results']['holdout']=test_rows
                b=metrics(test_rows,baseline); a=metrics(test_rows,winner)
                report['holdout']=dict(baseline=b,candidate=a)
                passes=a['missing']<=b['missing'] and a['extra']<=b['extra']
                report['status']='shadow_candidate' if passes else 'holdout_rejected'
                if passes: report['shadow_candidate']=dict(threshold=winner,automatic_promotion=False,
                    scope='isolated_score_selector_only',requires='fresh real-task evaluation of full delivered context')
            if not snapshot_valid(vault,corpus['source_versions']): raise ValueError('snapshot_changed')
            if config_revision(vault)!=report['config_digest']: raise ValueError('config_changed')
            if code_revision()!=revision: raise ValueError('code_changed')
        except Exception as error:
            safe={'config_invalid','config_changed','code_changed','snapshot_changed','budget_exhausted',
                  'response_invalid','usage_invalid','scores_invalid','inference_unavailable'}
            report['status']='failed'; report['shadow_candidate']=None
            report['error']=str(error) if isinstance(error,ValueError) and str(error) in safe else 'execution_failed'
        report['attempt_elapsed_seconds']=time.monotonic()-started
        report['elapsed_seconds']=elapsed+report['attempt_elapsed_seconds']
        write(target,report)
        return dict(status=report['status'],report=str(target),calls=report['calls'],shadow_candidate=report['shadow_candidate'])


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--vault',type=Path,required=True)
    sub=p.add_subparsers(dest='command',required=True)
    f=sub.add_parser('freeze'); f.add_argument('--labels',type=Path,required=True); f.add_argument('--output',type=Path,required=True)
    r=sub.add_parser('run'); r.add_argument('--corpus',type=Path,required=True); r.add_argument('--output-dir',type=Path,required=True); r.add_argument('--resume-timeout',action='store_true')
    a=p.parse_args()
    try:
        if a.command=='freeze':
            if a.output.exists(): p.error('refuse_overwrite')
            write(a.output,freeze(a.vault,json.loads(a.labels.read_text(encoding='utf-8'))))
            result=dict(status='frozen',path=str(a.output))
        else:
            result=run(a.vault,json.loads(a.corpus.read_text(encoding='utf-8')),a.output_dir,resume=a.resume_timeout)
    except (ValueError,OSError,TypeError,KeyError) as error:
        safe={'schema_invalid','label_review_required','label_status_invalid','corpus_budget',
              'sources_required','source_version_invalid','candidate_invalid','duplicate_candidate',
              'case_invalid','duplicate_case','query_invalid','scope_invalid','origin_required',
              'families_required','labels_invalid','label_scope_violation','family_provenance_missing',
              'label_source_missing','snapshot_stale','snapshot_changed','ledger_invalid',
              'legacy_ledger_incomplete','insufficient_independent_families',
              'positive_negative_coverage_required','holdout_already_consumed','call_budget_preflight',
              'resume_missing','resume_not_eligible','resume_revision_changed','budget_exhausted',
              'config_invalid'}
        code=str(error) if isinstance(error,ValueError) and str(error) in safe else 'preflight_failed'
        print(json.dumps(dict(status='rejected',error=code)))
        return 2
    print(json.dumps(result,ensure_ascii=False))
    return int(result.get('status')=='failed' or result.get('previous_status') in ('failed','started'))

if __name__=='__main__': raise SystemExit(main())
