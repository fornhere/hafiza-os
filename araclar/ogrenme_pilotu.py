"""Draft a source-backed experiment; never infer a person's knowledge or write memory.

Example: python3 araclar/ogrenme_pilotu.py --vault /tmp/pilot --input-json /tmp/brief.json
Brief fields: topic, source_path (relative to vault), evidence (exact quotation),
expected_source_hash (hafiza.statement_hash of UTF-8 source text), question,
experiment, success_criterion; optional sensitivity must be normal.
The authored question is a hypothesis, not a source-proven knowledge gap.
"""
import argparse
import json
from pathlib import Path, PureWindowsPath
import re
import sys

import hafiza as h

FIELDS = ('topic', 'source_path', 'evidence', 'expected_source_hash',
          'question', 'experiment', 'success_criterion')


def _secret(text: str) -> bool:
    return h.contains_secret(text) or bool(re.search(
        r'(?i)\b(password|passwd|api[_-]?key|access[_-]?token|secret)\s*[:=]\s*\S+', text))


def propose(vault: Path, brief: dict) -> dict:
    """Return an ephemeral proposal. Validation errors never echo source content."""
    if not isinstance(brief, dict) or set(brief) - set(FIELDS) - {'sensitivity'}:
        raise ValueError('Geçersiz brief alanları')
    for field in FIELDS:
        value = brief.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 4000:
            raise ValueError('Eksik veya geçersiz brief alanı: ' + field)
        if _secret(value):
            raise ValueError('Brief sır içeriyor')
    if brief.get('sensitivity', 'normal') != 'normal':
        raise ValueError('Yalnız normal hassasiyet desteklenir')
    relative = brief['source_path']
    if (Path(relative).is_absolute() or PureWindowsPath(relative).drive
            or '\\' in relative or '..' in Path(relative).parts):
        raise ValueError('Kaynak kasa içi göreli yol olmalı')
    source = h.source_file(vault, relative)
    content = source.read_text(encoding='utf-8')
    if _secret(content) or re.search(
            r'(?im)^\s*["\']?sensitivity["\']?\s*:\s*["\']?(private|secret)\b', content):
        raise ValueError('Kaynak normal hassasiyette değil veya sır içeriyor')
    current_hash = h.statement_hash(content)
    if current_hash != brief['expected_source_hash']:
        raise ValueError('Kaynak sürümü değişti')
    if len(brief['evidence']) < 10 or brief['evidence'] not in content:
        raise ValueError('Kanıt en az 10 karakterlik tam kaynak alıntısı olmalı')
    return {
        'schema_version': 1, 'status': 'proposed',
        'topic': brief['topic'],
        'source': {'path': relative, 'content_hash': current_hash,
                   'evidence': brief['evidence']},
        'question': brief['question'], 'experiment': brief['experiment'],
        'success_criterion': brief['success_criterion'],
        'interpretation': 'Yazarın deney önerisi; kaynak öğrenme boşluğu veya kişinin bilgi düzeyini kanıtlamaz.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True, type=Path)
    parser.add_argument('--input-json', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = propose(args.vault, json.loads(args.input_json.read_text(encoding='utf-8')))
    except (ValueError, OSError, UnicodeError):
        print('Deney önerisi üretilemedi: brief, kaynak, sürüm veya hassasiyet doğrulaması başarısız.', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
