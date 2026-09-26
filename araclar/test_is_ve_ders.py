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
        self.vault = Path(self.temp.name)
        (self.vault / 'kaynak.md').write_text('İşin uygulaması tamamlandı, testler geçti.')
        self.row = dict(id='test', title='Kaynaklı görev', status='active', next_step='Doğrula',
            source_path='kaynak.md', evidence='İşin uygulaması tamamlandı', actor='test',
            last_verified=dt.date.today().isoformat())

    def test_missing_ledger_preserves_existing_view(self):
        target = self.vault / 'zihin/açık-işler.md'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('Existing user work list\n')
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, 'defteri'):
            w.render(self.vault)
        self.assertEqual(before, target.read_bytes())

    def test_done_disappears_from_brief_but_history_remains(self):
        w.put(self.vault, 'task', self.row)
        self.assertEqual(1, len(w.brief(self.vault)))
        w.put(self.vault, 'task', dict(self.row, status='done', expected_version=1))
        self.assertEqual([], w.brief(self.vault))
        self.assertEqual(2, len(h.load_jsonl(self.vault / w.TASKS)))
        w.render(self.vault)
        self.assertIn('Kapanan işler', (self.vault / 'zihin/açık-işler.md').read_text())

    def test_stale_and_unconfirmed_not_presented_as_current(self):
        w.put(self.vault, 'task', dict(self.row, last_verified='2020-01-01'))
        self.assertEqual([], w.brief(self.vault))
        w.put(self.vault, 'task', dict(self.row, expected_version=1, status='needs_confirmation'))
        self.assertEqual([], w.brief(self.vault))

    def test_week_old_confirmation_is_not_current(self):
        eight = (w.dt.date.today() - w.dt.timedelta(days=8)).isoformat()
        six = (w.dt.date.today() - w.dt.timedelta(days=6)).isoformat()
        w.put(self.vault, 'task', dict(self.row, last_verified=six))
        self.assertEqual(1, len(w.brief(self.vault)))
        w.put(self.vault, 'task', dict(self.row, last_verified=eight, expected_version=1))
        self.assertEqual([], w.brief(self.vault))

    def test_task_source_change_invalidates_current_summary_even_with_quote(self):
        row=w.put(self.vault, 'task', self.row)
        self.assertIn('source_content_hash',row)
        source=self.vault/'kaynak.md';source.write_text(source.read_text()+' Ancak önceki iş iptal edildi.')
        self.assertEqual([],w.brief(self.vault))

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
