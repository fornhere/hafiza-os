"""context komutunun not kanalı: incelenmiş bilgi/ notları ve proje tespiti (sentetik)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import bilgi_agi
import hafiza


class ContextKnowledgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name) / 'kasa'
        self.root = Path(temporary.name) / 'isler' / 'atlas'
        self.root.mkdir(parents=True)
        for folder in ('gelen-kutusu', 'komuta', 'zihin', 'projeler/atlas'):
            (self.vault / folder).mkdir(parents=True)
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': [
            {'id': 'atlas', 'aliases': ['atlas'], 'roots': [str(self.root)]},
            {'id': 'bora', 'aliases': ['bora'], 'roots': []}]}), encoding='utf-8')
        (self.vault / 'zihin/hafıza-kataloğu.jsonl').write_text('', encoding='utf-8')
        # Ham işletim belgesi: sorguyla sözcük paylaşır ama varsayılan bağlama girmemeli.
        (self.vault / 'projeler/atlas/DURUM.md').write_text(
            '# Atlas\n\n## Sunum durumu\nSunum dosyası dün taşındı.\n', encoding='utf-8')
        source = self.vault / 'gelen-kutusu/kaynak.md'
        source.write_text('Kullanıcı: Sunum metninde robotik anlatım istemiyorum, doğal konuş.', encoding='utf-8')
        self.note = dict(id='sunum-dogal', title='Sunumda doğal konuşma', kind='preference',
                         statement='Sunum metninde robotik anlatım yerine doğal konuşma dili kullanılır.',
                         scope='project:atlas', domains=['sunum'], status='reviewed',
                         sources=[dict(path='gelen-kutusu/kaynak.md', sha256=bilgi_agi.digest(source),
                                       evidence='Sunum metninde robotik anlatım istemiyorum, doğal konuş.')],
                         reviewed_by='review-agent', review_note='Sentetik test notu.')
        bilgi_agi.register(self.vault, self.note, True)

    def context(self, query, *flags):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = hafiza.main(['--vault', str(self.vault), 'context', query, *flags])
        self.assertEqual(0, code)
        return json.loads(output.getvalue())

    def test_cwd_selects_project_and_delivers_reviewed_note(self):
        package = self.context('sunum metnini doğal konuşma diliyle yaz', '--cwd', str(self.root))
        self.assertEqual('project:atlas', package['scope'])
        self.assertEqual(['bilgi/sunum-dogal.md'], [n['path'] for n in package['notes']])
        self.assertIn('doğal konuşma dili', package['text'])

    def test_raw_operational_documents_are_not_default_context(self):
        package = self.context('sunum dosyası durumu', '--cwd', str(self.root))
        self.assertNotIn('projeler/atlas/DURUM.md', json.dumps(package, ensure_ascii=False))
        explicit = self.context('sunum dosyası durumu', '--cwd', str(self.root), '--uri', 'projeler')
        self.assertIn('projeler/atlas/DURUM.md', [n['path'] for n in explicit['notes']])

    def test_unrelated_prompt_gets_no_note(self):
        package = self.context('veritabanı şemasını kur', '--cwd', str(self.root))
        self.assertEqual([], package['notes'])

    def test_project_named_in_query_wins_over_cwd_and_explicit_scope_is_kept(self):
        self.assertEqual('project:bora', self.context('bora için sunum yaz', '--cwd', str(self.root))['scope'])
        self.assertEqual('user', self.context('sunum yaz', '--cwd', str(self.vault.parent))['scope'])
        self.assertEqual('project:bora', self.context('sunum yaz', '--scope', 'project:bora',
                                                      '--cwd', str(self.root))['scope'])

    def test_other_project_note_is_not_a_general_preference(self):
        package = self.context('sunum yaz', '--scope', 'user')
        self.assertEqual([], package['notes'])


if __name__ == '__main__':
    unittest.main()
