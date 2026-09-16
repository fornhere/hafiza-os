import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
import hafiza as h
from gorev_baglam import build_task_package
from is_ve_ders import put

class CompactProject(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.v=Path(self.tmp.name);(self.v/'komuta').mkdir()
  self.source=self.v/'current.md';self.source.write_text('Dışa aktarım CSV olacak. Sonraki adım CSV doğrulaması.')
  (self.v/'past.md').write_text('ESKI: dışa aktarım XML idi.')
  cfg={'projects':[{'id':'atlas','aliases':['Atlas'],'episode_sources':['past.md'],'working_sources':[{'path':str(self.source),'role':'karar','evidence_source':'current.md'}]}]}
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps(cfg))
 def task(self):
  return put(self.v,'task',dict(id='export',title='Dışa aktarım',status='active',next_step='CSV doğrulaması',project_id='atlas',source_path='current.md',evidence=self.source.read_text(),actor='test',last_verified=dt.date.today().isoformat()))
 def test_complete_current_task_avoids_reopening_history(self):
  self.task();p=build_task_package(self.v,'Atlas dışa aktarım işine devam')
  self.assertIn('CSV doğrulaması',p['text']);self.assertNotIn('ESKI',p['text'])
  self.assertEqual(p['summary']['task_ids'],['export']);self.assertFalse(p['history']['included'])
  self.assertNotIn('Güncel içeriği aç',p['text'])
 def test_sparse_and_different_topic_need_history(self):
  p=build_task_package(self.v,'Atlas devam');self.assertIn('ESKI',p['text'])
  self.task();p=build_task_package(self.v,'Atlas güvenlik izinlerine devam')
  self.assertIn('ESKI',p['text'])
 def test_legacy_task_is_hint_not_current_summary(self):
  self.task()
  path=self.v/'zihin/is-durumu.jsonl'
  rows=[json.loads(line) for line in path.read_text().splitlines()]
  for row in rows: row.pop('source_content_hash',None)
  path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows))
  p=build_task_package(self.v,'Atlas devam')
  self.assertIn('Kaynağı yeniden doğrulanacak iş:',p['text'])
  self.assertEqual(p['summary']['task_ids'],[])
  self.assertFalse(p['history']['topic_covered']);self.assertIn('ESKI',p['text'])
 def test_changed_source_does_not_prove_current_state(self):
  self.task();self.source.write_text(self.source.read_text()+' CSV iptal; JSON kullanılacak.')
  p=build_task_package(self.v,'Atlas devam')
  self.assertNotIn('export',p['summary']['task_ids']);self.assertIn('ESKI',p['text'])
 def test_explicit_history_and_opt_out(self):
  self.task()
  self.assertIn('ESKI',build_task_package(self.v,'Atlas önceki karar neydi')['text'])
  self.assertIn('ESKI',build_task_package(self.v,'Atlas',history='always')['text'])
  self.assertNotIn('ESKI',build_task_package(self.v,'Atlas önceki karar neydi',history='never')['text'])
 def test_self_contained_and_budget(self):
  self.task();p=build_task_package(self.v,'Atlas duyuru metni yaz: yarın kapanıyoruz')
  self.assertNotIn('ESKI',p['text'])
  p=build_task_package(self.v,'Atlas devam',budget=20)
  self.assertLessEqual(len(p['text']),20);self.assertFalse(p['history']['included'])
  self.assertFalse(p['history']['topic_covered'])
 def test_history_phrase_requires_adjacent_words(self):
  self.task()
  p=build_task_package(self.v,'Atlas önceki geri dönüş notuyla yeni karar metni yaz')
  self.assertFalse(p['history']['requested'])
  self.assertNotIn('ESKI',p['text'])
  p=build_task_package(self.v,'Atlas önceki kararı hatırlat')
  self.assertTrue(p['history']['requested'])
 def test_new_task_version_replaces_old_next_step(self):
  old=self.task();self.source.write_text('JSON doğrulaması ile devam et.')
  put(self.v,'task',dict(old,expected_version=old['version'],next_step='JSON doğrulaması',evidence=self.source.read_text()))
  p=build_task_package(self.v,'Atlas devam')
  self.assertIn('JSON doğrulaması',p['text']);self.assertNotIn('CSV doğrulaması',p['text'])
  self.assertNotIn('ESKI',p['text'])

if __name__=='__main__': unittest.main()
