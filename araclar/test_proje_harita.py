"""Synthetic project map tests; no personal vault content."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proje_harita as maps


class ProjectMap(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'komuta').mkdir()
        (self.vault / 'zihin').mkdir()
        (self.vault / 'gelen-kutusu/codex-oturumları').mkdir(parents=True)
        (self.vault / 'gelen-kutusu/ajan-oturumlari/.state').mkdir(parents=True)
        self.today = dt.date(2026, 9, 24)
        self.projects = [dict(id='atlas', aliases=['atlas'], roots=['/workspace/atlas']),
                         dict(id='old', aliases=['old'], roots=['/workspace/old'])]
        (self.vault / 'komuta/gorev-baglam.json').write_text(
            json.dumps(dict(projects=self.projects)), encoding='utf-8')
        (self.vault / 'Ana Sayfa.md').write_text('# İnsan ana sayfası\n\nKalıcı metin.\n', encoding='utf-8')

    def task(self, **extra):
        data = dict(id='one', title='atlas planı', status='active',
                    next_step='atlas adımını yap', source_path='gelen-kutusu/kaynak.md',
                    updated_at='2026-09-23T10:00:00+00:00')
        data.update(extra)
        (self.vault / 'zihin/is-durumu.jsonl').write_text(json.dumps(data) + '\n', encoding='utf-8')

    def test_build_idempotent_preserves_human_text_and_maps_task(self):
        self.task()
        folder = self.vault / 'projeler/atlas'
        folder.mkdir(parents=True)
        path = folder / 'DURUM.md'
        path.write_text('# İnsan başlığı\n\nÖzel açıklama.\n', encoding='utf-8')
        plan = maps.build(self.vault, today=self.today)
        self.assertEqual(next(p['action'] for p in plan['files'] if p['path'].endswith('atlas/DURUM.md')), 'change')
        self.assertEqual(path.read_text(), '# İnsan başlığı\n\nÖzel açıklama.\n')
        maps.build(self.vault, write=True, today=self.today)
        first = {p: p.read_bytes() for p in (path, self.vault / 'Ana Sayfa.md')}
        again = maps.build(self.vault, write=True, today=self.today)
        self.assertTrue(all(x['action'] == 'same' for x in again['files']))
        self.assertEqual(first, {p: p.read_bytes() for p in first})
        self.assertTrue(path.read_text().startswith('# İnsan başlığı\n\nÖzel açıklama.\n'))
        self.assertIn('olası · atlas planı', path.read_text())
        self.assertIn('Kalıcı metin.', (self.vault / 'Ana Sayfa.md').read_text())

    def test_explicit_project_wins_and_old_project_is_archive_candidate(self):
        self.task(project_id='old')
        result = maps.build(self.vault, write=True, today=self.today)
        atlas = (self.vault / 'projeler/atlas/DURUM.md').read_text()
        old = (self.vault / 'projeler/old/DURUM.md').read_text()
        self.assertNotIn('atlas planı (active)', atlas)
        self.assertIn('atlas planı (active)', old)
        self.assertNotIn('olası · atlas planı', old)
        self.assertEqual(next(p['open_tasks'] for p in result['projects'] if p['id'] == 'atlas'), 0)
        self.assertIn('arşiv adayı', atlas)

    def test_receipt_and_activity_then_archives_after_thirty_days(self):
        receipt = self.vault / 'gelen-kutusu/codex-oturumları/example.md'
        receipt.write_text('# Oturum — 2026-09-20\n\natlas üzerinde çalışma\n', encoding='utf-8')
        result = maps.build(self.vault, write=True, today=self.today)
        self.assertEqual(result['projects'][0]['receipts'], 1)
        self.assertEqual(result['projects'][0]['status'], 'aktif')
        self.assertIn('[[gelen-kutusu/codex-oturumları/example]]',
                      (self.vault / 'projeler/atlas/DURUM.md').read_text())
        result = maps.build(self.vault, write=True, today=dt.date(2026, 11, 1))
        self.assertEqual(result['projects'][0]['status'], 'arşiv adayı')

    def test_claude_cwd_and_project_note_are_linked(self):
        folder = self.vault / 'gelen-kutusu/ajan-oturumlari'
        (folder / 'sample.json').write_text(json.dumps(dict(
            summary='Work completed', reviewed_ns=1790157600000000000)), encoding='utf-8')
        (folder / '.state/sample.json').write_text(json.dumps(dict(
            client='claude', count=6,
            path='/users/example/.claude/projects/-workspace-atlas/session.jsonl')),
            encoding='utf-8')
        with patch.object(maps.bilgi_agi, '_rows', return_value=([
                dict(id='rule', title='Project rule', scope='project:atlas')], [])):
            result = maps.build(self.vault, write=True, today=self.today)
        self.assertEqual(result['projects'][0]['receipts'], 1)
        self.assertEqual(result['projects'][0]['notes'], 1)
        body = (self.vault / 'projeler/atlas/DURUM.md').read_text()
        self.assertIn('[[bilgi/rule]]', body)
        self.assertIn('[[gelen-kutusu/ajan-oturumlari/sample]]', body)

    def test_claude_encoded_root_keeps_literal_hyphens(self):
        project = dict(id='hyphen', aliases=['other'], roots=['/workspace/a-b'])
        self.assertTrue(maps._claude_root_score(
            '/users/example/.claude/projects/-workspace-a-b/session.jsonl', project))

    def test_detect_candidate_rejects_home_single_session_and_filters_secret(self):
        when = self.today
        items = [dict(cwd='/workspace/new/a', date=when, first='Plan next work', source='a'),
                 dict(cwd='/workspace/new/b', date=when, first='sk-' + 'x' * 30, source='b'),
                 dict(cwd=str(Path.home()), date=when, first='Home work', source='home1'),
                 dict(cwd=str(Path.home()), date=when, first='Home work', source='home2'),
                 dict(cwd='/workspace/solo', date=when, first='Only one', source='solo'),
                 dict(cwd='/workspace/atlas', date=when, first='Registered', source='known1'),
                 dict(cwd='/workspace/atlas', date=when, first='Registered', source='known2'),
                 dict(cwd='/users/example/scratch/workspaces/build', date=when,
                      first='Temporary', source='tmp1'),
                 dict(cwd='/users/example/scratch/workspaces/build', date=when,
                      first='Temporary', source='tmp2')]
        result = maps.detect(self.vault, write=True,
                             now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc), sessions=items)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['root'], '/workspace/new')
        self.assertEqual(result['candidates'][0]['sessions'], 2)
        view = (self.vault / 'komuta/proje-adaylari.md').read_text()
        self.assertNotIn('sk-' + 'x' * 30, view)
        self.assertFalse((self.vault / 'komuta/gorev-baglam.json').read_text().find('new') >= 0)


if __name__ == '__main__':
    unittest.main()
