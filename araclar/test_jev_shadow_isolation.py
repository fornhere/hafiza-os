"""Synthetic shadow-policy regressions; no real clients, credentials or network."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from unittest.mock import patch

import client_hafiza as hook
import gorev_baglam as packages
import jev_client as client


class ShadowIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name)
        self.other = self.vault / 'other'
        for vault in (self.vault, self.other):
            (vault / 'komuta').mkdir(parents=True)
            (vault / 'komuta/jev.json').write_text(json.dumps(dict(
                mode='shadow', retrieval_mode='assist', procedure_mode='on',
                claude_hook_mode='shadow')), encoding='utf-8')

    def test_shadow_does_not_change_unrelated_thread_or_config_reader(self):
        entered = threading.Event()
        release = threading.Event()
        original = client.load_config
        seen = []

        def build(vault, *args, **kwargs):
            seen.append(client.load_config(vault)['retrieval_mode'])
            entered.set()
            if not release.wait(5):
                raise AssertionError('test synchronization timed out')
            return {'text': '', 'selected_ids': []}

        with (patch.object(hook, 'local_task_package', return_value={'text': 'local'}),
              patch.object(packages, 'build_task_package', side_effect=build)):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(hook.claude_task_package, self.vault, 'Synthetic task')
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertIs(client.load_config, original)
                    self.assertEqual(client.load_config(self.vault)['retrieval_mode'], 'assist')
                    self.assertEqual(client.load_config(self.other)['procedure_mode'], 'on')
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=5)['text'], 'local')
        self.assertEqual(seen, ['rerank'])
        self.assertIs(client.load_config, original)

    def test_two_shadow_calls_finish_without_recursive_patches(self):
        barrier = threading.Barrier(2)
        seen = []

        def build(vault, *args, **kwargs):
            barrier.wait(timeout=5)
            seen.append(client.load_config(vault)['retrieval_mode'])
            barrier.wait(timeout=5)
            return {'text': '', 'selected_ids': []}

        original = client.load_config
        with (patch.object(hook, 'local_task_package', return_value={'text': 'local'}),
              patch.object(packages, 'build_task_package', side_effect=build)):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(hook.claude_task_package, self.vault, 'Synthetic task')
                           for _ in range(2)]
                self.assertEqual([f.result(timeout=10)['text'] for f in futures], ['local', 'local'])
        self.assertEqual(seen, ['rerank', 'rerank'])
        self.assertIs(client.load_config, original)
        self.assertEqual(client.load_config(self.vault)['retrieval_mode'], 'assist')

    def test_profile_is_vault_scoped_and_copied_to_readers(self):
        with client.shadow_retrieval(self.vault):
            with client.evaluation_context(self.vault):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    config = pool.submit(copy_context().run, client.load_config, self.vault).result()
                self.assertEqual(config['retrieval_mode'], 'rerank')
                self.assertEqual(config['procedure_mode'], 'off')
                self.assertEqual(client.load_config(self.other)['retrieval_mode'], 'assist')
        self.assertEqual(client.load_config(self.vault)['retrieval_mode'], 'assist')

    def test_profile_preserves_global_off_and_disabled_policy(self):
        (self.vault / 'komuta/jev.json').write_text('{"mode":"off"}', encoding='utf-8')
        with client.shadow_retrieval(self.vault):
            self.assertEqual(client.load_config(self.vault)['mode'], 'off')
        with client.disabled(), client.shadow_retrieval(self.other):
            self.assertEqual(client.load_config(self.other)['mode'], 'off')

    def test_nested_profile_and_exception_restore_outer_policy(self):
        with client.shadow_retrieval(self.vault):
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                with client.shadow_retrieval(self.other):
                    self.assertEqual(client.load_config(self.other)['retrieval_mode'], 'rerank')
                    raise RuntimeError('synthetic')
            self.assertEqual(client.load_config(self.vault)['retrieval_mode'], 'rerank')
            self.assertEqual(client.load_config(self.other)['retrieval_mode'], 'assist')
        self.assertEqual(client.load_config(self.vault)['retrieval_mode'], 'assist')
