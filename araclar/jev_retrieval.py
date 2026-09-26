"""Optional semantic selection after local eligibility gates; never a memory writer."""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
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

def facet_first_order(per_facet, ids, threshold):
    """Cover each supported facet first, then fill by maximum score and ID."""
    ids = list(ids)
    order = []
    for values in per_facet.values():
        hits = sorted((i for i in ids if values.get(i, 0) >= threshold),
                      key=lambda i: (-values.get(i, 0), i))
        if hits and hits[0] not in order: order.append(hits[0])
    scores = {i: max((values.get(i, 0) for values in per_facet.values()), default=0) for i in ids}
    order += [i for i in sorted(ids, key=lambda i: (-scores[i], i))
              if scores[i] >= threshold and i not in order]
    return order


def mode(vault):
    try: return jev_client.purpose_mode(jev_client.load_config(vault), 'retrieval')
    except (ValueError, OSError): return 'invalid'


def recall_settings(cfg):
    """Missing settings use defaults; malformed settings disable their feature."""
    safe = dict(static_preferences='off', static_preferences_chars=0, gate_override_min_terms=0)
    if not isinstance(cfg, dict): return safe
    values = cfg.get('erisim', {})
    if not isinstance(values, dict): return safe
    settings = dict(static_preferences='rerank', static_preferences_chars=600, gate_override_min_terms=2)
    for key, default in settings.items():
        value = values.get(key, default)
        valid = (isinstance(value, str) and value in ('off', 'rerank', 'always') if key == 'static_preferences'
                 else type(value) is int and 0 <= value <= (2000 if key == 'static_preferences_chars' else 5))
        settings[key] = value if valid else safe[key]
    return settings


def static_preferences(eligible, already, settings, rerank_active):
    """Append bounded preferences from the caller's source-validated candidates."""
    mode = settings['static_preferences']
    if mode == 'off' or (mode == 'rerank' and not rerank_active): return []
    seen = {row['memory_id'] for row in already}
    selected = []; used = 0
    for row in sorted(eligible, key=lambda row: (row['scope'] != 'user', row['memory_id'])):
        if row.get('category') not in ('preference', 'profile') or row['memory_id'] in seen: continue
        cost = len(row['statement'])
        if used + cost > settings['static_preferences_chars']: continue
        selected.append(row)
        seen.add(row['memory_id'])
        used += cost
    return selected


def gate_rows(vault, project_id):
    """Reuse catalog and note eligibility before considering a lexical override."""
    import bilgi_agi as b
    import hafiza as h
    vault = Path(vault)
    scope = f'project:{project_id}' if project_id else 'user'
    try: catalog = h.load_catalog(vault)
    except (OSError, ValueError): catalog = []
    rows = []
    for row in catalog:
        try:
            if h.retrievable(row, scope) and not h.context_record_errors(vault, row): rows.append(row)
        except (OSError, ValueError): continue
    try: notes = b._rows(vault)[0] if (vault / 'bilgi').is_dir() else []
    except (OSError, ValueError): notes = []
    rows.extend(row for row in notes if row['scope'] in ('user', scope))
    return rows


def strong_lexical_matches(rows, query, min_terms):
    """Only rank_records hits with enough corpus-distinguishing query terms."""
    if min_terms <= 0: return []
    from gorev_baglam import content_words, rank_records, search_text, word_match
    terms = content_words(query)
    documents = [(row, content_words(search_text(row))) for row in rows]
    frequencies = {term: sum(any(word_match(term, word) for word in words)
                             for _, words in documents) for term in terms}
    # Keep the informative-term definition identical to rank_records.
    informative = {term for term in terms if 0 < frequencies[term] < max(2, len(rows)*0.5)}
    matches = []
    for row in rank_records(rows, query):
        words = content_words(search_text(row))
        if sum(any(word_match(term, word) for word in words) for term in informative) >= min_terms:
            matches.append('memory:' + row['memory_id'] if 'memory_id' in row else 'note:' + row['id'])
    return matches


