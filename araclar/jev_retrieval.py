"""Optional semantic selection after local eligibility gates; never a memory writer."""
import json
import re
from pathlib import Path
import jev_client

from bilgi_agi import DOMAIN_ALIASES

DOMAINS = dict(DOMAIN_ALIASES, sunum=DOMAIN_ALIASES['sunum'] + ('anlatım', 'konuşma'))

def requested_domains(query):
    from gorev_baglam import content_words, word_match
    words = content_words(query)
    return [d for d, aliases in DOMAINS.items()
            if any(word_match(a, w) for a in aliases for w in words)]

def facet_plan(query):
    """Bounded evidence lenses, retaining the complete query as model state.

    Domain mentions are not an exhaustive list of requested evidence. Separate
    explicit evidence clauses can have an implicit domain. Ordinary task requests
    keep their explicit domain guard; this is not a general Turkish parser.
    """
    all_domains = requested_domains(query)
    if len(all_domains) > 3:
        return [dict(text=query, domains=all_domains)]
    evidence_request = bool(re.search(r'kaynak|notlar|ayrı\s+ayrı|geri\s+bildirim', query, re.I))
    clauses = [part.strip() for part in re.split(r'\s+(?:ve|ile)\s+|;', query, flags=re.I) if part.strip()]
    if evidence_request and 1 < len(clauses) <= 3:
        # An explicit leading task frame applies to coordinated objects too:
        # 'site için renk ve font kaynakları' does not open font to other domains.
        frame = re.match(r'^\s*(\w+)\s+için\b', query, re.I)
        inherited = requested_domains(frame.group(1)) if frame else []
        return [dict(text=clause, domains=requested_domains(clause) or inherited) for clause in clauses]
    domains = requested_domains(query)
    if len(domains) > 1:
        # More than three clauses cannot safely be truncated. Domain lenses keep
        # the whole query, including every remaining clause.
        return [dict(text=f'{query}\nYalnız {d} alanına ait istenen kanıtı değerlendir.', domains=[d])
                for d in domains]
    return [dict(text=query, domains=domains)]


def facets(query):
    return [item['text'] for item in facet_plan(query)]

def mode(vault):
    try: return jev_client.purpose_mode(jev_client.load_config(vault), 'retrieval')
    except (ValueError, OSError): return 'invalid'


def rerank_gate(vault, query, state):
    """One narrow judgment before any memory context is assembled."""
    candidate = dict(id='need', title='Stored context need', statement='Need for stored context',
                     scope='user', domains=[])
    result = jev_client.evaluate(vault, query, [candidate], purpose='retrieval_gate', state=state, timeout=1.0)
    result['requested_mode'] = 'rerank'
    result['effective_mode'] = 'local' if result.get('degraded') else 'rerank'
    if result.get('degraded'): return False, result
    probabilities = result.get('distributions', {}).get('need', {})
    config = jev_client.load_config(vault)
    if result.get('choices', {}).get('need') == 'insufficient_context':
        result['diagnostics'].append('abstain')
        return False, result
    return (result.get('choices', {}).get('need') == 'search_memory' and
            probabilities.get('search_memory', 0) >= config['rerank_gate_threshold']), result


def loose_candidates(query, catalog, notes, limit=8):
    """Shared lexical preselection without rank_records' delivery thresholds."""
    from gorev_baglam import content_words, word_match
    terms = content_words(query)
    pool = []
    for kind, rows in (('memory', catalog), ('note', notes)):
        for row in rows:
            ident = row['memory_id'] if kind == 'memory' else row['id']
            fields = ' '.join(str(row.get(k, '')) for k in
                              ('statement', 'subject_key', 'title', 'rationale', 'conditions', 'exceptions'))
            words = content_words(fields)
            overlap = sum(any(word_match(term, word) for word in words) for term in terms)
            pool.append((-overlap, kind, ident, row))
    return [(kind, row) for _, kind, _, row in sorted(pool)[:limit]]


