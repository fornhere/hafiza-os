import json
import tempfile
import unittest
from pathlib import Path
from ders_baglam import context, backlog
from codex_hafiza import hook
from hafiza import statement_hash

class Lessons(unittest.TestCase):
 def test_routing_after_first_turn_and_no_block(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'zihin').mkdir();(v/'komuta').mkdir()
   (v/'source.md').write_text('Eski maskot yanlış kullanıldı.')
   (v/'komuta/method.md').write_text('Kimlik ve tasarım referansını ayır.')
   row=dict(id='thumbnail-reference-role-boundaries',title='Referans',triggers=['kapak'],status='proposed',source_path='source.md',evidence='Eski maskot yanlış kullanıldı.',method_path='komuta/method.md',source_content_hash=statement_hash((v/'source.md').read_text()),implementation_status='applied',implementation_hash=statement_hash((v/'komuta/method.md').read_text()))
   (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(row)+'\n')
   self.assertEqual(context(v,'hava nasıl'), '')
   self.assertIn('Kimlik ve tasarım',context(v,'kapak üret'))
   self.assertEqual(context(v,'kapak üret',budget=5),'')
   hook(v,dict(hook_event_name='UserPromptSubmit',session_id='s',turn_id='1',prompt='selam'))
   result=hook(v,dict(hook_event_name='UserPromptSubmit',session_id='s',turn_id='2',prompt='kapak üret'))
   self.assertIn('Kimlik ve tasarım',result['hookSpecificOutput']['additionalContext'])
   self.assertNotIn('decision',result)
   self.assertEqual(hook(v,dict(hook_event_name='Stop',session_id='s',turn_id='2')), {})
   self.assertEqual(backlog(v)[0]['implementation_status'],'applied')
   (v/'komuta/method.md').write_text('Yöntem onaydan sonra değişti.')
   self.assertEqual(context(v,'kapak üret'), '')
   (v/'source.md').write_text('Değişmiş kaynak')
   self.assertEqual(context(v,'kapak üret'),'')

 def test_source_revision_cancellation_requires_explicit_review(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'komuta').mkdir();(v/'zihin').mkdir()
   quote='Dışa aktarımda önce kolon türlerini denetle.'
   (v/'source.md').write_text(quote);(v/'komuta/method.md').write_text('Kolon türlerini denetle.')
   data=dict(id='export',title='Kolon yöntemi',status='proposed',source_path='source.md',evidence=quote,actor='reviewer',triggers=['dışa aktarım'],method_path='komuta/method.md',implementation_hash=statement_hash((v/'komuta/method.md').read_text()))
   first=put(v,'lesson',data)
   self.assertEqual(first['source_content_hash'],statement_hash(quote))
   self.assertIn('Kolon türlerini',context(v,'dışa aktarım'))
   (v/'source.md').write_text(quote+'\nBu yöntemi iptal ettim.')
   self.assertEqual(context(v,'dışa aktarım'),'')
   # An explicitly reviewed rejection must not reactivate the lesson.
   put(v,'lesson',dict(data,status='rejected',expected_version=first['version']))
   self.assertEqual(context(v,'dışa aktarım'),'')

 def test_legacy_requires_review_and_harmless_append_needs_rebind(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'zihin').mkdir()
   (v/'source.md').write_text('Raporu yayınlamadan birim adlarını denetle.')
   (v/'method.md').write_text('Birim adlarını denetle.')
   row=dict(id='units',title='Birimler',status='proposed',source_path='source.md',evidence=(v/'source.md').read_text(),actor='reviewer',triggers=['rapor'],method_path='method.md',implementation_hash=statement_hash((v/'method.md').read_text()),version=1)
   (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(row)+'\n')
   self.assertEqual(context(v,'rapor'),'')
   reviewed=put(v,'lesson',dict(row,expected_version=1))
   self.assertIn('Birim adlarını',context(v,'rapor'))
   (v/'source.md').write_text((v/'source.md').read_text()+'\nBağımsız ek not.')
   self.assertEqual(context(v,'rapor'),'')
   put(v,'lesson',dict(reviewed,expected_version=2))
   self.assertIn('Birim adlarını',context(v,'rapor'))
