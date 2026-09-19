import json
import os
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch
import hafiza as h
import bilgi_agi as b
import jev_client
from jev_answer import verify

class Answer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.v=Path(self.tmp.name)
        (self.v/'komuta').mkdir();(self.v/'komuta/jev.json').write_text('{"mode":"off"}')
        self.quote='Sunum için kısa cümle kullan.';(self.v/'s.md').write_text(self.quote)
        self.source=dict(path='s.md',sha256=b.digest(self.v/'s.md'),evidence=self.quote)
        b.register(self.v,dict(id='c',title='Sunum',kind='decision',statement=self.quote,scope='project:p',domains=['sunum'],status='reviewed',reviewed_by='reviewer',review_note='Kaynak incelendi.',sources=[self.source]),True)
        self.claim=dict(text=self.quote,citations=[dict(card_id='c',path='s.md',sha256=self.source['sha256'],quote=self.quote)])

    def test_scope_hash_quote_and_off(self):
        self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],'uncertain')
        self.assertEqual(verify(self.v,[self.claim],'q')['claims'][0]['verdict'],'insufficient')
        self.claim['citations'][0]['quote']='Invented evidence.'
        self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],'insufficient')

    def test_semantic_verdicts_service_failure_and_source_race(self):
        for scores,expected in [([2,0],'supported'),([0,2],'contradicted'),([0,0],'insufficient'),([2,2],'uncertain')]:
            with patch.object(jev_client,'evaluate',return_value=dict(mode='on',facet_scores={i:{'claim-0':v} for i,v in enumerate(scores)})):
                self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],expected)
        with patch.object(jev_client,'evaluate',return_value=dict(mode='on',degraded=True,diagnostics=['timeout'])):
            self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],'degraded')
        def race(*a,**kw):
            (self.v/'s.md').write_text(self.quote+' changed');return dict(mode='on',facet_scores={0:{'claim-0':2}})
        with patch.object(jev_client,'evaluate',side_effect=race):
            self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],'degraded')

    def test_revoked_card_during_snapshot_is_not_supported(self):
        original=b.digest
        path=self.v/'bilgi/c.md'
        fired=[]
        def race(file):
            if Path(file)==path and not fired:
                fired.append(True)
                row=b._read(path);row.update(status='rejected',expected_version=original(path))
                b.register(self.v,row,True)
            return original(file)
        with patch.object(b,'digest',side_effect=race), patch.object(jev_client,'evaluate',return_value=dict(mode='on',facet_scores={0:{'claim-0':2}})):
            self.assertEqual(verify(self.v,[self.claim],'p')['claims'][0]['verdict'],'degraded')

    def test_real_client_contract_with_transport_stub(self):
        (self.v/'komuta/jev.json').write_text('{"mode":"on"}')
        def transport(url,body,key,timeout):
            self.assertEqual(body['state']['candidates'][0]['scope'],'project:p')
            return dict(answers={q:dict(type='score',score=2 if q.startswith('f0_') else 0) for q in body['questions']})
        with patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-key'},clear=True), patch.object(jev_client,'_transport',side_effect=transport):
            result=verify(self.v,[self.claim],'p')
        self.assertEqual(result['claims'][0]['verdict'],'supported')

    def test_memory_id_windows_catalog_key_with_real_client(self):
        # Keep actual filesystem operations native while reproducing Windows str().
        class WindowsSpelling(PureWindowsPath):
            def __fspath__(self): return self.as_posix()
        candidate=h.add_candidate(self.v,statement=self.quote,kind='semantic',scope='project:p',subject_key='speech',source_path='s.md',source_anchor='speech',confidence='explicit-user',sensitivity='normal',proposed_by='author',evidence=self.quote)
        h.promote_candidate(self.v,candidate['candidate_id'],memory_id='speech',reviewed_by='reviewer',apply=True)
        claim=dict(text=self.quote,citations=[dict(memory_id='speech',path='s.md',sha256=self.source['sha256'],quote=self.quote)])
        (self.v/'komuta/jev.json').write_text('{"mode":"on"}')
        def transport(url,body,key,timeout):
            return dict(answers={q:dict(type='score',score=2 if q.startswith('f0_') else 0) for q in body['questions']})
        with patch.object(h,'CATALOG_PATH',WindowsSpelling(h.CATALOG_PATH.as_posix())), patch.dict(os.environ,{'TYPESAFE_API_KEY':'test-key'},clear=True), patch.object(jev_client,'_transport',side_effect=transport) as call:
            result=verify(self.v,[claim],'p')
        self.assertEqual(call.call_count,1)
        self.assertTrue(result['claims'][0]['mechanical_verified'])
        self.assertEqual(result['claims'][0]['verdict'],'supported')