def rerank(vault, query, catalog, project_id, state, budget):
    """Return one bounded mixed ranking; caller handles local fallback on degradation."""
    import bilgi_agi as b
    import hafiza as h
    vault = Path(vault)
    config = jev_client.load_config(vault)
    notes, diagnostics = b._rows(vault) if (vault / 'bilgi').is_dir() else ([], [])
    notes = [row for row in notes if row['scope'] in ('user', f'project:{project_id}')]
    chosen = loose_candidates(query + ' ' + state.get('previous_user', ''), catalog, notes,
                              min(config['rerank_candidates'], 8))
    cards = []
    for kind, row in chosen:
        ident = row['memory_id'] if kind == 'memory' else row['id']
        cards.append(dict(id=kind + ':' + ident,
                          title=row.get('subject_key', row.get('title', '')),
                          statement=row['statement'], scope=row['scope'],
                          domains=row.get('domains', []), kind=row.get('kind', kind),
                          subject_key=row.get('subject_key', ''),
                          valid_from=row.get('valid_from', ''), valid_to=row.get('valid_to', ''),
                          **{k: row[k] for k in ('rationale', 'conditions', 'exceptions')
                             if isinstance(row.get(k), str)}))
    versions = {}
    try:
        for kind, row in chosen:
            if kind == 'memory': versions['memory:' + row['memory_id']] = h.statement_hash(str(row))
            else: versions['note:' + row['id']] = b.note_version(vault, row)
    except (OSError, ValueError):
        return None, None, dict(mode='rerank', degraded=True, diagnostics=['source_changed_before_evaluation'])
    if not cards:
        result = dict(mode='rerank', scores={}, degraded=False, diagnostics=[], proposed_ids=[])
        return [], dict(text='', records=[], transfers=[], source_versions={}, diagnostics=diagnostics,
                        omitted_record_ids=[], jev=result), result
    # Shrink the candidate set before calling the provider. The full query and
    # the candidate evidence remain intact; no silent lexical fallback.
    while cards:
        body = dict(model=config['model'], state=dict(query=query, facets=[query],
                    candidates=cards, **state), questions={
                    'f0_c'+str(i): jev_client._question('retrieval_rerank', i, 0)
                    for i in range(len(cards))})
        if (len(json.dumps(body, ensure_ascii=False)) <= config['max_input_chars'] and
                len(cards) <= config['max_candidates'] and len(cards) <= config['max_questions']):
            break
        cards.pop(); chosen.pop()
    if not cards:
        return None, None, dict(mode='rerank', degraded=True, diagnostics=['budget_exceeded'])
    result = jev_client.evaluate(vault, query, cards, purpose='retrieval_rerank',
                                 source_versions=versions, state=state)
    if result.get('degraded'):
        return None, None, result
    # An in-flight source change invalidates the entire answer.
    try:
        for kind, row in chosen:
            current = (next((r for r in h.load_catalog(vault) if r['memory_id'] == row['memory_id']), None)
                       if kind == 'memory' else next((r for r in b._rows(vault)[0] if r['id'] == row['id']), None))
            if current != row or (kind == 'memory' and h.context_record_errors(vault, current)):
                raise ValueError('source_changed')
    except (OSError, ValueError):
        return None, None, dict(result, degraded=True, diagnostics=result.get('diagnostics', []) + ['source_changed_during_evaluation'])
    probabilities = result.get('distributions', {}); threshold = config['rerank_p2']
    ordered = sorted(((probabilities.get(card['id'], {}).get('2', 0), kind, row) for card, (kind, row) in zip(cards, chosen)
                      if probabilities.get(card['id'], {}).get('2', 0) >= threshold),
                     key=lambda item: (-item[0], item[1], item[2].get('memory_id', item[2].get('id', ''))))[:config['rerank_limit']]
    selected_catalog = [row for _, kind, row in ordered if kind == 'memory']
    selected_notes = [row for _, kind, row in ordered if kind == 'note']
    note_cards = []; note_versions = {}; delivered_notes = []
    for row in selected_notes:
        card = f"Bilgi [{row['kind']}; {', '.join(row['domains'])}; {row['scope']}]: {row['statement']}\nKaynak: bilgi/{row['id']}.md"
        for key, label in (('rationale', 'Gerekçe'), ('conditions', 'Koşul'), ('exceptions', 'İstisna')):
            if row.get(key): card += '\n' + label + ': ' + row[key]
        if len('\n\n'.join(note_cards + [card])) > min(1800, budget): continue
        note_cards.append(card)
        delivered_notes.append(row)
        note_versions.update(versions_for_note(vault, row))
    result['proposed_ids'] = [kind + ':' + (row['memory_id'] if kind == 'memory' else row['id']) for _, kind, row in ordered]
    result['requested_mode'] = 'rerank'; result['effective_mode'] = 'rerank'
    knowledge = dict(text='\n\n'.join(note_cards), records=delivered_notes, transfers=[],
                     source_versions=note_versions, diagnostics=diagnostics, omitted_record_ids=[], jev=result)
    return selected_catalog, knowledge, result


def versions_for_note(vault, row):
    import bilgi_agi as b
    values = {f"bilgi/{row['id']}.md": b.note_version(vault, row)}
    for item in row['sources'] + row.get('examples', []):
        values[item['path']] = item['sha256']
    return values