def rerank_gate(vault, query, state):
    """One narrow judgment before any memory context is assembled."""
    candidate = dict(id='need', title='Stored context need', statement='Need for stored context',
                     scope='user', domains=[])
    result = jev_client.evaluate(vault, query, [candidate], purpose='retrieval_gate', state=state, timeout=1.0)
    result['requested_mode'] = 'rerank'
    result['effective_mode'] = 'local' if result.get('degraded') else 'rerank'
    result['needed'] = False
    if result.get('degraded'): return False, result
    probabilities = result.get('distributions', {}).get('need', {})
    config = jev_client.load_config(vault)
    if result.get('choices', {}).get('need') == 'insufficient_context':
        result['diagnostics'].append('abstain')
        return False, result
    result['needed'] = (result.get('choices', {}).get('need') == 'search_memory' and
                        probabilities.get('search_memory', 0) >= config['rerank_gate_threshold'])
    return result['needed'], result


def deterministic_expansion(query: str) -> list[str]:
    """Bounded local suffix/synonym hints using the existing inflection contract."""
    from gorev_baglam import _SUFFIXES, _SYNONYMS, content_words, inflected
    words = content_words(query)
    roots = set()
    hardened = {'ğ': 'k', 'b': 'p', 'd': 't', 'c': 'ç'}
    for word in sorted(words):
        if not word.isalpha(): continue
        frontier = {word}
        seen = {word}
        for _ in range(4):
            stems = {stem[:-len(suffix)] for stem in frontier for suffix in _SUFFIXES
                     if stem.endswith(suffix) and len(stem) - len(suffix) >= 4} - seen
            for stem in stems:
                variants = {stem}
                if stem[-1] in hardened:
                    variants.add(stem[:-1] + hardened[stem[-1]])
                roots.update(base for base in variants if inflected(base, word))
            seen.update(stems)
            frontier = stems
            if not frontier: break
    expanded = set(roots)
    for group in _SYNONYMS:
        if any(inflected(member, word) for member in group for word in words | roots):
            expanded.update(group)
    return sorted(expanded - words)[:24]


QUERY_EXPANDERS = [deterministic_expansion]


def expand_query(query: str) -> list[str]:
    """Call QUERY_EXPANDERS entries with signature fn(query) -> Iterable[str].

    Expanders only produce candidates, never authorize delivery; rerank retains
    that decision. A future LLM expander must not send secret/private prompts.
    Only local deterministic expansion is installed by default. A failing
    expander (including during iteration) is skipped in full, without affecting
    the others. Terms are normalized, deduplicated and sorted before the cap.
    """
    from gorev_baglam import content_words
    from hafiza import contains_secret
    original = content_words(query)
    expanded = set()
    for expander in QUERY_EXPANDERS:
        try:
            terms = set()
            for value in expander(query):
                if not isinstance(value, str): continue
                term = value.strip().casefold().replace('i\u0307', 'i')
                if term and len(term) <= 40 and term not in original and not contains_secret(term):
                    terms.add(term)
        except Exception:
            continue
        expanded.update(terms)
    return sorted(expanded)[:24]


def loose_candidates(query, catalog, notes, limit=8):
    """Shared lexical preselection without rank_records' delivery thresholds."""
    from gorev_baglam import content_words, word_match
    terms = content_words(query)
    expanded = expand_query(query)
    pool = []
    for kind, rows in (('memory', catalog), ('note', notes)):
        for row in rows:
            ident = row['memory_id'] if kind == 'memory' else row['id']
            fields = ' '.join(str(row.get(k, '')) for k in
                              ('statement', 'subject_key', 'title', 'rationale', 'conditions', 'exceptions'))
            if isinstance(row.get('arama_anahtarlari'), list):
                fields += ' ' + ' '.join(k for k in row['arama_anahtarlari'] if isinstance(k, str))
            words = content_words(fields)
            overlap = sum(any(word_match(term, word) for word in words) for term in terms)
            expanded_overlap = sum(any(word_match(term, word) for word in words) for term in expanded)
            pool.append((-overlap, -expanded_overlap, kind, ident, row))
    return [(kind, row) for _, _, kind, _, row in sorted(pool)[:limit]]


