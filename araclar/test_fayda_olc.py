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
