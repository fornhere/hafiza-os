import json
import tempfile
import unittest
from pathlib import Path
from gorev_baglam import build_task_package, digest, validate_inputs
from codex_hafiza import hook

class Package(unittest.TestCase):
 def asset_revision_fixture(self):
  import hafiza as h
  (self.v/'zihin').mkdir(exist_ok=True)
  rows=[]
  for ident,statement in [('old-asset','Kapak için eski sürüm tek aktif referanstır.'),('dignity','Kapak karakteri küçük düşürücü pozda gösterilmez.')]:
   rows.append(dict(memory_id=ident,kind='semantic',scope='user',subject_key=ident,statement=statement,status='active',source_path='approval.md',source_anchor=ident,source_hash=h.statement_hash(statement),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1))
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
  self.v=Path(self.tmp.name);(self.v/'komuta').mkdir()
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
  row=dict(memory_id='pref',kind='semantic',scope='user',subject_key='language',statement='Türkçe iletişim tercih edilir.',status='active',source_path='approval.md',source_anchor='language',source_hash=h.statement_hash('Türkçe iletişim tercih edilir.'),observed_at='2026-01-01',valid_from='2026-01-01',valid_to=None,confidence='explicit-user',sensitivity='normal',mem0_id=None,supersedes=None,reviewed_by='test',schema_version=1)
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
  projects=[dict(id='cover',aliases=['kapak','thumbnail'],roots=['/tmp/cover']),dict(id='game',aliases=['külaltı'],roots=['/tmp/game']),dict(id='astra',aliases=['astra videosu'],roots=['/tmp/astra'])]
  cases={'kapağımızı yenileyelim':'cover','kapaklarımızı düzenle':'cover','Külaltına dönelim':'game',"Külaltı’nda ilerleyelim":'game','Astranın videosuna devam':'astra',"Astra’nın videosuna kapak üret":'astra','thumnail üret':'cover','kabak çorbası yap':None,'astral seyahat videosu':None,'dünkü iş':None,'o kapak':None}
  for query,expected in cases.items():
   with self.subTest(query=query):
    rows,_=select_projects(projects,query)
    self.assertEqual(rows[0]['id'] if len(rows)==1 else None,expected)
  rows,reason=select_projects(projects,'Külaltına devam',cwd='/tmp/cover')
  self.assertEqual([p['id'] for p in rows],['game']);self.assertEqual(reason,'explicit')
  rows,reason=select_projects(projects,'o kapak',cwd='/tmp/cover')
  self.assertEqual([p['id'] for p in rows],['cover']);self.assertEqual(reason,'cwd')
  rows,_=select_projects(projects,'Külaltı ile Astranın videosu')
  self.assertEqual(len(rows),2)

 def test_unresolved_reference_explained_without_unrelated_noise(self):
  for query in ('o kapağa devam','dünkü işi aç'):
   result=build_task_package(self.v,query)
   self.assertIsNone(result['project_id'])
   self.assertIn('kaynak seçmeden netleştir',result['text'])
  self.assertEqual(build_task_package(self.v,'kabak nasıl pişer')['text'],'')
  self.assertEqual(build_task_package(self.v,'OBS nasıl açılır')['text'],'')

 def test_named_project_keeps_identity_with_cover_workflow(self):
  cfg={'projects':[self.project,dict(id='game',aliases=['külaltı'],roots=['/tmp/game'],assets=[]),dict(id='astra',aliases=['astra videosu'],roots=[],assets=[dict(self.asset,id='selected',role='selected-cover')])]}
  (self.v/'komuta/gorev-baglam.json').write_text(json.dumps(cfg))
  for query,expected in [('Külaltı için kapak hazırla','game'),('Astra videosuna kapak hazırla','astra')]:
   package=build_task_package(self.v,query)
   self.assertEqual(package['project_id'],expected)
   self.assertEqual(package['workflow_ids'],['youtube'])
   self.assertEqual(validate_inputs(package['assets'],[str(self.image)]),[str(self.image)])
   if expected=='game': self.assertIn('/tmp/game',package['text'])
  package=build_task_package(self.v,'Külaltı devam')
  self.assertEqual(package['assets'],[]);self.assertEqual(package['workflow_ids'],[])
