import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import hafiza as h
import is_ve_ders as w


def acceptance_fixture(vault, quote='Talimat dosyasındaki bu değişikliği kabul ettim.', prior=5, role='user', completed=True):
    import capture_source as c
    events=[dict(type='session_meta',payload=dict(id='session',source='vscode'))]
    events += [dict(type='response_item',timestamp=str(i),payload=dict(type='message',role='user',content=[dict(text='İstek '+str(i))])) for i in range(prior)]
    events += [dict(type='response_item',timestamp='acceptance',payload=dict(type='message',role=role,content=[dict(text=quote)]))]
    if completed: events += [dict(type='event_msg',payload=dict(type='task_complete',turn_id='acceptance'))]
    path=vault/'acceptance.jsonl';path.write_text('\n'.join(json.dumps(event,ensure_ascii=False) for event in events))
    source=c.snapshot(path,completed_prefix=True)
    return dict(session_id='session',source_snapshot=source,evidence_source=dict(source,line=prior+2,message_hash=c.digest(quote),quote=quote),evidence=quote)


class Work(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name).resolve()
        (self.vault / 'kaynak.md').write_text('İşin uygulaması tamamlandı, testler geçti.')
        self.row = dict(id='test', title='Kaynaklı görev', status='active', next_step='Doğrula',
            source_path='kaynak.md', evidence='İşin uygulaması tamamlandı', actor='test',
            last_verified=dt.date.today().isoformat())

    def test_task_decision_and_outcome_validation_and_brief(self):
        for name, values in (('decision_required', (None, False, '', ' ', 'x'*241)),
                             ('outcome_unverified', (None, 0, 1, 'true')),
                             ('status_reason', (None, False, '', ' ', 'x'*501))):
            for value in values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    w.put(self.vault, 'task', dict(self.row, **{name:value}))
        row = w.put(self.vault, 'task', dict(self.row,
            decision_required='Yayın zamanını seç', outcome_unverified=True))
        card = w.brief(self.vault)[0]
        self.assertEqual('active', card['status'])
        self.assertEqual(row['decision_required'], card['decision_required'])
        self.assertTrue(card['outcome_unverified'])
        row = w.put(self.vault, 'task', dict(row, expected_version=1, outcome_unverified=False))
        self.assertFalse(w.brief(self.vault)[0]['outcome_unverified'])
        self.assertEqual(row['updated_at'], w.brief(self.vault)[0]['content_updated_at'])

    def test_active_to_pending_requires_reason_but_legacy_creation_does_not(self):
        row = w.put(self.vault, 'task', self.row)
        pending = dict(row, status='needs_confirmation', expected_version=1)
        with self.assertRaisesRegex(ValueError, 'status_reason'):
            w.put(self.vault, 'task', pending)
        self.assertEqual(1, w.latest(self.vault, 'task')['test']['version'])
        saved = w.put(self.vault, 'task', dict(pending, status_reason='Kapsam değişimi kaynakta belirtildi'))
        self.assertEqual('needs_confirmation', saved['status'])
        self.assertEqual([], w.brief(self.vault))
        w.put(self.vault, 'task', dict(self.row, id='legacy', status='needs_confirmation'))

    def test_missing_ledger_preserves_existing_view(self):
        target = self.vault / 'zihin/açık-işler.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Existing user work list\n')
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'defteri'):
            w.render(self.vault)
        self.assertEqual(before, target.read_bytes())

    def test_project_report_preserves_active_and_pending_with_receipt_replay(self):
        (self.vault / 'komuta').mkdir()
        state = dict(project_id='demo', outcome='Uygulama tamamlandı.',
            rationale='Kaynak kontrolü tamamlandı.', open_items=['Kabul bekleniyor.'],
            next_step='Kullanıcı kabulünü doğrula.', evidence=dict(quote=self.row['evidence']))
        transcript = dict(client='claude', session='neutral-session')
        registry = self.vault / 'komuta/gorev-baglam.json'
        for initial in (None, 'needs_confirmation', 'active'):
            with self.subTest(initial=initial):
                project = 'demo-' + str(initial)
                registry.write_text(json.dumps({'projects': [{'id': project}]}))
                report = dict(state, project_id=project)
                ident = 'project-state:' + project
                if initial:
                    w.put(self.vault, 'task', dict(self.row, id=ident,
                        project_id=project, status=initial))
                before = len(h.load_jsonl(self.vault / w.TASKS))
                row = w.put_project_state(self.vault, report, project, 'kaynak.md', transcript)
                self.assertEqual('active' if initial == 'active' else 'needs_confirmation', row['status'])
                self.assertEqual(initial == 'active', row.get('outcome_unverified', False))
                self.assertEqual(2 if initial else 1, row['version'])
                self.assertEqual(report, row['assistant_report'])
                self.assertIsNone(row['verified_outcome'])
                self.assertNotIn('last_verified', row)
                self.assertEqual(row, w.put_project_state(self.vault, report, project, 'kaynak.md', transcript))
                for changed_report, changed_transcript in (
                        (dict(report, outcome='Başka rapor.'), transcript),
                        (report, dict(transcript, session='other-session'))):
                    with self.assertRaisesRegex(ValueError, 'project_state_receipt_conflict'):
                        w.put_project_state(self.vault, changed_report, project, 'kaynak.md', changed_transcript)
                self.assertEqual(before + 1, len(h.load_jsonl(self.vault / w.TASKS)))

    def test_successive_reports_preserve_decision_basis_without_confirmation(self):
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': [{'id': 'demo'}]}))
        active = w.put(self.vault, 'task', dict(self.row, id='project-state:demo',
            project_id='demo', decision_required='Kabul zamanını kullanıcı seçsin'))
        basis = {k: active[k] for k in ('id', 'version', 'source_path', 'source_content_hash', 'evidence')}
        quote = 'Asistan yeni uygulama adımını raporladı.'
        (self.vault / 'report.md').write_text(quote)
        report = dict(project_id='demo', outcome=quote, next_step='Kabulü doğrula.', evidence=dict(quote=quote))
        for receipt in ('first', 'second'):
            row = w.put_project_state(self.vault, report, receipt, 'report.md', {})
            self.assertEqual(active['decision_required'], row['decision_required'])
            self.assertEqual(basis, row['decision_source'])
            self.assertNotIn('last_verified', row)
            self.assertIsNone(row['verified_outcome'])
            self.assertTrue(row['outcome_unverified'])
            self.assertNotIn('decision_required', row['assistant_report'])
            self.assertEqual(row, w.put_project_state(self.vault, report, receipt, 'report.md', {}))
        from client_sessions import state_warnings
        self.assertIn(('karar bekliyor: '+active['decision_required'], basis), state_warnings(self.vault, row))
        (self.vault / 'kaynak.md').write_text('Eski kaynak artık değişti.')
        self.assertEqual([('sonuç teyitsiz', row)], state_warnings(self.vault, row))

    def test_done_disappears_from_brief_but_history_remains(self):
        w.put(self.vault, 'task', self.row)
        self.assertEqual(1, len(w.brief(self.vault)))
        w.put(self.vault, 'task', dict(self.row, status='done', expected_version=1))
        self.assertEqual([], w.brief(self.vault))
        self.assertEqual(2, len(h.load_jsonl(self.vault / w.TASKS)))
        w.render(self.vault)
        self.assertIn('Kapanan işler', (self.vault / 'zihin/açık-işler.md').read_text())

    def test_pending_opt_in_preserves_confirmation_and_source_checks(self):
        w.put(self.vault, 'task', dict(self.row, status='needs_confirmation'))
        self.assertEqual([], w.brief(self.vault, include_stale=True))
        self.assertEqual([], w.brief(self.vault, include_pending=True))
        card = w.brief(self.vault, include_stale=True, include_pending=True)[0]
        self.assertEqual('needs_confirmation', card['status'])
        self.assertTrue(card['confirmation_required'])
        (self.vault/'kaynak.md').write_text('Kaynak sonradan değişti.')
        self.assertEqual([], w.brief(self.vault, include_stale=True, include_pending=True))

    def test_pending_optional_next_step_keeps_recorded_state(self):
        for value in ('missing', None):
            with self.subTest(next_step=value):
                row = dict(self.row, id='pending-'+str(value), status='needs_confirmation')
                if value == 'missing': row.pop('next_step')
                else: row['next_step'] = value
                stored = w.put(self.vault, 'task', row)
                card = w.brief(self.vault, include_stale=True, include_pending=True,
                               card_ids={stored['id']})[0]
                self.assertEqual('needs_confirmation', card['status'])
                self.assertTrue(card['confirmation_required'])
                self.assertEqual(stored.get('next_step'), card.get('next_step'))
                self.assertEqual('next_step' in stored, 'next_step' in card)
                self.assertEqual([], w.brief(self.vault))

    def test_pending_opt_in_uses_latest_card_and_excludes_closed_status(self):
        w.put(self.vault, 'task', dict(self.row, status='needs_confirmation'))
        w.put(self.vault, 'task', dict(self.row, status='done', expected_version=1))
        self.assertEqual([], w.brief(self.vault, include_stale=True, include_pending=True))

    def test_card_ids_filter_skips_unrelated_source_reads(self):
        w.put(self.vault, 'task', self.row)
        w.put(self.vault, 'task', dict(self.row, id='other'))
        with patch.object(h, 'source_file', wraps=h.source_file) as reader:
            cards = w.brief(self.vault, card_ids={'test'})
        self.assertEqual(['test'], [c['id'] for c in cards])
        self.assertEqual(1, reader.call_count)
        self.assertEqual([], w.brief(self.vault, card_ids=set()))

    def test_stale_and_unconfirmed_not_presented_as_current(self):
        w.put(self.vault, 'task', dict(self.row, last_verified='2020-01-01'))
        old = w.brief(self.vault, include_stale=True)[0]
        self.assertEqual('needs_confirmation', old['status'])
        self.assertEqual('2020-01-01', old['last_verified'])
        self.assertTrue(old['confirmation_required'])
        self.assertEqual([], w.brief(self.vault, include_stale=False))
        w.render(self.vault)
        self.assertIn('**needs_confirmation**', (self.vault/'zihin/açık-işler.md').read_text())
        w.put(self.vault, 'task', dict(self.row, expected_version=1, status='needs_confirmation', status_reason='Kapsam değişimi için teyit gerekli'))
        self.assertEqual([], w.brief(self.vault))

    def test_week_old_confirmation_is_not_current(self):
        eight = (w.dt.date.today() - w.dt.timedelta(days=8)).isoformat()
        six = (w.dt.date.today() - w.dt.timedelta(days=6)).isoformat()
        w.put(self.vault, 'task', dict(self.row, last_verified=six))
        self.assertEqual(1, len(w.brief(self.vault)))
        w.put(self.vault, 'task', dict(self.row, last_verified=eight, expected_version=1))
        self.assertEqual([], w.brief(self.vault))
        self.assertTrue(w.brief(self.vault, include_stale=True)[0]['confirmation_required'])
        w.put(self.vault, 'task', dict(self.row, id='fresh', last_verified=six))
        self.assertEqual('fresh', w.brief(self.vault, limit=1, include_stale=True)[0]['id'])

    def test_missing_verification_is_only_a_pinned_history_hint(self):
        for status in ('active', 'blocked'):
            with self.subTest(status=status):
                data = dict(self.row, id=status, status=status)
                data.pop('last_verified')
                saved = w.put(self.vault, 'task', data)
                hint = next(r for r in w.brief(self.vault, include_stale=True) if r['id'] == status)
                self.assertEqual('needs_confirmation', hint['status'])
                self.assertTrue(hint['confirmation_required'])
                self.assertTrue(hint['verification_missing'])
                self.assertNotIn('last_verified', hint)
                self.assertEqual(saved['updated_at'], hint['updated_at'])
                self.assertEqual(saved, w.latest(self.vault, 'task')[status])
        self.assertEqual([], w.brief(self.vault))
        w.render(self.vault)
        view = (self.vault / 'zihin/açık-işler.md').read_text()
        self.assertNotIn('**active**', view)
        self.assertNotIn('**blocked**', view)
        self.assertEqual(2, view.count('**needs_confirmation**'))

    def test_missing_verification_sorts_after_current_even_if_newer(self):
        w.put(self.vault, 'task', dict(self.row, id='current'))
        w.put(self.vault, 'task', dict(self.row, id='dated', last_verified='2020-01-01'))
        w.put(self.vault, 'task', dict(self.row, last_verified=None))
        self.assertEqual(['current', 'dated', 'test'], [r['id'] for r in w.brief(self.vault, include_stale=True)])
        self.assertEqual('current', w.brief(self.vault, limit=1, include_stale=True)[0]['id'])

    def test_missing_verification_requires_unchanged_pinned_source(self):
        saved = w.put(self.vault, 'task', dict(self.row, last_verified=None))
        for changes in (dict(source_content_hash=None), dict(source_content_hash='wrong'),
                        dict(evidence='Kaynakta olmayan sonuç'), dict(source_path='missing.md')):
            with self.subTest(changes=changes), patch.object(w, 'latest', return_value={'test': dict(saved, **changes)}):
                self.assertEqual([], w.brief(self.vault, include_stale=True))
        source = self.vault / 'kaynak.md'
        source.write_text(source.read_text() + ' Durum değişti.')
        self.assertEqual([], w.brief(self.vault, include_stale=True))

    def test_missing_verification_does_not_restore_closed_or_archived_work(self):
        w.put(self.vault, 'task', dict(self.row, id='closed', status='done', last_verified=None))
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': [dict(id='old', status='archived')]}))
        w.put(self.vault, 'task', dict(self.row, project_id='old', last_verified=None))
        self.assertEqual([], w.brief(self.vault, include_stale=True))

    def test_task_source_change_invalidates_current_summary_even_with_quote(self):
        row=w.put(self.vault, 'task', self.row)
        self.assertIn('source_content_hash',row)
        source=self.vault/'kaynak.md';source.write_text(source.read_text()+' Ancak önceki iş iptal edildi.')
        self.assertEqual([],w.brief(self.vault))

    def test_brief_optional_exclusion_diagnostics(self):
        saved = w.put(self.vault, 'task', self.row)
        cases = [(dict(source_path='missing.md'), 'source_missing'),
                 (dict(evidence='Kaynakta olmayan sonuç'), 'evidence_missing'),
                 (dict(evidence=''), 'evidence_missing'),
                 (dict(source_content_hash='wrong'), 'source_changed'),
                 (dict(last_verified=None), 'unverified'),
                 (dict(last_verified='invalid'), 'unverified'),
                 (dict(last_verified='2020-01-01'), 'stale')]
        for changes, reason in cases:
            with self.subTest(reason=reason, changes=changes), patch.object(
                    w, 'latest', return_value={'test': dict(saved, **changes)}):
                diagnostics = []
                self.assertEqual([], w.brief(self.vault, diagnostics=diagnostics))
                self.assertEqual([('test', reason)], [(d['id'], d['reason']) for d in diagnostics])
        diagnostics = []
        self.assertEqual(w.brief(self.vault), w.brief(self.vault, diagnostics=diagnostics))
        self.assertEqual([], diagnostics)

    def test_metadata_versions_preserve_content_recency_and_latest(self):
        registry = self.vault/'komuta/gorev-baglam.json'
        registry.parent.mkdir()
        registry.write_text(json.dumps({'projects': [dict(id='alpha')]}))
        first = w.put(self.vault, 'task', self.row)
        second = w.put(self.vault, 'task', dict(self.row, id='second'))
        metadata = w.put(self.vault, 'task', dict(first, project_id='alpha',
                         actor='new actor', tags=['new'], expected_version=1))
        rows = [dict(first, updated_at='2026-10-01T10:00:00+00:00'),
                dict(second, updated_at='2026-10-02T10:00:00+00:00'),
                dict(metadata, updated_at='2026-10-03T10:00:00+00:00')]
        h._write_jsonl(self.vault/w.TASKS, rows)
        self.assertEqual(rows[-1], w.latest(self.vault, 'task')['test'])
        cards = w.brief(self.vault)
        self.assertEqual(['second', 'test'], [r['id'] for r in cards])
        self.assertEqual(rows[0]['updated_at'], cards[1]['content_updated_at'])
        self.assertEqual(rows[-1]['updated_at'], cards[1]['updated_at'])
        changed = w.put(self.vault, 'task', dict(metadata, next_step='Yeni adımı uygula', expected_version=2))
        self.assertEqual('test', w.brief(self.vault)[0]['id'])
        self.assertEqual(changed['updated_at'], w.brief(self.vault)[0]['content_updated_at'])

    def test_stale_writer_and_missing_source_rejected(self):
        w.put(self.vault, 'task', self.row)
        with self.assertRaisesRegex(ValueError, 'sürüm'):
            w.put(self.vault, 'task', self.row)
        with self.assertRaisesRegex(ValueError, 'kanıt'):
            w.put(self.vault, 'task', dict(self.row, evidence='Kaynakta yer almayan sonuç'))

    def test_lesson_requires_target_hash_and_verification(self):
        proposal = dict(self.row, status='proposed')
        w.put(self.vault, 'lesson', proposal)
        with self.assertRaises(ValueError):
            w.put(self.vault, 'lesson', dict(proposal, status='verified', expected_version=1))
        w.put(self.vault, 'lesson', dict(proposal, status='verified', expected_version=1,
            target_path='kaynak.md', target_hash=h.statement_hash((self.vault / 'kaynak.md').read_text()),
            verification_path='kaynak.md', verification_evidence='İşin uygulaması tamamlandı, testler geçti.'))
        self.assertEqual('verified', w.latest(self.vault, 'lesson')['test']['status'])

    def verified_fixture(self, target='CLAUDE.md'):
        path=self.vault/target;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('Talimat değişikliği: önce kaynakları doğrula.')
        return dict(self.row,status='verified',target_path=target,target_hash=h.statement_hash(path.read_text()),
            verification_path='kaynak.md',verification_evidence=(self.vault/'kaynak.md').read_text(),verification_kind='test_result',observed_result='passed')

    def test_instruction_target_defaults_at_any_depth_and_windows_paths(self):
        names=('CLAUDE.md','claude.local.md','AGENTS.md','gemini.md','SKILL.md','.cursorrules','hooks.json',
               '.claude/settings.json','.codex/config.toml','.agents/config.json','skills/y/SKILL.md','hooks/pre.sh')
        for name in names:
            for prefix in ('','a/','a/b/'):
                with self.subTest(path=prefix+name):self.assertTrue(w.is_instruction_target(self.vault,prefix+name))
        self.assertTrue(w.is_instruction_target(self.vault,PureWindowsPath('X/.CLAUDE/settings.json')))
        self.assertTrue(w.is_instruction_target(self.vault,r'X\HOOKS\pre.sh'))
        for name in ('komuta/method.md','my-skills/file.md','hooks.md','AGENTS.md.bak',None):
            with self.subTest(path=name):self.assertFalse(w.is_instruction_target(self.vault,name))

    def test_instruction_extra_patterns_only_extend_defaults(self):
        path=self.vault/'komuta/talimat-dosyalari.json';path.parent.mkdir()
        path.write_text(json.dumps(dict(extra_patterns=['komuta/ajan-*.md',None,7],patterns=[])))
        self.assertTrue(w.is_instruction_target(self.vault,'komuta/AJAN-test.md'))
        self.assertTrue(w.is_instruction_target(self.vault,'CLAUDE.md'))
        self.assertFalse(w.is_instruction_target(self.vault,'komuta/method.md'))
        for raw in ('{','[]','null','{"extra_patterns": null}','{"extra_patterns": "*"}'):
            with self.subTest(raw=raw):
                path.write_text(raw)
                self.assertTrue(w.is_instruction_target(self.vault,'x/.codex/config.toml'))
                self.assertFalse(w.is_instruction_target(self.vault,'komuta/method.md'))
        path.write_bytes(b'\xff')
        self.assertTrue(w.is_instruction_target(self.vault,'a/AGENTS.md'))
        with patch.object(Path,'read_text',side_effect=PermissionError('unreadable fixture')):
            self.assertTrue(w.is_instruction_target(self.vault,'hooks/pre.sh'))

    def test_instruction_verified_put_requires_acceptance_for_either_path(self):
        row=self.verified_fixture();ordinary=self.verified_fixture('komuta/method.md')
        for data in (row,dict(ordinary,method_path='hooks/pre.sh'),dict(row,verification_kind='user_acceptance',observed_result='accepted'),
                     dict(row,verification_kind='user_acceptance',observed_result='rejected',acceptance_source=acceptance_fixture(self.vault))):
            with self.subTest(data=data),self.assertRaisesRegex(ValueError,'^talimat dosyası dersi kullanıcı kabulü gerektirir$'):
                w.put(self.vault,'lesson',data)
        self.assertEqual(w.latest(self.vault,'lesson'),{})
        self.assertEqual(w.put(self.vault,'lesson',ordinary)['status'],'verified')

    def test_instruction_verified_put_accepts_original_user_and_keeps_existing_gates(self):
        row=dict(self.verified_fixture(),verification_kind='user_acceptance',observed_result='accepted',acceptance_source=acceptance_fixture(self.vault))
        for changes in (dict(target_hash='wrong'),dict(verification_evidence='Alıntı yok'),dict(evidence='Kaynakta olmayan sonuç')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):w.put(self.vault,'lesson',dict(row,**changes))
        saved=w.put(self.vault,'lesson',row)
        self.assertEqual(saved['status'],'verified');self.assertEqual(saved['acceptance_source'],row['acceptance_source'])

    def test_instruction_acceptance_rejects_invalid_original_source(self):
        row=dict(self.verified_fixture(),verification_kind='user_acceptance',observed_result='accepted')
        for options in (dict(prior=4),dict(prior=6,role='assistant'),dict(completed=False),dict(quote='Bu oturumu kaydetme.'),dict(quote='Tamam.')):
            with self.subTest(options=options),self.assertRaisesRegex(ValueError,'talimat dosyası dersi kullanıcı kabulü gerektirir'):
                w.put(self.vault,'lesson',dict(row,acceptance_source=acceptance_fixture(self.vault,**options)))
        source=acceptance_fixture(self.vault)
        for bad in (None,{},dict(source,session_id='wrong'),dict(source,source_snapshot={}),dict(source,evidence_source={}),dict(source,evidence='Kullanıcının söylemediği bir kabul.')):
            with self.subTest(source=bad),self.assertRaisesRegex(ValueError,'talimat dosyası dersi kullanıcı kabulü gerektirir'):
                w.put(self.vault,'lesson',dict(row,acceptance_source=bad))
        path=self.vault/'acceptance.jsonl';path.write_text(path.read_text().replace('İstek','Değişen'))
        with self.assertRaisesRegex(ValueError,'talimat dosyası dersi kullanıcı kabulü gerektirir'):
            w.put(self.vault,'lesson',dict(row,acceptance_source=source))
        self.assertEqual(w.latest(self.vault,'lesson'),{})

    def test_instruction_acceptance_preserves_secret_and_session_exclusion_gates(self):
        source=acceptance_fixture(self.vault)
        row=dict(self.verified_fixture(),verification_kind='user_acceptance',observed_result='accepted',acceptance_source=source)
        with patch.object(h,'contains_secret',return_value=True),self.assertRaisesRegex(ValueError,'sır kaydedilemez'):
            w.put(self.vault,'lesson',row)
        h._append_jsonl(self.vault/h.EVENT_PATH,dict(event_type='session.policy',session_id='session',policy='do-not-record'))
        with self.assertRaisesRegex(ValueError,'talimat dosyası dersi kullanıcı kabulü gerektirir'):w.put(self.vault,'lesson',row)

    def test_extra_instruction_pattern_enforces_verified_put_gate(self):
        row=self.verified_fixture('komuta/ajan-work.md')
        (self.vault/'komuta/talimat-dosyalari.json').write_text('{"extra_patterns":["komuta/ajan-*.md"]}')
        with self.assertRaisesRegex(ValueError,'talimat dosyası dersi kullanıcı kabulü gerektirir'):w.put(self.vault,'lesson',row)


class Retrieval(unittest.TestCase):
    def test_expired_future_private_quarantined_are_excluded(self):
        base = dict(status='active', scope='user')
        self.assertTrue(h.retrievable(base, 'project:youtube'))
        for more in [dict(valid_to='2020-01-01'), dict(valid_from='2999-01-01'),
            dict(valid_to='bozuk'), dict(sensitivity='private'), dict(status='superseded'), dict(scope='project:other')]:
            self.assertFalse(h.retrievable(dict(base, **more), 'project:youtube'))

    def test_evaluation_reports_budget_loss_separately(self):
        from test_hafiza import FakeMem0
        c = FakeMem0([], search_results=[dict(id='one', memory='Uzun kaynaklı tercih metni',
            metadata=dict(memory_id='one', scope='user', status='active'))])
        r = h.evaluate_retrieval(c, [dict(id='budget', query='tercih', expected_memory_ids=['one'], char_budget=5)])
        self.assertEqual(1, r['passed']); self.assertEqual(0, r['context_passed'])
        self.assertFalse(h.evaluation_passes(r))


if __name__ == '__main__': unittest.main()
