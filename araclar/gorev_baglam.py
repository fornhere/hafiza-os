"""Source-validated task context with optional bounded Jev advice; no memory writes."""
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
    # Explicit domain vocabulary; do not infer vowel loss for arbitrary words.
    if base == 'beyin': variants.append('beyn')
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
    # Without a distinguishing term, a word shared by most records (e.g. the
    # user's name) selects only when it covers at least half of the query.
    ranked = []
    for row, words in documents:
        matched = {term for term in terms if any(word_match(term, word) for word in words)}
        if not matched or (informative and not matched.intersection(informative)): continue
        if not informative and 2 * len(matched) < len(terms): continue
        # Long prompts share incidental words with almost every record; measured on
        # real prompts with erisim_olc.py, one overlapping word selected mostly noise.
        if len(terms) > 3 and len(matched & informative if informative else matched) < 2: continue
        score = sum(1 + math.log((len(rows) + 1) / (frequencies[term] + 1)) for term in matched)
        ranked.append((score, len(matched), row))
    return [row for _, _, row in sorted(ranked, key=lambda item:
            (-item[0], -item[1], item[2].get('memory_id', '')))]

def task_intent(text):
    """Exclude skill packaging from topic matching, preserving ordinary user paths.

    This only changes the retrieval query, never captured source evidence.
    """
    def skill_block(match):
        block = match.group(0)
        name = re.search(r'<name>\s*([^<]+?)\s*</name>', block, re.I)
        path = re.search(r'<path>\s*([^<]+?)\s*</path>', block, re.I)
        if name and path and path.group(1).strip().casefold().endswith('/skill.md'):
            return name.group(1).strip()
        return block
    text = re.sub(r'<skill(?:\s[^>]*)?>.*?</skill>', skill_block, text,
                  flags=re.S | re.I)
    return re.sub(r'\[(\$[^\]\n]+)\]\(<?[^()\n]*?/SKILL\.md>?\)',
                  lambda match: match.group(1), text, flags=re.I)


def select_projects(projects, query, cwd=None):
    words=query_words(task_intent(query))
    deictic=any(w in words for w in ('dünkü','o','şu','önceki'))
    def matches(project,fuzzy=False):
        return any(alias_match(alias,words,fuzzy) and not (deictic and set(query_words(alias)) <= _GENERIC)
                   for alias in project.get('aliases',[]))
    # Archived projects answer only an exact alias, never a fuzzy match or cwd.
    active=[p for p in projects if p.get('status','aktif')!='arsiv']
    explicit=[p for p in projects if matches(p)]
    if not explicit: explicit=[p for p in active if matches(p,True)]
    specific=[p for p in explicit if any(alias_match(a,words) and not set(query_words(a)) <= _GENERIC for a in p.get('aliases',[]))]
    if specific: explicit=specific
    located=[p for p in active if cwd and any(Path(cwd).resolve().is_relative_to(Path(r).resolve()) for r in p.get('roots',[]))]
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


def continuation_request(query):
    words = query_words(task_intent(query))
    return any(alias_match(term, words) for term in ('devam', 'kaldık', 'sonraki adım'))


class RevisionMap(dict):
    """A merged read set must never hide two observed versions of one path."""
    conflict = False
    def __setitem__(self, key, value):
        if key in self and self[key] != value: self.conflict = True
        super().__setitem__(key, value)
    def update(self, other):
        for key, value in other.items(): self[key] = value


