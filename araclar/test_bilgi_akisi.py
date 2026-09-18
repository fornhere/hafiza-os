import hashlib,json,tempfile,unittest
from pathlib import Path
from bilgi_agi import register,assess_source,status
from gorev_baglam import build_task_package

class KnowledgeFlow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.v=Path(self.tmp.name)
        (self.v/'gelen-kutusu').mkdir();self.source=self.v/'gelen-kutusu/tercih.md';self.source.write_text('Sunum metninde günlük Türkçe kullanılması tercih edilir.')
        self.record=dict(id='sunum-dil',title='Sunum dili',kind='preference',statement='Sunum metninde günlük Türkçe tercih edilir.',scope='user',domains=['sunum'],status='reviewed',sources=[dict(path='gelen-kutusu/tercih.md',sha256=hashlib.sha256(self.source.read_bytes()).hexdigest(),evidence=self.source.read_text())],reviewed_by='test-review',review_note='Sentetik kapsam kontrolü')
        register(self.v,self.record,True)
    def test_write_notice_requires_applied_change(self):
        unchanged=register(self.v,self.record,True)
        self.assertNotIn('notice',unchanged)
        changed=dict(self.record,id='sunum-dil-yeni',title='Yeni kaynaklı not')
        self.assertNotIn('notice',register(self.v,changed,False))
        result=register(self.v,changed,True)
        self.assertEqual(result['notice']['kind'],'verified_write')
    def test_package_retrieves_without_explicit_memory_command(self):
        p=build_task_package(self.v,'Benim sevdiğim tarzda sunum metni hazırla')
        self.assertEqual(p['knowledge']['records'][0]['id'],'sunum-dil');self.assertIn('günlük Türkçe',p['text'])
        self.assertIn('bilgi/sunum-dil.md',p['source_versions'])
    def test_off_domain_never_claims_site_style(self):
        p=build_task_package(self.v,'Benim sevdiğim tarzda site üret')
        self.assertFalse(p['knowledge']['records']);self.assertIn('günlük Türkçe',p['text']);self.assertIn('Uyarlama önerisi',p['text']);self.assertEqual(p['knowledge']['transfers'][0]['status'],'proposed')
    def test_transfer_keeps_provenance_and_drops_stale_source(self):
        p=build_task_package(self.v,'Benim tarzımda site üret')
        self.assertIn('gelen-kutusu/tercih.md',p['source_versions'])
        self.assertEqual(p['knowledge']['transfers'][0]['aspects'],['metin dili'])
        self.source.write_text('Kaynak değişti.')
        p=build_task_package(self.v,'Benim tarzımda site üret')
        self.assertFalse(p['knowledge']['transfers'])
    def test_no_transfer_to_unrelated_thumbnail_domain(self):
        p=build_task_package(self.v,'thumbnail üret')
        self.assertFalse(p['knowledge']['records']);self.assertFalse(p['knowledge']['transfers'])
    def test_changed_source_reopens_knowledge_backlog(self):
        assess_source(self.v,dict(path='gelen-kutusu/tercih.md',sha256=self.record['sources'][0]['sha256'],outcome='linked',record_ids=['sunum-dil'],reason='Sentetik kaynak incelendi',reviewed_by='test-review'),True)
        self.assertFalse(status(self.v)['unreviewed_sources'])
        self.source.write_text('Tercih kaynağı sonradan değişti.')
        p=build_task_package(self.v,'sunum metni hazırla')
        self.assertFalse(p['knowledge']['records']);self.assertEqual(len(status(self.v)['unreviewed_sources']),1)
    def test_budget_does_not_leak_undelivered_records(self):
        p=build_task_package(self.v,'sunum metni hazırla',budget=10)
        self.assertLessEqual(len(p['text']),10);self.assertIsNone(p['knowledge'])

if __name__=='__main__':unittest.main()
