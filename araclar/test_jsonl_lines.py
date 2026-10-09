"""Fiziksel LF sınırları ve transcript kanıt sözleşmesi."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import capture_source as c
import client_transcripts as ct
import konsolidasyon as k
from jsonl_lines import split_jsonl


class Lines(unittest.TestCase):
    def test_physical_boundaries(self):
        for ending in ('\n', '\r\n'):
            for final in ('', ending):
                text = 'a\u2028b\u0085c\u2029d' + ending + 'e' + final
                self.assertEqual(split_jsonl(text), ['a\u2028b\u0085c\u2029d', 'e'])
                self.assertEqual(''.join(split_jsonl(text, keepends=True)), text)
        self.assertEqual(split_jsonl(''), [])
        self.assertEqual(split_jsonl('a\n\n'), ['a', ''])
        self.assertEqual(split_jsonl('a\rb'), ['a\rb'])


class CaptureLines(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name).resolve()
        self.path = self.vault / 'source.jsonl'
        self.quote = 'Başlık a\u2028b\u0085c\u2029d biçiminde olsun.'
        self.rows = [dict(type='session_meta', payload=dict(id='s', source='exec', thread_source='user'))]
        self.rows += [dict(type='response_item', timestamp=str(i), payload=dict(type='message', role='user',
            content=[dict(text=self.quote if i == 5 else 'Görev '+str(i))])) for i in range(6)]
        self.rows.append(dict(type='event_msg', payload=dict(type='task_complete', turn_id='t')))
        self.lines = [json.dumps(row, ensure_ascii=False) for row in self.rows]

    def test_prefix_hash_and_original_evidence(self):
        for ending in ('\n', '\r\n'):
            for final in ('', ending):
                with self.subTest(ending=ending, final=final):
                    self.path.write_bytes((ending.join(self.lines)+final).encode('utf-8'))
                    source = c.snapshot(self.path, completed_prefix=True)
                    self.assertEqual(source['parse_status'], 'ok')
                    self.assertEqual(source['suffix_parse_status'], 'ok')
                    self.assertEqual(source['prefix_end_line'], 8)
                    expected = '\n'.join(self.lines)
                    self.assertEqual(source['prefix_hash'], hashlib.sha256(expected.encode()).hexdigest())
                    self.assertEqual(c.read_completed_prefix(self.vault, 's', source), expected)
                    evidence = dict(source, line=7, message_hash=c.digest(self.quote), quote=self.quote)
                    self.assertEqual(c.validate_candidate_evidence(self.vault, 's', source, evidence, self.quote), evidence)
                    self.assertTrue(c.exclusion_evidence(self.path, self.quote))
                    with self.assertRaises(ValueError):
                        c.validate_candidate_evidence(self.vault, 's', source, dict(evidence, line=6), self.quote)
                    with self.assertRaises(ValueError): c.snapshot(self.path, end_line=7)
                    self.path.write_bytes((ending.join(self.lines)+ending+'{"partial":').encode())
                    self.assertEqual(c.validate_source(self.vault, 's', source)['suffix_parse_status'], 'malformed')
                    self.assertEqual(c.read_completed_prefix(self.vault, 's', source), expected)

    def test_real_malformed_line_is_rejected(self):
        for bad in ('{"broken":', '', '{"text":"a\rb"}'):
            self.path.write_bytes(('\n'.join(self.lines[:3]+[bad]+self.lines[3:])+'\n').encode())
            with self.assertRaisesRegex(ValueError, 'bozuk JSON'): c.snapshot(self.path, completed_prefix=True)
            self.assertEqual(c.snapshot(self.path)['parse_status'], 'malformed')

    def test_source_privacy_with_unicode_separator(self):
        self.rows[6]['payload']['content'][0]['text'] = 'a\u2028Bu oturumu kaydetme'
        self.path.write_bytes(('\n'.join(json.dumps(x, ensure_ascii=False) for x in self.rows)+'\n').encode())
        source = c.snapshot(self.path, completed_prefix=True)
        with self.assertRaisesRegex(ValueError, 'kaydetmeme'):
            c.validate_source(self.vault, 's', source)

    def test_ownership_fallback_uses_physical_lines(self):
        root = self.vault / 'client'; (root / 'sessions').mkdir(parents=True)
        path = root / 'sessions/source.jsonl'
        rows = [dict(type='noise', payload=dict(text='a\u2028b\u0085c\u2029d')),
                dict(type='session_meta', payload=dict(id='s', source='exec', thread_source='subagent'))]
        path.write_bytes(('\n'.join(json.dumps(x, ensure_ascii=False) for x in rows)+'\n').encode())
        import datetime as dt
        diagnostics = []
        with patch.object(k, 'heartbeat_threads', return_value=set()):
            self.assertEqual(k.sessions(self.vault, root, dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc), diagnostics=diagnostics), [])
        self.assertEqual(diagnostics, [])


class ClientLines(unittest.TestCase):
    def test_native_hashes_and_evidence_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for client in ('claude', 'antigravity'):
                path = root / 's.jsonl' if client == 'claude' else root / 'brain/s/.system_generated/logs/transcript.jsonl'
                path.parent.mkdir(parents=True, exist_ok=True)
                quote = 'Görev a\u2028b\u0085c\u2029d'
                if client == 'claude':
                    rows = [dict(type='user', uuid='u', sessionId='s', isSidechain=False,
                                 message=dict(role='user', content=quote)),
                            dict(type='assistant', uuid='a', sessionId='s', isSidechain=False,
                                 message=dict(role='assistant', model='fixture', content='Sonuç', stop_reason='end_turn'))]
                else:
                    rows = [dict(step_index=0, source='USER_EXPLICIT', type='USER_INPUT', status='DONE',
                                 content='<USER_REQUEST>'+quote+'</USER_REQUEST>'),
                            dict(step_index=1, source='MODEL', type='PLANNER_RESPONSE', status='DONE', content='Sonuç')]
                for ending in ('\n', '\r\n'):
                    physical = [(json.dumps(row, ensure_ascii=False)+ending).encode() for row in rows]
                    data = b''.join(physical); path.write_bytes(data)
                    parsed = ct.parse(client, 's', path)
                    self.assertEqual(parsed['total_lines'], 2)
                    self.assertTrue(parsed['terminal'])
                    self.assertEqual(parsed['prefix_sha256'], ct.sha(data))
                    self.assertEqual(parsed['entries'][0]['quote'], quote)
                    self.assertEqual(parsed['entries'][0]['line'], 1)
                    self.assertEqual(parsed['entries'][0]['line_sha256'], ct.sha(physical[0]))
                    prefix = ct.parse(client, 's', path, end_line=1)
                    self.assertEqual(prefix['prefix_sha256'], ct.sha(physical[0]))
                    self.assertFalse(prefix['terminal'])
                    path.write_bytes(physical[0]+b'{"broken":\n')
                    with self.assertRaises(ct.SourceError): ct.parse(client, 's', path)
                    path.write_bytes(physical[0].rstrip(b'\r\n')+b'\r'+physical[1])
                    with self.assertRaisesRegex(ct.SourceError, 'invalid_json'): ct.parse(client, 's', path)
                    path.write_bytes(data[:-1])
                    with self.assertRaisesRegex(ct.SourceError, 'truncated_source'): ct.parse(client, 's', path)
                    path.write_bytes(b'\xff\n')
                    with self.assertRaisesRegex(ct.SourceError, 'invalid_json'): ct.parse(client, 's', path)


if __name__ == '__main__': unittest.main()
