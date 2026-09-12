import datetime as dt
import tempfile
import unittest
from pathlib import Path

import hafiza as h
import is_ve_ders as w


class Work(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        (self.vault / 'kaynak.md').write_text('İşin uygulaması tamamlandı, testler geçti.')
        self.row = dict(id='test', title='Kaynaklı görev', status='active', next_step='Doğrula',
            source_path='kaynak.md', evidence='İşin uygulaması tamamlandı', actor='test',
            last_verified=dt.date.today().isoformat())

    def test_done_disappears_from_brief_but_history_remains(self):
        w.put(self.vault, 'task', self.row)
        self.assertEqual(1, len(w.brief(self.vault)))
        w.put(self.vault, 'task', dict(self.row, status='done', expected_version=1))
        self.assertEqual([], w.brief(self.vault))
        self.assertEqual(2, len(h.load_jsonl(self.vault / w.TASKS)))
        w.render(self.vault)
        self.assertIn('Kapanan işler', (self.vault / 'zihin/açık-işler.md').read_text())

    def test_stale_and_unconfirmed_not_presented_as_current(self):
        w.put(self.vault, 'task', dict(self.row, last_verified='2020-01-01'))
        self.assertEqual([], w.brief(self.vault))
        w.put(self.vault, 'task', dict(self.row, expected_version=1, status='needs_confirmation'))
        self.assertEqual([], w.brief(self.vault))

    def test_stale_writer_and_missing_source_rejected(self):
        w.put(self.vault, 'task', self.row)
        with self.assertRaisesRegex(ValueError, 'sürüm'):
            w.put(self.vault, 'task', self.row)
        with self.assertRaisesRegex(ValueError, 'kanıt'):
            w.put(self.vault, 'task', dict(self.row, evidence='Kaynakta yer almayan sonuç'))

    def test_lesson_requires_target_hash_and_verification(self):
        proposal = dict(self.row, status='proposed')
        w.put(self.vault, 'lesson', proposal)
        with self.assertRaises(ValueError):
            w.put(self.vault, 'lesson', dict(proposal, status='verified', expected_version=1))
        w.put(self.vault, 'lesson', dict(proposal, status='verified', expected_version=1,
            target_path='kaynak.md', target_hash=h.statement_hash((self.vault / 'kaynak.md').read_text()),
            verification_path='kaynak.md', verification_evidence='İşin uygulaması tamamlandı, testler geçti.'))
        self.assertEqual('verified', w.latest(self.vault, 'lesson')['test']['status'])


class Retrieval(unittest.TestCase):
    def test_expired_future_private_quarantined_are_excluded(self):
        base = dict(status='active', scope='user')
        self.assertTrue(h.retrievable(base, 'project:youtube'))
        for more in [dict(valid_to='2020-01-01'), dict(valid_from='2999-01-01'),
            dict(valid_to='bozuk'), dict(sensitivity='private'), dict(status='superseded'), dict(scope='project:other')]:
            self.assertFalse(h.retrievable(dict(base, **more), 'project:youtube'))

    def test_evaluation_reports_budget_loss_separately(self):
        from test_hafiza import FakeMem0
        c = FakeMem0([], search_results=[dict(id='one', memory='Uzun kaynaklı tercih metni',
            metadata=dict(memory_id='one', scope='user', status='active'))])
        r = h.evaluate_retrieval(c, [dict(id='budget', query='tercih', expected_memory_ids=['one'], char_budget=5)])
        self.assertEqual(1, r['passed']); self.assertEqual(0, r['context_passed'])
        self.assertFalse(h.evaluation_passes(r))


if __name__ == '__main__': unittest.main()
