#!/usr/bin/env python3
"""Measure delivered memory context against privately reviewed real prompts."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from collections import Counter

import capture_source
import client_transcripts
import gorev_baglam
import hafiza
import jev_client


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)
    except ValueError:
        return None


def _valid(text):
    text = capture_source.clean_user(text)
    return (15 <= len(text) <= 400 and not hafiza.contains_secret(text)
            and not client_transcripts.private(text)
            and not text.lstrip().startswith(('İŞÇİ KOŞUSU', 'ISCI KOSUSU', '<task-notification',
                                              'Bu otomatik bir işçi koşusudur', '[Request interrupted by user]',
                                              '<subagent_notification', '# AGENTS.md instructions')))


def _claude(path, cutoff):
    try:
        parsed = client_transcripts.parse('claude', path.stem, path)
    except (OSError, ValueError, UnicodeError):
        return []
    rows = []
    # The parser decides which messages are genuine. The raw row supplies time and cwd.
    lines = path.read_text(encoding='utf-8').splitlines()
    for entry in parsed['entries']:
        if entry['role'] != 'user':
            continue
        row = json.loads(lines[entry['line'] - 1])
        when = _date(row.get('timestamp'))
        text = capture_source.clean_user(entry['quote'])
        if when and when >= cutoff and _valid(text):
            rows.append((when, row.get('cwd') if isinstance(row.get('cwd'), str) else '',
                         entry['message_id'], text))
    return rows


def _codex(path, cutoff):
    try:
        capture_source.snapshot(path)
        lines = path.read_text(encoding='utf-8').splitlines()
    except (OSError, ValueError, UnicodeError):
        return []
    cwd = ''
    rows = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        payload = item.get('payload', {})
        if item.get('type') == 'session_meta':
            cwd = payload.get('cwd') if isinstance(payload.get('cwd'), str) else ''
        if item.get('type') != 'response_item' or payload.get('type') != 'message' or payload.get('role') != 'user':
            continue
        when = _date(item.get('timestamp'))
        if not when or when < cutoff:
            continue
        text = '\n'.join(part.get('text', '') for part in payload.get('content', [])
                         if isinstance(part, dict) and part.get('type') in (None, 'input_text', 'text'))
        text = capture_source.clean_user(text)
        if _valid(text):
            rows.append((when, cwd, payload.get('id') or item.get('timestamp'), text))
    return rows


def collect(*, claude_root, codex_root, out, days=21, limit=80, now=None):
    if days < 1 or limit < 1:
        raise ValueError('days and limit must be positive')
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    roots = [('claude', Path(claude_root).glob('*/*.jsonl'), _claude),
             ('codex', Path(codex_root).glob('**/*.jsonl'), _codex)]
    pools = {}
    for client, paths, reader in roots:
        candidates = []
        for path in sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True):
            if path.is_symlink() or path.name.startswith('agent-') or 'subagent' in path.parts:
                continue
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                continue
            for when, cwd, source_id, prompt in reader(path, cutoff):
                ident = hashlib.sha256((client + '\0' + str(path) + '\0' + str(source_id)).encode()).hexdigest()[:20]
                candidates.append((when, dict(id=ident, client=client, cwd=cwd, prompt=prompt)))
            if len(candidates) >= limit * 3:
                break
        pools[client] = [row for _, row in sorted(candidates, key=lambda x: x[0], reverse=True)]
    chosen, seen = [], set()
    while len(chosen) < limit and any(pools.values()):
        for client in ('claude', 'codex'):
            while pools[client]:
                row = pools[client].pop(0)
                key = re.sub(r'\s+', ' ', row['prompt']).strip().casefold()
                if key in seen:
                    continue
                seen.add(key)
                chosen.append(row)
                break
            if len(chosen) >= limit:
                break
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in chosen), encoding='utf-8')
    return chosen


def _jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def evaluate(vault, set_path, labels_path, out_dir):
    prompts = _jsonl(set_path)
    labels = {row['id']: row for row in _jsonl(labels_path)}
    if len(labels) != len(prompts) or set(labels) != {row['id'] for row in prompts}:
        raise ValueError('labels must cover each prompt exactly once')
    catalog = {row['memory_id'] for row in hafiza.load_catalog(Path(vault)) if row.get('status') == 'active'}
    note_ids = {p.stem for p in (Path(vault) / 'bilgi').glob('*.md') if p.name != 'README.md'}
    results = []
    with jev_client.disabled():
        for row in prompts:
            label = labels[row['id']]
            gold_memory = set(label.get('relevant_memory_ids', []))
            gold_notes = set(label.get('relevant_notes', []))
            if gold_memory - catalog or gold_notes - note_ids:
                raise ValueError('label refers to unknown or inactive record: ' + row['id'])
            package = gorev_baglam.build_task_package(Path(vault), row['prompt'], cwd=row.get('cwd') or None, budget=2000)
            actual_memory = set(package['selected_ids']) & catalog
            knowledge = package.get('knowledge') or {}
            actual_notes = {record['id'] for record in knowledge.get('records', [])}
            actual_notes.update(t['source_record']['id'] for t in knowledge.get('transfers', []))
            # A knowledge candidate counts only when its text reached the package.
            actual_notes &= note_ids
            actual = {'memory:' + x for x in actual_memory} | {'note:' + x for x in actual_notes}
            gold = {'memory:' + x for x in gold_memory} | {'note:' + x for x in gold_notes}
            results.append(dict(id=row['id'], client=row['client'], prompt=row['prompt'],
                                tp=sorted(actual & gold), fp=sorted(actual - gold), fn=sorted(gold - actual),
                                selected_memory_ids=sorted(actual_memory), selected_notes=sorted(actual_notes),
                                relevant_memory_ids=sorted(gold_memory), relevant_notes=sorted(gold_notes),
                                injected_chars=len(package['text']), uncertain=bool(label.get('uncertain'))))
    tp = sum(len(r['tp']) for r in results)
    fp = sum(len(r['fp']) for r in results)
    fn = sum(len(r['fn']) for r in results)
    empty = [r for r in results if not r['relevant_memory_ids'] and not r['relevant_notes']]
    metrics = dict(prompts=len(results), tp=tp, fp=fp, fn=fn,
                   precision=tp / (tp + fp) if tp + fp else None,
                   recall=tp / (tp + fn) if tp + fn else None,
                   empty_return_rate=sum(r['injected_chars'] == 0 for r in empty) / len(empty) if empty else None,
                   empty_memory_return_rate=sum(not r['selected_memory_ids'] and not r['selected_notes'] for r in empty) / len(empty) if empty else None,
                   empty_gold_prompts=len(empty), average_injected_chars=sum(r['injected_chars'] for r in results) / len(results) if results else 0,
                   uncertain_labels=sum(r['uncertain'] for r in results))
    certain = [r for r in results if not r['uncertain']]
    ctp, cfp, cfn = (sum(len(r[key]) for r in certain) for key in ('tp', 'fp', 'fn'))
    metrics['certain_only'] = dict(prompts=len(certain), tp=ctp, fp=cfp, fn=cfn,
                                   precision=ctp / (ctp + cfp) if ctp + cfp else None,
                                   recall=ctp / (ctp + cfn) if ctp + cfn else None)
    report = dict(metrics=metrics, results=results)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'erisim-degerlendirme-2026-09-24.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    def examples(kind):
        ranked = sorted((r for r in results if r[kind]), key=lambda r: (-len(r[kind]), r['id']))[:10]
        return '\n'.join(f"- `{r['id']}` {r['prompt'][:80].replace(chr(10), ' ')} — {', '.join(r[kind])}" for r in ranked) or '- Yok'
    common_fp = Counter(item for row in results for item in row['fp']).most_common(5)
    common_fn = Counter(item for row in results for item in row['fn']).most_common(5)
    md = (f"# Erişim değerlendirmesi\n\nİstem: {len(results)}; TP: {tp}; FP: {fp}; FN: {fn}.\n"
          f"Precision: {metrics['precision']}; recall: {metrics['recall']}; alakasız kümede tüm metnin boş dönmesi: {metrics['empty_return_rate']}; katalog/notun boş dönmesi: {metrics['empty_memory_return_rate']}.\n"
          f"Ortalama enjekte karakter: {metrics['average_injected_chars']:.1f}; belirsiz etiket: {metrics['uncertain_labels']}.\n\n"
          f"Kesin etiketli {len(certain)} istemde precision: {metrics['certain_only']['precision']}; recall: {metrics['certain_only']['recall']} (TP {ctp}, FP {cfp}, FN {cfn}).\n\n"
          f"TP/FP/FN yalnız aktif katalog ve teslim edilmiş bilgi notu kimlikleri içindir; karakter ve boş dönme tüm paket metnini kapsar. Belirsiz etiketler metriklere dahildir.\n\n"
          f"## En kötü 10 FP\n\n{examples('fp')}\n\n## En kötü 10 FN\n\n{examples('fn')}\n\n"
          f"## Gözlenen desenler\n\n"
          f"- En sık FP: {', '.join(f'{name} ({count})' for name, count in common_fp) or 'yok'}.\n"
          f"- En sık FN: {', '.join(f'{name} ({count})' for name, count in common_fn) or 'yok'}.\n"
          f"- {len(empty)} istemde katalog/not etiketi boş; bunların {sum(r['injected_chars'] > 0 for r in empty)} tanesine yine de paket metni enjekte edildi.\n\n"
          f"## İyileştirme önerileri (bu ölçümde uygulanmadı)\n\n"
          f"- Talimat/skill yoklaması ve genel ürün sorularında katalog aramasını istem niyetine bağlayıp eşleşen konu kanıtı istemek; özellikle genel hafıza sözcüğünü tek başına yeterli saymamak.\n"
          f"- Proje ve cwd eşleşmesinden gelen kartlarda istemdeki somut konu ile kartın koşulunu birlikte doğrulamak; belirsiz devam mesajlarında seçimi zorlamamak.\n"
          f"- Kaçan bilgi notları için gerçek istemlerden eşanlamlı ifade ve alan kapsamı örnekleriyle erişim adaylarını incelemek; notu yalnız teslim edildiyse başarılı saymak.\n"
          f"- Belirsiz etiketleri ikinci bir gözden geçirmeden sonra kesin metrikten ayrı raporlamak.\n")
    (out_dir / 'erisim-degerlendirme-2026-09-24.md').write_text(md, encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('collect')
    c.add_argument('--claude-root', type=Path, default=Path.home() / '.claude/projects')
    c.add_argument('--codex-root', type=Path, default=Path.home() / '.codex/sessions')
    c.add_argument('--days', type=int, default=21)
    c.add_argument('--limit', type=int, default=80)
    c.add_argument('--out', type=Path, required=True)
    e = commands.add_parser('evaluate')
    e.add_argument('--set', type=Path, required=True)
    e.add_argument('--labels', type=Path, required=True)
    e.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'collect':
        print(json.dumps({'collected': len(collect(claude_root=args.claude_root, codex_root=args.codex_root,
                                                   out=args.out, days=args.days, limit=args.limit))}))
    else:
        print(json.dumps(evaluate(args.vault, args.set, args.labels, args.out_dir)['metrics']))


if __name__ == '__main__':
    main()
