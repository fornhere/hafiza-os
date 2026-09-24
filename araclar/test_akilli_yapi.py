"""Synthetic stage-one project and scope regression tests."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import client_sessions
import codex_hafiza
import hafiza
import is_ve_ders
import proje_harita


class SmartStructure(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'komuta').mkdir()
        self.projects = [dict(id='jev', aliases=['jev'], roots=['/workspace/Jev'], status='active'),
                         dict(id='twitter', aliases=['tweet'], roots=['/workspace/Twitter'], status='active'),
                         dict(id='old', aliases=['old'], roots=['/workspace/Old'], status='archived')]
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': self.projects}))

    def test_map_event_time_and_unique_alias_with_explicit_id(self):
        inbox = self.vault / 'gelen-kutusu/codex-oturumları'
        inbox.mkdir(parents=True)
        (inbox / 'one.md').write_text('# Codex görev makbuzu — 2026-09-24\n\nJev üzerinde çalışma\n')
        events = self.vault / 'günlük/hafıza-olayları.jsonl'
        events.parent.mkdir()
        events.write_text(json.dumps({'event_type': 'session.inspected.v2',
            'receipt_path': 'gelen-kutusu/codex-oturumları/one.md',
            'last_modified': dt.datetime(2026, 9, 5, tzinfo=dt.timezone.utc).timestamp()}) + '\n')
        rows = [{'id': 'ambiguous', 'title': 'Jev tweet', 'status': 'active'},
                {'id': 'explicit', 'title': 'Explicit Jev tweet', 'status': 'active', 'project_id': 'jev'},
                {'id': 'archived', 'title': 'old task', 'status': 'active', 'project_id': 'old'}]
        with patch.object(is_ve_ders, 'latest', return_value={r['id']: r for r in rows}):
            result = proje_harita.build(self.vault, write=True, today=dt.date(2026, 9, 24))
        jev = (self.vault / 'projeler/jev/DURUM.md').read_text()
        twitter = (self.vault / 'projeler/twitter/DURUM.md').read_text()
        self.assertIn('Explicit Jev tweet (active)', jev)
        self.assertNotIn('Jev tweet (active) ·', jev.replace('Explicit Jev tweet (active) ·', ''))
        self.assertNotIn('Explicit Jev tweet (active)', twitter)
        self.assertIn('Son etkinlik: 2026-09-05', jev)
        self.assertEqual('arşiv', next(p['status'] for p in result['projects'] if p['id'] == 'old'))

    def test_claude_encoding_and_temporary_roots(self):
        project = dict(roots=['/users/example/Hafıza/ikinci beyin'])
        self.assertGreater(proje_harita._claude_root_score(
            '/u/.claude/projects/-users-example-Haf-za-ikinci-beyin/session.jsonl', project), 0)
        home = self.vault / 'home user'
        actual = home / 'Hafıza' / 'ikinci beyin'
        actual.mkdir(parents=True)
        encoded = proje_harita._claude_encoded(str(actual))
        with patch.object(Path, 'home', return_value=home):
            self.assertEqual(str(actual), proje_harita._claude_cwd(
                '/u/.claude/projects/' + encoded + '/session.jsonl'))
        for path in ('/users/example/Documents/Codex/2026-09-24/kan', '/tmp/work',
                     '/users/example/scratchpad/project',
                     '/users/example/.config/Claude/scratch-workspaces/session'):
            self.assertIsNone(proje_harita._candidate_root(path))

    def test_generated_note_block_is_not_searched(self):
        note = self.vault / 'komuta/note.md'
        note.write_text('# İnsan notu\n\nözgün bilgi\n\n'
            '<!-- hafiza-os:proje-uretilmis:basla -->\n'
            '## gizli başlık\n\nüretilmiş sözcük\n'
            '<!-- hafiza-os:proje-uretilmis:bitir -->\n')
        self.assertFalse(hafiza.search_notes(self.vault, 'üretilmiş', uris=['komuta']))
        self.assertTrue(hafiza.search_notes(self.vault, 'özgün', uris=['komuta']))
        note.write_text('```md\n<!-- hafiza-os:örnek:basla -->\n```\n\ninsan devamı\n')
        self.assertTrue(hafiza.search_notes(self.vault, 'insan devamı', uris=['komuta']))

    def test_task_project_id_must_exist(self):
        (self.vault / 'source.md').write_text('Bu kaynakta iş kanıtı açıkça yazılıdır.')
        row = dict(id='one', title='iş', status='active', next_step='devam',
                   source_path='source.md', evidence='iş kanıtı açıkça', actor='test',
                   last_verified=dt.date.today().isoformat())
        with self.assertRaisesRegex(ValueError, 'project_id'):
            is_ve_ders.put(self.vault, 'task', dict(row, project_id='missing'))
        self.assertEqual('old', is_ve_ders.put(self.vault, 'task', dict(row, project_id='old'))['project_id'])
        self.assertEqual([], is_ve_ders.brief(self.vault))

    def test_candidate_scope_active_archived_invalid_and_user(self):
        source = {'entries': [{'role': 'user', 'quote': 'Kullanıcı proje kuralını açıkça seçti.'}]}
        candidate = dict(statement='Kullanıcı proje kuralını kalıcı olarak seçti.',
                         subject_key='project.rule', evidence='Kullanıcı proje kuralını açıkça seçti.')
        for scope, accepted in [('project:jev', True), ('project:old', False),
                                ('project:missing', False), ('bad', False), ('user', True)]:
            result = client_sessions.semantic_results({'decision': 'record',
                'semantic_candidates': [dict(candidate, scope=scope)]}, source, self.vault)[0]
            self.assertEqual('accepted' if accepted else 'rejected', result['status'])
            if not accepted:
                self.assertIn('invalid_scope', result['reasons'])
        with patch('capture_source.record_gate'):
            with self.assertRaisesRegex(ValueError, 'invalid_scope'):
                codex_hafiza.record(self.vault, 's', 't', 'Yeterince uzun bir kaynaklı görev özeti yazıldı.',
                                    [dict(candidate, scope='project:old')])


if __name__ == '__main__':
    unittest.main()
