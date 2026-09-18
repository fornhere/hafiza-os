import hashlib
import tempfile
import unittest
from pathlib import Path

from bilgi_agi import register
from gorev_baglam import build_task_package


class SynthesisFlow(unittest.TestCase):
    def test_topic_package_is_current_and_budgeted(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            source = vault / 'source.md'
            source.write_text('Sunum anlatımı günlük dil ve anlamlı geçişler içermeli.')
            for key, statement in [('dil', 'Sunum anlatımı günlük dil içermeli.'),
                                   ('gecis', 'Sunum anlatımı anlamlı geçişler içermeli.')]:
                register(vault, dict(id=key, title=key, statement=statement,
                    kind='preference', status='reviewed', scope='user', domains=['sunum'],
                    reviewed_by='test', review_note='Yalnız sunum anlatımı kapsamı.',
                    sources=[dict(path='source.md', sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                                  evidence=source.read_text())]), True)
            package = build_task_package(vault, 'Anlatım tercihlerimi özetle')
            self.assertEqual({r['id'] for r in package['knowledge']['records']}, {'dil', 'gecis'})
            self.assertIn('source.md', package['source_versions'])
            self.assertIn('Kaynak: bilgi/dil.md', package['text'])
            tiny = build_task_package(vault, 'Anlatım tercihlerimi özetle', budget=10)
            self.assertLessEqual(len(tiny['text']), 10)
            self.assertIsNone(tiny['knowledge'])
            source.write_text('Değişmiş kaynak artık önceki ifadeyi desteklemiyor.')
            changed = build_task_package(vault, 'Anlatım tercihlerimi özetle')
            self.assertFalse((changed.get('knowledge') or {}).get('records'))


if __name__ == '__main__':
    unittest.main()