def build_task_package(vault, query, cwd=None, budget=5000, history="auto", view="auto", previous_user=None):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from jev_client import evaluation_context
    import jev_client
    from is_ve_ders import TASKS, LESSONS
    vault = Path(vault).resolve()
    previous_user = previous_user if isinstance(previous_user, str) else None
    ledgers = [h.CATALOG_PATH, h.SOURCE_BINDINGS, TASKS, LESSONS,
               Path('komuta/gorev-baglam.json')]
    def revisions():
        return {str(p): digest(vault/p) if (vault/p).is_file() else None for p in ledgers}
    before = revisions()
    rerank_state = None
    skip_memory = False
    gate = None
    try: rerank_mode = jev_client.purpose_mode(jev_client.load_config(vault), 'retrieval') == 'rerank'
    except (OSError, ValueError): rerank_mode = False
    with evaluation_context(vault):
        if rerank_mode:
            from client_transcripts import private
            if any(h.contains_secret(value) or private(value) for value in (query, previous_user or '')):
                rerank_mode = False
                private_fallback = True
            else:
                private_fallback = False
                projects, _ = select_projects(config(vault).get('projects', []), query, cwd)
                project = projects[0] if len(projects) == 1 else None
                project_context = (str(project.get('id', '')) + ': ' + str(project.get('summary', ''))) if project else ''
                if h.contains_secret(project_context) or private(project_context): project_context = ''
                rerank_state = dict(previous_user=(previous_user or '')[:800], project=project_context[:500])
                from jev_retrieval import rerank_gate
                explicit_recall = bool(re.search(r'\b(?:memory:|note:)|neye\s+karar\s+ver|ne\s+karar\s+vermiştik|hatırla|hatırlat', query, re.I))
                if explicit_recall:
                    needed, gate = True, dict(mode='rerank', requested_mode='rerank', effective_mode='rerank',
                                              degraded=False, diagnostics=['explicit_recall_bypass'], latency_ms=0)
                else:
                    with evaluation_context(vault):
                        needed, gate = rerank_gate(vault, query, rerank_state)
                    if not gate.get('degraded') and not needed:
                        skip_memory = True
                        if jev_client.load_config(vault)['rerank_gate_scope'] == 'all':
                            result = dict(text='', selected_ids=[], source_versions={}, assets=[], knowledge=None,
                                          omitted_reasons=[], project_id=None, jev={'gate': gate},
                                          history={'mode': history, 'included': False},
                                          procedure_reading={'paths': [], 'delivered': False},
                                          summary={'record_ids': [], 'task_ids': [], 'derived': True},
                                          usage={'context_chars': 0, 'budget_chars': budget, 'selected_count': 0})
                            result['package_id'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()[:24]
                            return result
        else:
            private_fallback = False
        # Readers are independent. Assembly stays ordered in the calling thread.
        with evaluation_context(vault), ThreadPoolExecutor(max_workers=3) as executor:
            def submit(function, *args, **kwargs):
                return executor.submit(copy_context().run, function, *args, **kwargs)
            if (gate and gate.get('degraded')) or private_fallback:
                with jev_client.disabled():
                    result = _build_task_package(vault, query, cwd, budget, history, view, submit, None)
                result.setdefault('jev', {})['rerank'] = dict(gate or {}, mode='rerank', degraded=True,
                    diagnostics=(gate or {}).get('diagnostics', []) + (['private_input'] if private_fallback else []))
            else:
                result = _build_task_package(vault, query, cwd, budget, history, view, submit, rerank_state, skip_memory)
                if gate: result.setdefault('jev', {})['gate'] = gate
    changed = before != revisions() or getattr(result.get('source_versions'), 'conflict', False)
    for name, version in result.get('source_versions', {}).items():
        try:
            if digest(vault/name) != version: changed = True
        except OSError: changed = True
    if changed:
        # Never relabel an old claim with a freshly computed source hash.
        text = 'Bağlam hazırlanırken kaynak değişti; güncel kaynağı yeniden doğrula.'
        result.update(text=text[:max(0,int(budget))], selected_ids=[], assets=[],
                      source_versions={}, knowledge=None, decision_history=None, reuse=None)
        result['omitted_reasons'].append('source_changed_during_package')
        result['summary'] = dict(record_ids=[],task_ids=[],derived=True)
        result['procedure_reading'].update(paths=[],delivered=False)
        result['history'].update(included=False,topic_covered=False)
        if 'capsule' in result:
            result['capsule'].update(tasks=[],facts=[],outputs=[],last_verified_output=None,
                                    suggested_next_step=None,selection_required=True)
        if result.get('jev'): result['jev']['knowledge_delivered']=False
        result['usage'].update(context_chars=len(result['text']),selected_count=0,
                               omitted_count=len(result['omitted_reasons']))
    result['package_id']=hashlib.sha256(json.dumps(
        {k:result.get(k) for k in ('text','source_versions','selected_ids','assets','project_id')},
        ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
    return result


def _build_task_package(vault, query, cwd, budget, history, view, submit, rerank_state=None, skip_memory=False):
    if history not in ("auto", "always", "never"): raise ValueError("invalid history mode")
    if view not in ("auto", "standard", "resume"): raise ValueError("invalid view")
    query = task_intent(query)
    resume = view == "resume" or (view == "auto" and continuation_request(query))
    resume_tasks = []; card_facts = []
    vault = Path(vault).resolve(); words = tokens(query)
    selected=[]; omitted=[]; lines=[]; used=0; assets=[]; source_versions=RevisionMap()
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
    def requested_phrase(phrase):
        parts=query_words(phrase); actual=query_words(query)
        return any(all(inflected(p,w) for p,w in zip(parts,actual[i:i+len(parts)]))
                   for i in range(len(actual)-len(parts)+1))
    wants_decisions=any(requested_phrase(p) for p in ('karar geçmişi','eski karar','önceki karar','neden seçtik','neden seçmiştik'))
    wants_reuse=any(requested_phrase(p) for p in ('yeniden kullan','yeniden kullanım','yeniden kullanabiliriz','yeniden kullanabilirim','başka nerede','hangi çıktıyı'))
    knowledge_data = None
    knowledge_future = None
    from jev_procedures import route as route_procedures
    procedure_future = submit(route_procedures, vault, query, budget=min(1000,budget))
    if rerank_state is None and (vault / 'bilgi').is_dir() and len(projects)<=1:
        from konu_sentezi import retrieve as read_knowledge
        knowledge_future=submit(read_knowledge,vault,query,project_id=project['id'] if project else None,budget=min(1800,budget))
    decision_data = None; reuse_data = None; output_data = {'outputs':[], 'diagnostics':[]}
    if wants_decisions and len(projects)<=1:
        from karar_gecmisi import history as read_decisions
        decision_query=' '.join(w for w in query_words(query) if not any(
            word_match(w,a) for alias in (project or {}).get('aliases',[]) for a in query_words(alias)))
        decision_data=read_decisions(vault,decision_query,scope,budget=min(1800,budget))
    if project and resume:
        from cikti_kayit import verified_outputs
        output_data=verified_outputs(vault,project['id'])
    if project and wants_reuse:
        from yeniden_kullanim import propose
        reuse_data=propose(vault,project['id'],query,max_chars=min(1800,budget))
    def add(ident, text):
        priority = {'unresolved_reference':0, 'ambiguous_project':0, 'project':1,
                    'unresolved':2, 'methods':3, 'input-check':3, 'workflow':4,
                    'working-source':8, 'working-root':8, 'summary-policy':6, 'capsule-status':6, 'decision-history':4, 'knowledge':2, 'reuse':5, 'procedure-reading':5}.get(ident, 10)
        if any(ident == asset.get('id') for asset in (project or {}).get('assets', [])): priority=2
        if ident in task_ids: priority=4
        if ident.startswith('output:'): priority=5
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
    eligible_versions={}
    for row in h.load_catalog(vault):
        if decision_data and row.get('memory_id') in decision_data['considered_ids']: continue
        if not any(h.retrievable(row,context_scope) for context_scope in [scope]+['project:'+w['id'] for w in workflows]): continue
        if row.get('memory_id') in overrides:
            if rank_records([row], query): omitted.append(row['memory_id']+':'+overrides[row['memory_id']])
            continue
        if h.context_record_errors(vault,row):
            if rank_records([row], query): omitted.append(row.get('memory_id','unknown')+':invalid')
            continue
        eligible.append(row)
        eligible_versions[row['source_path']]=digest(h.source_file(vault,row['source_path']))
    # Out-of-scope, stale and replaced rows must not influence corpus rarity.
    if skip_memory:
        ranked_catalog, knowledge_data, catalog_evaluation = [], None, None
    elif rerank_state is None:
        from jev_retrieval import catalog as semantic_catalog
        catalog_future = submit(semantic_catalog, vault, query, eligible, rank_records, scope)
        ranked_catalog, catalog_evaluation = catalog_future.result()
    else:
        from jev_retrieval import rerank
        ranked_catalog, knowledge_data, catalog_evaluation = rerank(
            vault, query, eligible, project['id'] if project else None, rerank_state, budget)
        if catalog_evaluation.get('degraded'):
            from konu_sentezi import _retrieve_local
            ranked_catalog = rank_records(eligible, query)
            knowledge_data = _retrieve_local(vault, query, project_id=project['id'] if project else None,
                                             budget=min(1800, budget)) if (vault / 'bilgi').is_dir() else None
    procedure_data = procedure_future.result()
    if knowledge_future: knowledge_data = knowledge_future.result()
    if procedure_data['text']: add('procedure-reading', procedure_data['text'])
    def still_current(row):
        try:
            return (not h.context_record_errors(vault,row) and
                    digest(h.source_file(vault,row['source_path'])) == eligible_versions[row['source_path']])
        except (OSError,ValueError): return False
    ranked_catalog=[row for row in ranked_catalog if still_current(row)]
    if catalog_evaluation and catalog_evaluation.get('suggested_ids'):
        suggested=set(catalog_evaluation['suggested_ids'])
        for row in eligible:
            if row['memory_id'] not in suggested or not still_current(row):continue
            add('jev-reading:'+row['memory_id'], 'Jev kaynak adayı (okumadan tercih/onay sayma): '+row['subject_key']+' — '+str(vault/row['source_path']))
            source_versions[row['source_path']]=eligible_versions[row['source_path']]

    for row in ranked_catalog:
        # A source-derived card requires a reviewed source revision, not a new
        # hash computed from an unreviewed legacy statement's current file.
        content = h.source_file(vault, row['source_path']).read_text()
        pinned = (row.get('source_content_hash') == h.statement_hash(content)
                  or h.current_source_binding(vault, row, content))
        if resume and pinned and len(card_facts) >= 5:
            omitted.append(row['memory_id']+':card_limit'); continue
        if pinned: card_facts.append(row)
        prefix = 'Bilgi kartı: ' if resume and pinned else 'Güncel kayıt: '
        details = ''.join(' '+label+': '+row[key] for key,label in (('rationale','Gerekçe'),('conditions','Geçerlilik koşulu')) if isinstance(row.get(key),str) and row[key] in content and not h.contains_secret(row[key]))
        if add(row['memory_id'],prefix+row['statement']+details+' (kaynak: '+row['source_path']+')'):
            current_facts.append(row)
            priority,sequence,ident,text=candidates[-1]
            candidates[-1]=(4,sequence,ident,text)
            source_versions[row['source_path']]=eligible_versions[row['source_path']]
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
                if pinned:
                    resume_tasks.append(task)
                    if resume and len(resume_tasks) > 3:
                        omitted.append(task['id']+':card_limit'); continue
                    current_tasks.append(task)
                source_versions[task['source_path']]=digest(source)
                if resume and pinned:
                    state_label = 'engelli' if task['status'] == 'blocked' else 'devam edilebilir'
                    add(task['id'], 'Devam kartı ['+state_label+']: '+task['title']+': '+task['next_step']+' (kaynak: '+task['source_path']+')')
                    continue
                add(task['id'],('Güncel sonraki adım: ' if pinned else 'Kaynağı yeniden doğrulanacak iş: ')+task['title']+': '+task['next_step']+' (kaynak: '+task['source_path']+')')
        for asset in project.get('assets',[]):
            try: path=validate_asset(asset)
            except (ValueError,OSError,KeyError) as e: omitted.append(asset.get('id','asset')+':'+str(e)); continue
            if add(asset['id'], 'Onaylı '+asset['role']+': '+str(path)+'; hash: '+asset['sha256']+'. Gerçek araç girdisini validate_inputs ile doğrula; dosyanın bulunması kullanıldığını kanıtlamaz.'): assets.append(asset)
    if decision_data and decision_data['text']:
        add('decision-history',decision_data['text'])
        source_versions.update(decision_data['source_versions'])
    if knowledge_data and knowledge_data['text']:
        add('knowledge',knowledge_data['text'])
    if reuse_data and reuse_data['text']:
        add('reuse',reuse_data['text'])
    for output in output_data['outputs'][:3]:
        ident='output:'+output['task_id']+':'+output['id']
        add(ident,'Doğrulanmış çıktı: '+output['label']+' — '+output['path']+
            ' (kontrol: '+output['verified_at']+'; kanıt: '+output['verification_path']+'). Dosya sürümü ve kayıtlı kontrol; insan kabulü değildir.')
        source_versions[output['path']]=output['sha256']
        source_versions[output['verification_path']]=output['verification_sha256']
    if output_data['diagnostics']:
        add('output-status','Çıktı bağlantısı: dosya veya kontrol kaynağı değişmiş/eksik; önceki çıktıyı doğrulanmış sayma.')
    if resume and project:
        status = ('birden fazla güncel iş var; hedef işi varsayma' if len(resume_tasks)>1 else
                  'güncel iş engelli; otomatik adım yok' if resume_tasks and resume_tasks[0]['status']=='blocked' else
                  'güncel iş kaydı yok; sonraki adımı uydurma' if not resume_tasks else
                  'kaynaklı iş kartı aşağıda; yeni istek öncelikli')
        add('capsule-status', 'Devam kapsülü: '+status+'.')
    from ders_baglam import context
    methods=context(vault,query,budget=min(2600, budget), project_id=project['id'] if project else None, workflow_ids=[w['id'] for w in workflows])
    if methods: add('methods',methods)
    # Current records are a derived view, never a new canonical statement.
    # Project names and continuation words alone do not prove topic coverage.
    continuation=resume or continuation_request(query)
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
    errors=[reason for reason in omitted if not reason.endswith((':budget', ':card_limit'))]
    if errors:
        detail='Bağlam kontrolü: '+ '; '.join(errors)+'. Eksik veya değişmiş kaynağı onaylı sayma.'
        if len(detail)>min(600,budget): detail='Bağlam kontrolü: Geçersiz veya değişmiş kaynaklar dışlandı; omitted_reasons alanını incele.'
        candidates.append((0,-1,'context-check',detail))
    delivered_segments={}
    for _, _, ident, text in sorted(candidates):
        cost=len(text)+(1 if lines else 0)
        if used+cost>budget:
            omitted.append(ident+':budget'); continue
        lines.append(text);selected.append(ident);delivered_segments[ident]=text;used+=cost
    assets=[asset for asset in assets if asset['id'] in selected]
    result={'workflow_ids':[w['id'] for w in workflows],'match_reason':match_reason,'project_id':project['id'] if project else None,'assets':assets,'source_versions':source_versions,'selected_ids':selected,'omitted_reasons':omitted,'text':'\n'.join(lines),'delivered_segments':delivered_segments}
    if knowledge_data and 'knowledge' in selected:
        source_versions.update(knowledge_data.get('source_versions',{}))
    if 'procedure-reading' in selected:
        source_versions.update(procedure_data['source_versions'])
    result['procedure_reading'] = dict(paths=procedure_data['paths'] if 'procedure-reading' in selected else [], delivered='procedure-reading' in selected, advisory=True, diagnostics=procedure_data.get('diagnostics',[]))
    result['knowledge']=knowledge_data if 'knowledge' in selected else None
    if catalog_evaluation is not None or (knowledge_data and knowledge_data.get('jev')) or procedure_data.get('jev'):
        result['jev'] = {'catalog':catalog_evaluation,
                         'knowledge':knowledge_data.get('jev') if knowledge_data else None,
                         'knowledge_delivered':'knowledge' in selected,
                         'procedures':procedure_data.get('jev')}
    result['history']={'mode':history,'included':any(p in selected for p in (project or {}).get('episode_sources',[])), 'requested':use_history,'reason':history_reason,'topic_covered':covered}
    result['summary']={'record_ids':[r['memory_id'] for r in current_facts if r['memory_id'] in selected], 'task_ids':[t['id'] for t in current_tasks if t['id'] in selected], 'derived':True}
    visible_tasks = [t for t in current_tasks if t['id'] in selected][:3]
    visible_facts = [f for f in card_facts if f['memory_id'] in selected][:5]
    task_cards = [dict(id=t['id'], title=t['title'], status=t['status'],
                       next_step=t['next_step'], source_path=t['source_path'],
                       source_sha256=source_versions[t['source_path']],
                       verified_at=t.get('last_verified')) for t in visible_tasks]
    fact_cards = [dict(id=f['memory_id'], statement=f['statement'], kind=f['kind'],
                       source_path=f['source_path'], source_sha256=source_versions[f['source_path']],
                       observed_at=f.get('observed_at')) for f in visible_facts]
    # A relevant fact must not make an unrelated task look like the next action.
    task_words = content_words(' '.join(t['title']+' '+t['next_step'] for t in visible_tasks))
    task_covers_topic = all(any(word_match(t,w) for w in task_words) for t in topic)
    # Only a single current active project task can be suggested, never executed.
    single = (task_cards[0] if len(resume_tasks) == 1 and len(task_cards) == 1
              and task_cards[0]['status'] == 'active' and task_covers_topic and not explicit_history else None)
    delivered_outputs=[o for o in output_data['outputs'][:3]
                       if 'output:'+o['task_id']+':'+o['id'] in selected]
    latest_output=(delivered_outputs[0] if delivered_outputs and
                   delivered_outputs[0]==output_data['outputs'][0] and
                   sum(o['verified_at']==delivered_outputs[0]['verified_at'] for o in output_data['outputs'])==1 else None)
    result['answer_verification'] = {'command':'python3 araclar/hafiza_dongusu.py --vault <vault> verify-answer --input-json <claims.json>', 'citation_fields':['card_id or memory_id','path','sha256','quote'], 'requires_current_reviewed_card':True, 'on_failure':'Qualify or omit unsupported memory attribution; never invent a citation.'}
    result['decision_history']=(decision_data if 'decision-history' in selected else None)
    result['reuse']=(reuse_data if 'reuse' in selected else None)
    result['capsule'] = dict(enabled=resume, derived=True, project_id=result['project_id'],
        tasks=task_cards if resume else [], facts=fact_cards if resume else [],
        available_task_count=len(resume_tasks) if resume else 0,
        omitted_task_count=max(0,len(resume_tasks)-len(task_cards)) if resume else 0,
        suggested_next_step=single['next_step'] if resume and single else None,
        selection_required=resume and len(resume_tasks)>1,
        outputs=delivered_outputs, last_verified_output=latest_output,
        limits='Kaynaklı türetilmiş görünüm; izin veya otomatik yürütme değildir. Çıktı varsa dosya ve kayıtlı kontrol sürümüne bağlıdır; kalite veya insan kabulü çıkarılamaz.')
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
    p=sub.add_parser('resume');p.add_argument('query');p.add_argument('--cwd');p.add_argument('--budget',type=int,default=1800)
    p=sub.add_parser('validate-inputs');p.add_argument('--package',type=Path,required=True);p.add_argument('--actual-inputs',type=Path,required=True);p.add_argument('--role',default='identity')
    args=parser.parse_args()
    if args.command=='package': result=build_task_package(args.vault,args.query,args.cwd,history=args.history)
    elif args.command=='resume': result=build_task_package(args.vault,args.query,args.cwd,budget=args.budget,view='resume')
    else: result={'validated':validate_inputs(json.loads(args.package.read_text())['assets'],json.loads(args.actual_inputs.read_text()),args.role)}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
