import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import gelisim_dongusu as g
from platform_lock import exclusive_lock


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.v=Path(self.temp.name); (self.v/'source').write_text('verified source')
        self.out=self.v/'experiments'
        self.c=dict(schema=1,label_status='agent_labels',source_versions={'source':hashlib.sha256(b'verified source').hexdigest()},
            candidates=[dict(id=str(i),title=str(i),statement='fact '+str(i),scope='user',domains=[],families=['family'+str(i)]) for i in range(6)],
            cases=[dict(id=str(i),query='question '+str(i),scope='user',expected=[str(i)],allowed=[str(i)],families=['family'+str(i)],origin='synthetic') for i in range(6)])
        self.c['cases'] += [dict(id=str(i),query='unknown '+str(i),scope='user',expected=[],allowed=[],families=['negative'+str(i)],origin='synthetic') for i in (6,7)]
        self.calls=0

    def evaluate(self,v,q,rows,**kwargs):
        self.calls+=1; ident=q.strip()[-1]
        return dict(mode='shadow',scores={r['id']:1.4 if r['id']==ident else 0 for r in rows},usage={'input_tokens':10},latency_ms=1)

    def test_winner_is_shadow_and_same_run_free(self):
        result=g.run(self.v,self.c,self.out,self.evaluate)
        self.assertEqual(result['status'],'shadow_candidate')
        self.assertEqual(result['shadow_candidate']['threshold'],1.3)
        before=self.calls
        self.assertEqual(g.run(self.v,self.c,self.out,self.evaluate)['status'],'unchanged')
        self.assertEqual(before,self.calls)
        report=json.loads(Path(result['report']).read_text())
        self.assertFalse(report['production_changed'])
        self.assertEqual((self.v/'source').read_text(),'verified source')

    def test_no_improvement_skips_holdout(self):
        def perfect(v,q,rows,**kw):
            answer=self.evaluate(v,q,rows,**kw)
            answer['scores']={i:2 if s else 0 for i,s in answer['scores'].items()}; return answer
        result=g.run(self.v,self.c,self.out,perfect)
        self.assertEqual(result['status'],'no_improvement')
        self.assertEqual(self.calls,len(g.split(self.c['cases'])[0])*3)

    def test_holdout_cannot_choose_another_candidate(self):
        _,held=g.split(self.c['cases']); ids={c['id'] for c in held}
        def bad(v,q,rows,**kw):
            answer=self.evaluate(v,q,rows,**kw)
            if q.strip()[-1] in ids: answer['scores']={r['id']:1.4 for r in rows}
            return answer
        result=g.run(self.v,self.c,self.out,bad)
        self.assertEqual(result['status'],'holdout_rejected'); self.assertIsNone(result['shadow_candidate'])

    def test_family_leakage_and_bridge(self):
        cases=copy.deepcopy(self.c['cases'])
        cases[0]['families']=['a']; cases[1]['families']=['b']; cases[2]['families']=['a','b']
        dev,held=g.split(cases)
        self.assertFalse({f for c in dev for f in c['families']} & {f for c in held for f in c['families']})

    def test_stale_before_call(self):
        (self.v/'source').write_text('changed')
        with self.assertRaisesRegex(ValueError,'stale'): g.run(self.v,self.c,self.out,self.evaluate)
        self.assertEqual(self.calls,0)

    def test_stale_during_call_fails(self):
        def mutate(*a,**kw):
            answer=self.evaluate(*a,**kw); (self.v/'source').write_text('changed'); return answer
        result=g.run(self.v,self.c,self.out,mutate)
        self.assertEqual(result['status'],'failed'); self.assertEqual(self.calls,1)

    def test_failure_not_a_negative_label_or_retry(self):
        def broken(*a,**kw): return dict(mode='shadow',degraded=True,scores={})
        result=g.run(self.v,self.c,self.out,broken)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(g.run(self.v,self.c,self.out,broken)['status'],'unchanged')

    def test_budget_preflight(self):
        with patch.object(g,'MAX_CALLS',1):
            with self.assertRaisesRegex(ValueError,'preflight'): g.run(self.v,self.c,self.out,self.evaluate)
        self.assertEqual(self.calls,0)

    def test_token_overrun_cannot_produce_candidate(self):
        with patch.object(g,'MAX_TOKENS',5):
            result=g.run(self.v,self.c,self.out,self.evaluate)
        self.assertEqual(result['status'],'failed'); self.assertEqual(self.calls,1)
        self.assertIsNone(result['shadow_candidate'])

    def test_config_change_during_call(self):
        def mutate(*a,**kw):
            answer=self.evaluate(*a,**kw)
            (self.v/'komuta').mkdir(); (self.v/'komuta/jev.json').write_text('{"mode":"shadow"}')
            return answer
        result=g.run(self.v,self.c,self.out,mutate)
        self.assertEqual(result['status'],'failed'); self.assertEqual(self.calls,1)

    def test_explicit_timeout_resume_keeps_total_calls(self):
        def timeout(*a,**kw): return dict(mode='shadow',degraded=True,scores={},diagnostics=['deadline_exceeded'])
        first=g.run(self.v,self.c,self.out,timeout)
        self.assertEqual(first['calls'],1)
        second=g.run(self.v,self.c,self.out,self.evaluate,resume=True)
        self.assertEqual(second['status'],'shadow_candidate')
        report=json.loads(Path(second['report']).read_text())
        self.assertEqual(report['attempts'],2); self.assertEqual(report['calls'],self.calls+1)
        self.assertEqual(report['previous_attempt']['status'],'failed')
        with self.assertRaisesRegex(ValueError,'eligible'): g.run(self.v,self.c,self.out,self.evaluate,resume=True)

    def test_no_resume_after_holdout(self):
        result=g.run(self.v,self.c,self.out,self.evaluate)
        path=Path(result['report']); report=json.loads(path.read_text())
        report.update(status='failed',last_inference={'diagnostics':['deadline_exceeded']})
        g.write(path,report)
        with self.assertRaisesRegex(ValueError,'eligible'): g.run(self.v,self.c,self.out,self.evaluate,resume=True)

    def test_holdout_not_repackaged(self):
        g.run(self.v,self.c,self.out,self.evaluate)
        self.c['label_status']='repacked'
        with self.assertRaisesRegex(ValueError,'consumed'): g.run(self.v,self.c,self.out,self.evaluate)

    def test_scope_cannot_leak(self):
        self.c['candidates'][0]['scope']='project:other'
        with self.assertRaisesRegex(ValueError,'scope'): g.run(self.v,self.c,self.out,self.evaluate)

    def test_missing_family_provenance_rejected(self):
        self.c['cases'][0]['families']=['fake']
        with self.assertRaisesRegex(ValueError,'provenance'): g.validate(self.c)

    def test_concurrent_campaign_rejected(self):
        self.out.mkdir()
        with exclusive_lock(self.out/'.lock'):
            with self.assertRaises(TimeoutError): g.run(self.v,self.c,self.out,self.evaluate)
        self.assertEqual(self.calls,0)

if __name__=='__main__': unittest.main()
