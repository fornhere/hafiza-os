import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hafiza as h
from gorev_baglam import build_task_package, digest, rank_records, validate_inputs
from codex_hafiza import hook

class Package(unittest.TestCase):
 def asset_revision_fixture(self):
  import hafiza as h
  (self.v/'zihin').mkdir(exist_ok=True)
  rows=[]
  for ident,statement in [('old-asset','Kapak için eski sürüm tek aktif referanstır.'),('dignity','Kapak karakteri küçük düşürücü pozda gösterilmez.')]:
   rows.append(dict(memory_id=ident,kind='semantic',scope='user',subject_key=ident,statement=statement,status='active',source_path='approval.md',source_content_hash=h.statement_hash(self.source.read_text()),source_anchor=ident,source_hash=h.statement_hash(statement),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1))
  (self.v/'zihin/hafıza-kataloğu.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
  self.asset['replaces_memory_ids']=['old-asset']
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project]}))
  return [dict(metadata=dict(memory_id=r['memory_id'])) for r in rows]
 def test_exact_asset_revision_filters_local_and_remote_only_old_claim(self):
  from gorev_baglam import hydrate_remote
  remote=self.asset_revision_fixture()
  package=build_task_package(self.v,'kapak')
  self.assertNotIn('old-asset',package['selected_ids'])
  self.assertIn('dignity',package['selected_ids'])
  self.assertIn('mascot',package['selected_ids'])
  self.assertIn('old-asset:asset_revision_replaced',package['omitted_reasons'])
  self.assertEqual([r['metadata']['memory_id'] for r in hydrate_remote(self.v,remote)],['dignity'])
 def test_invalid_replacement_exposes_conflict_without_restoring_old_claim(self):
  from gorev_baglam import hydrate_remote
  remote=self.asset_revision_fixture();self.image.write_bytes(b'changed')
  package=build_task_package(self.v,'kapak')
  self.assertNotIn('old-asset',package['selected_ids'])
  self.assertIn('dignity',package['selected_ids'])
  self.assertIn('asset_revision_conflict',package['text'])
  with self.assertRaisesRegex(ValueError,'asset_revision_conflict'): hydrate_remote(self.v,remote)

 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.v=Path(self.tmp.name).resolve();(self.v/'komuta').mkdir()
  self.image=self.v/'approved.png';self.image.write_bytes(b'approved-image')
  self.source=self.v/'approval.md';self.source.write_text('Bu karakter tek onaylı kimlik referansıdır.')
  self.asset=dict(id='mascot',role='identity',path=str(self.image),allowed_roots=[str(self.v)],status='approved',sha256=digest(self.image),approval_source=str(self.source),approval_evidence=self.source.read_text())
  self.project=dict(id='youtube',aliases=['kapak'],assets=[self.asset],episode_sources=['episode.md'])
  (self.v/'episode.md').write_text('Son teslim: yalnız bir bölüm tamamlandı.')
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project]}))
 def test_hook_delivers_asset_but_invocation_must_include_it(self):
  result=hook(self.v,dict(hook_event_name='UserPromptSubmit',session_id='s',turn_id='t',prompt='kapak üret'))
  self.assertIn(str(self.image),result['hookSpecificOutput']['additionalContext'])
  with self.assertRaisesRegex(ValueError,'actual tool'): validate_inputs([self.asset],[])
  self.assertEqual(validate_inputs([self.asset],[str(self.image)]),[str(self.image)])
  with self.assertRaisesRegex(ValueError,'role'): validate_inputs([dict(self.asset,role='layout')],[str(self.image)])
 def test_changed_asset_or_approval_not_reused(self):
  self.image.write_bytes(b'changed')
  p=build_task_package(self.v,'kapak')
  self.assertEqual(p['assets'],[]);self.assertTrue(p['omitted_reasons'])
  self.assertNotIn(str(self.image),p['text'])
  self.asset['sha256']=digest(self.image);self.source.write_text('Changed approval')
  with self.assertRaisesRegex(ValueError,'evidence'): validate_inputs([self.asset],[str(self.image)])
 def test_irrelevant_prompt_and_selective_episodes(self):
  self.assertEqual(build_task_package(self.v,'OBS nasıl açılır')['text'],'')
  self.assertNotIn('Son teslim',build_task_package(self.v,'kapak üret')['text'])
  self.assertIn('Son teslim',build_task_package(self.v,'kapak devam')['text'])
 def test_repeated_segment_ids_preserve_all_delivered_text(self):
  self.project['roots']=[str(self.v/'first'),str(self.v/'second')]
  self.project['working_sources']=[dict(path=str(self.source),role=role,evidence_source='approval.md') for role in ('brief','reference')]
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project]}))
  package=build_task_package(self.v,'kapak',budget=10000)
  for ident,prefix in [('working-root','Çalışma kökü: '),('working-source','brief: ')]:
   segment=package['delivered_segments'][ident]
   if ident=='working-root':
    self.assertEqual(1,segment.count(prefix))
   else:
    self.assertIn('brief: ',segment);self.assertIn('reference: ',segment)
   self.assertIn(segment,package['text'])
  delivered=package['delivered_segments']
  self.assertEqual(len(package['text']),sum(map(len,delivered.values()))+len(delivered)-1)

 def test_budget_and_ambiguous_projects(self):
  self.assertEqual(build_task_package(self.v,'kapak',budget=1)['text'],'')
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project,dict(self.project,id='other')]}))
  p=build_task_package(self.v,'kapak');self.assertIsNone(p['project_id']);self.assertIn('ambiguous_project',p['omitted_reasons'])

 def test_lesson_diagnostics_exclude_changed_method_from_package(self):
  from is_ve_ders import put
  from hafiza import statement_hash
  (self.v/'method.md').write_text('Onaylı kapak yönteminin özgün içeriği.')
  row=dict(id='changed',title='Kapak yöntemi',status='proposed',source_path='approval.md',evidence=self.source.read_text(),actor='reviewer',triggers=['kapak'],method_path='method.md',implementation_hash=statement_hash((self.v/'method.md').read_text()))
  put(self.v,'lesson',row)
  (self.v/'method.md').write_text('İncelenmemiş yeni yöntem içeriği.')
  (self.v/'long.md').write_text('Bütçeye sığmayan geçerli yöntem. '*200)
  put(self.v,'lesson',dict(row,id='long',method_path='long.md',implementation_hash=statement_hash((self.v/'long.md').read_text())))
  package=build_task_package(self.v,'kapak',budget=5000)
  self.assertEqual(package['lessons'],dict(applied=[],diagnostics=[dict(id='changed',reason='method_changed'),dict(id='long',reason='budget')]))
  self.assertIn('lesson-check',package['selected_ids'])
  self.assertEqual(package['text'].count('Ders kontrolü:'),1)
  self.assertIn('2 ilgili ders dışlandı (değişmiş kaynak/yöntem/doğrulama: 1, bütçe: 1)',package['text'])
  self.assertNotIn('Onaylı kapak yönteminin özgün içeriği.',package['text'])
  self.assertNotIn((self.v/'method.md').read_text(),package['text'])
  self.assertNotIn('Bütçeye sığmayan geçerli yöntem.',package['text'])
  unrelated=build_task_package(self.v,'hava nasıl')
  self.assertEqual(unrelated['lessons'],dict(applied=[],diagnostics=[]))
  self.assertNotIn('Ders kontrolü',unrelated['text'])

 def test_lesson_check_yields_to_content_at_exact_budget(self):
  from is_ve_ders import put
  full=build_task_package(self.v,'kapak',history='always',budget=5000)
  budget=len(full['text'])
  row=dict(id='missing',title='Eksik kapak yöntemi',status='proposed',source_path='approval.md',evidence=self.source.read_text(),actor='reviewer',triggers=['kapak'])
  put(self.v,'lesson',row)
  package=build_task_package(self.v,'kapak',history='always',budget=budget)
  self.assertEqual(package['text'],full['text'])
  self.assertEqual(package['selected_ids'],full['selected_ids'])
  self.assertIn('lesson-check:budget',package['omitted_reasons'])
  self.assertEqual(package['lessons']['diagnostics'],[dict(id='missing',reason='method_missing')])
  self.assertLessEqual(len(package['text']),budget)

 def test_lesson_check_counts_instruction_targets_awaiting_acceptance(self):
  from is_ve_ders import put
  from hafiza import statement_hash
  method='Henüz kabul edilmemiş kapak talimatı.';(self.v/'CLAUDE.md').write_text(method)
  put(self.v,'lesson',dict(id='instruction',title='Talimat dersi',status='proposed',source_path='approval.md',evidence=self.source.read_text(),
      actor='reviewer',triggers=['kapak'],method_path='CLAUDE.md',implementation_hash=statement_hash(method)))
  package=build_task_package(self.v,'kapak',budget=5000)
  self.assertEqual(package['lessons'],dict(applied=[],diagnostics=[dict(id='instruction',reason='instruction_target_unaccepted')]))
  self.assertIn('kullanıcı kabulü bekleyen talimat: 1',package['text']);self.assertNotIn(method,package['text'])

 def test_hydrate_uses_canonical_text_and_rejects_obsolete(self):
  import hafiza as h
  from gorev_baglam import hydrate_remote
  (self.v/'zihin').mkdir()
  row=dict(memory_id='pref',kind='semantic',scope='user',subject_key='language',statement='Türkçe iletişim tercih edilir.',status='active',source_path='approval.md',source_content_hash=h.statement_hash(self.source.read_text()),source_anchor='language',source_hash=h.statement_hash('Türkçe iletişim tercih edilir.'),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
  path=self.v/'zihin/hafıza-kataloğu.jsonl';path.write_text(json.dumps(row)+'\n')
  result=hydrate_remote(self.v,[dict(memory='Wrong remote text',metadata=dict(memory_id='pref'))])
  self.assertEqual(result[0]['memory'],row['statement'])
  row['status']='superseded';path.write_text(json.dumps(row)+'\n')
  self.assertEqual(hydrate_remote(self.v,[dict(metadata=dict(memory_id='pref'))]),[])

 def test_context_cli_without_key_and_remote_failure_fallback(self):
  import contextlib, io
  from unittest.mock import patch
  import hafiza as h
  for extra in ([],['--remote']):
   out=io.StringIO()
   with patch.object(h,'load_api_key',side_effect=RuntimeError('no credentials')),contextlib.redirect_stdout(out):
    self.assertEqual(h.main(['--vault',str(self.v),'context','kapak']+extra),0)
   payload=json.loads(out.getvalue());self.assertEqual(payload['mode'],'local')
   self.assertEqual(payload['fallback_reason'],'RuntimeError' if extra else None)

 def test_turkish_routing_independent_phrases(self):
  from gorev_baglam import select_projects
  projects=[dict(id='cover',aliases=['kapak','thumbnail'],roots=['/tmp/cover']),dict(id='game',aliases=['ornekaltı'],roots=['/tmp/game']),dict(id='nova',aliases=['nova videosu'],roots=['/tmp/nova'])]
  cases={'kapağımızı yenileyelim':'cover','kapaklarımızı düzenle':'cover','Ornekaltına dönelim':'game',"Ornekaltı’nda ilerleyelim":'game','Novanın videosuna devam':'nova',"Nova’nın videosuna kapak üret":'nova','thumnail üret':'cover','kabak çorbası yap':None,'noval seyahat videosu':None,'dünkü iş':None,'o kapak':None}
  for query,expected in cases.items():
   with self.subTest(query=query):
    rows,_=select_projects(projects,query)
    self.assertEqual(rows[0]['id'] if len(rows)==1 else None,expected)
  rows,reason=select_projects(projects,'Ornekaltına devam',cwd='/tmp/cover')
  self.assertEqual([p['id'] for p in rows],['game']);self.assertEqual(reason,'explicit')
  rows,reason=select_projects(projects,'o kapak',cwd='/tmp/cover')
  self.assertEqual([p['id'] for p in rows],['cover']);self.assertEqual(reason,'cwd')
  rows,_=select_projects(projects,'Ornekaltı ile Novanın videosu')
  self.assertEqual(len(rows),2)

 def test_unresolved_reference_explained_without_unrelated_noise(self):
  for query in ('o kapağa devam','dünkü işi aç'):
   result=build_task_package(self.v,query)
   self.assertIsNone(result['project_id'])
   self.assertIn('kaynak seçmeden netleştir',result['text'])
  self.assertEqual(build_task_package(self.v,'kabak nasıl pişer')['text'],'')
  self.assertEqual(build_task_package(self.v,'OBS nasıl açılır')['text'],'')

 def test_named_project_keeps_identity_with_cover_workflow(self):
  cfg={'projects':[self.project,dict(id='game',aliases=['ornekaltı'],roots=['/tmp/game'],assets=[]),dict(id='nova',aliases=['nova videosu'],roots=[],assets=[dict(self.asset,id='selected',role='selected-cover')])]}
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps(cfg))
  for query,expected in [('Ornekaltı için kapak hazırla','game'),('Nova videosuna kapak hazırla','nova')]:
   package=build_task_package(self.v,query)
   self.assertEqual(package['project_id'],expected)
   self.assertEqual(package['workflow_ids'],['youtube'])
   self.assertEqual(validate_inputs(package['assets'],[str(self.image)]),[str(self.image)])
   if expected=='game': self.assertIn('/tmp/game',package['text'])
  package=build_task_package(self.v,'Ornekaltı devam')
  self.assertEqual(package['assets'],[]);self.assertEqual(package['workflow_ids'],[])


class ScopeContextPackageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        statement = 'Sunumlarda kısa cümle kullan.'
        (self.vault / 'source.md').write_text(statement, encoding='utf-8')
        self.row = dict(
            memory_id='presentation-style', kind='semantic', scope='project:alpha',
            subject_key='presentation.style', statement=statement, status='active',
            source_path='source.md', source_anchor='sunum',
            source_hash=h.statement_hash(statement), source_content_hash=h.statement_hash(statement),
            observed_at='2020-01-01', valid_from='2020-01-01', valid_to=None,
            confidence='explicit-user', sensitivity='normal', mem0_id=None,
            supersedes=None, reviewed_by='reviewer', schema_version=1,
        )
        h._write_jsonl(self.vault / h.CATALOG_PATH, [self.row])
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': [
            dict(id='alpha', aliases=['alpha']), dict(id='youtube', aliases=['kapak']),
        ]}), encoding='utf-8')

    def test_catalog_labels_and_header_for_current_records_and_cards(self):
        for scope in ('user', 'project:alpha'):
            h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(self.row, scope=scope)])
            for view, prefix in (('standard', 'Güncel kayıt: '), ('resume', 'Bilgi kartı: ')):
                with self.subTest(scope=scope, view=view):
                    result = build_task_package(self.vault, 'alpha sunum', view=view, history='never')
                    header = 'Aranan kapsam: user + project:alpha'
                    self.assertEqual(header, result['text'].splitlines()[0])
                    self.assertEqual('scope-header', result['selected_ids'][0])
                    self.assertEqual(header, result['delivered_segments']['scope-header'])
                    line = result['delivered_segments'][self.row['memory_id']]
                    self.assertTrue(line.startswith(prefix))
                    self.assertTrue(line.endswith(
                        '(kaynak: source.md; kapsam: '+scope+'; sınıf: incelenmiş kayıt)'))
                    self.assertEqual(len(result['text']), result['usage']['context_chars'])
                    self.assertEqual(len(result['selected_ids']), result['usage']['selected_count'])

    def test_scope_header_includes_searched_workflow(self):
        h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(self.row, scope='project:youtube')])
        result = build_task_package(self.vault, 'alpha kapak sunum')
        self.assertEqual(['youtube'], result['workflow_ids'])
        self.assertEqual('Aranan kapsam: user + project:alpha + project:youtube',
                         result['text'].splitlines()[0])
        self.assertIn('kapsam: project:youtube; sınıf: incelenmiş kayıt)', result['text'])

    def test_scope_header_budget_preserves_selected_record(self):
        h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(self.row, scope='user')])
        full = build_task_package(self.vault, 'sunum')
        self.assertEqual('Aranan kapsam: user', full['text'].splitlines()[0])
        size = len(full['text'])
        exact = build_task_package(self.vault, 'sunum', budget=size)
        self.assertEqual(full['text'], exact['text'])
        self.assertEqual(full['package_id'], exact['package_id'])
        smaller = build_task_package(self.vault, 'sunum', budget=size-1)
        self.assertEqual([self.row['memory_id']], smaller['selected_ids'])
        self.assertEqual(full['delivered_segments'][self.row['memory_id']], smaller['text'])
        self.assertIn('scope-header:budget', smaller['omitted_reasons'])
        self.assertNotIn('scope-header', smaller['delivered_segments'])
        self.assertLessEqual(len(smaller['text']), size-1)
        self.assertEqual(len(smaller['omitted_reasons']), smaller['usage']['omitted_count'])
        empty = build_task_package(self.vault, 'sunum', budget=len(smaller['text'])-1)
        self.assertEqual('', empty['text'])
        self.assertEqual([], empty['selected_ids'])
        self.assertNotIn('scope-header:budget', empty['omitted_reasons'])

    def test_no_selected_catalog_record_means_no_scope_header(self):
        for query, expected in (('OBS nasıl açılır', ''), ('alpha', 'Proje: alpha')):
            with self.subTest(query=query):
                result = build_task_package(self.vault, query)
                self.assertEqual(expected, result['text'])
                self.assertNotIn('scope-header', result['selected_ids'])
                self.assertNotIn('scope-header', result['delivered_segments'])


class SuppressedHistoryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': [
            dict(id='alpha', aliases=['alpha']), dict(id='youtube', aliases=['kapak']),
        ]}), encoding='utf-8')

    def promote(self, ident, statement, scope='user', supersedes=None):
        source_path = ident+'.md'
        (self.vault / source_path).write_text(statement, encoding='utf-8')
        candidate = h.add_candidate(
            self.vault, statement=statement, kind='semantic', scope=scope,
            subject_key='presentation.style', source_path=source_path, source_anchor='sunum',
            confidence='explicit-user', sensitivity='normal', proposed_by='test',
        )
        return h.promote_candidate(
            self.vault, candidate['candidate_id'], memory_id=ident,
            reviewed_by='test', supersedes=supersedes, apply=True,
        )['record']

    def supersede_chain(self, scope='user'):
        self.promote('old', 'Sunumlarda kısa cümle kullan.', scope)
        self.promote('new', 'Sunumlarda uzun cümle kullan.', scope, supersedes='old')
        old, new = h.load_catalog(self.vault)
        self.assertEqual('superseded', old['status'])
        self.assertEqual('old', new['supersedes'])
        return old, new

    def assert_suppressed(self, result, count):
        self.assertEqual(count, result['suppressed_count'])
        if count:
            notice = f'{count} eski kayıt bastırıldı; tarihçe için karar_gecmisi.'
            self.assertEqual(notice, result['delivered_segments']['suppressed-history'])
            self.assertEqual(1, result['text'].splitlines().count(notice))
        else:
            self.assertNotIn('eski kayıt bastırıldı', result['text'])
            self.assertNotIn('suppressed-history', result['selected_ids'])

    def test_superseded_chain_counts_without_delivering_old_statement(self):
        old, new = self.supersede_chain()
        for view in ('standard', 'resume'):
            with self.subTest(view=view):
                result = build_task_package(self.vault, 'sunum', view=view)
                self.assert_suppressed(result, 1)
                self.assertIn(new['statement'], result['text'])
                self.assertNotIn(old['statement'], json.dumps(result, ensure_ascii=False))
                self.assertEqual(['new'], result['summary']['record_ids'])
                self.assertLess(result['selected_ids'].index('new'),
                                result['selected_ids'].index('suppressed-history'))

    def test_expired_active_record_counts_at_utc_date_boundary(self):
        row = self.promote('expired', 'Sunumlarda kısa cümle kullan.')
        today = dt.datetime.now(dt.timezone.utc).date()
        cases = [((today-dt.timedelta(days=1)).isoformat(), 1),
                 (today.isoformat(), 1), (today.isoformat()+'T23:59:59Z', 1),
                 ((today+dt.timedelta(days=1)).isoformat(), 0),
                 ('bozuk', 0), ('2026-02-30', 0), (None, 0), ('', 0)]
        for valid_to, count in cases:
            with self.subTest(valid_to=valid_to):
                h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(row, valid_to=valid_to)])
                result = build_task_package(self.vault, 'sunum')
                self.assert_suppressed(result, count)
                if count:
                    self.assertNotIn(row['statement'], result['text'])
                    self.assertEqual('Aranan kapsam: user', result['text'].splitlines()[0])
                    self.assertEqual([], result['summary']['record_ids'])

    def test_unmatched_superseded_record_keeps_package_empty(self):
        self.supersede_chain()
        result = build_task_package(self.vault, 'OBS nasıl açılır')
        self.assert_suppressed(result, 0)
        self.assertEqual('', result['text'])

    def test_out_of_scope_superseded_record_not_counted(self):
        self.supersede_chain(scope='project:other')
        for query in ('sunum', 'alpha sunum'):
            with self.subTest(query=query):
                result = build_task_package(self.vault, query)
                self.assert_suppressed(result, 0)
                self.assertNotIn('scope-header', result['selected_ids'])

    def test_quarantined_deleted_and_sensitive_records_not_counted(self):
        old, _ = self.supersede_chain()
        for changes in (dict(status='quarantined'), dict(status='deleted'),
                        dict(sensitivity='private'), dict(sensitivity='secret'),
                        dict(status='active', sensitivity='private')):
            with self.subTest(changes=changes):
                h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(old, **changes)])
                result = build_task_package(self.vault, 'sunum')
                self.assert_suppressed(result, 0)
                self.assertEqual('', result['text'])

    def test_suppressed_only_package_includes_searched_scopes(self):
        old, _ = self.supersede_chain()
        for scope, query, header in (
            ('user', 'sunum', 'Aranan kapsam: user'),
            ('project:alpha', 'alpha sunum', 'Aranan kapsam: user + project:alpha'),
            ('project:youtube', 'alpha kapak sunum',
             'Aranan kapsam: user + project:alpha + project:youtube'),
        ):
            with self.subTest(scope=scope):
                row = dict(old, scope=scope)
                row.pop('sensitivity')
                h._write_jsonl(self.vault / h.CATALOG_PATH, [row])
                result = build_task_package(self.vault, query)
                self.assert_suppressed(result, 1)
                self.assertEqual(header, result['text'].splitlines()[0])
                self.assertEqual('scope-header', result['selected_ids'][0])
                self.assertEqual([], result['summary']['record_ids'])
                self.assertNotIn(old['statement'], result['text'])
                self.assertEqual(len(result['text']), result['usage']['context_chars'])
                self.assertEqual(len(result['selected_ids']), result['usage']['selected_count'])

    def test_decision_history_records_not_counted_twice(self):
        self.supersede_chain()
        result = build_task_package(self.vault, 'sunum karar geçmişi')
        self.assert_suppressed(result, 0)
        self.assertIn('decision-history', result['selected_ids'])
        self.assertEqual({'old', 'new'}, set(result['decision_history']['considered_ids']))
        entries = {entry['id']: entry for entry in result['decision_history']['entries']}
        self.assertFalse(entries['old']['current'])
        self.assertTrue(entries['new']['current'])

    def test_suppressed_notice_respects_budget_and_keeps_count(self):
        old, _ = self.supersede_chain()
        h._write_jsonl(self.vault / h.CATALOG_PATH, [old])
        full = build_task_package(self.vault, 'sunum')
        exact = build_task_package(self.vault, 'sunum', budget=len(full['text']))
        self.assertEqual(full['text'], exact['text'])
        notice = full['delivered_segments']['suppressed-history']
        smaller = build_task_package(self.vault, 'sunum', budget=len(notice))
        self.assert_suppressed(smaller, 1)
        self.assertEqual(notice, smaller['text'])
        self.assertIn('scope-header:budget', smaller['omitted_reasons'])
        empty = build_task_package(self.vault, 'sunum', budget=len(notice)-1)
        self.assertEqual(1, empty['suppressed_count'])
        self.assertEqual('', empty['text'])
        self.assertNotIn('scope-header', empty['selected_ids'])
        self.assertIn('suppressed-history:budget', empty['omitted_reasons'])

    def test_skip_memory_early_return_has_zero_suppressed_count(self):
        self.supersede_chain()
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(
            mode='on', retrieval_mode='rerank', rerank_gate_scope='all',
        )), encoding='utf-8')
        with patch('jev_retrieval.rerank_gate', return_value=(False, dict(degraded=False))):
            result = build_task_package(self.vault, 'sunum')
        self.assert_suppressed(result, 0)
        self.assertEqual('', result['text'])
        self.assertIn('gate', result['jev'])

    def test_memory_gate_skip_does_not_add_suppressed_notice(self):
        self.supersede_chain()
        (self.vault / 'komuta/jev.json').write_text(json.dumps(dict(
            mode='on', retrieval_mode='rerank', rerank_gate_scope='memory',
        )), encoding='utf-8')
        with patch('jev_retrieval.rerank_gate', return_value=(False, dict(degraded=False))):
            result = build_task_package(self.vault, 'sunum')
        self.assert_suppressed(result, 0)
        self.assertNotIn('eski kayıt bastırıldı', result['text'])

    def test_source_change_resets_suppressed_count(self):
        self.supersede_chain()
        def change_catalog(vault, query, rows, rank, scope):
            with (vault / h.CATALOG_PATH).open('a', encoding='utf-8') as stream:
                stream.write('\n')
            return rank(rows, query), None
        with patch('jev_retrieval.catalog', side_effect=change_catalog):
            result = build_task_package(self.vault, 'sunum')
        self.assert_suppressed(result, 0)
        self.assertIn('source_changed_during_package', result['omitted_reasons'])
        self.assertIn('kaynak değişti', result['text'])


