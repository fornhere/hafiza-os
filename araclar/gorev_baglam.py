"""Local, source-validated task context. No network and no memory writes."""
import math
import hashlib
import json
import re
from pathlib import Path
import hafiza as h
from is_ve_ders import brief

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tokens(text):
    return set(re.findall(r"[^\W_]+", text.casefold()))


# Deliberately finite inflection vocabulary, not a general Turkish stemmer.
_SUFFIXES = {'ı','i','u','ü','a','e','da','de','ta','te','dan','den','tan','ten',
 'ın','in','un','ün','nın','nin','nun','nün','na','ne','nı','ni','nu','nü',
 'ya','ye','yı','yi','yu','yü','la','le','yla','yle','lar','ler','ları','leri',
 'ım','im','um','üm','ımız','imiz','umuz','ümüz','ımızı','imizi','umuzu','ümüzü',
 'ımızın','imizin','umuzun','ümüzün','ımızda','imizde','umuzda','ümüzde',
 'nda','nde','ndan','nden','larımızı','lerimizi','larımız','lerimiz',
 'larını','lerini','larının','lerinin','larına','lerine','larda','lerde','lardan','lerden',
 'ki','sı','si','su','sü','sına','sine','suna','süne','sını','sini','sunu','sünü'}
_GENERIC = {'kapak','thumbnail','maskot','video','videosu','iş','proje'}

def query_words(text):
    # A proper-name apostrophe joins a suffix; quote boundaries remain boundaries.
    text = text.casefold().replace('i\u0307','i')
    text = re.sub(r"(?<=\w)['’](?=\w)", '', text)
    return re.findall(r"[^\W_]+", text)

def inflected(base, word):
    if base == word: return True
    if len(base) < 4: return False
    variants = [base]
    if base[-1:] in {'k','p','t','ç'}:
        variants.append(base[:-1]+{'k':'ğ','p':'b','t':'d','ç':'c'}[base[-1]])
    def suffix_chain(tail, depth=0):
        if not tail: return depth > 0
        if depth >= 4 or len(tail) > 20: return False
        return any(tail.startswith(suffix) and suffix_chain(tail[len(suffix):], depth+1)
                   for suffix in _SUFFIXES)
    return any(word.startswith(stem) and suffix_chain(word[len(stem):]) for stem in variants)

def one_typo(left, right):
    # Only long tokens: avoid kapak/kabak and short proper-name collisions.
    if min(len(left),len(right)) < 7 or abs(len(left)-len(right)) > 1: return False
    if len(left)==len(right):
        positions=[i for i,(a,b) in enumerate(zip(left,right)) if a!=b]
        return len(positions)==1 or (len(positions)==2 and positions[1]==positions[0]+1 and left[positions[0]]==right[positions[1]] and left[positions[1]]==right[positions[0]])
    short,long=sorted([left,right],key=len)
    return any(long[:i]+long[i+1:]==short for i in range(len(long)))

def alias_match(alias, words, fuzzy=False):
    parts=query_words(alias)
    if not parts: return False
    return all(any(inflected(part,word) or (fuzzy and one_typo(part,word)) for word in words) for part in parts)

# Function words cannot establish a memory match. Domain aliases belong in config.
_STOPWORDS = set('bir bu şu o ve veya ile için gibi daha çok az ne nasıl neden hangi ben benim sen bizim biz bana bunu şunu mı mi mu mü da de ama olarak olan olsun yap yapalım devam et üret'.split())
_SYNONYMS = ({'kapak', 'thumbnail'}, {'sunum', 'slayt', 'slideshow'},
             {'hafıza', 'bellek'}, {'yöntem', 'prosedür'}, {'yedek', 'yedekleme'})

def content_words(text):
    return set(query_words(text)) - _STOPWORDS

def word_match(left, right):
    if inflected(left, right) or inflected(right, left): return True
    return any(any(inflected(term, left) for term in group) and
               any(inflected(term, right) for term in group) for group in _SYNONYMS)

