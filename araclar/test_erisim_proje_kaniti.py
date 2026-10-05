"""Project-name evidence and matcher cache in retrieval (synthetic data)."""
import unittest

import gorev_baglam as g


class ProjectEvidence(unittest.TestCase):
    def test_project_name_is_scope_not_topic_evidence(self):
        data = [{'memory_id': 'a', 'statement': 'Delta projesinde otonom yerel işler onaysız başlamaz.'},
                {'memory_id': 'b', 'statement': 'Kapak renkleri sade tutulur.'},
                {'memory_id': 'c', 'statement': 'Ses kaydı ölçülür.'}]
        project = {'id': 'delta-os', 'aliases': ['delta', 'kapak']}
        query = 'delta için bir rapor hazırla ve otonom çalışmayı anlat bana'
        self.assertEqual([r['memory_id'] for r in g.rank_records(data, query)], ['a'])
        terms = g.project_terms(project)
        self.assertIn('delta', terms)
        self.assertNotIn('kapak', terms)  # generic workflow alias stays topical
        self.assertEqual(g.rank_records(data, query, ignore=terms), [])
        self.assertEqual([r['memory_id'] for r in g.rank_records(data, 'delta otonom yerel işler', ignore=terms)], ['a'])

    def test_word_match_cache_keeps_results(self):
        g.word_match.cache_clear()
        first = [g.word_match('kapak', w) for w in ('kapaklarda', 'thumbnail', 'kabak')]
        second = [g.word_match('kapak', w) for w in ('kapaklarda', 'thumbnail', 'kabak')]
        self.assertEqual(first, [True, True, False])
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
