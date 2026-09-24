import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import ders_baglam
from gorev_baglam import build_task_package, select_projects, task_intent, inflected


class SkillRouting(unittest.TestCase):
    def setUp(self):
        self.projects = [
            dict(id='proje-a', aliases=['proje-a'], roots=['/projects/proje-a']),
            dict(id='hafiza', aliases=['ikinci beyin', 'hafıza sistemi'], roots=['/projects/ikinci beyin']),
            dict(id='youtube', aliases=['kapak'], roots=[])]
        self.link = '[$ornek-skill](/projects/proje-a/skills/ornek-skill/SKILL.md)'

    def ids(self, query, cwd=None):
        rows, _ = select_projects(self.projects, query, cwd)
        return [row['id'] for row in rows]

    def test_original_skill_link_keeps_actual_project(self):
        self.assertEqual(self.ids(self.link + ' ikinci beyin mem0 + obsidian yapısını incele'), ['hafiza'])
        self.assertEqual(self.ids(self.link + ' hafıza sistemi yapısını incele'), ['hafiza'])
        self.assertEqual(self.ids(self.link + ' incele', '/projects/ikinci beyin'), ['hafiza'])
        self.assertEqual(self.ids(self.link + ' incele'), [])

    def test_second_brain_vowel_loss_is_finite(self):
        for word in ('beyin', 'beyni', 'beynimizi'):
            with self.subTest(word=word):
                self.assertTrue(inflected('beyin', word))
                self.assertEqual(self.ids('ikinci ' + word + ' geliştirelim'), ['hafiza'])
        for word in ('beyaz', 'beylik', 'beyn'):
            with self.subTest(word=word):
                self.assertFalse(inflected('beyin', word))
                self.assertEqual(self.ids('ikinci ' + word + ' geliştirelim'), [])
        self.assertEqual(self.ids(self.link + ' ikinci beynimizi geliştirelim'), ['hafiza'])

    def test_actual_project_and_ordinary_paths_are_preserved(self):
        for query in ('proje-a projesini incele', '/projects/proje-a dosyasını incele',
                      '[belge](/projects/proje-a/README.md) incele',
                      '[belge](/projects/proje-a/SKILL.md) incele'):
            self.assertEqual(self.ids(query), ['proje-a'])
        self.assertEqual(self.ids(self.link + ' proje-a projesini incele'), ['proje-a'])
        self.assertEqual(self.ids(self.link + ' proje-a ve ikinci beyin karşılaştır'), ['proje-a', 'hafiza'])
        self.assertEqual(task_intent('[$ornek-skill](/ordinary) [doc](/proje-a/SKILL.md)'),
                         '[$ornek-skill](/ordinary) [doc](/proje-a/SKILL.md)')

    def test_skill_xml_metadata_is_not_user_topic(self):
        block = '<skill><name>ornek-skill</name><path>/projects/proje-a/SKILL.md</path>kapak geçmiş kararlar</skill>'
        self.assertEqual(self.ids(block + ' ikinci beyin incele'), ['hafiza'])
        self.assertEqual(task_intent(block), 'ornek-skill')
        self.assertEqual(task_intent('<skill>proje-a incele</skill>'), '<skill>proje-a incele</skill>')
        self.assertEqual(task_intent('[$ornek-skill](</projects/proje-a/space dir/SKILL.md>)'), '$ornek-skill')

    def test_all_package_stages_receive_same_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            vault = Path(directory)
            (vault / 'komuta').mkdir()
            (vault / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': self.projects}))
            noisy = '[$ornek-skill](/projects/proje-a/kapak/geçmiş kararlar/SKILL.md) ikinci beyin incele'
            with patch.object(ders_baglam, 'context', return_value='') as method:
                package = build_task_package(vault, noisy)
            self.assertEqual(package['project_id'], 'hafiza')
            self.assertEqual(package['workflow_ids'], [])
            self.assertFalse(package['history']['requested'])
            self.assertEqual(method.call_args.args[1], '$ornek-skill ikinci beyin incele')


if __name__ == '__main__':
    unittest.main()
