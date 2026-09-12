import json
from pathlib import Path
import tempfile
import unittest
import codex_kur as k


class Installer(unittest.TestCase):
    def test_preserves_existing_config_quotes_path_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); vault = root / 'Benim Hafızam'; home = root / 'codex'
            (vault / 'araclar').mkdir(parents=True); home.mkdir()
            (vault / 'araclar/codex_hafiza.py').write_text('# fixture')
            original = {'hooks': {'Stop': [{'hooks': [{'type': 'command', 'command': 'existing-hook'}]}]}}
            (home / 'hooks.json').write_text(json.dumps(original)); (home / 'AGENTS.md').write_text('Mevcut yönerge\n')
            k.install(vault, home)
            self.assertEqual(original, json.loads((home / 'hooks.json').read_text()))
            k.install(vault, home, True); first = (home / 'hooks.json').read_text()
            k.install(vault, home, True)
            self.assertEqual(first, (home / 'hooks.json').read_text())
            hooks = json.loads(first)['hooks']
            self.assertEqual('existing-hook', hooks['Stop'][0]['hooks'][0]['command'])
            self.assertIn("'", hooks['Stop'][1]['hooks'][0]['command'])
            self.assertTrue((home / 'AGENTS.md').read_text().startswith('Mevcut yönerge'))
            self.assertEqual(1, (home / 'AGENTS.md').read_text().count(k.START))
            self.assertFalse((home / 'config.toml').exists())


if __name__ == '__main__': unittest.main()
