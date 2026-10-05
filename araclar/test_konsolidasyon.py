import datetime as dt
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import hafiza as h
import codex_hafiza as hook
import konsolidasyon as k
import capture_source as capture
from test_hafiza import FakeMem0


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name).resolve()
        for i in range(6):
            hook.hook(self.vault, dict(session_id="s", turn_id="t" if i == 5 else str(i), hook_event_name="UserPromptSubmit", prompt="Gerçek test isteği"))
        self.evidence = 'Belgelerin başlıkları kısa olsun.'
        self.proposal = dict(statement='Kullanıcı belgelerde kısa başlık tercih eder.',
                             subject_key='docs.title-style', evidence=self.evidence)

    def receipt(self):
        path=self.vault/'original.jsonl'
        rows=[dict(type='session_meta',payload=dict(id='s',source='exec',thread_source='user'))]
        rows += [dict(type='response_item',timestamp=str(i),payload=dict(type='message',role='user',content=[dict(text=self.evidence if i==5 else 'Gerçek istek '+str(i))])) for i in range(6)]
        rows.append(dict(type='event_msg',payload=dict(type='task_complete',turn_id='t')))
        path.write_text('\n'.join(map(json.dumps,rows)))
        snap=capture.snapshot(path,completed_prefix=True)
        proposal=dict(self.proposal,evidence_source=dict(snap,line=7,message_hash=capture.digest(self.evidence),quote=self.evidence))
        return hook.record(self.vault, 's', 'recovery-v2-'+snap['source_hash'], 'Kullanıcı beyanı: ' + self.evidence, [proposal],snap)

    def decision(self, ident):
        return dict(candidate_id=ident, reviewed_by=k.ACTOR, decision='approve',
            reason='Kaynak kullanıcı beyanı okundu; kalıcı tercih ve katalogda eşdeğeri yok.',
            source_checked=True, explicit_user=True, durable=True,
            normal_sensitivity=True, no_semantic_duplicate=True)

    def test_blocked_candidate_returns_to_pending_after_a_day(self):
        first=self.receipt(); cid=first['candidates'][0]['candidate_id']
        h._append_jsonl(self.vault/h.EVENT_PATH, dict(event_type='candidate.deferred', candidate_id=cid,
            at='2026-01-01T00:00:00+00:00', review=dict(decision='defer', reason='Kanıt doğrulanamadı; tekrar denenecek.')))
        now=dt.datetime(2026,1,1,12,tzinfo=dt.timezone.utc)
        self.assertEqual([cid],[c['candidate_id'] for c in k.candidate_states(self.vault, now)['blocked']])
        later=dt.datetime(2026,1,2,1,tzinfo=dt.timezone.utc)
        retried=k.candidate_states(self.vault, later)['pending']
        self.assertEqual([cid],[c['candidate_id'] for c in retried]); self.assertTrue(retried[0]['retry'])

    def test_deferred_state_requeue_and_terminal(self):
        source = self.vault / 'source.txt'
        source.write_text('First supporting passage. Second supporting passage.', encoding='utf-8')
        kwargs = dict(statement='Fixture preference is concise.', kind='semantic', scope='user',
                      subject_key='fixture.preference', source_path='source.txt', source_anchor='',
                      confidence='explicit-user', sensitivity='normal', proposed_by='test',
                      evidence='First supporting passage.')
        first = h.add_candidate(self.vault, **kwargs)
        cid = first['candidate_id']
        decision = dict(candidate_id=cid, reviewed_by=k.ACTOR, decision='defer',
                        reason='Supporting passage lacks an explicit user statement.')
        k.review(self.vault, decision, True)
        states = k.candidate_states(self.vault)
        self.assertEqual([], states['pending'])
        self.assertEqual(cid, states['blocked'][0]['candidate_id'])
        self.assertEqual(decision['reason'], states['blocked'][0]['blocked_reason'])
        self.assertTrue(states['blocked'][0]['last_reviewed_at'])
        self.assertEqual('duplicate', h.add_candidate(self.vault, **kwargs)['result'])
        second = h.add_candidate(self.vault, **dict(kwargs, evidence='Second supporting passage.'))
        self.assertEqual('requeued', second['result'])
        self.assertEqual(cid, second['supersedes_candidate'])
        self.assertEqual(cid, h.load_jsonl(self.vault / h.CANDIDATE_PATH)[1]['supersedes_candidate'])
        self.assertEqual('duplicate', h.add_candidate(self.vault, **dict(kwargs, evidence='Second supporting passage.'))['result'])
        status = k.status(self.vault)
        self.assertEqual((1, 1), (status['pending_candidates'], status['blocked_candidates']))
        self.assertIsNotNone(status['oldest_pending_days'])
        h._append_jsonl(self.vault / h.EVENT_PATH, dict(event_type='candidate.promoted',
                        candidate_id=second['candidate_id'], at=dt.datetime.now(dt.timezone.utc).isoformat()))
        states = k.candidate_states(self.vault)
        self.assertEqual([], states['pending'])
        self.assertEqual(1, len(states['blocked']))
        self.assertEqual(second['candidate_id'], states['terminal'][0]['candidate_id'])
        status = k.status(self.vault)
        self.assertEqual((0, 1), (status['pending_candidates'], status['blocked_candidates']))
        self.assertIsNone(status['oldest_pending_days'])

    def test_review_booleans_cannot_replace_original_evidence(self):
        first=self.receipt(); cid=first['candidates'][0]['candidate_id']
        rows=h.load_jsonl(self.vault/h.CANDIDATE_PATH)
        rows[0].pop('evidence_source',None)
        h._write_jsonl(self.vault/h.CANDIDATE_PATH,rows)
        with self.assertRaises(ValueError): k.review(self.vault,self.decision(cid),True)
        self.assertEqual([],h.load_catalog(self.vault))

    def test_original_message_mutation_blocks_promotion(self):
        first=self.receipt(); cid=first['candidates'][0]['candidate_id']
        original=self.vault/'original.jsonl'
        events=[json.loads(line) for line in original.read_text().splitlines()]
        events[6]['payload']['content'][0]['text']='Tamamen farklı kullanıcı isteği'
        original.write_text('\n'.join(map(json.dumps,events)))
        with self.assertRaises(ValueError): k.review(self.vault,self.decision(cid),True)
        self.assertEqual([],h.load_catalog(self.vault))

    def test_receipt_review_sync_retry_roundtrip(self):
        first = self.receipt(); self.receipt()
        self.assertEqual(1, len(k.pending(self.vault)))
        decision = self.decision(first['candidates'][0]['candidate_id'])
        k.review(self.vault, decision)
        self.assertEqual([], h.load_catalog(self.vault))
        k.review(self.vault, decision, True)
        self.assertEqual([], k.pending(self.vault))
        client = FakeMem0([])
        r = h.sync_existing(self.vault, h.load_catalog(self.vault), client, apply=True)
        self.assertEqual(1, r['verified'])
        h.sync_existing(self.vault, h.load_catalog(self.vault), client, apply=True)
        self.assertEqual(1, len(client.added))

    def test_missing_evidence_and_changed_source_rejected(self):
        with self.assertRaises(ValueError):
            hook.record(self.vault, 's', 't', 'Bu özet kullanıcı beyanını içermiyor.', [self.proposal])
        result = self.receipt()
        Path(result['saved']).write_text('Kaynak değiştirilmiş')
        with self.assertRaisesRegex(ValueError, 'kanıtı'):
            k.review(self.vault, self.decision(result['candidates'][0]['candidate_id']), True)
        self.assertEqual([], h.load_catalog(self.vault))

    def test_review_cannot_bypass_checks(self):
        first = self.receipt(); decision = self.decision(first['candidates'][0]['candidate_id'])
        decision['durable'] = False
        with self.assertRaises(ValueError): k.review(self.vault, decision, True)

    def test_supersedes_changes_local_and_remote_status(self):
        first = self.receipt(); cid = first['candidates'][0]['candidate_id']
        h.promote_candidate(self.vault, cid, memory_id='old', reviewed_by='test', apply=True)
        client = FakeMem0([])
        h.sync_existing(self.vault, h.load_catalog(self.vault), client, apply=True)
        second = h.add_candidate(self.vault, statement='Kullanıcı yeni bir başlık biçimi seçti.', kind='semantic',
            scope='user', subject_key='docs.title-style', source_path=str(Path(first['saved']).relative_to(self.vault)),
            source_anchor='beyan', confidence='explicit-user', sensitivity='normal', proposed_by='test')
        with self.assertRaisesRegex(ValueError, 'eşleşmeli'):
            h.promote_candidate(self.vault, second['candidate_id'], memory_id='new', reviewed_by='test', supersedes='wrong', apply=True)
        h.promote_candidate(self.vault, second['candidate_id'], memory_id='new', reviewed_by='test', supersedes='old', apply=True)
        records = h.load_catalog(self.vault)
        self.assertEqual('superseded', records[0]['status'])
        records[1]['mem0_id'] = 'new-remote'
        client.remote['new-remote'] = dict(id='new-remote', memory=records[1]['statement'], metadata={})
        h._write_jsonl(self.vault / h.CATALOG_PATH, records)
        h.sync_existing(self.vault, records, client, apply=True)
        self.assertEqual('superseded', next(iter(client.remote.values()))['metadata']['status'])

    def test_remote_add_crash_is_recovered_by_identity(self):
        result = self.receipt()
        k.review(self.vault, self.decision(result['candidates'][0]['candidate_id']), True)
        records = h.load_catalog(self.vault); record = records[0]
        client = FakeMem0([dict(id='recovered', memory=record['statement'], metadata=h.memory_metadata(self.vault, record))])
        receipt = h.sync_existing(self.vault, records, client, apply=True)
        self.assertEqual(1, receipt['verified']); self.assertEqual([], client.added)
        self.assertEqual('recovered', h.load_catalog(self.vault)[0]['mem0_id'])

    def test_stale_sync_cannot_overwrite_new_catalog(self):
        first = self.receipt()
        k.review(self.vault, self.decision(first['candidates'][0]['candidate_id']), True)
        with self.assertRaisesRegex(ValueError, 'eşzamanlı'):
            h.sync_existing(self.vault, [], FakeMem0([]), apply=True)
        self.assertEqual(1, len(h.load_catalog(self.vault)))

    def test_source_outside_vault_and_private_candidate_rejected(self):
        kwargs = dict(statement=self.proposal['statement'], kind='semantic', scope='user',
            subject_key='x', source_path='/etc/hostname', source_anchor='x',
            confidence='explicit-user', sensitivity='private', proposed_by='test')
        with self.assertRaises(ValueError): h.add_candidate(self.vault, **kwargs)
        with self.assertRaises(ValueError): h.source_file(self.vault, '/etc/hostname')

    def test_sessions_threshold_synthetic_and_checkpoint(self):
        root = self.vault / 'codex'; (root / 'sessions').mkdir(parents=True)
        path = root / 'sessions/test.jsonl'
        items = [dict(type='session_meta', payload=dict(id='test', source='vscode'))]
        for i in range(5):
            items.append(dict(type='response_item', timestamp=str(i), payload=dict(type='message', role='user', content=[dict(text='Gerçek mesaj')])) )
        items.append(dict(type='response_item', payload=dict(type='message', role='user', content=[dict(text='<goal>otomatik</goal>')])))
        def save():
            items.append(dict(type='event_msg', payload=dict(type='task_complete', turn_id='t6')))
            path.write_text('\n'.join(json.dumps(i) for i in items)); os.utime(path, (100000, 100000))
        since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        save(); self.assertEqual([], k.sessions(self.vault, root, since, 0))
        items.append(dict(type='response_item', timestamp='six', payload=dict(type='message', role='user', content=[dict(text='Altıncı gerçek mesaj')])))
        save(); rows = k.sessions(self.vault, root, since, 0)
        self.assertEqual(6, rows[0]['user_count'])
        self.assertNotIn('Gerçek mesaj', json.dumps(rows))
        k.checkpoint(self.vault, dict(rows[0], outcome='no_relevant_change', reason='Kalıcı bilgi yok; gözden geçirildi.'))
        self.assertEqual([], k.sessions(self.vault, root, since, 0))



    def test_rollout_owner_survives_inherited_metadata(self):
        root = self.vault / 'codex'; (root / 'sessions').mkdir(parents=True)
        messages = [dict(type='response_item', timestamp=str(i), payload=dict(
            type='message', role='user', content=[dict(text='Gerçek istek')])) for i in range(6)]
        parent = dict(type='session_meta', payload=dict(id='parent', source='vscode'))
        child = dict(type='session_meta', payload=dict(id='child', source={
            'subagent': {'thread_spawn': {'parent_thread_id': 'parent'}}}))
        for name, items in [('parent', [parent] + messages),
                            ('child', [child, parent] + messages)]:
            path = root / 'sessions' / (name + '.jsonl')
            path.write_text('\n'.join(json.dumps(x) for x in items))
        since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        rows = k.sessions(self.vault, root, since, 0)
        self.assertEqual(['parent'], [r['session_id'] for r in rows])
        self.assertEqual('parent.jsonl', Path(rows[0]['path']).name)

    def test_checkpoint_is_scoped_to_session_identity(self):
        root = self.vault / 'codex'; (root / 'sessions').mkdir(parents=True)
        messages = [dict(type='response_item', timestamp=str(i), payload=dict(
            type='message', role='user', content=[dict(text='Aynı gerçek istek')])) for i in range(6)]
        for ident in ('first', 'second'):
            items = [dict(type='session_meta', payload=dict(id=ident, source='vscode'))] + messages + [dict(type='event_msg', payload=dict(type='task_complete', turn_id='t6'))]
            (root / 'sessions' / (ident + '.jsonl')).write_text(
                '\n'.join(json.dumps(x) for x in items))
        since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        rows = k.sessions(self.vault, root, since, 0)
        self.assertEqual(2, len(rows))
        inspected = next(r for r in rows if r['session_id'] == 'first')
        k.checkpoint(self.vault, dict(inspected, outcome='no_relevant_change', reason='Bu oturum incelendi; kalıcı aday yok.'))
        self.assertEqual(['second'], [r['session_id'] for r in k.sessions(self.vault, root, since, 0)])

