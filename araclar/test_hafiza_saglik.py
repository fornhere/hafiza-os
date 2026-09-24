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
    def test_manual_scan_does_not_hide_missing_or_stopped_scheduler(self):
        self.scan();self.audit()
        self.write(Path('komuta/hafıza-işletim.json'),dict(require_scheduled_scan=True))
        self.assertEqual('unknown',snapshot(self.v,self.now)['status'])
        self.write(RUN_PATH.with_name('scheduled-scan.json'),dict(status='complete',finished_at=(self.now-dt.timedelta(hours=3)).isoformat()))
        self.assertEqual('stale',snapshot(self.v,self.now)['status'])
        self.write(RUN_PATH.with_name('scheduled-scan.json'),dict(status='complete',finished_at=self.now.isoformat()))
        self.assertEqual('healthy',snapshot(self.v,self.now)['status'])

    def test_deferred_candidate_is_listed_without_stale_queue_warning(self):
        import hafiza as h
        old = (self.now-dt.timedelta(days=2)).isoformat()
        self.write(h.CANDIDATE_PATH, dict(candidate_id='deferred', created_at=old))
        self.write(h.EVENT_PATH, dict(event_type='candidate.deferred', candidate_id='deferred',
                                      at=self.now.isoformat(), review=dict(reason='Needs fixture evidence.')))
        self.scan(); self.audit()
        report = snapshot(self.v, self.now)
        self.assertEqual('healthy', report['status'])
        self.assertEqual(1, report['candidate_queue']['blocked_count'])
        self.assertEqual(0, report['candidate_queue']['pending_count'])
        self.assertEqual('healthy', next(c for c in report['checks'] if c['name']=='candidate_queue')['status'])
        self.write(h.CANDIDATE_PATH, dict(candidate_id='pending', created_at=old))
        report = snapshot(self.v, self.now)
        self.assertEqual('stale', report['status'])
        self.assertEqual(1, report['candidate_queue']['pending_count'])

class CatalogHealthTests(unittest.TestCase):
    setUp = HealthTests.setUp
    write = HealthTests.write
    audit = HealthTests.audit
    scan = HealthTests.scan
    def record(self, memory_id='example', **changes):
        import hafiza as h
        source = self.v/'source.md'
        source.write_text('Reviewed public fixture statement.')
        row = dict(memory_id=memory_id, kind='semantic', scope='user',
                   subject_key='fixture', statement='Reviewed public fixture statement.',
                   status='active', source_path='source.md', source_anchor='',
                   source_hash=h.statement_hash('Reviewed public fixture statement.'),
                   observed_at='2020-01-01', valid_from='2020-01-01', valid_to=None,
                   confidence='explicit', sensitivity='normal', mem0_id=None,
                   supersedes=None, reviewed_by='test', schema_version=1)
        row.update(changes)
        return row

    def catalog(self, rows):
        import hafiza as h
        target=self.v/h.CATALOG_PATH; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text('\n'.join(json.dumps(row) for row in rows))
        self.scan();self.audit()
        return snapshot(self.v,self.now)

    def test_optional_catalog_absence_is_explicit_unknown(self):
        self.scan();self.audit()
        report=snapshot(self.v,self.now)
        self.assertEqual('healthy',report['status'])
        self.assertEqual('unknown',report['catalog']['status'])
        self.assertIsNone(report['catalog']['active_count'])

    def test_valid_schema_does_not_hide_unreviewed_source(self):
        import hafiza as h
        row=self.record(statement='Missing from source.',source_hash=h.statement_hash('Missing from source.'))
        report=self.catalog([row]); checks={c['name']:c['status'] for c in report['checks']}
        self.assertEqual('healthy',checks['catalog_validation'])
        self.assertEqual('failed',checks['retrieval_eligibility'])
        self.assertEqual({'source_revision_unreviewed':1},report['catalog']['exclusion_reasons'])
        self.assertEqual(0,report['catalog']['eligible_count'])

    def test_inactive_records_are_not_active_loss(self):
        rows=[self.record(),self.record('old',status='superseded'),self.record('held',status='quarantined')]
        report=self.catalog(rows)
        self.assertEqual('healthy',report['status'])
        self.assertEqual(1,report['catalog']['active_count'])
        self.assertEqual(1,report['catalog']['eligible_count'])
        self.assertEqual(0,report['catalog']['excluded_count'])
        self.assertEqual(2,report['catalog']['inactive_count'])

    def test_private_expired_and_invalid_records_explain_counts_without_text(self):
        rows=[self.record('private-identity',sensitivity='private'),
              self.record('expired',valid_to='2000-01-01'),self.record('broken',source_hash='invalid')]
        report=self.catalog(rows); encoded=json.dumps(report)
        self.assertEqual(3,report['catalog']['excluded_count'])
        self.assertEqual({'sensitivity_restricted':1,'validity_window_excluded':1,
                          'record_integrity_error':1},report['catalog']['exclusion_reasons'])
        for text in ('private-identity','Reviewed public fixture statement.','source.md','broken'):
            self.assertNotIn(text,encoded)

    def test_malformed_catalog_is_failed_and_counts_unknown(self):
        import hafiza as h
        self.catalog([])
        (self.v/h.CATALOG_PATH).write_text('{bad JSON with private text')
        report=snapshot(self.v,self.now)
        self.assertEqual('failed',report['status'])
        self.assertIsNone(report['catalog']['eligible_count'])
        self.assertNotIn('private text',json.dumps(report))

    def test_duplicate_ids_fail_integrity_even_if_individually_eligible(self):
        report=self.catalog([self.record(),self.record()])
        self.assertEqual('failed',report['status'])
        self.assertEqual(1,report['catalog']['validation_error_count'])
        self.assertEqual(2,report['catalog']['eligible_count'])

    def test_policy_exclusions_are_healthy_and_partition_excluded_count(self):
        rows=[self.record('private',sensitivity='private'),
              self.record('expired',valid_to='2000-01-01'),
              self.record('future',valid_from='9999-01-01')]
        report=self.catalog(rows)
        self.assertEqual('healthy',report['status'])
        self.assertEqual(3,report['catalog']['policy_excluded_count'])
        self.assertEqual(0,report['catalog']['source_blocked_count'])
        self.assertEqual(3,report['catalog']['excluded_count'])

    def test_policy_gated_unreviewed_source_does_not_count_as_active_source_loss(self):
        import hafiza as h
        row=self.record(sensitivity='private', statement='Not in source',
                        source_hash=h.statement_hash('Not in source'))
        report=self.catalog([row])
        self.assertEqual('healthy',report['status'])
        self.assertEqual(1,report['catalog']['policy_excluded_count'])
        self.assertEqual(0,report['catalog']['source_blocked_count'])

    def test_notice_omits_static_catalog_issues_but_keeps_operational_failures(self):
        from unittest.mock import patch
        from hafiza_saglik import notice
        import hafiza as h
        row=self.record(statement='Missing from source',source_hash=h.statement_hash('Missing from source'))
        report=self.catalog([row])
        self.assertEqual('failed',report['status'])
        self.assertEqual(1,report['catalog']['source_blocked_count'])
        with patch('hafiza_saglik.snapshot', return_value=report):
            self.assertEqual('',notice(self.v))
        self.scan(3)
        report=snapshot(self.v,self.now)
        with patch('hafiza_saglik.snapshot', return_value=report):
            text=notice(self.v)
        self.assertIn('stale',text)
        self.assertIn('iki saatten eski',text)
        self.assertNotIn('source_revision_unreviewed',text)
