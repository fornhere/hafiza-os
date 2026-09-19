"""Network waits must not own the canonical writer; stale commits fail closed."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
import hafiza as h
from test_hafiza import FakeMem0

class SyncConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);(self.v/'source.md').write_text('User prefers concise responses.')
        candidate=h.add_candidate(self.v,statement='User prefers concise responses.',kind='semantic',scope='user',
            subject_key='style',source_path='source.md',source_anchor='test',confidence='explicit-user',
            sensitivity='normal',proposed_by='test')
        h.promote_candidate(self.v,candidate['candidate_id'],memory_id='style',reviewed_by='test',apply=True)
    def slow_sync(self, mutate):
        entered=threading.Event();release=threading.Event()
        class Slow(FakeMem0):
            def list_memories(self):
                if not entered.is_set():entered.set();release.wait(5)
                return super().list_memories()
        client=Slow([])
        with ThreadPoolExecutor(max_workers=2) as pool:
            sync=pool.submit(h.sync_existing,self.v,h.load_catalog(self.v),client,apply=True)
            try:
                self.assertTrue(entered.wait(5))
                writer=pool.submit(h.serialized(mutate),self.v)
                writer.result(timeout=2)
            finally:release.set()
            return sync.result(timeout=5)
    def test_unrelated_writer_progresses_while_remote_is_waiting(self):
        def write(vault):h._append_jsonl(vault/h.EVENT_PATH,dict(event_type='test.local_write'))
        result=self.slow_sync(write)
        self.assertEqual(result['status'],'applied');self.assertEqual(result['verified'],1)
        self.assertTrue(h.load_catalog(self.v)[0]['mem0_id'])
    def test_late_sync_cannot_overwrite_new_catalog(self):
        def write(vault):
            records=h.load_catalog(vault);records[0]['status']='quarantined'
            h._write_jsonl(vault/h.CATALOG_PATH,records)
        result=self.slow_sync(write)
        self.assertTrue(result['reconciliation_required']);self.assertEqual(result['verified'],0)
        record=h.load_catalog(self.v)[0];self.assertEqual(record['status'],'quarantined');self.assertIsNone(record['mem0_id'])
        journals=list((self.v/'günlük/hafıza-makbuzları/sync-transactions').glob('*.json'))
        self.assertEqual(json.loads(journals[0].read_text())['status'],'catalog_conflict')
    def test_uncertain_remote_add_reuses_identity_on_explicit_retry(self):
        class Uncertain(FakeMem0):
            fail=True
            def add_memory(self,*args,**kwargs):
                created=super().add_memory(*args,**kwargs)
                if self.fail:self.fail=False;raise ConnectionError('response lost')
                return created
        client=Uncertain([])
        with self.assertRaises(ConnectionError):h.sync_existing(self.v,h.load_catalog(self.v),client,apply=True)
        self.assertIsNone(h.load_catalog(self.v)[0]['mem0_id'])
        states=[json.loads(p.read_text())['status'] for p in (self.v/'günlük/hafıza-makbuzları/sync-transactions').glob('*.json')]
        self.assertEqual(states,['remote_outcome_unknown'])
        result=h.sync_existing(self.v,h.load_catalog(self.v),client,apply=True)
        self.assertEqual(result['verified'],1);self.assertEqual(len(client.added),1)

if __name__=='__main__':unittest.main()
