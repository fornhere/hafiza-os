import json
import tempfile
import unittest
from pathlib import Path
from ders_baglam import context, context_details, backlog, trigger_match
from gorev_baglam import alias_match, query_words, select_projects
from codex_hafiza import hook
from hafiza import statement_hash
from test_is_ve_ders import acceptance_fixture


class TriggerMatchTests(unittest.TestCase):
    def check_pairs(self, expected, pairs):
        for trigger, prompt in pairs:
            with self.subTest(trigger=trigger, prompt=prompt):
                self.assertEqual(trigger_match(trigger, query_words(prompt)), expected)

    def test_verb_forms_retaining_the_trigger_prefix(self):
        examples = {
            'kapat': ('kapattı', 'kapattım', 'kapattın', 'kapattık', 'kapattınız',
                      'kapattılar', 'kapatır mısın', 'kapatırım', 'kapatırsınız',
                      'kapatma', 'kapatmadı', 'kapatmadım', 'kapatmış', 'kapatmışsınız',
                      'kapatacak', 'kapatacağım', 'kapatacağız', 'kapatacaksınız',
                      'kapatmayacak', 'kapatmayacağız', 'kapatıyor', 'kapatıyoruz',
                      'kapatmıyor', 'kapatmaz', 'kapatmam', 'kapatmayız'),
            'getir': ('getirdi', 'getirir', 'getirmiş', 'getirecek', 'getireceğim',
                      'getirme', 'getirmedi', 'getirmeyecek', 'getiriyor'),
            'bitir': ('bitirdik', 'bitirmedi'),
            'çalış': ('çalıştı', 'çalıştınız', 'çalışıyor'),
            'durdur': ('durdurdu', 'durdurur', 'durdurmuş', 'durduruyor', 'durdurmazsınız'),
            'söndür': ('söndürdü', 'söndürür', 'söndürmüş', 'söndürüyor', 'söndürmeyiz'),
            'çarp': ('çarptı', 'çarpar', 'çarparım'),
            'serp': ('serpti', 'serper', 'serperiz'),
            'hazırla': ('hazırladı', 'hazırlar', 'hazırlamıyor',
                        'hazırlayacak', 'hazırlayacağım'),
            'incele': ('inceledi', 'inceler', 'incelemiyor', 'inceleyecek'),
            'yükle': ('yükledi', 'yükler', 'yüklemiyor', 'yükleyecek'),
            'ekle': ('ekledi', 'eklenmedi', 'ekleyebilir'),
        }
        self.check_pairs(True, [(root, word) for root, words in examples.items() for word in words])

    def test_passive_and_ability_forms_can_combine_after_the_prefix(self):
        self.check_pairs(True, [
            ('kapat', 'kapatılmadı'), ('kapat', 'kapatılmamış'), ('kapat', 'kapatılacak'),
            ('kapat', 'kapatıldı'), ('kapat', 'kapatılıyor'), ('kapat', 'kapatılmayacak'),
            ('kapat', 'kapatabilir'), ('kapat', 'kapatabilirim'), ('kapat', 'kapatabildim'),
        ])
        self.check_pairs(True, [('getir', 'getirebilir'), ('göster', 'gösterilmedi'),
                                ('hazırla', 'hazırlanmadı'), ('hazırla', 'hazırlayabilir')])
        self.check_pairs(True, [('kapat', 'kapatılabilir'), ('kapat', 'kapatılmamalı')])

    def test_known_verb_prefix_does_not_validate_suffixes(self):
        self.check_pairs(True, [
            ('kapat', 'kapattımxyz'), ('kapat', 'kapatici'), ('kapat', 'kapattıı'),
            ('kapat', 'kapatıracak'), ('kapat', 'kapatmışmış'),
        ])

    def test_prefix_matching_is_limited_to_known_verb_triggers(self):
        self.check_pairs(False, [
            ('kapat', 'kapasite'), ('kapat', 'kapalı'), ('kapat', 'kapak'),
            ('kapak', 'kapakıyor'), ('sunum', 'sunumacak'), ('rapor', 'raporabildi'),
            ('özetle', 'özetleyecek'), ('kapatı', 'kapattım'),
        ])

    def test_prefix_matching_does_not_contract_verb_roots(self):
        self.check_pairs(False, [
            ('hazırla', 'hazırlıyor'), ('incele', 'inceliyor'),
            ('yükle', 'yüklüyor'), ('ekle', 'ekliyor'), ('yükle', 'yükliyor'),
        ])

    def test_inflected_trigger_can_match_root_or_another_nominal_form(self):
        self.check_pairs(True, [
            ('sekmeyi', 'sekme'), ('sekmeyi', 'sekmeleri'), ('sekmeyi', 'sekmeye'),
            ('sekmeyi', 'sekmelerimizi'), ('sekmelerimizi', 'sekme'),
            ('raporumuzu', 'rapor'), ('raporumuzu', 'raporları'),
            ('kapağını', 'kapak'), ('kapağını', 'kapakları'), ('kapağı', 'kapağım'),
        ])
        self.check_pairs(False, [
            ('sekmeyi', 'sek'), ('sekmeyi', 'semer'), ('sekmeyi', 'sekreter'),
            ('sekmeyi', 'sekmedeneme'), ('kapağını', 'kapalı'), ('raporumuzu', 'raportör'),
        ])

    def test_only_existing_synonym_groups_expand(self):
        self.check_pairs(True, [
            ('sunum', 'slayt'), ('sunum', 'slideshow'), ('slayt', 'sunumları'),
            ('sunumu', 'slaytları'), ('slaytları', 'sunumu'),
            ('kapak', 'thumbnail'), ('thumbnail', 'kapağı'),
            ('hafıza', 'belleği'), ('bellek', 'hafızayı'),
            ('yöntem', 'prosedürü'), ('prosedür', 'yöntemi'),
            ('yedek', 'yedekleme'), ('yedekleme', 'yedeği'),
        ])
        self.check_pairs(False, [
            ('sunum', 'grafik'), ('thumbnail', 'küçük resim'), ('kapak', 'önizleme görseli'),
            ('overlay', 'alt bant'), ('kapat', 'gizle'), ('sunum', 'slayton'),
        ])

    def test_one_derivation_and_nominal_inflection(self):
        self.check_pairs(True, [
            ('maskot', 'maskotlu'), ('maskot', 'maskotluyu'), ('maskot', 'maskotlular'),
            ('sunum', 'sunumlu'), ('sunum', 'sunumluk'), ('sunum', 'slaytlık'),
            ('sunum', 'slaytlığını'), ('slaytları', 'sunumluk'),
            ('anlam', 'anlamlı'), ('resim', 'resimli'), ('köpük', 'köpüklü'),
            ('kitap', 'kitaplık'), ('etkin', 'etkinlik'), ('kömür', 'kömürlük'),
        ])
        self.check_pairs(False, [
            ('kapak', 'kapalı'), ('kapak', 'kabak'), ('kapak', 'kapakçılık'),
            ('maskot', 'maskotsuz'), ('maskot', 'maskotluluktan'),
            ('maskot', 'maskotlumtrak'), ('sunum', 'slaytlaştır'),
        ])

    def test_short_roots_are_exact_only_including_reverse_stemming(self):
        for term in ('aç', 'sil', 'yap', 'ara', 'ses', 'göz'):
            self.assertTrue(trigger_match(term, query_words(term)))
        self.check_pairs(False, [
            ('aç', 'açtı'), ('sil', 'sildi'), ('yap', 'yapıyor'), ('ara', 'aradı'),
            ('ses', 'sesli'), ('göz', 'gözlük'), ('ses', 'sesi'),
            ('sesi', 'ses'), ('sesi', 'sesleri'), ('gözü', 'göz'),
        ])

    def test_multiword_triggers_keep_all_parts_any_order_and_no_new_expansion(self):
        self.check_pairs(True, [('sekme kapat', 'kapat bu sekmeyi'),
                                ('görsel sunum', 'sunumu sonra görseli düzenle')])
        self.check_pairs(False, [('sekme kapat', 'sekme'), ('sekme kapat', 'kapattım'),
                                 ('sekme kapat', 'sekme kapattım'),
                                 ('sekmeyi kapat', 'sekme kapat'),
                                 ('görsel sunum', 'görsel slayt'),
                                 ('maskot kapak', 'maskotlu kapak')])
        for trigger in ('sekme kapat', 'sekmeyi kapat', 'görsel sunum', 'maskot kapak', ''):
            for prompt in ('kapat şu sekmeyi', 'sekmeleri kapattım', 'görsel slayt', 'maskotlu kapak', ''):
                words = query_words(prompt)
                self.assertEqual(trigger_match(trigger, words), alias_match(trigger, words))

    def test_normalization_and_complete_tokens(self):
        self.check_pairs(True, [('KAPAT', 'Kapattım!'), ('İncele', 'İnceledi.'),
                                ('sunum', "Slayt'ları"), ('sunum', 'slayt’ları')])
        self.check_pairs(False, [('', 'kapak'), ('!!!', 'kapak'), ('kapak', ''),
                                 ('kapat', 'yenikapattım'), ('sunum', 'slaytlıkxyz')])

    def test_project_aliases_do_not_gain_lesson_expansions(self):
        for trigger, prompt in [('kapat', 'kapattım'), ('sekmeyi', 'sekme'),
                                ('sunum', 'slayt'), ('maskot', 'maskotlu')]:
            with self.subTest(trigger=trigger):
                words = query_words(prompt)
                self.assertTrue(trigger_match(trigger, words))
                self.assertFalse(alias_match(trigger, words))
                self.assertEqual(select_projects([dict(id='p', aliases=[trigger])], prompt),
                                 ([], 'unresolved'))