def rank_records(rows, query):
    """Query coverage weighted by corpus rarity; order cannot affect selection."""
    terms = content_words(query)
    documents = [(row, content_words(row.get('statement', ''))) for row in rows]
    frequencies = {term: sum(any(word_match(term, word) for word in words)
                             for _, words in documents) for term in terms}
    informative = {term for term in terms if 0 < frequencies[term] < max(2, len(rows)*0.5)}
    ranked = []
    for row, words in documents:
        matched = {term for term in terms if any(word_match(term, word) for word in words)}
        if not matched or (informative and not matched.intersection(informative)): continue
        score = sum(1 + math.log((len(rows) + 1) / (frequencies[term] + 1)) for term in matched)
        ranked.append((score, len(matched), row))
    return [row for _, _, row in sorted(ranked, key=lambda item:
            (-item[0], -item[1], item[2].get('memory_id', '')))]

def select_projects(projects, query, cwd=None):
    words=query_words(query)
    deictic=any(w in words for w in ('dünkü','o','şu','önceki'))
    def matches(project,fuzzy=False):
        return any(alias_match(alias,words,fuzzy) and not (deictic and set(query_words(alias)) <= _GENERIC)
                   for alias in project.get('aliases',[]))
    explicit=[p for p in projects if matches(p)]
    if not explicit: explicit=[p for p in projects if matches(p,True)]
    specific=[p for p in explicit if any(alias_match(a,words) and not set(query_words(a)) <= _GENERIC for a in p.get('aliases',[]))]
    if specific: explicit=specific
    located=[p for p in projects if cwd and any(Path(cwd).resolve().is_relative_to(Path(r).resolve()) for r in p.get('roots',[]))]
    # Nested workspaces choose the most specific root, never a sibling by recency.
    if len(located)>1:
        depths={p['id']:max(len(Path(r).resolve().parts) for r in p.get('roots',[]) if Path(cwd).resolve().is_relative_to(Path(r).resolve())) for p in located}
        located=[p for p in located if depths[p['id']]==max(depths.values())]
    chosen=explicit or located
    reason='explicit' if explicit else ('cwd' if located else 'unresolved')
    return chosen, reason

def config(vault):
    path = vault / 'komuta/gorev-baglam.json'
    try: return json.loads(path.read_text()) if path.exists() else {'projects': []}
    except (ValueError,OSError): return {'projects': [], 'invalid': True}

def validate_asset(asset, actual_paths=None):
    path = Path(asset['path']).resolve()
    roots = [Path(p).resolve() for p in asset.get('allowed_roots', [])]
    if not roots or not any(path.is_relative_to(p) for p in roots):
        raise ValueError('asset outside approved roots')
    if asset.get('status') != 'approved' or not path.is_file():
        raise ValueError('asset missing or not approved')
    source = Path(asset.get('approval_source', ''))
    evidence = asset.get('approval_evidence', '')
    if not any(source.resolve().is_relative_to(p) for p in roots):
        raise ValueError('approval source outside approved roots')
    if len(evidence) < 10 or not source.is_file() or evidence not in source.read_text():
        raise ValueError('asset approval evidence missing')
    if digest(path) != asset.get('sha256'):
        raise ValueError('asset hash changed')
    if actual_paths is not None and path not in {Path(p).resolve() for p in actual_paths}:
        raise ValueError('approved asset absent from actual tool inputs')
    return path

def validate_inputs(assets, actual_paths, role='identity'):
    required = [a for a in assets if a.get('role') == role]
    if not required: raise ValueError('required asset role missing')
    return [str(validate_asset(a, actual_paths)) for a in required]

def asset_claim_overrides(vault):
    """Exact configured asset revisions only; canonical records stay untouched."""
    overrides={}
    for project in config(vault).get('projects',[]):
        for asset in project.get('assets',[]):
            ids=asset.get('replaces_memory_ids',[])
            if not isinstance(ids,list): continue
            try:
                validate_asset(asset)
                reason='asset_revision_replaced'
            except (ValueError,OSError,KeyError):
                reason='asset_revision_conflict'
            for ident in ids:
                if isinstance(ident,str) and ident:
                    # Conflicting configured replacements must never restore old claims.
                    previous=overrides.get(ident)
                    overrides[ident]='asset_revision_conflict' if previous and previous!=reason else reason
    return overrides


