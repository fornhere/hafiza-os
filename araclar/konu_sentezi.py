"""Read-time, source-backed topic dossiers; never inferred user preferences.

Grouping uses existing domain/scope/kind metadata, not an LLM. Opposing claims
remain separate evidence; ordering does not resolve conflicts or imply recency.
Exports are managed read-only snapshots, never runtime retrieval caches or canonical facts.
"""
import argparse
import hashlib
import re
import json
from pathlib import Path
import bilgi_agi as knowledge

KINDS = {'preference': 'tercihler', 'decision': 'kararlar',
         'lesson': 'dersler', 'example': 'örnekler'}
TOPIC_DEFINITIONS = (
    {'id': 'anlatim', 'title': 'Anlatım tercihleri',
     'aliases': ['anlatım', 'anlatı', 'konuşma', 'sunum', 'slayt'],
     'selectors': ['anlatım', 'anlatı', 'konuşma', 'akış', 'metin', 'cümle', 'hikâye', 'altyapı', 'ayrıntı']},
    {'id': 'gorsel-tasarim', 'title': 'Görsel tasarım tercihleri',
     'aliases': ['tasarım', 'görsel', 'tipografi', 'kapak', 'thumbnail', 'site'],
     'selectors': ['tasarım', 'görsel', 'tipografi', 'renk', 'maskot', 'kompozisyon', 'kapak']},
    {'id': 'calisma-yontemi', 'title': 'Çalışma yöntemi',
     'aliases': ['çalışma', 'yöntem', 'işleyiş', 'workflow'],
     'selectors': ['yöntem', 'işleyiş', 'workflow', 'freestyle', 'half-scripted']},
)

CAUTION = ('Kaynaklı konu derlemesi; yeni çıkarım veya kullanıcı onayı değildir. '
           'İfadeler kendi kapsamındadır; olası çelişkiler çözülmemiştir.')


def build(vault, project_id=None, definitions=None):
    """Revalidate evidence and compose extractive, scoped topic dossiers.

    Optional definitions use id/title/aliases/selectors (lists of words). These
    are routing rules, never accepted user facts. No new claims are generated.
    """
    from gorev_baglam import content_words, word_match
    vault = Path(vault)
    rows, diagnostics = knowledge._rows(vault)
    records = [r for r in rows if r['scope'] in ('user', f'project:{project_id}')]
    topics = []
    for definition in TOPIC_DEFINITIONS if definitions is None else definitions:
        selectors = content_words(' '.join(definition['selectors']))
        members = []
        for record in records:
            words = content_words(record['title'] + ' ' + record['statement'])
            if any(word_match(t, w) for t in selectors for w in words):
                members.append(record)
        topics.append(dict(id=definition['id'], title=definition['title'],
                           aliases=definition['aliases'], records=members,
                           available=bool(members),
                           summary=[dict(statement=r['statement'], scope=r['scope'],
                                         domains=r['domains'], record_id=r['id'],
                                         review_note=r['review_note']) for r in members],
                           unknowns=['Yeni alana aktarım onayı yok.',
                                     'İfadeler arası çelişki/istisna otomatik çözümlenmedi.']
                                    if members else ['Doğrulanmış konu kaydı bulunamadı.'],
                           synthesis_mode='extractive_reviewed_assertions',
                           conflict_resolution='unresolved', notice=CAUTION))
    return dict(topics=topics, diagnostics=diagnostics,
                synthesis_mode='extractive_reviewed_assertions', notice=CAUTION)


def render_markdown(result):
    """Human-readable snapshot. Runtime retrieval always rebuilds from sources."""
    lines = ['# Kaynaklı konu sentezleri', '', CAUTION,
             '', 'Bu görünüm bir anlık dökümdür; görev bağlamı kaynakları yeniden doğrular.']
    for topic in result['topics']:
        lines.extend(['', '## ' + topic['title'], '', '### Birleşik kaynaklı özet'])
        for record in topic['records']:
            lines.extend(['', f"- {record['statement']}",
                          f"  Kapsam: {record['scope']} | Alan: {', '.join(record['domains'])}",
                          f"  İnceleme: {record['review_note']}",
                          f"  Kayıt: [[bilgi/{record['id']}]]"])
            for source in record['sources']:
                lines.extend([f"  Kaynak: [[{source['path']}]] | SHA-256: {source['sha256']}",
                              f"  Kanıt: {source['evidence']}"])
        lines.extend(['', '### Sınırlar ve açık noktalar', ''])
        lines.extend('- ' + unknown for unknown in topic['unknowns'])
    if result['diagnostics']:
        lines.extend(['', '## Dışlanan kaynaklar', ''] +
                     ['- ' + item for item in result['diagnostics']])
    return '\n'.join(lines) + '\n'


def retrieve(vault, query, project_id=None, budget=1800):
    from jev_retrieval import knowledge as semantic_knowledge
    return semantic_knowledge(vault, query, project_id, budget,
                              lambda: _retrieve_local(vault, query, project_id, budget))


