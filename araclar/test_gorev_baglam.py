import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hafiza as h
from gorev_baglam import build_task_package, digest, rank_records, validate_inputs
from codex_hafiza import hook

class SubtaskFocus(unittest.TestCase):
 def setUp(self):
  from gorev_baglam import _subfolders
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.v=Path(self.tmp.name).resolve();(self.v/'komuta').mkdir()
  self.root=self.v/'videolar';self.root.mkdir()
  for name in ('atlas-mercek','delta-sponsor','nova-kesit'): (self.root/name).mkdir()
  self.project=dict(id='proj-a',aliases=['videolar'],roots=[str(self.root)])
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project]}))
  _subfolders.cache_clear();self.addCleanup(_subfolders.cache_clear)

 def tasks(self):
  return [dict(id='foreign',title='Delta sponsor videosu',next_step='Kapak düzenle'),
          dict(id='unrelated',title='Önceki prova videosu',next_step='Ses düzenle'),
          dict(id='plan',title='Genel yayın sırası',next_step='Atlas ve mercek videosunu araştır'),
          dict(id='focused',title='Atlas ve mercek videosu',next_step='Kapak düzenle')]

 def test_title_beats_plan_and_siblings_are_removed(self):
  from gorev_baglam import subtask_focus
  tasks,focus,omitted=subtask_focus(self.tasks(),self.project,self.root/'atlas-mercek/arastirma')
  self.assertEqual([t['id'] for t in tasks],['plan','focused'])
  self.assertLess(focus['focused'],focus['plan'])
  self.assertEqual(omitted,['foreign:subtask_focus','unrelated:subtask_focus'])

 def test_root_outside_and_no_cwd_preserve_cards_without_scan(self):
  from gorev_baglam import subtask_focus
  tasks=self.tasks()
  with patch('gorev_baglam.os.scandir') as scan:
   for cwd in (self.root,self.v/'outside',None):
    self.assertEqual(subtask_focus(tasks,self.project,cwd),(tasks,{},[]))
   scan.assert_not_called()

 def test_temporary_cwd_components_preserve_cards_without_scan(self):
  from gorev_baglam import subtask_focus
  tasks=self.tasks()
  with patch('gorev_baglam.os.scandir') as scan:
   for name in ('.atlas-mercek','_atlas-mercek','tmp','temp','cache','scratch',
                'temporary','scratchpad','tmp-atlas','cache_mercek'):
    for relative in (name,name+'/atlas-mercek','atlas-mercek/'+name+'/ses'):
     with self.subTest(cwd=relative):
      self.assertEqual(subtask_focus(tasks,self.project,self.root/relative),(tasks,{},[]))
   scan.assert_not_called()

 def test_temporary_cwd_package_preserves_root_delivery(self):
  self.write_tasks(self.tasks())
  root=build_task_package(self.v,'devam',cwd=self.root,budget=2000,history='never')
  for relative in ('.atlas-mercek','_atlas-mercek','tmp/atlas-mercek',
                   'atlas-mercek/cache','scratch'):
   with self.subTest(cwd=relative):
    package=build_task_package(self.v,'devam',cwd=self.root/relative,budget=2000,history='never')
    self.assertEqual(package['project_id'],root['project_id'])
    self.assertEqual(package['selected_ids'],root['selected_ids'])
    self.assertEqual(package['omitted_reasons'],root['omitted_reasons'])

 def test_temporary_siblings_cannot_exclude_cards(self):
  from gorev_baglam import subtask_focus
  for name in ('.delta-sponsor','_delta-sponsor','tmp','temp','cache','scratch'):
   (self.root/name).mkdir()
  tasks=[dict(id='neutral',title='Tmp temp cache scratch',next_step='Ses düzenle')]
  self.assertEqual(subtask_focus(tasks,self.project,self.root/'new-work'),(tasks,{},[]))

 def test_sibling_inflections_in_title_next_step_and_evidence(self):
  from gorev_baglam import subtask_focus
  for suffix in ('sponsor','sponsoru','sponsorun','sponsoruna'):
   for field in ('title','next_step','evidence'):
    with self.subTest(suffix=suffix,field=field):
     foreign=dict(id='foreign',title='Genel durum',next_step='Ses düzenle')
     foreign[field]='Delta '+suffix
     for cwd in ('atlas-mercek','new-work'):
      kept,_,omitted=subtask_focus([foreign],self.project,self.root/cwd)
      self.assertEqual(kept,[]);self.assertEqual(omitted,['foreign:subtask_focus'])
     foreign['evidence']=foreign.get('evidence','')+' Atlas merceği'
     self.assertIn(foreign,subtask_focus([foreign],self.project,self.root/'atlas-mercek')[0])

 def test_sibling_inflections_require_every_distinct_name_word(self):
  from gorev_baglam import subtask_focus
  tasks=[dict(id='partial',title='Sponsoruna sponsorun sponsoru',next_step='Ses düzenle'),
         dict(id='lookalike',title='Delta sponsorluk',next_step='Ses düzenle')]
  self.assertEqual(subtask_focus(tasks,self.project,self.root/'new-work'),(tasks,{},[]))

 def test_no_focus_only_strong_sibling_is_removed(self):
  from gorev_baglam import subtask_focus
  tasks=[dict(id='partial',title='Delta videosu',next_step='Kapak düzenle'),self.tasks()[0],self.tasks()[1]]
  kept,focus,omitted=subtask_focus(tasks,self.project,self.root/'new-work')
  self.assertEqual([t['id'] for t in kept],['partial','unrelated'])
  self.assertEqual(focus,{})
  self.assertEqual(omitted,['foreign:subtask_focus'])

 def test_underscore_and_second_component_break_ties(self):
  from gorev_baglam import subtask_focus
  tasks=[dict(id='cover',title='Atlas mercek kapak',next_step='Renk düzenle'),
         dict(id='audio',title='Atlas mercek ses',next_step='Ses düzenle')]
  kept,focus,_=subtask_focus(tasks,self.project,self.root/'atlas_mercek/ses/v4')
  self.assertEqual(kept,tasks);self.assertLess(focus['audio'],focus['cover'])

 def test_sibling_scan_is_cached_and_missing_root_is_safe(self):
  import gorev_baglam as g
  scan=g.os.scandir
  with patch.object(g.time,'monotonic',return_value=60),patch.object(g.os,'scandir',wraps=scan) as mock:
   for _ in range(3): g.subtask_focus(self.tasks(),self.project,self.root/'atlas-mercek')
   self.assertEqual(mock.call_count,1)
  with patch.object(g.time,'monotonic',return_value=120),patch.object(g.os,'scandir',side_effect=OSError):
   self.assertEqual(g.subtask_focus(self.tasks(),self.project,self.root/'atlas-mercek')[0],self.tasks()[2:])

 def test_deepest_configured_root_has_no_subtask_at_its_root(self):
  from gorev_baglam import subtask_focus
  project=dict(self.project,roots=[str(self.root),str(self.root/'atlas-mercek')])
  tasks=self.tasks()
  self.assertEqual(subtask_focus(tasks,project,self.root/'atlas-mercek'),(tasks,{},[]))

 def write_tasks(self,tasks):
  from is_ve_ders import put
  for task in reversed(tasks):
   source=task['id']+'.md';(self.v/source).write_text('Sentetik iş kanıtı.')
   data=dict(task,project_id='proj-a',status='active',source_path=source,
       evidence='Sentetik iş kanıtı.',actor='reviewer')
   data.setdefault('last_verified',dt.date.today().isoformat())
   put(self.v,'task',data)

 def test_query_orders_cards_with_equal_folder_evidence(self):
  self.write_tasks([dict(id='cover',title='Atlas mercek kapak',next_step='Renk düzenle'),
                    dict(id='audio',title='Atlas mercek ses',next_step='Ses düzenle')])
  package=build_task_package(self.v,'ses',cwd=self.root/'atlas-mercek',budget=2000,history='never')
  self.assertEqual([i for i in package['selected_ids'] if i in ('cover','audio')],['audio','cover'])

 def test_focus_never_delivers_changed_source(self):
  self.write_tasks(self.tasks())
  (self.v/'focused.md').write_text('Değişmiş kaynak.')
  package=build_task_package(self.v,'devam',cwd=self.root/'atlas-mercek',budget=2000,history='never')
  self.assertNotIn('focused',package['selected_ids'])
  self.assertIn('focused:evidence_missing',package['omitted_reasons'])
  self.assertNotIn('foreign',package['selected_ids'])

 def test_package_focus_first_and_root_keeps_previous_order(self):
  self.write_tasks(self.tasks())
  root=build_task_package(self.v,'devam',cwd=self.root,budget=2000,history='never')
  self.assertEqual([i for i in root['selected_ids'] if i in {t['id'] for t in self.tasks()}],
                   ['foreign','unrelated','plan'])
  for cwd in ('atlas-mercek','atlas-mercek/arastirma','atlas-mercek/motion/b1','atlas-mercek/paket/thumbnail/v4'):
   package=build_task_package(self.v,'devam',cwd=self.root/cwd,budget=2000,history='never')
   ids=[i for i in package['selected_ids'] if i in {t['id'] for t in self.tasks()}]
   self.assertEqual(package['project_id'],'proj-a')
   self.assertEqual(ids,['focused','plan'])
   self.assertNotIn('Bağlam kontrolü',package['text'])

 def test_project_state_and_legacy_session_project_name_survive_focus(self):
  from gorev_baglam import subtask_focus
  states=[dict(id='project-state:proj-a',title='Proj A oturum durumu',next_step='Tam sürümün ses kabulü'),
          dict(id='proj-a',title='Son durum',next_step='Tam sürümü incele',transcript_source={'session':'test'}),
          dict(id='legacy',title='Proj A',next_step='Ses kabulü',assertion_kind='assistant_report')]
  plain=dict(id='plain',title='Proj A',next_step='Eski genel iş')
  kept,focus,omitted=subtask_focus(self.tasks()+states+[plain],self.project,self.root/'atlas-mercek')
  for state in states:
   self.assertIn(state,kept);self.assertIn(state['id'],focus)
  self.assertNotIn(plain,kept)
  self.assertIn('plain:subtask_focus',omitted)

 def test_project_state_sibling_evidence_can_exclude_but_focus_evidence_protects(self):
  from gorev_baglam import subtask_focus
  for field in ('next_step','evidence'):
   state=dict(id='project-state:proj-a',title='Proj A oturum durumu',next_step='Tam sürümün ses kabulü')
   state[field]='delta-sponsor dizininde çalış'
   kept,_,omitted=subtask_focus(self.tasks()+[state],self.project,self.root/'atlas-mercek')
   self.assertNotIn(state,kept);self.assertIn(state['id']+':subtask_focus',omitted)
   state[field]+='; atlas-mercek dizini de ilgili'
   self.assertIn(state,subtask_focus(self.tasks()+[state],self.project,self.root/'atlas-mercek')[0])

 def test_fresh_session_state_precedes_old_focused_demo_in_package(self):
  today=dt.date.today()
  self.write_tasks([dict(id='demo',title='Atlas mercek prova',next_step='Demoyu incele',
                        last_verified=(today-dt.timedelta(days=4)).isoformat()),
                    dict(id='project-state:proj-a',title='Proj A oturum durumu',
                         next_step='Tam sürümün ses kabulünü incele',last_verified=today.isoformat())])
  package=build_task_package(self.v,'prova',cwd=self.root/'atlas-mercek',budget=2000,history='never')
  self.assertEqual([i for i in package['selected_ids'] if i in ('demo','project-state:proj-a')],
                   ['project-state:proj-a','demo'])

 def test_fresh_partial_focus_precedes_old_title_and_query_match(self):
  today=dt.date.today()
  self.write_tasks([dict(id='old',title='Atlas mercek prova',next_step='Demoyu incele',
                        last_verified=(today-dt.timedelta(days=5)).isoformat()),
                    dict(id='new',title='Yeni ses kabulü',next_step='Atlas sürümünü incele',
                         last_verified=today.isoformat())])
  package=build_task_package(self.v,'prova',cwd=self.root/'atlas-mercek',budget=2000,history='never')
  self.assertEqual([i for i in package['selected_ids'] if i in ('old','new')],['new','old'])

 def test_freshness_fallback_invalid_dates_and_no_focus(self):
  from gorev_baglam import _task_focus_order
  focus={'new':(0,-1,0),'old':(-2,-2,0)}
  old=dict(id='old',last_verified='2026-01-01',updated_at='2026-01-09')
  for fields in (dict(updated_at='2026-01-05T10:00:00Z'),
                 dict(last_verified='invalid',content_updated_at='2026-01-05T10:00:00Z',updated_at='2026-01-01')):
   new=dict(id='new',**fields)
   self.assertLess(_task_focus_order(new,focus),_task_focus_order(old,focus))
   self.assertEqual(_task_focus_order(new,{}),())
  self.assertGreater(_task_focus_order(dict(id='new',last_verified=None,updated_at='invalid'),focus),
                     _task_focus_order(old,focus))

