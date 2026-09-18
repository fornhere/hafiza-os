import json
import os
import tempfile
import time
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
        return j.evaluate(self.vault,'question',self.cards,transport=self.transport,**kw)
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
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn('test-key',path.read_text());self.assertNotIn('question',path.read_text())
    def test_facets(self):
        self.config()
        r=self.run_client(facets=['A','B']);self.assertEqual(len(r['facet_scores']),2)
        self.assertEqual(set(self.calls[0]['questions']),{'f0_c0','f1_c0'})
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
        def slow(*args): time.sleep(0.1); return {}
        start=time.monotonic()
        result=j.evaluate(self.vault,'q',self.cards,transport=slow)
        self.assertLess(time.monotonic()-start,0.09)
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

if __name__=='__main__': unittest.main()
