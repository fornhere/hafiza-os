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
