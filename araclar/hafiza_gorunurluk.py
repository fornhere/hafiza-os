"""Read-only evidence checks for concise memory visibility notices.

A usage notice is an agent's explanation, not independent proof of causality.
A write notice proves current readback differs from a supplied before hash; it
cannot authenticate who wrote the file. Neither helper writes or logs anything.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

import hafiza as h


def _hash(value):
    if not isinstance(value, str):
        raise ValueError('SHA-256 gerekli')
    value = value.removeprefix('sha256:').lower()
    if not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('Geçersiz SHA-256')
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ValueError('Kısa ve boş olmayan açıklama gerekli')
    value = ' '.join(value.split())
    if h.contains_secret(value):
        raise ValueError('Özel anahtar içeren açıklama gösterilemez')
    # Keep user-supplied labels from creating arbitrary links or formatting.
    return re.sub(r'([\\`*_{}\[\]<>])', r'\\\1', value)


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Kaynak normal bir dosya olmalı')
    payload = path.read_bytes()
    if h.contains_secret(payload.decode('utf-8', errors='replace')) or h.contains_secret(str(path)):
        raise ValueError('Özel anahtar içeren kaynak gösterilemez')
    return hashlib.sha256(payload).hexdigest()


def _link(path):
    # Angle-bracket destinations support spaces without ambiguous Markdown.
    target = str(path).replace('%', '%25').replace('<', '%3C').replace('>', '%3E').replace('\n', '%0A').replace('\r', '%0D')
    return f'[kaynak](<{target}>)'


def usage_note(vault, package, source_path, effect):
    """Validate an offered source version; describe agent-reported application."""
    versions = package.get('source_versions', {})
    if not isinstance(versions, dict) or source_path not in versions:
        raise ValueError('Kaynak sunulan bağlam paketinde yok')
    if not isinstance(package.get('text'), str) or source_path not in package['text']:
        raise ValueError('Kaynak teslim edilen bağlam metninde yok')
    vault = Path(vault).resolve()
    raw = Path(source_path)
    path = raw if raw.is_absolute() else vault / raw
    if path.is_symlink():
        raise ValueError('Sembolik kaynak kabul edilmez')
    path = path.resolve()
    if not raw.is_absolute() and (raw.parts and '..' in raw.parts or not path.is_relative_to(vault)):
        raise ValueError('Göreli kaynak kasa dışında')
    effect = _text(effect)
    actual = _read(path)
    if actual != _hash(versions[source_path]):
        raise ValueError('Kaynak sürümü değişmiş')
    return {'kind': 'agent_reported_usage', 'text': f'Hafızadan yararlandım: {effect} — {_link(path)}',
            'source_path': str(path), 'source_sha256': actual,
            'evidence_status': 'agent_reported', 'source_version_verified': True,
            'limitation': 'Kaynak sürümü doğrulandı; kullanım açıklaması ajan beyanıdır, bağımsız nedensellik kanıtı değildir.'}


def write_note(path, before_hash, expected_after_hash, summary):
    """Check readback after an existing writer; return None for unchanged bytes."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Sembolik kaynak kabul edilmez')
    path = path.resolve()
    expected = _hash(expected_after_hash)
    before = None if before_hash is None else _hash(before_hash)
    actual = _read(path)
    if actual != expected:
        raise ValueError('Yazım sonrası sürüm eşleşmiyor')
    if actual == before:
        return None
    summary = _text(summary)
    return {'kind': 'verified_write', 'text': f'Hafızada güncellendi: {summary} — {_link(path)}',
            'source_path': str(path), 'before_sha256': before, 'source_sha256': actual,
            'readback_verified': True,
            'limitation': 'Dosyanın beklenen sürümü okundu; önceki hash çağırandan gelir, yazarı veya insan kabulünü kanıtlamaz.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    usage = sub.add_parser('usage')
    usage.add_argument('--vault', required=True)
    usage.add_argument('--package-json', required=True, type=Path)
    usage.add_argument('--source', required=True)
    usage.add_argument('--effect', required=True)
    write = sub.add_parser('write')
    write.add_argument('--path', required=True, type=Path)
    write.add_argument('--before-hash')
    write.add_argument('--after-hash', required=True)
    write.add_argument('--summary', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'usage':
            result = usage_note(args.vault, json.loads(args.package_json.read_text(encoding='utf-8')), args.source, args.effect)
        else:
            result = write_note(args.path, args.before_hash, args.after_hash, args.summary)
    except (ValueError, OSError, TypeError) as error:
        parser.exit(2, f'Hafıza bildirimi üretilemedi: {error}\n')
    if result is not None:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
