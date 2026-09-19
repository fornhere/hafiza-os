"""Source-bound advisory checks. Never registers, promotes or supersedes memories."""
import json
from pathlib import Path
import bilgi_agi as knowledge
import jev_client
from jev_retrieval import versions

SUPPORT = [
    'The quoted evidence directly supports the stored claim, including its scope, time and conditions; no broader preference is inferred.',
    'The quoted evidence directly contradicts the stored claim in the same scope, time and conditions.'
]
RELATIONS = [
    'The candidate and anchor express the same claim with the same scope, time and conditions, despite different wording.',
    'The candidate and anchor are incompatible in the same scope, time and conditions. Different contexts alone are not a contradiction.',
    'The candidate narrows the anchor: it adds a condition or exception to its broader claim. Direction is candidate toward anchor.'
]


def packet(row):
    """Only exact validated quotes; never surrounding source text or example files."""
    return dict(id=row['id'], title=row['title'], scope=row['scope'], domains=row['domains'],
                statement=json.dumps(dict(stored_claim=row['statement'], kind=row['kind'],
                    applicability={key:row[key] for key in ('rationale','conditions','exceptions') if key in row},
                    evidence=[dict(quote=s['evidence'], source_sha256=s['sha256'])
                              for s in row['sources']]), ensure_ascii=False))


def audit(vault, project_id=None, card_ids=None, anchor_id=None):
    vault = Path(vault)
    rows, diagnostics = knowledge._rows(vault)
    rows = [r for r in rows if r['scope'] in ('user', f'project:{project_id}')]
    lookup = {r['id']: r for r in rows}
    if card_ids is not None:
        if not isinstance(card_ids, list) or not card_ids or any(i not in lookup for i in card_ids):
            raise ValueError('card_not_eligible')
        rows = [lookup[i] for i in dict.fromkeys(card_ids)]
    if anchor_id is not None and anchor_id not in lookup:
        raise ValueError('anchor_not_eligible')
    anchor = lookup.get(anchor_id)
    # Explicit anchor can be outside the support-check subset, but never outside
    # the caller's eligible scope. Cross-project or cross-domain pairs are omitted.
    related = [r for r in rows if anchor and r['id'] != anchor_id and r['scope'] == anchor['scope']
               and ('all' in r['domains'] or 'all' in anchor['domains'] or set(r['domains']) & set(anchor['domains']))]
    watched = list({r['id']:r for r in rows + ([anchor] if anchor else [])}.values())
    result = dict(status='advisory', canonical_writes=False, requires_review=True,
                  support_checks=[], relation_candidates=[], source_versions={}, diagnostics=[],
                  evaluations={}, excluded_count=len(diagnostics))
    try:
        before = versions(vault, watched)
    except OSError:
        result.update(status='degraded', diagnostics=['source_changed_before_evaluation'])
        return result
    checks = jev_client.evaluate(vault, 'Assess each stored claim against only its attached exact evidence quotes.',
        [packet(r) for r in rows], source_versions=before, scope=f'project:{project_id}' if project_id else 'user',
        facets=SUPPORT, purpose='evidence_review')
    result['evaluations']['support'] = checks
    pairs = None
    def unchanged():
        fresh, _ = knowledge._rows(vault)
        fresh = [r for r in fresh if r['id'] in {r['id'] for r in watched}]
        try: return versions(vault, fresh) == before
        except OSError: return False
    if not unchanged():
        checks.update(scores={}, facet_scores={}, degraded=True)
        result.update(status='degraded', diagnostics=['source_changed_during_evaluation'])
        return result
    if related and checks.get('mode') != 'off' and not checks.get('degraded'):
        pairs = jev_client.evaluate(vault, json.dumps(dict(anchor=packet(anchor)), ensure_ascii=False),
            [packet(r) for r in related], source_versions=before, scope=anchor['scope'],
            facets=RELATIONS, purpose='memory_review')
        result['evaluations']['relations'] = pairs
    fresh, _ = knowledge._rows(vault)
    fresh = [r for r in fresh if r['id'] in {r['id'] for r in watched}]
    try: after = versions(vault, fresh)
    except OSError: after = None
    if after != before:
        result.update(status='degraded', diagnostics=['source_changed_during_evaluation'])
        # Retain diagnostic/usage metadata, never publish stale semantic scores.
        for evaluation in result['evaluations'].values():
            evaluation.update(scores={}, facet_scores={}, degraded=True)
        return result
    result['source_versions'] = before
    if checks.get('mode') == 'off' and not checks.get('degraded'):
        result['status'] = 'disabled'
        return result
    def score(evaluation, facet, ident):
        values = evaluation.get('facet_scores', {})
        return (values.get(facet) or values.get(str(facet)) or {}).get(ident, 0)
    if checks.get('degraded'):
        result['status'] = 'degraded'
        result['diagnostics'] += checks.get('diagnostics', [])
    else:
        for row in rows:
            yes, no = score(checks, 0, row['id']), score(checks, 1, row['id'])
            verdict = ('uncertain' if yes >= 1.5 and no >= 1.5 else
                       'supported' if yes >= 1.5 else 'contradicted' if no >= 1.5 else 'insufficient')
            result['support_checks'].append(dict(card_id=row['id'], verdict=verdict,
                support_score=yes, contradiction_score=no, status='advisory'))
    if pairs:
        if pairs.get('mode') == 'off' and not pairs.get('degraded'):
            result['status'] = 'degraded'
            result['diagnostics'].append('relations_disabled_during_evaluation')
            return result
        if pairs.get('degraded'):
            result['status'] = 'degraded'; result['diagnostics'] += pairs.get('diagnostics', [])
        else:
            for row in related:
                scores = {label:score(pairs, i, row['id']) for i,label in enumerate(('same_claim','incompatible','narrows'))}
                hits = [label for label,value in scores.items() if value >= 1.5]
                result['relation_candidates'].append(dict(source_id=row['id'], target_id=anchor_id,
                    relation=hits[0] if len(hits)==1 else 'uncertain', scores=scores,
                    status='proposed', reason='Model judgment requires source and contextual review.'))
    return result


