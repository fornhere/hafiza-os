import hashlib
import tempfile
import unittest
from pathlib import Path

from hafiza_gorunurluk import usage_note, write_note


class Visibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        self.p = self.v / 'tercih.md'
        self.p.write_text('Önce ihtiyacı açıkla.', encoding='utf-8')
        self.sha = hashlib.sha256(self.p.read_bytes()).hexdigest()
        self.package = {'source_versions': {'tercih.md': self.sha}, 'text': 'Kaynak: tercih.md'}

    def test_usage_is_source_checked_self_report_not_causal_proof(self):
        result = usage_note(self.v, self.package, 'tercih.md', 'Girişi ihtiyaçtan başlattım.')
        self.assertTrue(result['source_version_verified'])
        self.assertEqual(result['evidence_status'], 'agent_reported')
        self.assertIn(str(self.p), result['text'])
        self.assertIn('ajan beyanıdır', result['limitation'])
        self.assertEqual(list(self.v.iterdir()), [self.p])

    def test_stale_or_unoffered_source_rejected(self):
        with self.assertRaises(ValueError):
            usage_note(self.v, self.package, 'other.md', 'Uyguladım')
        self.p.write_text('Değişti')
        with self.assertRaises(ValueError):
            usage_note(self.v, self.package, 'tercih.md', 'Uyguladım')

    def test_budget_omitted_source_rejected(self):
        self.package['text'] = 'Başka bir kayıt sunuldu.'
        with self.assertRaises(ValueError):
            usage_note(self.v, self.package, 'tercih.md', 'Kullandım')

    def test_empty_secret_effect_and_secret_source_rejected(self):
        for effect in ('', ' ', 'api_key=secret123'):
            with self.assertRaises(ValueError):
                usage_note(self.v, self.package, 'tercih.md', effect)
        self.p.write_text('token=veryprivate')
        digest = hashlib.sha256(self.p.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):
            usage_note(self.v, {'source_versions': {'tercih.md': digest}, 'text': 'Kaynak: tercih.md'}, 'tercih.md', 'Kullandım')
        with self.assertRaises(ValueError):
            write_note(self.p, None, digest, 'Yeni kayıt')

    def test_path_escape_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            usage_note(self.v, {'source_versions': {'../outside': self.sha}}, '../outside', 'Kullandım')
        alias = self.v / 'alias.md'
        alias.symlink_to(self.p)
        with self.assertRaises(ValueError):
            usage_note(self.v, {'source_versions': {'alias.md': self.sha}}, 'alias.md', 'Kullandım')

    def test_absolute_offered_source_and_prefixed_hash(self):
        result = usage_note(self.v, {'source_versions': {str(self.p): 'sha256:' + self.sha}, 'text': str(self.p)}, str(self.p), 'Kullandım')
        self.assertEqual(result['source_sha256'], self.sha)

    def test_write_readback_and_noop(self):
        self.assertIsNone(write_note(self.p, self.sha, self.sha, 'Aynı'))
        result = write_note(self.p, None, self.sha, 'Tercih eklendi')
        self.assertEqual(result['kind'], 'verified_write')
        self.assertTrue(result['readback_verified'])
        self.assertEqual(list(self.v.iterdir()), [self.p])
        with self.assertRaises(ValueError):
            write_note(self.p, None, '0' * 64, 'Yanlış')
        with self.assertRaises(ValueError):
            write_note(self.p, None, self.sha, 'token=secret')


if __name__ == '__main__':
    unittest.main()
