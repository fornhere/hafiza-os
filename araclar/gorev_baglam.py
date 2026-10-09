"""Source-validated task context with optional bounded Jev advice; no memory writes."""
import datetime as dt
import functools
import heapq
import math
import hashlib
import json
import os
import re
import time
from pathlib import Path
import hafiza as h
from is_ve_ders import brief, latest

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

@functools.lru_cache(maxsize=65536)
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
    # Kısa varyantlar alias sözlüğünde; genel hata toleransı uzun sözcüklerde.
    if min(len(left),len(right)) < 7 or abs(len(left)-len(right)) > 1: return False
    if len(left)==len(right):
        positions=[i for i,(a,b) in enumerate(zip(left,right)) if a!=b]
        return len(positions)==1 or (len(positions)==2 and positions[1]==positions[0]+1 and left[positions[0]]==right[positions[1]] and left[positions[1]]==right[positions[0]])
    short,long=sorted([left,right],key=len)
    return any(long[:i]+long[i+1:]==short for i in range(len(long)))

# Kısa alan varyantları yönlüdür; genel yazım hatası toleransını açmaz.
_ALIAS_VARIANTS = {'tweet': ('twit',), 'twitter': ('twit',)}

def alias_inflected(base, word):
    # Vowel-final aliases take unbuffered plural possessives (video-muz-a).
    # Keep this routing vocabulary out of general record/lesson ranking.
    return (inflected(base, word) or
        any(inflected(variant, word) for variant in _ALIAS_VARIANTS.get(base, ())) or
        (base[-1:] in 'aeıioöuü' and bool(base) and
         any(inflected(base + suffix, word) for suffix in ('mız', 'miz', 'muz', 'müz'))))


def alias_match(alias, words, fuzzy=False, *, ordered=False):
    parts=query_words(alias)
    if not parts: return False
    # Dersler ve diğer çağıranlar bütün parçaları herhangi sırada arar.
    if not ordered:
        return all(any(alias_inflected(part,word) or (fuzzy and one_typo(part,word))
                       for word in words) for part in parts)
    # Yalnız proje seçimi: ayrı konu sözcükleri proje adı değildir.
    return any(all(alias_inflected(part,word) or (fuzzy and one_typo(part,word))
                   for part,word in zip(parts,words[start:start+len(parts)]))
               for start in range(len(words)-len(parts)+1))

# Function words cannot establish a memory match. Domain aliases belong in config.
_STOPWORDS = set('kanka kanak knk oğlum amk şimdi şuan şuanda tamam tamamdır falan bakalım göre ilgili son artık önemli zaten ya yahu bir bu şu o ve veya ile için gibi daha çok az ne nasıl neden hangi ben benim sen bizim biz bana bunu şunu mı mi mu mü da de ama olarak olan olsun yap yapalım devam et üret'.split())
_SYNONYMS = ({'kapak', 'thumbnail'}, {'sunum', 'slayt', 'slideshow'},
             {'hafıza', 'bellek'}, {'yöntem', 'prosedür'}, {'yedek', 'yedekleme'})

def content_words(text):
    return set(query_words(text)) - _STOPWORDS

@functools.lru_cache(maxsize=8192)
def _synonym_groups(word):
    # Membership depends on one word, not every term/record pair. Keep the
    # same directional inflection rule as the original nested comparisons.
    return frozenset(index for index, group in enumerate(_SYNONYMS)
                     if any(inflected(term, word) for term in group))

# Pure function of two words; ranking calls it terms x words x records times.
@functools.lru_cache(maxsize=65536)
def word_match(left, right):
    if inflected(left, right) or inflected(right, left): return True
    return bool(_synonym_groups(left) & _synonym_groups(right))

def search_text(row):
    """Statement plus optional reviewed search keys; keys never enter context text."""
    keys = row.get('arama_anahtarlari')
    return ' '.join([row.get('statement', '')] + ([k for k in keys if isinstance(k, str)] if isinstance(keys, list) else []))

def rank_records(rows, query, *, tie_break=None, ignore=(), context=None, expansion=None):
    """Query coverage weighted by corpus rarity; order cannot affect selection.

    `ignore` words (e.g. the selected project's name) are scope, not topic
    evidence: they still match, but never count as one of the two independent
    words a long query needs. `context` (the previous user turn) never selects
    on its own: it can only complete a record the current query already
    anchors with an informative word, where the query alone was too weak, and
    it adds at most one such record, only when the current query selects none.
    A direct current topic must not acquire a competing prior-turn topic that
    displaces its cards at a downstream limit or budget.
    """
    terms = content_words(query)
    scoped = {t for t in terms if any(word_match(t, w) for w in ignore)}
    extra = {t for t in content_words(context) - terms
             if not any(word_match(t, u) for u in terms) and not any(word_match(t, w) for w in ignore)} if context else set()
    documents = [(row, content_words(search_text(row))) for row in rows]
    frequencies = {term: sum(any(word_match(term, word) for word in words)
                             for _, words in documents) for term in terms | extra}
    def rare(term): return 0 < frequencies[term] < max(2, len(rows)*0.5)
    def weight(term): return 1 + math.log((len(rows) + 1) / (frequencies[term] + 1))
    informative = {term for term in terms if rare(term)}
    extra = {term for term in extra if rare(term)}
    # Without a distinguishing term, a word shared by most records (e.g. the
    # user's name) selects only when it covers at least half of the query.
    ranked = []; completions = []
    for row, words in documents:
        matched = {term for term in terms if any(word_match(term, word) for word in words)}
        if not matched or (informative and not matched.intersection(informative)): continue
        score = sum(weight(term) for term in matched)
        # Long prompts share incidental words with almost every record; measured on
        # real prompts with erisim_olc.py, one overlapping word selected mostly noise.
        anchors = (matched & informative if informative else matched) - scoped
        weak = ((not informative and 2 * len(matched) < len(terms)) or
                (len(terms) > 3 and len(anchors) < 2))
        if weak:
            completed = {term for term in extra if any(word_match(term, word) for word in words)}
            if not (anchors & informative and completed): continue
            completions.append((score + sum(weight(term) / 2 for term in completed), len(matched), row))
            continue
        ranked.append((score, len(matched), row))
    def order(item):
        return (-item[0], -item[1], tie_break(item[2]) if tie_break else item[2].get('memory_id', ''))
    if not ranked:
        ranked.extend(sorted(completions, key=order)[:1])
    if expansion and area_expansion(query):
        ranked = [(score * 4, count, row) for score, count, row in ranked]
        # Expansion is weaker evidence and never changes the eligible scope.
        expanded = content_words(expansion) - terms
        additions = []
        selected_ids = {row.get('memory_id') for _, _, row in ranked}
        for row, words in documents:
            if row.get('memory_id') in selected_ids: continue
            matched = {t for t in terms if any(word_match(t, w) for w in words)}
            related = {w for w in words if any(word_match(t, w) for t in expanded)}
            if not matched - scoped or len(related) < 2: continue
            additions.append((sum(weight(t) for t in matched) * 4 + min(len(related), 4) / 4,
                              len(matched), row))
        ranked.extend(sorted(additions, key=order)[:2])
    return [row for _, _, row in sorted(ranked, key=order)]


def project_terms(project):
    """Specific project name words; generic workflow aliases stay topical."""
    names = [str(project.get('id', '')).replace('-', ' ')]
    names += [a for a in project.get('aliases', []) if isinstance(a, str)]
    return frozenset(content_words(' '.join(names)) - _GENERIC)

def _temporary_component(name):
    # Geçici/özel dizinler alt iş kanıtı değildir; sözcük sınırını koru.
    return name.startswith(('.', '_')) or bool(
        set(query_words(name)) & {'tmp', 'temp', 'temporary', 'cache', 'scratch', 'scratchpad'})

def _subtask_parts(project, cwd):
    """En derin proje köküne göre alt işi kartlardan bağımsız belirle."""
    if not cwd: return None
    location = Path(cwd).resolve()
    roots = [Path(r).resolve() for r in project.get('roots', [])
             if location.is_relative_to(Path(r).resolve())]
    if not roots: return None
    parts = location.relative_to(max(roots, key=lambda r: len(r.parts))).parts
    if parts and _temporary_component(parts[0]): return ()
    return parts


def _project_state(task, project):
    names = {frozenset(content_words(name)) for name in
             [project['id'], *project.get('aliases', [])] if name}
    return (task['id'] == 'project-state:' + project['id'] or
            ((task.get('transcript_source') or task.get('assertion_kind') == 'assistant_report') and
             (frozenset(content_words(task['title'])) in names or
              frozenset(content_words(task['id'])) in names)))


def _root_state_tasks(tasks, project):
    """Keep the freshest state and source-backed general project work.

    Project-named work is general only when its title/next action has no
    distinctive sibling-folder reference. Evidence alone is not work scope.
    An unconfirmed session report must not replace the verified general work.
    Missing/unreadable roots cannot safely establish that work is general.
    """
    sibling_words = set()
    readable = False
    for root in project.get('roots', []):
        try:
            children = list(Path(root).iterdir())
            for child in children:
                if child.is_dir() and not _temporary_component(child.name):
                    sibling_words.update(w for w in content_words(child.name) -
                                         project_terms(project) - _GENERIC if not w.isdecimal())
            readable = True
        except OSError:
            return _freshest_root_tasks(tasks, project, [])
    general = []
    if readable:
        for task in tasks:
            if _project_state(task, project) or task.get('confirmation_required'): continue
            words = content_words(task['title'] + ' ' + task.get('next_step', ''))
            names = [project['id'], *project.get('aliases', [])]
            named = any(content_words(name) - _GENERIC and alias_match(name, words)
                        for name in names)
            if named and not any(word_match(t, w) for t in sibling_words for w in words):
                general.append(task)
    return _freshest_root_tasks(tasks, project, general)


def _freshest_root_tasks(tasks, project, general):
    states = [t for t in tasks if _project_state(t, project)]
    focus = {t['id']: (0, 0, 0) for t in states + general}
    def order(task):
        return (bool(task.get('confirmation_required')), _task_focus_order(task, focus), task['id'])
    # Preserve the general record separately: a session's next step may omit
    # still-current project information held by that verified work record.
    kept = [min(group, key=order) for group in (general, states) if group]
    return sorted(kept, key=order)


