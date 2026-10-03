"""Türetilmiş görünüm: geçici kasa, gerçek kanıtlara veya servislere yazım yok."""
from contextlib import redirect_stderr
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import client_review
import oturum_gorunumu as views
from client_transcripts import SourceError


class SessionViews(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name) / 'vault'
        self.root = self.vault / views.INBOX
        self.root.mkdir(parents=True)
        (self.root / '.state').mkdir()
        self.home = self.vault / 'Ana Sayfa.md'
        self.home.write_text('# Merkez\n\nMevcut içerik.\n', encoding='utf-8')

    def receipt(self, key='one', **updates):
        ident = hashlib.sha256(key.encode()).hexdigest()
        data = dict(id=ident, decision='record', meaningful=True,
                    summary='Yerel uygulama tamamlandı ve sonuç doğrulama bekliyor.',
                    reviewed_ns=1_790_000_000_000_000_000, semantic_candidates=[])
        data.update(updates)
        path = self.root / (ident + '.json')
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return ident

    def project(self, ident, center='DURUM', aliases=()):
        folder = self.vault / 'projeler' / ident
        folder.mkdir(parents=True)
        if center:
            (folder / (center + '.md')).write_text('# Proje merkezi\n', encoding='utf-8')
        config = self.vault / 'komuta/gorev-baglam.json'
        config.parent.mkdir(exist_ok=True)
        data = json.loads(config.read_text()) if config.exists() else {'projects': []}
        data['projects'].append({'id': ident, 'aliases': list(aliases)})
        config.write_text(json.dumps(data), encoding='utf-8')

    def note(self, ident):
        return next(p for p in (self.vault / views.OUTPUT).glob('*.md')
                    if views.frontmatter_id(p.read_text(encoding='utf-8')) == ident)

    def snapshot(self, root=None):
        return {str(p.relative_to(self.vault)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root or self.vault).rglob('*') if p.is_file()}

    def test_dry_run_and_idempotence_title_changes_keep_path(self):
        ident = self.receipt()
        before = self.snapshot()
        report = views.render(self.vault)
        self.assertEqual(report['view_actions'], {'create': 1})
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.vault / views.OUTPUT).exists())
        views.render(self.vault, True)
        first = self.snapshot()
        original = self.note(ident)
        report = views.render(self.vault, True)
        self.assertEqual(report['view_actions'], {'unchanged': 1})
        self.assertEqual(first, self.snapshot())
        self.receipt(summary='Başlık değişti ama aynı kaydın dosyası korunmalı.')
        views.render(self.vault, True)
        self.assertEqual(original, self.note(ident))
        self.assertIn('Başlık değişti', original.read_text())
        self.assertEqual(len(list((self.vault / views.OUTPUT).glob('*.md'))), 2)
        self.assertEqual(self.home.read_text().count(views.HOME_LINK), 1)

    def test_collisions_and_later_records_keep_names(self):
        ids = [self.receipt(k) for k in ('one', 'two')]
        views.render(self.vault, True)
        names = {ident: self.note(ident).name for ident in ids}
        self.assertEqual(len(set(names.values())), 2)
        self.assertTrue(any(ident[:8] in names[ident] for ident in ids))
        ident = self.receipt('three')
        views.render(self.vault, True)
        self.assertEqual(names, {i: self.note(i).name for i in ids})
        self.assertNotIn(self.note(ident).name, names.values())

    def test_scope_first_multiple_centers_and_missing_center_report(self):
        self.project('kanal', aliases=('afiş', 'logo'))
        self.project('atlas', center='OKU')
        self.project('missing', center=None)
        ident = self.receipt(summary='Atlas hakkında ayrıca konuşuldu ve test çalıştırıldı.',
                            semantic_candidates=[{'scope': 'project:kanal'},
                                                 {'scope': 'project:missing'}])
        report = views.render(self.vault, True)
        text = self.note(ident).read_text()
        self.assertIn('[[projeler/kanal/DURUM]]', text)
        self.assertNotIn('[[projeler/atlas/OKU]]', text)
        self.assertNotIn('[[projeler/missing/', text)
        self.assertEqual(report['missing_centers'], {'missing': 1})
        self.assertEqual(report['projects'], {'kanal': 1})
        self.assertFalse(list((self.vault / 'projeler/missing').glob('*.md')))
        self.receipt('both', semantic_candidates=[{'scope': 'project:kanal'}, {'scope': 'project:atlas'}])
        report = views.render(self.vault, True)
        self.assertEqual(report['linked_notes'], 2)
        self.assertEqual(report['projects'], {'atlas': 1, 'kanal': 2})

    def test_conservative_summary_matching_and_ambiguity(self):
        self.project('kanal', aliases=('afiş', 'logo', 'pazar radarı'))
        self.project('atlas')
        named = self.receipt('named', summary='Kanal yayın hazırlığı tamamlandı ve kullanıcı incelemesi bekleniyor.')
        alias = self.receipt('alias', summary='Pazar radarı çalışması tamamlandı ve sonuç incelemesi bekleniyor.')
        weak = self.receipt('weak', summary='Afiş için dosya hazırlığı tamamlandı ve inceleme bekleniyor.')
        unknown = self.receipt('unknown')
        ambiguous = self.receipt('ambiguous', summary='Atlas ve Kanal birlikte değerlendirildi ve sonuç yazıldı.')
        report = views.render(self.vault, True)
        for ident in (named, alias):
            self.assertIn('[[projeler/kanal/DURUM]]', self.note(ident).read_text())
        for ident in (weak, unknown, ambiguous):
            self.assertNotIn('Proje merkezi:', self.note(ident).read_text())
        self.assertEqual(report['linked_notes'], 2)

    def test_folder_name_without_config_and_preferred_center(self):
        folder = self.vault / 'projeler/defne'
        folder.mkdir(parents=True)
        (folder / 'index.md').write_text('# Defne')
        (folder / 'DURUM.md').write_text('# Durum')
        ident = self.receipt(summary='Defne çalışmasında yeni sonuç elde edildi ve doğrulandı.')
        views.render(self.vault, True)
        self.assertIn('[[projeler/defne/index]]', self.note(ident).read_text())

    def mapping(self, data):
        path = self.vault / views.PROJECT_MAPPING
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def test_manual_mapping_replaces_scope_and_preserves_other_automatic_matches(self):
        for project in ('kanal', 'atlas', 'nova'):
            self.project(project)
        ident = self.receipt(semantic_candidates=[{'scope': 'project:kanal'}])
        automatic = self.receipt('automatic', summary='Kanal yayın hazırlığı tamamlandı.')
        path = self.mapping({ident: ['atlas', 'nova', 'nova']})
        before = path.read_bytes()
        report = views.render(self.vault)
        self.assertFalse(list(path.parent.glob('*.md')))
        self.assertEqual(report['matching'], {'manual': 1, 'summary': 1})
        views.render(self.vault, True)
        text = self.note(ident).read_text()
        self.assertIn('projeler: ["atlas", "nova"]', text)
        self.assertIn('[[projeler/nova/DURUM]]', text)
        self.assertIn('[[projeler/atlas/DURUM]]', text)
        self.assertNotIn('[[projeler/kanal/DURUM]]', text)
        self.assertIn('[[projeler/kanal/DURUM]]', self.note(automatic).read_text())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(views.render(self.vault, True)['view_actions'], {'unchanged': 2})

    def test_empty_manual_mapping_intentionally_leaves_session_unlinked(self):
        self.project('kanal')
        ident = self.receipt(summary='Kanal yayın hazırlığı tamamlandı.',
                             semantic_candidates=[{'scope': 'project:kanal'}])
        views.render(self.vault, True)
        self.mapping({ident: []})
        report = views.render(self.vault, True)
        text = self.note(ident).read_text()
        self.assertIn('projeler: []', text)
        self.assertNotIn('Proje merkezi:', text)
        self.assertEqual(report['linked_notes'], 0)
        self.assertEqual(report['matching'], {'manual': 1})

    def test_manual_mapping_ignores_invalid_projects_warns_without_fallback(self):
        self.project('kanal')
        self.project('missing', center=None)
        ident = self.receipt(summary='Kanal yayın hazırlığı tamamlandı.')
        self.mapping({ident: ['missing', 'unknown', '../kanal', 'kanal']})
        with redirect_stderr(io.StringIO()) as stderr:
            report = views.render(self.vault, True)
        self.assertEqual(report['projects'], {'kanal': 1})
        self.assertEqual(report['missing_centers'], {})
        self.assertIn('projeler: ["kanal"]', self.note(ident).read_text())
        for name in ('missing', 'unknown', '../kanal'):
            self.assertIn(json.dumps(name), stderr.getvalue())
        self.mapping({ident: ['unknown']})
        with redirect_stderr(io.StringIO()):
            views.render(self.vault, True)
        self.assertIn('projeler: []', self.note(ident).read_text())
        self.assertNotIn('Proje merkezi:', self.note(ident).read_text())

    def test_invalid_manual_mapping_stops_before_writing(self):
        ident = self.receipt()
        views.render(self.vault, True)
        for data in ({ident: 'kanal'}, {ident: [None]}, {'bad-id': []}, []):
            with self.subTest(data=data):
                self.mapping(data)
                before = self.snapshot()
                with self.assertRaises(SourceError):
                    views.render(self.vault, True)
                self.assertEqual(before, self.snapshot())

    def test_symlink_manual_mapping_rejected(self):
        self.receipt()
        outside = Path(self.temp.name) / 'mapping.json'
        outside.write_text('{}')
        path = self.vault / views.PROJECT_MAPPING
        path.parent.mkdir(parents=True)
        path.symlink_to(outside)
        with self.assertRaisesRegex(SourceError, 'symlink_rejected'):
            views.render(self.vault, True)

    def test_dizi_requires_project_context_not_tweet_series(self):
        self.project('dizi')
        tweet = self.receipt('tweets', summary='Sekiz tweetlik dizi hazırlandı ve paylaşım kullanıcıya bırakıldı.')
        film = self.receipt('film', summary='AI dizi projesinde backlog hazırlanıp kullanıcıya teslim edildi.')
        report = views.render(self.vault, True)
        self.assertNotIn('Proje merkezi:', self.note(tweet).read_text())
        self.assertIn('[[projeler/dizi/DURUM]]', self.note(film).read_text())
        self.assertEqual(report['linked_notes'], 1)

    def test_skip_excluded_privacy_and_secrets_are_not_written(self):
        self.receipt('skip', decision='skip')
        self.receipt('false', meaningful=False)
        self.receipt('literal', meaningful=1)
        ident = self.receipt('excluded')
        (self.root / '.state' / (ident + '.json')).write_text(json.dumps(
            {'client': 'claude', 'session': 'fixture-session', 'path': '/nonexistent/transcript.jsonl'}))
        policy = self.root / '.state/context-fixture.json'
        policy.write_text(json.dumps({'client': 'claude', 'session': 'fixture-session', 'excluded': True}))
        self.receipt('privacy', summary='Bu oturumu kaydetme')
        self.receipt('secret', summary='Yerel sonuç api_key=fixture-secret-value içeriyor ve tamamlandı.')
        report = views.render(self.vault, True)
        self.assertEqual(report['notes'], 0)
        self.assertEqual(report['skip_reasons'], {'decision_not_record': 1, 'not_meaningful': 2,
                         'excluded_privacy': 1, 'privacy_text': 1, 'secret_pattern': 1})
        self.assertEqual(len(list((self.vault / views.OUTPUT).glob('*.md'))), 1)

    def test_later_exclusion_removes_only_derived_view_and_index_link(self):
        ident = self.receipt(client='claude', session='fixture')
        views.render(self.vault, True)
        view = self.note(ident)
        (self.root / '.state/context-fixture.json').write_text(json.dumps(
            {'client': 'claude', 'session': 'fixture', 'privacy': True}))
        evidence = self.snapshot(self.root)
        report = views.render(self.vault)
        self.assertTrue(view.exists())
        self.assertEqual(report['view_actions'], {'remove': 1})
        views.render(self.vault, True)
        self.assertFalse(view.exists())
        self.assertNotIn(ident, (self.vault / views.INDEX).read_text())
        self.assertEqual(evidence, self.snapshot(self.root))

    def test_evidence_hashes_unchanged_and_only_existing_user_text(self):
        ident = self.receipt(semantic_candidates=[{'statement': 'Kullanıcı kısa özet ister.',
                                                 'evidence': 'Özeti kısa yaz.'}])
        source = self.root / (ident + '.md')
        source.write_text('# Oturum\n\n## Kullanıcı beyanı 1\n\nKullanıcı kısa özet ister.\n\n'
                          'Kullanıcı beyanı:\n\nÖzeti kısa yaz.\n', encoding='utf-8')
        (self.root / '.state' / (ident + '.json')).write_text(json.dumps(
            {'client': 'claude', 'session': 'fixture', 'path': '/DO_NOT_READ/raw.jsonl'}))
        before = self.snapshot(self.root)
        original_read = views.read_bytes
        def guarded_read(path, *args):
            self.assertTrue(Path(path).is_relative_to(self.vault))
            self.assertNotEqual(Path(path).suffix, '.jsonl')
            return original_read(path, *args)
        with patch.object(views, 'read_bytes', side_effect=guarded_read):
            views.render(self.vault, True)
        self.assertEqual(before, self.snapshot(self.root))
        text = self.note(ident).read_text()
        self.assertIn('istemci: "claude"', text)
        self.assertIn(f'Kaynak: [[{views.INBOX.as_posix()}/{ident}]]', text)
        self.assertEqual(text.count('Özeti kısa yaz.'), 1)
        self.assertIn('kanonik: false', text)

    def test_secret_in_note_blocks_whole_record(self):
        ident = self.receipt()
        (self.root / (ident + '.md')).write_text('## Kullanıcı beyanı 1\n\napi_key=fixture-secret-value\n')
        report = views.render(self.vault, True)
        self.assertEqual(report['notes'], 0)
        self.assertEqual(report['skip_reasons'], {'secret_pattern': 1})

    def test_index_months_all_links_and_home_single_appended_line(self):
        before = self.home.read_bytes()
        ids = [self.receipt(), self.receipt('later', reviewed_ns=1_793_000_000_000_000_000)]
        views.render(self.vault, True)
        text = (self.vault / views.INDEX).read_text()
        for ident in ids:
            note = self.note(ident)
            self.assertIn('[[' + note.relative_to(self.vault).with_suffix('').as_posix() + ']]', text)
            self.assertIn('Günlük merkezi: ' + views.HOME_LINK, note.read_text())
        self.assertIn('## 2026-09', text)
        self.assertIn('## 2026-10', text)
        self.assertLess(text.index('## 2026-10'), text.index('## 2026-09'))
        self.assertIn('[[Ana Sayfa]]', text)
        self.assertEqual(self.home.read_bytes(), before + ('- ' + views.HOME_LINK + '\n').encode())

    @unittest.skipUnless(hasattr(time, 'tzset'), 'tzset POSIX gerektirir')
    def test_reviewed_ns_uses_local_date(self):
        previous = os.environ.get('TZ')
        try:
            os.environ['TZ'] = 'Europe/Istanbul'
            time.tzset()
            reviewed = int(datetime.fromisoformat('2026-09-24T22:30:00+00:00').timestamp())
            ident = self.receipt(reviewed_ns=reviewed * 1_000_000_000)
            views.render(self.vault, True)
            self.assertTrue(self.note(ident).name.startswith('2026-09-25 '))
        finally:
            if previous is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = previous
            time.tzset()

    def test_unicode_filename_budget(self):
        ident = self.receipt(summary=('Ş' * 32 + ' ') * 7)
        views.render(self.vault, True)
        self.assertLessEqual(len(self.note(ident).name.encode()), 255)
        for summary in ('İş tamamlandı.', ('Ş' * 32 + ' ') * 7):
            title = views.short_title(summary)
            self.assertGreaterEqual(len(title.split()), 4)
            self.assertLessEqual(len(title.split()), 7)

    def test_symlink_output_rejected_without_external_write(self):
        self.receipt()
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.vault / 'günlük').mkdir()
        (self.vault / views.OUTPUT).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(SourceError, 'symlink_rejected'):
            views.render(self.vault, True)
        self.assertEqual(list(outside.iterdir()), [])

    def test_cli_dry_run(self):
        self.receipt()
        before = self.snapshot()
        process = subprocess.run([sys.executable, '-X', 'utf8', views.__file__, 'render',
                                  '--vault', str(self.vault)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['notes'], 1)
        self.assertEqual(before, self.snapshot())


class ReviewIntegration(unittest.TestCase):
    def test_successful_record_triggers_render_and_errors_do_not_fail_review(self):
        for error in (None, OSError('sensitive fixture detail')):
            with self.subTest(error=bool(error)), \
                 patch.object(client_review, 'pending', return_value=[{'id': 'fixture', 'status': 'pending'}]), \
                 patch.object(client_review, 'packet', return_value={}), \
                 patch.object(client_review, 'invoke', return_value={}), \
                 patch.object(client_review, 'review', return_value={'id': 'fixture', 'status': 'record'}), \
                 patch.object(views, 'render', side_effect=error) as render, \
                 redirect_stderr(io.StringIO()) as stderr:
                result = client_review.run(Path('/unused'), ['fixture'], apply=True)
                self.assertEqual(result, [{'id': 'fixture', 'status': 'record'}])
                render.assert_called_once_with(Path('/unused'), apply=True)
                if error:
                    self.assertIn('oturum_gorunumu render başarısız: OSError', stderr.getvalue())
                    self.assertNotIn('sensitive fixture detail', stderr.getvalue())

    def test_skip_does_not_render(self):
        with patch.object(client_review, 'pending', return_value=[{'id': 'fixture', 'status': 'pending'}]), \
             patch.object(client_review, 'packet', return_value={}), \
             patch.object(client_review, 'invoke', return_value={}), \
             patch.object(client_review, 'review', return_value={'id': 'fixture', 'status': 'skip'}), \
             patch.object(views, 'render') as render:
            self.assertEqual(client_review.run(Path('/unused'), ['fixture'], apply=True)[0]['status'], 'skip')
            render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