class Package(unittest.TestCase):
 def test_expansion_requires_current_anchor_and_preserves_order(self):
  rows=[dict(memory_id='direct',statement='Kapak renk tipografi'),
        dict(memory_id='related',statement='Kapak kimlik hareket'),
        dict(memory_id='noise',statement='Kimlik hareket kompozisyon')]
  query='Kapak renk tipografiyi hazırlayalım'
  base=rank_records(rows,query)
  expanded=rank_records(rows,query,expansion='kimlik hareket kompozisyon')
  self.assertEqual([r['memory_id'] for r in base],['direct'])
  self.assertEqual([r['memory_id'] for r in expanded],['direct','related'])
  self.assertEqual(rank_records(rows,'devam',expansion='kimlik hareket kompozisyon'),[])

 def test_expansion_cannot_anchor_on_discourse_words(self):
  rows=[dict(memory_id='noise',statement='Son cevap önemli ve ilgili görsel kimliği koru.'),
        dict(memory_id='relevant',statement='Kapak kimliği ve hareket referansları koru.')]
  expanded=rank_records(rows,'Kapak için son önemli kararı yap bakalım',
                        expansion='kimlik hareket referans')
  self.assertEqual([r['memory_id'] for r in expanded],['relevant'])

 def test_changed_task_cannot_seed_expansion_graph(self):
  from is_ve_ders import put
  import konu_sentezi
  statement='İş kartının onaylı kaynak metni ve kanıtı.'
  (self.v/'task.md').write_text(statement)
  put(self.v,'task',dict(id='task',title='Kapak düzenleme',status='active',
      project_id='youtube',next_step='Kimlik ve hareket düzenle',source_path='task.md',
      evidence=statement,actor='reviewer'))
  (self.v/'bilgi').mkdir()
  (self.v/'task.md').write_text('Changed [[bilgi/unreviewed]]')
  with patch.object(konu_sentezi,'retrieve',return_value=dict(text='',records=[],source_versions={})) as reader:
   build_task_package(self.v,'kapak')
  self.assertEqual(reader.call_args.kwargs['linked_paths'],[])
  self.assertNotIn('Kimlik ve hareket düzenle',reader.call_args.kwargs['expansion'])

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

 def test_duplicate_closures_keep_newest_and_different_next_steps_survive(self):
  from client_sessions import unique_states
  base=dict(project_id='youtube',assertion_kind='assistant_report',
      assistant_report=dict(outcome='Yayın düzenlemesi kaynak kontrolü ve kabul incelemesi tamamlandı.'),
      next_step='Yayın kabulünü kontrol et.')
  old=dict(base,id='old',updated_at='2026-10-01')
  new=dict(base,id='new',updated_at='2026-10-02')
  groups=unique_states([old,new])
  self.assertEqual([[c['id'] for c in g] for g in groups],[['new','old']])
  different=dict(new,next_step='Ses sürücüsünü yükle.')
  self.assertEqual(len(unique_states([old,different])),2)

 def state_fixture(self, different=False, changed=False):
  from is_ve_ders import put
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project]}))
  statement='Sentetik kaynak durumu ve doğrulama kanıtı.'
  for ident in ('work', 'project-state:youtube'):
   (self.v/(ident.replace(':','-')+'.md')).write_text(statement)
  common=dict(project_id='youtube', transcript_source=dict(client='claude',session='fixture-session'), next_step='Yayın kabulünü kontrol et.', actor='reviewer', evidence=statement)
  put(self.v,'task',dict(common,id='work',title='Yayın iş durumu',status='active',
      last_verified=dt.date.today().isoformat(),last_result='Yayın düzenlemesi tamamlandı.',
      open_work='Ek kapak kontrolü bekleniyor.',source_path='work.md'))
  if different: common['next_step']='Mikrofon sürücüsünü yükle.'
  put(self.v,'task',dict(common,id='project-state:youtube',title='Youtube oturum kapanışı',status='needs_confirmation',
      source_path='project-state-youtube.md',assertion_kind='assistant_report',
      assistant_report=dict(outcome='Yayın düzenlemesi tamamlandı.',open_items=[]),
      ))
  if changed: (self.v/'project-state-youtube.md').write_text('Değişmiş ve onaysız kaynak')

 def test_same_state_report_and_work_are_one_newest_card(self):
  self.state_fixture()
  package=build_task_package(self.v,'kapak durumu',budget=5000)
  self.assertEqual(package['text'].count('İş durum kartı'),1)
  self.assertIn('Youtube oturum kapanışı',package['text'])
  self.assertIn('Ek kapak kontrolü bekleniyor.',package['text'])
  self.assertIn('work',package['selected_ids'])
  self.assertIn('project-state:youtube',package['selected_ids'])

 def test_different_jobs_are_not_collapsed(self):
  self.state_fixture(different=True)
  package=build_task_package(self.v,'kapak durumu',budget=5000)
  self.assertEqual(package['text'].count('İş durum kartı'),2)

 def test_changed_newer_source_cannot_displace_work(self):
  self.state_fixture(changed=True)
  package=build_task_package(self.v,'kapak durumu',budget=5000)
  self.assertIn('Yayın iş durumu',package['text'])
  self.assertNotIn('Youtube oturum kapanışı',package['text'])

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

 def profile_fixture(self):
  (self.v/'zihin').mkdir(exist_ok=True)
  rows=[]
  for ident,scope,source,statement in [
      ('core','project:youtube','projeler/youtube/DURUM.md','Birinci ağızdan anlatmayı tercih eder.'),
      ('sibling','project:other','projeler/other/DURUM.md','Farklı bir anlatımı tercih eder.'),
      ('episode','project:youtube','gelen-kutusu/episode.md','Yeni bir anlatımı tercih eder.')]:
   path=self.v/source;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(statement)
   rows.append(dict(memory_id=ident,kind='semantic',scope=scope,subject_key=ident,
       statement=statement,status='active',source_path=source,
       source_content_hash=h.statement_hash(statement),source_anchor=ident,
       source_hash=h.statement_hash(statement),observed_at='2026-01-01',
       valid_from='2026-01-01',valid_to=None,confidence='explicit-user',
       sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1))
  (self.v/'zihin/hafıza-kataloğu.jsonl').write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
  return rows

 def test_scope_profile_requires_active_domain_but_not_direct_query_overlap(self):
  self.profile_fixture()
  self.assertNotIn('core',build_task_package(self.v,'kapak')['selected_ids'])
  self.assertNotIn('core',build_task_package(self.v,'kapak devam')['selected_ids'])
  package=build_task_package(self.v,'kapak için video senaryosu')
  self.assertIn('core',package['selected_ids'])
  self.assertIn('Kapsam profili: Birinci ağızdan anlatmayı tercih eder.',package['text'])
  self.assertNotIn('sibling',package['selected_ids'])
  self.assertNotIn('episode',package['selected_ids'])
  self.assertIn('projeler/youtube/DURUM.md',package['source_versions'])
  self.assertEqual(build_task_package(self.v,'hava nasıl')['text'],'')
  self.assertNotIn('core',build_task_package(self.v,'kapak',budget=100)['selected_ids'])

 def test_scope_profile_rejects_changed_private_expired_and_ambiguous_rows(self):
  rows=self.profile_fixture()
  catalog=self.v/'zihin/hafıza-kataloğu.jsonl'
  for field,value in [('sensitivity','private'),('valid_to','2026-01-02'),('status','superseded')]:
   altered=[dict(r,**{field:value}) if r['memory_id']=='core' else r for r in rows]
   catalog.write_text('\n'.join(json.dumps(r) for r in altered)+'\n')
   self.assertNotIn('core',build_task_package(self.v,'kapak')['selected_ids'])
  catalog.write_text('\n'.join(json.dumps(r) for r in rows)+'\n')
  (self.v/'projeler/youtube/DURUM.md').write_text('İncelenmemiş yeni ifade.')
  self.assertNotIn('core',build_task_package(self.v,'kapak')['selected_ids'])
  (self.v/'projeler/youtube/DURUM.md').write_text(rows[0]['statement'])
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[self.project,dict(self.project,id='other')]}))
  self.assertNotIn('Kapsam profili:',build_task_package(self.v,'kapak')['text'])

 def test_lesson_diagnostics_exclude_changed_method_from_package(self):
  from is_ve_ders import put
  from hafiza import statement_hash
  (self.v/'method.md').write_text('Onaylı kapak yönteminin özgün içeriği.')
  row=dict(id='changed',title='Kapak yöntemi',status='proposed',source_path='approval.md',evidence=self.source.read_text(),actor='reviewer',triggers=['kapak'],method_path='method.md',implementation_hash=statement_hash((self.v/'method.md').read_text()))
  put(self.v,'lesson',row)
  (self.v/'method.md').write_text('İncelenmemiş yeni yöntem içeriği.')
  (self.v/'long.md').write_text('Bütçeye sığmayan geçerli yöntem '*200)
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

 def test_short_lessons_have_reserved_budget_and_versioned_delivery(self):
  from is_ve_ders import put
  from hafiza import statement_hash
  method='Kapak üretirken referans rollerini ayrı seç. '+('Uzun açıklama. '*250)
  (self.v/'method.md').write_text(method)
  row=put(self.v,'lesson',dict(id='short',title='Referans rolleri',status='proposed',
      source_path='approval.md',evidence=self.source.read_text(),actor='reviewer',
      triggers=['kapak'],project_id='youtube',method_path='method.md',implementation_hash=statement_hash(method)))
  package=build_task_package(self.v,'kapak',budget=500)
  self.assertEqual(package['delivered_lessons'],[dict(id='short',version=row['version'])])
  self.assertEqual(package['lessons']['applied'],package['delivered_lessons'])
  segment=package['delivered_lesson_segments']['short']
  self.assertIn(segment,package['text']);self.assertLessEqual(len(segment),300)
  self.assertIn('Kapak üretirken referans rollerini ayrı seç.',segment)
  self.assertIn('Yöntem: method.md',segment)
  self.assertIn('method.md',package['source_versions'])
  self.assertLessEqual(len(package['text']),500)
  small=build_task_package(self.v,'kapak',budget=20)
  self.assertEqual(small['delivered_lessons'],[])
  self.assertIn(dict(id='short',reason='budget'),small['lessons']['diagnostics'])
  (self.v/'method.md').write_text('Değişmiş yöntem.')
  self.assertEqual(build_task_package(self.v,'kapak')['delivered_lessons'],[])

 def test_lessons_share_small_budget_and_exclusions_identify_each_lesson(self):
  from is_ve_ders import put
  from hafiza import statement_hash
  method='Kapak üretirken kaynakları aç ve onaylı referans rolleriyle karşılaştır.'
  (self.v/'method.md').write_text(method)
  for ident in ('a','b','c'):
   put(self.v,'lesson',dict(id=ident,title='Referans rolleri '+ident,status='proposed',
       source_path='approval.md',evidence=self.source.read_text(),actor='reviewer',
       triggers=['kapak'],method_path='method.md',implementation_hash=statement_hash(method)))
  package=build_task_package(self.v,'kapak',budget=2000)
  delivered={r['id'] for r in package['delivered_lessons']}
  excluded={r['id'] for r in package['lessons']['diagnostics'] if r['reason']=='budget'}
  self.assertTrue(delivered);self.assertTrue(excluded)
  self.assertEqual(delivered|excluded,{'a','b','c'})
  self.assertLessEqual(len(package['delivered_segments']['methods']),300)
  self.assertFalse(delivered&excluded)

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
        self.vault = Path(tmp.name).resolve()
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
        self.vault = Path(tmp.name).resolve()
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

    def test_invalid_cards_expose_scoped_omission_reasons(self):
        from is_ve_ders import TASKS
        for changes, reason in ((dict(source_path='missing.md'), 'source_missing'),
                                (dict(evidence='Kaynakta olmayan sonuç'), 'evidence_missing'),
                                (dict(source_content_hash='wrong'), 'source_changed')):
            with self.subTest(reason=reason):
                task = self.task()
                h._write_jsonl(self.vault/TASKS, [dict(task, **changes),
                    dict(task, id='foreign', project_id='beta', **changes)])
                result = build_task_package(self.vault, 'alpha ne durumda')
                self.assertIn('work:'+reason, result['omitted_reasons'])
                self.assertNotIn('foreign:'+reason, result['omitted_reasons'])
                self.assertNotIn('work', result['selected_ids'])
                h._write_jsonl(self.vault/TASKS, [])

    def test_metadata_version_keeps_history_date_and_card_order(self):
        from is_ve_ders import TASKS, put
        first = self.task(last_verified=None)
        second = self.task('second', last_verified=None)
        metadata = put(self.vault, 'task', dict(first, project_id=None, expected_version=1))
        h._write_jsonl(self.vault/TASKS, [dict(first, updated_at='2026-10-01T10:00:00+00:00'),
            dict(second, updated_at='2026-10-02T10:00:00+00:00'),
            dict(metadata, updated_at='2026-10-03T10:00:00+00:00')])
        result = build_task_package(self.vault, 'alpha ne durumda')
        self.assertLess(result['selected_ids'].index('second'), result['selected_ids'].index('work'))
        self.assertIn('son bilinen durum (2026-10-01, teyit kaydı yok)', result['text'])
        put(self.vault, 'task', dict(metadata, next_step='Yeni adımı uygula', expected_version=2))
        result = build_task_package(self.vault, 'alpha ne durumda')
        self.assertLess(result['selected_ids'].index('work'), result['selected_ids'].index('second'))

    def task(self, ident='work', days=0, **extra):
        from is_ve_ders import put
        data = dict(id=ident, title='Alpha iş kartı', status='active', project_id='alpha',
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
        self.assertIn('work',result['selected_ids'])
        self.assertIn('teyit gerekli',result['text'])

    def test_missing_verification_card_is_dated_history_without_current_action(self):
        task = self.task(last_verified=None)
        result = build_task_package(self.vault, 'alpha ne durumda')
        self.assertIn('work', result['selected_ids'])
        self.assertIn('son bilinen durum ('+task['updated_at'][:10]+', teyit kaydı yok)', result['text'])
        self.assertNotIn('work', result['summary']['task_ids'])
        self.assertEqual([], result['capsule']['tasks'])
        self.assertIsNone(result['capsule']['suggested_next_step'])
        self.assertIn(task['next_step'], result['text'])
        self.task('fresh')
        result = build_task_package(self.vault, 'alpha ne durumda')
        self.assertLess(result['selected_ids'].index('fresh'), result['selected_ids'].index('work'))
        self.assertEqual(['fresh'], [t['id'] for t in result['capsule']['tasks']])

    def test_newest_active_task_and_remaining_count(self):
        self.task('first');self.task('second')
        result=build_task_package(self.vault,'alpha devam')
        self.assertEqual(['second','first'],[t['id'] for t in result['capsule']['tasks']])
        self.assertNotIn('aktif iş daha',result['text'])
        self.assertTrue(result['capsule']['selection_required'])
        self.assertIsNone(result['capsule']['suggested_next_step'])

    def test_status_intents_and_destination_project(self):
        from gorev_baglam import continuation_request, select_projects
        for phrase in ('ne durumda','nerede kaldık','son durum','kaldığımız yer','devam'):
            self.assertTrue(continuation_request('alpha '+phrase))
            self.assertTrue(build_task_package(self.vault,'alpha '+phrase)['capsule']['enabled'])
        projects=[dict(id='beta',aliases=['Beta']),dict(id='gamma',aliases=['Gamma'])]
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':projects}))
        for query in ("Beta'yı bırakıp Gamma", 'Beta yerine Gamma', 'Beta’yı bırak Gamma ne durumda'):
            with self.subTest(query=query):
                self.assertEqual(['gamma'],[p['id'] for p in select_projects(projects,query)[0]])
                result=build_task_package(self.vault,query)
                self.assertEqual('gamma',result['project_id'])
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


class BoundedStatusRegressionTests(unittest.TestCase):
    setUp = ScopeContextPackageTests.setUp
    task = ProjectStatusTests.task
    def test_three_cards_and_actual_remaining_count(self):
        for ident in ('one', 'two', 'three', 'four'):
            self.task(ident)
        full = build_task_package(self.vault, 'alpha devam', history='never')
        self.assertEqual(['four', 'three', 'two'], [t['id'] for t in full['capsule']['tasks']])
        self.assertIn('1 aktif iş daha', full['text'])
        self.assertIn('one:card_limit', full['omitted_reasons'])
        self.assertIsNone(full['capsule']['suggested_next_step'])
        short = build_task_package(self.vault, 'alpha devam', budget=370, history='never')
        self.assertLessEqual(len(short['text']), 370)
        self.assertEqual(1, len(short['capsule']['tasks']))
        self.assertIn('3 aktif iş daha', short['text'])

    def test_unique_legacy_title_restores_scope_without_overriding_explicit_scope(self):
        from gorev_baglam import digest
        path=self.vault/'komuta/gorev-baglam.json'
        path.write_text(json.dumps({'projects':[dict(id='alpha',aliases=['alpha']),dict(id='beta',aliases=['beta'])]}))
        self.task('legacy', project_id=None, title='Alpha CI kontrolü')
        self.task('foreign', project_id='beta', title='Alpha entegrasyonu')
        self.task('generic', project_id=None, title='İş kontrolü')
        result = build_task_package(self.vault, 'alpha devam', history='never')
        self.assertIn('legacy', result['selected_ids'])
        self.assertNotIn('foreign', result['selected_ids'])
        self.assertNotIn('generic', result['selected_ids'])
        self.assertEqual(digest(self.vault/'source.md'), result['source_versions']['source.md'])
        (self.vault/'source.md').write_text('İncelenmemiş değişiklik')
        self.assertNotIn('legacy', build_task_package(self.vault, 'alpha devam')['selected_ids'])

    def test_ambiguous_legacy_title_does_not_restore_scope(self):
        path=self.vault/'komuta/gorev-baglam.json'
        path.write_text(json.dumps({'projects':[dict(id='alpha',aliases=['alpha']),dict(id='beta',aliases=['beta'])]}))
        self.task('mixed', project_id=None, title='Alpha beta entegrasyonu')
        self.assertNotIn('mixed', build_task_package(self.vault, 'alpha devam')['selected_ids'])

    def test_video_area_restores_only_unique_unscoped_legacy_cards(self):
        path=self.vault/'komuta/gorev-baglam.json'
        area=dict(id='studio', kind='area', aliases=['thumbnail', 'video radarı'])
        path.write_text(json.dumps({'projects':[area, dict(id='beta', aliases=['beta'])]}))
        self.task('legacy-video', project_id=None, title='Model seçimi videoları')
        self.task('foreign-video', project_id='beta', title='Model seçimi videoları')
        self.task('unrelated', project_id=None, title='Sunucu kontrolü')
        package=build_task_package(self.vault, 'video kurgusunu planla', history='never')
        self.assertIn('legacy-video', package['selected_ids'])
        self.assertNotIn('foreign-video', package['selected_ids'])
        self.assertNotIn('unrelated', package['selected_ids'])
        path.write_text(json.dumps({'projects':[area, dict(area, id='second')]}))
        self.assertIsNone(build_task_package(self.vault, 'video kurgusunu planla')['project_id'])

    def test_topic_area_limits_alternatives_and_omits_cover_kit(self):
        area=dict(id='studio', kind='area', aliases=['thumbnail', 'video radarı'],
                  assets=[dict(id='irrelevant-cover')],
                  working_sources=[dict(path='irrelevant-cover')])
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[area]}))
        for ident in ('one', 'two', 'three'):
            self.task(ident, project_id=None, title='Kurgu videosu '+ident)
        package=build_task_package(self.vault, 'video planlayalım', history='never')
        self.assertEqual('area_topic', package['match_reason'])
        self.assertEqual(3, len(set(package['selected_ids']) & {'one','two','three'}))
        self.assertEqual([], package['assets'])
        self.assertNotIn('irrelevant-cover', package['text'])

    def test_compact_card_preserves_claim_warning_and_source_binding(self):
        path = 'gelen-kutusu/' + 'a'*90 + '.md'
        (self.vault/'gelen-kutusu').mkdir()
        (self.vault/path).write_text((self.vault/'source.md').read_text())
        self.task('history', days=60, source_path=path,
                  last_result='Kaynaklı ayrıntı. '*30)
        package=build_task_package(self.vault, 'alpha devam', budget=2000, history='never')
        self.assertIn('history', package['selected_ids'])
        self.assertIn('teyit gerekli', package['text'])
        self.assertIn('Sonraki adım: Testleri doğrula', package['text'])
        reference='zihin/is-durumu.jsonl#history'
        self.assertIn(reference, package['text'])
        self.assertEqual(dict(path=path, sha256=digest(self.vault/path)),
                         package['source_references'][reference])
        self.assertEqual(digest(self.vault/path), package['source_versions'][path])
        self.assertNotIn('Son sonuç:', package['text'])
        self.assertIsNone(package['capsule']['suggested_next_step'])
        full=build_task_package(self.vault, 'alpha devam', budget=5000, history='never')
        self.assertIn('Son sonuç: Kaynaklı ayrıntı.', full['text'])
        self.assertIn(path, full['text'])
        small=build_task_package(self.vault, 'alpha devam', budget=20, history='never')
        self.assertEqual({}, small['source_references'])

    def test_previous_scope_only_for_safe_unambiguous_continuation(self):
        from gorev_baglam import select_projects
        projects=[dict(id='alpha',aliases=['alpha']),dict(id='beta',aliases=['beta'],roots=[str(self.vault/'beta')])]
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':projects}))
        inherited = build_task_package(self.vault, 'devam et döngüye', previous_user='alpha üzerinde çalış')
        self.assertEqual('alpha', inherited['project_id'])
        self.assertEqual('previous_user', inherited['match_reason'])
        self.assertIsNone(build_task_package(self.vault, 'devam et döngüye')['project_id'])
        self.assertIsNone(build_task_package(self.vault, 'devam', previous_user='alpha ve beta')['project_id'])
        self.assertIsNone(build_task_package(self.vault, 'hava nasıl', previous_user='alpha')['project_id'])
        self.assertEqual('beta', build_task_package(self.vault, 'beta devam', previous_user='alpha')['project_id'])
        self.assertEqual('beta', build_task_package(self.vault, 'devam', cwd=str(self.vault/'beta'), previous_user='alpha')['project_id'])
        with patch('client_transcripts.private', return_value=True):
            self.assertIsNone(build_task_package(self.vault, 'devam', previous_user='alpha')['project_id'])

    def test_notes_survive_status_card_and_partial_delivery_metadata_is_exact(self):
        from gorev_baglam import digest
        self.task()
        (self.vault/'bilgi').mkdir()
        records=[]; versions={}; cards=[]
        for ident, statement in (('a', 'Alpha için incelenmiş kısa bilgi.\n\nAynı kaydın kapsam koşulu.'), ('b', 'İkinci bağımsız bilgi. '*50)):
            path='bilgi/'+ident+'.md'
            (self.vault/path).write_text(statement)
            records.append(dict(id=ident,statement=statement,sources=[],examples=[]))
            versions[path]=digest(self.vault/path)
            cards.append('Bilgi [decision; all; project:alpha]: '+statement+'\nKaynak: '+path)
        notes=dict(text='\n\n'.join(cards),records=records,transfers=[],source_versions=versions,diagnostics=[])
        with patch('konu_sentezi.retrieve', return_value=notes):
            result=build_task_package(self.vault, 'alpha ne durumda', budget=650, history='never')
        self.assertIn('work', result['selected_ids'])
        self.assertIn(records[0]['statement'], result['delivered_segments']['knowledge'])
        self.assertNotIn(records[1]['statement'], result['text'])
        self.assertEqual(['a'], [r['id'] for r in result['knowledge']['records']])
        self.assertIn('b', result['knowledge']['omitted_record_ids'])
        self.assertIn('bilgi/a.md', result['source_versions'])
        self.assertNotIn('bilgi/b.md', result['source_versions'])
        self.assertEqual(result['delivered_segments']['knowledge'], result['knowledge']['text'])
        self.assertLessEqual(len(result['text']),650)

    def test_task_topic_precedes_unrelated_newer_card(self):
        self.task('build', title='Alpha derleme hatası', next_step='Derleme hatasını doğrula')
        self.task('newer', title='Alpha tasarım incelemesi', next_step='Renk seçimini incele')
        result=build_task_package(self.vault, 'alpha derleme devam', history='never')
        self.assertEqual('build', result['capsule']['tasks'][0]['id'])
        self.assertTrue(result['capsule']['selection_required'])
        self.assertIsNone(result['capsule']['suggested_next_step'])

    def test_current_topic_keeps_card_slots_against_previous_topic(self):
        self.task('archive', days=4, title='Alpha ses kaydı', next_step='Sesi dinle')
        self.task('older', days=3, title='Alpha derleme renkleri', next_step='Paleti incele')
        self.task('build', title='Alpha derleme hatası', next_step='Derleme hatasını doğrula')
        self.task('second', title='Alpha güncel kontrol', next_step='Kontrolü doğrula')
        self.task('third', title='Alpha teslim planı', next_step='Planı doğrula')
        query = 'alpha derleme hatası için ayrıntılı kontrol yap devam'
        baseline = build_task_package(self.vault, query, budget=2000, history='never')
        contextual = build_task_package(self.vault, query, budget=2000, history='never',
                                        previous_user='renkleri ve paleti incele')
        self.assertEqual([t['id'] for t in baseline['capsule']['tasks']],
                         [t['id'] for t in contextual['capsule']['tasks']])
        self.assertEqual(3, len(contextual['capsule']['tasks']))
        self.assertIn('older:card_limit', contextual['omitted_reasons'])


