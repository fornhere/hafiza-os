"""Geçici kasalarda salt okunur kapsam denetimi regresyonları."""

import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import hafiza
import kayit_denetimi as audit
import konsolidasyon


class ScopeAudit(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name)
        self.registry = self.vault / 'komuta/gorev-baglam.json'
        self.registry.parent.mkdir()
        self.registry.write_text(json.dumps({'projects': [{'id': 'youtube'}]}), encoding='utf-8')

    def record(self, memory_id='m1', **overrides):
        row = dict(memory_id=memory_id, status='active', subject_key='video.style',
                   scope='user', source_path='projeler/youtube/not.md',
                   sensitivity='normal', statement='Örnek projede kısa başlık tercihi.')
        return dict(row, **overrides)

    def catalog(self, *rows):
        hafiza._write_jsonl(self.vault / hafiza.CATALOG_PATH, list(rows))

    def candidate(self, candidate_id='c1', **overrides):
        row = self.record(**overrides)
        del row['memory_id']
        row['candidate_id'] = candidate_id
        hafiza._append_jsonl(self.vault / hafiza.CANDIDATE_PATH, row)

    def snapshot(self, vault):
        return {path.relative_to(vault).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for path in vault.rglob('*')}

    def test_registered_project(self):
        self.catalog(self.record())
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['suspects'], [dict(
            memory_id='m1', status='active', subject_key='video.style',
            source_path='projeler/youtube/not.md', project_dir='youtube',
            suggested_scope='project:youtube', registered_project=True,
            reason='scope=user ama kaynak projeler/youtube/ altında')])
        self.assertEqual(result['check'], 'scope_audit')
        self.assertEqual(result['checked_records'], 1)
        self.assertEqual(result['active_suspect_count'], 1)
        self.assertEqual(result['pending_candidates'], [])
        self.assertEqual(result['diagnostics'], [])
        self.assertIs(result['canonical_writes'], False)
        self.assertEqual(result['note'], 'Salt okunur şüphe listesi; kapsam değişikliği insan incelemesi ve yeni aday/supersede akışıyla yapılır.')

    def test_unregistered_project(self):
        self.catalog(self.record(source_path='projeler/bilinmeyen/x.md'))
        suspect = audit.scope_audit(self.vault)['suspects'][0]
        self.assertEqual(suspect['project_dir'], 'bilinmeyen')
        self.assertIsNone(suspect['suggested_scope'])
        self.assertIs(suspect['registered_project'], False)

    def test_normalized_paths(self):
        sources = [r'projeler\youtube\not.md', './projeler/youtube/not.md',
                   r'.\projeler\youtube\not.md', '././projeler/youtube/not.md']
        for index, source in enumerate(sources):
            self.candidate(f'c{index}', source_path=source)
        self.catalog(*(self.record(f'm{index}', source_path=source)
                       for index, source in enumerate(sources)))
        result = audit.scope_audit(self.vault)
        for key in ('suspects', 'pending_candidates'):
            self.assertEqual(len(result[key]), len(sources))
            for suspect in result[key]:
                self.assertEqual(suspect['source_path'], 'projeler/youtube/not.md')
                self.assertEqual(suspect['suggested_scope'], 'project:youtube')

    def test_non_project_sources_and_scopes(self):
        rows = [self.record('project', scope='project:youtube'),
                self.record('user', source_path='zihin/tercihler.md'),
                self.record('index', source_path='projeler/OKU.md'),
                self.record('directory', source_path='projeler/youtube/'),
                self.record('prefix', source_path='arsiv/projeler/youtube/not.md')]
        self.catalog(*rows)
        for row in rows:
            self.candidate(row['memory_id'], scope=row['scope'], source_path=row['source_path'])
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['checked_records'], len(rows))
        self.assertEqual(result['suspects'], [])
        self.assertEqual(result['active_suspect_count'], 0)
        self.assertEqual(result['pending_candidates'], [])

    def test_all_statuses_and_active_count(self):
        statuses = ['active', 'superseded', 'quarantined', 'deleted']
        self.catalog(*(self.record(f'm{index}', status=status) for index, status in enumerate(statuses)),
                     self.record('outside', source_path='zihin/tercihler.md'))
        result = audit.scope_audit(self.vault)
        self.assertEqual([row['status'] for row in result['suspects']], statuses)
        self.assertEqual(result['active_suspect_count'], 1)
        self.assertEqual(result['checked_records'], 5)

    def test_pending_candidates(self):
        self.candidate('pending', source_path='projeler/youtube/alt/not.md')
        self.candidate('unknown', source_path='projeler/bilinmeyen/x.md')
        self.candidate('terminal')
        self.candidate('blocked')
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.promoted', candidate_id='terminal'))
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.deferred', candidate_id='blocked',
                                 at=dt.datetime.now(dt.timezone.utc).isoformat()))
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['pending_candidates'], [
            dict(candidate_id='pending', subject_key='video.style',
                 source_path='projeler/youtube/alt/not.md', project_dir='youtube',
                 suggested_scope='project:youtube'),
            dict(candidate_id='unknown', subject_key='video.style',
                 source_path='projeler/bilinmeyen/x.md', project_dir='bilinmeyen',
                 suggested_scope=None),
        ])
        self.assertEqual(result['checked_records'], 0)
        self.assertEqual(result['active_suspect_count'], 0)

    def test_deterministic_order(self):
        rows = [self.record('m3'), self.record('m1'), self.record('m2')]
        self.catalog(*rows)
        for ident in ('c3', 'c1', 'c2'):
            self.candidate(ident)
        result = audit.scope_audit(self.vault)
        self.assertEqual([row['memory_id'] for row in result['suspects']], ['m1', 'm2', 'm3'])
        self.assertEqual([row['candidate_id'] for row in result['pending_candidates']], ['c1', 'c2', 'c3'])
        self.catalog(*reversed(rows))
        self.assertEqual(result, audit.scope_audit(self.vault))

    def test_sensitive_statements_omitted(self):
        sensitivities = ['normal', 'private', 'secret']
        self.catalog(*(self.record(f'm{index}', sensitivity=sensitivity,
                                  statement=f'Katalog hassas örnek {index}')
                       for index, sensitivity in enumerate(sensitivities)))
        for index, sensitivity in enumerate(sensitivities):
            self.candidate(f'c{index}', sensitivity=sensitivity, statement=f'Aday hassas örnek {index}')
        result = audit.scope_audit(self.vault)
        self.assertEqual(len(result['suspects']), 3)
        self.assertEqual(len(result['pending_candidates']), 3)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('statement', serialized)
        self.assertNotIn('hassas örnek', serialized)

    def test_read_only(self):
        self.catalog(self.record())
        self.candidate()
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.created', candidate_id='c1'))
        for label in ('populated', 'empty'):
            with self.subTest(vault=label), tempfile.TemporaryDirectory() as empty:
                vault = self.vault if label == 'populated' else Path(empty)
                before = self.snapshot(vault)
                result = audit.scope_audit(vault)
                self.assertEqual(before, self.snapshot(vault))
                self.assertIs(result['canonical_writes'], False)

    def test_missing_registry(self):
        self.registry.unlink()
        self.catalog(self.record())
        self.candidate()
        before = self.snapshot(self.vault)
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['diagnostics'], ['project_registry_unreadable'])
        self.assertIsNone(result['suspects'][0]['suggested_scope'])
        self.assertIs(result['suspects'][0]['registered_project'], False)
        self.assertIsNone(result['pending_candidates'][0]['suggested_scope'])
        self.assertEqual(before, self.snapshot(self.vault))

    def test_unreadable_registry(self):
        self.catalog(self.record())
        broken = [b'{broken', b'\xff', b'null', b'[]', b'{}', b'{"projects": null}',
                  b'{"projects": {}}', b'{"projects": [null]}', b'{"projects": [{}]}',
                  b'{"projects": [{"id": []}]}', b'{"projects": [{"id": ""}]}',
                  b'{"projects": [{"id": "youtube"}, {}]}']
        for payload in broken:
            with self.subTest(payload=payload):
                self.registry.write_bytes(payload)
                before = self.snapshot(self.vault)
                result = audit.scope_audit(self.vault)
                self.assertEqual(result['diagnostics'], ['project_registry_unreadable'])
                self.assertIsNone(result['suspects'][0]['suggested_scope'])
                self.assertIs(result['suspects'][0]['registered_project'], False)
                self.assertEqual(before, self.snapshot(self.vault))

    def check_cli(self, module, command):
        self.catalog(self.record())
        self.candidate()
        before = self.snapshot(self.vault)
        output = io.StringIO()
        argv = [module.__file__, '--vault', str(self.vault), command]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            module.main()
        result = audit.scope_audit(self.vault)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertEqual(output.getvalue(), json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        self.assertEqual(before, self.snapshot(self.vault))

    def test_kapsam_cli(self):
        self.check_cli(audit, 'kapsam')

    def test_scope_audit_cli(self):
        self.check_cli(konsolidasyon, 'scope-audit')


if __name__ == '__main__':
    unittest.main()
