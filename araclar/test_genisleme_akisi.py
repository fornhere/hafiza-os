import json
import unittest
import test_cikti_kayit as outputs_fixture
import test_karar_gecmisi as history_fixture
from gorev_baglam import build_task_package


class Expansion(unittest.TestCase):
    def fixture(self):
        f=outputs_fixture.Outputs();f.setUp();self.addCleanup(f.doCleanups);f.task();return f
    def test_resume_has_done_output_and_drops_changed_file(self):
        f=self.fixture();p=build_task_package(f.v,'Atlas devam')
        self.assertEqual(p['capsule']['last_verified_output']['id'],'demo')
        self.assertIn(str(f.file),p['text']);self.assertIn('Doğrulanmış çıktı:',p['text'])
        f.file.write_text('changed')
        p=build_task_package(f.v,'Atlas devam')
        self.assertIsNone(p['capsule']['last_verified_output']);self.assertEqual(p['capsule']['outputs'],[])
        self.assertIn('Çıktı bağlantısı:',p['text'])
    def test_reuse_in_task_flow_has_sources_and_drops_changed_review(self):
        f=self.fixture();p=build_task_package(f.v,'Atlas CSV yeniden kullan')
        self.assertEqual(p['reuse']['status'],'proposed');self.assertIn('Öneri:',p['text'])
        f.review.write_text('changed')
        self.assertIsNone(build_task_package(f.v,'Atlas CSV yeniden kullan')['reuse'])
    def test_output_budget_whole_card_and_no_metadata_only_claim(self):
        f=self.fixture()
        for budget in (0,20,150,300,600):
            p=build_task_package(f.v,'Atlas devam',budget=budget)
            self.assertLessEqual(len(p['text']),budget)
            if p['capsule']['last_verified_output']:
                self.assertIn(str(f.file),p['text']);self.assertIn(f.output['verified_at'],p['text'])
    def test_decisions_superseded_remain_historical_in_package(self):
        f=history_fixture.History();f.setUp();self.addCleanup(f.doCleanups)
        (f.v/'komuta').mkdir();(f.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[dict(id='atlas',aliases=['Atlas'])]}))
        f.row('old','superseded',scope='project:atlas');f.row('new',scope='project:atlas',supersedes='old')
        p=build_task_package(f.v,'Atlas karar geçmişi')
        entries=p['decision_history']['entries'];self.assertEqual(len(entries),2)
        self.assertFalse(next(e for e in entries if e['id']=='old')['current'])
        self.assertNotIn('Güncel kayıt:',p['text'])
    def test_ambiguous_decisions_not_reintroduced_as_current_cards(self):
        f=history_fixture.History();f.setUp();self.addCleanup(f.doCleanups)
        (f.v/'komuta').mkdir();(f.v/'komuta/gorev-baglam.json').write_text(json.dumps({'projects':[dict(id='atlas',aliases=['Atlas'])]}))
        f.row('one',scope='project:atlas');f.row('two',scope='project:atlas')
        p=build_task_package(f.v,'Atlas eski karar devam')
        self.assertIn('güncel karar varsayma',p['text']);self.assertEqual(p['capsule']['facts'],[])
        self.assertFalse(any(e['current'] for e in p['decision_history']['entries']))
    def test_new_optional_content_does_not_displace_asset_guard(self):
        from test_gorev_baglam import Package
        f=Package();f.setUp();self.addCleanup(f.doCleanups)
        p=build_task_package(f.v,'kapak devam',budget=610)
        self.assertIn('input-check',p['selected_ids'])


if __name__=='__main__':unittest.main()
