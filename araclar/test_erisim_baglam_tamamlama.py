"""Previous-turn completion and project-name evidence in retrieval (synthetic data)."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import bilgi_agi as b
import gorev_baglam as g
import hafiza as h


def rows():
    noise = [{'memory_id': f'n{i}', 'statement': f'Genel ölçüm notu {i} ses kaydı düzeni.'} for i in range(12)]
    target = {'memory_id': 'kapak', 'statement': 'Kapaklarda referansı kopyalamadan özgün kompozisyon kurulur.'}
    return noise + [target]


class CatalogCompletion(unittest.TestCase):
    def test_previous_turn_completes_but_never_starts_a_match(self):
        data = rows()
        current = 'kanka bunlara bak bakalım yine kapak aynı olmuş çok sıkıcı'
        previous = 'limon karakterli referansı gibi olmalı'
        self.assertEqual(g.rank_records(data, current), [])
        self.assertEqual([r['memory_id'] for r in g.rank_records(data, current, context=previous)], ['kapak'])
        # Context alone (no anchor in the current query) selects nothing.
        self.assertEqual(g.rank_records(data, 'tamam devam edelim şimdi', context=previous + ' kapak'), [])
        # A strong current match is unchanged by an unrelated previous turn.
        strong = g.rank_records(data, 'kapak referansı', context='ses kaydı düzeni')
        self.assertEqual([r['memory_id'] for r in strong], ['kapak'])

    def test_previous_turn_adds_at_most_one_record(self):
        data = rows() + [{'memory_id': 'kapak2', 'statement': 'Kapak referansı için ikinci not.'}]
        current = 'kanka bunlara bak bakalım yine kapak aynı olmuş çok sıkıcı'
        got = g.rank_records(data, current, context='limon karakterli referansı gibi olmalı')
        self.assertEqual(len(got), 1)

    def test_context_repeating_query_words_adds_no_evidence(self):
        data = rows()
        current = 'kanka bunlara bak bakalım yine kapak aynı olmuş çok sıkıcı'
        self.assertEqual(g.rank_records(data, current, context='kapakları yine değiştir'), [])

    def test_order_independent_with_context(self):
        data = rows()
        args = ('kanka bunlara bak bakalım yine kapak aynı olmuş çok sıkıcı',)
        self.assertEqual(g.rank_records(data, *args, context='referansı'),
                         g.rank_records(data[::-1], *args, context='referansı'))


class NoteCompletion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.v = Path(self.tmp.name).resolve(); (self.v / 'gelen-kutusu').mkdir()
        source = self.v / 'gelen-kutusu/source.md'
        source.write_text('Kullanıcı: çekimi freestyle yapalım ama çekim kartları olsun.')
        b.register(self.v, dict(id='freestyle-kart', title='Freestyle çekim kartları', kind='decision',
                                statement='Freestyle anlatımda bağlamdan kopmamak için kartlar kullanılır.',
                                scope='project:kanal', domains=['sunum'], status='reviewed',
                                sources=[dict(path='gelen-kutusu/source.md', sha256=b.digest(source),
                                              evidence='çekimi freestyle yapalım ama çekim kartları olsun.')],
                                reviewed_by='review-agent', review_note='Synthetic reviewed note.'), True)

    def test_previous_turn_completes_one_anchor(self):
        query = 'tamam da bu kadar freestyle olmaz nereden gireceğim'
        self.assertFalse(b.retrieve(self.v, query, project_id='kanal')['records'])
        got = b.retrieve(self.v, query, project_id='kanal', context='bağlamdan kopmamak lazım')
        self.assertEqual([r['id'] for r in got['records']], ['freestyle-kart'])
        self.assertFalse(b.retrieve(self.v, 'tamam devam', project_id='kanal',
                                    context='freestyle bağlamdan kopmamak')['records'])


class HookPackage(unittest.TestCase):
    def test_local_package_passes_previous_turn_and_drops_secret(self):
        import jev_client
        seen = []
        def fake_rank(rows, query, **kwargs):
            seen.append(kwargs.get('context')); return []
        with tempfile.TemporaryDirectory() as temp, patch.object(g, 'rank_records', fake_rank), jev_client.disabled():
            v = Path(temp).resolve(); (v / 'komuta').mkdir()
            (v / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': []}))
            per_build = []
            for previous in ('önceki tur konusu', 'token ' + 'sk-' + 'abcdefghijklmnopqrstuvwxyz123456', None):
                seen.clear()
                g.build_task_package(v, 'soru', previous_user=previous, budget=500)
                per_build.append(set(seen))
        # Ranking may run more than once per package (query expansion); each
        # call sees the safe previous turn, and a secret one never reaches it.
        self.assertEqual(per_build, [{'önceki tur konusu'}, {None}, {None}])


class ContextCli(unittest.TestCase):
    def test_previous_flag_reaches_ranking_and_ignores_secret(self):
        seen = []
        def fake_rank(rows, query, **kwargs):
            seen.append(kwargs.get('context')); return []
        with tempfile.TemporaryDirectory() as temp, patch('gorev_baglam.rank_records', fake_rank), \
                patch.object(h, 'knowledge_notes', return_value=[]):
            v = Path(temp).resolve(); (v / 'komuta').mkdir()
            (v / 'komuta/gorev-baglam.json').write_text(json.dumps({'projects': []}))
            for previous in ('önceki tur konusu', 'token ' + 'sk-' + 'abcdefghijklmnopqrstuvwxyz123456'):
                with redirect_stdout(io.StringIO()):
                    h.main(['--vault', str(v), 'context', 'soru', '--local', '--cwd', '/nonexistent',
                            '--previous', previous])
        self.assertEqual(seen[0], 'önceki tur konusu')
        self.assertIsNone(seen[1])


if __name__ == '__main__':
    unittest.main()
