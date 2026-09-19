"""Source-bound, human-readable knowledge notes. No model calls or canonical writes."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
import hafiza as h


# Shared established topics; aliases do not broaden card scope or domains.
DOMAIN_ALIASES = {'site':('site','web','website'),
                  'sunum':('sunum','slayt','slideshow'),
                  'thumbnail':('thumbnail','kapak'),
                  'twitter':('twitter','tweet'),
                  'proje':('proje','orvant'),
                  'video':('video','youtube','çekim')}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _safe(vault, relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or '\\' in relative or ':' in relative: raise ValueError('unsafe_source_path')
    result=vault/p
    if result.is_symlink() or not result.resolve().is_relative_to(vault.resolve()): raise ValueError('unsafe_source_path')
    return result


def _validate(vault, data):
    d=dict(data);d.pop('expected_version',None)
    required={'id','title','kind','statement','scope','domains','status','sources'}
    allowed=required|{'examples','relations','reviewed_by','review_note'}
    if not required<=d.keys() or d.keys()-allowed: raise ValueError('invalid_fields')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}',d['id']): raise ValueError('invalid_id')
    for k in ('title','statement','scope'):
        if not isinstance(d[k],str) or not d[k].strip():raise ValueError('invalid_text')
    if d['kind'] not in {'preference','decision','lesson','example'} or d['status'] not in {'reviewed','proposed','rejected','superseded'}:raise ValueError('invalid_kind_status')
    if d['scope']!='user' and not re.fullmatch(r'project:[\w-]+',d['scope']):raise ValueError('invalid_scope')
    if not isinstance(d['domains'],list) or not d['domains'] or any(not isinstance(x,str) or not re.fullmatch(r'[\w-]+',x) for x in d['domains']):raise ValueError('invalid_domains')
    if d['status']=='reviewed' and any(not isinstance(d.get(k),str) or not d[k].strip() for k in ('reviewed_by','review_note')):raise ValueError('review_required')
    if h.contains_secret(json.dumps(d,ensure_ascii=False)):raise ValueError('restricted_record')
    if not isinstance(d['sources'],list) or not d['sources']:raise ValueError('sources_required')
    contents=[]
    for s in d['sources']:
        if set(s)!={'path','sha256','evidence'}:raise ValueError('invalid_source')
        path=_safe(vault,s['path']);text=path.read_text()
        if h.contains_secret(text):raise ValueError('restricted_source')
        if digest(path)!=s['sha256']:raise ValueError('source_changed')
        if not isinstance(s['evidence'],str) or len(s['evidence'].strip())<10 or s['evidence'] not in text:raise ValueError('evidence_missing')
        contents.append(text)
    for e in d.get('examples',[]):
        if set(e)-{'path','sha256','role','acceptance','evidence_source','acceptance_evidence'}:raise ValueError('invalid_example')
        p=Path(e['path']);idx=e['evidence_source']
        if not p.is_absolute() or p.is_symlink() or not p.is_file():raise ValueError('invalid_example_path')
        if digest(p)!=e['sha256']:raise ValueError('example_changed')
        if not isinstance(idx,int) or isinstance(idx,bool) or not 0<=idx<len(contents):raise ValueError('invalid_evidence_source')
        if not isinstance(e['role'],str) or not e['role'].strip() or e['acceptance'] not in {'unknown','accepted','rejected'}:raise ValueError('invalid_example_role')
        if e['acceptance']!='unknown':
            quote=e.get('acceptance_evidence','')
            if len(quote.strip())<10 or quote not in contents[idx]:raise ValueError('acceptance_evidence_required')
    for r in d.get('relations',[]):
        if set(r)!={'target','reason'} or not isinstance(r['reason'],str) or not r['reason'].strip():raise ValueError('invalid_relation')
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,100}',r['target']) or r['target']==d['id']:raise ValueError('invalid_relation_target')
        if not (vault/'bilgi'/f"{r['target']}.md").is_file():raise ValueError('missing_relation_target')
    return d


def _body(d):
    lines=[f"# {d['title']}",'',d['statement'],'',f"Durum: {d['status']} | Alan: {', '.join(d['domains'])} | Kapsam: {d['scope']}",'','## Kaynaklar']
    for s in d['sources']:lines.extend([f"- [[{s['path']}]]",f"  Kanıt: {s['evidence']}"])
    for e in d.get('examples',[]):lines.append(f"- Örnek: [{e['role']}](<{e['path']}>) — kabul: {e['acceptance']}")
    if d.get('relations'):
        lines.extend(['','## İlişkiler'])
        for r in d['relations']:lines.append(f"- [[bilgi/{r['target']}]]: {r['reason']}")
    if d.get('reviewed_by'):lines.extend(['',f"İnceleyen: {d['reviewed_by']}",f"İnceleme: {d.get('review_note','')}"])
    return '\n'.join(lines)+'\n'


def _read(path):
    raw=path.read_text();match=re.fullmatch(r'<!-- bilgi-agi-v1\n(.*?)\n-->\n(.*)',raw,re.S)
    if not match:raise ValueError('unmanaged_note')
    meta=json.loads(match[1]);body=match[2]
    if hashlib.sha256(body.encode()).hexdigest()!=meta['body_sha256']:raise ValueError('note_manually_changed')
    if body!=_body(meta['record']):raise ValueError('note_metadata_changed')
    return meta['record']


def _write(path,text):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.bilgi-')
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:stream.write(text)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)


def register(vault,data,apply=False):
    return h.serialized(_register)(Path(vault),data,True) if apply else _register(Path(vault),data,False)


def _register(vault,data,apply=False):
    vault=Path(vault);d=_validate(vault,data);folder=vault/'bilgi'
    if folder.is_symlink():raise ValueError('unsafe_knowledge_folder')
    path=folder/f"{d['id']}.md";exists=path.exists()
    before_hash=digest(path) if exists else None
    if path.is_symlink():raise ValueError('unsafe_note')
    if exists:
        old=_read(path)
        if old==d:return dict(changed=False,path=str(path),version=digest(path),applied=False)
        if data.get('expected_version')!=digest(path):raise ValueError('expected_version_required')
    body=_body(d);meta=dict(record=d,body_sha256=hashlib.sha256(body.encode()).hexdigest())
    text='<!-- bilgi-agi-v1\n'+json.dumps(meta,ensure_ascii=False,sort_keys=True)+'\n-->\n'+body
    if apply:
        if exists:
            archive=folder/'.history'/d['id']/f'{digest(path)}.md'
            if not archive.exists():_write(archive,path.read_text())
        _write(path,text)
        index=folder/'README.md'
        index_text='<!-- bilgi-agi-index-v1 -->\n# Bilgi ağı\n\n'+''.join(f'- [[bilgi/{p.stem}]]\n' for p in sorted(folder.glob('*.md')) if p.name!='README.md')
        if not index.exists() or index.read_text().startswith('<!-- bilgi-agi-index-v1 -->\n'):_write(index,index_text)
    result=dict(changed=True,path=str(path),version=hashlib.sha256(text.encode()).hexdigest(),applied=apply)
    if apply:
        from hafiza_gorunurluk import write_note
        result['notice']=write_note(path,before_hash,result['version'],d['title']+' ('+d['status']+')')
    return result


def _rows(vault):
    records=[];diagnostics=[]
    folder=vault/'bilgi'
    if folder.is_symlink():return [],['unsafe_knowledge_folder']
    for path in sorted(folder.glob('*.md')):
        if path.name=='README.md':continue
        try:
            if path.is_symlink():raise ValueError('unsafe_note')
            d=_validate(vault,_read(path))
            if d['id']!=path.stem:raise ValueError('note_id_mismatch')
            if d['status']=='reviewed':records.append(d)
            else:diagnostics.append(f"{path.stem}:not_reviewed")
        except (ValueError,OSError,KeyError,TypeError) as exc:diagnostics.append(f'{path.stem}:{exc}')
    return records,diagnostics


def assess_source(vault,data,apply=False):
    return h.serialized(_assess_source)(Path(vault),data,True) if apply else _assess_source(Path(vault),data,False)


def _assess_source(vault,data,apply=False):
    vault=Path(vault)
    if set(data)!={'path','sha256','outcome','record_ids','reason','reviewed_by'}:raise ValueError('invalid_assessment_fields')
    source=_safe(vault,data['path'])
    if digest(source)!=data['sha256']:raise ValueError('source_changed')
    if h.contains_secret(source.read_text()) or h.contains_secret(json.dumps(data,ensure_ascii=False)):raise ValueError('restricted_source')
    if data['outcome'] not in {'linked','no_relevant_knowledge','deferred'}:raise ValueError('invalid_outcome')
    if any(not isinstance(data[k],str) or not data[k].strip() for k in ('reason','reviewed_by')):raise ValueError('review_required')
    if not isinstance(data['record_ids'],list):raise ValueError('invalid_record_ids')
    if data['outcome']=='linked':
        if not data['record_ids']:raise ValueError('linked_records_required')
        rows,_=_rows(vault);lookup={d['id']:d for d in rows}
        for key in data['record_ids']:
            if key not in lookup or not any(s['path']==data['path'] and s['sha256']==data['sha256'] for s in lookup[key]['sources']):raise ValueError('linked_record_unverified')
    elif data['record_ids']:raise ValueError('unexpected_record_ids')
    path=vault/'bilgi/.reviews.jsonl'
    if path.parent.is_symlink() or path.is_symlink():raise ValueError('unsafe_review_journal')
    old=path.read_text() if path.exists() else ''
    previous=[json.loads(line) for line in old.splitlines() if line.strip()]
    last=next((entry for entry in reversed(previous) if entry.get('path')==data['path']),None)
    if last==data:return dict(applied=False,changed=False,assessment=data)
    if apply:_write(path,old+json.dumps(data,ensure_ascii=False)+'\n')
    return dict(applied=apply,assessment=data)


def status(vault):
    vault=Path(vault);rows,diagnostics=_rows(vault);latest={}
    journal=vault/'bilgi/.reviews.jsonl'
    if journal.exists() and not journal.is_symlink() and not journal.parent.is_symlink():
        for line in journal.read_text().splitlines():
            try:
                entry=json.loads(line);latest[entry['path']]=entry
            except (ValueError,KeyError,TypeError):diagnostics.append('invalid_source_assessment')
    sources=sorted(set((vault/'gelen-kutusu').glob('*.md'))|set((vault/'gelen-kutusu/codex-oturumları').glob('*.md')))
    pending=[];deferred=[];complete=[]
    for path in sources:
        if path.name.lower()=='readme.md':continue
        relative=str(path.relative_to(vault));entry=latest.get(relative)
        if entry:
            try:
                assess_source(vault,entry)
                (deferred if entry['outcome']=='deferred' else complete).append(relative)
                continue
            except (ValueError,OSError,KeyError,TypeError):diagnostics.append(relative+':assessment_stale')
        pending.append(relative)
    return dict(eligible=len(rows),records=[d['id'] for d in rows],diagnostics=diagnostics,
                unreviewed_sources=pending,deferred_sources=deferred,reviewed_sources=complete,
                coverage_note='Unreviewed means no current source assessment; it does not imply a missing decision.')


def retrieve(vault,query,project_id=None,budget=1800):
    from jev_retrieval import knowledge
    return knowledge(vault, query, project_id, budget,
                     lambda: _retrieve_local(vault, query, project_id, budget))


def _retrieve_local(vault,query,project_id=None,budget=1800):
    from gorev_baglam import content_words,word_match
    vault=Path(vault);rows,diagnostics=_rows(vault);terms=content_words(query)
    domain_aliases=DOMAIN_ALIASES
    requested={domain for domain,aliases in domain_aliases.items() if any(word_match(alias,word) for alias in aliases for word in terms)}
    ranked=[]
    # These are candidate analogies, never new user preferences. Only features
    # actually named in the reviewed statement can support a transfer.
    bridges={('sunum','site'),('site','sunum')}
    features=[('anlatı sırası',('altyapı','ayrıntı','anlatı','hikâye','akış')),
              ('metin dili',('konuşma','Türkçe','sözcük','cümle','anlatım')),
              ('tipografi',('tipografi','font','yazı tipi')),
              ('renk',('renk','palet')),
              ('yerleşim',('boşluk','hiyerarşi','kompozisyon','yerleşim')),
              ('hareket',('animasyon','hareket'))]
    for d in rows:
        if d['scope']!='user' and d['scope']!=f'project:{project_id}':continue
        transfer=None
        if requested and 'all' not in d['domains'] and not requested.intersection(d['domains']):
            targets=sorted({target for source in d['domains'] for target in requested if (source,target) in bridges})
            words=content_words(d['statement'])
            aspects=[label for label,aliases in features if any(word_match(t,w) for alias in aliases for t in content_words(alias) for w in words)]
            if d['kind']!='preference' or not targets or not aspects:continue
            transfer=dict(status='proposed',source_record_id=d['id'],source_domains=d['domains'],target_domains=targets,
                          aspects=aspects,reason='İki işte de '+', '.join(aspects)+' kararları bulunabilir; uygunluğu bu görevde değerlendirilmelidir.')
        # Domain-specific knowledge needs an explicit domain query; do not generalize taste.
        if not requested and 'all' not in d['domains']:continue
        words=content_words(d['title']+' '+d['statement']+' '+' '.join(d['domains']))
        score=sum(any(word_match(t,w) for w in words) for t in terms)
        if score or transfer:ranked.append((score,d,transfer))
    ranked.sort(key=lambda item:(item[2] is not None,-item[0],item[1]['id']))
    selected=[];transfers=[];cards=[];versions={};valid_ids={d['id'] for d in rows}
    for _,d,transfer in ranked:
        card=f"Bilgi [{d['kind']}; {', '.join(d['domains'])}]: {d['statement']}\nKaynak: bilgi/{d['id']}.md"
        if transfer:
            card='Uyarlama önerisi ['+', '.join(d['domains'])+' → '+', '.join(transfer['target_domains'])+']: '+d['statement']+'\nAktarılabilecek özellik: '+', '.join(transfer['aspects'])+'. '+transfer['reason']+' Yeni alanda kullanıcı onayı değildir; renk/font gibi belirtilmeyen özellikleri çıkarma.\nKaynak: bilgi/'+d['id']+'.md'
        for e in d.get('examples',[]):card+=f"\nÖrnek ({e['acceptance']}; {e['role']}): {e['path']}"
        for r in d.get('relations',[]):
            if r['target'] in valid_ids:card+=f"\nİlişki: {r['target']} — {r['reason']}"
            else:diagnostics.append(f"{d['id']}:relation_unverified:{r['target']}")
        if len('\n\n'.join(cards+[card]))>max(0,budget):continue
        cards.append(card)
        if transfer:transfers.append(dict(transfer,source_record=d))
        else:selected.append(d)
        versions[f"bilgi/{d['id']}.md"]=digest(vault/'bilgi'/f"{d['id']}.md")
        for s in d['sources']:versions[s['path']]=s['sha256']
        for e in d.get('examples',[]):versions[e['path']]=e['sha256']
    text='\n\n'.join(cards)
    if requested and not selected and not transfers:
        warning=('Eşleşen bilgi var, ancak bağlam bütçesine sığmadı.' if ranked else 'Bu iş alanı için doğrulanmış ve eşleşen tercih/örnek bulunamadı; başka alandaki beğeniler genellenmedi.')
        if len(warning)<=budget:text=warning
    return dict(text=text,records=selected,transfers=transfers,source_versions=versions,diagnostics=diagnostics)


def main():
    p=argparse.ArgumentParser();p.add_argument('--vault',type=Path,required=True);subs=p.add_subparsers(dest='command',required=True)
    reg=subs.add_parser('register');reg.add_argument('--input-json',type=Path,required=True);reg.add_argument('--apply',action='store_true')
    assess=subs.add_parser('assess-source');assess.add_argument('--input-json',type=Path,required=True);assess.add_argument('--apply',action='store_true')
    ctx=subs.add_parser('context');ctx.add_argument('query');ctx.add_argument('--project-id');ctx.add_argument('--budget',type=int,default=1800)
    review=subs.add_parser('review');review.add_argument('--project-id');review.add_argument('--card-id',action='append');review.add_argument('--anchor-id')
    proposal=subs.add_parser('review-candidate');proposal.add_argument('--input-json',type=Path,required=True);proposal.add_argument('--project-id')
    subs.add_parser('status');a=p.parse_args()
    try:
        if a.command=='review-candidate':
            from jev_review import audit_proposed
            if a.input_json.stat().st_size>100000: raise ValueError('candidate_budget_exceeded')
            print(json.dumps(audit_proposed(a.vault,json.loads(a.input_json.read_text()),a.project_id),ensure_ascii=False,indent=2))
            return
        if a.command=='review':
            from jev_review import audit
            print(json.dumps(audit(a.vault,a.project_id,a.card_id,a.anchor_id),ensure_ascii=False,indent=2))
            return
        result=(register if a.command=='register' else assess_source)(a.vault,json.loads(a.input_json.read_text()),a.apply) if a.command in {'register','assess-source'} else retrieve(a.vault,a.query,a.project_id,a.budget) if a.command=='context' else status(a.vault)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,KeyError,TypeError) as exc:p.exit(1,f'{exc}\n')


if __name__=='__main__':main()
