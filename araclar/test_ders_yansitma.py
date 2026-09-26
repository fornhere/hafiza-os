from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import bilgi_agi as b
import ders_baglam
import ders_yansitma as r
import hafiza as h
import hafiza_dongusu as d
import is_ve_ders as work


class Reflection(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.v=Path(self.tmp.name)
        self.quote='Sunum testi tamamlandı; sonuç makbuzdan ayrıca incelenmelidir.'
        self.serial=0
        guard=patch.object(d.jev_client,'evaluate',side_effect=AssertionError('reflection must not call Jev'))
        guard.start();self.addCleanup(guard.stop)

    def outcome_fixture(self, task_id, result='failed', **changes):
        source='source-'+task_id+'.md';(self.v/source).write_text(self.quote,encoding='utf-8')
        task=work.latest(self.v,'task').get(task_id)
        work.put(self.v,'task',dict(id=task_id,title='Sunum testi',status='done',source_path=source,
            evidence=self.quote,actor='worker',scope=changes.pop('scope','user'),expected_version=task['version'] if task else None))
        method=changes.get('method_path','method.md');path=self.v/method;path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():path.write_text('Sunum yöntemi: kısa cümle kullan.',encoding='utf-8')
        self.serial+=1;verification='test-'+str(self.serial)+'.json'
        command=changes.pop('command',['python3','test.py'])
        raw=json.dumps(dict(task_id=task_id,exit_code=0 if result=='passed' else 1,passed=result=='passed',
            command=command,finished_at='2026-09-19T12:00:00Z',stderr='RAW_TRACE_DO_NOT_COPY'),ensure_ascii=False)
        if result in ('accepted','rejected'):raw='Kullanıcı sonucu bildirdi: '+result+'; RAW_ACCEPTANCE_DO_NOT_COPY'
        (self.v/verification).write_text(raw,encoding='utf-8')
        data=dict(task_id=task_id,title='Sunum dersi',lesson='OUTCOME_LESSON_DO_NOT_COPY',conditions='OUTCOME_CONDITIONS_DO_NOT_COPY',
            method_path=method,verification_path=verification,verification_hash=b.digest(self.v/verification),verification_evidence=raw,
            verification_kind='user_acceptance' if result in ('accepted','rejected') else 'test_result',observed_result=result,actor='worker',triggers=['sunum'])
        return d.outcome(self.v,dict(data,**changes),True)['row']

    def pair(self, **changes):
        return [self.outcome_fixture(task,**changes) for task in ('one','two')]

    def lesson_fixture(self, **changes):
        return work.put(self.v,'lesson',dict(dict(id='existing',title='Mevcut ders',status='proposed',source_path='source-one.md',
            evidence=self.quote,actor='reviewer',scope='user',method_path='method.md',proposal='EXISTING_LESSON_DO_NOT_REWRITE'),**changes))

    def snapshot(self):
        return {p.relative_to(self.v).as_posix():p.read_bytes() for p in self.v.rglob('*') if p.is_file()}

    def test_failed_sessions_propose_reference_only_skeleton_and_deterministic_id(self):
        rows=[self.outcome_fixture(task,actor_session_id='session-'+task) for task in ('one','two')]
        result=r.reflect(self.v);proposal,=result['proposals']
        self.assertEqual(result['diagnostics'],[]);self.assertFalse(result['applied']);self.assertFalse(result['canonical_writes'])
        self.assertEqual(result['distillation'],'reviewer');self.assertEqual(proposal['status'],'proposed')
        self.assertEqual(proposal['kind'],'new');self.assertFalse(proposal['canonical_writes']);self.assertFalse(proposal['instruction_target'])
        self.assertEqual(proposal['format'],'condition→action→rationale');self.assertIsNone(proposal['action']);self.assertIsNone(proposal['rationale'])
        self.assertTrue(proposal['needs_distillation']);self.assertNotIn('application',proposal)
        self.assertEqual(proposal['pattern_key'],['user','method.md','test_result','python3 test.py'])
        self.assertEqual(proposal['condition'],'Kapsam user, yöntem method.md: `python3 test.py` 2 bağımsız oturumda olumsuz sonuçlandı.')
        ids=sorted(row['receipt_id'] for row in rows)
        self.assertEqual([o['receipt_id'] for o in proposal['occurrences']],ids)
        for occurrence in proposal['occurrences']:
            self.assertEqual(set(occurrence),{'receipt_id','task_id','session_key','observed_result','verification_path','verification_hash'})
            row=next(row for row in rows if row['receipt_id']==occurrence['receipt_id'])
            self.assertEqual(occurrence,dict({k:row[k] for k in occurrence if k!='session_key'},session_key=row['actor_session_id']))
        serialized=json.dumps(result,ensure_ascii=False)
        for text in ('RAW_TRACE_DO_NOT_COPY','verification_evidence','OUTCOME_LESSON_DO_NOT_COPY','OUTCOME_CONDITIONS_DO_NOT_COPY','finished_at',self.quote):
            self.assertNotIn(text,serialized)
        payload=dict(pattern_key=proposal['pattern_key'],occurrence_ids=ids)
        self.assertEqual(proposal['receipt_id'],hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest())
        h._write_jsonl(self.v/d.OUTCOMES,list(reversed(rows))+[rows[0]])
        self.assertEqual(r.reflect(self.v),result)

    def test_source_fallback_uses_latest_task(self):
        self.pair();proposal,=r.reflect(self.v)['proposals']
        self.assertEqual({o['session_key'] for o in proposal['occurrences']},{'source:source-one.md','source:source-two.md'})
        task=work.latest(self.v,'task')['two']
        work.put(self.v,'task',dict(task,source_path='source-one.md',expected_version=task['version']))
        self.assertEqual(r.reflect(self.v)['proposals'],[])

    def test_same_actor_session_does_not_meet_threshold(self):
        self.pair(actor_session_id='same-session')
        self.assertEqual(r.reflect(self.v)['proposals'],[])

    def test_same_task_does_not_meet_threshold(self):
        for session in ('first','second'):self.outcome_fixture('one',actor_session_id=session)
        self.assertEqual(r.reflect(self.v)['proposals'],[])

    def test_min_sessions_validation_and_threshold(self):
        for value in (1,0,-1,True,2.5):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'min_sessions_invalid'):r.reflect(self.v,min_sessions=value)
        self.pair();self.assertEqual(r.reflect(self.v,min_sessions=3)['proposals'],[])
        self.outcome_fixture('three');self.assertEqual(len(r.reflect(self.v,min_sessions=3)['proposals']),1)

    def test_dry_run_empty_vault_writes_nothing(self):
        self.assertEqual(r.reflect(self.v)['proposals'],[]);self.assertEqual(list(self.v.iterdir()),[])

    def test_dry_run_and_apply_are_idempotent_without_ledger_changes(self):
        self.pair();before=self.snapshot();dry=r.reflect(self.v)
        self.assertEqual(self.snapshot(),before);self.assertFalse((self.v/r.REFLECTIONS).exists())
        with patch.object(d,'append_once',wraps=d.append_once) as append:
            applied=r.reflect(self.v,True);self.assertEqual(append.call_count,1)
            self.assertEqual(append.call_args.args[1],r.REFLECTIONS)
        self.assertTrue(applied['applied']);self.assertEqual(applied['proposals'],dry['proposals'])
        self.assertEqual(h.load_jsonl(self.v/r.REFLECTIONS),applied['proposals'])
        after=self.snapshot();self.assertEqual(r.reflect(self.v,True)['proposals'],[])
        self.assertEqual(r.reflect(self.v)['proposals'],[]);self.assertEqual(self.snapshot(),after)
        self.assertFalse((self.v/work.LESSONS).exists());self.assertEqual(ders_baglam.context(self.v,'sunum'),'')

    def test_delta_only_appends_unseen_occurrences_across_history(self):
        self.pair();base,=r.reflect(self.v,True)['proposals']
        for task in ('three','four'):
            new=self.outcome_fixture(task);before=(self.v/r.REFLECTIONS).read_bytes()
            # The older proposal's occurrences can fall outside the input window.
            delta,=r.reflect(self.v,True,limit=2)['proposals']
            self.assertEqual(delta['kind'],'delta');self.assertEqual(delta['base_receipt_id'],base['receipt_id'])
            self.assertEqual([o['receipt_id'] for o in delta['occurrences']],[new['receipt_id']])
            self.assertEqual(delta['append'],dict(occurrences=delta['occurrences'],condition=delta['condition']))
            self.assertTrue((self.v/r.REFLECTIONS).read_bytes().startswith(before));base=delta
        self.assertEqual(r.reflect(self.v,True)['proposals'],[])
        self.assertEqual(len(h.load_jsonl(self.v/r.REFLECTIONS)),3)

    def test_existing_lesson_delta_preserves_text_and_version(self):
        self.pair();base=self.lesson_fixture()
        base=self.lesson_fixture(expected_version=base['version']);before=(self.v/work.LESSONS).read_bytes()
        proposal,=r.reflect(self.v,True)['proposals']
        self.assertEqual(proposal['kind'],'delta');self.assertEqual(proposal['base_lesson_id'],base['id'])
        self.assertEqual(proposal['base_lesson_version'],2);self.assertNotIn('base_receipt_id',proposal)
        self.assertEqual(proposal['append'],dict(occurrences=proposal['occurrences'],condition=proposal['condition']))
        self.assertNotIn(base['proposal'],json.dumps(proposal));self.assertEqual((self.v/work.LESSONS).read_bytes(),before)
        self.outcome_fixture('three');delta,=r.reflect(self.v,True)['proposals']
        self.assertEqual(delta['base_receipt_id'],proposal['receipt_id']);self.assertEqual(delta['base_lesson_version'],2)
        self.assertEqual((self.v/work.LESSONS).read_bytes(),before);self.assertEqual(ders_baglam.context(self.v,'sunum'),'')

    def test_other_scope_or_method_lesson_is_not_base(self):
        self.pair();self.lesson_fixture(id='other-scope',scope='project:p');self.lesson_fixture(id='other-method',method_path='elsewhere.md')
        proposal,=r.reflect(self.v)['proposals']
        self.assertEqual(proposal['kind'],'new');self.assertNotIn('base_lesson_id',proposal);self.assertNotIn('append',proposal)

    def test_successful_outcomes_are_not_pattern_evidence(self):
        failed=self.outcome_fixture('one')
        for task,result in (('two','passed'),('three','passed'),('four','accepted'),('five','accepted')):self.outcome_fixture(task,result)
        self.assertEqual(r.reflect(self.v)['proposals'],[])
        other=self.outcome_fixture('six');proposal,=r.reflect(self.v)['proposals']
        self.assertEqual({o['receipt_id'] for o in proposal['occurrences']},{failed['receipt_id'],other['receipt_id']})

    def test_instruction_target_is_gap_only(self):
        self.pair(method_path='nested/AGENTS.md');before=self.snapshot();proposal,=r.reflect(self.v,True)['proposals']
        self.assertTrue(proposal['instruction_target']);self.assertEqual(proposal['application'],'gap_noted_not_applied')
        self.assertEqual(proposal['status'],'proposed');self.assertFalse((self.v/work.LESSONS).exists())
        for path,content in before.items():self.assertEqual((self.v/path).read_bytes(),content)
        self.assertEqual(ders_baglam.context(self.v,'sunum'),'')

    def test_rejected_acceptance_uses_fixed_signature_and_references_only(self):
        self.pair(result='rejected');proposal,=r.reflect(self.v)['proposals']
        self.assertEqual(proposal['pattern_key'],['user','method.md','user_acceptance','user_rejected'])
        self.assertNotIn('RAW_ACCEPTANCE_DO_NOT_COPY',json.dumps(proposal))
        self.assertEqual({o['observed_result'] for o in proposal['occurrences']},{'rejected'})

    def test_pattern_key_keeps_scope_method_command_and_kind_separate(self):
        self.outcome_fixture('one')
        for task,changes in (('two',dict(scope='project:p')),('three',dict(method_path='other.md')),
                            ('four',dict(command=['python3','other.py'])),('five',dict(result='rejected'))):
            self.outcome_fixture(task,**changes)
        self.assertEqual(r.reflect(self.v)['proposals'],[])
        self.outcome_fixture('six');proposal,=r.reflect(self.v)['proposals']
        self.assertEqual({o['task_id'] for o in proposal['occurrences']},{'one','six'})

    def test_missing_task_is_counted_without_leaking(self):
        self.pair();h._write_jsonl(self.v/work.TASKS,[]);result=r.reflect(self.v)
        self.assertEqual(result['proposals'],[]);self.assertEqual(result['diagnostics'],[dict(reason='missing_task_source',count=2)])
        self.assertNotIn('OUTCOME_LESSON_DO_NOT_COPY',json.dumps(result))

    def test_actor_session_takes_precedence_over_task_source(self):
        self.pair(actor_session_id='declared-session');h._write_jsonl(self.v/work.TASKS,[])
        result=r.reflect(self.v);self.assertEqual(result['proposals'],[]);self.assertEqual(result['diagnostics'],[])

    def test_bad_verification_is_skipped_and_diagnosed(self):
        rows=self.pair();path=self.v/rows[1]['verification_path'];original=path.read_bytes()
        cases=[(None,'verification_unreadable'),(b'changed','verification_hash_mismatch'),
               (b'not json','verification_unreadable'),(b'\xff','verification_unreadable')]
        for receipt in ([],{},dict(command=[]),dict(command='python test.py'),dict(command=[42]),dict(command=[''])):
            cases.append((json.dumps(receipt).encode(),'verification_command_invalid'))
        for content,reason in cases:
            with self.subTest(content=content):
                changed=dict(rows[1]);path.write_bytes(original)
                if content is None:path.unlink()
                else:
                    path.write_bytes(content)
                    if reason!='verification_hash_mismatch':changed['verification_hash']=b.digest(path)
                h._write_jsonl(self.v/d.OUTCOMES,[rows[0],changed]);result=r.reflect(self.v,True)
                self.assertEqual(result['proposals'],[]);self.assertEqual(result['diagnostics'],[dict(reason=reason,count=1)])
                self.assertFalse((self.v/r.REFLECTIONS).exists())

    def test_restricted_pattern_is_not_emitted(self):
        rows=self.pair();secret='sk-'+'x'*24
        for field in ('scope','method_path','actor_session_id','command'):
            changed=[dict(row) for row in rows]
            for row in changed:
                if field=='command':
                    path=self.v/row['verification_path'];receipt=json.loads(path.read_bytes());receipt['command']=['runner',secret]
                    path.write_text(json.dumps(receipt),encoding='utf-8');row['verification_hash']=b.digest(path)
                else:row[field]=secret if field!='actor_session_id' else secret+row['task_id']
            with self.subTest(field=field):
                h._write_jsonl(self.v/d.OUTCOMES,changed);result=r.reflect(self.v,True)
                self.assertEqual(result['proposals'],[]);self.assertEqual(result['diagnostics'],[dict(reason='restricted_pattern',count=1)])
                self.assertNotIn(secret,json.dumps(result));self.assertFalse((self.v/r.REFLECTIONS).exists())

    def test_limit_applies_to_tail_lines_before_result_filtering(self):
        self.pair();self.outcome_fixture('three','passed');self.outcome_fixture('four','passed')
        for limit in (1,2,3):self.assertEqual(r.reflect(self.v,limit=limit)['proposals'],[])
        self.assertEqual(len(r.reflect(self.v,limit=4)['proposals']),1)
        with (self.v/d.OUTCOMES).open('a',encoding='utf-8') as stream:stream.write('broken json\n# ignored\n')
        result=r.reflect(self.v,limit=2)
        self.assertEqual(result['proposals'],[]);self.assertEqual(result['diagnostics'],[dict(reason='invalid_outcome',count=1)])
        for limit in (0,-1,True,2.5):
            with self.subTest(limit=limit),self.assertRaisesRegex(ValueError,'limit_invalid'):r.reflect(self.v,limit=limit)

    def test_malformed_tail_rows_are_counted(self):
        rows=self.pair()
        bad=[dict(rows[0],actor_session_id=''),dict(rows[0],verification_kind='other'),dict(rows[0],task_id=None)]
        h._write_jsonl(self.v/d.OUTCOMES,rows+bad)
        with (self.v/d.OUTCOMES).open('a',encoding='utf-8') as stream:stream.write('[]\n{\n')
        result=r.reflect(self.v);self.assertEqual(len(result['proposals']),1)
        self.assertEqual(result['diagnostics'],[dict(reason='invalid_outcome',count=3),dict(reason='invalid_result_kind',count=1),dict(reason='invalid_session_key',count=1)])

    def test_concurrent_apply_appends_one_proposal(self):
        self.pair()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(r.reflect,self.v,True) for _ in range(2)]
            results=[future.result(timeout=10) for future in futures]
        self.assertEqual(sum(len(result['proposals']) for result in results),1)
        self.assertEqual(len(h.load_jsonl(self.v/r.REFLECTIONS)),1)

    def test_cli_json_and_options(self):
        self.pair();script=Path(__file__).with_name('ders_yansitma.py')
        command=[sys.executable,'-X','utf8',str(script),'--vault',str(self.v),'reflect','--limit','2','--min-sessions','2']
        dry=subprocess.run(command,input='',text=True,capture_output=True,check=True,timeout=10)
        result=json.loads(dry.stdout);self.assertEqual(len(result['proposals']),1);self.assertFalse(result['applied'])
        self.assertFalse((self.v/r.REFLECTIONS).exists())
        applied=subprocess.run(command+['--apply'],input='',text=True,capture_output=True,check=True,timeout=10)
        self.assertTrue(json.loads(applied.stdout)['applied']);self.assertEqual(len(h.load_jsonl(self.v/r.REFLECTIONS)),1)


if __name__=='__main__':unittest.main()
