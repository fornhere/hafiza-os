import copy
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import gorev_plani as g
import jev_client


def fixture():
    return dict(scope='project:demo', resources=[
        dict(id='all', key='vault', description='All vault records'),
        dict(id='catalog', key='vault/catalog', description='Reviewed memory index'),
        dict(id='video', key='video', description='Video assets')], tasks=[
        dict(id='a', description='Read index', reads=['catalog'], writes=[], after=[], complete=True),
        dict(id='b', description='Read index again', reads=['catalog'], writes=[], after=[], complete=True),
        dict(id='c', description='Edit video', reads=[], writes=['video'], after=[], complete=True)])


class PlannerTests(unittest.TestCase):
    def test_read_read_parallel(self):
        self.assertEqual(g.plan(fixture())['waves'], [['a','b','c']])

    def test_write_read_and_independent(self):
        d=fixture(); d['tasks'][0]['writes']=['catalog']
        self.assertEqual(g.plan(d)['waves'], [['a','c'],['b']])

    def test_ancestor_write(self):
        d=fixture(); d['tasks'][0]['writes']=['all']
        self.assertEqual(g.plan(d)['waves'], [['a','c'],['b']])

    def test_write_write_alias(self):
        d=fixture(); d['resources'].append(dict(id='alias',key='vault/catalog',description='Same index'))
        d['tasks'][0]['writes']=['catalog']; d['tasks'][1]['writes']=['alias']
        self.assertEqual(len(g.plan(d)['conflicts']),1)

    def test_prefix_is_not_ancestor(self):
        self.assertFalse(g.overlap('vault/a','vault/abc'))

    def test_unknown_and_dependent_blocked(self):
        d=fixture(); d['tasks'][0]['complete']=False; d['tasks'][1]['after']=['a']
        p=g.plan(d)
        self.assertEqual(p['blocked'],['a','b']); self.assertEqual(p['waves'],[['c']])

    def test_dependency_order(self):
        d=fixture(); d['tasks'][0]['after']=['c']
        self.assertEqual(g.plan(d)['waves'],[['b','c'],['a']])

    def test_invalid_cycle_and_unknown(self):
        d=fixture(); d['tasks'][0]['after']=['b']; d['tasks'][1]['after']=['a']
        with self.assertRaisesRegex(ValueError,'cycle'): g.plan(d)
        d=fixture(); d['tasks'][0]['reads']=['missing']
        with self.assertRaisesRegex(ValueError,'reads_invalid'): g.plan(d)

    def test_digest_changes(self):
        a=fixture(); b=copy.deepcopy(a); b['tasks'][0]['writes']=['catalog']
        self.assertNotEqual(g.plan(a)['input_digest'],g.plan(b)['input_digest'])

    def test_advisor_cannot_fill_unknown_or_change_plan(self):
        d=fixture(); d['tasks'][0]['complete']=False; before=copy.deepcopy(d)
        with patch.object(jev_client,'evaluate',return_value={'facet_scores':{0:{'catalog':2}}}):
            a=g.advise(Path('.'),d)
        self.assertEqual(a['suggestions']['a'],['catalog'])
        self.assertEqual(d,before); self.assertIn('a',g.plan(d)['blocked'])
        self.assertFalse(a['execution_authorized'])

    def test_default_no_network(self):
        with tempfile.TemporaryDirectory() as v:
            result=g.advise(Path(v),fixture(),transport=lambda *a: self.fail('network'))
        self.assertEqual(result['jev']['mode'],'off')

    def test_mapping_config_shadow_only(self):
        self.assertEqual(jev_client.purpose_mode({'mode':'shadow','task_mapping_mode':'shadow'},'task_resource_mapping'),'shadow')
        self.assertEqual(jev_client.purpose_mode({'mode':'off','task_mapping_mode':'shadow'},'task_resource_mapping'),'off')

if __name__=='__main__': unittest.main()
