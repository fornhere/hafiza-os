"""Synthetic collection and scoring; no private transcripts or catalog data."""
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import erisim_olc as measure


class AccessMeasure(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.claude = self.root / 'claude' / 'project'
        self.claude.mkdir(parents=True)
        self.codex = self.root / 'codex' / '2026' / '09'
        self.codex.mkdir(parents=True)
        self.now = datetime(2026, 9, 24, tzinfo=timezone.utc)

    def write_rows(self, path, rows):
        path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')

    def test_collect_balances_genuine_prompts_and_filters_private_worker(self):
        session = 'session1'
        def user(i, text):
            return dict(type='user', uuid=f'u{i}', sessionId=session, isSidechain=False,
                        timestamp='2026-09-23T12:00:00Z', cwd='/work',
                        message=dict(role='user', content=text))
        rows = [user(1, 'Please summarize the project history.'),
                user(2, '<task-notification>Background job finished.</task-notification>'),
                user(3, 'İŞÇİ KOŞUSU — otomatik işçi için test metni.'),
                user(4, 'Please summarize the project history.')]
        self.write_rows(self.claude / f'{session}.jsonl', rows)
        codex_rows = [dict(type='session_meta', payload=dict(id='codex1', source='vscode', cwd='/code')),
                      dict(type='response_item', timestamp='2026-09-23T13:00:00Z',
                           payload=dict(type='message', role='user', content=[dict(type='input_text', text='Help me update the deployment script.')]))]
        self.write_rows(self.codex / 'codex1.jsonl', codex_rows)
        out = self.root / 'set.jsonl'
        got = measure.collect(claude_root=self.claude.parent, codex_root=self.codex.parent.parent,
                              out=out, now=self.now)
        self.assertEqual([x['client'] for x in got], ['claude', 'codex'])
        self.assertEqual([x['cwd'] for x in got], ['/work', '/code'])
        self.assertEqual(len(measure._jsonl(out)), 2)

    def test_evaluate_scores_only_delivered_records_and_empty_gold(self):
        (self.vault / 'zihin').mkdir()
        (self.vault / 'bilgi').mkdir()
        self.write_rows(self.vault / 'zihin/hafıza-kataloğu.jsonl',
                        [dict(memory_id='m1', status='active'), dict(memory_id='old', status='superseded')])
        (self.vault / 'bilgi/n1.md').write_text('synthetic')
        prompts = [dict(id='a', client='claude', cwd='/tmp/project', prompt='Plan the next release.'),
                   dict(id='b', client='codex', cwd='', prompt='Explain a generic formula.')]
        labels = [dict(id='a', relevant_memory_ids=['m1'], relevant_notes=['n1']),
                  dict(id='b', relevant_memory_ids=[], relevant_notes=[])]
        self.write_rows(self.root / 'set.jsonl', prompts)
        self.write_rows(self.root / 'labels.jsonl', labels)
        packages = [dict(selected_ids=['m1', 'old'], knowledge=dict(records=[]), text='context'),
                    dict(selected_ids=[], knowledge=None, text='workflow note')]
        with patch.object(measure.gorev_baglam, 'build_task_package', side_effect=packages) as build:
            report = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl', self.root)
        self.assertEqual(build.call_count, 2)
        self.assertEqual(build.call_args.kwargs['budget'], 2000)
        self.assertEqual((report['metrics']['tp'], report['metrics']['fp'], report['metrics']['fn']), (1, 0, 1))
        self.assertEqual(report['metrics']['certain_only']['recall'], 0.5)
        self.assertEqual(report['metrics']['empty_return_rate'], 0)
        self.assertEqual(report['metrics']['empty_memory_return_rate'], 1)
        self.assertTrue((self.root / 'erisim-degerlendirme-2026-09-24.md').exists())

    def test_seeded_halves_are_disjoint(self):
        (self.vault / 'zihin').mkdir()
        (self.vault / 'bilgi').mkdir()
        (self.vault / 'zihin/hafıza-kataloğu.jsonl').write_text('')
        prompts = [dict(id=str(i), client='codex', cwd='', prompt='A synthetic task') for i in range(6)]
        labels = [dict(id=str(i), relevant_memory_ids=[], relevant_notes=[]) for i in range(6)]
        self.write_rows(self.root / 'set.jsonl', prompts)
        self.write_rows(self.root / 'labels.jsonl', labels)
        package = dict(selected_ids=[], knowledge=None, text='')
        with patch.object(measure.gorev_baglam, 'build_task_package', return_value=package):
            first = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                     self.root, split_seed=7, split_half='first', write=False)
            second = measure.evaluate(self.vault, self.root / 'set.jsonl', self.root / 'labels.jsonl',
                                      self.root, split_seed=7, split_half='second', write=False)
        self.assertEqual({r['id'] for r in first['results']} & {r['id'] for r in second['results']}, set())
        self.assertEqual(len(first['results']) + len(second['results']), 6)

    def test_short_collection_and_prefixed_v2_labels(self):
        self.assertFalse(measure._valid('Devam'))
        self.assertTrue(measure._valid('Devam', include_short=True))
        (self.vault/'zihin').mkdir(); (self.vault/'bilgi').mkdir()
        self.write_rows(self.vault/'zihin/hafıza-kataloğu.jsonl',[dict(memory_id='m1',status='active')])
        (self.vault/'bilgi/n1.md').write_text('synthetic')
        self.write_rows(self.root/'set.jsonl',[dict(id='a',client='claude',cwd='',prompt='Devam',previous_user='Synthetic planning request')])
        self.write_rows(self.root/'labels.jsonl',[dict(id='a',relevant_memory_ids=['memory:m1'],relevant_notes=['note:n1'])])
        package=dict(text='memory\nnote\nprocedure\nproject',selected_ids=['m1','knowledge','procedure-reading','p1'],project_id='p1',
                     summary={'task_ids':[]},knowledge={'records':[{'id':'n1'}]},
                     delivered_segments={'m1':'memory','knowledge':'note','procedure-reading':'procedure','p1':'project'})
        with patch.object(measure.gorev_baglam,'build_task_package',return_value=package) as build:
            report=measure.evaluate(self.vault,self.root/'set.jsonl',self.root/'labels.jsonl',self.root,write=False)
        self.assertEqual(build.call_args.kwargs['previous_user'],'Synthetic planning request')
        self.assertEqual(report['metrics']['tp'],2)
        self.assertEqual(report['metrics']['requested_mode_counts'],{'local':1})
        self.assertEqual(report['metrics']['effective_mode_counts'],{'local':1})
        self.assertEqual(report['metrics']['channel_chars'],{'catalog':6,'note':4,'procedure':9,'project':7,'other':0})


if __name__ == '__main__':
    unittest.main()
