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
   row=dict(id='thumbnail-reference-role-boundaries',title='Referans',triggers=['kapak'],status='proposed',source_path='source.md',evidence='Eski maskot yanlış kullanıldı.',method_path='komuta/method.md',implementation_status='applied',implementation_hash=statement_hash((v/'komuta/method.md').read_text()))
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
