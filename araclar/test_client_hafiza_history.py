"""Synthetic genuine user turn selection for native client hooks."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import client_hafiza
import gorev_baglam
import jev_client


class HistoryTests(unittest.TestCase):
    def test_previous_genuine_user_turn_only(self):
        source = {'entries': [dict(role='user', quote='Earlier task'),
                              dict(role='assistant', quote='response'),
                              dict(role='user', quote='Current task')]}
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        source['entries'].pop()
        self.assertEqual(client_hafiza.previous_user(source, 'Current task'), 'Earlier task')
        with patch.object(gorev_baglam, 'build_task_package', return_value={}) as build:
            client_hafiza.local_task_package('/tmp/example', 'Current task', previous_user='Earlier task')
        self.assertEqual(build.call_args.kwargs['previous_user'], 'Earlier task')

    def test_private_previous_turn_is_excluded(self):
        source = {'entries': [dict(role='user', quote='Do not save this private request'),
                              dict(role='user', quote='Current task')]}
        self.assertIsNone(client_hafiza.previous_user(source, 'Current task'))

    def test_claude_shadow_logs_hash_without_prompt_and_keeps_local_text(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory)
            local={'text':'local context','selected_ids':['local']}
            shadow={'text':'remote context','selected_ids':['memory:m1'],
                    'jev':{'gate':{'scores':{},'diagnostics':[]},
                           'catalog':{'scores':{'memory:m1':1.8},'diagnostics':[]}}}
            with (patch.object(jev_client,'load_config',return_value=dict(jev_client.DEFAULTS,claude_hook_mode='shadow')),
                  patch.object(client_hafiza,'local_task_package',return_value=local),
                  patch.object(gorev_baglam,'build_task_package',return_value=shadow) as build):
                result=client_hafiza.claude_task_package(vault,'Synthetic writing request',previous_user='Earlier synthetic task')
            self.assertIs(result,local)
            build.assert_called_once()
            lines=list((vault/'.cache/jev-golge').glob('*.jsonl'))
            self.assertEqual(len(lines),1)
            raw=lines[0].read_text()
            self.assertNotIn('Synthetic writing request',raw)
            self.assertNotIn('Earlier synthetic task',raw)
            self.assertEqual(json.loads(raw)['selected_ids'],['memory:m1'])


if __name__ == '__main__':
    unittest.main()
