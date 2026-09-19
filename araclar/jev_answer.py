"""Read-only answer claim checks. Exact evidence gates precede semantic judgment."""
import json
from pathlib import Path
import hafiza as h
import bilgi_agi as b
import jev_client
from jev_review import SUPPORT


def verify(vault, claims, project_id=None):
    vault = Path(vault)
    if not isinstance(claims, list) or not 1 <= len(claims) <= 20:
        raise ValueError('claims_limit_1_20')
    if len(json.dumps(claims, ensure_ascii=False)) > 32000 or h.contains_secret(json.dumps(claims)):
        raise ValueError('claims_restricted_or_over_budget')
    rows, _ = b._rows(vault)
    rows = {r['id']: r for r in rows if r['scope'] in ('user', 'project:'+project_id if project_id else 'user')}
    catalog = {r['memory_id']:r for r in h.load_catalog(vault) if h.retrievable(r,'project:'+project_id if project_id else 'user') and not h.context_record_errors(vault,r)}
    results = []
    for i, claim in enumerate(claims):
        if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
            raise ValueError('invalid_claim')
        citations = claim.get('citations', [])
        if not isinstance(citations, list) or len(citations) > 8: raise ValueError('citation_limit')
        evidence = []; watched = {}; reason = None; used_cards={};used_memories={}
        for cite in citations:
            if not isinstance(cite, dict): raise ValueError('invalid_citation')
            if cite.get('memory_id'):
                record=catalog.get(cite['memory_id'])
                if record is None: reason='citation_not_current_or_in_scope'; break
                try:
                    path=b._safe(vault,record['source_path']); content=path.read_text(encoding='utf-8')
                    quote=cite.get('quote')
                    if record['source_path']!=cite.get('path') or b.digest(path)!=cite.get('sha256') or not isinstance(quote,str) or len(quote)<10 or quote not in content or h.contains_secret(quote):
                        reason='citation_quote_or_hash_mismatch'; break
                    if record.get('source_content_hash')!=h.statement_hash(content) and not h.current_source_binding(vault,record,content):
                        reason='citation_source_unpinned'; break
                    if h.contains_secret(content): reason='restricted_source'; break
                    used_memories[record['memory_id']]=record
                    evidence.append(dict(path=cite['path'],sha256=cite['sha256'],evidence=quote))
                    watched[cite['path']]=cite['sha256']
                    watched[str(h.CATALOG_PATH)]=b.digest(vault/h.CATALOG_PATH)
                    continue
                except (ValueError,OSError):reason='citation_source_unavailable';break
            row = rows.get(cite.get('card_id'))
            if row is None: reason = 'citation_not_current_or_in_scope'; break
            matches = [s for s in row['sources'] if s['path'] == cite.get('path') and s['sha256'] == cite.get('sha256') and s['evidence'] == cite.get('quote')]
            if not matches: reason = 'citation_quote_or_hash_mismatch'; break
            used_cards[row['id']]=row
            watched['bilgi/'+row['id']+'.md'] = b.digest(vault/'bilgi'/f"{row['id']}.md")
            watched.update({s['path']: s['sha256'] for s in matches})
            evidence.extend(matches)
        item = dict(index=i, verdict='insufficient', diagnostics=[], mechanical_verified=False)
        if reason or not evidence:
            item['diagnostics'] = [reason or 'citation_missing']; results.append(item); continue
        item['mechanical_verified'] = True
        candidate = dict(id='claim-'+str(i), title='Answer claim', scope='project:'+project_id if project_id else 'user', domains=['all'], statement=json.dumps(dict(claim=claim['text'], evidence=evidence), ensure_ascii=False))
        current_cards,_=b._rows(vault)
        current_cards={r['id']:r for r in current_cards}
        current_catalog={r['memory_id']:r for r in h.load_catalog(vault)}
        if any(current_cards.get(k)!=r for k,r in used_cards.items()) or any(current_catalog.get(k)!=r for k,r in used_memories.items()):
            item.update(verdict='degraded',diagnostics=['record_changed_before_evaluation']);results.append(item);continue
        evaluation = jev_client.evaluate(vault, 'Evaluate only this answer claim against the attached exact quotations. No outside knowledge.', [candidate], source_versions=watched, scope='project:'+project_id if project_id else 'user', facets=SUPPORT, purpose='evidence_review')
        try: unchanged = all(b.digest(b._safe(vault, path)) == sha for path, sha in watched.items())
        except (ValueError, OSError): unchanged = False
        fresh_cards,_=b._rows(vault)
        fresh_cards={r['id']:r for r in fresh_cards}
        fresh_memories={r['memory_id']:r for r in h.load_catalog(vault)}
        unchanged = unchanged and all(fresh_cards.get(k)==r for k,r in used_cards.items()) and all(fresh_memories.get(k)==r and h.retrievable(r,'project:'+project_id if project_id else 'user') and not h.context_record_errors(vault,r) for k,r in used_memories.items())
        if not unchanged:
            item.update(verdict='degraded', diagnostics=['source_changed_during_evaluation'])
        elif evaluation.get('degraded'):
            item.update(verdict='degraded', diagnostics=evaluation.get('diagnostics', []))
        elif evaluation.get('mode') != 'on':
            item.update(verdict='uncertain', diagnostics=['semantic_'+evaluation.get('mode', 'unavailable')])
        else:
            values = evaluation.get('facet_scores', {})
            yes = (values.get(0) or values.get('0') or {}).get(candidate['id'], 0)
            no = (values.get(1) or values.get('1') or {}).get(candidate['id'], 0)
            item['verdict'] = 'uncertain' if yes >= 1.5 and no >= 1.5 else 'supported' if yes >= 1.5 else 'contradicted' if no >= 1.5 else 'insufficient'
        results.append(item)
    return dict(claims=results, advisory=True, rewrites=False, canonical_writes=False)
