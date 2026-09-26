"""Synthetic detector fixtures; no complete secret-shaped literal in source."""
import json
from pathlib import Path
import tempfile
import unittest

import hafiza
import yayinla


def grouped(*groups):
    return '-'.join(groups)


def provider_examples():
    suffix = 'F4ke' * 10
    return (
        [('provider_sk', prefix + suffix) for prefix in ('sk-', 'sk-proj-', 'sk-ant-api03-', 'sk-or-v1-')]
        + [('provider_github', prefix + suffix) for prefix in
           ('ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_', 'github_pat_')]
        + [('provider_slack', prefix + suffix) for prefix in
           ('xoxa-', 'xoxb-', 'xoxe-', 'xoxp-', 'xoxr-', 'xoxs-', 'xapp-', 'xwfp-')]
        + [('provider_aws', prefix + 'F4KE' * 4) for prefix in ('AKIA', 'ASIA')]
        + [('provider_google', 'AIza' + ('F4ke' * 8) + 'A_9'),
           ('provider_gitlab', 'glpat-' + suffix),
           ('provider_huggingface', 'hf_' + suffix),
           ('provider_vercel', 'vck_' + suffix),
           ('provider_vercel', 'vcp_' + suffix)]
    )


class SecretDetection(unittest.TestCase):
    def assert_detected(self, text, rule):
        self.assertTrue(hafiza.contains_secret(text))
        self.assertIsNotNone(dict(hafiza.SECRET_RULES)[rule].search(text))
        self.assertIn(rule, yayinla.findings(text))

    def test_provider_prefixes_with_and_without_context(self):
        for rule, value in provider_examples():
            for template in ('{}', 'kanka bu anahtar: {}', 'Authorization: Bearer {}',
                             '"{}"', 'değer (`{}`).'):
                with self.subTest(rule=rule, template=template):
                    self.assert_detected(template.format(value), rule)

    def test_turkish_and_english_labels_and_separators(self):
        # One mixed group is sufficient WITH context; no provider prefix needed.
        value = grouped('abcd', 'efgh', 'q7rs')
        labels = ('anahtar', 'anahtarım', 'anahtarı', 'ANAHTARIM', 'ANAHTARINIZ',
                  'şifre', 'ŞİFRE', 'şifrem', 'şifreniz', 'sifre', 'parola', 'parolam',
                  'kurtarma kodu', 'kurtarma kodum', 'token', 'access token',
                  'api key', 'API_KEY', 'api-key', 'secret key', 'access key',
                  'secret', 'password', 'passwd', 'passphrase', 'key',
                  'recovery code', 'backup_code')
        separators = (': ', '=', ' ', ' - ', ' — ', ':\n', ': "', " = '", ' `')
        for label in labels:
            for separator in separators:
                with self.subTest(label=label, separator=separator):
                    self.assert_detected(label + separator + value, 'context_value')

    def test_context_value_boundaries_json_and_identifier_values(self):
        values = ('a1' * 6, 'Z8' * 32, 'F4ke_value_123', grouped('abcd', 'efgh', '1234'),
                  grouped('ab1c', '9x2y', 'q7'),
                  grouped('a1b2c3d4', 'e5f6', 'a7b8', 'c9d0', 'e1f2a3b4c5d6'),
                  'a1' * 20, 'b2' * 32)
        for value in values:
            for text in ('anahtar: ' + value, 'anahtar ' + value, '**anahtar:** `' + value + '`',
                         '**anahtar**: ' + value,
                         json.dumps({'anahtar': value}, ensure_ascii=False),
                         json.dumps({'secret': value})):
                with self.subTest(length=len(value), quoted=text.startswith('{')):
                    self.assert_detected(text, 'context_value')

    def test_grouped_codes_without_labels(self):
        values = (grouped('a1b', 'c2d', 'e3f'), grouped('ab1c', '9x2y', 'q7rs'),
                  grouped('a1b2c3d4', 'e5f6g7h8', 'i9j0k1l2'),
                  grouped('AB1C', '9X2Y', 'Q7RS', 'Z3MV'),
                  grouped('abcd', 'e1f2', 'g3h4'), grouped('a1b2', '1234', 'e5f6'),
                  grouped('a1b2', 'c3d4', 'efgh'))
        for value in values:
            for template in ('{}', '({})', '`{}`', '"{}"', 'Kod {}.'):
                with self.subTest(length=len(value), template=template):
                    self.assert_detected(template.format(value), 'grouped_key')

    def test_dates_slugs_paths_hashes_ids_prose_and_versions_are_not_secrets(self):
        mixed = grouped('ab1c', '9x2y', 'q7rs')
        negatives = (
            '2026-09-26', '2026-09-26T12:34:56Z', '2026-365-001',
            'jev-context-video', 'memory-apply-before-visual-production',
            'model-v123-preview', 'candidate-abc123-example', 'obs-2026-config',
            'release-123-abcdef', 'linux-x86-release',
            '/tmp/jev-context-video.md', 'araclar/hafiza.py', 'C:\\work\\notes.md',
            '/tmp/' + mixed, mixed + '/notes', mixed + '.md', 'notes.' + mixed,
            'C:\\work\\' + mixed, mixed + '\\notes',
            'a1' * 20, 'B2' * 32, 'sha256:' + 'f0' * 32, 'commit ' + 'a1' * 20,
            'a1b2c3d', 'v1.2.3', 'v1.2.3-45-gabc1234', '1.0.0-beta.2',
            grouped('a1b2c3d4', 'e5f6', 'a7b8', 'c9d0', 'e1f2a3b4c5d6'),
            grouped('550e8400', 'e29b', '41d4', 'a716', '446655440000'),
            'Bu Türkçe cümlede anahtar kelime tercihidir.',
            'anahtar kelime: ' + 'a1' * 8,
            'Şifreleme algoritması ' + 'a1' * 8,
            'anahtarlık: ' + 'a1' * 8, 'tokenizer: ' + 'a1' * 8,
            'secretary: ' + 'a1' * 8, 'passwordless: ' + 'a1' * 8,
            'anahtar: ' + 'a1' * 5 + 'a', 'anahtar: abcdefghijklmnop',
            'anahtar: 1234567890123456', 'anahtar: /tmp/' + mixed,
            'anahtar: ' + mixed + '.json', 'anahtar: jev-context-video',
            grouped('a1', 'b2c3', 'd4e5'), grouped('a1b2', 'c3d4'),
            grouped('a1b2c3d4e', 'f5g6', 'h7i8'),
            grouped('a1b2', 'c3d4', 'e5f6g7h8i'),
            grouped('abcdef', 'ghijkl', 'mnopqr'), grouped('1234', '5678', '9012'),
            grouped('abcd', 'efgh', 'q7rs'),  # Ambiguous without a label.
            'anahtar kelime', 'şifreleme', 'SECRET_PATTERNS',
            'sk-short', 'ghp_example', 'github_pat_example', 'xoxb-example',
            'AKIA' + 'A' * 15, 'ASIA' + 'A' * 17, 'AIza' + 'A' * 34,
            'glpat-example', 'hf_example', 'vck_example', 'vcp_example',
        )
        for index, text in enumerate(negatives):
            with self.subTest(index=index):
                self.assertFalse(hafiza.contains_secret(text))
                self.assertEqual(yayinla.findings(text), [])

    def test_existing_short_assignment_protection_and_private_keys(self):
        for label in ('api_key', 'token', 'parola', 'şifre'):
            self.assertTrue(hafiza.contains_secret(label + '=short'))
        for kind in ('', 'RSA ', 'EC ', 'OPENSSH ', 'ENCRYPTED '):
            self.assert_detected('-----BEGIN ' + kind + 'PRIVATE' + ' KEY-----', 'private_key')

    def test_publication_rejects_without_exposing_values(self):
        values = [v for _, v in provider_examples()]
        values += ['anahtar: ' + 'a1' * 6, grouped('ab1c', '9x2y', 'q7rs')]
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for value in values:
                (repo / 'note.md').write_text(value, encoding='utf-8')
                with self.assertRaises(ValueError) as error:
                    yayinla.scan(repo, ['note.md'])
                self.assertNotIn(value, str(error.exception))
                self.assertIn('publication scan rejected file: note.md', str(error.exception))

    def test_candidate_gate_rejects_new_shapes(self):
        with tempfile.TemporaryDirectory() as temp:
            vault = Path(temp)
            for statement in ('kanka bu anahtar: ' + grouped('abcd', 'efgh', 'q7rs'),
                              grouped('ab1c', '9x2y', 'q7rs'), 'vck_' + 'F4ke' * 8):
                with self.assertRaisesRegex(ValueError, 'gizli bilgi'):
                    hafiza.add_candidate(vault, statement=statement, kind='semantic', scope='user',
                                         subject_key='test', source_path='note.md', source_anchor='test',
                                         confidence='explicit-user', sensitivity='normal', proposed_by='test')
                self.assertFalse((vault / hafiza.CANDIDATE_PATH).exists())


if __name__ == '__main__':
    unittest.main()