def build_task_package(vault, query, cwd=None, budget=5000, history="auto"):
    if history not in ("auto", "always", "never"): raise ValueError("invalid history mode")
    vault = Path(vault).resolve(); words = tokens(query)
    selected=[]; omitted=[]; lines=[]; used=0; assets=[]; source_versions={}
    budget=max(0, int(budget)); candidates=[]; current_facts=[]; current_tasks=[]
    projects=[]
    cfg=config(vault)
    if cfg.get('invalid'): omitted.append('config_invalid')
    projects, match_reason = select_projects(cfg.get('projects', []), query, cwd)
    project = projects[0] if len(projects)==1 else None
    workflows=[]
    if project:
        for candidate in cfg.get('projects',[]):
            if candidate['id']==project['id']: continue
            if any(set(query_words(a)) <= {'kapak','thumbnail','maskot'} and alias_match(a,query_words(query)) for a in candidate.get('aliases',[]) if query_words(a)):
                workflows.append(candidate)
        if workflows:
            project=dict(project)
            project['assets']=list(project.get('assets',[]))
            project['working_sources']=list(project.get('working_sources',[]))
            for workflow in workflows:
                for asset in workflow.get('assets',[]):
                    if not any(a['id']==asset['id'] for a in project['assets']): project['assets'].append(asset)
                project['working_sources'].extend(workflow.get('working_sources',[]))
    scope = 'project:'+project['id'] if project else 'user'
    def add(ident, text):
        priority = {'unresolved_reference':0, 'ambiguous_project':0, 'project':1,
                    'unresolved':2, 'methods':3, 'input-check':3, 'workflow':4,
                    'working-source':8, 'working-root':8, 'summary-policy':6}.get(ident, 10)
        if any(ident == asset.get('id') for asset in (project or {}).get('assets', [])): priority=2
        if ident in task_ids: priority=4
        candidates.append((priority, len(candidates), ident, text))
        return True
    task_ids=set()
    qwords=query_words(query)
    deictic=any(w in qwords for w in ('dünkü','o','şu','önceki'))
    task_reference=any(inflected(base,word) for base in ('kapak','video','proje','çıktı') for word in qwords) or any(w in qwords for w in ('iş','işi','işe','işin'))
    if not projects and deictic and task_reference:
        add('unresolved_reference','Hangi proje veya önceki çıktı olduğu bağlamdan belirlenemedi; kaynak seçmeden netleştir.')
    if len(projects)>1:
        omitted.append('ambiguous_project')
        add('ambiguous_project','Birden fazla proje eşleşti; proje seçimini netleştirmeden dosya veya onay uydurma.')
    overrides=asset_claim_overrides(vault)
    eligible=[]
    for row in h.load_catalog(vault):
        if not any(h.retrievable(row,context_scope) for context_scope in [scope]+['project:'+w['id'] for w in workflows]): continue
        if row.get('memory_id') in overrides:
            if rank_records([row], query): omitted.append(row['memory_id']+':'+overrides[row['memory_id']])
            continue
        if h.context_record_errors(vault,row):
            if rank_records([row], query): omitted.append(row.get('memory_id','unknown')+':invalid')
            continue
        eligible.append(row)
    # Out-of-scope, stale and replaced rows must not influence corpus rarity.
    for row in rank_records(eligible, query):
        if add(row['memory_id'],'Güncel kayıt: '+row['statement']+' (kaynak: '+row['source_path']+')'):
            current_facts.append(row)
            priority,sequence,ident,text=candidates[-1]
            candidates[-1]=(4,sequence,ident,text)
            source_versions[row['source_path']]=digest(h.source_file(vault,row['source_path']))
    if project:
        add('project', 'Proje: '+project['id'])
        if workflows: add('workflow', 'Bu projedeki üretim yöntemi: '+', '.join(w['id'] for w in workflows)+'. Yöntem referansları proje seçimini değiştirmez.')
        for issue in project.get('unresolved',[]): add('unresolved', 'Teyit gerekli: '+issue)
        for ref in project.get('working_sources',[]):
            path=Path(ref['path']).resolve()
            if path.is_file():
                source_versions[str(path)]=digest(path)
                add('working-source',ref['role']+': '+str(path)+'; kaynak: '+ref['evidence_source']+'. Gerektikçe aç; varlık ≠ kabul.')
            else: omitted.append(str(path)+':missing')
        for working_root in project.get('roots',[]): add('working-root','Çalışma kökü: '+working_root+'; dosyada işlem yapmadan canlı Git HEAD/status ve ilgili testleri doğrula.')
        for task in brief(vault,limit=100):
            if task.get('project_id')==project['id'] or task['id'] in project.get('task_ids',[]):
                task_ids.add(task['id'])
                source=h.source_file(vault,task['source_path'])
                pinned=task.get('source_content_hash')==h.statement_hash(source.read_text())
                if task.get('source_content_hash') and not pinned:
                    omitted.append(task['id']+':source_changed'); continue
                if pinned: current_tasks.append(task)
                source_versions[task['source_path']]=digest(source)
                add(task['id'],('Güncel sonraki adım: ' if pinned else 'Kaynağı yeniden doğrulanacak iş: ')+task['title']+': '+task['next_step']+' (kaynak: '+task['source_path']+')')
        for asset in project.get('assets',[]):
            try: path=validate_asset(asset)
            except (ValueError,OSError,KeyError) as e: omitted.append(asset.get('id','asset')+':'+str(e)); continue
            if add(asset['id'], 'Onaylı '+asset['role']+': '+str(path)+'; hash: '+asset['sha256']+'. Gerçek araç girdisini validate_inputs ile doğrula; dosyanın bulunması kullanıldığını kanıtlamaz.'): assets.append(asset)
    from ders_baglam import context
    methods=context(vault,query,budget=min(2600, budget), project_id=project['id'] if project else None, workflow_ids=[w['id'] for w in workflows])
    if methods: add('methods',methods)
    # Current records are a derived view, never a new canonical statement.
    # Project names and continuation words alone do not prove topic coverage.
    continuation=any(alias_match(term,qwords) for term in ('devam','kaldık','sonraki adım'))
    def history_phrase(term):
        parts=query_words(term)
        return any(all(inflected(part,word) for part,word in zip(parts,qwords[i:i+len(parts)]))
                   for i in range(len(qwords)-len(parts)+1))
    explicit_history=any(history_phrase(term) for term in
                         ('geçmiş','dün','dünkü','hatırla','neden seçtik','eski karar','önceki karar','önceki oturum'))
    topic=content_words(query)-set(query_words('devam kaldık nerede şimdi sonraki adım edelim iş işine önceki ders dersini uygulayarak bu ayki teslim kontrol plan planını yaz hazırla yap çıkar oluştur'))
    if project:
        for alias in project.get('aliases',[]):
            topic={t for t in topic if not any(word_match(t,a) for a in query_words(alias))}
    # Only candidates that fit the actual bounded package can satisfy coverage.
    preview_ids=set(); preview_used=0
    for _,_,ident,text in sorted(candidates):
        cost=len(text)+(1 if preview_ids else 0)
        if preview_used+cost<=budget: preview_ids.add(ident); preview_used+=cost
    current_facts=[r for r in current_facts if r['memory_id'] in preview_ids]
    current_tasks=[t for t in current_tasks if t['id'] in preview_ids]
    coverage_text=' '.join(r['statement'] for r in current_facts)+' '+ ' '.join(t['title']+' '+t['next_step'] for t in current_tasks)
    coverage_words=content_words(coverage_text+(' '+methods if 'methods' in preview_ids else ''))
    covered=bool(current_tasks or current_facts) and all(any(word_match(t,w) for w in coverage_words) for t in topic)
    # Generic continuation requires an actual next step, not just preferences.
    if continuation and not topic: covered=bool(current_tasks)
    use_history=bool(project) and (history=='always' or (history=='auto' and
                         (explicit_history or (continuation and not covered))))
    history_reason=('explicit' if history=='always' or explicit_history else
                    'current_context_insufficient' if use_history else 'current_context_sufficient' if covered else 'not_requested')
    if history=='never': history_reason='disabled'
    if project and covered and not use_history:
        add('summary-policy','Kaynaklı özet yeterliyse yeniden okuma. Hash ≠ doğruluk; yeni talep öncelikli. Belirsizlikte/işlemde kaynağı doğrula.')
    if use_history:
        for relative in sorted(project.get('episode_sources',[]), key=lambda p: len(words & tokens(p)), reverse=True)[:3]:
            try:
                path=h.source_file(vault,relative); text=path.read_text()
                if h.contains_secret(text): continue
                source_versions[relative]=digest(path)
                add(relative,'Tarihli geçmiş, güncel dosya yerine geçmez: '+relative+'\n'+text[:700]+'\n[Kaynak özeti kesilmiş olabilir; karar için tam kaynağı aç.]')
            except (OSError,ValueError): omitted.append(relative+':missing')
    if assets:
        instruction='Üretim öncesi gorev_baglam.py package ile bu paketi al; gerçek araca gönderilecek referans yollarını JSON dizisi yapıp validate-inputs --package <paket.json> --actual-inputs <yollar.json> çalıştır. Bu denetim araç çağrısının otomatik gözlemcisi değildir; gerçek argümanlarla aynı yollar olmalı.'
        instruction += ' Paket varlık rolleri: '+', '.join(sorted({a['role'] for a in assets}))+'. validate-inputs için ilgili --role değerini kullan.'
        if not add('input-check',instruction):
            omitted.append('input-check:budget')
    errors=[reason for reason in omitted if not reason.endswith(':budget')]
    if errors:
        detail='Bağlam kontrolü: '+ '; '.join(errors)+'. Eksik veya değişmiş kaynağı onaylı sayma.'
        if len(detail)>min(600,budget): detail='Bağlam kontrolü: Geçersiz veya değişmiş kaynaklar dışlandı; omitted_reasons alanını incele.'
        candidates.append((0,-1,'context-check',detail))
    for _, _, ident, text in sorted(candidates):
        cost=len(text)+(1 if lines else 0)
        if used+cost>budget:
            omitted.append(ident+':budget'); continue
        lines.append(text);selected.append(ident);used+=cost
    assets=[asset for asset in assets if asset['id'] in selected]
    result={'workflow_ids':[w['id'] for w in workflows],'match_reason':match_reason,'project_id':project['id'] if project else None,'assets':assets,'source_versions':source_versions,'selected_ids':selected,'omitted_reasons':omitted,'text':'\n'.join(lines)}
    result['history']={'mode':history,'included':any(p in selected for p in (project or {}).get('episode_sources',[])), 'requested':use_history,'reason':history_reason,'topic_covered':covered}
    result['summary']={'record_ids':[r['memory_id'] for r in current_facts if r['memory_id'] in selected], 'task_ids':[t['id'] for t in current_tasks if t['id'] in selected], 'derived':True}
    result['usage']={'context_chars':len(result['text']), 'budget_chars':budget,
                     'selected_count':len(selected), 'omitted_count':len(omitted),
                     'token_count':None, 'token_count_method':'not_measured'}
    result['package_id']=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return result


