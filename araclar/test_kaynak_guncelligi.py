import json
from pathlib import Path
import tempfile
import unittest
import hafiza as h

class SourceVersions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);(self.v/'zihin').mkdir()
        self.source=self.v/'zihin/kaynak.md';self.source.write_text('Kullanıcı: Sunumlarda koyu zemin istiyorum.')
        self.kw=dict(statement='Kullanıcı koyu sunum zemini tercih eder.',kind='semantic',scope='user',subject_key='slides.background',source_path='zihin/kaynak.md',source_anchor='Kullanıcı',confidence='explicit-user',sensitivity='normal',proposed_by='test',evidence='Sunumlarda koyu zemin istiyorum.')
    def record(self):
        cid=h.add_candidate(self.v,**self.kw)['candidate_id']
        return h.promote_candidate(self.v,cid,memory_id='pref',reviewed_by='human-fixture',apply=True)['record']
    def test_promoted_source_edit_is_not_retrievable(self):
        r=self.record();self.assertEqual([],h.context_record_errors(self.v,r))
        self.source.write_text('Kullanıcı: Önceki tercihi iptal ettim, açık zemin istiyorum.')
        self.assertTrue(h.context_record_errors(self.v,r));self.assertTrue(h.validate_catalog(self.v,[r]))
    def test_candidate_source_changed_even_if_quote_remains_needs_review(self):
        cid=h.add_candidate(self.v,**self.kw)['candidate_id']
        self.source.write_text(self.source.read_text()+'\nYukarıdaki tercihi iptal ettim.')
        with self.assertRaisesRegex(ValueError,'sürümü'):
            h.promote_candidate(self.v,cid,memory_id='pref',reviewed_by='test',apply=True)
    def test_legacy_binding_is_explicit_versioned_and_does_not_rewrite_catalog(self):
        r=self.record();r.pop('source_content_hash');h._write_jsonl(self.v/h.CATALOG_PATH,[r])
        self.assertTrue(h.context_record_errors(self.v,r))
        before=(self.v/h.CATALOG_PATH).read_bytes()
        d=dict(memory_id='pref',reviewed_by='reviewer',reason='Kaynak cümlesi kayıt ifadesini açıkça destekliyor.',evidence=self.kw['evidence'],expected_source_hash=h.statement_hash(self.source.read_text()))
        h.bind_source(self.v,d);self.assertFalse((self.v/h.SOURCE_BINDINGS).exists())
        h.bind_source(self.v,d,True);self.assertEqual([],h.context_record_errors(self.v,r))
        self.assertEqual(before,(self.v/h.CATALOG_PATH).read_bytes())
        self.source.write_text('Başka bir kaynak sürümü.');self.assertTrue(h.context_record_errors(self.v,r))
        with self.assertRaises(ValueError):h.bind_source(self.v,d,True)
    def test_consolidator_cannot_promote_summary_only_evidence(self):
        cid=h.add_candidate(self.v,**self.kw)['candidate_id']
        with self.assertRaisesRegex(ValueError,'özgün'):
            h.promote_candidate(self.v,cid,memory_id='pref',reviewed_by='codex-consolidator',apply=True)
        self.assertEqual([],h.load_catalog(self.v))

    def test_reviewed_rebind_repairs_pinned_record_after_harmless_append(self):
        r=self.record();self.source.write_text(self.source.read_text()+'\nBaşka not eklendi.')
        self.assertTrue(h.context_record_errors(self.v,r))
        h.bind_source(self.v,dict(memory_id='pref',reviewed_by='reviewer',reason='Eklenen not tercihi değiştirmiyor; kaynak yeniden incelendi.',evidence=self.kw['evidence'],expected_source_hash=h.statement_hash(self.source.read_text())),True)
        self.assertEqual([],h.context_record_errors(self.v,r))
        self.assertEqual([],h.validate_catalog(self.v,[r]))

    def test_cross_key_overlap_is_review_not_unconditional_eligible(self):
        old=dict(status='active',memory_id='m1',statement='Kullanıcı sunumlarda koyu zemin tercih eder.',subject_key='design.background')
        for statement in ('Sunum arka planlarında kullanıcının tercihi karanlık tonlardır.', 'Kullanıcı sunumlarda yalnız beyaz arka plan istiyor.'):
            result=h.assess_candidate(dict(statement=statement,subject_key='another.key'),[old])
            self.assertEqual('needs_semantic_review',result['result'])
