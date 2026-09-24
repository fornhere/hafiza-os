"""Regression tests use fake transport and isolated vaults, never live services."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import jev_client as j
import jev_runtime as runtime
import client_hafiza as native
import codex_hafiza as codex
import gorev_baglam as g

CARDS = [dict(id='one',title='One',statement='Evidence',scope='user',domains=['all'])]

def answer(body):
    return dict(answers={q:dict(type='score',score=2) for q in body['questions']})

class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);(self.v/'komuta').mkdir()
        self.config()
        self.env=patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-key'},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
    def config(self,**values):
        (self.v/'komuta/jev.json').write_text(json.dumps(dict(mode='shadow',procedure_mode='on',**values)))
    def test_native_policy_covers_procedures_and_does_not_mutate_other_callers(self):
        (self.v/'YAYINLAMA.md').write_text('release')
        entered=threading.Event();release=threading.Event()
        original=g.build_task_package
        def blocked(*args,**kwargs):
            entered.set();self.assertTrue(release.wait(5));return original(*args,**kwargs)
        with patch.object(g,'build_task_package',side_effect=blocked), patch.object(j,'evaluate') as evaluate:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(native.local_task_package,self.v,'Hafıza kodunu yayımla')
                self.assertTrue(entered.wait(5))
                self.assertEqual(j.load_config(self.v)['mode'],'shadow')
                release.set();future.result(5)
            evaluate.assert_not_called()
    def test_probability_sum_alone_does_not_validate_score(self):
        raw={'answers':{'x':dict(type='score',score=2,probabilities=[1,0,0])}}
        for quantized in (False,True):
            with self.assertRaisesRegex(ValueError,'answers_invalid'):
                j._scores(raw,['x'],allow_quantized=quantized)
        consistent={'answers':{'x':dict(type='score',score=1.3,probabilities=[0,.7,.3])}}
        self.assertEqual(j._scores(consistent,['x']),{'x':(1.3,{'0':0,'1':.7,'2':.3},None)})

    def test_single_flight_threads(self):
        started=[]
        def transport(url,body,key,timeout):
            started.append(1);time.sleep(.08);return answer(body)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(lambda _:j.evaluate(self.v,'same',CARDS,transport=transport),range(6)))
        self.assertEqual(len(started),1)
        self.assertTrue(all(r['scores']=={'one':2} for r in results))
        self.assertEqual(sum(r['cache_hit'] for r in results),5)
    def test_timed_out_workers_keep_slots_until_transport_finishes(self):
        self.config(timeout=.06)
        release=threading.Event();workers=[];started=[]
        original_thread=threading.Thread
        def tracked_thread(*args,**kwargs):
            worker=original_thread(*args,**kwargs);workers.append(worker);return worker
        def stalled(url,body,key,timeout):
            started.append(1)
            release.wait(5);return answer(body)
        try:
            with patch.object(runtime.threading,'Thread',side_effect=tracked_thread):
                results=[j.evaluate(self.v,'different-'+str(n),CARDS,transport=stalled) for n in range(7)]
            self.assertTrue(all(r['degraded'] for r in results))
            self.assertEqual(len(started),runtime.MAX_INFLIGHT)
            self.assertTrue(all(r['scores']=={} for r in results))
        finally:
            release.set()
            for worker in workers:
                worker.join(5)
                self.assertFalse(worker.is_alive(),'request worker still holds temporary vault')
        self.assertTrue(all(r['scores']=={} for r in results),'late answer mutated fallback')
    def test_single_flight_processes(self):
        script = '''import sys,json,time,os
from pathlib import Path
import jev_client as j
v=Path(sys.argv[1])
cards=[dict(id='one',title='One',statement='Evidence',scope='user',domains=['all'])]
def transport(url,body,key,timeout):
 fd=os.open(v/'calls',os.O_APPEND|os.O_CREAT|os.O_WRONLY,0o600)
 os.write(fd,b'call\\n');os.close(fd);time.sleep(.1)
 return dict(answers={q:dict(type='score',score=2) for q in body['questions']})
print(json.dumps(j.evaluate(v,'same',cards,transport=transport)))
'''
        env=dict(os.environ,PYTHONPATH=str(Path(j.__file__).parent))
        children=[subprocess.Popen([sys.executable,'-c',script,str(self.v)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
        try:
            for child in children:
                stdout,stderr=child.communicate(timeout=10)
                self.assertEqual(child.returncode,0,stderr)
                self.assertEqual(json.loads(stdout)['scores'],{'one':2})
        finally:
            for child in children:
                if child.poll() is None:child.kill();child.wait()
        self.assertEqual((self.v/'calls').read_text().count('call'),1)
    def test_package_independent_readers_overlap(self):
        (self.v/'bilgi').mkdir();barrier=threading.Barrier(3)
        def knowledge(*a,**kw):barrier.wait(5);return dict(text='',records=[],source_versions={})
        def procedure(*a,**kw):barrier.wait(5);return dict(text='',paths=[],source_versions={})
        def catalog(*a,**kw):barrier.wait(5);return [],None
        with patch('konu_sentezi.retrieve',side_effect=knowledge),patch('jev_procedures.route',side_effect=procedure),patch('jev_retrieval.catalog',side_effect=catalog):
            self.assertEqual(g.build_task_package(self.v,'hello')['text'],'')
    def test_context_config_snapshot_does_not_change_mid_package(self):
        with j.evaluation_context(self.v):
            self.config(retrieval_mode='off')
            self.assertEqual(j.load_config(self.v)['retrieval_mode'],'inherit')
        self.assertEqual(j.load_config(self.v)['retrieval_mode'],'off')
    def test_dynamic_metrics_do_not_defeat_repeat_suppression(self):
        package=dict(text='Stable context',source_versions={'note':'v1'},jev={'latency_ms':1})
        with patch.object(g,'build_task_package',return_value=package):
            codex.hook(self.v,dict(session_id='s',turn_id='1',hook_event_name='UserPromptSubmit',prompt='göreve devam'))
            package['jev']={'latency_ms':2,'cache_hit':True}
            out=codex.hook(self.v,dict(session_id='s',turn_id='2',hook_event_name='UserPromptSubmit',prompt='göreve devam'))
            self.assertEqual(out,{})
            package['source_versions']['note']='v2'
            self.assertTrue(codex.hook(self.v,dict(session_id='s',turn_id='3',hook_event_name='UserPromptSubmit',prompt='göreve devam')))

    def test_hook_sessions_do_not_share_a_network_lock(self):
        # Real CLI dispatch with a deliberately stalled local package builder.
        script = """import sys,time
