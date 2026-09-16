"""Adversarial retrieval tests: irrelevant volume, order, scope and real budgets."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import gorev_baglam as g
import ders_baglam as d
from hafiza import statement_hash

class Retrieval(unittest.TestCase):
 def test_ranking_is_order_independent_and_specific(self):
  noise=[{'memory_id':str(i),'statement':'Video üretimi için genel tercih.'} for i in range(80)]
  important={'memory_id':'important','statement':'Video ses dengesi ölçümü gerçek kayıtla yapılır.'}
  rows=noise+[important]
  self.assertEqual(g.rank_records(rows,'video ses dengesi')[0],important)
  self.assertEqual(g.rank_records(rows,'video ses dengesi'),g.rank_records(rows[::-1],'video ses dengesi'))
  self.assertEqual(g.rank_records(rows,'bunu da yapalım'),[])
 def test_inflections_and_measured_synonyms(self):
  rows=[{'memory_id':'a','statement':'Hafıza sunum kararları'}, {'memory_id':'b','statement':'Kabak pişirme'}]
  self.assertEqual(g.rank_records(rows,'bellek slaytlarını hazırla')[0]['memory_id'],'a')
  self.assertEqual(g.rank_records(rows,'kapak'),[])
  self.assertEqual(g.rank_records(rows,'slaytlarını')[0]['memory_id'],'a')
 def test_project_and_methods_survive_catalog_noise_and_exact_budget(self):
  with tempfile.TemporaryDirectory() as temp:
   v=Path(temp);(v/'komuta').mkdir()
   (v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[{'id':'delta','aliases':['delta']}]}))
   rows=[{'memory_id':str(i),'statement':'Delta '*80,'source_path':'s.md'} for i in range(40)]
   (v/'s.md').write_text('source')
   for row in rows:
    row.update(kind='semantic',scope='user',subject_key=row['memory_id'],status='active',source_anchor='test',source_hash=statement_hash(row['statement']),source_content_hash=statement_hash('source'),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
   with patch.object(g.h,'load_catalog',return_value=rows), patch.object(d,'context',return_value='METHOD'):
    package=g.build_task_package(v,'delta',budget=120)
    self.assertIn('Proje: delta',package['text']);self.assertIn('METHOD',package['text'])
    self.assertLessEqual(len(package['text']),120)
    self.assertEqual(package['usage']['context_chars'],len(package['text']))
    self.assertIsNone(package['usage']['token_count'])
 def test_error_reporting_obeys_small_budgets(self):
  with tempfile.TemporaryDirectory() as temp:
   v=Path(temp);(v/'komuta').mkdir();(v/'komuta/gorev-baglam.json').write_text('{')
   for budget in [0,1,40,100,500]:
    self.assertLessEqual(len(g.build_task_package(v,'x',budget=budget)['text']),budget)
 def test_lessons_scope_finite_match_and_header_budget(self):
  with tempfile.TemporaryDirectory() as temp:
   v=Path(temp);(v/'zihin').mkdir();(v/'s.md').write_text('Kaynak kanıtı.')
   (v/'method.md').write_text('PROJE YÖNTEMİ')
   row=dict(id='lesson',title='Başlık',triggers=['kapak'],status='proposed',source_path='s.md',evidence='Kaynak kanıtı.',method_path='method.md',project_id='delta',source_content_hash=statement_hash((v/'s.md').read_text()),implementation_hash=statement_hash('PROJE YÖNTEMİ'))
   (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(row)+'\n')
   self.assertEqual(d.context(v,'kapak'), '')
   self.assertEqual(d.context(v,'kapak',project_id='other'), '')
   good=d.context(v,'kapağı',project_id='delta');self.assertIn('PROJE YÖNTEMİ',good)
   self.assertEqual(d.context(v,'kapakçılık',project_id='delta'), '')
   self.assertEqual(d.context(v,'kapak',project_id='delta',budget=len(good)-1),'')
   self.assertEqual(len(d.context(v,'kapak',project_id='delta',budget=len(good))),len(good))
 def test_foreign_and_invalid_records_cannot_change_relevant_ranking(self):
  import hafiza as h
  with tempfile.TemporaryDirectory() as temp:
   v=Path(temp);(v/'komuta').mkdir();(v/'zihin').mkdir()
   (v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[{'id':'amber','aliases':['amber']}]}))
   def row(ident,statement,scope):
    source='zihin/'+ident+'.md';(v/source).write_text(statement)
    return dict(memory_id=ident,kind='semantic',scope=scope,subject_key=ident,statement=statement,status='active',source_path=source,source_content_hash=statement_hash(statement),source_anchor='test',source_hash=statement_hash(statement),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
   target=row('target','Amber ses seviyesi konuşma dengesi','project:amber')
   noise=[row('noise'+str(i),'Amber ses seviyesi genel kayıt','project:foreign') for i in range(80)]
   noise.append(row('rare','Sınırlayıcı ayarı','project:foreign'))
   h._write_jsonl(v/h.CATALOG_PATH,[target])
   self.assertIn('target',g.build_task_package(v,'Amber ses seviyesi sınırlayıcı ayarı')['selected_ids'])
   for invalid in (False,True):
    if invalid:
     for r in noise:r['scope']='project:amber';(v/r['source_path']).write_text('Changed source')
    h._write_jsonl(v/h.CATALOG_PATH,[target]+noise)
    self.assertIn('target',g.build_task_package(v,'Amber ses seviyesi sınırlayıcı ayarı')['selected_ids'])

 def test_irrelevant_stale_memory_does_not_interrupt_simple_question(self):
  import hafiza as h
  with tempfile.TemporaryDirectory() as temp:
   v=Path(temp);(v/'zihin').mkdir()
   stale=dict(memory_id='stale',kind='semantic',scope='user',subject_key='video',statement='Video sesi dengeli olmalı',status='active',source_path='missing.md',source_anchor='test',source_hash=statement_hash('Video sesi dengeli olmalı'),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
   h._write_jsonl(v/h.CATALOG_PATH,[stale])
   self.assertEqual('',g.build_task_package(v,'Kabak çorbası nasıl yapılır')['text'])
   self.assertIn('stale:invalid',g.build_task_package(v,'Video sesi')['omitted_reasons'])
