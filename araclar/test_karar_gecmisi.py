import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import hafiza as h
from karar_gecmisi import history


class History(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);(self.v/'zihin').mkdir()
    def row(self,ident,status='active',**extra):
        text='Atlas karar '+ident
        source=self.v/(ident+'.md');source.write_text(text)
        row=dict(memory_id=ident,kind='semantic',scope='user',subject_key='atlas',statement=text,status=status,
                 source_path=ident+'.md',source_content_hash=h.statement_hash(text),source_anchor=ident,
                 source_hash=h.statement_hash(text),observed_at='2026-01-01',valid_from=None,valid_to=None,
                 confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
        row.update(extra)
        with (self.v/h.CATALOG_PATH).open('a') as f:f.write(json.dumps(row)+'\n')
    def test_history_chain_does_not_infer_reason(self):
        self.row('old','superseded');self.row('new',supersedes='old',observed_at='2026-02-01')
        p=history(self.v,'Atlas neden seçtik')
        self.assertEqual([e['id'] for e in p['entries']],['new','old'])
        self.assertTrue(p['entries'][0]['current']);self.assertFalse(p['entries'][1]['current'])
        self.assertEqual(p['entries'][0]['supersedes'],'old');self.assertIsNone(p['entries'][0]['rationale'])
    def test_source_loss_never_promotes_predecessor(self):
        self.row('old','superseded');self.row('new',supersedes='old')
        (self.v/'new.md').write_text('changed')
        p=history(self.v,'Atlas');self.assertEqual([e['id'] for e in p['entries']],['old'])
        self.assertFalse(p['entries'][0]['current']);self.assertIn('new:source_invalid',p['diagnostics'])
    def test_ambiguous_active_budget_and_scope(self):
        self.row('one');self.row('two');self.row('private',sensitivity='private')
        self.row('other',scope='project:other')
        p=history(self.v,'Atlas',limit=1)
        self.assertEqual(len(p['entries']),1);self.assertFalse(p['entries'][0]['current'])
        self.assertIn('user:atlas:multiple_active',p['diagnostics'])
        self.assertNotIn('private',json.dumps(p));self.assertNotIn('other',json.dumps(p))
        for budget in (0,20,300):
            p=history(self.v,'Atlas',budget=budget)
            self.assertLessEqual(len(p['text']),budget)
            self.assertEqual(len(p['entries']),len(p['source_versions']))
    def test_cycle_missing_predecessor_and_no_matching_query(self):
        self.row('one',supersedes='two');self.row('two','superseded',supersedes='one')
        self.row('missing','superseded',supersedes='unknown')
        p=history(self.v,'Atlas')
        self.assertIn('one:cycle',p['diagnostics']);self.assertIn('missing:predecessor_unavailable',p['diagnostics'])
        self.assertFalse(any(e['current'] for e in p['entries']))
        self.assertEqual(history(self.v,'alakasız')['entries'],[])
    def test_scope_groups_empty_topic_and_considered_ids(self):
        self.row('global');self.row('local',scope='project:atlas')
        p=history(self.v,'Atlas',scope='project:atlas')
        self.assertFalse(p['diagnostics']);self.assertTrue(all(e['current'] for e in p['entries']))
        p=history(self.v,'karar geçmişi',scope='project:atlas')
        self.assertEqual(p['considered_ids'],['local'])
        self.assertEqual(history(self.v,'karar geçmişi')['considered_ids'],[])
        p=history(self.v,'Atlas',scope='project:atlas',budget=0)
        self.assertEqual(p['considered_ids'],['global','local']);self.assertEqual(p['entries'],[])
        (self.v/'local.md').write_text('changed')
        p=history(self.v,'karar geçmişi',scope='project:atlas')
        self.assertIn('Karar geçmişi uyarısı:',p['text'])
        self.assertEqual(p['considered_ids'],['local']);self.assertEqual(p['entries'],[])

    def test_asset_override_cannot_restore_active_memory(self):
        self.row('old')
        for reason in ('asset_revision_replaced', 'asset_revision_conflict'):
            with self.subTest(reason=reason), patch('gorev_baglam.asset_claim_overrides', return_value={'old':reason}):
                p=history(self.v,'Atlas')
                self.assertEqual(len(p['entries']),1)
                self.assertFalse(p['entries'][0]['current'])
                self.assertEqual(p['entries'][0]['override_reason'],reason)
                self.assertIn('old:'+reason,p['diagnostics'])
                self.assertIn('güncelliği seçilmedi',p['text'])

    def test_unpinned_and_expired_not_current(self):
        self.row('legacy',source_content_hash=None);self.row('expired',valid_to='2020-01-01')
        p=history(self.v,'Atlas')
        self.assertEqual([e['id'] for e in p['entries']],['expired']);self.assertFalse(p['entries'][0]['current'])
        self.assertIn('legacy:source_unpinned',p['diagnostics'])


if __name__=='__main__': unittest.main()
