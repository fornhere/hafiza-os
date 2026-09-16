import unittest
from fayda_olc import summarize
class Benefit(unittest.TestCase):
    def row(self,ident,**changes):
        data=dict(task_id=ident,condition='B',workflow='thumbnail',model='fixed',protocol_version='1',
                  outcome='accepted',evidence_source='receipt:one',correction_rounds=2);data.update(changes);return data
    def test_missing_data_and_abandoned_tasks_are_not_hidden(self):
        result=summarize([self.row('one'),self.row('two',outcome='abandoned',correction_rounds=None)])
        group=result['groups'][0]
        self.assertEqual(2,group['tasks']);self.assertEqual(1,group['outcomes']['abandoned'])
        self.assertEqual(1,group['measurements']['correction_rounds']['missing'])
        self.assertIsNone(group['measurements']['elapsed_seconds']['median'])
    def test_models_and_protocols_not_pooled(self):
        self.assertEqual(2,len(summarize([self.row('one'),self.row('two',model='other')])['groups']))
    def test_duplicates_rejected_and_empty_has_no_claim(self):
        with self.assertRaises(ValueError):summarize([self.row('same'),self.row('same')])
        self.assertEqual('no_observations',summarize([])['status'])
    def test_nonfinite_measurements_rejected(self):
        for value in (float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError): summarize([self.row('one',elapsed_seconds=value)])

class PassiveObservation(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.v=Path(self.temp.name);self.path=self.v/'source.jsonl'
        self.events=[dict(type='session_meta',payload=dict(id='session',source='vscode'))]
        self.events += [dict(type='response_item',timestamp=str(i),payload=dict(type='message',role='user',content=[dict(text='İstek '+str(i))])) for i in range(5)]
        self.events += [dict(type='response_item',timestamp='six',payload=dict(type='message',role='user',content=[dict(text='Tamam, bu kapağı kabul ettim.')]))]
        self.events += [dict(type='event_msg',payload=dict(type='task_complete',turn_id='six'))]
        self.save()
    def save(self):
        import json
        self.path.write_text('\n'.join(map(json.dumps,self.events)))
    def data(self,**changes):
        import capture_source as c
        source=c.snapshot(self.path,completed_prefix=True)
        quote=self.events[6]['payload']['content'][0]['text']
        data=dict(task_id='cover',condition='observational',workflow='thumbnail',model='fixed',protocol_version='natural-1',outcome='accepted',session_id='session',source_snapshot=source,evidence=quote,evidence_source=dict(source,line=7,message_hash=c.digest(quote),quote=quote),reviewed_by='codex-consolidator')
        data.update(changes);return data
    def test_dry_run_retry_and_versioned_update(self):
        from fayda_olc import record,OBSERVATIONS,summarize
        import hafiza as h
        first=record(self.v,self.data())
        self.assertEqual('dry_run',first['status']);self.assertFalse((self.v/OBSERVATIONS).exists())
        first=record(self.v,self.data(),True)
        self.assertEqual(1,first['observation']['version'])
        self.assertEqual('unchanged',record(self.v,self.data(),True)['status'])
        self.events += [dict(type='response_item',timestamp='seven',payload=dict(type='message',role='user',content=[dict(text='Vazgeçtim, bu kapağı kullanmayalım.')])) ,dict(type='event_msg',payload=dict(type='task_complete',turn_id='seven'))]
        self.save()
        import capture_source as c
        quote=self.events[8]['payload']['content'][0]['text'];new=self.data(outcome='rejected')
        new['evidence']=quote;new['evidence_source'].update(line=9,message_hash=c.digest(quote),quote=quote)
        with self.assertRaises(ValueError):record(self.v,new,True)
        new['expected_version']=1
        second=record(self.v,new,True)
        self.assertEqual(2,second['observation']['version'])
        rows=h.load_jsonl(self.v/OBSERVATIONS);self.assertEqual(2,len(rows))
        self.assertEqual({'accepted':0,'rejected':1,'abandoned':0,'unknown':0},summarize(rows)['observational_groups'][0]['outcomes'])
        self.assertIsNone(rows[-1]['elapsed_seconds'])
    def test_metrics_and_roles_and_experiment_labels_rejected(self):
        from fayda_olc import record,METRICS
        for field in METRICS:
            with self.subTest(field=field), self.assertRaises(ValueError):record(self.v,self.data(**{field:0}),True)
        for changes in ({'reviewed_by':'main-agent'},{'condition':'B'},{'expected_version':True}):
            with self.assertRaises(ValueError):record(self.v,self.data(**changes),True)
    def test_forged_quote_and_assistant_quote_rejected(self):
        from fayda_olc import record
        data=self.data();data['evidence']='Bu hiç söylenmedi';data['evidence_source']['quote']=data['evidence']
        with self.assertRaises(ValueError):record(self.v,data,True)
        self.events[6]['payload']['role']='assistant'
        self.events.insert(7,dict(type='response_item',timestamp='extra',payload=dict(type='message',role='user',content=[dict(text='Başka bir gerçek istek')])));self.save()
        with self.assertRaisesRegex(ValueError,'özgün kullanıcı mesajı'):record(self.v,self.data(),True)
    def test_privacy_suffix_and_first_five_rejected(self):
        from fayda_olc import record
        data=self.data()
        self.events += [dict(type='response_item',timestamp='privacy',payload=dict(type='message',role='user',content=[dict(text='Bunu hafızaya alma lütfen.')]))]
        self.save()
        with self.assertRaises(ValueError):record(self.v,data,True)
        self.events=self.events[:8];self.events.pop(1);self.save()
        import capture_source as c
        data['source_snapshot']=c.snapshot(self.path,completed_prefix=True)
        with self.assertRaisesRegex(ValueError,'ilk beş'):record(self.v,data,True)
    def test_malformed_and_changed_source_rejected(self):
        from fayda_olc import record
        data=self.data();self.path.write_text(self.path.read_text().replace('İstek','Değişmiş'))
        # json defaults escape Turkish: alter an ASCII field in the bounded prefix.
        self.path.write_text(self.path.read_text().replace('"six"','"changed"'))
        with self.assertRaises(ValueError):record(self.v,data,True)
        self.path.write_text('{broken\n'+self.path.read_text())
        with self.assertRaises(ValueError):record(self.v,data,True)
    def test_natural_and_experiment_never_pool(self):
        from fayda_olc import record,summarize
        natural=record(self.v,self.data())['observation']
        experiment=Benefit().row('cover')
        result=summarize([natural,experiment])
        self.assertEqual(1,len(result['observational_groups']))
        self.assertEqual(1,len(result['experiment_groups']))
        self.assertEqual(1,result['observational_groups'][0]['tasks'])
