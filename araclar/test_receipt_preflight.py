"""Real capture evidence in temporary vaults; no external services or user data."""
import json
import tempfile
import unittest
from pathlib import Path

import capture_source as capture
import codex_hafiza as receipts
import hafiza as memory


class ReceiptPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = self.root / 'codex/sessions/example.jsonl'
        source.parent.mkdir(parents=True)
        self.quote = 'Example reports use numbered section headings.'
        rows = [dict(type='session_meta', payload=dict(id='s', source='vscode'))]
        rows += [dict(type='response_item', timestamp=str(i), payload=dict(
            type='message', role='user', content=[dict(text=self.quote if i == 5 else
                                                     'Synthetic request number ' + str(i))]))
                 for i in range(6)]
        rows.append(dict(type='event_msg', payload=dict(type='task_complete', turn_id='t6')))
        source.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
        self.snapshot = capture.snapshot(source, completed_prefix=True)
        self.candidate = dict(statement=self.quote, subject_key='example.report.headings',
                              evidence=self.quote, evidence_source=dict(
                                  self.snapshot, line=7, message_hash=capture.digest(self.quote),
                                  quote=self.quote))

    def record(self, vault, candidates):
        return receipts.record(vault, 's', 'recovery-v2-' + self.snapshot['source_hash'],
                               self.quote, candidates, self.snapshot)

    def assert_no_receipt_or_candidates(self, vault):
        self.assertFalse((vault / receipts.INBOX).exists())
        self.assertFalse((vault / memory.CANDIDATE_PATH).exists())
        self.assertFalse((vault / memory.EVENT_PATH).exists())

    def test_empty_subject_is_rejected_before_receipt_and_index(self):
        for index, value in enumerate(('', '   ', '\t\n')):
            with self.subTest(value=repr(value)):
                vault = self.root / ('blank-subject-' + str(index))
                with self.assertRaises(ValueError):
                    self.record(vault, [dict(self.candidate, subject_key=value)])
                self.assert_no_receipt_or_candidates(vault)

    def test_whitespace_statement_is_rejected_before_receipt(self):
        vault = self.root / 'blank-statement'
        with self.assertRaises(ValueError):
            self.record(vault, [dict(self.candidate, statement=' ' * 20)])
        self.assert_no_receipt_or_candidates(vault)

    def test_later_invalid_candidate_does_not_partially_queue_earlier_one(self):
        vault = self.root / 'mixed-batch'
        with self.assertRaises(ValueError):
            self.record(vault, [self.candidate, dict(self.candidate, subject_key=' ')])
        self.assert_no_receipt_or_candidates(vault)

    def test_valid_candidate_keeps_evidence_and_existing_receipt_contract(self):
        vault = self.root / 'valid-batch'
        result = self.record(vault, [self.candidate])
        self.assertTrue(Path(result['saved']).is_file())
        rows = memory.load_jsonl(vault / memory.CANDIDATE_PATH)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['subject_key'], self.candidate['subject_key'])
        self.assertEqual(rows[0]['evidence_source'], self.candidate['evidence_source'])
        self.assertEqual(rows[0]['status'], 'pending')
