"""Preflight-only native hook planning. Ownership lives outside client schemas."""
import copy
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

from ajan_kur import read_target, safe_path


def shell_command(argv, shell=None):
    if shell is None:
        if os.name == 'nt':
            raise ValueError('Windows string hooks require verified --hook-shell cmd or posix')
        shell = 'posix'
    if shell == 'posix':
        return shlex.join([str(arg) for arg in argv])
    # cmd expands percent/exclamation even inside quotes. Reject metacharacters,
    # rather than depending on undocumented client escaping or delayed expansion.
    if shell != 'cmd' or any(any(c in str(arg) for c in '%!^&|<>\r\n"') for arg in argv):
        raise ValueError('Unsafe cmd hook path or unsupported shell')
    return subprocess.list2cmdline([str(arg) for arg in argv])


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate configuration key')
            result[key] = value
        return result
    value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique) if raw is not None else {}
    if not isinstance(value, dict):
        raise ValueError('Configuration must be an object')
    return value


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def plan_hooks(vault, agent, home, codex_home, remove, migrate, shell):
    if agent == 'generic':
        raise ValueError('generic has no hook adapter')
    locations = {'claude': Path(home) / '.claude/settings.json',
                 'codex': Path(codex_home or os.environ.get('CODEX_HOME') or Path(home) / '.codex') / 'hooks.json',
                 'antigravity': Path(home) / '.gemini/config/hooks.json'}
    plans = []
    for client in (locations if agent == 'all' else [agent]):
        path = safe_path(locations[client])
        owner_path = safe_path(path.with_name(path.name + '.hafiza-os.json'))
        raw, owner_raw = read_target(path), read_target(owner_path)
        config, owner = decode(raw), decode(owner_raw)
        before = copy.deepcopy(config)
        if owner and (set(owner) != {'version', 'vault', 'client', 'entries'} or owner['version'] != 1
                      or owner['vault'] != str(vault) or owner['client'] != client or not isinstance(owner['entries'], dict)):
            raise ValueError('Hook ownership conflict')
        nested = client != 'antigravity'
        key = 'hooks' if nested else 'hafiza-os'
        if key in config and not isinstance(config[key], dict):
            raise ValueError('Invalid hook container')
        hooks = config.get(key, {})
        if not nested and hooks and not owner:
            raise ValueError('Unowned hafiza-os group')
        for event, groups in hooks.items():
            if not isinstance(groups, list) or any(not isinstance(g, dict) for g in groups):
                raise ValueError('Invalid hook event')
            if nested and any(not isinstance(g.get('hooks'), list) or any(not isinstance(h, dict) for h in g['hooks']) for g in groups):
                raise ValueError('Invalid hook handlers')
        # Remove exactly our previously written event entries. Any edit refuses
        # the entire transaction, including instructions, before writes begin.
        for event, entry in owner.get('entries', {}).items():
            if hooks.get(event, []).count(entry) != 1:
                raise ValueError('Edited or missing owned hook')
            hooks[event].remove(entry)
            if not hooks[event]:
                del hooks[event]
        legacy = set()
        if client == 'claude':
            legacy = {str(vault / '.claude/hooks' / name) for name in
                      ('oturum-basla.sh', 'mesaj-say.sh', 'hafiza-kontrol.sh', 'oturum-bitir.sh')}
        elif client == 'codex':
            legacy = {'python3 ' + shlex.quote(str(vault / 'araclar/codex_hafiza.py')) + ' hook'}
        for event, groups in list(hooks.items()):
            if not nested:
                continue
            for group in list(groups):
                matches = [h for h in group['hooks'] if h.get('type') == 'command' and h.get('command') in legacy and not h.get('args')]
                if matches and not migrate:
                    raise ValueError('Legacy same-vault hooks conflict; use --migrate-legacy')
                for handler in matches:
                    group['hooks'].remove(handler)
                if matches and not group['hooks']:
                    groups.remove(group)
            if not groups:
                del hooks[event]
        entries = {}
        if not remove:
            events = ('SessionStart', 'UserPromptSubmit', 'Stop', 'Interrupt') if client == 'codex' else (
                ('SessionStart', 'UserPromptSubmit', 'Stop') if client == 'claude' else ('PreInvocation', 'Stop'))
            adapter = safe_path(vault / 'araclar' / ('codex_hafiza.py' if client == 'codex' else 'client_hafiza.py'))
            if not adapter.is_file():
                raise ValueError('Missing native adapter')
            for event in events:
                argv = [sys.executable, '-X', 'utf8', str(adapter), '--vault', str(vault)]
                argv += ['hook'] if client == 'codex' else ['--client', client, '--event', event]
                handler = {'type': 'command', 'timeout': 3 if event == 'Interrupt' else 10}
                if client == 'claude':
                    handler.update(command=argv[0], args=argv[1:])
                else:
                    handler['command'] = shell_command(argv, shell)
                entry = {'hooks': [handler]} if nested else handler
                # A command without our sidecar is not ours to silently adopt.
                existing = [h for g in hooks.get(event, []) for h in (g['hooks'] if nested else [g])]
                if any(h.get('command') == handler['command'] and h.get('args') == handler.get('args') for h in existing):
                    raise ValueError('Unowned duplicate hook command')
                hooks.setdefault(event, []).append(entry)
                entries[event] = entry
        if hooks:
            config[key] = hooks
        else:
            config.pop(key, None)
        updated = raw if before == config else encode(config)
        manifest = {'version': 1, 'vault': str(vault), 'client': client, 'entries': entries} if entries else {}
        owner_updated = owner_raw if owner == manifest else encode(manifest)
        plans.extend([(path, raw, updated or b''), (owner_path, owner_raw, owner_updated or b'')])
    return plans