def _rerank_body(config, query, facets, cards, state, purpose='retrieval_rerank'):
    """Mirror evaluate's rerank payload for exact character budgeting."""
    return dict(model=config['model'], state=dict(query=query, facets=facets,
                candidates=cards, **state), questions={
                f'f{j}_c{i}': jev_client._question(purpose, i, j)
                for j in range(len(facets)) for i in range(len(cards))})


def _rerank_packages(config, query, facets, cards, state, purpose='retrieval_rerank'):
    """Greedy, ordered packages plus IDs that cannot fit even on their own."""
    def fits(batch):
        return (len(batch) <= config['max_candidates'] and
                len(batch) * len(facets) <= config['max_questions'] and
                len(json.dumps(_rerank_body(config, query, facets, batch, state, purpose),
                               ensure_ascii=False)) <= config['max_input_chars'])

    packages = []; pending = []; oversized_ids = []
    for card in cards:
        if fits(pending + [card]):
            pending.append(card)
            continue
        if pending:
            packages.append(pending)
            pending = []
        if fits([card]): pending.append(card)
        else: oversized_ids.append(card['id'])
    if pending: packages.append(pending)
    return packages, oversized_ids


def rerank(vault, query, catalog, project_id, state, budget):
    """Return one bounded mixed ranking; caller handles local fallback on degradation."""
    import bilgi_agi as b
    import hafiza as h
    vault = Path(vault)
    config = jev_client.load_config(vault)
    notes, diagnostics = b._rows(vault) if (vault / 'bilgi').is_dir() else ([], [])
    notes = [row for row in notes if row['scope'] in ('user', f'project:{project_id}')]
    chosen = loose_candidates(query + ' ' + state.get('previous_user', ''), catalog, notes,
                              config['rerank_candidates'])
    plan = facet_plan(query)
    multi_facet = config['rerank_facets'] and len(plan) > 1
    facets = [p['text'] for p in plan][:3] if multi_facet else [query]
    purpose = 'retrieval_rerank_facets' if multi_facet else 'retrieval_rerank'
    rerank_info = dict(facet_count=len(facets), rerank_purpose=purpose)
    if multi_facet: rerank_info['coverage'] = {str(j): 'unresolved' for j in range(len(facets))}
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
    pool_ids = [card['id'] for card in cards]
    versions = {}
    try:
        for kind, row in chosen:
            if kind == 'memory': versions['memory:' + row['memory_id']] = h.statement_hash(str(row))
            else: versions['note:' + row['id']] = b.note_version(vault, row)
    except (OSError, ValueError):
        return None, None, dict(mode='rerank', degraded=True, diagnostics=['source_changed_before_evaluation'],
                                pool_ids=pool_ids, **rerank_info)
    if not cards:
        result = dict(mode='rerank', scores={}, degraded=False, diagnostics=[], proposed_ids=[],
                      pool_ids=[], packages=[], fallback_ids=[], **rerank_info)
        return [], dict(text='', records=[], transfers=[], source_versions={}, diagnostics=diagnostics,
                        omitted_record_ids=[], jev=result), result
    packages, oversized_ids = _rerank_packages(config, query, facets, cards, state, purpose)
    if not packages:
        return None, None, dict(mode='rerank', degraded=True, diagnostics=['budget_exceeded'],
                                pool_ids=pool_ids, packages=[], fallback_ids=pool_ids, **rerank_info)
    with ThreadPoolExecutor(max_workers=min(3, len(packages))) as executor:
        futures = [executor.submit(copy_context().run, jev_client.evaluate, vault, query, package,
                                   purpose=purpose, facets=facets, state=state,
                                   source_versions={card['id']: versions[card['id']] for card in package})
                   for package in packages]
        evaluations = [future.result() for future in futures]
    successful = [evaluation for evaluation in evaluations if not evaluation.get('degraded')]
    fallback_ids = set(oversized_ids)
    for package, evaluation in zip(packages, evaluations):
        if evaluation.get('degraded'):
            fallback_ids.update(card['id'] for card in package)
    result = dict(successful[0] if successful else evaluations[0])
    result.update(scores={}, distributions={}, facet_distributions={}, diagnostics=[], usage={},
                  degraded=not successful, pool_ids=pool_ids,
                  fallback_ids=[ident for ident in pool_ids if ident in fallback_ids],
                  packages=[dict(size=len(package), degraded=bool(evaluation.get('degraded')),
                                 diagnostics=list(evaluation.get('diagnostics', [])))
                            for package, evaluation in zip(packages, evaluations)],
                  latency_ms=max(evaluation.get('latency_ms', 0) for evaluation in evaluations),
                  cache_hit=all(evaluation.get('cache_hit', False) for evaluation in evaluations), **rerank_info)
    if any('facet_scores' in evaluation for evaluation in evaluations): result['facet_scores'] = {}
    for evaluation in evaluations:
        result['diagnostics'].extend(d for d in evaluation.get('diagnostics', []) if d not in result['diagnostics'])
        for key in ('input_tokens', 'output_tokens'):
            if key in evaluation.get('usage', {}):
                result['usage'][key] = result['usage'].get(key, 0) + evaluation['usage'][key]
        if evaluation.get('degraded'): continue
        for key in ('scores', 'distributions'): result[key].update(evaluation.get(key, {}))
        for key in ('facet_scores', 'facet_distributions'):
            for facet, values in evaluation.get(key, {}).items():
                result[key].setdefault(facet, {}).update(values)
    if oversized_ids and 'budget_exceeded' not in result['diagnostics']:
        result['diagnostics'].append('budget_exceeded')
    if result.get('degraded'):
        return None, None, result
    if fallback_ids and 'package_fallback' not in result['diagnostics']:
        result['diagnostics'].append('package_fallback')
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
    if multi_facet:
        by_id = {card['id']: (kind, row) for card, (kind, row) in zip(cards, chosen)
                 if card['id'] not in fallback_ids}
        per_facet = {j: {ident: result['facet_distributions'].get(j, {}).get(ident, {}).get('2', 0)
                         for ident in by_id} for j in range(len(facets))}
        scores = {ident: max(values[ident] for values in per_facet.values()) for ident in by_id}
        ordered = [(scores[ident], *by_id[ident])
                   for ident in facet_first_order(per_facet, by_id, threshold)]
    else:
        ordered = sorted(((probabilities.get(card['id'], {}).get('2', 0), kind, row) for card, (kind, row) in zip(cards, chosen)
                          if card['id'] not in fallback_ids and probabilities.get(card['id'], {}).get('2', 0) >= threshold),
                         key=lambda item: (-item[0], item[1], item[2].get('memory_id', item[2].get('id', ''))))
    if fallback_ids:
        from gorev_baglam import rank_records
        fallback_rows = {id(row): (kind, row) for card, (kind, row) in zip(cards, chosen)
                         if card['id'] in fallback_ids}
        ordered.extend((0, *fallback_rows[id(row)]) for row in rank_records([row for _, row in chosen], query)
                       if id(row) in fallback_rows)
    ordered = ordered[:config['rerank_limit']]
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
    if multi_facet:
        delivered = {'memory:' + row['memory_id'] for row in selected_catalog}
        delivered.update('note:' + row['id'] for row in delivered_notes)
        result['coverage'] = {str(j): 'covered' if any(values[i] >= threshold for i in delivered if i in values)
                              else 'unresolved' for j, values in per_facet.items()}
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
    order = facet_first_order(per_facet, by_id, 1.5)
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
