import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from hafiza_saglik import snapshot, RUN_PATH

class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name)
        self.now = dt.datetime(2026, 9, 15, 12, tzinfo=dt.timezone.utc)
    def write(self, path, value):
        p=self.v/path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(value))
    def audit(self, hours=0, **issues):
        p={k: [] for k in ('catalog_errors','missing_remote','drifted','orphan_remote_ids','duplicate_remote_groups')}; p.update(issues)
        self.write(Path('günlük/hafıza-makbuzları/2026-audit-test.json'), dict(at=(self.now-dt.timedelta(hours=hours)).isoformat(),payload=p))
    def scan(self, hours=0, **extra):
        data=dict(status='complete',finished_at=(self.now-dt.timedelta(hours=hours)).isoformat(),parse_errors=0);data.update(extra);self.write(RUN_PATH,data)
    def test_missing_is_unknown_not_healthy(self):
        self.assertEqual('unknown',snapshot(self.v,self.now)['status'])
    def test_recent_generation_does_not_refresh_old_audit(self):
        self.scan();self.audit(25)
        self.assertEqual('stale',snapshot(self.v,self.now)['status'])
    def test_orphans_fail_even_without_missing_records(self):
        self.scan();self.audit(orphan_remote_ids=['orphan'])
        self.assertEqual('failed',snapshot(self.v,self.now)['status'])
    def test_success_and_stopped_scheduler(self):
        self.scan();self.audit()
        self.assertEqual('healthy',snapshot(self.v,self.now)['status'])
        self.scan(3)
        self.assertEqual('stale',snapshot(self.v,self.now)['status'])
    def test_parse_error_and_incomplete_run(self):
        self.audit();self.scan(parse_errors=1)
        self.assertEqual('failed',snapshot(self.v,self.now)['status'])
        self.scan(1,status='running')
        self.assertEqual('failed',snapshot(self.v,self.now)['status'])
    def test_old_backlog_and_future_receipt(self):
        self.audit();self.scan(oldest_eligible_at=(self.now-dt.timedelta(days=2)).isoformat())
        self.assertEqual('stale',snapshot(self.v,self.now)['status'])
        self.scan(-1)
        self.assertEqual('failed',snapshot(self.v,self.now)['status'])
