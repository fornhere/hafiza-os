import copy
import tempfile
import unittest
from pathlib import Path
import bilgi_agi as b


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.v=Path(self.tmp.name);(self.v/'gelen-kutusu').mkdir()
        self.source=self.v/'gelen-kutusu/source.md';self.source.write_text('Kullanıcı: Bu sunumun tipografisini beğendim ve koruyalım.')
        self.d=dict(id='sunum-tercihi',title='Sunum tipografisi',kind='preference',statement='Sunum tipografisini koru.',scope='user',domains=['sunum'],status='reviewed',sources=[dict(path='gelen-kutusu/source.md',sha256=b.digest(self.source),evidence='Bu sunumun tipografisini beğendim ve koruyalım.')],reviewed_by='review-agent',review_note='Exact user feedback reviewed.')
    def register(self):return b.register(self.v,self.d,True)
    def test_source_change_excluded(self):
        self.register();self.assertEqual(len(b.retrieve(self.v,'sunum tipografisi')['records']),1)
        self.source.write_text('Changed');self.assertFalse(b.retrieve(self.v,'sunum')['records'])
    def test_domain_and_scope(self):
        self.register();self.assertFalse(b.retrieve(self.v,'sevdiğim tarzda site')['records'])
        self.assertFalse(b.retrieve(self.v,'sevdiğim tarz')['records'])
        self.d['id']='project-note';self.d['scope']='project:one';b.register(self.v,self.d,True)
        self.assertEqual(len(b.retrieve(self.v,'sunum',project_id='two')['records']),1)
    def test_established_topics_explicit_scope_and_no_generic_dump(self):
        aliases={'twitter':('Twitter','tweet'), 'proje':('proje','Orvant'),
                 'video':('video','YouTube','çekim')}
        for domain,words in aliases.items():
            for project in ('one','two'):
                row=copy.deepcopy(self.d)
                row.update(id=f'{domain}-{project}',domains=[domain],scope=f'project:{project}',
                           title=' '.join(words),statement=' '.join(words)+' için kaynaklı yöntem.')
                b.register(self.v,row,True)
        for domain,words in aliases.items():
            for word in words:
                with self.subTest(word=word):
                    result=b.retrieve(self.v,word+' yöntemi',project_id='one')
                    self.assertEqual([r['id'] for r in result['records']],[domain+'-one'])
                    self.assertFalse(b.retrieve(self.v,word,project_id='other')['records'])
        self.assertFalse(b.retrieve(self.v,'sevdiğim yöntem',project_id='one')['records'])
        self.assertFalse(b.retrieve(self.v,'x',project_id='one')['records'])

    def test_example_acceptance_explicit(self):
        p=self.v/'slide.html';p.write_text('slide')
        self.d['examples']=[dict(path=str(p),sha256=b.digest(p),role='Typography reference only',acceptance='accepted',evidence_source=0)]
        with self.assertRaisesRegex(ValueError,'acceptance_evidence'):self.register()
        self.d['examples'][0]['acceptance']='unknown';self.register()
        self.assertEqual(b.retrieve(self.v,'sunum')['records'][0]['examples'][0]['acceptance'],'unknown')
        p.write_text('changed');self.assertFalse(b.retrieve(self.v,'sunum')['records'])
    def test_idempotency_and_manual_edits(self):
        result=self.register();self.assertFalse(self.register()['changed'])
        p=Path(result['path']);p.write_text(p.read_text()+'Manual note\n')
        with self.assertRaisesRegex(ValueError,'manually_changed'):self.register()
        self.assertFalse(b.retrieve(self.v,'sunum')['records'])
        self.assertIn('Manual note',p.read_text())
    def test_revision_archive(self):
        result=self.register();self.d['statement']='Sunum için tipografiyi koru.'
        with self.assertRaisesRegex(ValueError,'expected_version'):self.register()
        self.d['expected_version']=result['version'];self.register()
        self.assertEqual(len(list((self.v/'bilgi/.history/sunum-tercihi').glob('*.md'))),1)
    def test_path_traversal(self):
        for value in ('../outside.md','/tmp/out.md','..\\outside.md'):
            d=copy.deepcopy(self.d);d['sources'][0]['path']=value
            with self.assertRaises(ValueError):b.register(self.v,d)
    def test_relations_and_stale_target(self):
        self.register();other=copy.deepcopy(self.d);other['id']='related';other['relations']=[dict(target=self.d['id'],reason='Same typography feedback')]
        b.register(self.v,other,True)
        p=self.v/'bilgi/sunum-tercihi.md';p.write_text(p.read_text()+'manual')
        result=b.retrieve(self.v,'sunum');self.assertEqual(len(result['records']),1)
        self.assertNotIn('İlişki:',result['text']);self.assertTrue(any('relation_unverified' in x for x in result['diagnostics']))
    def test_review_states_budget(self):
        self.d['status']='proposed';self.register();self.assertFalse(b.retrieve(self.v,'sunum')['records'])
        self.assertLessEqual(len(b.retrieve(self.v,'sunum',budget=20)['text']),20)
    def test_source_coverage_journal(self):
        self.assertEqual(len(b.status(self.v)['unreviewed_sources']),1)
        self.register();entry=dict(path='gelen-kutusu/source.md',sha256=b.digest(self.source),outcome='linked',record_ids=[self.d['id']],reason='Reviewed user preference',reviewed_by='review-agent')
        b.assess_source(self.v,entry,True);self.assertEqual(len(b.status(self.v)['reviewed_sources']),1)
        self.source.write_text('new source');self.assertEqual(len(b.status(self.v)['unreviewed_sources']),1)
    def test_budget_omission_is_not_missing_knowledge(self):
        self.d['statement']='Sunum tipografisi '+('uzun açıklama '*40);self.register()
        result=b.retrieve(self.v,'sunum',budget=200)
        self.assertFalse(result['records']);self.assertIn('bütçesine',result['text'])
    def test_assessment_idempotent(self):
        entry=dict(path='gelen-kutusu/source.md',sha256=b.digest(self.source),outcome='no_relevant_knowledge',record_ids=[],reason='No reusable claim',reviewed_by='review-agent')
        b.assess_source(self.v,entry,True);b.assess_source(self.v,entry,True)
        self.assertEqual(len((self.v/'bilgi/.reviews.jsonl').read_text().splitlines()),1)
    def test_deferred_not_complete(self):
        entry=dict(path='gelen-kutusu/source.md',sha256=b.digest(self.source),outcome='deferred',record_ids=[],reason='Needs exact user passage',reviewed_by='review-agent')
        b.assess_source(self.v,entry,True);s=b.status(self.v)
        self.assertEqual(len(s['deferred_sources']),1);self.assertFalse(s['reviewed_sources'])


if __name__=='__main__':unittest.main()
