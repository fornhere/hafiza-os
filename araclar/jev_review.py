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
