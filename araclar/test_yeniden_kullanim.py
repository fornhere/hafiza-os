import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import yeniden_kullanim as reuse


class ReuseTests(unittest.TestCase):
    def output(self, id='one', label='Türkçe erişim ölçümü', **changes):
        value=dict(id=id, label=label, path='çıktılar/'+id+'.md', sha256='a'*64,
                   verified_at='2026-09-18T00:00:00Z', reviewer='fixture-reviewer',
                   task_id='task-'+id, project_id='second-brain', uses=['erişim deneyi'])
        value.update(changes)
        return value

    def run_propose(self, rows, need='erişim ölçümü', **kwargs):
        with patch.object(reuse, 'verified_outputs', return_value=dict(outputs=rows,diagnostics=[])) as read:
            result=reuse.propose(Path('/fixture'), 'second-brain', need, **kwargs)
        read.assert_called_once_with(Path('/fixture'), 'second-brain')
        return result

    def test_transparent_rank_and_complete_source_provenance(self):
        low=self.output('low',label='Erişim raporu')
        high=self.output('high')
        result=self.run_propose([low,high])
        self.assertEqual('proposed',result['status'])
        self.assertEqual(['high','low'],[c['source']['id'] for c in result['candidates']])
        best=result['candidates'][0]
        self.assertEqual(high,best['source'])
        self.assertEqual(['erişim','ölçümü'],best['matched_terms'])
        self.assertIn('erişim, ölçümü',best['reason'])
        self.assertIn('yeniden doğrula',best['required_work'])
        self.assertNotIn('savings',best)
        self.assertNotIn('accepted_by',best)

    def test_no_outputs_no_match_and_wrong_project_remain_empty(self):
        for rows in ([], [self.output(label='Başka konu',uses=[])],
                     [self.output(project_id='unrelated')]):
            self.assertEqual([],self.run_propose(rows)['candidates'])

    def test_turkish_capital_i_and_stopwords(self):
        result=self.run_propose([self.output(label='İÇERİK',uses=[])],need='İçerik için bir')
        self.assertEqual(['içerik'],result['candidates'][0]['matched_terms'])
        self.assertEqual([],self.run_propose([self.output(label='Bir için',uses=[])])['candidates'])

    def test_budget_keeps_whole_records_and_default_limit(self):
        rows=[self.output(str(i)) for i in range(4)]
        full=self.run_propose(rows)
        self.assertEqual(2,len(full['candidates']))
        one=self.run_propose(rows,limit=1)
        exact=self.run_propose(rows,max_chars=len(one['text']))
        self.assertEqual(one['text'],exact['text'])
        self.assertEqual(1,len(exact['candidates']))
        empty=self.run_propose(rows,max_chars=10)
        self.assertEqual([],empty['candidates'])
        self.assertEqual('',empty['text'])
        self.assertIn('reuse_candidates_exceed_text_budget',empty['diagnostics'])

    def test_blank_need_and_invalid_limits(self):
        with patch.object(reuse,'verified_outputs') as read:
            self.assertEqual([],reuse.propose('/fixture','second-brain','')['candidates'])
            read.assert_not_called()
        for kwargs in ({'limit':-1},{'max_chars':-1}):
            with self.assertRaises(ValueError):
                reuse.propose('/fixture','second-brain','need',**kwargs)

    def test_cli_and_registry_diagnostics(self):
        with patch.object(reuse,'verified_outputs',return_value=dict(outputs=[],diagnostics=['source_changed'])):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(0,reuse.main(['--vault','/fixture','--project','second-brain','--need','erişim']))
        result=json.loads(output.getvalue())
        self.assertEqual([],result['candidates'])
        self.assertEqual(['source_changed'],result['diagnostics'])