class ArchivedProjects(unittest.TestCase):
    def test_archived_project_needs_exact_alias(self):
        from gorev_baglam import select_projects
        projects=[dict(id='eski',aliases=['eskiproje'],roots=['/tmp/eski'],status='arsiv'),
                  dict(id='yeni',aliases=['yeniproje'],roots=['/tmp'])]
        self.assertEqual(['yeni'],[p['id'] for p in select_projects(projects,'devam edelim',cwd='/tmp/eski/alt')[0]])
        self.assertEqual(['eski'],[p['id'] for p in select_projects(projects,'eskiproje notlarına bak')[0]])

    def test_archived_status_words_all_mean_archived(self):
        from gorev_baglam import select_projects
        for status in ('arsiv', 'arşiv', 'archived'):
            with self.subTest(status=status):
                projects=[dict(id='eski',aliases=['eskiproje'],roots=['/tmp/eski'],status=status),
                          dict(id='yeni',aliases=['yeniproje'],roots=['/tmp'])]
                self.assertEqual(['yeni'],[p['id'] for p in select_projects(projects,'devam edelim',cwd='/tmp/eski/alt')[0]])


class RankRelevance(unittest.TestCase):
    def rows(self):
        return [dict(memory_id=f'r{i}', statement=f'Deniz {topic} tercih eder.')
                for i, topic in enumerate(('kapakta büyük yazı', 'hızlı kurgu temposu',
                                           'Türkçe başlıklar', 'maskotu saygın poz'))]

    def test_shared_name_alone_does_not_select_every_record(self):
        query = 'görev bildirimi tamamlandı çıktı dosyası deniz arka plan komutu'
        self.assertEqual([], rank_records(self.rows(), query))

    def test_long_prompt_needs_two_distinguishing_terms(self):
        rows = self.rows()
        one = 'bu akşam uzun bir toplantı notunu toparla ve kurgu kısmını ayrıca belirt'
        self.assertEqual([], rank_records(rows, one))
        two = 'bu akşam uzun bir toplantı notunu toparla ve kurgu temposu kısmını belirt'
        self.assertEqual(['r1'], [r['memory_id'] for r in rank_records(rows, two)])

    def test_distinguishing_term_still_selects_its_record(self):
        ids = [r['memory_id'] for r in rank_records(self.rows(), 'kurgu temposu nasıl olmalı')]
        self.assertEqual(['r1'], ids)


