import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ders_tetik as t
from hafiza import statement_hash
from is_ve_ders import put


class LessonTriggerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.v=Path(self.tmp.name);self.out=self.v/'reports/result.json'
  self.ledger=self.v/'zihin/ders-durumu.jsonl'
  (self.v/'source.md').write_text('Kapak üretirken önce kimlik ve tasarımı denetle.',encoding='utf-8')
  (self.v/'method.md').write_text('Kimlik ve tasarımı denetle.',encoding='utf-8')
  (self.v/'verification.md').write_text('Test sonucu: kimlik ve tasarım kontrolü doğrulandı.',encoding='utf-8')
  self.row=self.lesson()
  self.spec=dict(schema=1,label_review=dict(status='reviewed',kind='fixture',reviewed_by='offline-reviewer'),
   cases=[dict(lesson_id='kapak',project_id=None,workflow_ids=[],should_trigger=['kapak üret','kapak tasarla','kapak düzenle'],
    should_not_trigger=['ses düzenle','metni kısalt','raporu denetle'])])

 def lesson(self,ident='kapak',**changes):
  return put(self.v,'lesson',dict(dict(id=ident,title=ident,status='verified',source_path='source.md',
   evidence=(self.v/'source.md').read_text(encoding='utf-8'),actor='reviewer',triggers=['kapak'],method_path='method.md',
   implementation_hash=statement_hash((self.v/'method.md').read_text(encoding='utf-8')),target_path='method.md',
   target_hash=statement_hash((self.v/'method.md').read_text(encoding='utf-8')),verification_path='verification.md',
   verification_hash=hashlib.sha256((self.v/'verification.md').read_bytes()).hexdigest(),
   verification_evidence=(self.v/'verification.md').read_text(encoding='utf-8')),**changes))

 def replace(self,**changes):
  self.ledger.write_text(json.dumps(dict(self.row,**changes),ensure_ascii=False)+'\n',encoding='utf-8')

 def files(self):
  return {p.relative_to(self.v).as_posix():p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

 def fails(self,kind,message,spec=...):
  before=self.files()
  with self.assertRaises(kind) as caught: t.run(self.v,self.spec if spec is ... else spec,self.out)
  self.assertEqual(str(caught.exception),message)
  self.assertFalse(self.out.exists());self.assertEqual(self.files(),before)

 def test_perfect_recall_writes_snapshot_and_reviewed_report(self):
  before=self.files();report=t.run(self.v,self.spec,self.out)
  self.assertEqual(report,json.loads(self.out.read_text(encoding='utf-8')))
  self.assertEqual((report['schema'],report['status'],report['recall'],report['false_trigger_rate']),(1,'measured',1.0,0.0))
  self.assertEqual(report['lessons'],[dict(lesson_id='kapak',version=1,recall=1.0,false_trigger_rate=0.0,
   should_trigger=dict(total=3,hits=3,missed=[]),should_not_trigger=dict(total=3,hits=0,false_triggers=[]))])
  names=['zihin/ders-durumu.jsonl','source.md','method.md','verification.md']
  self.assertEqual(report['source_versions'],{name:hashlib.sha256(before[name]).hexdigest() for name in names})
  self.assertEqual(report['spec_digest'],t.digest(self.spec));self.assertTrue(report['generated_at'])
  self.assertEqual(report['label_review'],self.spec['label_review']);self.assertIsNot(report['label_review'],self.spec['label_review'])
  self.assertIn('faydasının kanıtı değildir',report['note'])
  self.assertEqual(before,{name:data for name,data in self.files().items() if name!='reports/result.json'})

 def test_missed_and_false_triggers_are_listed(self):
  self.spec['cases'][0]['should_trigger'][0]='görsel üret'
  self.spec['cases'][0]['should_not_trigger'][1]='kapak sözcüğünü açıkla'
  report=t.run(self.v,self.spec,self.out);lesson=report['lessons'][0]
  self.assertEqual(lesson['should_trigger'],dict(total=3,hits=2,missed=['görsel üret']))
  self.assertEqual(lesson['should_not_trigger'],dict(total=3,hits=1,false_triggers=['kapak sözcüğünü açıkla']))
  self.assertEqual(report['recall'],2/3);self.assertEqual(report['false_trigger_rate'],1/3)

 def test_micro_rates_weight_prompts_instead_of_lessons(self):
  self.lesson('ikinci',triggers=['bilinmeyen'])
  self.spec['cases'].append(dict(lesson_id='ikinci',should_trigger=['soru '+str(i) for i in range(5)],
   should_not_trigger=['bilinmeyen '+str(i) for i in range(4)]))
  report=t.run(self.v,self.spec,self.out)
  self.assertEqual(report['recall'],3/8);self.assertEqual(report['false_trigger_rate'],4/7)
  self.assertEqual(report['lessons'][1]['recall'],0.0)

 def test_missing_lesson_and_missing_ledger_fail_without_output(self):
  self.spec['cases'][0]['lesson_id']='yok'
  self.fails(t.HarnessError,'lesson_missing:yok')
  self.ledger.unlink();self.fails(t.HarnessError,'lesson_missing:yok')

 def test_changed_evidence_files_are_ineligible(self):
  for name,reason in [('source.md','source_changed'),('method.md','method_changed'),('verification.md','verification_changed')]:
   with self.subTest(name=name):
    path=self.v/name;original=path.read_bytes();path.write_text('İncelemeden sonra değişti.',encoding='utf-8')
    self.fails(t.HarnessError,'lesson_ineligible:kapak:'+reason);path.write_bytes(original)

 def test_ineligible_status_integrity_and_instruction_gates_stop(self):
  (self.v/'CLAUDE.md').write_bytes((self.v/'method.md').read_bytes())
  cases=[(dict(status='rejected'),'rejected'),(dict(review_required={}),'review_required'),
   (dict(status='proposed',outcome_id='pending'),'outcome_unverified'),
   (dict(source_content_hash=None),'legacy_unreviewed'),(dict(method_path=None),'method_missing'),
   (dict(method_path='missing.md'),'method_missing'),(dict(source_path='../outside.md'),'source_changed'),
   (dict(method_path='CLAUDE.md'),'instruction_target_unaccepted')]
  for changes,reason in cases:
   with self.subTest(reason=reason):
    self.replace(**changes)
    with patch.object(t.ders_baglam,'context_details') as context:
     self.fails(t.HarnessError,'lesson_ineligible:kapak:'+reason);context.assert_not_called()

 def test_scope_requires_both_owner_and_project_scope(self):
  cases=[(dict(project_id='p',scope='global'),None,[],False),
   (dict(project_id='p',scope='global'),'p',[],True),
   (dict(scope='project:p'),None,['p'],True),(dict(scope='project:p'),'q',[],False),
   (dict(project_id='p',scope='project:w'),'p',[],False),
   (dict(project_id='p',scope='project:w'),'p',['w'],True)]
  for row,project,workflows,allowed in cases:
   with self.subTest(row=row,project=project,workflows=workflows):
    self.replace(**row);self.spec['cases'][0].update(project_id=project,workflow_ids=workflows)
    if allowed:
     self.assertEqual(t.run(self.v,self.spec,self.out)['recall'],1.0);self.out.unlink()
    else: self.fails(t.HarnessError,'lesson_ineligible:kapak:scope_mismatch')

 def test_all_lessons_are_preflighted_before_any_measurement(self):
  self.lesson('son',status='rejected');self.spec['cases'].append(dict(self.spec['cases'][0],lesson_id='son'))
  with patch.object(t.ders_baglam,'context_details') as context:
   self.fails(t.HarnessError,'lesson_ineligible:son:rejected');context.assert_not_called()

 def test_context_exception_is_a_redacted_harness_error(self):
  with patch.object(t.ders_baglam,'context_details',side_effect=RuntimeError('özel hata içeriği')):
   self.fails(t.HarnessError,'context_failed:kapak:RuntimeError')

 def test_malformed_context_never_becomes_zero_recall(self):
  for details in (None,{},dict(text='',lessons=[],diagnostics=None),dict(text='',lessons=[{}],diagnostics=[])):
   with self.subTest(details=details),patch.object(t.ders_baglam,'context_details',return_value=details):
    self.fails(t.HarnessError,'context_failed:kapak:ValueError')

 def test_target_budget_and_integrity_diagnostics_stop(self):
  for reason,error in [('budget','budget_interference:kapak'),('review_required','lesson_ineligible:kapak:review_required')]:
   details=dict(text='',lessons=[],diagnostics=[dict(id='kapak',reason=reason)])
   with self.subTest(reason=reason),patch.object(t.ders_baglam,'context_details',return_value=details):
    self.fails(t.HarnessError,error)

 def test_other_lesson_budget_diagnostic_does_not_block_target(self):
  context=t.ders_baglam.context_details
  def unrelated(*args,**kwargs):
   self.assertEqual(kwargs['budget'],200000)
   details=context(*args,**kwargs);details['diagnostics'].append(dict(id='other',reason='budget'));return details
  with patch.object(t.ders_baglam,'context_details',side_effect=unrelated):
   self.assertEqual(t.run(self.v,self.spec,self.out)['recall'],1.0)

 def test_snapshot_is_checked_at_start_and_end(self):
  for answers in ([False],[True,False]):
   with self.subTest(answers=answers),patch.object(t,'snapshot_valid',side_effect=answers) as check:
    self.fails(t.HarnessError,'snapshot_changed');self.assertEqual(check.call_count,len(answers))

 def test_snapshot_change_during_context_stops_without_output(self):
  context=t.ders_baglam.context_details
  for name in ('source.md','method.md','verification.md','zihin/ders-durumu.jsonl'):
   with self.subTest(name=name):
    path=self.v/name;original=path.read_bytes()
    def change(*args,**kwargs):
     result=context(*args,**kwargs)
     path.write_bytes(original+b'\n');return result
    with patch.object(t.ders_baglam,'context_details',side_effect=change):
     with self.assertRaisesRegex(t.HarnessError,'^snapshot_changed$'): t.run(self.v,self.spec,self.out)
    self.assertFalse(self.out.exists());self.assertFalse(self.out.parent.exists());path.write_bytes(original)

 def test_ledger_is_pinned_before_latest_reads(self):
  latest=t.is_ve_ders.latest
  def change(*args):
   rows=latest(*args);self.ledger.write_bytes(self.ledger.read_bytes()+b'\n');return rows
  with patch.object(t.is_ve_ders,'latest',side_effect=change):
   with self.assertRaisesRegex(t.HarnessError,'^snapshot_changed$'): t.run(self.v,self.spec,self.out)
  self.assertFalse(self.out.exists())

 def test_ledger_created_during_read_cannot_escape_snapshot(self):
  latest=t.is_ve_ders.latest;original=self.ledger.read_bytes();self.ledger.unlink()
  def create(*args):
   self.ledger.write_bytes(original);return latest(*args)
  with patch.object(t.is_ve_ders,'latest',side_effect=create):
   with self.assertRaisesRegex(t.HarnessError,'^snapshot_changed$'): t.run(self.v,self.spec,self.out)
  self.assertFalse(self.out.exists())

 def test_invalid_schema_cases_and_identifiers_are_rejected(self):
  for value in (None,[],dict(self.spec,schema=True),dict(self.spec,schema=2)):
   with self.subTest(value=value): self.fails(ValueError,'schema_invalid',value)
  for cases,error in [([], 'cases_invalid'),([self.spec['cases'][0]]*51,'cases_invalid'),
   ([self.spec['cases'][0]]*2,'duplicate_lesson_id'),([None],'lesson_id_invalid'),
   ([dict(self.spec['cases'][0],lesson_id=' ')],'lesson_id_invalid')]:
   with self.subTest(error=error): self.fails(ValueError,error,dict(self.spec,cases=cases))

 def test_label_review_is_required_and_validated(self):
  for review in (None,{},dict(status='reviewed',kind='unknown',reviewed_by='reviewer'),
   dict(status='pending',kind='human',reviewed_by='reviewer'),dict(status='reviewed',kind='agent',reviewed_by=' ')):
   with self.subTest(review=review): self.fails(ValueError,'label_review_required',dict(self.spec,label_review=review))
  spec=copy.deepcopy(self.spec);spec.pop('label_review');self.fails(ValueError,'label_review_required',spec)

 def test_prompt_count_uniqueness_type_and_length_are_bounded(self):
  for field in ('should_trigger','should_not_trigger'):
   for prompts in (['a','b'],['q'+str(i) for i in range(11)],['a','b','b'],['a','b',' '],['a','b',1],['a','b','c'*1501],'abc'):
    with self.subTest(field=field,prompts=prompts):
     spec=copy.deepcopy(self.spec);spec['cases'][0][field]=prompts;self.fails(ValueError,field+'_invalid',spec)
  spec=copy.deepcopy(self.spec);spec['cases'][0]['should_trigger']=['a'*1500]+['q'+str(i) for i in range(9)]
  t.validate(spec)

 def test_prompt_overlap_is_rejected(self):
  self.spec['cases'][0]['should_not_trigger'][0]=self.spec['cases'][0]['should_trigger'][0]
  self.fails(ValueError,'prompt_overlap')

 def test_scope_types_are_validated(self):
  for field,value in [('project_id',[]),('project_id',7),('workflow_ids','p'),('workflow_ids',[None]),('workflow_ids',None)]:
   with self.subTest(field=field,value=value):
    spec=copy.deepcopy(self.spec);spec['cases'][0][field]=value;self.fails(ValueError,field+'_invalid',spec)

 def test_secret_scan_covers_entire_spec(self):
  secret='token: fixture-secret'
  for field in ('prompt','review','extra'):
   with self.subTest(field=field):
    spec=copy.deepcopy(self.spec)
    if field=='prompt': spec['cases'][0]['should_trigger'][0]=secret
    elif field=='review': spec['label_review']['reviewed_by']=secret
    else: spec['extra']=secret
    self.fails(ValueError,'spec_contains_secret',spec)

 def test_existing_output_is_immutable(self):
  self.out.parent.mkdir();self.out.write_text('existing report',encoding='utf-8');before=self.files()
  with patch.object(t.ders_baglam,'context_details') as context:
   with self.assertRaisesRegex(ValueError,'^output_exists$'): t.run(self.v,self.spec,self.out)
   context.assert_not_called()
  self.assertEqual(self.files(),before)

 def test_concurrent_output_is_preserved_without_staging_files(self):
  context=t.ders_baglam.context_details
  def winner(*args,**kwargs):
   self.out.parent.mkdir(exist_ok=True);self.out.write_text('other run',encoding='utf-8');return context(*args,**kwargs)
  with patch.object(t.ders_baglam,'context_details',side_effect=winner):
   with self.assertRaisesRegex(ValueError,'^output_exists$'): t.run(self.v,self.spec,self.out)
  self.assertEqual(self.out.read_text(encoding='utf-8'),'other run');self.assertEqual(list(self.out.parent.iterdir()),[self.out])

 def test_write_failure_leaves_no_report_or_staging_files(self):
  with patch.object(t,'write',side_effect=OSError('fixture write failed')):
   self.fails(t.HarnessError,'output_failed:OSError')
  self.assertEqual(list(self.out.parent.iterdir()),[])

 def cli(self):
  path=self.v/'spec.json';path.write_text(json.dumps(self.spec,ensure_ascii=False),encoding='utf-8')
  return subprocess.run([sys.executable,'-X','utf8',str(Path(t.__file__)),'run','--vault',str(self.v),
   '--spec',str(path),'--output',str(self.out)],capture_output=True,text=True,encoding='utf-8',stdin=subprocess.DEVNULL)

 def test_cli_success_prints_the_measured_report(self):
  result=self.cli();self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(result.stderr,'')
  self.assertEqual(json.loads(result.stdout),json.loads(self.out.read_text(encoding='utf-8')))

 def test_cli_errors_exit_two_with_empty_stdout(self):
  self.spec['cases'][0]['lesson_id']='yok'
  result=self.cli();self.assertEqual(result.returncode,2);self.assertEqual(result.stdout,'')
  self.assertEqual(json.loads(result.stderr),dict(status='error',error='lesson_missing:yok'));self.assertFalse(self.out.exists())
  self.spec.pop('label_review');result=self.cli();self.assertEqual(result.returncode,2);self.assertEqual(result.stdout,'')
  self.assertEqual(json.loads(result.stderr),dict(status='error',error='label_review_required'));self.assertFalse(self.out.exists())


if __name__=='__main__': unittest.main()