def subtask_focus(tasks, project, cwd):
    """Alt iş biliniyorsa yalnız kaynakta ona atıf taşıyan kartları tut."""
    parts = _subtask_parts(project, cwd)
    if not parts: return tasks, {}, []
    # Sürüm numarası kardeş işin adı yerine geçmez.
    main = {w for w in content_words(parts[0]) - _GENERIC if not w.isdecimal()}
    detail = content_words(parts[1]) - _GENERIC if len(parts)>1 else set()
    focus = {}
    for task in tasks:
        title = content_words(task['title'])
        next_words = content_words(task.get('next_step', ''))
        evidence_words = content_words(task.get('evidence', ''))
        words = next_words | evidence_words
        # Proje durumunun genel başlığı alt iş bağı sayılmaz.
        if not _project_state(task, project): words |= title
        hits = sum(any(word_match(t,w) for w in words) for t in main)
        if hits:
            title_hits = sum(any(word_match(t,w) for w in title) for t in main)
            next_hits = sum(any(word_match(t,w) for w in next_words) for t in main)
            evidence_hits = sum(any(word_match(t,w) for w in evidence_words) for t in main)
            focus[task['id']] = (-title_hits, -next_hits, -evidence_hits, -hits,
                                -sum(any(word_match(t,w) for w in words) for t in detail))
    kept = [t for t in tasks if t['id'] in focus]
    omitted = [t['id']+':subtask_focus' for t in tasks if t['id'] not in focus]
    return kept, focus, omitted


def _source_paths(row):
    """Unsupported optional metadata cannot invalidate an otherwise valid card."""
    sources = row.get('sources')
    return [s['path'] for s in sources if isinstance(s, dict)
            and isinstance(s.get('path'), str) and s['path']] if isinstance(sources, list) else []


def _subtask_claim(row, project, query, cwd):
    """Alt işe bağlı kanıtı genel tercih gibi teslim etme; ek kaynak okuma yok."""
    sources = _source_paths(row)
    sources += [row.get('source_path')]
    sources = [s for s in sources if isinstance(s, str) and s]
    roots = project.get('roots', []) if project else []
    bound = []
    for source in sources:
        path = Path(source)
        for root in roots:
            try: parts = path.relative_to(Path(root)).parts
            except ValueError: continue
            if len(parts)>1 and not _temporary_component(parts[0]): bound.append((parts[0], False))
        # Eski oturum özetinin dosya adı tek videoyu açıkça tanımlayabilir.
        if path.parent.name == 'rollout_summaries':
            match = re.search(r'(?:^|[-_])([a-z][a-z0-9-]*)_video(?:_|$)', path.stem)
            if match: bound.append((match[1], True))
        parts = path.parts
        if (project and len(parts)>3 and parts[:2] == ('projeler', project['id'])
                and not _temporary_component(parts[2])): bound.append((parts[2], False))
    title = row.get('title') if isinstance(row.get('title'), str) else ''
    words = query_words(title)
    video = next((i for i,w in enumerate(words) if any(inflected(t, w) for t in ('video', 'yayın'))), None)
    # Başlığın video adından sonraki biçim sözcükleri iş kimliği değildir.
    if row.get('kind') == 'decision' and video is not None and video>0:
        bound.append((' '.join(words[:video]), True))
    if not bound: return False
    terms = content_words(query)
    if cwd and project:
        location = Path(os.path.abspath(cwd))
        for root in roots:
            try: parts = location.relative_to(Path(os.path.abspath(root))).parts
            except ValueError: continue
            if not any(_temporary_component(p) for p in parts):
                # Bir video klasörü doğrudan proje kökü olarak ayarlanabilir.
                terms |= content_words(parts[0] if parts else Path(root).name)
    def identity_match(term, word):
        return word_match(term, word) or (len(term)>=3 and word.startswith(term) and word[len(term):] in _SUFFIXES)
    for name, named_video in bound:
        identity = [w for w in query_words(name) if w not in _GENERIC and w not in _STOPWORDS]
        if not identity: continue
        if all(any(identity_match(t, w) for w in terms) for t in identity): return False
        if (named_video and identity[0] not in {'bölüm', 'bolum'} and
                not identity[0].isdigit() and any(identity_match(identity[0], w) for w in terms)): return False
    return True


def _guard_knowledge(data, project, query, cwd):
    """Yerel, sentez ve danışman bilgi çıktısında aynı teslim koruması."""
    if not data or not data.get('text'): return data
    rows = list(data.get('records') or [])
    rows += [t['source_record'] for t in data.get('transfers', [])]
    excluded = {r['id'] for r in rows if _subtask_claim(r, project, query, cwd)}
    if not excluded: return data
    # Boş satır statement'ın içinde de olabilir; yalnız teslim başlıkları sınırdır.
    cards = re.split(r'\n\n(?=Bilgi \[|Uyarlama önerisi \[|Konu:)', data['text'])
    kept_indices = [i for i, card in enumerate(cards) if not any(
        'Kaynak: bilgi/'+ident+'.md' in card for ident in excluded)]
    kept = [cards[i] for i in kept_indices]
    # Kalan kartın ilişkisi de elenen kararın açıklamasını yeniden taşımasın.
    kept = ['\n'.join(line for line in card.split('\n') if not any(
        line.startswith('İlişki: '+ident+' ') or line == 'İlişki: '+ident
        for ident in excluded)) for card in kept]
    records = [r for r in data.get('records', []) if r['id'] not in excluded]
    transfers = [t for t in data.get('transfers', []) if t['source_record']['id'] not in excluded]
    topics = []
    for topic in data.get('topics', []):
        ids = [i for i in topic['record_ids'] if i not in excluded]
        if ids:
            topics.append(dict(topic, record_ids=ids, summary=[r for r in topic.get('summary', [])
                                                               if r['record_id'] not in excluded]))
    records = [dict(r, relations=[link for link in r['relations'] if link['target'] not in excluded])
               if r.get('relations') else r for r in records]
    remaining = records + [t['source_record'] for t in transfers]
    paths = {'bilgi/'+r['id']+'.md' for r in remaining}
    paths.update(p for r in remaining for p in _source_paths(r))
    paths.update(e['path'] for r in remaining for e in r.get('examples', []) if e.get('path'))
    return dict(data, text='\n\n'.join(kept) if remaining else '', records=records,
                card_indices=dict(zip(kept, kept_indices)),
                transfers=transfers, topics=topics,
                source_versions={p:v for p,v in data.get('source_versions', {}).items() if p in paths},
                guarded_record_ids=sorted(excluded),
                omitted_record_ids=sorted(set(data.get('omitted_record_ids', [])) | excluded))


def _task_focus_order(task, focus):
    """Focus eligibility, then dated freshness, then lexical focus strength.

    Day precision keeps same-day query ranking intact; four-day older cards
    cannot outrank fresh focused/session state merely by repeating folder words.
    Without subtask evidence the existing rank_records ordering is unchanged.
    """
    if not focus: return ()
    freshness = 0
    for field in ('last_verified', 'content_updated_at', 'updated_at'):
        try:
            freshness = dt.date.fromisoformat(str(task.get(field, ''))[:10]).toordinal()
            break
        except ValueError: pass
    return (task['id'] not in focus, -freshness, focus.get(task['id'], (0,0,0)))


def scope_profile(rows, project, projects, limit=4):
    """Stable, query-independent preferences from an established scope.

    Callers supply source-validated eligible rows. Legacy semantic facts do
    not become preferences by guessing from their IDs or statement wording.
    User records mentioning a configured domain/project are not universal.
    Reviewed legacy preferences may lack category; explicit preference verbs
    support a read-time classification, never a canonical metadata rewrite.
    """
    if project is None: return []
    scope = 'project:' + project['id']
    domains = content_words(' '.join(str(a) for p in projects
                                   for a in [p.get('id', ''), *p.get('aliases', [])]))
    def eligible(row):
        category = row.get('category')
        legacy_preference = category is None and bool(re.search(
            r'\b(?:tercih eder|istemez|sevmez)\b', row.get('statement', ''), re.I))
        if category not in ('preference', 'procedure') and not (
                category is None and (row.get('kind') == 'procedural' or legacy_preference)):
            return False
        # A core profile comes from maintained project/user reference files,
        # not from episodic captures and imported historical summaries.
        path = Path(row.get('source_path', ''))
        if row.get('scope') == scope:
            return path.is_relative_to(Path('projeler') / project['id'])
        words = content_words(search_text(row))
        return (row.get('scope') == 'user' and path.is_relative_to(Path('zihin'))
                and category == 'preference'
                and not any(word_match(t, w) for t in domains for w in words))
    def order(row):
        date = str(row.get('observed_at', ''))[:10]
        try: freshness = dt.date.fromisoformat(date).toordinal()
        except ValueError: freshness = 0
        return (row.get('scope') != scope,
                not str(row.get('source_path', '')).startswith('projeler/'),
                row.get('confidence') != 'explicit-user', -freshness,
                row.get('category') != 'preference', row.get('memory_id', ''))
    scoped = sorted((r for r in rows if eligible(r) and r.get('scope') == scope), key=order)
    general = sorted((r for r in rows if eligible(r) and r.get('scope') == 'user'), key=order)
    return (scoped[:max(0, limit-1)] + general[:1])[:limit]
# Workflow vocabulary, independent of record IDs and project names. Only the
# current request can activate a domain; scope alone cannot activate all of it.
_AREA_TERMS = (
    ('video senaryo kurgu çekim metin', 'anlatım anlatmayı izleyici konuşma senaryo çekim'),
    ('kapak thumbnail maskot tasarım', 'görsel kimlik referans hareket kompozisyon tasarım'),
)

def area_expansion(query):
    words = content_words(query)
    return ' '.join(extra for triggers, extra in _AREA_TERMS
                    if any(word_match(t, w) for t in content_words(triggers) for w in words))


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


