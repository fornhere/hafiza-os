"""Read-only reuse suggestions from reviewed outputs; lexical match is not approval."""
import argparse
import json
import re
from pathlib import Path

_STOPWORDS = {'bir', 'bu', 've', 'ile', 'için', 'olan', 'olarak', 'the', 'a', 'an', 'and', 'for', 'to', 'of'}
_REQUIRED_WORK = 'Çıktıyı yeni ihtiyaca göre incele, gerekli uyarlamayı yap ve sonucu yeniden doğrula.'


def verified_outputs(vault, project_id):
    # Lazy import permits isolated tests while the output registry is installed.
    from cikti_kayit import verified_outputs as read
    return read(vault, project_id)


def terms(text):
    normalized = text.casefold().replace('i\u0307', 'i')
    return set(re.findall(r'[^\W_]+', normalized)) - _STOPWORDS


def propose(vault, project_id, need, limit=2, max_chars=1800):
    """Return whole candidates within the rendered-text budget, without side effects.

    Exact token overlap ranks candidates; no semantic equivalence, suitability,
    effort reduction, or human acceptance is inferred from it.
    """
    if not isinstance(need, str) or not isinstance(project_id, str) or not project_id.strip():
        raise ValueError('project_id ve need metin olmalı; proje boş olamaz')
    if not isinstance(limit, int) or limit < 0 or not isinstance(max_chars, int) or max_chars < 0:
        raise ValueError('limit ve max_chars negatif olmayan tamsayı olmalı')
    result = dict(status='proposed', candidates=[], diagnostics=[], text='')
    query = terms(need)
    if not query or not limit:
        return result
    registry = verified_outputs(Path(vault), project_id)
    result['diagnostics'] = list(registry.get('diagnostics', []))
    ranked = []
    for output in registry.get('outputs', []):
        # Defense against accidental scope mixing in callers/registry adapters.
        if output.get('project_id') != project_id:
            continue
        matched = sorted(query & terms(output['label'] + ' ' + ' '.join(output['uses'])))
        if matched:
            ranked.append((len(matched), str(output['id']), output, matched))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    blocks = []
    for _, _, output, matched in ranked:
        reason = 'İhtiyaç ile etiket/kullanım alanlarında ortak sözcükler: ' + ', '.join(matched)
        candidate = dict(status='proposed', source=dict(output), matched_terms=matched,
                         reason=reason, required_work=_REQUIRED_WORK)
        block = (f"Öneri: {output['label']}\nKaynak: {output['path']} "
                 f"(çıktı: {output['id']}; görev: {output['task_id']})\n"
                 f"{reason}\nGereken iş: {_REQUIRED_WORK}")
        next_text = '\n\n'.join(blocks + [block])
        if len(next_text) > max_chars:
            continue  # Never cut a source or reason midway to fit the budget.
        blocks.append(block)
        result['candidates'].append(candidate)
        if len(result['candidates']) >= limit:
            break
    result['text'] = '\n\n'.join(blocks)
    if ranked and not result['candidates']:
        result['diagnostics'].append('reuse_candidates_exceed_text_budget')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--project', required=True)
    parser.add_argument('--need', required=True)
    parser.add_argument('--limit', type=int, default=2)
    parser.add_argument('--max-chars', type=int, default=1800)
    args = parser.parse_args(argv)
    print(json.dumps(propose(args.vault, args.project, args.need, args.limit, args.max_chars),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
