import copy
import tempfile
import unittest
from pathlib import Path
import bilgi_agi as b
import konu_sentezi as k


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        self.source = self.v / 'source.md'
        self.quote = 'Sunumda kısa cümle kullan; başka projede uzun anlatı kullan.'
        self.source.write_text(self.quote)
        self.record = dict(id='short', title='Kısa anlatım', kind='preference',
                           statement='Sunumda kısa cümle kullan.', scope='user',
                           domains=['sunum'], status='reviewed',
                           sources=[dict(path='source.md', sha256=b.digest(self.source),
                                         evidence=self.quote)],
                           reviewed_by='test-reviewer', review_note='Kaynak doğrudan alıntıdır.')
        b.register(self.v, self.record, True)

    def add(self, **changes):
        record = copy.deepcopy(self.record)
        record.update(changes)
        b.register(self.v, record, True)

    def test_expands_related_claim_and_preserves_scope(self):
        self.add(id='long', title='Uzun anlatı', statement='Başka projede uzun anlatı kullan.')
        self.add(id='private', scope='project:other')
        result = k.retrieve(self.v, 'anlatım tercihlerimi özetle', budget=6000)
        self.assertEqual({r['id'] for r in result['records']}, {'short', 'long'})
        self.assertIn('çelişkiler çözülmemiştir', result['text'])
        self.assertEqual(result['source_versions']['source.md'], b.digest(self.source))
        self.assertTrue(result['topics'][0]['summary'][0]['review_note'])

    def test_changed_source_never_returned_from_snapshot(self):
        snapshot = k.render_markdown(k.build(self.v))
        self.assertIn('Sunumda kısa', snapshot)
        self.source.write_text('source changed')
        result = k.retrieve(self.v, 'anlatım tercihlerim')
        self.assertFalse(result['records'])
        self.assertTrue(any('source_changed' in d for d in result['diagnostics']))

    def test_proposals_not_promoted(self):
        self.add(id='proposal', status='proposed', statement='Anlatım tamamen değişsin.')
        result = k.build(self.v)
        self.assertFalse(any(r['id'] == 'proposal' for t in result['topics'] for r in t['records']))

    def test_budget_exposes_omission_and_no_phantom_versions(self):
        result = k.retrieve(self.v, 'anlatım tercihlerim', budget=100)
        self.assertLessEqual(len(result['text']), 100)
        self.assertEqual(result['omitted_record_ids'], ['short'])
        self.assertFalse(result['source_versions'])

    def test_normal_queries_keep_baseline_transfer(self):
        query = 'sevdiğim tarzda site üret'
        self.assertEqual(k.retrieve(self.v, query), b.retrieve(self.v, query))

    def test_explicit_site_preferences_keep_domain_gate(self):
        query = 'site tasarım tercihlerimi özetle'
        self.assertEqual(k.retrieve(self.v, query), b.retrieve(self.v, query))

    def test_unknown_topic_does_not_dump_records(self):
        result = k.retrieve(self.v, 'veritabanı tercihlerimi özetle')
        self.assertFalse(result['records'])
        self.assertFalse(k.retrieve(self.v, 'tercihlerimi özetle')['records'])

    def test_omitted_records_do_not_leak_via_summary(self):
        first = k.retrieve(self.v, 'anlatım tercihlerim', budget=6000)
        self.add(id='long', statement='Uzun anlatı ' + 'açıklama ' * 200)
        result = k.retrieve(self.v, 'anlatım tercihlerim', budget=len(first['text']) + 10)
        self.assertEqual([r['id'] for r in result['records']], ['short'])
        self.assertEqual([e['record_id'] for t in result['topics'] for e in t['summary']], ['short'])

    def test_unavailable_topic_and_custom_definitions(self):
        result = k.build(self.v)
        work = next(t for t in result['topics'] if t['id'] == 'calisma-yontemi')
        self.assertFalse(work['available'])
        custom = k.build(self.v, definitions=[dict(id='custom', title='Özel', aliases=['özel'], selectors=['cümle'])])
        self.assertEqual(custom['topics'][0]['records'][0]['id'], 'short')
        self.assertIn('SHA-256:', k.render_markdown(custom))

    def test_export_dry_run_noop_refresh_and_no_canonical_change(self):
        canonical = (self.v / 'bilgi/short.md').read_bytes()
        dry = k.export(self.v)
        path = Path(dry['path'])
        self.assertFalse(path.exists())
        self.assertTrue(dry['changed'])
        first = k.export(self.v, apply=True)
        self.assertTrue(first['applied'])
        self.assertIn(self.record['statement'], path.read_text())
        self.assertFalse(k.export(self.v, apply=True)['changed'])
        self.source.write_text('changed source')
        self.assertTrue(k.export(self.v, apply=True)['changed'])
        self.assertNotIn(self.record['statement'], path.read_text())
        self.assertEqual((self.v / 'bilgi/short.md').read_bytes(), canonical)
        self.assertFalse((self.v / 'katalog.jsonl').exists())

    def test_export_protects_manual_edits(self):
        path = Path(k.export(self.v, apply=True)['path'])
        path.write_text(path.read_text() + 'human edit')
        with self.assertRaisesRegex(ValueError, 'snapshot_manually_changed'):
            k.export(self.v, apply=True)
        self.assertTrue(path.read_text().endswith('human edit'))

    def test_export_rejects_unsafe_paths_and_project_ids(self):
        for project in ('../escape', '/tmp/file', '', 'has spaces'):
            with self.assertRaisesRegex(ValueError, 'invalid_project_id'):
                k.export(self.v, project, True)
        folder = self.v / 'bilgi/konu-sentezleri'
        target = self.v / 'target'
        target.mkdir()
        folder.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unsafe_snapshot_path'):
            k.export(self.v, apply=True)
        self.assertFalse(list(target.iterdir()))
        folder.unlink()
        folder.mkdir()
        (folder / 'user.md').symlink_to(target / 'missing.md')
        with self.assertRaisesRegex(ValueError, 'unsafe_snapshot_path'):
            k.export(self.v, apply=True)

    def test_export_project_scope_explicit(self):
        result = k.export(self.v, 'sample-one', True)
        self.assertTrue(result['path'].endswith('project-sample-one.md'))
        self.assertIn('user + project:sample-one', Path(result['path']).read_text())


if __name__ == '__main__':
    unittest.main()