def inventory_intent(query):
    """Yeni aday seçimi; sıradan üretim/düzenleme istemi envanter istemez."""
    words = query_words(task_intent(query))
    def has(*bases):
        return any(word_match(base, word) or alias_inflected(base, word)
                   or (base == 'iş' and word in {'işi','işin','işe','işler','işleri'})
                   for base in bases for word in words)
    conditional = any(word in {'çeksem','çeksek','çekseydim','yapsam','yapsak',
                               'yapayım','yapalım','çekeyim','çekelim',
                               'yapmalı','yapmalıyım','çekmeli','çekmeliyim'} for word in words)
    idea = has('fikir') or any(inflected('fikr', word) for word in words)
    what_video = any(left == 'ne' and word_match('video', right)
                     for left, right in zip(words, words[1:]))
    return bool(('ne' in words and conditional) or what_video or has('aday') or
                (has('konu') and (has('öneri') or any(action_form(w, ('öner',)) for w in words))) or
                (has('yeni') and idea) or
                (has('sıradaki') and has('video','iş','proje')) or
                (idea and has('video','proje','iş')))


def file_revision(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_inventory(vault, project, query, omitted):
    spec = (project or {}).get('inventory')
    if spec is None or not inventory_intent(query): return None
    try:
        if not isinstance(spec, dict): raise ValueError('config')
        relative, marker = spec.get('path'), spec.get('marker')
        if (not isinstance(relative, str) or Path(relative).is_absolute() or
            Path(relative).suffix != '.md' or not isinstance(marker, str) or
            not re.fullmatch(r'[\w-]+', marker)): raise ValueError('config')
        relative.encode('utf-8')
        path = h.source_file(vault, relative)
        revision = file_revision(path)
        raw = path.read_bytes()  # Tek içerik okuması; hash aynı baytlara dayanır.
        if file_revision(path) != revision: raise ValueError('changed')
        text = raw.decode('utf-8')
        blocks = re.findall(r'<!--\s*'+re.escape(marker)+r'\s*\n(.*?)-->', text, re.S)
        if len(blocks) != 1: raise ValueError('block')
        rows = []; invalid = False
        states = {'yayinlandi','kurguda','cekildi','planlandi','vazgecildi'}
        for line in blocks[0].splitlines():
            if not line.strip(): continue
            try:
                row = json.loads(line)
                if (not isinstance(row, dict) or row.get('durum') not in states or
                    row.get('tarih') is not None and not isinstance(row['tarih'], str)):
                    raise ValueError('row')
                # JSON escapes can decode to lone surrogates in valid UTF-8 files.
                # Normalize here so delivery and package hashing only see safe text.
                title = ''
                for field in ('baslik', 'konu'):
                    value = row.get(field)
                    if value is None: continue
                    if not isinstance(value, str): raise ValueError('row')
                    value.encode('utf-8')
                    value = ' '.join(value.split())
                    if not title: title = value
                if not title: raise ValueError('row')
                rows.append(dict(row, baslik=title))
            except (ValueError, TypeError, RecursionError):
                invalid = True
        if invalid: omitted.append('inventory:invalid_or_missing')
        if not rows:
            if not invalid: omitted.append('inventory:empty')
            return None
        def order(row):
            confidence = {'yuksek':3,'yüksek':3,'orta':2,'dusuk':1,'düşük':1}
            return (row.get('tarih') or '', row['durum'] in {'yayinlandi','cekildi'},
                    confidence.get(str(row.get('guven', '')).casefold(), 0))
        done = [row for row in rows if row['durum'] in {'yayinlandi','kurguda','cekildi'}]
        planned = [row for row in rows if row['durum'] == 'planlandi']
        if not done and not planned:
            if not invalid: omitted.append('inventory:empty')
            return None
        def distinct_latest(rows, limit):
            distinct = {}
            for row in rows:
                key = row['baslik'].casefold()
                if key not in distinct or order(row) > order(distinct[key]): distinct[key] = row
            return heapq.nlargest(limit, distinct.values(), key=order)
        return dict(path=relative, sha256=hashlib.sha256(raw).hexdigest(), revision=revision,
                    done=distinct_latest(done, 20), done_count=len(done),
                    planned=distinct_latest(planned, 5), planned_count=len(planned))
    except (OSError, ValueError, TypeError, RecursionError):
        omitted.append('inventory:invalid_or_missing')
        return None


def inventory_card(data, budget):
    prefix = 'Daha önce yapılanlar (yeni aday değildir; devam bölümü olarak ayrıca önerilebilir): '
    def line(label, rows, total, limit):
        titles = []; seen = set()
        for row in rows:
            title = row['baslik']
            if title.casefold() in seen: continue
            seen.add(title.casefold())
            if not title: continue
            left = total-len(titles)-1
            tail = f'; +{left}' if left else ''
            head = label+'; '.join(titles)+('; ' if titles else '')
            room = min(100, limit-len(head)-len(tail))
            if room < min(12,len(title)): break
            if len(title)>room: title = title[:room-1]+'…'
            titles.append(title)
        if not titles: return ''
        return label+'; '.join(titles)+(f'; +{total-len(titles)}' if total>len(titles) else '')
    # Keep plans visibly separate and short even when the completed list is long.
    planned = line('Planlananlar: ', data['planned'], data['planned_count'], min(100, budget//4))
    text = line(prefix, data['done'], data['done_count'], budget-len(planned)-bool(planned))
    if data['done_count'] and not text: return ''
    if not text:
        planned = line('Planlananlar: ', data['planned'], data['planned_count'], min(100, budget))
    return text+('\n' if text and planned else '')+planned


def inventory_limit(budget):
    return max(0, int(budget) * 3 // 10)



_VISUAL_TERMS = ('kapak','thumbnail','maskot','logo','banner','görsel','render')

# Full-word forms keep verb roots from matching nouns (yaz != yazıları).
_ACTION_SUFFIXES = ('', 'ın', 'in', 'un', 'ün', 'ınız', 'iniz', 'unuz', 'ünüz',
                    'sana', 'sene', 'alım', 'elim', 'manı', 'meni', 'manızı', 'menizi',
                    'ar', 'er', 'ır', 'ir', 'ur', 'ür', 'yın', 'yin', 'yınız', 'yiniz',
                    'yalım', 'yelim', 'yabilir', 'abilir', 'ebilir', 'ıver', 'iver',
                    'ıverin', 'iverin')
_VISUAL_ROOTS = ('üret', 'hazırla', 'oluştur', 'çiz', 'tasarla', 'yenile',
                 'düzenle', 'değiştir', 'düzelt', 'yap', 'al')
_NONVISUAL_ROOTS = ('araştır', 'incele', 'sil', 'derle', 'yaz', 'kullan')
_NEGATIVE_SUFFIXES = ('ma', 'me', 'mayın', 'meyin', 'mayınız', 'meyiniz',
                      'mamanı', 'memeni', 'mamanızı', 'memenizi', 'mamak', 'memek',
                      'mıyorum', 'miyorum', 'mayalım', 'meyelim')

def action_form(word, roots, suffixes=_ACTION_SUFFIXES):
    return any(word == root + suffix for root in roots for suffix in suffixes)

def positive_visual_action(words):
    return (any(action_form(w, _VISUAL_ROOTS) for w in words) or
            any(w == 'revize' and i+1 < len(words) and
                action_form(words[i+1], ('et', 'ed')) for i, w in enumerate(words)))

def visual_intent(query, previous_user=None):
    """Sentence-local production intent plus bounded noun/continuation requests."""
    intent = task_intent(query)
    words = query_words(intent)
    for clause in re.split(r'[\n.!?;,]+', intent):
        part = query_words(clause)
        negative = (any(action_form(w, _VISUAL_ROOTS + ('iste', 'et'),
                                    _NEGATIVE_SUFFIXES) for w in part) or
                    'istemiyorum' in part)
        if negative:
            continue
        visual = any(inflected(term, word) or one_typo(term, word)
                     for term in _VISUAL_TERMS for word in part)
        if visual and positive_visual_action(part):
            return True
        information = ('hakkında' in part or 'nedir' in part or
                       any(part[i:i+2] == ['bilgi', 'ver'] for i in range(len(part))))
        if visual and len(part) <= 6 and not information and not any(
                action_form(w, _NONVISUAL_ROOTS) or w == 'teşhis' or
                w.startswith(('skill', 'silindi', 'sildi', 'silinmiş')) for w in part):
            return True
        # Existing bare drawing commands remain a concise request for artwork.
        if len(part) <= 4 and any(action_form(w, ('çiz',)) for w in part):
            return True
    if not previous_user or len(words) > 12 or len(intent) > 140:
        return False
    allowed = set(query_words('tamam evet devam et edelim kaldık nerede şimdi '
                             'sonraki adım son durum ne durumda kaldığımız yer '
                             'bunu onu biraz daha parlak koyu açık büyük küçük '
                             'olsun yap yenile düzenle revize renkleri'))
    allowed.update(query_words(task_intent(previous_user)))
    short_followup = (continuation_request(query) or
                      any(w in {'yenile', 'düzenle', 'revize', 'parlak', 'koyu', 'büyük', 'küçük'} for w in words))
    return bool(short_followup and all(w in allowed for w in words) and
                not any(action_form(w, _NONVISUAL_ROOTS) or w in
                        {'senaryo', 'araştırma', 'açıklama', 'etiket', 'altyazı',
                         'üret', 'hazırla', 'oluştur', 'tasarla'} for w in words) and
                visual_intent(previous_user))

def visual_record(row):
    """Gate only explicit catalog identity or cover-design purposes.

    Domains, tags, paths and prose describe context, not a visual-task need.
    """
    for key in ('subject_key', 'kind', 'role'):
        value = row.get(key)
        if not isinstance(value, str):
            continue
        words = set(query_words(value))
        if value == 'identity' or words & {'maskot', 'mascot'}:
            return True
        if (words & {'karakter', 'character'} and
                words & {'kimlik', 'identity'}):
            return True
        if (words & {'kapak', 'thumbnail'} and
                words & {'tasarım', 'tasarımı', 'design', 'choice', 'style',
                         'stil', 'stili', 'renk', 'palette', 'typography'}):
            return True
    return False


def shared_workspace(root, vault=None):
    """A vault is a shared launch directory, including a relocated snapshot's origin.

    Recognize the layout without reading its records or relying on a project ID.
    Descendant project roots are still ordinary, specific workspaces.
    """
    root = Path(root).resolve()
    return ((vault is not None and root == Path(vault).resolve()) or
            ((root / 'komuta/gorev-baglam.json').is_file() and
             (root / 'zihin').is_dir()))


def area_topic(project, words):
    """Expand a configured video production area, never a named video project.

    Generic words remain insufficient to match arbitrary project aliases.
    Multiple eligible areas remain ambiguous rather than picking the first.
    """
    vocabulary = {'video', 'kurgu', 'senaryo', 'thumbnail', 'youtube'}
    aliases = {w for a in project.get('aliases', []) for w in query_words(a)}
    return (project.get('kind') == 'area' and
            bool(aliases & {'video', 'thumbnail'}) and
            not any(w in words for w in ('dünkü', 'o', 'şu', 'önceki')) and
            any(alias_inflected(term, word) for term in vocabulary for word in words))


def implicit_project(projects, cwd, vault):
    # Dizin adı tek başına kanıt değil; yalnız kaynak doğrulamalı kartla kapsam kur.
    if not cwd or vault is None: return None
    root = Path(cwd).resolve(); home = Path.home().resolve()
    if root == home or root == Path(root.anchor) or shared_workspace(root, vault): return None
    # Ev altındaki yolda yalnız evden sonraki bileşenler; ev dışı yolda hepsi denetlenir.
    parts = root.relative_to(home).parts if root.is_relative_to(home) else root.parts
    if any(p.casefold() in {'tmp', 'temp', '.cache'} or
           p.casefold().startswith(('scratch', 'tmp-', 'temp-')) for p in parts): return None
    generic = _GENERIC | {'calisma','çalışma','projects','projeler','scratch','tmp','temp',
                          'home','videolar','youtube','desktop','downloads','documents','share'}
    configured = {str(a).casefold() for p in projects
                  for a in [p.get('id', ''), *p.get('aliases', [])]}
    candidates = {}
    def add(path, priority):
        slug = path.name.casefold()
        if (len(slug) < 4 or slug in generic or slug in configured or slug == home.name.casefold()
                or slug.startswith(('scratch', 'tmp-', 'temp-'))
                or not re.fullmatch(r'[^\W_]+(?:[-_][^\W_]+)*', slug) or slug.isdigit()): return
        candidates[slug] = min(priority, candidates.get(slug, priority))
    add(root, 0)
    # Git süreci başlatma; üst dizin denetimi ve alt dizin taraması sınırlı.
    for parent in [root, *list(root.parents)[:12]]:
        if parent == home: break
        if (parent / '.git').exists():
            add(parent, 1); break
    if root.is_relative_to(home):
        relative = root.relative_to(home).parts
        for depth in range(1, min(2, len(relative))+1):
            add(home.joinpath(*relative[:depth]), 2)
    children = []
    try:
        for count, child in enumerate(root.iterdir()):
            if count >= 32: children = []; break
            if not child.name.startswith('.') and child.is_dir(): children.append(child)
            if len(children) > 8: children = []; break
    except OSError: children = []
    for child in children: add(child, 3)
    if not candidates: return None
    matches = {}
    # Önce defterdeki son satırları süz; ilgisiz kartların kaynaklarını açma.
    for card in latest(Path(vault), 'task').values():
        if (not isinstance(card, dict) or
                any(not isinstance(card.get(key), str) for key in ('id', 'title', 'status')) or
                any(key in card and card[key] is not None and not isinstance(card[key], str)
                    for key in ('source_path', 'evidence', 'project_id', 'next_step'))):
            raise ValueError('invalid implicit task schema')
        for slug in candidates:
            owner = card.get('project_id')
            if owner and owner != slug: continue
            text = str(card.get('source_path', ''))+' '+str(card.get('evidence', ''))
            if (owner == slug or card['id'].casefold().startswith(slug+'-') or
                    re.search(r'(?<![\w-])'+re.escape(slug)+r'(?![\w-])', text.casefold())):
                matches.setdefault(slug, set()).add(card['id'])
    if not matches: return None
    card_ids = set().union(*matches.values())
    cards = brief(Path(vault), limit=10000, include_stale=True, include_pending=True, card_ids=card_ids)
    matches = {slug:[c for c in cards if c['id'] in ids] for slug, ids in matches.items()}
    matches = {slug:cards for slug, cards in matches.items() if cards}
    if not matches: return None
    best = min(candidates[s] for s in matches)
    slugs = [s for s in matches if candidates[s] == best]
    if len(slugs) != 1: return None  # Kardeş projeler arasında sıraya göre seçim yapma.
    slug = slugs[0]
    return dict(id=slug, aliases=[], roots=[str(root)], task_ids=[t['id'] for t in matches[slug]],
                _implicit_tasks=matches[slug])


def select_projects(projects, query, cwd=None, previous_user=None, session_project_id=None, *, vault=None, diagnostics=None):
    intent = task_intent(query)
    # Explicit replacement names the destination; the abandoned project is not scope.
    replacement = re.search(r'\b(?:bırak(?:ıp)?|yerine)\b(.+)', intent, re.I)
    if replacement: intent = replacement.group(1)
    words=query_words(intent)
    deictic=any(w in words for w in ('dünkü','o','şu','önceki'))
    def matches(project,fuzzy=False):
        return any(alias_match(alias,words,fuzzy,ordered=True) and not (deictic and set(query_words(alias)) <= _GENERIC)
                   for alias in [project.get('id', ''), *project.get('aliases',[])])
    # Archived projects answer only an exact alias, never a fuzzy match or cwd.
    # Config uses both Turkish and English status words; both mean archived.
    active=[p for p in projects if p.get('status','aktif') not in ('arsiv', 'arşiv', 'archived')]
    # An area's root may host work about a different configured project.
    # A mixed root name is insufficient area evidence, and "kurgu" alone can
    # mean the structure of technical work. Require a current production topic;
    # never infer the other project's scope from its name in this path either.
    mixed_areas = set()
    if cwd:
        for area in active:
            if area.get('kind') != 'area': continue
            for root in area.get('roots', []):
                if not Path(cwd).resolve().is_relative_to(Path(root).resolve()): continue
                root_words = query_words(Path(root).name)
                if any(alias_match(alias, root_words, ordered=True)
                       for other in projects if other['id'] != area['id']
                       and other.get('kind') != 'area'
                       for alias in [other.get('id', ''), *other.get('aliases', [])]
                       if query_words(alias) and not set(query_words(alias)) <= _GENERIC):
                    mixed_areas.add(area['id'])
    production_topic = any(alias_inflected(term, word)
                           for term in ('video', 'senaryo', 'thumbnail', 'youtube', 'kapak', 'maskot')
                           for word in words)
    explicit=[p for p in projects if matches(p)]
    if not explicit: explicit=[p for p in active if matches(p,True)]
    specific=[p for p in explicit if any(alias_match(a,words,ordered=True) and not set(query_words(a)) <= _GENERIC for a in [p.get('id', ''), *p.get('aliases',[])])]
    if specific: explicit=specific
    located=[p for p in active if cwd and (p['id'] not in mixed_areas or production_topic) and any(
        Path(cwd).resolve().is_relative_to(Path(r).resolve()) and
        (not shared_workspace(r, vault) or any(
            alias_inflected(term, word) for term in project_terms(p) for word in words))
        for r in p.get('roots',[]))]
    # Nested workspaces choose the most specific root, never a sibling by recency.
    if len(located)>1:
        depths={p['id']:max(len(Path(r).resolve().parts) for r in p.get('roots',[]) if Path(cwd).resolve().is_relative_to(Path(r).resolve())) for p in located}
        located=[p for p in located if depths[p['id']]==max(depths.values())]
    # A short continuation may inherit one unambiguous previous scope.
    # Explicit current names, ambiguous matches and cwd always take precedence.
    topical = [p for p in active if area_topic(p, words)
               and (p['id'] not in mixed_areas or production_topic)] if not explicit else []
    if len(topical) == len(located) == 1 and topical[0]['id'] == located[0]['id']:
        topical = []  # The specific workspace already establishes this scope.
    prior=[]
    if (not explicit and not located and not topical and continuation_request(query)
            and len(words) <= 24 and len(intent) <= 240):
        if session_project_id is not None:
            # Only the caller's same-session last delivered scope; no global
            # recency, alias inference, archived scope or ambiguous state.
            prior = [p for p in active if isinstance(session_project_id, str)
                     and p.get('id') == session_project_id]
        elif previous_user:
            prior, _ = select_projects(active, previous_user, vault=vault)
        if len(prior) != 1: prior=[]
    chosen=explicit or topical or located or prior
    reason='explicit' if explicit else ('area_topic' if topical else 'cwd' if located else ('session_project' if session_project_id is not None else 'previous_user') if prior else 'unresolved')
    if not chosen:
        try:
            inferred = implicit_project(projects, cwd, vault)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Only the optional inference path degrades to the former empty scope.
            # Preserve a bounded diagnostic without leaking ledger contents.
            if diagnostics is not None:
                diagnostics.append('implicit_project:'+type(exc).__name__)
            inferred = None
        if inferred: chosen, reason = [inferred], 'cwd-implicit'
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
    return any(alias_match(term, words) for term in ('devam', 'kaldık', 'sonraki adım', 'ne durumda', 'nerede kaldık', 'son durum', 'kaldığımız yer'))


class RevisionMap(dict):
    """A merged read set must never hide two observed versions of one path."""
    conflict = False
    def __init__(self):
        super().__init__()
        self.single_reads = {}
    def __setitem__(self, key, value):
        if key in self and self[key] != value: self.conflict = True
        super().__setitem__(key, value)
    def update(self, other):
        for key, value in other.items(): self[key] = value


def build_task_package(vault, query, cwd=None, budget=5000, history="auto", view="auto", previous_user=None, session_project_id=None):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from jev_client import evaluation_context
    import jev_client
    from is_ve_ders import TASKS, LESSONS
    vault = Path(vault).resolve()
    previous_user = previous_user if isinstance(previous_user, str) else None
    from client_transcripts import private, worker_prompt
    private_previous = bool(previous_user and (h.contains_secret(previous_user) or private(previous_user) or worker_prompt(previous_user)))
    if private_previous:
        previous_user = None
    if h.contains_secret(query) or private(query) or worker_prompt(query):
        session_project_id = None
    ledgers = [h.CATALOG_PATH, h.SOURCE_BINDINGS, TASKS, LESSONS,
               Path('komuta/gorev-baglam.json')]
    def revisions():
        return {str(p): digest(vault/p) if (vault/p).is_file() else None for p in ledgers}
    before = revisions()
    rerank_state = None
    skip_memory = False
    gate = None
    inventory_probe = None
    try: rerank_mode = jev_client.purpose_mode(jev_client.load_config(vault), 'retrieval') == 'rerank'
    except (OSError, ValueError): rerank_mode = False
    with evaluation_context(vault):
        if rerank_mode:
            from client_transcripts import private
            if private_previous or any(h.contains_secret(value) or private(value) for value in (query, previous_user or '')):
                rerank_mode = False
                private_fallback = True
            else:
                private_fallback = False
                projects, _ = select_projects(config(vault).get('projects', []), query, cwd, previous_user, session_project_id, vault=vault)
                project = projects[0] if len(projects) == 1 else None
                project_context = (str(project.get('id', '')) + ': ' + str(project.get('summary', ''))) if project else ''
                if h.contains_secret(project_context) or private(project_context): project_context = ''
                rerank_state = dict(previous_user=(previous_user or '')[:800], project=project_context[:500])
                from jev_retrieval import rerank_gate, recall_settings, gate_rows, strong_lexical_matches
                explicit_recall = bool(re.search(r'\b(?:memory:|note:)|neye\s+karar\s+ver|ne\s+karar\s+vermiştik|hatırla|hatırlat', query, re.I))
                if explicit_recall:
                    needed, gate = True, dict(mode='rerank', requested_mode='rerank', effective_mode='rerank',
                                              degraded=False, diagnostics=['explicit_recall_bypass'], latency_ms=0,
                                              needed=True, effective_needed=True)
                else:
                    with evaluation_context(vault):
                        needed, gate = rerank_gate(vault, query, rerank_state)
                    if not gate.get('degraded') and not needed:
                        min_terms = recall_settings(config(vault))['gate_override_min_terms']
                        if min_terms > 0:
                            matches = strong_lexical_matches(gate_rows(vault, project['id'] if project else None), query, min_terms)
                            if matches:
                                needed = True
                                gate.setdefault('diagnostics', []).append('lexical_override')
                                gate['override_ids'] = matches
                    gate['effective_needed'] = needed
                    if not gate.get('degraded') and not needed:
                        skip_memory = True
                        if jev_client.load_config(vault)['rerank_gate_scope'] == 'all':
                            diagnostics = []
                            inventory = read_inventory(vault, project, query, diagnostics)
                            inventory_probe = (inventory, diagnostics)
                        if (jev_client.load_config(vault)['rerank_gate_scope'] == 'all' and
                            not (inventory_probe[0] and inventory_card(inventory_probe[0], inventory_limit(budget)))):
                            result = dict(text='', selected_ids=[], source_versions={}, assets=[], knowledge=None, delivered_lessons=[], delivered_lesson_segments={}, lessons=dict(applied=[],diagnostics=[]),
                                          omitted_reasons=[], project_id=None, suppressed_count=0, jev={'gate': gate},
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
                    result = _build_task_package(vault, query, cwd, budget, history, view, submit, None, **({'session_project_id': session_project_id} if session_project_id is not None else {}))
                result.setdefault('jev', {})['rerank'] = dict(gate or {}, mode='rerank', degraded=True,
                    diagnostics=(gate or {}).get('diagnostics', []) + (['private_input'] if private_fallback else []))
            else:
                result = _build_task_package(vault, query, cwd, budget, history, view, submit, rerank_state, skip_memory,
                                             previous_user=(previous_user or '')[:800] or None, inventory_probe=inventory_probe, **({'session_project_id': session_project_id} if session_project_id is not None else {}))
                if gate: result.setdefault('jev', {})['gate'] = gate
    changed = before != revisions() or getattr(result.get('source_versions'), 'conflict', False)
    for name, version in result.get('source_versions', {}).items():
        try:
            revision = getattr(result['source_versions'], 'single_reads', {}).get(name)
            if (file_revision(h.source_file(vault,name)) != revision if revision is not None
                else digest(vault/name) != version): changed = True
        except (OSError, ValueError): changed = True
    if changed:
        # Never relabel an old claim with a freshly computed source hash.
        text = 'Bağlam hazırlanırken kaynak değişti; güncel kaynağı yeniden doğrula.'
        result.update(text=text[:max(0,int(budget))], selected_ids=[], assets=[],
                      source_versions={}, delivered_segments={}, delivered_lessons=[], delivered_lesson_segments={}, knowledge=None, decision_history=None, reuse=None, suppressed_count=0, lessons=dict(applied=[],diagnostics=[]))
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


def _build_task_package(vault, query, cwd, budget, history, view, submit, rerank_state=None, skip_memory=False, previous_user=None, session_project_id=None, inventory_probe=None):
    if history not in ("auto", "always", "never"): raise ValueError("invalid history mode")
    if view not in ("auto", "standard", "resume"): raise ValueError("invalid view")
    query = task_intent(query)
    visual = visual_intent(query, previous_user)
    resume = view == "resume" or (view == "auto" and continuation_request(query))
    resume_tasks = []; card_facts = []; task_duplicates = {}
    vault = Path(vault).resolve(); words = tokens(query)
    selected=[]; omitted=[]; lines=[]; used=0; assets=[]; source_versions=RevisionMap()
    budget=max(0, int(budget)); candidates=[]; current_facts=[]; current_tasks=[]
    compact = budget <= 2000
    source_references = {}
    def source_reference(row, ledger):
        path = row['source_path']
        ident = row.get('memory_id', row.get('id'))
        reference = ledger+'#'+ident
        if compact and len(reference) < len(path):
            source_references[reference] = dict(path=path, sha256=digest(h.source_file(vault, path)))
            return reference
        return path
    projects=[]
    cfg=config(vault)
    if cfg.get('invalid'): omitted.append('config_invalid')
    projects, match_reason = select_projects(cfg.get('projects', []), query, cwd, previous_user, session_project_id, vault=vault, diagnostics=omitted)
    project = projects[0] if len(projects)==1 else None
    if inventory_probe is None:
        inventory = read_inventory(vault, project, query, omitted)
    else:
        inventory, inventory_diagnostics = inventory_probe
        omitted.extend(inventory_diagnostics)
    if project and match_reason == 'area_topic':
        # An area's production topic does not request its cover identity kit.
        project = dict(project, assets=[], working_sources=[])
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
    project_tasks = []
    if project:
        def belongs_to_project(task):
            belongs = task.get('project_id')==project['id'] or task['id'] in project.get('task_ids',[])
            if not task.get('project_id') and not belongs:
                # Legacy cards have no project_id. Only a unique specific title
                # alias can restore scope; generic video/thumbnail aliases cannot.
                title_projects = [p for p in cfg.get('projects', [])
                                  if any(not set(query_words(a)) <= _GENERIC and alias_match(a, query_words(task['title']))
                                         for a in p.get('aliases', []) if query_words(a))]
                if not title_projects and match_reason == 'area_topic':
                    title_projects = [p for p in cfg.get('projects', [])
                                      if p.get('status', 'active') not in ('arsiv', 'arşiv', 'archived')
                                      and area_topic(p, query_words(task['title']))]
                belongs = len(title_projects)==1 and title_projects[0]['id']==project['id']
            return belongs
        diagnostics = []
        cards = (project['_implicit_tasks'] if match_reason == 'cwd-implicit' else
                 brief(vault,limit=10000,include_stale=True,diagnostics=diagnostics,
                       include_pending=bool(_subtask_parts(project, cwd))))
        for task in cards:
            if belongs_to_project(task):
                # Confirmation cards may legitimately omit the next action.
                project_tasks.append(dict(task, next_step=task.get('next_step') or
                                          'Kaydedilmiş sonraki adım yok; teyit gerekli.'))
        omitted.extend(item['id']+':'+item['reason'] for item in diagnostics
                       if belongs_to_project(item))
    task_focus = {}
    if project:
        project_tasks, task_focus, focus_omitted = subtask_focus(project_tasks, project, cwd)
        omitted.extend(focus_omitted)
    task_rows = [dict(t, statement=t['title']+' '+t['next_step'], memory_id=t['id'])
                 for t in project_tasks]
    expansion_tasks = rank_records(task_rows, query, ignore=project_terms(project) if project else (), context=previous_user)
    if task_focus and task_rows:
        order = {t['id']: index for index,t in enumerate(expansion_tasks)}
        expansion_tasks = [min(task_rows, key=lambda t: (_task_focus_order(t, task_focus), order.get(t['id'], len(order))))]
    if not expansion_tasks:
        if project and _subtask_parts(project, cwd) == ():
            expansion_tasks = _root_state_tasks(task_rows, project)[:1]
        else: expansion_tasks = task_rows[:1]
    expansion_parts = []; linked_paths = []
    if project and len(content_words(query)) <= 24:
        expansion_parts = [project.get('id', ''), project.get('summary', ''), area_expansion(query)]
        expansion_parts += [a for a in project.get('aliases', []) if alias_match(a, query_words(query))]
        for task in expansion_tasks[:1]:
            source = h.source_file(vault, task['source_path'])
            version = digest(source)
            if (task.get('source_content_hash') and
                    task['source_content_hash'] == h.statement_hash(source.read_text())):
                expansion_parts += [task['title'], task['next_step']]
                source_versions[task['source_path']] = version
                linked_paths.append(task['source_path'])
        if previous_user:
            prior, _ = select_projects(cfg.get('projects', []), previous_user, vault=vault)
            if len(prior) == 1 and prior[0]['id'] == project['id']:
                expansion_parts.append(previous_user)
    from client_transcripts import private
    expansion = ' '.join(part for part in expansion_parts if isinstance(part, str)
                         and not h.contains_secret(part) and not private(part))
    knowledge_data = None
    knowledge_future = None
    from jev_procedures import route as route_procedures
    procedure_future = submit(route_procedures, vault, query, budget=min(1000,budget))
    if rerank_state is None and (vault / 'bilgi').is_dir() and len(projects)<=1:
        from konu_sentezi import retrieve as read_knowledge
        # A broad area word establishes routing, not a particular episode's
        # decisions. Require the note's own topic evidence for this fallback.
        knowledge_future=submit(read_knowledge,vault,query,project_id=project['id'] if project and match_reason != 'area_topic' else None,budget=min(1800,budget),
                                context=previous_user, expansion=expansion, linked_paths=linked_paths,
                                routed_project_id=project['id'] if project and match_reason == 'area_topic' else None)
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
    delivery_costs = {}
    def add(ident, text):
        priority = {'subtask-empty':-2, 'unresolved_reference':0, 'ambiguous_project':0, 'project':1,
                    'unresolved':2, 'methods':3, 'input-check':3, 'workflow':4,
                    'working-source':8, 'working-root':8, 'summary-policy':6, 'capsule-status':6, 'suppressed-history':6, 'decision-history':4, 'knowledge':0.5, 'reuse':5, 'procedure-reading':5}.get(ident, 10)
        for asset in (project or {}).get('assets', []):
            if ident == asset.get('id'):
                priority = 0.25 if visual and asset.get('role') == 'identity' else 2
                break
        if ident in task_ids: priority=-2
        if ident.startswith('output:'): priority=5
        candidates.append((priority, len(candidates), ident, text))
        return True
    task_ids=set()
    if inventory: candidates.append((-3,len(candidates),'inventory',''))
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
    suppressed_count=0
    context_scopes=[scope]+['project:'+w['id'] for w in workflows]
    today=dt.datetime.now(dt.timezone.utc).date().isoformat()
    for row in h.load_catalog(vault):
        if decision_data and row.get('memory_id') in decision_data['considered_ids']: continue
        if not any(h.retrievable(row,context_scope) for context_scope in context_scopes):
            if row.get('sensitivity','normal') == 'normal' and row.get('scope') in ['user']+context_scopes:
                stale=row.get('status') == 'superseded'
                if row.get('status') == 'active' and row.get('valid_to'):
                    try:
                        stale=dt.date.fromisoformat(str(row['valid_to'])[:10]).isoformat() <= today
                    except ValueError:
                        pass
                if stale and rank_records([row], query): suppressed_count+=1
            continue
        if row.get('memory_id') in overrides:
            if rank_records([row], query): omitted.append(row['memory_id']+':'+overrides[row['memory_id']])
            continue
        if h.context_record_errors(vault,row):
            if rank_records([row], query): omitted.append(str(row.get('memory_id') or 'unknown')+':invalid')
            continue
        if not visual and visual_record(row):
            omitted.append(str(row.get('memory_id') or 'unknown')+':visual_intent_required')
            continue
        eligible.append(row)
        eligible_versions[row['source_path']]=digest(h.source_file(vault,row['source_path']))
    # A gate that skipped memory must not reintroduce a memory hint.
    if skip_memory: suppressed_count=0
    if suppressed_count:
        add('suppressed-history',f'{suppressed_count} eski kayıt bastırıldı; tarihçe için karar_gecmisi.')
    # Out-of-scope, stale and replaced rows must not influence corpus rarity.
    if skip_memory:
        ranked_catalog, knowledge_data, catalog_evaluation = [], None, None
    elif rerank_state is None:
        from jev_retrieval import catalog as semantic_catalog
        # Local ranking only; a semantic advisor keeps its own inputs.
        local_rank = functools.partial(rank_records, ignore=project_terms(project) if project else (),
                                       context=previous_user, expansion=area_expansion(query),
                                       tie_break=lambda row: (row.get('scope') != scope, row.get('memory_id', '')))
        catalog_future = submit(semantic_catalog, vault, query, eligible, local_rank, scope)
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
    from jev_retrieval import static_preferences, recall_settings
    ranked_catalog = ranked_catalog + static_preferences(
        eligible, ranked_catalog, recall_settings(cfg), rerank_state is not None, query)
    procedure_data = procedure_future.result()
    if knowledge_future: knowledge_data = knowledge_future.result()
    unguarded_knowledge = knowledge_data
    knowledge_data = _guard_knowledge(knowledge_data, project, query, cwd)
    if knowledge_data:
        omitted.extend(i+':other_subtask_decision' for i in knowledge_data.get('guarded_record_ids', []))
    if procedure_data['text']: add('procedure-reading', procedure_data['text'])
    def still_current(row):
        try:
            return (not h.context_record_errors(vault,row) and
                    digest(h.source_file(vault,row['source_path'])) == eligible_versions[row['source_path']])
        except (OSError,ValueError): return False
    ranked_catalog=[row for row in ranked_catalog if still_current(row)]
    catalog_indices = {row['memory_id']: i for i, row in enumerate(ranked_catalog)}
    unguarded_catalog = ranked_catalog
    foreign_catalog = {row['memory_id'] for row in eligible if _subtask_claim(row, project, query, cwd)}
    omitted.extend(i+':other_subtask_decision' for i in sorted(foreign_catalog)
                   if i in {r['memory_id'] for r in ranked_catalog})
    ranked_catalog = [r for r in ranked_catalog if r['memory_id'] not in foreign_catalog]
    profile_rows = [] if skip_memory else scope_profile(
        eligible, project, cfg.get('projects', []))
    # Scope identifies whose preferences apply; the active work domain decides
    # which of them deserve unsolicited space. A vague continuation does not
    # activate every preference of a project.
    profile_topic = content_words(area_expansion(query))
    profile_rows = [row for row in profile_rows if still_current(row) and
                    any(word_match(t, w) for t in profile_topic
                        for w in content_words(search_text(row)))]
    omitted.extend(row['memory_id']+':other_subtask_decision' for row in profile_rows
                   if row['memory_id'] in foreign_catalog and row['memory_id']+':other_subtask_decision' not in omitted)
    profile_rows = [row for row in profile_rows if row['memory_id'] not in foreign_catalog]
    ranked_ids = {row['memory_id'] for row in ranked_catalog}
    profile_ids = set()
    profile_used = 0
    # A reserved, bounded share; complete claims only, no truncated conditions.
    profile_budget = min(480, budget // 4)
    for row in profile_rows:
        if row['memory_id'] in ranked_ids: continue
        content = h.source_file(vault, row['source_path']).read_text()
        details = ''.join(' '+label+': '+row[key] for key,label in
                          (('rationale','Gerekçe'),('conditions','Geçerlilik koşulu'))
                          if isinstance(row.get(key),str) and row[key] in content)
        text = ('Kapsam profili: '+row['statement']+details+
                ' (kaynak: '+source_reference(row, 'zihin/hafıza-kataloğu.jsonl')+')')
        original_cost = len(text)
        if profile_used + max(original_cost, len(text)) + 1 > profile_budget: continue
        profile_used += max(original_cost, len(text)) + 1
        profile_ids.add(row['memory_id'])
        add(row['memory_id'], text)
        priority, sequence, ident, text = candidates[-1]
        candidates[-1] = (0.6, sequence, ident, text)
        current_facts.append(row)
        source_versions[row['source_path']] = eligible_versions[row['source_path']]
    if catalog_evaluation and catalog_evaluation.get('suggested_ids'):
        suggested=set(catalog_evaluation['suggested_ids'])
        for row in eligible:
            if row['memory_id'] not in suggested or not still_current(row): continue
            if row['memory_id'] in foreign_catalog:
                reason = row['memory_id']+':other_subtask_decision'
                if reason not in omitted: omitted.append(reason)
                continue
            add('jev-reading:'+row['memory_id'], 'Jev kaynak adayı (okumadan tercih/onay sayma): '+row['subject_key']+' — '+str(vault/row['source_path']))
            source_versions[row['source_path']]=eligible_versions[row['source_path']]

    for rank_index, row in enumerate(ranked_catalog):
        rank_index = catalog_indices[row['memory_id']]
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
        text = prefix+row['statement']+details+' (kaynak: '+source_reference(row, 'zihin/hafıza-kataloğu.jsonl')+'; kapsam: '+row.get('scope','bilinmiyor')+('' if compact and source_reference(row, 'zihin/hafıza-kataloğu.jsonl') != row['source_path'] else '; sınıf: '+h.context_source_class(row))+')'
        original_cost = len(text)
        delivery_costs[(row['memory_id'], text)] = max(original_cost, len(text))
        if add(row['memory_id'],text):
            current_facts.append(row)
            priority,sequence,ident,text=candidates[-1]
            # Alternate catalog cards and note cards at the same priority.
            # A whole note dossier must not exhaust the record budget first.
            candidates[-1]=(0.5,2*rank_index,ident,text)
            source_versions[row['source_path']]=eligible_versions[row['source_path']]
    if project:
        add('project', 'Proje: '+project['id'])
        if workflows: add('workflow', 'Bu projedeki üretim yöntemi: '+', '.join(w['id'] for w in workflows)+'. Yöntem referansları proje seçimini değiştirmez.')
        for issue in project.get('unresolved',[]): add('unresolved', 'Teyit gerekli: '+issue)
        for ref in project.get('working_sources',[]):
            if not visual and visual_record({'role': ref.get('role')}):
                omitted.append('working-source:visual_intent_required'); continue
            path=Path(ref['path']).resolve()
            if path.is_file():
                source_versions[str(path)]=digest(path)
                add('working-source',ref['role']+': '+str(path)+'; kaynak: '+ref['evidence_source']+'. Gerektikçe aç; varlık ≠ kabul.')
            else: omitted.append(str(path)+':missing')
        roots = project.get('roots', [])
        if roots:
            matching = [r for r in roots if cwd and Path(cwd).resolve().is_relative_to(Path(r).resolve())]
            working_root = max(matching, key=lambda r: len(Path(r).resolve().parts)) if matching else roots[0]
            root_check = ('; canlı Git HEAD/status ve testleri doğrula.' if compact else
                          '; işlem öncesi canlı Git HEAD/status ve testleri doğrula.')
            add('working-root','Çalışma kökü: '+working_root+root_check)
            if len(roots)>1:
                label = 'kök' if compact else 'alternatif kök'
                add('alternative-roots',f'+{len(roots)-1} {label}: komuta/gorev-baglam.json')
        topical_tasks = rank_records([dict(t, statement=t['title']+' '+t['next_step'], memory_id=t['id'])
                                      for t in project_tasks], query, ignore=project_terms(project), context=previous_user)
        topical_ids = [t['id'] for t in topical_tasks]
        parts = _subtask_parts(project, cwd)
        if parts and not project_tasks:
            add('subtask-empty', 'Bu alt iş ('+parts[0]+') için kayıtlı iş kartı yok.')
        # Kök dizinde konu yoksa kardeş işlerden rastgele kart seçme.
        topic_words = project_terms(project) | _GENERIC
        direct_query = ' '.join(w for w in query_words(query)
                                if not any(word_match(w,t) for t in topic_words))
        direct = rank_records(task_rows, direct_query)
        if parts == () and not direct and match_reason != 'cwd-implicit':
            fallback = _root_state_tasks(project_tasks, project)
            if previous_user:
                prior_words = {w for w in content_words(previous_user)
                               if not any(word_match(w,t) for t in topic_words)}
                prior = rank_records([t for t in task_rows if not _project_state(t, project) and
                                      any(word_match(w,word) for w in prior_words
                                          for word in content_words(t['title']))],
                                     ' '.join(prior_words))
                if prior:
                    prior_focus = {t['id']:(0,0,0) for t in prior}
                    fallback.append(min(prior, key=lambda t: _task_focus_order(t, prior_focus)))
            allowed = {t['id'] for t in fallback}
            omitted.extend(t['id']+':root_fallback' for t in project_tasks if t['id'] not in allowed)
            project_tasks = fallback
            topical_ids = []
        # A topic that matches every card distinguishes none; keep recency.
        if len(topical_ids) == len(project_tasks): topical_ids = []
        # Within subtask focus, dated freshness precedes lexical/query strength.
        # Outside it, the existing topical and verified-recency order remains.
        topical_order = {ident: index for index,ident in enumerate(topical_ids)}
        project_tasks.sort(key=lambda t: (_task_focus_order(t, task_focus),
                                         t['id'] not in topical_order, topical_order.get(t['id'], 0)))
        # Routing uncertainty forbids choosing a single next action; it need not
        # hide a third source-backed alternative that fits the same budget.
        card_limit = 3
        from client_sessions import unique_states, state_values
        # Verify every source before allowing it to displace another card.
        valid_tasks = []
        for task in project_tasks:
            source = h.source_file(vault, task['source_path'])
            if task.get('source_content_hash') and task['source_content_hash'] != h.statement_hash(source.read_text()):
                omitted.append(task['id']+':source_changed')
            else:
                valid_tasks.append(task)
        groups = unique_states([t for t in valid_tasks if t.get('source_content_hash')])
        groups.extend([t] for t in valid_tasks if not t.get('source_content_hash'))
        groups.sort(key=lambda group: min(project_tasks.index(t) for t in group))
        visible_count = 0
        for group in groups:
            task = group[0]
            task_ids.add(task['id'])
            source=h.source_file(vault,task['source_path'])
            pinned=task.get('source_content_hash')==h.statement_hash(source.read_text())
            if task.get('source_content_hash') and not pinned:
                omitted.append(task['id']+':source_changed'); continue
            stale = task.get('confirmation_required', False)
            if pinned and not stale: resume_tasks.append(task)
            if visible_count >= card_limit:
                omitted.append(task['id']+':card_limit'); continue
            visible_count += 1
            if pinned and not stale: current_tasks.append(task)
            source_versions[task['source_path']]=digest(source)
            date = task.get('last_verified') or (str(task.get('content_updated_at', task.get('updated_at', '')))[:10]
                   if task.get('verification_missing') else '') or 'tarih yok'
            report = task.get('assistant_report') if task.get('assertion_kind') == 'assistant_report' else None
            state_label = ('oturum kapanış bildirimi ('+date+', doğrulanmış sonuç değil)' if report else
                           'son bilinen durum ('+date+', teyit kaydı yok)' if task.get('verification_missing') else
                           'son bilinen durum ('+date+', teyit gerekli)' if stale else
                           'engelli' if task['status']=='blocked' else 'devam edilebilir')
            prefix = ('Kaynağı yeniden doğrulanacak iş:' if not pinned else
                      'Devam kartı' if resume else 'İş durum kartı')
            report_fields = dict(last_result=report.get('outcome'),
                                 open_work='; '.join(report.get('open_items') or [])) if isinstance(report, dict) else {}
            def field(name, fallback):
                value = task.get(name) or report_fields.get(name)
                return value if isinstance(value, str) and value and not h.contains_secret(value) else fallback
            text = prefix+' ['+state_label+']: '+task['title']
            # Preserve recorded facts; repeated title and absent fields add no evidence.
            optional_fields = (('Hedef', field('goal', '')),
                                 ('Son sonuç', field('last_result', '')),
                                 ('Açık iş/engel', field('blocker', field('open_work', ''))))
            for label, value in optional_fields:
                if value and not (compact and sum(len(v) for _, v in optional_fields) > 200): text += '; '+label+': '+value
            text += ('; Sonraki adım: '+task['next_step']+'; Tarih: '+date+
                     ' (kaynak: '+source_reference(task, 'zihin/is-durumu.jsonl')+')')
            values = state_values(task)
            duplicates = []
            for older in group[1:]:
                extra = [v for v in state_values(older) if v not in values]
                if extra:
                    text += '; Ek alan: ' + '; '.join(extra) + ' (kaynak: '+older['source_path']+')'
                    values.extend(extra)
                source_versions[older['source_path']] = digest(h.source_file(vault, older['source_path']))
                duplicates.append(older['id'])
            task_duplicates[task['id']] = duplicates
            add(task['id'],text)
            # One relevant primary card comes first; notes precede additional
            # cards and unrelated recency hints, so a long card cannot starve notes.
            primary = visible_count==1 and (resume or bool(task_focus) or bool(topical_ids) or not unguarded_knowledge or not unguarded_knowledge['text'])
            priority,sequence,ident,text=candidates[-1]
            candidates[-1]=(-2 if primary else 2,sequence,ident,text)
        identity_assets = [a for a in project.get('assets', []) if a.get('role') == 'identity']
        if not visual and identity_assets:
            add('visual-assets', 'Görsel varlıklar: '+str(len(identity_assets))+' adet, gerektiğinde.')
        for asset in project.get('assets', []):
            if not visual and asset.get('role') == 'identity':
                continue
            try: path=validate_asset(asset)
            except (ValueError,OSError,KeyError) as e: omitted.append(asset.get('id','asset')+':'+str(e)); continue
            if add(asset['id'], 'Onaylı '+asset['role']+': '+str(path)+'; hash: '+asset['sha256']+'. Gerçek araç girdisini validate_inputs ile doğrula; dosyanın bulunması kullanıldığını kanıtlamaz.'): assets.append(asset)
    if decision_data and decision_data['text']:
        add('decision-history',decision_data['text'])
        source_versions.update(decision_data['source_versions'])
    if knowledge_data and knowledge_data['text']:
        # Local notes are independently source-backed paragraphs. Admit complete
        # cards individually rather than dropping the whole dossier when one
        # task consumes part of the budget. Transfers/syntheses keep their notices.
        separate_notes = (knowledge_data['text'].startswith('Bilgi [') and
                          not knowledge_data.get('transfers') and not knowledge_data.get('topics'))
        for note_index, card in enumerate(re.split(r'\n\n(?=Bilgi \[)', knowledge_data['text']) if separate_notes else [knowledge_data['text']]):
            # Keep the pre-filter interleave with catalog cards. Removing an
            # earlier note must not promote later notes ahead of preferences.
            if separate_notes: note_index = knowledge_data.get('card_indices', {}).get(card, note_index)
            # Tam kartlar seçim bütçesine birlikte sığmalı.
            cost = knowledge_data.get('delivery_costs', {}).get(card, len(card))
            if not separate_notes: cost = max(cost, len(knowledge_data.get('original_text', card)))
            delivery_costs[('knowledge', card)] = max(cost, len(card))
            add('knowledge',card)
            priority, _, ident, text = candidates[-1]
            candidates[-1] = (priority, 2*note_index+1, ident, text)
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
    from ders_baglam import context_details
    lesson_details=context_details(vault,query,budget=min(300, budget), project_id=project['id'] if project else None, workflow_ids=[w['id'] for w in workflows], compact=True)
    methods=lesson_details['text']
    lesson_reserve=len(methods)+1 if methods else 0
    if methods: add('methods',methods)
    lesson_diagnostics=lesson_details.get('diagnostics',[])
    if lesson_diagnostics:
        groups=(('değişmiş kaynak/yöntem/doğrulama',{'source_changed','method_changed','verification_changed'}),
                ('eksik yöntem',{'method_missing'}),('eski kayıt',{'legacy_unreviewed'}),
                ('kullanıcı kabulü bekleyen talimat',{'instruction_target_unaccepted'}),
                ('inceleme gerekli',{'review_required'}),('bütçe',{'budget'}))
        counts=[(label,sum(d['reason'] in reasons for d in lesson_diagnostics)) for label,reasons in groups]
        detail=', '.join(label+': '+str(count) for label,count in counts if count)
        # Lowest priority: visibility must never displace real content.
        candidates.append((20,len(candidates),'lesson-check',f"Ders kontrolü: {len(lesson_diagnostics)} ilgili ders dışlandı ({detail}); geçersiz ders uygulanmadı, yeniden kontrol için lesson_backlog'a bak."))
    # Current records are a derived view, never a new canonical statement.
    # Project names and continuation words alone do not prove topic coverage.
    continuation=resume or continuation_request(query)
    def history_phrase(term):
        parts=query_words(term)
        return any(all(inflected(part,word) for part,word in zip(parts,qwords[i:i+len(parts)]))
                   for i in range(len(qwords)-len(parts)+1))
    explicit_history=any(history_phrase(term) for term in
                         ('geçmiş','dün','dünkü','hatırla','neden seçtik','eski karar','önceki karar','önceki oturum'))
    topic=content_words(query)-set(query_words('devam kaldık nerede şimdi ne durumda son durum kaldığımız yer sonraki adım edelim iş işine önceki ders dersini uygulayarak bu ayki teslim kontrol plan planını yaz hazırla yap çıkar oluştur'))
    if project:
        for alias in project.get('aliases',[]):
            topic={t for t in topic if not any(word_match(t,a) for a in query_words(alias))}
    # Only candidates that fit the actual bounded package can satisfy coverage.
    preview_ids=set(); preview_used=0
    for _,_,ident,text in sorted(candidates):
        cost=delivery_costs.get((ident,text), len(text))+(1 if preview_ids else 0)
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
    if project and covered and not use_history and not profile_ids:
        add('summary-policy', 'Belirsizlikte/işlemde kaynağı doğrula; hash ≠ doğruluk.' if compact and source_references else 'Kaynaklı özet yeterliyse yeniden okuma. Hash ≠ doğruluk; yeni talep öncelikli. Belirsizlikte/işlemde kaynağı doğrula.')
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
    # Failed optional inference reports diagnostics without adding a context card
    # to a selection that previously stayed empty.
    errors=[reason for reason in omitted
            if not reason.endswith((':budget', ':card_limit', ':subtask_focus', ':root_fallback', ':visual_intent_required', ':other_subtask_decision'))
            and not reason.startswith(('implicit_project:', 'inventory:'))]
    if errors:
        detail='Bağlam kontrolü: '+ '; '.join(errors)+'. Eksik veya değişmiş kaynağı onaylı sayma.'
        if len(detail)>min(600,budget): detail='Bağlam kontrolü: Geçersiz veya değişmiş kaynaklar dışlandı; omitted_reasons alanını incele.'
        candidates.append((0,-1,'context-check',detail))
    # Reserve the surviving cards that fit before subtask filtering. A newly
    # affordable long card must not consume a later general preference's room.
    original_candidates = list(candidates)
    if foreign_catalog:
        for row in unguarded_catalog:
            if row['memory_id'] not in foreign_catalog: continue
            content = h.source_file(vault, row['source_path']).read_text()
            pinned = (row.get('source_content_hash') == h.statement_hash(content)
                      or h.current_source_binding(vault, row, content))
            details = ''.join(' '+label+': '+row[key] for key,label in (('rationale','Gerekçe'),('conditions','Geçerlilik koşulu')) if isinstance(row.get(key),str) and row[key] in content and not h.contains_secret(row[key]))
            text = ('Bilgi kartı: ' if resume and pinned else 'Güncel kayıt: ')+row['statement']+details+' (kaynak: '+source_reference(row, 'zihin/hafıza-kataloğu.jsonl')+'; kapsam: '+row.get('scope','bilinmiyor')+('' if compact and source_reference(row, 'zihin/hafıza-kataloğu.jsonl') != row['source_path'] else '; sınıf: '+h.context_source_class(row))+')'
            original_candidates.append((0.5,2*catalog_indices[row['memory_id']],row['memory_id'],text))
    if unguarded_knowledge and knowledge_data and knowledge_data.get('guarded_record_ids'):
        original_candidates = [c for c in original_candidates if c[2] != 'knowledge']
        separate = (unguarded_knowledge['text'].startswith('Bilgi [') and
                    not unguarded_knowledge.get('transfers') and not unguarded_knowledge.get('topics'))
        for i, card in enumerate(re.split(r'\n\n(?=Bilgi \[)', unguarded_knowledge['text']) if separate else [unguarded_knowledge['text']]):
            original_candidates.append((0.5,2*i+1,'knowledge',card))
    original_selected = set(); original_used = 0; original_reserve = lesson_reserve
    for candidate in sorted(original_candidates):
        _, _, ident, text = candidate
        cost = len(text)+(1 if original_selected else 0)
        limit = budget if ident == 'methods' else budget-original_reserve
        if original_used+cost > limit: continue
        original_selected.add(candidate[:3]); original_used += cost
        if ident == 'methods': original_reserve = 0
    # Keep a scope header that fit before filtering with the surviving memory
    # cards, before admitting newly affordable cards. Knowledge-channel context
    # may remain even when the catalog card that triggered the header is gone.
    header = h.context_scope_header(scope, ['project:'+w['id'] for w in workflows])
    original_fact_ids = {row['memory_id'] for row in unguarded_catalog} | profile_ids
    surviving_fact_ids = {row['memory_id'] for row in current_facts}
    header_reserve = (len(header)+1 if
                      any(c[2] in original_fact_ids for c in original_selected)
                      and any(c[2] in surviving_fact_ids or c[2] == 'knowledge' for c in candidates)
                      and original_used+len(header)+1 <= budget else 0)
    admitted = []
    for candidate in sorted(candidates, key=lambda c: (c[:3] not in original_selected, c)):
        _, _, ident, text = candidate
        if ident == 'inventory':
            text = inventory_card(inventory, min(inventory_limit(budget), max(0,budget-lesson_reserve-header_reserve-used-bool(admitted))))
            if not text:
                omitted.append('inventory:budget'); continue
            candidate = candidate[:3]+(text,)
        cost=delivery_costs.get((ident,text), len(text))+(1 if admitted else 0)
        limit=budget-header_reserve if ident=='methods' else budget-lesson_reserve-header_reserve
        if used+cost>limit:
            omitted.append(ident+':budget'); continue
        if ident=='methods': lesson_reserve=0
        admitted.append(candidate);used+=cost
    delivered_segments={}
    for _, _, ident, text in sorted(admitted):
        lines.append(text);selected.append(ident)
        if ident == 'inventory':
            source_versions[inventory['path']] = inventory['sha256']
            source_versions.single_reads[inventory['path']] = inventory['revision']
        selected.extend(task_duplicates.get(ident, []))
        # One channel may deliver several roots or working sources.
        if ident in delivered_segments:
            delivered_segments[ident] += '\n' + text
        else:
            delivered_segments[ident] = text
    remaining_active = sum(t['id'] not in selected for t in resume_tasks)
    if remaining_active:
        text = f'{remaining_active} aktif iş daha; hedef işi seçmek için iş defterini aç.'
        if used+len(text)+(1 if lines else 0)<=budget-header_reserve:
            lines.append(text); selected.append('other-active-tasks')
            delivered_segments['other-active-tasks']=text
            used+=len(text)+(1 if len(lines)>1 else 0)
        else: omitted.append('other-active-tasks:budget')
    if (header_reserve and 'knowledge' in selected) or 'suppressed-history' in selected or any(row['memory_id'] in selected for row in current_facts):
        header = h.context_scope_header(scope, ['project:'+w['id'] for w in workflows])
        if used + len(header) + 1 <= budget:
            lines.insert(0, header)
            selected.insert(0, 'scope-header')
            delivered_segments['scope-header'] = header
            used += len(header) + 1
        else:
            omitted.append('scope-header:budget')
    assets=[asset for asset in assets if asset['id'] in selected]
    result={'workflow_ids':[w['id'] for w in workflows],'match_reason':match_reason,'project_id':project['id'] if project else None,'assets':assets,'source_versions':source_versions,'selected_ids':selected,'omitted_reasons':omitted,'text':'\n'.join(lines),'delivered_segments':delivered_segments}
    result['project_source'] = match_reason
    result['source_references'] = {ref: data for ref, data in source_references.items()
                                   if ref in result['text']}
    result['deduplicated_tasks'] = {ident: ids for ident, ids in task_duplicates.items() if ids and ident in selected}
    result['suppressed_count']=suppressed_count
    delivered_lessons=[dict(id=r['id'],version=r['version']) for r in lesson_details['lessons']] if 'methods' in selected else []
    if methods and 'methods' not in selected:
        lesson_diagnostics.extend(dict(id=r['id'],reason='budget') for r in lesson_details['lessons'])
    result['delivered_lessons']=delivered_lessons
    result['delivered_lesson_segments']={r['id']:lesson_details['blocks'][r['id']]['text'] for r in delivered_lessons}
    # Compatibility alias only: delivery is neither application nor success.
    result['lessons']=dict(applied=delivered_lessons,diagnostics=lesson_diagnostics)
    for r in delivered_lessons:
        for path in lesson_details['blocks'][r['id']]['paths']:
            source_versions[path]=digest(h.source_file(vault,path))
    if knowledge_data and 'knowledge' in selected:
        delivered = delivered_segments['knowledge']
        if separate_notes:
            records = [r for r in knowledge_data['records'] if r['statement'] in delivered
                       and 'Kaynak: bilgi/'+r['id']+'.md' in delivered]
            paths = {'bilgi/'+r['id']+'.md' for r in records}
            paths.update(p for r in records for p in _source_paths(r))
            paths.update(e['path'] for r in records for e in r.get('examples', []))
            knowledge_data = dict(knowledge_data, records=records, text=delivered,
                                  source_versions={p:v for p,v in knowledge_data['source_versions'].items() if p in paths},
                                  omitted_record_ids=sorted(set(knowledge_data.get('omitted_record_ids', [])) |
                                      {r['id'] for r in knowledge_data['records'] if r not in records}))
        source_versions.update(knowledge_data.get('source_versions',{}))
    if 'procedure-reading' in selected:
        source_versions.update(procedure_data['source_versions'])
    result['procedure_reading'] = dict(paths=procedure_data['paths'] if 'procedure-reading' in selected else [], delivered='procedure-reading' in selected, advisory=True, diagnostics=procedure_data.get('diagnostics',[]))
    if knowledge_data:
        knowledge_data = {k:v for k,v in knowledge_data.items() if k not in ('original_text', 'delivery_costs', 'card_indices')}
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
