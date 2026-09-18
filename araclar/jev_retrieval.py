"""Optional semantic selection after local eligibility gates; never a memory writer."""
from pathlib import Path
import jev_client

DOMAINS = {'sunum': ('sunum', 'slayt', 'anlatım', 'konuşma'),
           'thumbnail': ('thumbnail', 'kapak'), 'site': ('site', 'web', 'website')}

def requested_domains(query):
    from gorev_baglam import content_words, word_match
    words = content_words(query)
    return [d for d, aliases in DOMAINS.items()
            if any(word_match(a, w) for a in aliases for w in words)]

def facets(query):
    domains = requested_domains(query)
    # Preserve the original question. These are bounded domain lenses, not a
    # claim that arbitrary natural-language conjunctions were fully parsed.
    return ([f'{query}\nYalnız {d} alanına ait istenen kanıtı değerlendir.' for d in domains]
            if len(domains) > 1 else [query])

def mode(vault):
    try: return jev_client.load_config(vault).get('mode', 'off')
    except (ValueError, OSError): return 'invalid'

def versions(vault, rows):
    import bilgi_agi as b
    result = {}
    for row in rows:
        name = f"bilgi/{row['id']}.md"
        result[name] = b.digest(Path(vault) / name)
        for s in row['sources']: result[s['path']] = s['sha256']
        for e in row.get('examples', []): result[e['path']] = e['sha256']
    return result

def knowledge(vault, query, project_id, budget, local):
    """Same hook for direct knowledge and synthesis; local is a zero-arg fallback."""
    import bilgi_agi as b
    active = mode(vault)
    if active == 'off': return local()
    vault = Path(vault)
    rows, diagnostics = b._rows(vault)
    requested = set(requested_domains(query))
    rows = [r for r in rows if r['scope'] in ('user', f'project:{project_id}')
            and (not requested or 'all' in r['domains'] or requested.intersection(r['domains']))]
    try: before = versions(vault, rows)
    except OSError:
        out = local(); out['jev'] = dict(mode=active, degraded=True, diagnostics=['source_changed_before_evaluation']); return out
    candidates = [{k: r[k] for k in ('id', 'title', 'statement', 'scope', 'domains')} for r in rows]
    result = jev_client.evaluate(vault, query, candidates, source_versions=before,
                                 scope=f'project:{project_id}' if project_id else 'user', facets=facets(query))
    # Reject a response if source revisions changed during the network call.
    fresh, _ = b._rows(vault)
    fresh = [r for r in fresh if r['id'] in {d['id'] for d in rows}]
    try: after = versions(vault, fresh)
    except OSError: after = None
    if after != before:
        result = dict(result, degraded=True, diagnostics=result.get('diagnostics', []) + ['source_changed_during_evaluation'])
    if result.get('degraded') or not rows or active == 'invalid':
        out = local(); out['jev'] = result; return out
    scores = result.get('scores', {})
    by_id = {r['id']: r for r in rows}
    per_facet = result.get('facet_scores') or {'0': scores}
    domains = requested_domains(query)
    if len(domains) > 1:
        per_facet = {f: {i: score if 'all' in by_id[i]['domains'] or domains[int(f)] in by_id[i]['domains'] else 0
                         for i, score in values.items() if i in by_id}
                     for f, values in per_facet.items()}
        scores = {i: max(v.get(i, 0) for v in per_facet.values()) for i in by_id}
        result['facet_scores'] = per_facet; result['scores'] = scores
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
    if active == 'shadow':
        out = local(); out['jev'] = result; return out
    # On mode delivers direct evidence only when candidates exist. Shadow/off
    # preserve the existing proposed domain-transfer behavior through local().
    out = dict(text='\n\n'.join(cards), records=selected, transfers=[],
               source_versions={k: v for k, v in before.items() if any(k == f"bilgi/{r['id']}.md" or k in [s['path'] for s in r['sources']] + [e['path'] for e in r.get('examples', [])] for r in selected)}, diagnostics=diagnostics,
               omitted_record_ids=omitted, jev=result)
    if 'unresolved' in result['coverage'].values():
        warning = 'İstenen bilginin bir bölümü için yeterli kaynak bulunamadı; eksikliği varsayımla doldurma.'
        if len(out['text']) + len(warning) + 1 <= max(0, budget):
            out['text'] = (out['text'] + '\n' + warning).strip()
    return out

def catalog(vault, query, eligible, local_rank, scope):
    """Canonical rows have already passed retrievable/source/override checks."""
    import hafiza as h
    active = mode(vault)
    if active == 'off' or not eligible: return local_rank(eligible, query), None
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
        except OSError: pass
    if len(still_valid) != len(eligible):
        result = dict(result, degraded=True, diagnostics=result.get('diagnostics', []) + ['source_changed_during_evaluation'])
    if active != 'on' or result.get('degraded'): return local_rank(still_valid, query), result
    scores = result.get('scores', {})
    selected = sorted([r for r in still_valid if scores.get(r['memory_id'], 0) >= 1.5],
                      key=lambda r: (-scores[r['memory_id']], r['memory_id']))
    result['proposed_ids'] = [r['memory_id'] for r in selected]
    return selected, result