from pathlib import Path
import gorev_baglam as g,codex_hafiza as h
v=Path(sys.argv[1]);ident=sys.argv[2]
def package(*a,**kw):
 (v/('entered-'+ident)).write_text('yes')
 if ident=='one':
  end=time.monotonic()+5
  while not (v/'release').exists() and time.monotonic()<end:time.sleep(.01)
 return dict(text='')
g.build_task_package=package
sys.argv=['codex_hafiza.py','--vault',str(v),'hook'];h.main()
"""
        env=dict(os.environ,PYTHONPATH=str(Path(j.__file__).parent))
        children=[]
        def start(ident):
            child=subprocess.Popen([sys.executable,'-c',script,str(self.v),ident],env=env,
                                   stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            children.append(child)
            child.stdin.write(json.dumps(dict(session_id=ident,turn_id='t',hook_event_name='UserPromptSubmit',prompt='göreve devam')))
            child.stdin.close();child.stdin=None
            return child
        def entered(ident):
            end=time.monotonic()+3
            while time.monotonic()<end:
                if (self.v/('entered-'+ident)).exists():return True
                time.sleep(.01)
            return False
        try:
            start('one');self.assertTrue(entered('one'))
            second=start('two');self.assertTrue(entered('two'),'another session waited behind inference')
            stdout,stderr=second.communicate(timeout=3);self.assertEqual(second.returncode,0,stderr)
        finally:
            (self.v/'release').write_text('go')
            for child in children:
                try:child.communicate(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.communicate()

    def test_source_changed_after_reader_finishes_is_not_delivered(self):
        (self.v/'bilgi').mkdir();source=self.v/'source.md';source.write_text('old evidence')
        old_hash=g.digest(source);done=threading.Event()
        def knowledge(*args,**kwargs):
            done.set();return dict(text='Old claim',records=[],source_versions={'source.md':old_hash})
        def catalog(*args,**kwargs):
            self.assertTrue(done.wait(5));source.write_text('new contradictory evidence');return [],None
        with patch('konu_sentezi.retrieve',side_effect=knowledge),patch('jev_retrieval.catalog',side_effect=catalog):
            result=g.build_task_package(self.v,'hello')
        self.assertNotIn('Old claim',result['text']);self.assertIsNone(result['knowledge'])
        self.assertIn('source_changed_during_package',result['omitted_reasons'])

    def test_two_readers_cannot_overwrite_conflicting_source_versions(self):
        (self.v/'bilgi').mkdir();source=self.v/'source.md';source.write_text('new')
        knowledge=dict(text='Old claim',records=[],source_versions={'source.md':'old-hash'})
        procedure=dict(text='Read source.md',paths=['source.md'],source_versions={'source.md':g.digest(source)})
        with patch('konu_sentezi.retrieve',return_value=knowledge),patch('jev_procedures.route',return_value=procedure):
            result=g.build_task_package(self.v,'hello')
        self.assertNotIn('Old claim',result['text']);self.assertEqual(result['selected_ids'],[])
        self.assertIn('source_changed_during_package',result['omitted_reasons'])

    def test_package_identity_excludes_model_timing(self):
        with patch('jev_procedures.route',side_effect=[
            dict(text='',paths=[],source_versions={},jev={'latency_ms':1}),
            dict(text='',paths=[],source_versions={},jev={'latency_ms':2})]):
            self.assertEqual(g.build_task_package(self.v,'hello')['package_id'],
                             g.build_task_package(self.v,'hello')['package_id'])


class ReviewConcurrency(unittest.TestCase):
    def test_terminal_candidate_cannot_be_promoted_or_reviewed_twice(self):
        import hafiza as h
        import konsolidasyon as k
        with tempfile.TemporaryDirectory() as tmp:
            v=Path(tmp);(v/'source.md').write_text('User prefers concise responses.')
            candidate=h.add_candidate(v,statement='User prefers concise responses.',kind='semantic',
                scope='user',subject_key='style',source_path='source.md',source_anchor='test',
                confidence='explicit-user',sensitivity='normal',proposed_by='test')
            decision=dict(candidate_id=candidate['candidate_id'],decision='reject',
                          reviewed_by=k.ACTOR,reason='This evidence is not sufficient for a stable preference.')
            def review():
                try:return k.review(v,decision,apply=True)['result']
                except ValueError:return 'already_closed'
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:review(),range(2)))
            self.assertCountEqual(results,['reject','already_closed'])
            with self.assertRaises(ValueError):
                h.promote_candidate(v,candidate['candidate_id'],memory_id='bad',reviewed_by='human',apply=True)
            self.assertEqual(h.load_catalog(v),[])

    def test_non_private_prompt_does_not_take_writer_lock(self):
        import capture_source as c
        with patch.object(c,'_apply_prompt_policy') as writer:
            self.assertFalse(c.apply_prompt_policy(Path('/unused'),'s','Build a page'))
            writer.assert_not_called()

if __name__=='__main__':unittest.main()
