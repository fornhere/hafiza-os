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
 def test_budget_and_ambiguous_projects(self):
  self.assertEqual(build_task_package(self.v,'kapak',budget=1)['text'],'')
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project,dict(self.project,id='other')]}))
  p=build_task_package(self.v,'kapak');self.assertIsNone(p['project_id']);self.assertIn('ambiguous_project',p['omitted_reasons'])

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
