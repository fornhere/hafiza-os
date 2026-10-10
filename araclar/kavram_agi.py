"""Kavram ağı: incelenmiş kayıtları kavramlara bağlayan yönlendirme katmanı.

Kavram tanımları (`komuta/kavramlar.json`) yönlendirme kuralıdır; kullanıcı
tercihi, yeni iddia veya onay değildir. Üyelik kaydın kendi ifadesinde seçici
sözcük eşleşmesiyle belirlenir; model çağrısı yoktur.

İki çıktı üretir:
- Arama: üye kayda kavramın eş anlamlı sözcükleri ek arama anahtarı olarak
  verilir. Anahtar tek başına kayıt seçemez (bkz. gorev_baglam.rank_records);
  bağlam metnine girmez, kanonik katalog değişmez.
- Obsidian: `beyin/` altında yönetilen, salt-okunur bir döküm. Elle değişen
  döküm dosyasının üzerine yazılmaz.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import hafiza as h

DEFINITIONS = Path('komuta/kavramlar.json')
EXPORT_DIR = Path('beyin')
# Mark sits at the end so Obsidian still reads the leading YAML properties.
MARK = '\n<!-- kavram-agi-v1 sha256:{} -->\n'
_MARK_RE = re.compile(r'(.*)\n<!-- kavram-agi-v1 sha256:([a-f0-9]{64}) -->\n', re.S)
_ID_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,60}')
CAUTION = ('Otomatik döküm: kavram üyeliği sözcük eşleşmesidir; yeni tercih, '
           'kanıt veya kullanıcı onayı değildir. Elle düzenleme; kaynak kayıtları değiştir.')
_TR = str.maketrans('çğıöşüÇĞİÖŞÜâîû', 'cgiosuCGIOSUaiu')


def _data(vault):
    path = Path(vault) / DEFINITIONS
    if not path.is_file() or path.is_symlink():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def subjects(vault):
    """Leading subject words dropped from note names (e.g. the user's name)."""
    try:
        words = _data(vault).get('ozne', ['Kullanıcı'])
    except (ValueError, OSError, AttributeError):
        words = ['Kullanıcı']
    return [w for w in words if isinstance(w, str) and w.strip()] if isinstance(words, list) else []


def definitions(vault):
    """Validated concept definitions; a missing file means no concept layer."""
    data = _data(vault)
    if not data:
        return []
    items = data.get('kavramlar') if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError('invalid_concept_file')
    seen = set()
    for item in items:
        if (not isinstance(item, dict) or set(item) - {'id', 'title', 'selectors', 'aliases', 'related', 'note'}
                or not isinstance(item.get('id'), str) or not _ID_RE.fullmatch(item['id'])
                or item['id'] in seen or not isinstance(item.get('title'), str) or not item['title'].strip()):
            raise ValueError('invalid_concept')
        for key in ('selectors', 'aliases', 'related'):
            value = item.get(key, [])
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError('invalid_concept_' + key)
        if not item.get('selectors'):
            raise ValueError('invalid_concept_selectors')
        if h.contains_secret(json.dumps(item, ensure_ascii=False)):
            raise ValueError('restricted_concept')
        seen.add(item['id'])
    for item in items:
        if any(r not in seen or r == item['id'] for r in item.get('related', [])):
            raise ValueError('invalid_concept_related')
    # Distinct titles must not share one export file (case-insensitive file systems too).
    names = [_filename(item['title']).casefold() for item in items]
    if len(set(names)) != len(names):
        raise ValueError('duplicate_concept_filename')
    return items


def _member(selectors, text):
    from gorev_baglam import content_words, word_match
    words = content_words(text)
    return any(word_match(s, w) for s in selectors for w in words)


def memberships(vault, rows, concepts=None, text=lambda r: r.get('statement', '')):
    """memory_id -> [concept ids]; membership reads only the record's own text."""
    from gorev_baglam import content_words
    concepts = definitions(vault) if concepts is None else concepts
    result = {}
    for row in rows:
        own = text(row)
        ids = [c['id'] for c in concepts if _member(content_words(' '.join(c['selectors'])), own)]
        if ids:
            result[row.get('memory_id') or row.get('id')] = ids
    return result


def concept_keys(vault, rows):
    """memory_id -> extra search words: only the aliases of its concepts.

    Selectors decide membership; reusing them as keys turned generic words
    (metin, cümle) into matches on real prompts (erisim_olc, 2026-10-10)."""
    try:
        concepts = definitions(vault)
    except (ValueError, OSError):
        return {}
    lookup = {c['id']: c for c in concepts}
    keys = {}
    for memory_id, ids in memberships(vault, rows, concepts).items():
        words = []
        if not any(lookup[cid].get('aliases') for cid in ids):
            continue
        for cid in ids:
            for word in lookup[cid].get('aliases', []):
                if word not in words:
                    words.append(word)
        keys[memory_id] = tuple(words)
    return keys


def ranker(vault, rank):
    """Wrap a rank_records-like callable so catalog rows carry concept keys.

    Ranking sees keyed copies; callers get their original row objects back, so
    keys never leak into context text, profiles or canonical writes.
    """
    def ranked(rows, query, **options):
        rows = list(rows)
        keys = concept_keys(vault, rows)
        if not keys:
            return rank(rows, query, **options)
        keyed = [dict(r, kavram_anahtarlari=keys[r.get('memory_id')]) if r.get('memory_id') in keys else r
                 for r in rows]
        back = {id(k): r for k, r in zip(keyed, rows)}
        return [back.get(id(r), r) for r in rank(keyed, query, **options)]
    return ranked


# ---- Obsidian dökümü -------------------------------------------------------

def _slug(text, lead=(), limit=6):
    from gorev_baglam import query_words
    text = unicodedata.normalize('NFC', text).strip()
    if lead:
        text = re.sub(r'^(?:' + '|'.join(re.escape(w) for w in lead) + r')(?:\s*,)?\s+', '', text, flags=re.I)
    words = [w.translate(_TR) for w in query_words(text) if len(w) > 2][:limit]
    return '-'.join(re.sub(r'[^a-z0-9]', '', w.lower()) for w in words).strip('-') or 'kayit'


def _filename(title):
    return re.sub(r'[\\/:*?"<>|#^\[\]]', '-', title).strip() or 'kavram'


def _short(text, limit=110):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def _project(scope):
    return scope.split(':', 1)[1] if isinstance(scope, str) and scope.startswith('project:') else None


SESSION_DIRS = (Path('günlük/oturumlar'), Path('gelen-kutusu/codex-oturumları'))
SESSION_LIMIT = 3


def _session_topic(path):
    """Session title (H1) or, for hash-named receipts, the first summary paragraph."""
    lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    title = next((l[2:].strip() for l in lines if l.startswith('# ')), path.stem)
    if 'makbuzu' in title.lower() or re.fullmatch(r'[0-9a-f]{16,}', path.stem):
        body = [l for l in lines if l.strip() and not l.startswith(('#', '<!--', 'Durum:', '[[', '---'))]
        return (body[0][:240] if body else ''), title
    return title, title


def sessions(vault, concepts):
    """concept id -> [(relative path, label)]; topic association, never evidence.

    Only a session's own title/summary is read and old receipts are not edited;
    each session joins at most SESSION_LIMIT concepts, the strongest matches."""
    from gorev_baglam import content_words, word_match
    vault = Path(vault)
    vocab = {c['id']: content_words(' '.join(c['selectors'] + c.get('aliases', []))) for c in concepts}
    result = {c['id']: [] for c in concepts}
    for folder in SESSION_DIRS:
        root = vault / folder
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.glob('*.md'), reverse=True):
            if path.name.lower() == 'readme.md' or path.is_symlink():
                continue
            try:
                topic, title = _session_topic(path)
            except OSError:
                continue
            if not topic or h.contains_secret(topic) or h.contains_secret(title):
                continue
            words = content_words(topic)
            hits = sorted(((sum(any(word_match(v, w) for v in vocab[cid]) for w in words), cid)
                           for cid in vocab), reverse=True)
            for count, cid in hits[:SESSION_LIMIT]:
                if count:
                    label = _short(title if not title.lower().startswith('codex') else topic, 70)
                    result[cid].append((path.relative_to(vault).with_suffix('').as_posix(), label))
    return result


