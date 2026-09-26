import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import hafiza as h
from ogrenme_pilotu import main, propose


class LearningPilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'vault'
        self.vault.mkdir()
        self.source = self.vault / 'source.md'
        self.quote = 'Kaynak bulma ve yanıt doğruluğu ayrı ölçülür.'
        self.source.write_text(self.quote, encoding='utf-8')
        self.brief = dict(topic='RAG deneyi', source_path='source.md',
                          evidence=self.quote, expected_source_hash=h.statement_hash(self.quote),
                          question='Doğru kaynak yanlış yanıta yol açabilir mi?',
                          experiment='İki belgeyle kaynak ve yanıtı ayrı denetle.',
                          success_criterion='Kaynak ve cevap hataları ayrı sayılmış olsun.')

    def test_proposal_no_inferred_gap_no_mutation(self):
        before = {p.name: p.read_bytes() for p in self.vault.iterdir()}
        result = propose(self.vault, self.brief)
        self.assertEqual(result['status'], 'proposed')
        self.assertEqual(result['source']['content_hash'], self.brief['expected_source_hash'])
        self.assertIn('kanıtlamaz', result['interpretation'])
        self.assertNotIn('knowledge_gap', result)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.vault.iterdir()})

    def test_changed_missing_and_quote(self):
        for change in ({'expected_source_hash': 'sha256:old'}, {'evidence': 'uydurma kaynak alıntısı'},
                       {'evidence': 'kısa'}, {'source_path': 'missing.md'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                propose(self.vault, dict(self.brief, **change))
        self.source.write_text(self.quote + ' Yeni karar.', encoding='utf-8')
        with self.assertRaises(ValueError):
            propose(self.vault, self.brief)

    def test_escape_and_symlink(self):
        outside = self.vault.parent / 'outside.md'
        outside.write_text(self.quote, encoding='utf-8')
        (self.vault / 'link.md').symlink_to(outside)
        for path in ('../outside.md', str(self.source), 'C:\\source.md', 'link.md'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                propose(self.vault, dict(self.brief, source_path=path))

    def test_sensitive_input_and_source(self):
        for field, value in [('sensitivity', 'private'), ('question', 'password=' + 'supersecret123')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                propose(self.vault, dict(self.brief, **{field: value}))
        self.source.write_text('sensitivity: private\n' + self.quote, encoding='utf-8')
        with self.assertRaises(ValueError):
            propose(self.vault, dict(self.brief, expected_source_hash=h.statement_hash(self.source.read_text())))

    def test_cli_success_and_generic_error(self):
        inp = self.vault.parent / 'brief.json'
        inp.write_text(json.dumps(self.brief), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(['--vault', str(self.vault), '--input-json', str(inp)]), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'proposed')
        inp.write_text('{invalid', encoding='utf-8')
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(['--vault', str(self.vault), '--input-json', str(inp)]), 2)
        self.assertNotIn('invalid', errors.getvalue())


if __name__ == '__main__':
    unittest.main()
