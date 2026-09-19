"""Read-only, source-validated decision timeline; never infers decision reasons."""
import argparse
import hashlib
import json
from pathlib import Path
import hafiza as h


def history(vault, query, scope='user', limit=5, budget=1800):
    from gorev_baglam import content_words, word_match, task_intent, asset_claim_overrides
    vault = Path(vault).resolve()
    budget = max(0, int(budget)); limit = max(0, min(20, int(limit)))
    terms = content_words(task_intent(query)) - content_words('neden seçtik seçmiştik eski karar karar geçmişi geçmiş göster seçildi')
    rows = [r for r in h.load_catalog(vault) if r.get('sensitivity') == 'normal'
            and r.get('scope') in ('user', scope) and r.get('status') in ('active', 'superseded')
            and not h.contains_secret(str(r.get('statement', '')))]
    def subject(row): return (row.get('scope'), row.get('subject_key'))
    subjects = {subject(r) for r in rows if
                (not terms and scope != 'user' and r.get('scope') == scope) or
                (terms and any(word_match(t, w) for t in terms for w in
                 content_words(str(r.get('subject_key', ''))+' '+str(r.get('statement', '')))))}
    rows = [r for r in rows if subject(r) in subjects]
    overrides = asset_claim_overrides(vault)
    cycle_ids = set()
    diagnostics = []; versions = {}; entries = []; lines = []
    ids = {r['memory_id'] for r in rows}
    by_id = {r['memory_id']: r for r in rows}
    duplicates = {ident for ident in ids if sum(r['memory_id'] == ident for r in rows) > 1}
    for ident in sorted(duplicates): diagnostics.append(ident+':duplicate_id')
    for row in rows:
        ident = row['memory_id']; previous = row.get('supersedes')
        if ident in overrides: diagnostics.append(ident+':'+overrides[ident])
        if previous and previous not in ids: diagnostics.append(ident+':predecessor_unavailable')
        seen = set(); cursor = ident
        while cursor in by_id:
            if cursor in seen:
                diagnostics.append(ident+':cycle'); cycle_ids.update(seen); break
            seen.add(cursor); cursor = by_id[cursor].get('supersedes')
    # Ambiguity must survive source loss and output-budget trimming.
    ambiguous = {s for s in subjects if sum(r.get('status') == 'active' for r in rows if subject(r) == s) > 1}
    for group in sorted(ambiguous): diagnostics.append(':'.join(group)+':multiple_active')
    valid = []
    for row in rows:
        ident = row['memory_id']
        if ident in duplicates: continue
        try:
            errors = h.context_record_errors(vault, row)
            if errors:
                diagnostics.append(ident+':source_invalid'); continue
            source = h.source_file(vault, row['source_path']); raw = source.read_bytes()
            # Require a pinned or reviewed source revision for a source-bound timeline.
            content = raw.decode('utf-8')
            if not (row.get('source_content_hash') == h.statement_hash(content) or h.current_source_binding(vault, row, content)):
                diagnostics.append(ident+':source_unpinned'); continue
        except (OSError, ValueError, KeyError, TypeError):
            diagnostics.append(ident+':source_invalid'); continue
        current = row['status'] == 'active' and h.retrievable(row, scope) and subject(row) not in ambiguous and ident not in cycle_ids and ident not in overrides
        rationale = row.get('rationale')
        if not isinstance(rationale, str) or not rationale or rationale not in content or h.contains_secret(rationale): rationale = None
        entry = dict(id=ident, scope=row['scope'], subject_key=row['subject_key'], statement=row['statement'],
                     status=row['status'], current=current, override_reason=overrides.get(ident), supersedes=row.get('supersedes'),
                     observed_at=row.get('observed_at'), valid_from=row.get('valid_from'), valid_to=row.get('valid_to'),
                     rationale=rationale, conditions=(row.get('conditions') if isinstance(row.get('conditions'),str) and row['conditions'] in content and not h.contains_secret(row['conditions']) else None), source_path=row['source_path'], source_sha256=hashlib.sha256(raw).hexdigest())
        valid.append(entry)
    if diagnostics:
        notice = 'Karar geçmişi uyarısı: çelişkili veya doğrulanamayan kayıtlar var; güncel karar varsayma.'
        if len(notice) <= budget: lines.append(notice)
    for entry in sorted(valid, key=lambda r: (str(r['observed_at'] or ''), r['id']), reverse=True):
        label = 'güncel' if entry['current'] else 'tarihsel / güncelliği seçilmedi'
        text = (f"Karar geçmişi [{label}; {entry['status']}]: {entry['statement']} "
                f"(kayıt: {entry['id']}; tarih: {entry['observed_at'] or 'bilinmiyor'}; kaynak: {entry['source_path']}). "
                + ('Gerekçe: '+entry['rationale'] if entry['rationale'] else 'Gerekçe kayıtlı değil.'))
        if entry['conditions']: text += ' Koşul: '+entry['conditions']
        if len(entries) >= limit: continue
        if len('\n'.join(lines+[text])) > budget: continue
        entries.append(entry); lines.append(text); versions[entry['source_path']] = entry['source_sha256']
    return dict(text='\n'.join(lines), entries=entries, source_versions=versions,
                diagnostics=sorted(set(diagnostics)), considered_ids=sorted(ids), derived=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('query'); parser.add_argument('--scope', default='user')
    parser.add_argument('--budget', type=int, default=1800)
    args = parser.parse_args()
    print(json.dumps(history(args.vault, args.query, args.scope, budget=args.budget), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
