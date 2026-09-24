import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import jev_client as j

class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.vault=Path(self.temp.name); (self.vault/'komuta').mkdir()
        self.cards=[dict(id='one',title='A',statement='B',scope='user',domains=['all'],secret_extra='never send')]
        self.calls=[]
        self.env=patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-key'},clear=True);self.env.start();self.addCleanup(self.env.stop)
    def config(self,**kw):
        (self.vault/'komuta/jev.json').write_text(json.dumps(dict(mode='shadow',**kw)))
    def transport(self,url,body,key,timeout):
        self.calls.append(body)
        self.assertNotIn('secret_extra',json.dumps(body))
        return dict(answers={q:dict(type='score',score=1.8,confidence='ignored') for q in body['questions']},usage=dict(input_tokens=3,output_tokens=2))
    def run_client(self,**kw):
        kw.setdefault('transport',self.transport)
        return j.evaluate(self.vault,'question',self.cards,**kw)
    def test_default_off(self):
        self.assertEqual(self.run_client()['mode'],'off');self.assertFalse(self.calls)
    def test_cache_source_and_scope_binding(self):
        self.config()
        a=self.run_client(source_versions={'a':'1'});self.assertEqual(a['scores'],{'one':1.8})
        self.assertTrue(self.run_client(source_versions={'a':'1'})['cache_hit'])
        self.assertFalse(self.run_client(source_versions={'a':'2'})['cache_hit'])
        self.assertFalse(self.run_client(source_versions={'a':'2'},scope='project:other')['cache_hit'])
        self.assertEqual(len(self.calls),3)
        for path in (self.vault/'.cache/jev').glob('*.json'):
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn('test-key',path.read_text());self.assertNotIn('question',path.read_text())
    def test_facets(self):
        self.config()
        r=self.run_client(facets=['A','B']);self.assertEqual(len(r['facet_scores']),2)
        self.assertEqual(set(self.calls[0]['questions']),{'f0_c0','f1_c0'})
    def test_choice_and_noul_are_validated_and_cached(self):
        self.config()
        choices={'search_memory':.8,'no_memory':.1,'insufficient_context':.1}
        def gate(*args): return {'answers':{'f0_c0':dict(type='choice',choice='search_memory',probabilities=choices)}}
        first=self.run_client(purpose='retrieval_gate',transport=gate)
        self.assertFalse(first['degraded']);self.assertEqual(first['choices']['one'],'search_memory')
        self.assertEqual(self.run_client(purpose='retrieval_gate',transport=gate)['distributions']['one'],choices)
        self.assertTrue(self.run_client(purpose='retrieval_gate',transport=gate)['cache_hit'])
        def noul(*args): return {'answers':{'f0_c0':dict(type='noul',noul=.83)}}
        result=self.run_client(question_type='noul',transport=noul)
        self.assertEqual(result['distributions']['one']['true'],.83)
        self.assertTrue(self.run_client(question_type='noul',transport=noul)['cache_hit'])
        invalid=self.run_client(purpose='retrieval_gate',source_versions={'new':'1'},
                                transport=lambda *a:{'answers':{'f0_c0':dict(type='score',score=2)}})
        self.assertTrue(invalid['degraded']);self.assertIn('answers_invalid',invalid['diagnostics'])
    def test_bad_answers_do_not_cache(self):
        self.config()
        for value in [float('nan'),True,3,-1]:
            r=j.evaluate(self.vault,'q',self.cards,transport=lambda *a:dict(answers={'f0_c0':dict(type='score',score=value)}))
            self.assertTrue(r['degraded']);self.assertEqual(r['scores'],{})
        self.assertFalse(list((self.vault/'.cache/jev').glob('*.json')))
    def test_missing_extra_answers(self):
        self.config()
        for answers in [{},{'other':dict(type='score',score=2)}]:
            self.assertTrue(j.evaluate(self.vault,'q',self.cards,transport=lambda *a:dict(answers=answers))['degraded'])
    def test_budget_and_bad_config(self):
        self.config(max_questions=1)
        self.assertTrue(self.run_client(facets=['A','B'])['degraded']);self.assertFalse(self.calls)
        (self.vault/'komuta/jev.json').write_text('{bad')
        self.assertEqual(j.inspect_config(self.vault)['valid'],False)
        self.assertIn('config_invalid',self.run_client()['diagnostics'])
    def test_endpoint_and_error_redaction(self):
        self.config(base_url='http://example.com')
        self.assertTrue(self.run_client()['degraded']);self.assertFalse(self.calls)
        self.config()
        def bad(*args): raise RuntimeError('test-key PRIVATE')
        r=j.evaluate(self.vault,'q',self.cards,transport=bad)
        self.assertNotIn('PRIVATE',json.dumps(r));self.assertNotIn('test-key',json.dumps(r))
    def test_env_file_literal_not_executed(self):
        keyfile=self.vault/'env';keyfile.write_text('TYPESAFE_API_KEY="$(touch nope)"\n')
        self.config(env_file=str(keyfile))
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(j._environment(j.load_config(self.vault))['TYPESAFE_API_KEY'],'$(touch nope)')
        self.assertFalse((self.vault/'nope').exists())
    def test_deadline(self):
        self.config(timeout=0.02)
        entered=threading.Event()
        release=threading.Event()
        returned=threading.Event()
        transport_threads=[]
        timeouts=[]
        results=[]
        errors=[]
        guard=10  # Deadlock guard, not a caller-latency performance assertion.
        def stalled(endpoint,body,key,timeout):
            transport_threads.append(threading.current_thread())
            timeouts.append(timeout)
            entered.set()
            release.wait()
            return {}
        def call():
            try:
                results.append(j.evaluate(self.vault,'q',self.cards,transport=stalled))
            except Exception as exc:
                errors.append(exc)
            finally:
                returned.set()
        caller=threading.Thread(target=call,daemon=True)
        # Freeze elapsed-time bookkeeping so slow setup cannot exhaust the budget
        # before transport starts. Queue.get still uses its real timed wait.
        with patch.object(j.time,'monotonic',return_value=0):
            caller.start()
            try:
                self.assertTrue(entered.wait(guard),'transport did not start')
                self.assertTrue(returned.wait(guard),'caller waited for stalled transport')
                self.assertFalse(release.is_set())
                self.assertTrue(transport_threads[0].is_alive())
            finally:
                release.set()
                caller.join(guard)
                for worker in transport_threads:
                    worker.join(guard)
        self.assertFalse(caller.is_alive(),'caller did not stop during cleanup')
        self.assertTrue(all(not worker.is_alive() for worker in transport_threads))
        self.assertEqual(errors,[])
        self.assertEqual(timeouts,[0.02])
        self.assertEqual(len(results),1)
        result=results[0]
        self.assertTrue(result['degraded'])
        self.assertIn('deadline_exceeded',result['diagnostics'])
    def test_bad_distribution(self):
        self.config()
        result=j.evaluate(self.vault,'q',self.cards,transport=lambda *a:dict(answers={
            'f0_c0':dict(type='score',score=1,probabilities=[0.1,0.1,0.1])}))
        self.assertTrue(result['degraded'])
    def test_categorized_errors(self):
        import urllib.error
        self.config()
        for status,expected in [(401,'http_unauthorized'),(429,'http_rate_limited'),(503,'http_server_error')]:
            def fail(*args): raise urllib.error.HTTPError('https://example.com',status,'PRIVATE',{},None)
            result=j.evaluate(self.vault,'q',self.cards,transport=fail)
            self.assertIn(expected,result['diagnostics'])
            self.assertNotIn('PRIVATE',json.dumps(result))
    def test_metadata_and_config(self):
        self.config()
        result=j.evaluate(self.vault,'q',self.cards,transport=lambda *a:dict(model='jev-1.13.0',answers={
            'f0_c0':dict(type='score',score=1,confidence=0.8)}))
        self.assertEqual(result['reported_model'],'jev-1.13.0')
        self.assertEqual(result['confidence_provenance']['present'],1)
        self.assertFalse(result['confidence_provenance']['used_for_selection'])
        for config in [dict(env_file=123),dict(timeout=float('nan')),dict(timeout=float('inf'))]:
            self.config(**config)
            self.assertFalse(j.inspect_config(self.vault)['valid'])
    def test_cache_expiry(self):
        self.config(cache_ttl=1);self.run_client()
        path=next((self.vault/'.cache/jev').glob('*.json'));v=json.loads(path.read_text());v['created_at']=0;path.write_text(json.dumps(v))
        self.assertFalse(self.run_client()['cache_hit'])

    def test_invalid_answer_diagnostics_preserve_usage_without_raw_content(self):
        self.config()
        variants = [
            ({}, 'answer_keys_mismatch'),
            ({'f0_c0':dict(type='choice',score=1)}, 'answer_type'),
            ({'f0_c0':dict(type='score',score=True)}, 'score_range_or_type'),
            ({'f0_c0':dict(type='score',score=1,probabilities={'bad':1})}, 'probability_keys'),
            ({'f0_c0':dict(type='score',score=1,probabilities=[.5,.5])}, 'probability_shape'),
            ({'f0_c0':dict(type='score',score=1,probabilities=[-.1,.1,1])}, 'probability_range_or_type'),
            ({'f0_c0':dict(type='score',score=1,probabilities=[.33,.33,.33])}, 'probability_sum')]
        for answers,issue in variants:
            result=j.evaluate(self.vault,'q',self.cards,transport=lambda *a:dict(answers=answers,private='DO NOT LOG',usage={'input_tokens':5,'output_tokens':2}))
            self.assertTrue(result['degraded']); self.assertEqual(result['answer_issue'],issue)
            self.assertEqual(result['usage'],{'input_tokens':5,'output_tokens':2})
            self.assertNotIn('DO NOT LOG',json.dumps(result))
            self.assertEqual(result['scores'],{})
        self.assertFalse(list((self.vault/'.cache/jev').glob('*.json')))

    def test_purpose_profiles_and_cache_separation(self):
        self.config()
        for purpose in ('retrieval','memory_review','evidence_review'):
            result=self.run_client(purpose=purpose,facets=['Requested relationship'])
            self.assertFalse(result['degraded']);self.assertFalse(result['cache_hit'])
            self.assertEqual(result['purpose'],purpose)
            self.assertTrue(self.run_client(purpose=purpose,facets=['Requested relationship'])['cache_hit'])
        self.assertEqual(len(self.calls),3)
        self.assertEqual(self.calls[0]['questions']['f0_c0']['criteria'],j.CRITERIA)
        self.assertEqual(self.calls[1]['questions']['f0_c0']['criteria'],j.REVIEW_CRITERIA)
        self.assertIn('anchor record',self.calls[1]['questions']['f0_c0']['instructions'])
        self.assertIn('unapproved proposal',self.calls[1]['questions']['f0_c0']['instructions'])
        self.assertIn('exact evidence quotes',self.calls[2]['questions']['f0_c0']['instructions'])
        self.assertNotEqual(self.calls[1]['questions'],self.calls[2]['questions'])

    def test_unknown_purpose_rejected_before_network(self):
        self.config()
        for purpose in ('raw_prompt',None,[]):
            result=self.run_client(purpose=purpose)
            self.assertTrue(result['degraded']);self.assertIn('purpose_invalid',result['diagnostics'])
        self.assertFalse(self.calls)

    def test_http_status_only_no_response_body_or_retry(self):
        import urllib.error
        self.config();calls=[]
        def fail(*args):
            calls.append(1)
            raise urllib.error.HTTPError('https://example.com/private',502,'PRIVATE error details',{},None)
        result=j.evaluate(self.vault,'q',self.cards,transport=fail)
        self.assertEqual(result['http_status'],502);self.assertEqual(calls,[1])
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertTrue(result['degraded'])

    def test_captured_vercel_quantization_provider_only(self):
        cases=[(.63,{'0':.4,'1':.56,'2':.03}),(.08,{'0':.93,'1':.05,'2':.01})]
        for score,probabilities in cases:
            raw={'answers':{'x':dict(type='score',score=score,probabilities=probabilities)}}
            with self.assertRaises(ValueError):j._scores(raw,['x'])
            count=[]
            self.assertEqual(j._scores(raw,['x'],allow_quantized=True,quantized_counter=count),{'x':(score,probabilities,None)})
            self.assertEqual(count,['x'])
        self.config(provider='vercel',base_url='https://ai-gateway.vercel.sh/typesafe')
        os.environ['AI_GATEWAY_API_KEY']='test-gateway-key'
        def response(*args):return dict(answers={'f0_c0':dict(type='score',score=.63,probabilities={'2':.03,'0':.4,'1':.56})})
        result=j.evaluate(self.vault,'q',self.cards,transport=response)
        self.assertFalse(result['degraded']);self.assertEqual(result['quantized_probability_count'],1)
        self.assertIn('quantized_probability',result['diagnostics']);self.assertEqual(result['scores'],{'one':.63})
        cached=j.evaluate(self.vault,'q',self.cards,transport=response)
        self.assertTrue(cached['cache_hit']);self.assertEqual(cached['quantized_probability_count'],1)
        self.assertEqual(cached['distributions'],result['distributions'])
        self.config(provider='typesafe')
        self.assertTrue(j.evaluate(self.vault,'q',self.cards,transport=response)['degraded'])

    def test_quantization_rejects_infeasible_distribution_and_score(self):
        for score,probabilities in [(1,[0,0,0]),(.63,[.4,.56,.0]),(1.2,[.4,.56,.03]),
                                    (.63,[.401,.56,.03]),(.08,[.93,.05,.04]),
                                    (1,[-.01,.5,.5]),(1,[True,.0,.0]),(1,['.4',.56,.03])]:
            raw={'answers':{'x':dict(type='score',score=score,probabilities=probabilities)}}
            with self.assertRaises(ValueError):j._scores(raw,['x'],allow_quantized=True)
        # A sum above one can also be valid independent rounding, not normalization.
        raw={'answers':{'x':dict(type='score',score=1,probabilities=[.34,.34,.33])}}
        self.assertEqual(j._scores(raw,['x'],allow_quantized=True),{'x':(1.0,{'0':.34,'1':.34,'2':.33},None)})

if __name__=='__main__': unittest.main()
