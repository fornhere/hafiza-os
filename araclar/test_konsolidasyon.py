import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest

import hafiza as h
import codex_hafiza as hook
import konsolidasyon as k
from test_hafiza import FakeMem0


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name)
        self.evidence = 'Videolarımın açıklaması yapay zekâ odaklı olsun.'
        self.proposal = dict(statement='Forn video açıklamalarında yapay zekâ odağını tercih eder.',
                             subject_key='channel.seo-focus', evidence=self.evidence)

    def receipt(self):
        return hook.record(self.vault, 's', 't', 'Kullanıcı beyanı: ' + self.evidence, [self.proposal])

    def decision(self, ident):
        return dict(candidate_id=ident, reviewed_by=k.ACTOR, decision='approve',
            reason='Kaynak kullanıcı beyanı okundu; kalıcı tercih ve katalogda eşdeğeri yok.',
            source_checked=True, explicit_user=True, durable=True,
            normal_sensitivity=True, no_semantic_duplicate=True)

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
        second = h.add_candidate(self.vault, statement='Forn yeni bir kanal odağı seçti.', kind='semantic',
            scope='user', subject_key='channel.seo-focus', source_path=str(Path(first['saved']).relative_to(self.vault)),
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
            path.write_text('\n'.join(json.dumps(i) for i in items)); os.utime(path, (100000, 100000))
        since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        save(); self.assertEqual([], k.sessions(self.vault, root, since, 0))
        items.append(dict(type='response_item', timestamp='six', payload=dict(type='message', role='user', content=[dict(text='Altıncı gerçek mesaj')])))
        save(); rows = k.sessions(self.vault, root, since, 0)
        self.assertEqual(6, rows[0]['user_count'])
        self.assertNotIn('Gerçek mesaj', json.dumps(rows))
        k.checkpoint(self.vault, dict(rows[0], reason='Kalıcı bilgi yok; gözden geçirildi.'))
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
            items = [dict(type='session_meta', payload=dict(id=ident, source='vscode'))] + messages
            (root / 'sessions' / (ident + '.jsonl')).write_text(
                '\n'.join(json.dumps(x) for x in items))
        since = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
        rows = k.sessions(self.vault, root, since, 0)
        self.assertEqual(2, len(rows))
        inspected = next(r for r in rows if r['session_id'] == 'first')
        k.checkpoint(self.vault, dict(inspected, reason='Bu oturum incelendi; kalıcı aday yok.'))
        self.assertEqual(['second'], [r['session_id'] for r in k.sessions(self.vault, root, since, 0)])

if __name__ == '__main__': unittest.main()
