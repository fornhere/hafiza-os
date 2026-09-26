import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch
import bilgi_agi as b
import hafiza as h
import hafiza_dongusu as d
import is_ve_ders as work
import jev_client
import ders_baglam
from gorev_baglam import build_task_package


class Lifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.v=Path(self.tmp.name)
        (self.v/'komuta').mkdir();(self.v/'komuta/jev.json').write_text('{"mode":"off"}')
        self.quote='Sunum için kısa cümle kullan; çünkü okunabilirliği artırır. Yalnız sunum anlatımında geçerlidir.'
        (self.v/'source.md').write_text(self.quote)
        self.card=dict(id='speech',title='Sunum anlatımı',kind='decision',statement='Sunum için kısa cümle kullan.',scope='project:p',domains=['sunum'],status='proposed',sources=[dict(path='source.md',sha256=b.digest(self.v/'source.md'),evidence=self.quote)],rationale='çünkü okunabilirliği artırır.',conditions='Yalnız sunum anlatımında geçerlidir.')
        (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[{'id':'p','aliases':['sunum'],'cwd_roots':[str(self.v)]}]}))

    def fake(self,vault,query,cards,**kw):
        return dict(mode='on',degraded=False,facet_scores={i:{c['id']:2 if i==0 else 0 for c in cards} for i in range(len(kw['facets']))})

    def cli(self,*args):
        stream=io.StringIO()
        with contextlib.redirect_stdout(stream):d.main(['--vault',str(self.v),*args])
        return json.loads(stream.getvalue())

    def test_review_is_bounded_idempotent_source_bound_and_scoped(self):
        b.register(self.v,self.card,True)
        b.register(self.v,dict(self.card,id='other',scope='project:q'),True)
        with patch.object(jev_client,'evaluate',side_effect=self.fake):
            first=self.cli('review-pending','--project-id','p','--limit','1','--apply')
            second=self.cli('review-pending','--project-id','p','--limit','1','--apply')
        self.assertEqual(first['pending_total'],1);self.assertTrue(first['reviews'][0]['changed'])
        self.assertEqual(second['reviews'],[]);self.assertEqual(second['already_reviewed'],1)
        self.assertEqual(b._read(self.v/'bilgi/speech.md')['status'],'proposed')
        (self.v/'source.md').write_text(self.quote+' New revision')
        stale=self.cli('review-pending','--project-id','p','--apply')
        self.assertEqual(stale['reviews'][0]['row']['status'],'degraded')

    def test_transient_failure_then_success_is_persisted(self):
        b.register(self.v,self.card,True)
        with patch.object(jev_client,'evaluate',return_value=dict(mode='on',degraded=True,diagnostics=['timeout'])):
            first=d.review_pending(self.v,'p',apply=True)
        with patch.object(jev_client,'evaluate',side_effect=self.fake) as call:
            second=d.review_pending(self.v,'p',apply=True)
            third=d.review_pending(self.v,'p',apply=True)
            self.assertEqual(call.call_count,1)
        self.assertEqual(first['reviews'][0]['row']['status'],'degraded')
        self.assertEqual(second['reviews'][0]['row']['status'],'advisory')
        self.assertEqual(second['reviews'][0]['row']['attempt'],2)
        self.assertEqual(third['reviews'],[])

    def test_stale_candidate_does_not_starve_next_candidate(self):
        b.register(self.v,self.card,True)
        b.register(self.v,dict(self.card,id='second'),True)
        with patch.object(jev_client,'evaluate',return_value=dict(mode='on',degraded=True,diagnostics=['timeout'])):
            first=d.review_pending(self.v,'p',limit=1,apply=True)
            second=d.review_pending(self.v,'p',limit=1,apply=True)
        self.assertNotEqual(first['reviews'][0]['row']['candidate_id'],second['reviews'][0]['row']['candidate_id'])

    def test_catalog_peer_comparison_contains_conditions_and_conflict(self):
        args=dict(kind='semantic',scope='project:p',subject_key='speech',source_path='source.md',source_anchor='speech',confidence='explicit-user',sensitivity='normal',proposed_by='author',evidence=self.quote)
        first=h.add_candidate(self.v,statement='Sunum için kısa cümle kullan.',rationale=self.card['rationale'],conditions=self.card['conditions'],**args)
        h.promote_candidate(self.v,first['candidate_id'],memory_id='old',reviewed_by='reviewer',apply=True)
        h.add_candidate(self.v,statement='Sunum için uzun cümle kullan.',**args)
        def fake(v,q,cards,**kw):
            return dict(mode='on',degraded=False,facet_scores={i:{c['id']:2 if i==(1 if kw['purpose']=='memory_review' else 0) else 0 for c in cards} for i in range(len(kw['facets']))})
        class WindowsSpelling(PureWindowsPath):
            def __fspath__(self): return self.as_posix()
        with patch.object(h,'CATALOG_PATH',WindowsSpelling(h.CATALOG_PATH.as_posix())), patch.object(jev_client,'evaluate',side_effect=fake) as call:
            result=d.review_pending(self.v,'p',apply=True)
        row=result['reviews'][0]['row']
        self.assertEqual(row['deterministic_assessment']['result'],'conflict')
        self.assertEqual(row['advice']['catalog_relations']['comparisons'][0]['relation'],'incompatible')
        self.assertIn(self.card['conditions'],json.dumps(call.call_args.args,ensure_ascii=False,default=str))

    def test_changed_peer_source_invalidates_review_receipt(self):
        b.register(self.v,self.card,True)
        (self.v/'peer.md').write_text('Sunum için daha uzun cümle tercih edilir.')
        peer=dict(self.card,id='peer',status='reviewed',reviewed_by='reviewer',review_note='Doğrudan kaynak incelendi.',sources=[dict(path='peer.md',sha256=b.digest(self.v/'peer.md'),evidence=(self.v/'peer.md').read_text())])
        peer.pop('rationale');peer.pop('conditions')
        b.register(self.v,peer,True)
        with patch.object(jev_client,'evaluate',side_effect=self.fake):
            first=d.review_pending(self.v,'p',apply=True)
            (self.v/'peer.md').write_text('Peer source revoked and no longer eligible.')
            second=d.review_pending(self.v,'p',apply=True)
        self.assertEqual(len(second['reviews']),1)
        self.assertNotEqual(first['reviews'][0]['row']['receipt_id'],second['reviews'][0]['row']['receipt_id'])

    def test_decision_catalog_storage_promotion_context_budget(self):
        result=h.add_candidate(self.v,statement='Sunum için kısa cümle kullan.',kind='semantic',scope='project:p',subject_key='speech',source_path='source.md',source_anchor='speech',confidence='explicit-user',sensitivity='normal',proposed_by='author',evidence=self.quote,rationale=self.card['rationale'],conditions=self.card['conditions'])
        h.promote_candidate(self.v,result['candidate_id'],memory_id='speech',reviewed_by='reviewer',apply=True)
        package=build_task_package(self.v,'sunum kısa cümle',budget=5000)
        self.assertIn(self.card['conditions'],package['text']);self.assertIn(self.card['rationale'],package['text'])
        self.assertLessEqual(len(build_task_package(self.v,'sunum',budget=30)['text']),30)
        self.assertIn('answer_verification',package)

    def outcome_fixture(self,failed=False):
        work.put(self.v,'task',dict(id='t',title='Sunum testi',status='done',source_path='source.md',evidence=self.quote,actor='worker',project_id='p'))
        (self.v/'method.md').write_text('Sunum yöntemi: kısa cümle kullan.')
        receipt=dict(task_id='t',exit_code=1 if failed else 0,passed=not failed,command=['python3','test.py'],finished_at='2026-09-19T12:00:00Z')
        raw=json.dumps(receipt);(self.v/'test.json').write_text(raw)
        return dict(task_id='t',title='Sunum dersi',lesson='Sunumda bu yöntem sınandı.',conditions='Yalnız bu sunumun koşullarında.',method_path='method.md',verification_path='test.json',verification_hash=b.digest(self.v/'test.json'),verification_evidence=raw,verification_kind='test_result',observed_result='failed' if failed else 'passed',actor='worker',triggers=['sunum'])

    def reviewed_outcome_fixture(self):
        data=self.outcome_fixture();row=d.outcome(self.v,data,True)['row']
        review=dict(receipt_id=row['receipt_id'],reviewed_by='reviewer',reason='Test makbuzu ve dersin koşulları kaynakla karşılaştırıldı.',evidence_checked=True,conditions_checked=True)
        return data,d.review_lesson(self.v,review,True)['lesson']

    def applied_outcome_fixture(self,data,lesson,task_id,result='failed',version=None):
        work.put(self.v,'task',dict(id=task_id,title='Sunum testi',status='done',source_path='source.md',evidence=self.quote,actor='worker',project_id='p'))
        raw=json.dumps(dict(task_id=task_id,exit_code=0 if result=='passed' else 1,passed=result=='passed',command=['python3','test.py'],finished_at='2026-09-19T12:00:00Z')) if result in ('passed','failed') else 'Kullanıcı sunumun sonucunu bildirdi: '+result
        path=task_id+'.json';(self.v/path).write_text(raw)
        return d.outcome(self.v,dict(data,task_id=task_id,observed_result=result,verification_kind='test_result' if result in ('passed','failed') else 'user_acceptance',verification_path=path,verification_hash=b.digest(self.v/path),verification_evidence=raw,applied_lessons=[dict(id=lesson['id'],version=lesson['version'] if version is None else version)]),True)['row']

    def test_outcome_applied_lessons_validation_and_sorting(self):
        data,lesson=self.reviewed_outcome_fixture()
        applied=dict(id=lesson['id'],version=lesson['version'])
        for value in (None,{},'lesson',[{}],[dict(applied,id='missing')],[dict(applied,version=2)],[dict(applied,version=0)],[dict(applied,version=True)],[dict(applied,version=1.0)],[dict(applied,id=[])],[dict(applied,extra=True)],[applied,applied],[applied]*21):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'applied_lessons_invalid'):
                d.outcome(self.v,dict(data,applied_lessons=value),True)
        other=work.put(self.v,'lesson',dict(lesson,id='z-lesson'))
        work.put(self.v,'lesson',dict(lesson,expected_version=lesson['version']))
        values=[dict(id=other['id'],version=other['version']),applied]
        row=d.outcome(self.v,dict(data,applied_lessons=values),True)['row']
        self.assertEqual(row['applied_lessons'],[applied,values[0]])
        self.assertEqual(values[0]['id'],'z-lesson')
        self.assertFalse(d.outcome(self.v,dict(data,applied_lessons=list(reversed(values))),True)['changed'])
        self.assertEqual(len(h.load_jsonl(self.v/d.OUTCOMES)),2)

    def test_outcome_without_applied_lessons_keeps_legacy_receipt_id(self):
        data=self.outcome_fixture();task=work.latest(self.v,'task')['t']
        expected=dict(data,task_version=task['version'],scope='project:p',project_id='p',method_hash=h.statement_hash((self.v/'method.md').read_text()),source_path=task['source_path'],source_content_hash=task['source_content_hash'],evidence=task['evidence'],status='proposed')
        row=d.outcome(self.v,data)['row']
        self.assertNotIn('applied_lessons',row)
        self.assertEqual(row['receipt_id'],d.fingerprint(expected))
        self.assertEqual(row,dict(expected,receipt_id=d.fingerprint(expected)))
        explicit=d.outcome(self.v,dict(data,applied_lessons=[]))['row']
        self.assertEqual(explicit['applied_lessons'],[])
        self.assertNotEqual(explicit['receipt_id'],row['receipt_id'])

    def test_outcome_applied_lessons_twenty_item_limit(self):
        data,lesson=self.reviewed_outcome_fixture();applied=[]
        for i in range(21):
            row=work.put(self.v,'lesson',dict(lesson,id='lesson-'+str(i)))
            applied.append(dict(id=row['id'],version=row['version']))
        self.assertEqual(len(d.outcome(self.v,dict(data,applied_lessons=applied[:20]))['row']['applied_lessons']),20)
        with self.assertRaisesRegex(ValueError,'applied_lessons_invalid'):d.outcome(self.v,dict(data,applied_lessons=applied))

    def test_review_lesson_fresh_outcome_preserves_applied_lessons(self):
        data,lesson=self.reviewed_outcome_fixture()
        row=self.applied_outcome_fixture(data,lesson,'next',result='passed')
        review=dict(receipt_id=row['receipt_id'],reviewed_by='independent',reason='Kaynak sonuç ve uygulama koşulları ayrıca incelendi.',evidence_checked=True,conditions_checked=True)
        result=d.review_lesson(self.v,review,True)
        self.assertEqual(result['lesson']['outcome_id'],row['receipt_id'])
        self.assertEqual(result['lesson']['status'],'verified')
        self.assertFalse(d.review_lesson(self.v,review,True)['changed'])

    def test_lesson_utility_dry_run_apply_and_idempotence(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        receipts=[self.applied_outcome_fixture(data,lesson,task)['receipt_id'] for task in ('first','second')]
        before={p.relative_to(self.v):p.read_bytes() for p in self.v.rglob('*') if p.is_file()}
        dry=self.cli('lesson-utility')
        self.assertEqual(dry['lessons'][ident],dict(help=0,harm=2,outcome_ids=sorted(receipts),action='review_required'))
        self.assertEqual(dry['review_required'],[ident]);self.assertFalse(dry['applied'])
        self.assertEqual(before,{p.relative_to(self.v):p.read_bytes() for p in self.v.rglob('*') if p.is_file()})
        applied=self.cli('lesson-utility','--apply');new=work.latest(self.v,'lesson')[ident]
        self.assertTrue(applied['applied']);self.assertEqual(applied['failures'],[]);self.assertEqual(applied['canonical_deletes'],0)
        self.assertEqual(new['status'],'proposed');self.assertEqual(new['actor'],'lesson-utility')
        self.assertEqual(new['review_required'],dict(reason='harm_exceeds_help',help=0,harm=2,outcome_ids=sorted(receipts)))
        self.assertEqual(new['version'],lesson['version']+1)
        history=h.load_jsonl(self.v/work.LESSONS)
        self.assertEqual(history,[lesson,new])
        self.assertEqual(len(h.load_jsonl(self.v/d.OUTCOMES)),3)
        self.assertEqual(ders_baglam.context(self.v,'sunum',project_id='p'),'')
        self.assertEqual(build_task_package(self.v,'sunum')['lessons'],dict(applied=[]))
        view=json.loads((self.v/'zihin/ders-faydasi.json').read_text())
        self.assertEqual(view['lessons'],applied['lessons']);self.assertEqual(view['min_harm'],2);self.assertTrue(view['generated_at'])
        second=self.cli('lesson-utility','--apply')
        self.assertEqual(second['review_required'],[])
        self.assertEqual(h.load_jsonl(self.v/work.LESSONS),history)

    def test_lesson_utility_min_harm_and_balanced_results(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        self.applied_outcome_fixture(data,lesson,'one')
        self.assertEqual(d.lesson_utility(self.v)['review_required'],[])
        self.assertEqual(self.cli('lesson-utility','--min-harm','1')['review_required'],[ident])
        self.applied_outcome_fixture(data,lesson,'two',result='rejected')
        self.assertEqual(self.cli('lesson-utility','--min-harm','3')['review_required'],[])
        self.applied_outcome_fixture(data,lesson,'three',result='accepted')
        self.applied_outcome_fixture(data,lesson,'four',result='passed')
        result=d.lesson_utility(self.v)
        self.assertEqual(result['lessons'][ident]['harm'],2);self.assertEqual(result['lessons'][ident]['help'],2)
        self.assertEqual(result['review_required'],[])
        for value in (0,-1,True):
            with self.assertRaisesRegex(ValueError,'min_harm_invalid'):d.lesson_utility(self.v,min_harm=value)

    def test_lesson_utility_deduplicates_and_excludes_own_outcome(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        own=h.load_jsonl(self.v/d.OUTCOMES)[0]
        h._append_jsonl(self.v/d.OUTCOMES,dict(own,applied_lessons=[dict(id=ident,version=lesson['version'])]))
        row=self.applied_outcome_fixture(data,lesson,'one')
        h._append_jsonl(self.v/d.OUTCOMES,row)
        h._append_jsonl(self.v/d.OUTCOMES,dict(row,receipt_id='another-receipt-same-verification'))
        result=d.lesson_utility(self.v)
        self.assertEqual(result['lessons'][ident],dict(help=0,harm=1,outcome_ids=[row['receipt_id']],action='none'))

    def test_lesson_utility_reapproval_ignores_old_harm_but_harmless_revisions_do_not(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        self.applied_outcome_fixture(data,lesson,'one')
        revised=work.put(self.v,'lesson',dict(lesson,expected_version=lesson['version']))
        self.applied_outcome_fixture(data,revised,'two')
        self.assertEqual(d.lesson_utility(self.v,True)['review_required'],[ident])
        demoted=work.latest(self.v,'lesson')[ident]
        reviewed=dict(demoted,status='verified',actor='reviewer',expected_version=demoted['version'])
        reviewed.pop('review_required');reviewed=work.put(self.v,'lesson',reviewed)
        self.assertIn('Sunum yöntemi',ders_baglam.context(self.v,'sunum',project_id='p'))
        self.applied_outcome_fixture(data,lesson,'old-delayed')
        self.applied_outcome_fixture(data,demoted,'at-cutoff')
        fresh=d.lesson_utility(self.v,True)
        self.assertEqual(fresh['lessons'][ident],dict(help=0,harm=0,outcome_ids=[],action='none'))
        self.assertEqual(work.latest(self.v,'lesson')[ident]['version'],reviewed['version'])
        self.applied_outcome_fixture(data,reviewed,'after-one')
        self.assertEqual(d.lesson_utility(self.v)['review_required'],[])
        self.applied_outcome_fixture(data,reviewed,'after-two')
        self.assertEqual(d.lesson_utility(self.v,True)['review_required'],[ident])
        self.assertEqual(d.lesson_utility(self.v)['lessons'][ident]['harm'],0)

    def test_lesson_utility_only_demotes_eligible_statuses(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        self.applied_outcome_fixture(data,lesson,'one');self.applied_outcome_fixture(data,lesson,'two')
        rejected=work.put(self.v,'lesson',dict(lesson,status='rejected',expected_version=lesson['version']))
        self.assertEqual(d.lesson_utility(self.v,True)['review_required'],[])
        proposed=work.put(self.v,'lesson',dict(rejected,status='proposed',expected_version=rejected['version']))
        self.assertEqual(d.lesson_utility(self.v,True)['review_required'],[ident])
        flagged=work.latest(self.v,'lesson')[ident]
        self.assertEqual(flagged['version'],proposed['version']+1)
        flagged=work.put(self.v,'lesson',dict(flagged,status='verified',expected_version=flagged['version']))
        self.applied_outcome_fixture(data,flagged,'three');self.applied_outcome_fixture(data,flagged,'four')
        self.assertEqual(d.lesson_utility(self.v,True)['review_required'],[])
        self.assertEqual(work.latest(self.v,'lesson')[ident],flagged)

    def test_lesson_utility_reports_put_failure_and_continues(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        self.applied_outcome_fixture(data,lesson,'one');self.applied_outcome_fixture(data,lesson,'two')
        other=work.put(self.v,'lesson',dict(lesson,id='z-lesson'))
        self.applied_outcome_fixture(data,other,'three');self.applied_outcome_fixture(data,other,'four')
        original=work.put
        def put(vault,kind,row):
            if row['id']==ident:raise ValueError('source_changed')
            return original(vault,kind,row)
        with patch.object(work,'put',side_effect=put):result=d.lesson_utility(self.v,True)
        self.assertEqual(result['failures'],[dict(id=ident,reason='demotion_failed:source_changed')])
        self.assertEqual(result['lessons'][ident]['action'],'demotion_failed:source_changed')
        self.assertEqual(result['review_required'],[other['id']])
        self.assertEqual(work.latest(self.v,'lesson')[ident],lesson)
        self.assertEqual(work.latest(self.v,'lesson')[other['id']]['status'],'proposed')

    def test_lesson_utility_never_rebinds_changed_source(self):
        data,lesson=self.reviewed_outcome_fixture();ident=lesson['id']
        self.applied_outcome_fixture(data,lesson,'one');self.applied_outcome_fixture(data,lesson,'two')
        (self.v/'source.md').write_text(self.quote+' Kaynak artık değişti.')
        result=d.lesson_utility(self.v,True)
        self.assertEqual(result['failures'],[dict(id=ident,reason='demotion_failed:lesson_source_changed')])
        self.assertEqual(work.latest(self.v,'lesson')[ident],lesson)
        self.assertEqual(ders_baglam.context(self.v,'sunum',project_id='p'),'')

    def test_task_package_applied_lessons_follow_delivered_methods(self):
        data,lesson=self.reviewed_outcome_fixture()
        package=build_task_package(self.v,'sunum',budget=5000)
        self.assertIn('methods',package['selected_ids'])
        self.assertEqual(package['lessons'],dict(applied=[dict(id=lesson['id'],version=lesson['version'])]))
        self.assertIn(ders_baglam.context(self.v,'sunum',project_id='p'),package['text'])
        self.assertEqual(build_task_package(self.v,'sunum',budget=30)['lessons'],dict(applied=[]))
        with patch('ders_baglam.context_details',wraps=ders_baglam.context_details) as call:
            method_budget=len(ders_baglam.context(self.v,'sunum',project_id='p'))
            package=build_task_package(self.v,'sunum',budget=method_budget)
            self.assertTrue(call.called)
        self.assertNotIn('methods',package['selected_ids']);self.assertEqual(package['lessons'],dict(applied=[]))

    def test_task_package_clears_applied_lessons_on_source_change(self):
        data,lesson=self.reviewed_outcome_fixture();original=ders_baglam.context_details
        def changing(*args,**kwargs):
            details=original(*args,**kwargs)
            work.put(self.v,'lesson',dict(lesson,status='rejected',expected_version=lesson['version']))
            return details
        with patch('ders_baglam.context_details',side_effect=changing):package=build_task_package(self.v,'sunum')
        self.assertIn('source_changed_during_package',package['omitted_reasons'])
        self.assertEqual(package['lessons'],dict(applied=[]))

    def test_task_package_skipped_by_gate_has_no_applied_lessons(self):
        self.reviewed_outcome_fixture()
        gate=dict(mode='rerank',degraded=False)
        with patch.object(jev_client,'purpose_mode',return_value='rerank'), patch.object(jev_client,'load_config',return_value=dict(jev_client.DEFAULTS,rerank_gate_scope='all')), patch('jev_retrieval.rerank_gate',return_value=(False,gate)):
            package=build_task_package(self.v,'sunum')
        self.assertEqual(package['text'],'')
        self.assertEqual(package['selected_ids'],[])
        self.assertEqual(package['lessons'],dict(applied=[]))

    def test_verified_outcome_review_next_task_and_stale_evidence(self):
        data=self.outcome_fixture(failed=True);(self.v/'input.json').write_text(json.dumps(data))
        proposed=self.cli('outcome','--input-json',str(self.v/'input.json'),'--apply')
        self.assertEqual(ders_baglam.context(self.v,'sunum',project_id='p'),'')
        self.assertFalse(self.cli('outcome','--input-json',str(self.v/'input.json'),'--apply')['changed'])
        review=dict(receipt_id=proposed['row']['receipt_id'],reviewed_by='reviewer',reason='Test makbuzu ve dersin koşulları kaynakla karşılaştırıldı.',evidence_checked=True,conditions_checked=True)
        (self.v/'review.json').write_text(json.dumps(review))
        self.cli('review-lesson','--input-json',str(self.v/'review.json'),'--apply')
        context=build_task_package(self.v,'sunum',budget=5000)['text']
        self.assertIn('failed',context);self.assertIn(data['conditions'],context)
        self.assertEqual(ders_baglam.context(self.v,'sunum',project_id='q'),'')
        self.assertFalse(self.cli('review-lesson','--input-json',str(self.v/'review.json'),'--apply')['changed'])
        (self.v/'test.json').write_text('{}')
        self.assertEqual(ders_baglam.context(self.v,'sunum',project_id='p'),'')
        with self.assertRaises(ValueError):d.review_lesson(self.v,review,True)

    def test_self_rating_and_same_actor_not_accepted(self):
        data=self.outcome_fixture();data['observed_result']='great'
        with self.assertRaises(ValueError):d.outcome(self.v,data,True)
        data['observed_result']='passed';row=d.outcome(self.v,data,True)['row']
        with self.assertRaises(ValueError):d.review_lesson(self.v,dict(receipt_id=row['receipt_id'],reviewed_by='worker',reason='Long enough explanation of alleged success.',evidence_checked=True,conditions_checked=True),True)

    def test_no_jev_queue_stays_pending(self):
        b.register(self.v,self.card,True)
        report=self.cli('review-pending','--project-id','p','--apply')
        self.assertEqual(report['reviews'][0]['row']['status'],'disabled')
        self.assertEqual(b._read(self.v/'bilgi/speech.md')['status'],'proposed')
