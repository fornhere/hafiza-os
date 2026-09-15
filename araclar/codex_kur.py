#!/usr/bin/env python3
"""Install optional Codex hooks without replacing other hooks or trust settings."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shlex

from codex_hafiza import atomic

START = '<!-- HAFIZA-OS:CODEX:START -->'
END = '<!-- HAFIZA-OS:CODEX:END -->'


def install(vault, codex_home, apply=False):
    script = vault.resolve() / 'araclar/codex_hafiza.py'
    if not script.is_file(): raise ValueError('Codex adaptörü bulunamadı')
    hooks_path = codex_home / 'hooks.json'
    config = json.loads(hooks_path.read_text()) if hooks_path.exists() else {}
    hooks = config.setdefault('hooks', {})
    command = 'python3 ' + shlex.quote(str(script)) + ' hook'
    for event in ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt'):
        groups = hooks.setdefault(event, [])
        if not any(h.get('command') == command for g in groups for h in g.get('hooks', [])):
            groups.append({'hooks': [{'type': 'command', 'command': command,
                                     'timeout': 3 if event == 'Interrupt' else 10}]})
    path = codex_home / 'AGENTS.md'
    previous = path.read_text() if path.exists() else ''
    if previous.count(START) != previous.count(END) or previous.count(START) > 1:
        raise ValueError('AGENTS.md yönetilen blok işaretleri tutarsız')
    block = (START + '\n# Ortak hafıza\n\n'
        f'Hafıza kasası `{vault.resolve()}`. Yeni ana oturumda agents.md, '
        'zihin/son-oturum.md dosyasının en yeni bölümü, zihin/açık-işler.md ve '
        'komuta/bu-hafta.md oku. Selam/gündem sorusunda en fazla 2–3 ilgili, '
        'güncel işi hatırlat; eski işi yeniden açma. İlk beş gerçek kullanıcı '
        'mesajında kayıt isteme. Altıncıdan sonra anlamlı karar/sonuçları arka plan '
        'konsolidasyonuna bırak; cevap sonunda kayıt isteme veya ek tur açma. '
        'Kaydetmeme isteğine uy. Kalıcı tercihler yalnız kaynaklı adaydır; '
        'inceleme öncesi Mem0’a doğrudan yazma. Ayrıntı: '
        'komuta/hafıza-konsolidasyonu.md.\n' + END)
    if START in previous:
        before, rest = previous.split(START, 1)
        _, after = rest.split(END, 1)
        instructions = before + block + after
    else:
        instructions = previous.rstrip() + ('\n\n' if previous else '') + block + '\n'
    if apply:
        codex_home.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        for target in (hooks_path, path):
            if target.exists(): atomic(target.with_name(target.name + '.backup-' + stamp), target.read_text())
        atomic(hooks_path, json.dumps(config, ensure_ascii=False, indent=2) + '\n')
        atomic(path, instructions)
    return {'apply': apply, 'hooks_path': str(hooks_path), 'instructions_path': str(path),
            'next_step': 'Codex /hooks ekranında dört Hafıza OS bağlantısını inceleyip etkinleştir; ardından yeni oturumda doğrula.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(install(args.vault, args.codex_home, args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
