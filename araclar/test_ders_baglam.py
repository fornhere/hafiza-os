import json
import tempfile
import unittest
from pathlib import Path
from ders_baglam import context, context_details, backlog
from codex_hafiza import hook
from hafiza import statement_hash

class Lessons(unittest.TestCase):
 def lesson_fixture(self,v,ident='units',**changes):
  from is_ve_ders import put
  (v/'source.md').write_text('Raporu yayınlamadan birim adlarını denetle.')
  (v/'method.md').write_text('Birim adlarını denetle.')
  data=dict(id=ident,title=ident,status='proposed',source_path='source.md',evidence=(v/'source.md').read_text(),actor='reviewer',triggers=['rapor'],method_path='method.md',implementation_hash=statement_hash((v/'method.md').read_text()))
  return put(v,'lesson',dict(data,**changes))

 def test_context_details_reports_only_delivered_lessons_in_order(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);z=self.lesson_fixture(v,'z');a=self.lesson_fixture(v,'a')
   self.lesson_fixture(v,'unmatched',triggers=['kapak'])
   details=context_details(v,'rapor')
   self.assertEqual(details['text'],context(v,'rapor'))
   self.assertEqual(details['lessons'],[dict(id=r['id'],version=r['version'],status=r['status']) for r in (a,z)])
   self.assertLess(details['text'].index('Ders: a'),details['text'].index('Ders: z'))
   one=context_details(v,'rapor',budget=len(details['text'])-1)
   self.assertEqual([r['id'] for r in one['lessons']],['a'])
   self.assertEqual(one['text'],context(v,'rapor',budget=len(details['text'])-1))
   self.assertEqual(context_details(v,'rapor',budget=5),dict(text='',lessons=[]))
   (v/'source.md').write_text('Değişen kaynak dersi geçersiz kılar.')
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[]))

 def test_review_required_never_enters_context_and_backlog_requests_review(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);review=dict(reason='harm_exceeds_help',help=0,harm=2,outcome_ids=['one','two'])
   row=self.lesson_fixture(v,review_required=review,next_step='Eski sonraki adım')
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[]))
   entry=backlog(v)[0]
   self.assertEqual(entry['review_required'],review)
   self.assertEqual(entry['next_step'],'Fayda incelemesi: zarar 2 > yardım 0; dersi yeniden incele (otomatik silinmedi).')
   (v/'verified.md').write_text('Test sonucu birim adları için doğrulandı.')
   verified=put(v,'lesson',dict(row,status='verified',expected_version=row['version'],target_path='method.md',target_hash=row['implementation_hash'],verification_path='verified.md',verification_evidence=(v/'verified.md').read_text()))
   self.assertEqual(context(v,'rapor'),'')
   self.assertEqual(backlog(v),[])
   verified['review_required']={}
   put(v,'lesson',dict(verified,expected_version=verified['version']))
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[]))

 def test_backlog_without_review_required_keeps_original_fields(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v,proposal='Önce birimleri denetle.')
   self.assertEqual(backlog(v),[dict(id='units',status='proposed',implementation_status='not_applied',next_step='Önce birimleri denetle.')])

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