class SessionProjectInheritanceTests(unittest.TestCase):
    setUp = ScopeContextPackageTests.setUp

    def test_session_scope_precedes_previous_turn_but_not_current_evidence(self):
        projects = [dict(id='alpha', aliases=['alpha']),
                    dict(id='beta', aliases=['beta'], roots=[str(self.vault/'beta')])]
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects': projects}))
        for query in ('pr attıysan devam edelim', 'devam et döngüye', 'son durum'):
            result = build_task_package(self.vault, query, cwd='/unrelated',
                                        previous_user='beta üzerinde çalış', session_project_id='alpha')
            self.assertEqual(('alpha', 'session_project'), (result['project_id'], result['match_reason']))
        for kwargs in (dict(query='beta devam'), dict(query='devam', cwd=str(self.vault/'beta'))):
            result = build_task_package(self.vault, session_project_id='alpha', **kwargs)
            self.assertEqual('beta', result['project_id'])
        self.assertIsNone(build_task_package(self.vault, 'alpha beta devam', session_project_id='alpha')['project_id'])
        # Scope remains available after a prior continuation no longer names it.
        self.assertEqual('alpha', build_task_package(self.vault, 'devam', previous_user='devam',
                                                     session_project_id='alpha')['project_id'])
        self.assertEqual('alpha', build_task_package(self.vault, 'devam', previous_user='alpha')['project_id'])

    def test_session_inheritance_fails_closed(self):
        projects = [dict(id='alpha', aliases=['alpha']),
                    dict(id='old', aliases=['old'], status='archived')]
        (self.vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects': projects}))
        for ident in ('missing', 'old', ['alpha', 'old'], {'project_id': 'alpha'}, ''):
            with self.subTest(ident=ident):
                self.assertIsNone(build_task_package(self.vault, 'devam', previous_user='alpha',
                                                     session_project_id=ident)['project_id'])
        for query in ('hava nasıl', 'devam ' + 'uzun açıklama '*25,
                      '[kaydetme] devam', 'İŞÇİ KOŞUSU. devam',
                      'devam token sk-' + 'abcdefghijklmnopqrstuvwxyz123456'):
            with self.subTest(query=query):
                self.assertIsNone(build_task_package(self.vault, query, session_project_id='alpha')['project_id'])

    def test_inherited_scope_rechecks_configuration_revision(self):
        def change_config(vault, query, rows, rank, scope):
            (vault/'komuta/gorev-baglam.json').write_text(json.dumps({'projects': []}))
            return rank(rows, query), None
        with patch('jev_retrieval.catalog', side_effect=change_config):
            result = build_task_package(self.vault, 'devam', session_project_id='alpha')
        self.assertEqual([], result['selected_ids'])
        self.assertEqual({}, result['source_versions'])
        self.assertNotIn('Proje: alpha', result['text'])
        self.assertIn('source_changed_during_package', result['omitted_reasons'])


class CatalogBudgetFairnessTests(unittest.TestCase):
    setUp = ScopeContextPackageTests.setUp

    def test_equal_match_prefers_selected_scope_and_preserves_order_independence(self):
        rows = [dict(self.row, memory_id='a-user', scope='user'),
                dict(self.row, memory_id='z-project'),
                dict(self.row, memory_id='other', scope='project:other')]
        for data in (rows, rows[::-1]):
            h._write_jsonl(self.vault/h.CATALOG_PATH, data)
            package = build_task_package(self.vault, 'alpha sunum', history='never', budget=2000)
            ids = [ident for ident in package['selected_ids'] if ident in ('a-user', 'z-project', 'other')]
            self.assertEqual(['z-project', 'a-user'], ids)

    def test_notes_and_catalog_share_budget_without_splitting_cards(self):
        first = dict(self.row, memory_id='first')
        second = dict(self.row, memory_id='second')
        h._write_jsonl(self.vault/h.CATALOG_PATH, [first, second])
        (self.vault/'bilgi').mkdir()
        note_cards = ['Bilgi [decision]: Sentetik not '+str(i)+' '+('n'*240) for i in range(3)]
        knowledge = dict(text='\n\n'.join(note_cards), records=[], source_versions={}, transfers=[], topics=[])
        with patch('konu_sentezi.retrieve', return_value=knowledge):
            full = build_task_package(self.vault, 'alpha sunum', history='never', budget=10000)
            segments = full['delivered_segments']
            budget = len(segments['first']) + len(note_cards[0]) + len(segments['second']) + 2
            small = build_task_package(self.vault, 'alpha sunum', history='never', budget=budget)
        self.assertEqual(['first', 'knowledge', 'second'], small['selected_ids'])
        self.assertEqual(note_cards[0], small['delivered_segments']['knowledge'])
        self.assertIn('knowledge:budget', small['omitted_reasons'])
        self.assertLessEqual(len(small['text']), budget)


class SharedWorkspaceRoutingTests(unittest.TestCase):
    def test_alias_possessives_do_not_expand_record_ranking(self):
        from gorev_baglam import alias_match, word_match
        self.assertTrue(alias_match('video', ['videomuza']))
        self.assertFalse(word_match('video', 'videomuza'))
        self.assertFalse(word_match('sekmeyi', 'sekmedeneme'))

    def test_shared_vault_needs_topic_but_nested_workspace_keeps_scope(self):
        from gorev_baglam import select_projects
        with tempfile.TemporaryDirectory() as tmp:
            vault=Path(tmp).resolve()
            projects=[dict(id='memory-engine', aliases=['hafıza sistemi'], roots=[str(vault)]),
                      dict(id='studio', kind='area', aliases=['thumbnail', 'video radarı']),
                      dict(id='beta', aliases=['beta'], roots=[str(vault/'beta')])]
            for query, expected in [('durum ne', []), ('hava nasıl', []),
                                    ('hafızamızda ne değişti', ['memory-engine']),
                                    ('video fikri', ['studio']), ('kurgu planla', ['studio']),
                                    ('beta devam', ['beta'])]:
                with self.subTest(query=query):
                    rows,_=select_projects(projects, query, cwd=str(vault), vault=vault)
                    self.assertEqual(expected, [p['id'] for p in rows])
            rows,reason=select_projects(projects, 'devam', cwd=str(vault/'beta'), vault=vault)
            self.assertEqual((['beta'], 'cwd'), ([p['id'] for p in rows], reason))
            rows,reason=select_projects(projects, 'devam', cwd=str(vault),
                                       previous_user='video planlayalım', vault=vault)
            self.assertEqual((['studio'], 'previous_user'), ([p['id'] for p in rows], reason))

    def test_relocated_vault_recognizes_original_layout(self):
        from gorev_baglam import select_projects
        with tempfile.TemporaryDirectory() as tmp:
            origin=Path(tmp).resolve()/'origin'
            (origin/'komuta').mkdir(parents=True)
            (origin/'komuta/gorev-baglam.json').write_text('{}')
            (origin/'zihin').mkdir()
            projects=[dict(id='engine', aliases=['memory engine'], roots=[str(origin)])]
            self.assertEqual([], select_projects(projects, 'devam', cwd=str(origin),
                                                vault=Path(tmp).resolve()/'snapshot')[0])
            self.assertEqual(['engine'], [p['id'] for p in select_projects(
                projects, 'memory engine devam', cwd=str(origin), vault=Path(tmp).resolve()/'snapshot')[0]])

    def test_generic_guard_and_specific_names_survive_area_expansion(self):
        from gorev_baglam import select_projects
        projects=[dict(id='studio', kind='area', aliases=['thumbnail', 'video radarı']),
                  dict(id='nova', aliases=['nova videosu'])]
        for query, expected in [('videomuza kesit çıkar', ['studio']),
                                ('youtube için hazırla', ['studio']),
                                ('novanın videosuna kapak', ['nova']),
                                ('kabak çorbası', []), ('dünkü iş', []), ('o kapak', []),
                                ('o thumbnail', []), ('önceki video', [])]:
            with self.subTest(query=query):
                self.assertEqual(expected, [p['id'] for p in select_projects(projects,query)[0]])
        self.assertEqual([], select_projects([projects[1]], 'video planla')[0])
        self.assertEqual(2, len(select_projects([projects[0],dict(projects[0],id='other')],
                                               'video planla')[0]))
        named=[dict(id='memory-engine',aliases=['hafıza sistemi']),projects[0]]
        self.assertEqual(['memory-engine'],[p['id'] for p in select_projects(named,'memory-engine thumbnail üret')[0]])

    def test_mixed_area_root_requires_current_production_topic(self):
        from gorev_baglam import select_projects
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            mixed = base/'solver-context-video'
            studio = dict(id='studio', kind='area', aliases=['thumbnail', 'video radarı'],
                          roots=[str(mixed), str(base/'studio')])
            projects = [studio, dict(id='solver', aliases=['solver']),
                        dict(id='engine', aliases=['memory engine'])]
            for query in ('devam et', 'doğru kurguyla devam et',
                          'model ile devam', 'adaylar neden elendi', 'belleğimizde neler değişti'):
                with self.subTest(query=query):
                    self.assertEqual(([], 'unresolved'), select_projects(
                        projects, query, cwd=str(mixed/'research')))
            for query in ('video planla', 'kurgu videosuna devam', 'senaryo yaz', 'kapak hazırla'):
                with self.subTest(query=query):
                    rows, _ = select_projects(projects, query, cwd=str(mixed))
                    self.assertEqual(['studio'], [p['id'] for p in rows])
            rows, reason = select_projects(projects, 'devam et', cwd=str(base/'studio'))
            self.assertEqual((['studio'], 'cwd'), ([p['id'] for p in rows], reason))
            for query, expected in [('solver devam', 'solver'), ('memory engine devam', 'engine')]:
                rows, reason = select_projects(projects, query, cwd=str(mixed))
                self.assertEqual(([expected], 'explicit'), ([p['id'] for p in rows], reason))

    def test_mixed_area_root_allows_safe_prior_but_never_infers_path_project(self):
        from gorev_baglam import select_projects
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()/'solver-video'
            projects = [dict(id='studio', kind='area', aliases=['thumbnail'], roots=[str(root)]),
                        dict(id='solver', aliases=['solver']),
                        dict(id='engine', aliases=['memory engine'])]
            rows, reason = select_projects(projects, 'devam', cwd=str(root),
                                           previous_user='memory engine üzerinde çalış')
            self.assertEqual((['engine'], 'previous_user'), ([p['id'] for p in rows], reason))
            rows, reason = select_projects(projects, 'devam', cwd=str(root),
                                           session_project_id='engine')
            self.assertEqual((['engine'], 'session_project'), ([p['id'] for p in rows], reason))
            self.assertEqual([], select_projects(projects, 'devam', cwd=str(root),
                                                previous_user='solver ve engine')[0])

    def test_area_root_collision_uses_full_configured_alias(self):
        from gorev_baglam import select_projects
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            projects = [dict(id='studio', kind='area', aliases=['thumbnail'],
                             roots=[str(base/'proof-engine-video'), str(base/'proof-video')]),
                        dict(id='solver', aliases=['proof engine'])]
            self.assertEqual([], select_projects(projects, 'devam', cwd=str(base/'proof-engine-video'))[0])
            rows, reason = select_projects(projects, 'devam', cwd=str(base/'proof-video'))
            self.assertEqual((['studio'], 'cwd'), ([p['id'] for p in rows], reason))


class ImplicitProjectTests(unittest.TestCase):
    def setUp(self):
        # A neutral workspace fixture must not itself live under a filtered /tmp.
        self.tmp = tempfile.TemporaryDirectory(prefix='fixture-', dir=Path(__file__).resolve().parent.parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.vault = self.base/'vault'; (self.vault/'komuta').mkdir(parents=True)
        self.registry = self.vault/'komuta/gorev-baglam.json'
        self.registry.write_text(json.dumps({'projects': []}))
        self.home = self.base/'user'; self.home.mkdir()
        self.home_patch = patch('gorev_baglam.Path.home', return_value=self.home)
        self.home_patch.start(); self.addCleanup(self.home_patch.stop)

    def card(self, ident='proj-a-plan', evidence='Kaynakta doğrulanmış proje durumu.', **extra):
        from is_ve_ders import put
        source = ident+'.md'; (self.vault/source).write_text(evidence)
        return put(self.vault, 'task', dict(id=ident, title='İş planı', status='active',
            next_step='Sıradaki adımı doğrula.', source_path=source, evidence=evidence,
            actor='test', last_verified=dt.date.today().isoformat(), **extra))

    def package(self, cwd, query='devam edelim'):
        return build_task_package(self.vault, query, cwd=str(cwd), budget=2000)

    def test_directory_prefix_delivers_legacy_card_without_config(self):
        self.card(); cwd = self.home/'projects/proj-a'; cwd.mkdir(parents=True)
        p = self.package(cwd)
        self.assertEqual('proj-a', p['project_id'])
        self.assertEqual('cwd-implicit', p['project_source'])
        self.assertIn('proj-a-plan', p['selected_ids'])
        self.assertIn('proj-a-plan', p['summary']['task_ids'])

    def test_small_parent_directory_finds_unique_child_project(self):
        self.card(); cwd = self.home/'workspace'; (cwd/'proj-a').mkdir(parents=True)
        (cwd/'calisma').mkdir()
        p = self.package(cwd)
        self.assertEqual('proj-a', p['project_id'])
        self.assertIn('proj-a-plan', p['selected_ids'])

    def test_pending_legacy_card_is_delivered_as_confirmation_hint(self):
        from is_ve_ders import put
        row = self.card(); cwd = self.home/'proj-a'; cwd.mkdir()
        put(self.vault, 'task', dict(row, status='needs_confirmation', expected_version=row['version']))
        p = self.package(cwd)
        self.assertEqual('proj-a', p['project_id'])
        self.assertIn('proj-a-plan', p['selected_ids'])
        self.assertIn('teyit gerekli', p['text'])
        self.assertEqual([], p['summary']['task_ids'])

    def test_pending_missing_or_null_next_step_is_safe_in_package(self):
        from is_ve_ders import put, latest
        cwd = self.home/'proj-a'; cwd.mkdir()
        row = self.card()
        for value in ('missing', None):
            with self.subTest(next_step=value):
                row = dict(row, status='needs_confirmation', expected_version=row['version'])
                if value == 'missing': row.pop('next_step', None)
                else: row['next_step'] = value
                row = put(self.vault, 'task', row)
                for query in ('devam edelim', 'iş planı durumunu incele'):
                    p = self.package(cwd, query)
                    self.assertEqual('proj-a', p['project_id'])
                    self.assertIn('proj-a-plan', p['selected_ids'])
                    self.assertIn('teyit gerekli', p['text'])
                    self.assertIn('Kaydedilmiş sonraki adım yok', p['text'])
                    self.assertEqual([], p['summary']['task_ids'])
                    self.assertEqual([], p['capsule']['tasks'])
                    self.assertIsNone(p['capsule']['suggested_next_step'])
                recorded = latest(self.vault, 'task')['proj-a-plan']
                self.assertIsNone(recorded.get('next_step'))
                self.assertEqual(value is None, 'next_step' in recorded)

    def test_implicit_bad_json_and_schema_preserve_empty_selection_with_diagnostic(self):
        from is_ve_ders import TASKS
        cwd = self.home/'proj-a'; cwd.mkdir()
        ledger = self.vault/TASKS; ledger.parent.mkdir()
        for content, error in [('{broken\n', 'JSONDecodeError'), ('{}\n', 'KeyError'),
                               ('[]\n', 'ValueError'),
                               ('{"id": "proj-a-plan", "status": []}\n', 'ValueError'),
                               ('{"id": "proj-a-plan", "status": "active"}\n', 'ValueError'),
                               ('{"id": "proj-a-plan", "title": null, "status": "active"}\n', 'ValueError')]:
            with self.subTest(content=content):
                ledger.write_text(content)
                p = self.package(cwd)
                self.assertIsNone(p['project_id'])
                self.assertEqual('unresolved', p['match_reason'])
                self.assertEqual([], p['selected_ids'])
                self.assertEqual('', p['text'])
                self.assertIn('implicit_project:'+error, p['omitted_reasons'])

    def test_implicit_read_errors_preserve_empty_selection_with_diagnostic(self):
        self.card(); cwd = self.home/'proj-a'; cwd.mkdir()
        for reader in ('latest', 'brief'):
            with self.subTest(reader=reader), patch('gorev_baglam.'+reader, side_effect=PermissionError('fixture')):
                p = self.package(cwd)
                self.assertIsNone(p['project_id'])
                self.assertEqual([], p['selected_ids'])
                self.assertIn('implicit_project:PermissionError', p['omitted_reasons'])
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            if path == cwd: raise OSError('fixture resolution failure')
            return original(path, *args, **kwargs)
        with patch('gorev_baglam.Path.resolve', resolve):
            p = self.package(cwd)
        self.assertIsNone(p['project_id'])
        self.assertEqual([], p['selected_ids'])
        self.assertIn('implicit_project:OSError', p['omitted_reasons'])

    def test_implicit_programming_error_is_not_silenced(self):
        cwd = self.home/'proj-a'; cwd.mkdir()
        with patch('gorev_baglam.implicit_project', side_effect=RuntimeError('fixture bug')):
            with self.assertRaisesRegex(RuntimeError, 'fixture bug'):
                self.package(cwd)

    def test_temporary_components_cannot_be_bypassed_by_project_or_git_root(self):
        self.card()
        for component in ('tmp', 'temp', '.cache', 'scratch', 'scratch-workspaces'):
            root = self.home/component/'proj-a'; (root/'src').mkdir(parents=True)
            (root/'.git').mkdir()
            for cwd in (root, root/'src'):
                with self.subTest(cwd=cwd):
                    p = self.package(cwd)
                    self.assertIsNone(p['project_id'])
                    self.assertEqual([], p['selected_ids'])
        if Path('/tmp').is_dir():
            with tempfile.TemporaryDirectory(dir='/tmp', prefix='fixture-') as directory:
                cwd = Path(directory)/'proj-a'; cwd.mkdir(); (cwd/'.git').mkdir()
                p = self.package(cwd)
                self.assertIsNone(p['project_id'])
                self.assertEqual([], p['selected_ids'])

    def test_first_two_home_levels_find_project_from_nested_cwd(self):
        self.card(); cwd = self.home/'projects/proj-a/src/module'; cwd.mkdir(parents=True)
        self.assertEqual('proj-a', self.package(cwd)['project_id'])

    def test_git_root_finds_project_outside_home(self):
        if any(p.casefold() in {'tmp', 'temp'} for p in self.base.parts):
            self.skipTest('ev dışı geçici dizinler bilerek örtük proje üretmez')
        self.card(); root = self.base/'repos/proj-a'; cwd = root/'src/module'
        cwd.mkdir(parents=True); (root/'.git').write_text('gitdir: elsewhere')
        self.assertEqual('proj-a', self.package(cwd)['project_id'])

    def test_evidence_whole_slug_and_source_path_match(self):
        cwd = self.home/'proj-a'; cwd.mkdir()
        for field in ('evidence', 'source_path', 'project_id'):
            with self.subTest(field=field):
                row = dict(id='neutral-plan', title='İş planı', status='active', evidence='', source_path='', project_id=None)
                row[field] = {'evidence':'Kaynak proj-a durumunu doğrular.',
                              'source_path':'notes/proj-a/state.md', 'project_id':'proj-a'}[field]
                with patch('gorev_baglam.latest', return_value={row['id']:row}), patch('gorev_baglam.brief', return_value=[row]):
                    from gorev_baglam import select_projects
                    rows, reason = select_projects([], 'devam', cwd=cwd, vault=self.vault)
                self.assertEqual(('proj-a', 'cwd-implicit'), (rows[0]['id'], reason))

    def test_partial_slug_and_other_project_owner_do_not_match(self):
        from gorev_baglam import select_projects
        cwd = self.home/'proj-a'; cwd.mkdir()
        for row in [dict(id='proj-ab-plan', evidence='proj-ab durumu', source_path='proj-ab.md'),
                    dict(id='proj-a-plan', evidence='proj-a durumu', project_id='proj-b')]:
            with self.subTest(row=row), patch('gorev_baglam.latest', return_value={row['id']:row}):
                self.assertEqual(([], 'unresolved'), select_projects([], 'devam', cwd=cwd, vault=self.vault))

    def test_generic_short_shared_and_scratch_directories_are_excluded(self):
        from gorev_baglam import select_projects
        for name in ('calisma', 'youtube', 'abc', 'scratch-workspaces/proj-a', 'tmp-build/proj-a'):
            cwd = self.home/name; cwd.mkdir(parents=True)
            with self.subTest(name=name), patch('gorev_baglam.brief') as reader:
                self.assertEqual(([], 'unresolved'), select_projects([], 'devam', cwd=cwd, vault=self.vault))
                reader.assert_not_called()
        for cwd in (self.home, self.vault):
            self.assertIsNone(self.package(cwd)['project_id'])

    def test_ambiguous_siblings_and_many_children_do_not_guess(self):
        self.card(); self.card('proj-b-plan')
        cwd = self.home/'workspace'; cwd.mkdir()
        (cwd/'proj-a').mkdir(); (cwd/'proj-b').mkdir()
        self.assertIsNone(self.package(cwd)['project_id'])
        for i in range(7): (cwd/('child-'+str(i))).mkdir()
        self.assertIsNone(self.package(cwd)['project_id'])

    def test_configured_scope_and_explicit_name_keep_precedence(self):
        self.card(); cwd = self.home/'proj-a'; cwd.mkdir()
        configured = dict(id='proj-b', aliases=['proj-b'], roots=[str(cwd)])
        self.registry.write_text(json.dumps({'projects':[configured]}))
        self.assertEqual('proj-b', self.package(cwd)['project_id'])
        configured['roots'] = []; self.registry.write_text(json.dumps({'projects':[configured]}))
        self.assertEqual('proj-b', self.package(cwd, 'proj-b devam')['project_id'])
        configured['id'] = 'proj-a'; configured['status'] = 'archived'
        self.registry.write_text(json.dumps({'projects':[configured]}))
        self.assertIsNone(self.package(cwd)['project_id'])

    def test_latest_closed_and_changed_sources_cannot_establish_scope(self):
        from is_ve_ders import put
        row = self.card(); cwd = self.home/'proj-a'; cwd.mkdir()
        (self.vault/row['source_path']).write_text('Kaynak sonradan değişti.')
        self.assertIsNone(self.package(cwd)['project_id'])
        (self.vault/row['source_path']).write_text(row['evidence'])
        put(self.vault, 'task', dict(row, status='done', expected_version=row['version']))
        self.assertIsNone(self.package(cwd)['project_id'])