class ScheduledScan(unittest.TestCase):
    def test_cli_default_since_is_last_14_days_utc(self):
        before=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=14)
        with tempfile.TemporaryDirectory() as directory, patch.object(sys,'argv',[
                'konsolidasyon.py','--vault',directory,'sessions','--codex-root',directory]), \
                patch.object(k,'scan_with_receipt',return_value=[]) as scan, \
                contextlib.redirect_stdout(io.StringIO()):
            k.main()
        after=dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=14)
        self.assertLessEqual(before,scan.call_args.args[2])
        self.assertLessEqual(scan.call_args.args[2],after)

    def test_cli_explicit_since_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(sys,'argv',[
                'konsolidasyon.py','--vault',directory,'sessions','--since','2026-09-12']), \
                patch.object(k,'scan_with_receipt',return_value=[]) as scan, \
                contextlib.redirect_stdout(io.StringIO()):
            k.main()
        self.assertEqual(dt.datetime(2026,9,12,tzinfo=dt.timezone.utc),scan.call_args.args[2])

    def test_manual_scan_never_refreshes_scheduled_receipt(self):
        from hafiza_saglik import RUN_PATH
        with tempfile.TemporaryDirectory() as directory:
            vault=Path(directory).resolve()
            since=dt.datetime(1970,1,1,tzinfo=dt.timezone.utc)
            target=vault/RUN_PATH.with_name('scheduled-scan.json')
            k.scan_with_receipt(vault,vault/'empty',since)
            self.assertFalse(target.exists())
            k.scan_with_receipt(vault,vault/'empty',since,scheduled=True)
            before=target.read_bytes()
            self.assertEqual(since.isoformat(),json.loads(before)['since'])
            k.scan_with_receipt(vault,vault/'empty',since)
            self.assertEqual(before,target.read_bytes())