def hydrate_remote(vault, results, scope='user'):
    """Remote search ranks IDs; current canonical rows supply all content."""
    rows = {r['memory_id']: r for r in h.load_catalog(vault)}
    overrides=asset_claim_overrides(vault)
    output=[]
    for item in results:
        ident=(item.get('metadata') or {}).get('memory_id')
        if ident in overrides:
            if overrides[ident]=='asset_revision_conflict':
                raise ValueError('asset_revision_conflict: replacement invalid; old claim excluded')
            continue
        row=rows.get(ident)
        if row and h.retrievable(row,scope) and not h.context_record_errors(vault,row):
            output.append({'memory':row['statement'],'metadata':row})
    return output

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--vault',type=Path,default=Path(__file__).resolve().parents[1])
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('package');p.add_argument('query');p.add_argument('--cwd');p.add_argument('--history',choices=('auto','always','never'),default='auto')
    p=sub.add_parser('validate-inputs');p.add_argument('--package',type=Path,required=True);p.add_argument('--actual-inputs',type=Path,required=True);p.add_argument('--role',default='identity')
    args=parser.parse_args()
    if args.command=='package': result=build_task_package(args.vault,args.query,args.cwd,history=args.history)
    else: result={'validated':validate_inputs(json.loads(args.package.read_text())['assets'],json.loads(args.actual_inputs.read_text()),args.role)}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