def versions(vault, rows):
    import bilgi_agi as b
    result = {}
    for row in rows:
        name = f"bilgi/{row['id']}.md"
        result[name] = b.note_version(vault, row)
        for s in row['sources']: result[s['path']] = s['sha256']
        for e in row.get('examples', []): result[e['path']] = e['sha256']
    return result

def knowledge(vault, query, project_id, budget, local):
    with jev_client.evaluation_context(vault):
        return _knowledge(vault, query, project_id, budget, local)


def _knowledge(vault, query, project_id, budget, local):
    """Same hook for direct knowledge and synthesis; local is a zero-arg fallback."""
    import bilgi_agi as b
    active = mode(vault)
    if active in ('off', 'rerank'): return local()
    vault = Path(vault)
    rows, diagnostics = b._rows(vault)
    # Source/scope are hard eligibility gates. A lexical domain mention cannot
    # exclude a second, implicit subject before semantic assessment.
    rows = [r for r in rows if r['scope'] in ('user', f'project:{project_id}')]
    plan = facet_plan(query)
    try: before = versions(vault, rows)
    except (OSError, ValueError):
        out = local(); out['jev'] = dict(mode=active, degraded=True, diagnostics=['source_changed_before_evaluation']); return out
    candidates = [{k: r[k] for k in ('id', 'title', 'statement', 'scope', 'domains')} for r in rows]
    result = jev_client.evaluate(vault, query, candidates, source_versions=before,
                                 scope=f'project:{project_id}' if project_id else 'user', facets=[f['text'] for f in plan])
    # Reject a response if source revisions changed during the network call.
    fresh, _ = b._rows(vault)
    fresh = [r for r in fresh if r['id'] in {d['id'] for d in rows}]
    try: after = versions(vault, fresh)
    except (OSError, ValueError): after = None
    if after != before:
        result = dict(result, degraded=True, diagnostics=result.get('diagnostics', []) + ['source_changed_during_evaluation'])
    if result.get('degraded') or not rows or active == 'invalid':
        out = local(); out['jev'] = result; return out
    scores = result.get('scores', {})
    by_id = {r['id']: r for r in rows}
    per_facet = result.get('facet_scores') or {'0': scores}
    # Video is a workflow umbrella: narration and cover evidence remain in their
    # original domains. Project/source gates still run before the model.
    guarded_domains = [set(f['domains']) | ({'sunum', 'thumbnail'} if 'video' in f['domains'] else set())
                       | ({d for r in rows for d in r['domains']} if 'proje' in f['domains'] else set()) for f in plan]
    # Apply each explicit domain guard to its own clause. An implicit clause
    # remains open to semantic support, never to inferred cross-domain approval.
    per_facet = {f: {i: score if not plan[int(f)]['domains'] or 'all' in by_id[i]['domains']
                        or guarded_domains[int(f)].intersection(by_id[i]['domains']) else 0
                     for i, score in values.items() if i in by_id}
                 for f, values in per_facet.items()}
    scores = {i: max((v.get(i, 0) for v in per_facet.values()), default=0) for i in by_id}
    result['facet_scores'] = per_facet; result['scores'] = scores
    result['routing'] = 'scoped_candidates_clause_domain_guards_v3'
    result['facet_domains'] = [f['domains'] for f in plan]
    # Cover each supported facet first, then fill by score. No unqualified union.
    order = []
    for values in per_facet.values():
        hits = sorted((i for i in by_id if values.get(i, 0) >= 1.5), key=lambda i: (-values[i], i))
        if hits and hits[0] not in order: order.append(hits[0])
    order += [i for i in sorted(by_id, key=lambda i: (-scores.get(i, 0), i))
              if scores.get(i, 0) >= 1.5 and i not in order]
    cards = []; selected = []; omitted = []
    for ident in order:
        r = by_id[ident]
        card = f"Bilgi [{r['kind']}; {', '.join(r['domains'])}; {r['scope']}]: {r['statement']}\nKaynak: bilgi/{ident}.md"
        for key,label in (('rationale','Gerekçe'),('conditions','Koşul'),('exceptions','İstisna')):
            if r.get(key): card+='\n'+label+': '+r[key]
        for e in r.get('examples', []):
            card += f"\nÖrnek ({e['acceptance']}; {e['role']}): {e['path']}"
        if len('\n\n'.join(cards + [card])) > max(0, budget): omitted.append(ident); continue
        cards.append(card); selected.append(r)
    delivered = {r['id'] for r in selected}
    result['coverage'] = {str(f): ('covered' if any(v.get(i, 0) >= 1.5 for i in delivered)
                         else 'budget_exceeded' if any(v.get(i, 0) >= 1.5 for i in omitted)
                         else 'unresolved') for f, v in per_facet.items()}
    result['proposed_ids'] = sorted(delivered)
    result['facet_count'] = len(facets(query))
    if active == 'assist':
        # Extra reading candidates, never promoted to delivered user preferences.
        out=local(); existing={r['id'] for r in out.get('records',[])}
        suggestions=[]; added=[]
        for r in selected:
            if r['id'] in existing or len(suggestions)>=2: continue
            path=f"bilgi/{r['id']}.md"
            line=f"Jev kaynak adayı (okumadan tercih/onay sayma): {r['title']} — {path}"
            if len(out['text'])+sum(len(x)+1 for x in added)+len(line)+1>max(0,budget): continue
            added.append(line);suggestions.append(r['id'])
            out.setdefault('source_versions',{}).update({k:v for k,v in before.items() if k==path or k in [s['path'] for s in r['sources']] + [e['path'] for e in r.get('examples',[])]})
        if added: out['text']='\n'.join([out['text'],*added]).strip()
        result['suggested_ids']=suggestions;out['jev']=result
        out['suggested_ids']=suggestions
        return out
    if active == 'shadow':
        out = local(); out['jev'] = result; return out
    # On mode delivers direct evidence only when candidates exist. Shadow/off
    # preserve the existing proposed domain-transfer behavior through local().
    out = dict(text='\n\n'.join(cards), records=selected, transfers=[],
               source_versions={k: v for k, v in before.items() if any(k == f"bilgi/{r['id']}.md" or k in [s['path'] for s in r['sources']] + [e['path'] for e in r.get('examples', [])] for r in selected)}, diagnostics=diagnostics,
               omitted_record_ids=omitted, jev=result)
    if active == 'assist' and 'unresolved' in result['coverage'].values():
        warning = 'İstenen bilginin bir bölümü için yeterli kaynak bulunamadı; eksikliği varsayımla doldurma.'
        if len(out['text']) + len(warning) + 1 <= max(0, budget):
            out['text'] = (out['text'] + '\n' + warning).strip()
    return out