class AutomaticRegistryMaintenance(unittest.TestCase):
    def setUp(self):
        import client_sessions
        self.client = client_sessions
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.vault = Path(directory.name).resolve()
        _, self.state = self.client.layout(self.vault)
        self.since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        limit = patch.object(self.client, 'MAX_REGISTRY', 10)
        limit.start(); self.addCleanup(limit.stop)

    def fill(self, statuses):
        for index, status in enumerate(statuses):
            self.client.atomic(self.state / (f'{index:064x}.json'),
                               dict(status=status, created_ns=1))

    def run_scan(self, scheduled=True):
        k.scan_with_receipt(self.vault, self.vault / 'empty', self.since, scheduled)
        from hafiza_saglik import RUN_PATH
        return json.loads((self.vault / RUN_PATH).read_text())

    def test_below_and_exact_threshold_do_not_call_maintenance(self):
        for count in (6, 7):
            with self.subTest(count=count):
                self.fill(['superseded'] * count)
                with patch.object(self.client, 'maintain') as maintain:
                    receipt = self.run_scan()
                maintain.assert_not_called()
                self.assertEqual('below_threshold', receipt['client_registry_maintenance']['status'])
                self.assertEqual(0, self.client.registry_status(self.vault)['archive_count'])

    def test_above_threshold_archives_only_terminals_and_is_idempotent(self):
        self.fill(['superseded'] * 5 + ['pending', 'record', 'skip'])
        original = (self.state / (f'{0:064x}.json')).read_bytes()
        with patch.object(self.client, 'maintain', wraps=self.client.maintain) as maintain:
            receipt = self.run_scan()
        maintain.assert_called_once_with(self.vault, apply=True)
        result = receipt['client_registry_maintenance']
        self.assertEqual(5, len(result['receipts']))
        self.assertEqual(8, result['before']['active_count'])
        self.assertEqual(3, result['after']['active_count'])
        move = next(r for r in result['receipts'] if r['source'] == f'{0:064x}.json')
        destination = self.state / move['destination']
        self.assertEqual(original, destination.read_bytes())
        self.assertEqual(move, json.loads(destination.with_suffix('.move.json').read_text()))
        from hafiza_saglik import RUN_PATH
        scheduled = json.loads((self.vault / RUN_PATH.with_name('scheduled-scan.json')).read_text())
        self.assertEqual(result, scheduled['client_registry_maintenance'])
        registry = k.status(self.vault)['client_registry']
        self.assertEqual(5, registry['archive_count'])
        self.assertEqual(0.3, registry['occupancy_ratio'])
        before = {p: p.read_bytes() for p in self.state.rglob('*.json')}
        with patch.object(self.client, 'maintain') as maintain:
            self.run_scan()
        maintain.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in self.state.rglob('*.json')})

    def test_manual_scan_does_not_maintain_above_threshold(self):
        self.fill(['superseded'] * 8)
        with patch.object(self.client, 'maintain') as maintain:
            receipt = self.run_scan(scheduled=False)
        maintain.assert_not_called()
        self.assertNotIn('client_registry_maintenance', receipt)
        self.assertEqual(8, self.client.registry_status(self.vault)['active_count'])

    def test_repeated_maintenance_above_threshold_has_no_new_moves(self):
        self.fill(['superseded'] + ['pending'] * 8)
        self.assertEqual(1, len(self.run_scan()['client_registry_maintenance']['receipts']))
        before = {p: p.read_bytes() for p in self.state.rglob('*.json')}
        with patch.object(self.client, 'maintain', wraps=self.client.maintain) as maintain:
            receipt = self.run_scan()
        maintain.assert_called_once_with(self.vault, apply=True)
        self.assertEqual([], receipt['client_registry_maintenance']['receipts'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.state.rglob('*.json')})

    def test_status_and_hook_warning_use_same_capacity(self):
        from hook_health import warning
        self.fill(['pending'] * 9)
        self.assertEqual('', warning(self.vault))
        self.fill(['pending'] * 10)
        before = {p: p.read_bytes() for p in self.vault.rglob('*') if p.is_file()}
        report = k.status(self.vault)
        registry = report['client_registry']
        self.assertEqual(10, registry['active_count'])
        self.assertEqual(0, registry['archive_count'])
        self.assertEqual(1.0, registry['occupancy_ratio'])
        check = next(c for c in report['operational_health']['checks'] if c['name'] == 'client_registry')
        self.assertEqual('stale', check['status'])
        self.assertEqual(warning(self.vault), check['reason'])
        self.assertIn('registry_capacity_high', check['reason'])
        self.assertEqual(before, {p: p.read_bytes() for p in self.vault.rglob('*') if p.is_file()})

    def test_failed_maintenance_marks_scheduled_run_failed(self):
        self.fill(['superseded'] * 8)
        with patch.object(self.client, 'maintain', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.run_scan()
        from hafiza_saglik import RUN_PATH
        receipt = json.loads((self.vault / RUN_PATH.with_name('scheduled-scan.json')).read_text())
        self.assertEqual('failed', receipt['status'])
        self.assertEqual('OSError', receipt['error_code'])

if __name__ == '__main__': unittest.main()
