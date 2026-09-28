"""Synthetic project map tests; no personal vault content."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import proje_harita as maps


def absolute(posix):
    """Platform-absolute fixture path; unchanged on POSIX, drive-rooted on Windows."""
    return str(Path(Path.cwd().anchor, *posix.strip('/').split('/')))


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
        self.projects = [dict(id='atlas', aliases=['atlas'], roots=[absolute('/workspace/atlas')]),
                         dict(id='old', aliases=['old'], roots=[absolute('/workspace/old')])]
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

    def test_receipt_line_shows_summary_not_header(self):
        receipt = self.vault / 'gelen-kutusu/codex-oturumları/example.md'
        receipt.write_text('# Oturum — 2026-09-20\n\n<!-- codex-receipt:x -->\n\nDurum: görev özeti.\n\n'
                           'atlas testleri düzeltildi\n', encoding='utf-8')
        maps.build(self.vault, write=True, today=self.today)
        page = (self.vault / 'projeler/atlas/DURUM.md').read_text()
        self.assertIn('· atlas testleri düzeltildi', page)
        self.assertNotIn('· # Oturum', page)

    def test_archived_project_without_page_gets_no_folder(self):
        self.projects[1]['status'] = 'archived'
        (self.vault / 'komuta/gorev-baglam.json').write_text(
            json.dumps(dict(projects=self.projects)), encoding='utf-8')
        maps.build(self.vault, write=True, today=self.today)
        self.assertFalse((self.vault / 'projeler/old').exists())
        home = (self.vault / 'Ana Sayfa.md').read_text()
        self.assertIn('- old · ', home)
        self.assertNotIn('[[projeler/old/DURUM]]', home)
        (self.vault / 'projeler/old').mkdir()
        (self.vault / 'projeler/old/DURUM.md').write_text('# eski\n', encoding='utf-8')
        maps.build(self.vault, write=True, today=self.today)
        self.assertIn('[[projeler/old/DURUM]]', (self.vault / 'Ana Sayfa.md').read_text())

    def test_claude_cwd_and_project_note_are_linked(self):
        folder = self.vault / 'gelen-kutusu/ajan-oturumlari'
        (folder / 'sample.json').write_text(json.dumps(dict(
            summary='Work completed', reviewed_ns=1790157600000000000)), encoding='utf-8')
        (folder / '.state/sample.json').write_text(json.dumps(dict(
            client='claude', count=6,
            path='/users/example/.claude/projects/' + maps._claude_encoded(absolute('/workspace/atlas'))
                 + '/session.jsonl')),
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
        self.assertEqual(maps._claude_encoded('/workspace/a-b'), '-workspace-a-b')
        project = dict(id='hyphen', aliases=['other'], roots=[absolute('/workspace/a-b')])
        self.assertTrue(maps._claude_root_score(
            '/users/example/.claude/projects/' + maps._claude_encoded(absolute('/workspace/a-b'))
            + '/session.jsonl', project))

    def test_detect_candidate_rejects_home_single_session_and_filters_secret(self):
        when = self.today
        items = [dict(cwd=absolute('/workspace/new/a'), date=when, first='Plan next work', source='a'),
                 dict(cwd=absolute('/workspace/new/b'), date=when, first='sk-' + 'x' * 30, source='b'),
                 dict(cwd=str(Path.home()), date=when, first='Home work', source='home1'),
                 dict(cwd=str(Path.home()), date=when, first='Home work', source='home2'),
                 dict(cwd=absolute('/workspace/solo'), date=when, first='Only one', source='solo'),
                 dict(cwd=absolute('/workspace/atlas'), date=when, first='Registered', source='known1'),
                 dict(cwd=absolute('/workspace/atlas'), date=when, first='Registered', source='known2'),
                 dict(cwd=absolute('/users/example/scratch/workspaces/build'), date=when,
                      first='Temporary', source='tmp1'),
                 dict(cwd=absolute('/users/example/scratch/workspaces/build'), date=when,
                      first='Temporary', source='tmp2')]
        result = maps.detect(self.vault, write=True,
                             now=dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc), sessions=items)
        self.assertEqual(len(result['candidates']), 1)
        self.assertEqual(result['candidates'][0]['root'], absolute('/workspace/new'))
        self.assertEqual(result['candidates'][0]['sessions'], 2)
        view = (self.vault / 'komuta/proje-adaylari.md').read_text()
        self.assertNotIn('sk-' + 'x' * 30, view)
        self.assertFalse((self.vault / 'komuta/gorev-baglam.json').read_text().find('new') >= 0)


if __name__ == '__main__':
    unittest.main()
