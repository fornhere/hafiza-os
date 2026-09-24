"""Synthetic gate and mixed ranking checks; no personal source data."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bilgi_agi
import gorev_baglam
import hafiza
import jev_client
import jev_retrieval


class RerankTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        (self.vault / 'komuta').mkdir()
        self.config()

    def config(self, **changes):
        values = dict(mode='on', retrieval_mode='rerank', procedure_mode='off')
        values.update(changes)
        (self.vault / 'komuta/jev.json').write_text(json.dumps(values))

    def test_gate_no_preserves_non_memory_package(self):
        answer = dict(choices={'need':'no_memory'}, distributions={'need':{'search_memory':.01,'no_memory':.98,'insufficient_context':.01}}, degraded=False, diagnostics=[])
        minimal = dict(text='project and procedure', selected_ids=['project','procedure-reading'], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate', return_value=answer) as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=minimal) as build:
            result = gorev_baglam.build_task_package(self.vault, 'Explain addition')
        self.assertEqual(result['text'], 'project and procedure')
        self.assertTrue(build.call_args.args[-1])
        self.assertEqual(evaluate.call_args.kwargs['purpose'], 'retrieval_gate')

    def test_gate_yes_passes_previous_turn_and_error_uses_local(self):
        minimal = dict(text='', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate', return_value=dict(choices={'need':'search_memory'}, distributions={'need':{'search_memory':.9,'no_memory':.05,'insufficient_context':.05}}, degraded=False)) as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=dict(minimal)) as build:
            gorev_baglam.build_task_package(self.vault, 'Use my preference', previous_user='Earlier task', cwd='/work')
        self.assertEqual(evaluate.call_args.kwargs['state']['previous_user'], 'Earlier task')
        self.assertEqual(build.call_args.args[-2]['previous_user'], 'Earlier task')
        self.assertNotIn('cwd', build.call_args.args[-2])
        def local_build(*args):
            self.assertEqual(jev_client.load_config(self.vault)['mode'], 'off')
            return dict(minimal)
        with patch.object(jev_client, 'evaluate', return_value=dict(scores={}, degraded=True, diagnostics=['deadline_exceeded'])), \
             patch.object(gorev_baglam, '_build_task_package', side_effect=local_build) as build:
            result = gorev_baglam.build_task_package(self.vault, 'Use my preference')
            self.assertEqual(jev_client.load_config(self.vault)['mode'], 'on')
        self.assertIsNone(build.call_args.args[-1])
        self.assertTrue(result['jev']['rerank']['degraded'])

    def test_private_prompt_never_reaches_jev(self):
        minimal = dict(text='', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client, 'evaluate') as evaluate, \
             patch.object(gorev_baglam, '_build_task_package', return_value=minimal):
            result = gorev_baglam.build_task_package(self.vault, 'Do not save this private request')
        evaluate.assert_not_called()
        self.assertTrue(result['jev']['rerank']['degraded'])

    def test_explicit_recall_skips_gate_but_builds_memory(self):
        minimal = dict(text='stored decision', selected_ids=[], source_versions={}, assets=[],
                       omitted_reasons=[], history={}, procedure_reading={}, usage={})
        with patch.object(jev_client,'evaluate') as evaluate, \
             patch.object(gorev_baglam,'_build_task_package',return_value=minimal) as build:
            result=gorev_baglam.build_task_package(self.vault,'Neye karar vermiştik?')
        evaluate.assert_not_called()
        self.assertFalse(build.call_args.args[-1])
        self.assertIn('explicit_recall_bypass',result['jev']['gate']['diagnostics'])

    def test_rerank_selects_at_most_configured_limit(self):
        self.config(rerank_limit=2)
        rows = [dict(memory_id=f'm{i}', subject_key='style', statement=f'Writing style {i}',
                     scope='user', source_path=f'm{i}.md') for i in range(5)]
        def answer(vault, query, cards, **kwargs):
            return dict(scores={card['id']: 2 for card in cards}, distributions={card['id']:{'0':0,'1':0,'2':1} for card in cards}, degraded=False, diagnostics=[])
        with patch.object(bilgi_agi, '_rows', return_value=([], [])), \
             patch.object(hafiza, 'load_catalog', return_value=rows), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(jev_client, 'evaluate', side_effect=answer):
            selected, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Writing style', rows, None, {}, 2000)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(result['proposed_ids']), 2)
        self.assertEqual(knowledge['records'], [])

    def test_input_budget_reduces_candidates_before_call(self):
        self.config(max_input_chars=1200)
        rows = [dict(memory_id=f'm{i}', subject_key='style', statement='Writing style ' + 'x'*180,
                     conditions='Only for this writing style', scope='user', source_path=f'm{i}.md')
                for i in range(8)]
        counts = []
        def answer(vault, query, cards, **kwargs):
            counts.append(len(cards))
            self.assertEqual(cards[0]['scope'], 'user')
            self.assertEqual(cards[0]['conditions'], 'Only for this writing style')
            return dict(scores={card['id']: 0 for card in cards}, degraded=False, diagnostics=[])
        with patch.object(bilgi_agi, '_rows', return_value=([], [])), \
             patch.object(hafiza, 'load_catalog', return_value=rows), \
             patch.object(jev_client, 'evaluate', side_effect=answer):
            jev_retrieval.rerank(self.vault, 'Writing style', rows, None, {}, 2000)
        self.assertEqual(len(counts), 1)
        self.assertLess(counts[0], 8)
        self.assertGreater(counts[0], 0)

    def test_notes_and_catalog_share_the_same_limit(self):
        self.config(rerank_limit=2)
        (self.vault / 'bilgi').mkdir()
        memory = dict(memory_id='m1', subject_key='writing', statement='Writing style preference',
                      scope='user', source_path='m1.md')
        note = dict(id='n1', title='Writing guidance', statement='Writing style note',
                    scope='user', domains=['writing'], kind='preference',
                    conditions='Only for drafts', rationale='Reviewed example', exceptions='None', sources=[])
        def answer(vault, query, cards, **kwargs):
            self.assertEqual(next(c for c in cards if c['id'] == 'note:n1')['conditions'], 'Only for drafts')
            return dict(scores={card['id']: 2 for card in cards}, distributions={card['id']:{'0':0,'1':0,'2':1} for card in cards}, degraded=False, diagnostics=[])
        with patch.object(bilgi_agi, '_rows', return_value=([note], [])), \
             patch.object(bilgi_agi, 'note_version', return_value='note-sha'), \
             patch.object(hafiza, 'load_catalog', return_value=[memory]), \
             patch.object(hafiza, 'context_record_errors', return_value=[]), \
             patch.object(jev_client, 'evaluate', side_effect=answer):
            catalog, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Writing style', [memory], None, {}, 2000)
        self.assertEqual(len(catalog) + len(knowledge['records']), 2)
        self.assertEqual(knowledge['records'][0]['id'], 'n1')
        self.assertEqual(len(result['proposed_ids']), 2)

    def test_no_eligible_candidates_stays_empty_without_rank_call(self):
        with patch.object(jev_client, 'evaluate') as evaluate:
            catalog, knowledge, result = jev_retrieval.rerank(
                self.vault, 'Recall a missing preference', [], None, {}, 2000)
        evaluate.assert_not_called()
        self.assertEqual(catalog, [])
        self.assertEqual(knowledge['text'], '')
        self.assertFalse(result['degraded'])

    def test_p2_threshold_excludes_high_expected_score(self):
        self.config(rerank_p2=.75)
        row=dict(memory_id='m1',subject_key='style',statement='Writing style',scope='user',source_path='m1.md')
        def answer(*args,**kwargs):
            return dict(scores={'memory:m1':1.6},distributions={'memory:m1':{'0':0,'1':.4,'2':.6}},degraded=False,diagnostics=[])
        with patch.object(bilgi_agi,'_rows',return_value=([],[])), \
             patch.object(hafiza,'load_catalog',return_value=[row]), \
             patch.object(hafiza,'context_record_errors',return_value=[]), \
             patch.object(jev_client,'evaluate',side_effect=answer):
            selected,_,_=jev_retrieval.rerank(self.vault,'Writing style',[row],None,{},2000)
        self.assertEqual(selected,[])


if __name__ == '__main__':
    unittest.main()