def build(vault):
    """Pure graph model: concepts, memory nodes, knowledge cards, edges."""
    import bilgi_agi
    vault = Path(vault)
    concepts = definitions(vault)
    catalog = [r for r in h.load_catalog(vault)
               if h.retrievable(r) and not h.context_record_errors(vault, r)
               and not h.contains_secret(r.get('statement', ''))]
    cards, diagnostics = bilgi_agi._rows(vault) if (vault / 'bilgi').is_dir() else ([], [])
    mem_of = memberships(vault, catalog, concepts)
    card_of = memberships(vault, cards, concepts, text=lambda r: r['title'] + ' ' + r['statement'])
    names, used, lead = {}, set(), subjects(vault)
    for row in sorted(catalog, key=lambda r: r['memory_id']):
        base = _slug(row['statement'], lead)
        name = base
        if name in used:
            name = base + '-' + hashlib.sha256(row['memory_id'].encode()).hexdigest()[:4]
        used.add(name)
        names[row['memory_id']] = name
    nodes = {}
    for c in concepts:
        members = [r for r in catalog if c['id'] in mem_of.get(r['memory_id'], [])]
        linked_cards = [d for d in cards if c['id'] in card_of.get(d['id'], [])]
        nodes[c['id']] = dict(concept=c, memories=members, cards=linked_cards,
                              projects=sorted({p for p in (_project(r['scope']) for r in members + linked_cards) if p}))
    edges = {}
    for c in concepts:
        for other in c.get('related', []):
            edges.setdefault(tuple(sorted((c['id'], other))), set()).add('tanım')
    for ids in list(mem_of.values()) + list(card_of.values()):
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                edges.setdefault(tuple(sorted((a, b))), set()).add('ortak kayıt')
    linked = sessions(vault, concepts)
    for cid, node in nodes.items():
        node['sessions'] = linked.get(cid, [])
    return dict(concepts=nodes, memories=catalog, names=names, memberships=mem_of,
                cards=cards, card_memberships=card_of, edges=edges, diagnostics=diagnostics)