def catalog(vault, query, eligible, local_rank, scope):
    with jev_client.evaluation_context(vault):
        return _catalog(vault, query, eligible, local_rank, scope)


def _catalog(vault, query, eligible, local_rank, scope):
    """Canonical rows have already passed retrievable/source/override checks."""
    import hafiza as h
    active = mode(vault)
    if active in ('off', 'rerank') or not eligible: return local_rank(eligible, query), None
    mapped = [{ 'id':r['memory_id'], 'title':r['subject_key'], 'statement':r['statement'],
                'scope':r['scope'], 'domains':['all']} for r in eligible]
    source_versions = {r['memory_id']: h.statement_hash(str(r)) for r in eligible}
    result = jev_client.evaluate(vault, query, mapped, source_versions=source_versions, scope=scope, facets=facets(query))
    still_valid = []
    # Reload catalog metadata too: an in-flight result cannot revive a record
    # that was revoked or superseded while the advisor was working.
    try: current = {r['memory_id']: r for r in h.load_catalog(Path(vault))}
    except (OSError, ValueError): current = {}
    for r in eligible:
        try:
            if current.get(r['memory_id']) == r and not h.context_record_errors(Path(vault), r) and h.retrievable(r, r['scope']): still_valid.append(r)
        except (OSError, ValueError): pass
    if len(still_valid) != len(eligible):
        result = dict(result, degraded=True, diagnostics=result.get('diagnostics', []) + ['source_changed_during_evaluation'])
    if active == 'assist' and not result.get('degraded'):
        local=local_rank(still_valid,query); present={r['memory_id'] for r in local}
        result['suggested_ids']=[r['memory_id'] for r in sorted(still_valid,key=lambda r:-result.get('scores',{}).get(r['memory_id'],0))
            if r['memory_id'] not in present and result.get('scores',{}).get(r['memory_id'],0)>=1.5][:2]
        return local,result
    if active != 'on' or result.get('degraded'): return local_rank(still_valid, query), result
    scores = result.get('scores', {})
    selected = sorted([r for r in still_valid if scores.get(r['memory_id'], 0) >= 1.5],
                      key=lambda r: (-scores[r['memory_id']], r['memory_id']))
    result['proposed_ids'] = [r['memory_id'] for r in selected]
    return selected, result
