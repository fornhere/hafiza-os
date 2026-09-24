import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hafiza_rapor as report


NOW = dt.datetime(2026, 9, 24, 12, tzinfo=dt.timezone.utc)


class WeeklyReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name)

    def write_rows(self, name, items):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(item) + '\n' for item in items), encoding='utf-8')
        return path

    def write_file(self, name, content='fixture'):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
        os.utime(path, (NOW.timestamp(), NOW.timestamp()))
        return path

    def test_all_sections_use_real_field_names_and_window(self):
        recent = (NOW - dt.timedelta(days=1)).isoformat()
        old = (NOW - dt.timedelta(days=10)).isoformat()
        self.write_rows('günlük/hafıza-olayları.jsonl', [
            dict(event_type='session.inspected.v2', session_id='s1', outcome='recorded', at=recent),
            dict(event_type='session.inspected.v2', session_id='s1', outcome='excluded', at=recent),
            dict(event_type='session.inspected.v2', session_id='s2', outcome='no_relevant_change', at=recent),
            dict(event_type='session.inspected.v2', session_id='s3', outcome='recorded', at=old),
            dict(event_type='candidate.promoted', candidate_id='c1', memory_id='m1', at=recent),
            dict(event_type='candidate.rejected', candidate_id='c2', at=recent),
            dict(event_type='candidate.deferred', candidate_id='c4', at=(NOW - dt.timedelta(hours=2)).isoformat(),
                 review=dict(reason='Needs stronger fixture evidence.')),
        ])
        self.write_rows('gelen-kutusu/hafıza-adayları.jsonl', [
            dict(candidate_id='c1', created_at=recent, proposed_by='worker'),
            dict(candidate_id='c2', created_at=recent, proposed_by='worker'),
            dict(candidate_id='c3', created_at=old, proposed_by='reviewer'),
            dict(candidate_id='c4', created_at=old, proposed_by='reviewer'),
        ])
        self.write_rows('zihin/hafıza-kataloğu.jsonl', [
            dict(memory_id='m1', status='active', valid_from=recent),
            dict(memory_id='m2', status='superseded', valid_from=old, valid_to=recent),
            dict(memory_id='m3', status='quarantined', valid_from=old),
        ])
        self.write_rows('zihin/is-durumu.jsonl', [
            dict(id='t1', status='active', updated_at=old),
            dict(id='t1', status='done', updated_at=recent),
            dict(id='t2', status='needs_confirmation', updated_at=recent),
            dict(id='t3', status='cancelled', updated_at=old),
        ])
        self.write_file('gelen-kutusu/codex-oturumları/a.md')
        older = self.write_file('gelen-kutusu/codex-oturumları/older.md')
        os.utime(older, ((NOW - dt.timedelta(days=10)).timestamp(),) * 2)
        self.write_file('gelen-kutusu/ajan-oturumlari/b.md')
        state = 'gelen-kutusu/ajan-oturumlari/.state/'
        for number, status in enumerate(('pending', 'record', 'skip', 'superseded')):
            self.write_file(state + f'{number:064x}.json', json.dumps(dict(status=status)))
        self.write_file(state + 'context-one.json', '{}')
        codex = 'gelen-kutusu/codex-oturumları/.state/'
        self.write_file(codex + 'one.json', json.dumps(dict(count=2, context_usage=dict(emitted_chars=100))))
        self.write_file(codex + 'two.json', json.dumps(dict(count=1, context_usage=dict(emitted_chars=200))))
        with patch('konsolidasyon.status', return_value={'operational_health': {'status': 'healthy'}}):
            data = report.report(self.vault, now=NOW)
        self.assertEqual(data['capture']['outcomes'], dict(recorded=1, no_relevant_change=1, excluded=1))
        self.assertEqual(data['capture']['unique_sessions'], 2)
        self.assertEqual(data['capture']['new_codex_receipts'], 1)
        self.assertEqual(data['capture']['claude_queue'], dict(pending=1, record=1, skip=1, superseded=1))
        self.assertEqual(data['capture']['new_claude_source_notes'], 1)
        self.assertEqual(data['candidates']['added'], 2)
        self.assertEqual(data['candidates']['proposed_by'], {'worker': 2})
        self.assertEqual(data['candidates']['promoted'], 1)
        self.assertEqual(data['candidates']['pending'], 1)
        self.assertEqual(data['candidates']['blocked'], 1)
        self.assertEqual(data['candidates']['terminal'], 2)
        self.assertEqual(data['candidates']['oldest_pending_days'], 10)
        self.assertIn('engellenen: 1', report.markdown(data))
        self.assertEqual(data['catalog']['status'], dict(active=1, quarantined=1, superseded=1))
        self.assertEqual((data['catalog']['added'], data['catalog']['changed']), (1, 1))
        self.assertEqual(data['context']['per_turn_mean_chars'], 100)
        self.assertEqual(data['context']['per_turn_median_chars'], 125)
        self.assertEqual(data['context']['per_turn_max_chars'], 200)
        self.assertEqual(data['context']['claude_context_files'], 1)
        self.assertEqual(data['tasks']['status'], dict(active=0, needs_confirmation=1, done=1, cancelled=1))
        self.assertEqual(data['tasks']['closed_in_period'], 1)
        self.assertEqual(data['health']['status'], 'healthy')

    def test_missing_files_are_zero_or_unknown(self):
        data = report.report(self.vault, now=NOW)
        self.assertEqual(data['capture']['inspected'], 0)
        self.assertEqual(data['candidates']['pending'], 0)
        self.assertIsNone(data['candidates']['oldest_pending_days'])
        self.assertEqual(data['context']['per_turn_mean_chars'], 0)
        self.assertEqual(data['tasks']['closed_in_period'], 0)
        self.assertIn(data['health']['status'], ('unknown', 'failed'))
        self.assertEqual(list(self.vault.rglob('*')), [])

    def test_write_creates_only_report_and_prints_json(self):
        script = Path(report.__file__)
        result = subprocess.run([sys.executable, str(script), '--vault', str(self.vault), '--write'],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        rendered = (self.vault / 'komuta/hafıza-raporu.md').read_text(encoding='utf-8')
        self.assertIn(data['generated_at'], rendered)
        self.assertIn('[[Ana Sayfa]]', rendered)
        self.assertEqual([p.relative_to(self.vault).as_posix() for p in self.vault.rglob('*') if p.is_file()],
                         ['komuta/hafıza-raporu.md'])


if __name__ == '__main__':
    unittest.main()