def _neighbours(model, cid):
    out = []
    for (a, b), why in sorted(model['edges'].items()):
        if cid in (a, b):
            out.append((b if a == cid else a, why))
    return out


def render(vault, model):
    """Relative path -> markdown body for every managed export file."""
    vault = Path(vault)
    concepts = model['concepts']
    title = {cid: n['concept']['title'] for cid, n in concepts.items()}
    link = lambda cid: f"[[beyin/kavramlar/{_filename(title[cid])}|{title[cid]}]]"
    files = {}

    def project_link(p):
        durum = vault / 'projeler' / p / 'DURUM.md'
        return f"[[projeler/{p}/DURUM|{p}]]" if durum.is_file() else p

    hub = ['# Beyin', '', CAUTION, '', '## Kavramlar', '']
    for cid, n in sorted(concepts.items(), key=lambda kv: (-len(kv[1]['memories']) - len(kv[1]['cards']), kv[0])):
        hub.append(f"- {link(cid)} — {len(n['memories'])} kayıt, {len(n['cards'])} bilgi kartı, "
                   f"{len(n.get('sessions', []))} oturum")
    loose = [r for r in model['memories'] if r['memory_id'] not in model['memberships']]
    if loose:
        hub += ['', '## Kavramı olmayan kayıtlar', '']
        hub += [f"- [[beyin/hafıza/{model['names'][r['memory_id']]}|{_short(r['statement'], 80)}]]" for r in loose]
    projects = sorted({p for n in concepts.values() for p in n['projects']})
    if projects:
        hub += ['', '## Projeler', ''] + [f"- {project_link(p)}" for p in projects]
    hub += ['', 'Ana giriş: [[Ana Sayfa]]']
    files['Beyin.md'] = '\n'.join(hub) + '\n'

    for cid, n in concepts.items():
        c = n['concept']
        lines = ['---', 'tür: kavram', f"kavram: {cid}", 'aliases: [' + ', '.join(json.dumps(a, ensure_ascii=False) for a in c.get('aliases', [])) + ']', '---',
                 f"# {c['title']}", '']
        if c.get('note'):
            lines += [c['note'], '']
        lines += [f"Seçiciler: {', '.join(c['selectors'])}"]
        if c.get('aliases'):
            lines += [f"Eş sözcükler: {', '.join(c['aliases'])}"]
        lines += ['', '## Kayıtlar', '']
        lines += [f"- [[beyin/hafıza/{model['names'][r['memory_id']]}|{_short(r['statement'])}]] ({r['scope']})"
                  for r in n['memories']] or ['- Eşleşen incelenmiş kayıt yok.']
        if n['cards']:
            lines += ['', '## Bilgi kartları', '']
            lines += [f"- [[bilgi/{d['id']}|{d['title']}]] ({d['scope']})" for d in n['cards']]
        near = _neighbours(model, cid)
        if near:
            lines += ['', '## İlgili kavramlar', '']
            lines += [f"- {link(o)} — {', '.join(sorted(why))}" for o, why in near]
        if n['projects']:
            lines += ['', '## Projeler', ''] + [f"- {project_link(p)}" for p in n['projects']]
        if n.get('sessions'):
            lines += ['', '## İlgili oturumlar', '', 'Başlık/özet eşleşmesi; kayıt veya karar değildir.', '']
            lines += [f"- [[{path}|{label.replace('|', '/').replace(']', ')')}]]" for path, label in n['sessions']]
        lines += ['', '---', CAUTION]
        files[f"kavramlar/{_filename(c['title'])}.md"] = '\n'.join(lines) + '\n'

    for r in model['memories']:
        ids = model['memberships'].get(r['memory_id'], [])
        p = _project(r['scope'])
        lines = ['---', 'tür: hafıza', f"memory_id: {r['memory_id']}", f"kapsam: {r['scope']}",
                 f"güven: {r.get('confidence', 'bilinmiyor')}", f"tarih: {r.get('observed_at') or r.get('valid_from') or 'bilinmiyor'}", '---',
                 f"# {_short(r['statement'], 80)}", '', r['statement'], '']
        if ids:
            lines += ['Kavramlar: ' + ' · '.join(link(cid) for cid in ids)]
        if p:
            lines += ['Proje: ' + project_link(p)]
        lines += [f"Kaynak: [[{r['source_path']}]]", f"Kanonik kayıt: `zihin/hafıza-kataloğu.jsonl` → `{r['memory_id']}`",
                  '', '---', CAUTION]
        # No back-link to the hub: it turned the graph into one star again.
        files[f"hafıza/{model['names'][r['memory_id']]}.md"] = '\n'.join(lines) + '\n'
    return files


