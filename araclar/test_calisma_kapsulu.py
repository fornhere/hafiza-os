import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hafiza as h
from gorev_baglam import build_task_package
from is_ve_ders import put
from codex_hafiza import hook


class Capsule(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.v=Path(self.temp.name).resolve();(self.v/'komuta').mkdir();(self.v/'zihin').mkdir()
        self.source=self.v/'current.md';self.source.write_text('Atlas CSV dışa aktarım. Sonraki adım CSV kontrolü.')
        (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[dict(id='atlas',aliases=['Atlas'],assets=[])]}))
    def task(self, ident='export', status='active'):
        return put(self.v,'task',dict(id=ident,title='CSV dışa aktarım '+ident,status=status,
            next_step='CSV kontrolü',project_id='atlas',source_path='current.md',evidence=self.source.read_text(),actor='test',last_verified=dt.date.today().isoformat()))
    def fact(self,ident='format',**extra):
        row=dict(memory_id=ident,kind='semantic',scope='project:atlas',subject_key=ident,
            statement='Atlas CSV biçimini kullanır.',status='active',source_path='current.md',source_content_hash=h.statement_hash(self.source.read_text()),source_anchor='format',source_hash=h.statement_hash('Atlas CSV biçimini kullanır.'),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
        row.update(extra);p=self.v/h.CATALOG_PATH
        with p.open('a') as f:f.write(json.dumps(row)+'\n')
        return row
    def package(self,query='Atlas devam',**kw):return build_task_package(self.v,query,**kw)
    def test_single_current_task_and_no_invented_output(self):
        self.task();self.fact();p=self.package();c=p['capsule']
        self.assertEqual(c['suggested_next_step'],'CSV kontrolü')
        self.assertIsNone(c['last_verified_output']);self.assertTrue(c['derived'])
        self.assertEqual(c['tasks'][0]['source_sha256'],h.statement_hash(self.source.read_text()).removeprefix('sha256:'))
        self.assertIn('Devam kartı',p['text']);self.assertIn('Bilgi kartı',p['text'])
    def test_blocked_or_multiple_tasks_never_choose_next_step(self):
        self.task(status='blocked');p=self.package();self.assertIsNone(p['capsule']['suggested_next_step'])
        self.assertIn('engelli',p['text'])
        self.task('second');p=self.package();self.assertTrue(p['capsule']['selection_required'])
        self.assertIsNone(p['capsule']['suggested_next_step'])
    def test_limits_and_dropped_tasks_do_not_create_single_choice(self):
        for i in range(5):self.task(str(i))
        for i in range(7):self.fact(str(i))
        p=self.package();c=p['capsule'];self.assertEqual(len(c['tasks']),3);self.assertEqual(len(c['facts']),5)
        self.assertEqual(c['available_task_count'],5);self.assertEqual(c['omitted_task_count'],2)
        self.assertIsNone(c['suggested_next_step']);self.assertIn('birden fazla',p['text'])
        self.assertNotIn('Bağlam kontrolü:',p['text'])
    def test_budget_never_returns_unselected_or_partial_cards(self):
        self.task();self.fact()
        for budget in (0,20,150,240,400):
            p=self.package(budget=budget);self.assertLessEqual(len(p['text']),budget)
            for card in p['capsule']['tasks']+p['capsule']['facts']:
                self.assertIn(card['id'],p['selected_ids']);self.assertIn(card['source_path'],p['text'])
                self.assertIn(card.get('statement',card.get('next_step')),p['text'])
    def test_source_change_removes_task_and_fact(self):
        self.task();self.fact();self.assertTrue(self.package()['capsule']['tasks'])
        self.source.write_text('Atlas CSV iptal; JSON kullanılacak.')
        p=self.package();self.assertEqual(p['capsule']['tasks'],[]);self.assertEqual(p['capsule']['facts'],[])
        self.assertIsNone(p['capsule']['suggested_next_step'])
    def test_legacy_exact_statement_is_not_a_reviewed_card(self):
        self.source.write_text('Atlas CSV biçimini kullanır.');self.fact(source_content_hash=None)
        p=self.package();self.assertEqual(p['capsule']['facts'],[])
        self.assertIn('Güncel kayıt:',p['text'])
    def test_private_and_superseded_cards_never_return(self):
        self.fact('private',sensitivity='private');self.fact('old',status='superseded')
        self.assertEqual(self.package()['capsule']['facts'],[])
    def test_normal_prompt_keeps_standard_view_and_no_network(self):
        self.task();self.fact()
        with patch.object(h.Mem0HttpClient,'search_memories',side_effect=AssertionError('network')):
            p=self.package('Atlas CSV hazırla')
        self.assertFalse(p['capsule']['enabled']);self.assertIn('Güncel kayıt:',p['text']);self.assertNotIn('Devam kartı',p['text'])
    def test_unrelated_topic_or_history_does_not_suggest_known_task(self):
        self.task()
        for q in ['Atlas güvenlik izinlerine devam','Atlas önceki karara devam']:
            self.assertIsNone(self.package(q)['capsule']['suggested_next_step'])
    def test_relevant_fact_cannot_make_unrelated_task_the_next_action(self):
        self.task()
        statement='Atlas güvenlik incelemesi ister.'
        self.fact(statement=statement,source_hash=h.statement_hash(statement))
        p=self.package('Atlas güvenlik devam')
        self.assertTrue(p['history']['topic_covered'])
        self.assertIsNone(p['capsule']['suggested_next_step'])

    def test_capsule_cannot_displace_asset_input_guard(self):
        from test_gorev_baglam import Package
        fixture=Package();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for budget in (600,610,650,800,1200):
            old=build_task_package(fixture.v,'kapak devam',budget=budget,view='standard')
            new=build_task_package(fixture.v,'kapak devam',budget=budget,view='resume')
            if 'input-check' in old['selected_ids']:
                self.assertIn('input-check',new['selected_ids'])

    def test_codex_receipt_counts_delivery_but_not_suppressed_repeat(self):
        import codex_hafiza as c
        method='Atlas CSV üretirken alanları kontrol et.'
        (self.v/'method.md').write_text(method)
        lesson=put(self.v,'lesson',dict(id='csv-method',title='CSV kontrolü',status='proposed',
            source_path='current.md',evidence=self.source.read_text(),actor='test',
            triggers=['CSV'],project_id='atlas',method_path='method.md',implementation_hash=h.statement_hash(method)))
        def event(turn):
            return hook(self.v,dict(session_id='lessons',turn_id=turn,hook_event_name='UserPromptSubmit',prompt='Atlas CSV üret'))
        def receipt():
            return json.loads((self.v/c.INBOX/'.state'/(c.key('lessons','state')+'.json')).read_text())
        with patch('codex_hafiza.opening_brief',return_value=''),patch('codex_hafiza.shared_reviewed_context',return_value=''):
            first=event('one')
            self.assertIn('Yöntem: method.md',first['hookSpecificOutput']['additionalContext'])
            self.assertEqual(receipt()['delivered_lessons'],[dict(id=lesson['id'],version=lesson['version'])])
            event('two');self.assertEqual(receipt()['delivered_lessons'],[])
            event('three');self.assertEqual(receipt()['delivered_lessons'],[])
            for n in range(4,10):
                event(str(n));self.assertEqual(receipt()['delivered_lessons'],[])
            event('ten');self.assertEqual(receipt()['delivered_lessons'],[dict(id=lesson['id'],version=lesson['version'])])
        self.assertFalse((self.v/'gelen-kutusu/lesson-outcomes.jsonl').exists())

    def test_claude_receipt_uses_final_text_after_filter_and_truncation(self):
        import client_hafiza as client
        from client_sessions import locked, policy_path
        segment='Ders: CSV kontrolü\nKoşul/adım: Üretirken alanları kontrol et.\nYöntem: method.md'
        lesson=dict(id='csv-method',version=3)
        package=dict(text=segment,selected_ids=[],project_id='atlas',package_id='synthetic',
            delivered_segments={'methods':segment},
            delivered_lessons=[lesson],delivered_lesson_segments={'csv-method':segment})
        with patch('client_hafiza.claude_task_package',return_value=package),patch('codex_hafiza.opening_brief',return_value=''),patch('codex_hafiza.latest_session_section',return_value=''),patch('client_hafiza.recall',return_value=''):
            first=client.context(self.v,'claude','lessons',None,{'prompt':'Atlas CSV üret'},'UserPromptSubmit')
            self.assertIn(segment,first)
            with locked(self.v) as (_,state):
                receipt=json.loads(policy_path(state,'claude','lessons').read_text())
            self.assertEqual(receipt['delivered_lessons'],[lesson])
            # Opening line dedup removes the entire unchanged lesson.
            client.context(self.v,'claude','lessons',None,{'prompt':'Atlas CSV yenile'},'UserPromptSubmit')
            with locked(self.v) as (_,state):
                self.assertEqual(json.loads(policy_path(state,'claude','lessons').read_text())['delivered_lessons'],[])
            with patch.object(client,'CONTEXT_BUDGET',50):
                client.context(self.v,'claude','lessons',None,{'prompt':'Atlas CSV hazırla'},'UserPromptSubmit')
            with locked(self.v) as (_,state):
                self.assertEqual(json.loads(policy_path(state,'claude','lessons').read_text())['delivered_lessons'],[])

    def test_hook_reads_fresh_cards_and_keeps_receipt_quiet(self):
        self.task();self.fact()
        def event(turn):return hook(self.v,dict(session_id='capsule',turn_id=turn,hook_event_name='UserPromptSubmit',prompt='Atlas devam'))
        first=event('one');self.assertIn('Devam kartı',first['hookSpecificOutput']['additionalContext'])
        self.source.write_text('Atlas CSV iptal edildi.')
        second=event('two');self.assertNotIn('Devam kartı',second.get('hookSpecificOutput',{}).get('additionalContext',''))
        self.assertEqual({},hook(self.v,dict(session_id='capsule',hook_event_name='Stop')))


if __name__=='__main__':unittest.main()