class Lessons(unittest.TestCase):
 def lesson_fixture(self,v,ident='units',**changes):
  from is_ve_ders import put
  (v/'source.md').write_text('Raporu yayınlamadan birim adlarını denetle.')
  (v/'method.md').write_text('Birim adlarını denetle.')
  data=dict(id=ident,title=ident,status='proposed',source_path='source.md',evidence=(v/'source.md').read_text(),actor='reviewer',triggers=['rapor'],method_path='method.md',implementation_hash=statement_hash((v/'method.md').read_text()))
  return put(v,'lesson',dict(data,**changes))

 def test_expanded_triggers_preserve_scope_integrity_and_read_only_context(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp)
   for ident,trigger in [('verb','kapat'),('noun','sekmeyi'),('synonym','sunum'),('derived','maskot')]:
    self.lesson_fixture(v,ident,triggers=[trigger],project_id='p')
   before={p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()}
   for ident,prompt in [('verb','Kapattım.'),('noun','Sekme'),('synonym','Slayt'),('derived','Maskotlu')]:
    with self.subTest(ident=ident):
     details=context_details(v,prompt,project_id='p')
     self.assertEqual([r['id'] for r in details['lessons']],[ident])
     self.assertEqual(context(v,prompt,project_id='other'),'')
   self.assertEqual(before,{p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()})
   (v/'method.md').write_text('İncelemeden sonra değişti.')
   self.assertEqual(context_details(v,'kapattım',project_id='p'),
                    dict(text='',lessons=[],diagnostics=[dict(id='verb',reason='method_changed')]))

 def test_context_details_reports_only_delivered_lessons_in_order(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);z=self.lesson_fixture(v,'z');a=self.lesson_fixture(v,'a')
   self.lesson_fixture(v,'unmatched',triggers=['kapak'])
   details=context_details(v,'rapor')
   self.assertEqual(details['text'],context(v,'rapor'))
   self.assertEqual(details['diagnostics'],[])
   self.assertEqual(details['lessons'],[dict(id=r['id'],version=r['version'],status=r['status']) for r in (a,z)])
   self.assertLess(details['text'].index('Ders: a'),details['text'].index('Ders: z'))
   one=context_details(v,'rapor',budget=len(details['text'])-1)
   self.assertEqual([r['id'] for r in one['lessons']],['a'])
   self.assertEqual(one['diagnostics'],[dict(id='z',reason='budget')])
   self.assertEqual(one['text'],context(v,'rapor',budget=len(details['text'])-1))
   self.assertEqual(context_details(v,'rapor',budget=5),dict(text='',lessons=[],diagnostics=[dict(id=i,reason='budget') for i in ('a','z')]))
   (v/'source.md').write_text('Değişen kaynak dersi geçersiz kılar.')
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[],diagnostics=[dict(id=i,reason='source_changed') for i in ('a','z')]))

 def test_review_required_never_enters_context_and_backlog_requests_review(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);review=dict(reason='harm_exceeds_help',help=0,harm=2,outcome_ids=['one','two'])
   row=self.lesson_fixture(v,review_required=review,next_step='Eski sonraki adım')
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[],diagnostics=[dict(id='units',reason='review_required')]))
   entry=backlog(v)[0]
   self.assertEqual(entry['review_required'],review)
   self.assertEqual(entry['next_step'],'Fayda incelemesi: zarar 2 > yardım 0; dersi yeniden incele (otomatik silinmedi).')
   (v/'verified.md').write_text('Test sonucu birim adları için doğrulandı.')
   verified=put(v,'lesson',dict(row,status='verified',expected_version=row['version'],target_path='method.md',target_hash=row['implementation_hash'],verification_path='verified.md',verification_evidence=(v/'verified.md').read_text()))
   self.assertEqual(context(v,'rapor'),'')
   self.assertEqual(backlog(v),[])
   verified['review_required']={}
   put(v,'lesson',dict(verified,expected_version=verified['version']))
   self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[],diagnostics=[dict(id='units',reason='review_required')]))

 def test_changed_files_diagnostics_and_verified_backlog_are_read_only(self):
  from is_ve_ders import put
  from bilgi_agi import digest
  for filename,reason in [('method.md','method_changed'),('source.md','source_changed'),('verified.md','verification_changed')]:
   with self.subTest(filename=filename),tempfile.TemporaryDirectory() as tmp:
    v=Path(tmp);row=self.lesson_fixture(v,implementation_status='applied')
    (v/'verified.md').write_text('Test sonucu birim adları için doğrulandı.')
    put(v,'lesson',dict(row,status='verified',expected_version=row['version'],target_path='method.md',target_hash=row['implementation_hash'],verification_path='verified.md',verification_hash=digest(v/'verified.md'),verification_evidence=(v/'verified.md').read_text()))
    self.assertEqual(backlog(v),[])
    (v/filename).write_text('İncelemeden sonra değişen dosya.')
    before={p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()}
    self.assertEqual(context(v,'rapor'),'')
    self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[],diagnostics=[dict(id='units',reason=reason)]))
    self.assertEqual(backlog(v),[dict(id='units',status='verified',implementation_status='applied',recheck_reason=reason,next_step=f'Yeniden kontrol: {reason}. Kaynağı/yöntemi incele ve yeni sürümü is_ve_ders put ile bağla; o zamana kadar bağlama alınmaz.')])
    self.assertEqual(before,{p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()})

 def test_diagnostics_only_for_matching_status_scope_and_trigger(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp)
   for ident,changes in [('other-owner',dict(project_id='other',scope='global')),
                         ('other-scope',dict(scope='project:other')),
                         ('rejected',dict(status='rejected',review_required={})),
                         ('outcome',dict(outcome_id='pending')),
                         ('unmatched',dict(triggers=['kapak'])),
                         ('relevant',dict(project_id='current')),
                         ('review',dict(outcome_id='pending',review_required={})),
                         ('scoped-review',dict(project_id='other',review_required={}))]:
    self.lesson_fixture(v,ident,**changes)
   (v/'method.md').write_text('Değişen yöntem.')
   self.assertEqual(context_details(v,'hava nasıl',project_id='current')['diagnostics'],[])
   self.assertEqual(context_details(v,'rapor',project_id='current')['diagnostics'],[dict(id='relevant',reason='method_changed'),dict(id='review',reason='review_required')])
   self.assertEqual(context(v,'rapor',project_id='current'),'')
   self.assertEqual(context_details(v,'rapor',workflow_ids=['current'])['diagnostics'],[dict(id='relevant',reason='method_changed'),dict(id='review',reason='review_required')])

 def test_integrity_missing_legacy_and_evidence_reasons(self):
  cases=[(dict(source_path='missing.md'),'source_changed'),
         (dict(source_path='../outside.md'),'source_changed'),
         (dict(source_content_hash=None),'legacy_unreviewed'),
         (dict(evidence='Kaynakta bulunmayan kanıt.'),'source_changed'),
         (dict(method_path=None),'method_missing'),
         (dict(method_path='missing.md'),'method_missing'),
         (dict(method_path='../outside.md'),'method_missing'),
         (dict(implementation_hash=None),'method_changed'),
         (dict(verification_path='missing.md',verification_hash='old'),'verification_changed')]
  for changes,reason in cases:
   with self.subTest(changes=changes),tempfile.TemporaryDirectory() as tmp:
    v=Path(tmp);row=self.lesson_fixture(v)
    (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(dict(row,**changes))+'\n')
    self.assertEqual(context(v,'rapor'),'')
    self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason=reason)])
    self.assertEqual(backlog(v)[0]['recheck_reason'],reason)

 def test_integrity_reason_precedence(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);row=self.lesson_fixture(v)
   row.update(verification_path='missing.md',verification_hash='old',source_content_hash=None,method_path=None)
   ledger=v/'zihin/ders-durumu.jsonl'
   for reason in ('verification_changed','source_changed','legacy_unreviewed','method_missing'):
    with self.subTest(reason=reason):
     if reason=='source_changed': row.pop('verification_hash');(v/'source.md').unlink()
     if reason=='legacy_unreviewed': (v/'source.md').write_text(row['evidence'])
     if reason=='method_missing': row['source_content_hash']=statement_hash(row['evidence'])
     ledger.write_text(json.dumps(row)+'\n')
     self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason=reason)])

 def test_unreadable_files_remain_excluded(self):
  from unittest.mock import patch
  for filename,reason in [('source.md','source_changed'),('method.md','method_changed')]:
   with self.subTest(filename=filename),tempfile.TemporaryDirectory() as tmp:
    v=Path(tmp);self.lesson_fixture(v);read_text=Path.read_text
    def unreadable(path,*args,**kwargs):
     if path==v/filename: raise PermissionError('unreadable fixture')
     return read_text(path,*args,**kwargs)
    with patch.object(Path,'read_text',unreadable):
     self.assertEqual(context(v,'rapor'),'')
     self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason=reason)])
     self.assertEqual(backlog(v)[0]['recheck_reason'],reason)

 def test_backlog_proposed_recheck_preserves_fields_without_duplicates(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v,implementation_status='applied',next_step='Gerçek örnekte denetle.')
   self.lesson_fixture(v,'rejected',status='rejected')
   original=backlog(v)[0]
   (v/'method.md').write_text('Değişen yöntem.')
   self.assertEqual(backlog(v),[dict(original,recheck_reason='method_changed')])

 def test_target_hash_fallback_preserves_valid_context(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v,implementation_hash=None,target_hash=statement_hash('Birim adlarını denetle.'))
   self.assertIn('Birim adlarını denetle.',context(v,'rapor'))
   self.assertEqual(context_details(v,'rapor')['diagnostics'],[])

 def test_backlog_without_review_required_keeps_original_fields(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v,proposal='Önce birimleri denetle.')
   self.assertEqual(backlog(v),[dict(id='units',status='proposed',implementation_status='not_applied',next_step='Önce birimleri denetle.')])

 def test_instruction_unaccepted_is_excluded_diagnosed_and_reported_without_writes(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'CLAUDE.md').write_text('Birim adlarını denetle.')
   row=self.lesson_fixture(v,method_path='CLAUDE.md',next_step='Talimat dosyasını otomatik düzenle.')
   source=acceptance_fixture(v);accepted=dict(verification_kind='user_acceptance',observed_result='accepted',acceptance_source=source)
   cases=[{},dict(status='verified'),dict(status='verified',**dict(accepted,verification_kind='test_result')),
          dict(status='verified',**dict(accepted,observed_result='rejected')),accepted,
          dict(status='verified',**dict(accepted,acceptance_source=None))]
   cases += [dict(status='verified',**dict(accepted,acceptance_source={k:value for k,value in source.items() if k!=missing})) for missing in source]
   for changes in cases:
    with self.subTest(changes=changes):
     (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(dict(row,**changes))+'\n')
     before={p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()}
     self.assertEqual(context(v,'rapor'),'')
     self.assertEqual(context_details(v,'rapor'),dict(text='',lessons=[],diagnostics=[dict(id='units',reason='instruction_target_unaccepted')]))
     entry=backlog(v)[0]
     self.assertTrue(entry['instruction_target']);self.assertEqual(entry['recheck_reason'],'instruction_target_unaccepted')
     self.assertEqual(entry['next_step'],'Boşluk not edildi, uygulanmadı: talimat dosyası değişikliği kullanıcı kabulü (özgün kullanıcı mesajı alıntısı) ister.')
     self.assertEqual(before,{p.relative_to(v):p.read_bytes() for p in v.rglob('*') if p.is_file()})

 def test_instruction_target_path_alone_and_extra_patterns_gate_context(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v,target_path='a/AGENTS.md')
   self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason='instruction_target_unaccepted')])
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);self.lesson_fixture(v);(v/'komuta').mkdir()
   self.assertIn('Birim adlarını',context(v,'rapor'))
   (v/'komuta/talimat-dosyalari.json').write_text('{"extra_patterns":["method.md"]}')
   self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason='instruction_target_unaccepted')])
   self.assertTrue(backlog(v)[0]['instruction_target'])

 def test_accepted_instruction_context_still_checks_hashes_and_marks_backlog(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'hooks').mkdir();method=v/'hooks/pre.sh';method.write_text('Birim adlarını denetle.')
   row=self.lesson_fixture(v,method_path='hooks/pre.sh')
   (v/'verified.md').write_text('Test sonucu birim adları için doğrulandı.')
   put(v,'lesson',dict(row,status='verified',expected_version=row['version'],target_path='hooks/pre.sh',target_hash=row['implementation_hash'],
       verification_path='verified.md',verification_evidence=(v/'verified.md').read_text(),verification_kind='user_acceptance',observed_result='accepted',acceptance_source=acceptance_fixture(v)))
   self.assertIn('Birim adlarını',context(v,'rapor'));self.assertEqual(context_details(v,'rapor')['diagnostics'],[]);self.assertEqual(backlog(v),[])
   method.write_text('Değişmiş talimat içeriği.')
   self.assertEqual(context(v,'rapor'),'')
   self.assertEqual(context_details(v,'rapor')['diagnostics'],[dict(id='units',reason='method_changed')])
   entry=backlog(v)[0];self.assertTrue(entry['instruction_target']);self.assertEqual(entry['recheck_reason'],'method_changed')

 def test_routing_after_first_turn_and_no_block(self):
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'zihin').mkdir();(v/'komuta').mkdir()
   (v/'source.md').write_text('Eski maskot yanlış kullanıldı.')
   (v/'komuta/method.md').write_text('Kimlik ve tasarım referansını ayır.')
   row=dict(id='thumbnail-reference-role-boundaries',title='Referans',triggers=['kapak'],status='proposed',source_path='source.md',evidence='Eski maskot yanlış kullanıldı.',method_path='komuta/method.md',source_content_hash=statement_hash((v/'source.md').read_text()),implementation_status='applied',implementation_hash=statement_hash((v/'komuta/method.md').read_text()))
   (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(row)+'\n')
   self.assertEqual(context(v,'hava nasıl'), '')
   self.assertIn('Kimlik ve tasarım',context(v,'kapak üret'))
   self.assertEqual(context(v,'kapak üret',budget=5),'')
   hook(v,dict(hook_event_name='UserPromptSubmit',session_id='s',turn_id='1',prompt='selam'))
   result=hook(v,dict(hook_event_name='UserPromptSubmit',session_id='s',turn_id='2',prompt='kapak üret'))
   self.assertIn('Kimlik ve tasarım',result['hookSpecificOutput']['additionalContext'])
   self.assertNotIn('decision',result)
   self.assertEqual(hook(v,dict(hook_event_name='Stop',session_id='s',turn_id='2')), {})
   self.assertEqual(backlog(v)[0]['implementation_status'],'applied')
   (v/'komuta/method.md').write_text('Yöntem onaydan sonra değişti.')
   self.assertEqual(context(v,'kapak üret'), '')
   (v/'source.md').write_text('Değişmiş kaynak')
   self.assertEqual(context(v,'kapak üret'),'')

 def test_source_revision_cancellation_requires_explicit_review(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'komuta').mkdir();(v/'zihin').mkdir()
   quote='Dışa aktarımda önce kolon türlerini denetle.'
   (v/'source.md').write_text(quote);(v/'komuta/method.md').write_text('Kolon türlerini denetle.')
   data=dict(id='export',title='Kolon yöntemi',status='proposed',source_path='source.md',evidence=quote,actor='reviewer',triggers=['dışa aktarım'],method_path='komuta/method.md',implementation_hash=statement_hash((v/'komuta/method.md').read_text()))
   first=put(v,'lesson',data)
   self.assertEqual(first['source_content_hash'],statement_hash(quote))
   self.assertIn('Kolon türlerini',context(v,'dışa aktarım'))
   (v/'source.md').write_text(quote+'\nBu yöntemi iptal ettim.')
   self.assertEqual(context(v,'dışa aktarım'),'')
   # An explicitly reviewed rejection must not reactivate the lesson.
   put(v,'lesson',dict(data,status='rejected',expected_version=first['version']))
   self.assertEqual(context(v,'dışa aktarım'),'')

 def test_legacy_requires_review_and_harmless_append_needs_rebind(self):
  from is_ve_ders import put
  with tempfile.TemporaryDirectory() as tmp:
   v=Path(tmp);(v/'zihin').mkdir()
   (v/'source.md').write_text('Raporu yayınlamadan birim adlarını denetle.')
   (v/'method.md').write_text('Birim adlarını denetle.')
   row=dict(id='units',title='Birimler',status='proposed',source_path='source.md',evidence=(v/'source.md').read_text(),actor='reviewer',triggers=['rapor'],method_path='method.md',implementation_hash=statement_hash((v/'method.md').read_text()),version=1)
   (v/'zihin/ders-durumu.jsonl').write_text(json.dumps(row)+'\n')
   self.assertEqual(context(v,'rapor'),'')
   reviewed=put(v,'lesson',dict(row,expected_version=1))
   self.assertIn('Birim adlarını',context(v,'rapor'))
   (v/'source.md').write_text((v/'source.md').read_text()+'\nBağımsız ek not.')
   self.assertEqual(context(v,'rapor'),'')
   put(v,'lesson',dict(reviewed,expected_version=2))
   self.assertIn('Birim adlarını',context(v,'rapor'))