def export(vault, apply=False):
    """Refresh the managed `beyin/` snapshot; never touches canonical records."""
    vault = Path(vault)
    return h.serialized(_export)(vault, True) if apply else _export(vault, False)


def _managed(path):
    match = _MARK_RE.fullmatch(path.read_text(encoding='utf-8'))
    return bool(match) and hashlib.sha256(match[1].encode()).hexdigest() == match[2]


def _export(vault, apply):
    import bilgi_agi
    root = vault / EXPORT_DIR
    if any(p.is_symlink() for p in (vault, root)) or (
            root.exists() and not root.resolve().is_relative_to(vault.resolve())):
        raise ValueError('unsafe_export_path')
    files = render(vault, build(vault))
    base = vault.resolve()

    def unsafe(path):
        # Every component below the vault must be a real directory/file, so a
        # symlinked subfolder can never redirect a write outside the vault.
        parts = path.relative_to(vault).parts
        return (any((vault.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1))
                or not path.resolve().is_relative_to(base))
    wanted = {root / rel: body + MARK.format(hashlib.sha256(body.encode()).hexdigest()) for rel, body in files.items()}
    risky = sorted(str(p.relative_to(vault)) for p in list(wanted) + (list(root.rglob('*')) if root.is_dir() else [])
                   if unsafe(p))
    if risky:
        raise ValueError('unsafe_export_path: ' + ', '.join(risky[:5]))
    existing = {p for p in root.rglob('*.md')} if root.is_dir() else set()
    blocked = sorted(str(p.relative_to(vault)) for p in existing if not _managed(p))
    if blocked:
        raise ValueError('export_manually_changed: ' + ', '.join(blocked[:5]))
    changed = [p for p, text in wanted.items() if not p.exists() or p.read_text(encoding='utf-8') != text]
    stale = sorted(existing - set(wanted))
    if apply:
        for p in changed:
            bilgi_agi._write(p, wanted[p])
            if p.read_text(encoding='utf-8') != wanted[p]:
                raise ValueError('export_readback_failed')
        for p in stale:
            p.unlink()
    rel = lambda ps: [str(p.relative_to(vault)) for p in sorted(ps)]
    return dict(path=str(root), files=len(wanted), changed=rel(changed), removed=rel(stale),
                applied=bool(apply and (changed or stale)), snapshot_only=True)


def status(vault):
    vault = Path(vault)
    model = build(vault)
    return dict(concepts={cid: dict(memories=len(n['memories']), cards=len(n['cards']))
                          for cid, n in model['concepts'].items()},
                memories=len(model['memories']), unassigned=sorted(r['memory_id'] for r in model['memories']
                                                                  if r['memory_id'] not in model['memberships']),
                edges=len(model['edges']), diagnostics=model['diagnostics'])


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--vault', type=Path, required=True)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('status')
    exp = subs.add_parser('export')
    exp.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        result = export(args.vault, args.apply) if args.command == 'export' else status(args.vault)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
