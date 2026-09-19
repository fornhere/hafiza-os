import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import jev_client as j
import jev_procedures as p
import gorev_baglam as g

class ProcedureRouting(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.v=Path(self.tmp.name)
  for _,rel,_ in p.PROCEDURES:
   target=self.v/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text('local operating rule')
  self.config()
 def config(self,**extra):
  (self.v/'komuta/jev.json').write_text(json.dumps(dict(mode='shadow',procedure_mode='on',**extra)))
 def high(self,*args,**kwargs):return dict(mode='on',degraded=False,scores={r['id']:2 for r in args[2]})
 def test_off_never_calls_model_and_modes_are_independent(self):
  (self.v/'komuta/jev.json').write_text(json.dumps(dict(mode='shadow',retrieval_mode='on',procedure_mode='off')))
  cfg=j.load_config(self.v)
  self.assertEqual(j.purpose_mode(dict(cfg,mode='off'),'retrieval'),'off')
  self.assertEqual(j.purpose_mode(dict(cfg,mode='off',procedure_mode='on'),'procedure_routing'),'off')
  self.assertEqual(j.purpose_mode(cfg,'retrieval'),'on');self.assertEqual(j.purpose_mode(cfg,'evidence_review'),'shadow')
  with patch.object(j,'evaluate') as call:self.assertFalse(p.route(self.v,'hi')['paths']);call.assert_not_called()
 def test_only_existing_allowlisted_paths_and_no_source_content_sent(self):
  (self.v/'YAYINLAMA.md').unlink()
  with patch.object(j,'evaluate',side_effect=self.high) as call:r=p.route(self.v,'yayınla')
  self.assertLessEqual(len(r['paths']),3);self.assertNotIn('YAYINLAMA.md',r['paths'])
  self.assertNotIn('local operating rule',json.dumps(call.call_args.args[2]))
  self.assertTrue(r['mandatory_rules_unchanged'])
 def test_source_change_or_bad_config_degrades_without_suggestions(self):
  def mutate(*args,**kw):
   (self.v/'HAFIZA-DONGUSU.md').write_text('changed');return self.high(*args,**kw)
  with patch.object(j,'evaluate',side_effect=mutate):self.assertEqual(p.route(self.v,'verify')['paths'],[])
  (self.v/'komuta/jev.json').write_text('{bad');self.assertEqual(p.route(self.v,'verify')['diagnostics'],['config_invalid'])
 def test_secret_budget_and_shadow(self):
  with patch.object(j,'evaluate',side_effect=self.high) as call:
   self.assertEqual(p.route(self.v,'token: sensitive')['paths'],[]);call.assert_not_called()
   self.assertEqual(p.route(self.v,'read',budget=1)['text'],'')
  with patch.object(j,'evaluate',return_value=dict(mode='shadow',degraded=False,scores={'production':2})):
   self.assertEqual(p.route(self.v,'read')['paths'],[])
 def test_package_budget_and_provenance(self):
  with patch.object(j,'evaluate',side_effect=self.high):
   full=g.build_task_package(self.v,'Kapak üret',budget=2000)
   self.assertTrue(full['procedure_reading']['delivered']);self.assertTrue(full['procedure_reading']['paths'])
   self.assertTrue(set(full['procedure_reading']['paths'])<=set(full['source_versions']))
   tiny=g.build_task_package(self.v,'Kapak üret',budget=20)
   self.assertLessEqual(len(tiny['text']),20);self.assertEqual(tiny['procedure_reading']['paths'],[])
 def test_purpose_has_task_routing_rubric_and_separate_cache_purpose(self):
  q=j._question('procedure_routing',0,0)
  self.assertIn('procedure',q['instructions']);self.assertIn('permissions',q['instructions'])
  self.assertNotEqual(q,j._question('retrieval',0,0))

if __name__=='__main__':unittest.main()