def _retrieve_local(vault, query, project_id=None, budget=1800):
    """For explicit synthesis queries, expand evidence within matched topics.

    Return only fully delivered records and their versions. This is contextual
    expansion, not semantic search. `omitted_record_ids` exposes budget loss.
    """
    from gorev_baglam import content_words, word_match
    vault = Path(vault)
    terms = content_words(query)
    intent = content_words('tercih özet sentez birlikte yöntem')
    if not any(word_match(t, w) for t in intent for w in terms):
        return knowledge._retrieve_local(vault, query, project_id, budget)
    if any(word_match(t, w) for t in ('site', 'web', 'website') for w in terms):
        return knowledge._retrieve_local(vault, query, project_id, budget)
    result = build(vault, project_id)
    ranked = []
    for topic in result['topics']:
        words = content_words(' '.join(topic['aliases']))
        score = sum(any(word_match(t, w) for w in words) for t in terms)
        if score:
            ranked.append((-score, topic['id'], topic))
    if not ranked:
        return knowledge._retrieve_local(vault, query, project_id, budget)
    ranked.sort(key=lambda item: item[:2])
    cards, records, topics, versions, omitted = [], [], [], {}, []
    seen = set()
    for _, _, topic in ranked:
        delivered = []
        for record in topic['records']:
            if record['id'] in seen:
                continue
            try: revision=knowledge.note_version(vault,record)
            except (OSError,ValueError):
                result['diagnostics'].append(record['id']+':source_changed_during_read');continue
            path = f"bilgi/{record['id']}.md"
            card = (f"Konu: {topic['title']} | Kapsam: {record['scope']} | "
                    f"Alanlar: {', '.join(record['domains'])}\n"
                    f"{record['statement']}\nKaynak: {path}")
            for source in record['sources']:
                card += f"\nDayanak: {source['path']}"
            for example in record.get('examples', []):
                card += (f"\nÖrnek ({example['acceptance']}; {example['role']}): "
                         f"{example['path']}")
            prospective = '\n\n'.join([CAUTION] + cards + [card])
            if len(prospective) > max(0, budget):
                omitted.append(record['id'])
                continue
            cards.append(card)
            records.append(record)
            delivered.append(record['id'])
            seen.add(record['id'])
            versions[path] = revision
            for source in record['sources']:
                versions[source['path']] = source['sha256']
            for example in record.get('examples', []):
                versions[example['path']] = example['sha256']
        if delivered:
            topics.append({k: v for k, v in topic.items() if k not in ('records', 'summary')} |
                          {'record_ids': delivered, 'summary': [entry for entry in topic['summary']
                                                               if entry['record_id'] in delivered]})
    return dict(text='\n\n'.join([CAUTION] + cards) if cards else '',
                records=records, transfers=[], topics=topics, source_versions=versions,
                diagnostics=result['diagnostics'],
                omitted_record_ids=sorted(set(omitted) - seen),
                synthesis_mode=result['synthesis_mode'])


def export(vault, project_id=None, apply=False):
    """Refresh a managed Obsidian snapshot; protect manual edits, never facts."""
    operation = knowledge.h.serialized(_export) if apply else _export
    return operation(Path(vault), project_id, apply)


def _export(vault, project_id=None, apply=False):
    if project_id is not None and (not isinstance(project_id, str) or
                                  not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,79}', project_id)):
        raise ValueError('invalid_project_id')
    folder = vault / 'bilgi' / 'konu-sentezleri'
    path = folder / (f'project-{project_id}.md' if project_id is not None else 'user.md')
    if any(p.is_symlink() for p in (vault, vault / 'bilgi', folder, path)):
        raise ValueError('unsafe_snapshot_path')
    if not path.resolve().is_relative_to(vault.resolve()):
        raise ValueError('unsafe_snapshot_path')
    before = path.read_text() if path.exists() else None
    if before is not None:
        match = re.fullmatch(r'<!-- konu-sentezi-v1 sha256:([a-f0-9]{64}) -->\n(.*)', before, re.S)
        if not match or hashlib.sha256(match[2].encode()).hexdigest() != match[1]:
            raise ValueError('snapshot_manually_changed')
    scope = f'user + project:{project_id}' if project_id is not None else 'user'
    body = f'Döküm kapsamı: {scope}\n\n' + render_markdown(build(vault, project_id))
    version = hashlib.sha256(body.encode()).hexdigest()
    content = f'<!-- konu-sentezi-v1 sha256:{version} -->\n' + body
    changed = content != before
    if apply and changed:
        knowledge._write(path, content)
        if path.read_text() != content:
            raise ValueError('snapshot_readback_failed')
    return dict(path=str(path), changed=changed, applied=bool(apply and changed),
                version=version, scope=scope, snapshot_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('build', 'retrieve', 'export'):
        sub = subs.add_parser(command)
        sub.add_argument('--project-id')
        if command == 'export':
            sub.add_argument('--apply', action='store_true')
        if command == 'build':
            sub.add_argument('--format', choices=['json', 'markdown'], default='json')
        if command == 'retrieve':
            sub.add_argument('query')
            sub.add_argument('--budget', type=int, default=1800)
    args = parser.parse_args()
    if args.command == 'build':
        result = build(args.vault, args.project_id)
    elif args.command == 'export':
        result = export(args.vault, args.project_id, args.apply)
    else:
        result = retrieve(args.vault, args.query, args.project_id, args.budget)
    print(render_markdown(result) if getattr(args, 'format', None) == 'markdown'
          else json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