class ProjectStatusTests(unittest.TestCase):
    setUp = ScopeContextPackageTests.setUp

    def task(self, ident='work', days=0, **extra):
        from is_ve_ders import put
        data = dict(id=ident, title='Orvant iş kartı', status='active', project_id='alpha',
                    source_path='source.md', evidence=(self.vault/'source.md').read_text(),
                    actor='test', next_step='Testleri doğrula', goal='Durumu görünür yap',
                    last_result='Düzeltme uygulandı', open_work='Regresyon kontrolü',
                    last_verified=(dt.date.today()-dt.timedelta(days=days)).isoformat())
        data.update(extra)
        return put(self.vault, 'task', data)

    def test_one_root_selects_cwd_or_primary_and_counts_alternatives(self):
        roots = [str(self.vault/str(i)) for i in range(31)]
        path = self.vault/'komuta/gorev-baglam.json'
        path.write_text(json.dumps({'projects':[dict(id='alpha',aliases=['alpha'],roots=roots)]}))
        for cwd, expected in ((None, roots[0]), (roots[17]+'/child', roots[17])):
            with self.subTest(cwd=cwd):
                result=build_task_package(self.vault,'alpha ne durumda',cwd=cwd)
                lines=[line for line in result['text'].splitlines() if line.startswith('Çalışma kökü:')]
                self.assertEqual(1,len(lines))
                self.assertIn(expected,lines[0])
                self.assertEqual(1,result['text'].count('canlı Git HEAD/status'))
                self.assertIn('+30 alternatif kök: komuta/gorev-baglam.json',result['text'])

    def test_status_card_precedes_seven_long_catalog_records_and_survives_budget(self):
        self.task()
        rows=[dict(self.row,memory_id='record'+str(i),statement='Alpha sunum tercihi '+('uzun '*100)) for i in range(7)]
        h._write_jsonl(self.vault/h.CATALOG_PATH,rows)
        with patch('jev_retrieval.catalog',side_effect=lambda v,q,r,rank,scope: (r,None)):
            for query in ('alpha sunum', 'alpha ne durumda'):
                result=build_task_package(self.vault,query,budget=1000,history='never')
                self.assertIn('work',result['selected_ids'])
                self.assertNotIn('work:budget',result['omitted_reasons'])
                self.assertEqual('work',result['selected_ids'][0] if result['selected_ids'][0]!='scope-header' else result['selected_ids'][1])
                for label in ('Hedef: Durumu görünür yap','Son sonuç: Düzeltme uygulandı',
                              'Açık iş/engel: Regresyon kontrolü','Sonraki adım: Testleri doğrula','Tarih: '+dt.date.today().isoformat()):
                    self.assertIn(label,result['text'])
                self.assertLessEqual(len(result['text']),1000)

    def test_old_task_has_dated_label_and_never_suggests_action(self):
        task=self.task(days=8)
        result=build_task_package(self.vault,'alpha ne durumda')
        self.assertIn('son bilinen durum ('+task['last_verified']+', teyit gerekli)',result['text'])
        self.assertIsNone(result['capsule']['suggested_next_step'])
        self.task('fresh')
        result=build_task_package(self.vault,'alpha ne durumda',budget=500)
        self.assertIn('fresh',result['selected_ids'])
        self.assertNotIn('work',result['selected_ids'])

    def test_newest_active_task_and_remaining_count(self):
        self.task('first');self.task('second')
        result=build_task_package(self.vault,'alpha devam')
        self.assertEqual(['second'],[t['id'] for t in result['capsule']['tasks']])
        self.assertIn('1 aktif iş daha',result['text'])
        self.assertTrue(result['capsule']['selection_required'])
        self.assertIsNone(result['capsule']['suggested_next_step'])

    def test_status_intents_and_destination_project(self):
        from gorev_baglam import continuation_request, select_projects
        for phrase in ('ne durumda','nerede kaldık','son durum','kaldığımız yer','devam'):
            self.assertTrue(continuation_request('alpha '+phrase))
            self.assertTrue(build_task_package(self.vault,'alpha '+phrase)['capsule']['enabled'])
        projects=[dict(id='serai',aliases=['Serai']),dict(id='orvant',aliases=['Orvant'])]
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':projects}))
        for query in ("Serai'yi bırakıp Orvant", 'Serai yerine Orvant', 'Serai’yi bırak Orvant ne durumda'):
            with self.subTest(query=query):
                self.assertEqual(['orvant'],[p['id'] for p in select_projects(projects,query)[0]])
                result=build_task_package(self.vault,query)
                self.assertEqual('orvant',result['project_id'])
                self.assertNotIn('ambiguous_project',result['omitted_reasons'])

    def test_session_close_report_card_reaches_short_status_prompt(self):
        from is_ve_ders import put_project_state
        quote = (self.vault/'source.md').read_text()
        state = dict(project_id='alpha', outcome='Kök satırları teke indi', rationale='Bağlam gürültüsü',
                     open_items=['Ölçüm setini koş'], next_step='Taban ölçümle karşılaştır',
                     evidence=dict(line=1, line_sha256='0'*64, quote=quote))
        put_project_state(self.vault, state, 'r1', 'source.md', dict(client='claude', session='s'))
        result = build_task_package(self.vault, 'alpha ne durumda')
        self.assertIn('project-state:alpha', result['selected_ids'])
        for label in ('oturum kapanış bildirimi (', 'doğrulanmış sonuç değil', 'Son sonuç: Kök satırları teke indi',
                      'Açık iş/engel: Ölçüm setini koş', 'Sonraki adım: Taban ölçümle karşılaştır'):
            self.assertIn(label, result['text'])
        self.assertIsNone(result['capsule']['suggested_next_step'])