def audit_proposed(vault, candidate, project_id=None, allow_registered=False):
    """Check an unregistered proposal; validated advisory output cannot promote it.

    Relations compare up to eight eligible same-scope/domain existing cards to
    the proposed anchor. Remaining cards are explicitly counted, never implied
    to have been checked. No candidate is registered, even temporarily.
    """
    import copy
    vault=Path(vault)
    if not isinstance(candidate,dict): raise ValueError('invalid_candidate')
    candidate=copy.deepcopy(candidate)
    try: encoded=json.dumps(candidate,ensure_ascii=False,allow_nan=False)
    except (TypeError,ValueError): raise ValueError('invalid_candidate') from None
    if len(encoded)>24000: raise ValueError('candidate_budget_exceeded')
    if candidate.get('status')!='proposed': raise ValueError('candidate_must_be_proposed')
    if candidate.get('scope') not in ('user',f'project:{project_id}' if project_id else 'user'):
        raise ValueError('candidate_scope_mismatch')
    if not isinstance(candidate.get('sources'),list) or not 1<=len(candidate['sources'])<=8:
        raise ValueError('candidate_sources_invalid')
    try: proposal=knowledge._validate(vault,candidate)
    except (ValueError,OSError,TypeError,KeyError): raise ValueError('candidate_source_or_fields_invalid') from None
    rows,diagnostics=knowledge._rows(vault)
    # A new proposal may not impersonate any existing card identity.
    registered=vault/'bilgi'/f"{proposal['id']}.md"
    if registered.exists() and (not allow_registered or knowledge._read(registered)!=proposal): raise ValueError('candidate_id_exists')
    eligible=[r for r in rows if r['scope']==proposal['scope'] and
              ('all' in r['domains'] or 'all' in proposal['domains'] or set(r['domains']) & set(proposal['domains']))]
    eligible.sort(key=lambda r:r['id'])
    related=eligible[:8]
    result=dict(status='advisory',candidate_id=proposal['id'],candidate_status='proposed',
        canonical_writes=False,requires_review=True,support_checks=[],relation_candidates=[],
        source_versions={},diagnostics=[],evaluations={},excluded_count=len(diagnostics),
        relation_limit=8,omitted_relation_count=max(0,len(eligible)-8))
    def snapshot():
        # Re-run exact evidence/hash/field gates after every network call.
        checked=knowledge._validate(vault,proposal)
        current,_=knowledge._rows(vault)
        lookup={r['id']:r for r in current}
        if any(lookup.get(r['id'])!=r for r in related): raise ValueError('source_changed')
        if registered.exists() and (not allow_registered or knowledge._read(registered)!=proposal): raise ValueError('candidate_registered_during_evaluation')
        if allow_registered and not registered.exists(): raise ValueError('candidate_disappeared')
        versions_now=versions(vault,related)
        for source in checked['sources']: versions_now[source['path']]=source['sha256']
        for example in checked.get('examples',[]): versions_now[example['path']]=example['sha256']
        return versions_now
    def discard():
        result.update(status='degraded',diagnostics=['source_changed_during_evaluation'],source_versions={},
                      support_checks=[],relation_candidates=[])
        for evaluation in result['evaluations'].values(): evaluation.update(scores={},facet_scores={},degraded=True)
        return result
    try: before=snapshot()
    except (OSError,ValueError,TypeError,KeyError):
        result.update(status='degraded',diagnostics=['source_changed_before_evaluation']);return result
    checks=jev_client.evaluate(vault,'Assess the proposed claim against only its attached exact evidence quotes.',
        [packet(proposal)],source_versions=before,scope=proposal['scope'],facets=SUPPORT,purpose='evidence_review')
    result['evaluations']['support']=checks
    try:
        if snapshot()!=before:return discard()
    except (OSError,ValueError,TypeError,KeyError):return discard()
    result['source_versions']=before
    if checks.get('degraded'):
        result.update(status='degraded',diagnostics=checks.get('diagnostics',[]));return result
    if checks.get('mode')=='off':result['status']='disabled';return result
    def score(evaluation,facet,ident):
        values=evaluation.get('facet_scores',{})
        return (values.get(facet) or values.get(str(facet)) or {}).get(ident,0)
    yes,no=score(checks,0,proposal['id']),score(checks,1,proposal['id'])
    verdict=('uncertain' if yes>=1.5 and no>=1.5 else 'supported' if yes>=1.5 else 'contradicted' if no>=1.5 else 'insufficient')
    result['support_checks']=[dict(card_id=proposal['id'],verdict=verdict,support_score=yes,
        contradiction_score=no,status='advisory')]
    if related:
        pairs=jev_client.evaluate(vault,json.dumps(dict(anchor=packet(proposal)),ensure_ascii=False),
            [packet(r) for r in related],source_versions=before,scope=proposal['scope'],
            facets=RELATIONS,purpose='memory_review')
        result['evaluations']['relations']=pairs
        try:
            if snapshot()!=before:return discard()
        except (OSError,ValueError,TypeError,KeyError):return discard()
        if pairs.get('mode')=='off' and not pairs.get('degraded'):
            result.update(status='degraded',diagnostics=['relations_disabled_during_evaluation']);return result
        if pairs.get('degraded'):
            result.update(status='degraded',diagnostics=pairs.get('diagnostics',[]));return result
        for row in related:
            scores={label:score(pairs,i,row['id']) for i,label in enumerate(('same_claim','incompatible','narrows'))}
            hits=[label for label,value in scores.items() if value>=1.5]
            result['relation_candidates'].append(dict(source_id=row['id'],target_id=proposal['id'],
                relation=hits[0] if len(hits)==1 else 'uncertain',scores=scores,status='proposed',
                reason='Existing card compared toward proposed anchor; independent source review required.'))
    return result
