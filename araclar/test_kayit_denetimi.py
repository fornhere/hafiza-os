"""Geçici kasalarda kapsam ve active çelişki denetimi regresyonları."""

import contextlib
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import hafiza
import hafiza_dongusu
import bilgi_agi
import jev_client
import jev_review
import kayit_denetimi as audit
import konsolidasyon


class ScopeAudit(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name)
        self.registry = self.vault / 'komuta/gorev-baglam.json'
        self.registry.parent.mkdir()
        self.registry.write_text(json.dumps({'projects': [{'id': 'youtube'}]}), encoding='utf-8')

    def record(self, memory_id='m1', **overrides):
        row = dict(memory_id=memory_id, status='active', subject_key='video.style',
                   scope='user', source_path='projeler/youtube/not.md',
                   sensitivity='normal', statement='Örnek projede kısa başlık tercihi.')
        return dict(row, **overrides)

    def catalog(self, *rows):
        hafiza._write_jsonl(self.vault / hafiza.CATALOG_PATH, list(rows))

    def candidate(self, candidate_id='c1', **overrides):
        row = self.record(**overrides)
        del row['memory_id']
        row['candidate_id'] = candidate_id
        hafiza._append_jsonl(self.vault / hafiza.CANDIDATE_PATH, row)

    def snapshot(self, vault):
        return {path.relative_to(vault).as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                for path in vault.rglob('*')}

    def test_registered_project(self):
        self.catalog(self.record())
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['suspects'], [dict(
            memory_id='m1', status='active', subject_key='video.style',
            source_path='projeler/youtube/not.md', project_dir='youtube',
            suggested_scope='project:youtube', registered_project=True,
            reason='scope=user ama kaynak projeler/youtube/ altında')])
        self.assertEqual(result['check'], 'scope_audit')
        self.assertEqual(result['checked_records'], 1)
        self.assertEqual(result['active_suspect_count'], 1)
        self.assertEqual(result['pending_candidates'], [])
        self.assertEqual(result['diagnostics'], [])
        self.assertIs(result['canonical_writes'], False)
        self.assertEqual(result['note'], 'Salt okunur şüphe listesi; kapsam değişikliği insan incelemesi ve yeni aday/supersede akışıyla yapılır.')

    def test_unregistered_project(self):
        self.catalog(self.record(source_path='projeler/bilinmeyen/x.md'))
        suspect = audit.scope_audit(self.vault)['suspects'][0]
        self.assertEqual(suspect['project_dir'], 'bilinmeyen')
        self.assertIsNone(suspect['suggested_scope'])
        self.assertIs(suspect['registered_project'], False)

    def test_normalized_paths(self):
        sources = [r'projeler\youtube\not.md', './projeler/youtube/not.md',
                   r'.\projeler\youtube\not.md', '././projeler/youtube/not.md']
        for index, source in enumerate(sources):
            self.candidate(f'c{index}', source_path=source)
        self.catalog(*(self.record(f'm{index}', source_path=source)
                       for index, source in enumerate(sources)))
        result = audit.scope_audit(self.vault)
        for key in ('suspects', 'pending_candidates'):
            self.assertEqual(len(result[key]), len(sources))
            for suspect in result[key]:
                self.assertEqual(suspect['source_path'], 'projeler/youtube/not.md')
                self.assertEqual(suspect['suggested_scope'], 'project:youtube')

    def test_non_project_sources_and_scopes(self):
        rows = [self.record('project', scope='project:youtube'),
                self.record('user', source_path='zihin/tercihler.md'),
                self.record('index', source_path='projeler/OKU.md'),
                self.record('directory', source_path='projeler/youtube/'),
                self.record('prefix', source_path='arsiv/projeler/youtube/not.md')]
        self.catalog(*rows)
        for row in rows:
            self.candidate(row['memory_id'], scope=row['scope'], source_path=row['source_path'])
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['checked_records'], len(rows))
        self.assertEqual(result['suspects'], [])
        self.assertEqual(result['active_suspect_count'], 0)
        self.assertEqual(result['pending_candidates'], [])

    def test_all_statuses_and_active_count(self):
        statuses = ['active', 'superseded', 'quarantined', 'deleted']
        self.catalog(*(self.record(f'm{index}', status=status) for index, status in enumerate(statuses)),
                     self.record('outside', source_path='zihin/tercihler.md'))
        result = audit.scope_audit(self.vault)
        self.assertEqual([row['status'] for row in result['suspects']], statuses)
        self.assertEqual(result['active_suspect_count'], 1)
        self.assertEqual(result['checked_records'], 5)

    def test_pending_candidates(self):
        self.candidate('pending', source_path='projeler/youtube/alt/not.md')
        self.candidate('unknown', source_path='projeler/bilinmeyen/x.md')
        self.candidate('terminal')
        self.candidate('blocked')
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.promoted', candidate_id='terminal'))
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.deferred', candidate_id='blocked',
                                 at=dt.datetime.now(dt.timezone.utc).isoformat()))
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['pending_candidates'], [
            dict(candidate_id='pending', subject_key='video.style',
                 source_path='projeler/youtube/alt/not.md', project_dir='youtube',
                 suggested_scope='project:youtube'),
            dict(candidate_id='unknown', subject_key='video.style',
                 source_path='projeler/bilinmeyen/x.md', project_dir='bilinmeyen',
                 suggested_scope=None),
        ])
        self.assertEqual(result['checked_records'], 0)
        self.assertEqual(result['active_suspect_count'], 0)

    def test_deterministic_order(self):
        rows = [self.record('m3'), self.record('m1'), self.record('m2')]
        self.catalog(*rows)
        for ident in ('c3', 'c1', 'c2'):
            self.candidate(ident)
        result = audit.scope_audit(self.vault)
        self.assertEqual([row['memory_id'] for row in result['suspects']], ['m1', 'm2', 'm3'])
        self.assertEqual([row['candidate_id'] for row in result['pending_candidates']], ['c1', 'c2', 'c3'])
        self.catalog(*reversed(rows))
        self.assertEqual(result, audit.scope_audit(self.vault))

    def test_sensitive_statements_omitted(self):
        sensitivities = ['normal', 'private', 'secret']
        self.catalog(*(self.record(f'm{index}', sensitivity=sensitivity,
                                  statement=f'Katalog hassas örnek {index}')
                       for index, sensitivity in enumerate(sensitivities)))
        for index, sensitivity in enumerate(sensitivities):
            self.candidate(f'c{index}', sensitivity=sensitivity, statement=f'Aday hassas örnek {index}')
        result = audit.scope_audit(self.vault)
        self.assertEqual(len(result['suspects']), 3)
        self.assertEqual(len(result['pending_candidates']), 3)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('statement', serialized)
        self.assertNotIn('hassas örnek', serialized)

    def test_read_only(self):
        self.catalog(self.record())
        self.candidate()
        hafiza._append_jsonl(self.vault / hafiza.EVENT_PATH,
                            dict(event_type='candidate.created', candidate_id='c1'))
        for label in ('populated', 'empty'):
            with self.subTest(vault=label), tempfile.TemporaryDirectory() as empty:
                vault = self.vault if label == 'populated' else Path(empty)
                before = self.snapshot(vault)
                result = audit.scope_audit(vault)
                self.assertEqual(before, self.snapshot(vault))
                self.assertIs(result['canonical_writes'], False)

    def test_missing_registry(self):
        self.registry.unlink()
        self.catalog(self.record())
        self.candidate()
        before = self.snapshot(self.vault)
        result = audit.scope_audit(self.vault)
        self.assertEqual(result['diagnostics'], ['project_registry_unreadable'])
        self.assertIsNone(result['suspects'][0]['suggested_scope'])
        self.assertIs(result['suspects'][0]['registered_project'], False)
        self.assertIsNone(result['pending_candidates'][0]['suggested_scope'])
        self.assertEqual(before, self.snapshot(self.vault))

    def test_unreadable_registry(self):
        self.catalog(self.record())
        broken = [b'{broken', b'\xff', b'null', b'[]', b'{}', b'{"projects": null}',
                  b'{"projects": {}}', b'{"projects": [null]}', b'{"projects": [{}]}',
                  b'{"projects": [{"id": []}]}', b'{"projects": [{"id": ""}]}',
                  b'{"projects": [{"id": "youtube"}, {}]}']
        for payload in broken:
            with self.subTest(payload=payload):
                self.registry.write_bytes(payload)
                before = self.snapshot(self.vault)
                result = audit.scope_audit(self.vault)
                self.assertEqual(result['diagnostics'], ['project_registry_unreadable'])
                self.assertIsNone(result['suspects'][0]['suggested_scope'])
                self.assertIs(result['suspects'][0]['registered_project'], False)
                self.assertEqual(before, self.snapshot(self.vault))

    def check_cli(self, module, command):
        self.catalog(self.record())
        self.candidate()
        before = self.snapshot(self.vault)
        output = io.StringIO()
        argv = [module.__file__, '--vault', str(self.vault), command]
        with patch.object(sys, 'argv', argv), contextlib.redirect_stdout(output):
            module.main()
        result = audit.scope_audit(self.vault)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertEqual(output.getvalue(), json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        self.assertEqual(before, self.snapshot(self.vault))

    def test_kapsam_cli(self):
        self.check_cli(audit, 'kapsam')

    def test_scope_audit_cli(self):
        self.check_cli(konsolidasyon, 'scope-audit')


class ActiveConflictAudit(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.vault = Path(temporary.name)
        (self.vault / 'komuta').mkdir()
        (self.vault / 'komuta/jev.json').write_text('{"mode":"off"}', encoding='utf-8')
        # A real transport is never allowed in this fixture, even if off regresses.
        transport = patch.object(jev_client, '_transport',
                                 side_effect=AssertionError('network forbidden'))
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    snapshot = ScopeAudit.snapshot

    def record(self, memory_id, statement, subject_key=None, content=None, **overrides):
        content = statement if content is None else content
        source = self.vault / (memory_id + '.md')
        source.write_text(content, encoding='utf-8')
        return dict(dict(memory_id=memory_id, kind='semantic', scope='user',
                         subject_key=subject_key or memory_id, statement=statement,
                         status='active', source_path=source.name, source_anchor=memory_id,
                         source_hash=hafiza.statement_hash(statement),
                         source_content_hash=hafiza.statement_hash(content), evidence=statement,
                         observed_at='2025-01-01T00:00:00+00:00', valid_from='2025-01-01',
                         valid_to=None, confidence='explicit-user', sensitivity='normal',
                         mem0_id=None, supersedes=None, reviewed_by='human-reviewer',
                         schema_version=1), **overrides)

    def catalog(self, rows):
        self.assertEqual(hafiza.validate_catalog(self.vault, rows), [])
        for row in rows:
            self.assertEqual(hafiza.context_record_errors(self.vault, row), [])
        hafiza._write_jsonl(self.vault / hafiza.CATALOG_PATH, rows)
        return rows

    def seed(self, prefix=''):
        rows = [
            self.record('theme-dark', prefix + 'Kullanıcı koyu tema tercih eder.', 'arayuz-tema-rengi'),
            self.record('theme-light', prefix + 'Kullanıcı açık renkli tema ister.', 'tema-secimi'),
            self.record('speech-long', prefix + 'Sunumlarda uzun cümle kullan.'),
            self.record('speech-short', prefix + 'Sunumlarda kısa cümle kullan.'),
            self.record('noise-test', prefix + 'Testleri Python unittest ile yaz.'),
            self.record('noise-commit', prefix + 'Commit mesajları Türkçe olsun.'),
            self.record('project-theme', prefix + 'Kullanıcı koyu tema tercih eder.', scope='project:p'),
            self.record('old-theme', prefix + 'Kullanıcı koyu tema tercih eder.', status='superseded'),
        ]
        return self.catalog(rows)

    def three_pairs(self, **first_overrides):
        return self.catalog([
            self.record('a', 'Kullanıcı koyu tema ister.', 'theme', **first_overrides),
            self.record('b', 'Kullanıcı açık tema ister.', 'theme'),
            self.record('c', 'Kullanıcı mavi tema ister.', 'theme'),
        ])

    def fake(self, vault, query, cards, **kwargs):
        return dict(mode='on', degraded=False,
                    facet_scores={i: {card['id']: 2 if i == 1 else 0 for card in cards}
                                  for i in range(3)})

    def pair_ids(self, result):
        return {(pair['a_id'], pair['b_id']) for pair in result['pairs']}

    def test_seed_recall_two_of_two_and_zero_false_alarms(self):
        rows = self.seed()
        before = self.snapshot(self.vault)
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            result = audit.active_conflict_audit(self.vault, jev_pairs=0)
        expected = {('theme-dark', 'theme-light'), ('speech-long', 'speech-short')}
        found = self.pair_ids(result)
        self.assertEqual(len(expected & found), 2, 'recall 2/2')
        self.assertEqual(len(found - expected), 0, 'false alarms 0')
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual(result['omitted_count'], 0)
        self.assertEqual(result['status'], 'cheap_only')
        self.assertEqual(result['jev_checked'], 0)
        self.assertEqual(result['jev_pair_limit'], 0)
        self.assertEqual(result['check'], 'active_conflict_audit')
        self.assertEqual(result['diagnostics'], [])
        self.assertEqual(result['note'], 'Yalnız inceleme adayı; supersede kararı insanda. Jev puanı onay değildir.')
        lookup = {row['memory_id']: row for row in rows}
        for pair in result['pairs']:
            self.assertLess(pair['a_id'], pair['b_id'])
            self.assertEqual(lookup[pair['a_id']]['scope'], lookup[pair['b_id']]['scope'])
            self.assertNotIn('old-theme', (pair['a_id'], pair['b_id']))
            self.assertIsNone(pair['jev'])
            self.assertEqual(pair['reason'], 'word_overlap')
        theme = next(pair for pair in result['pairs'] if pair['a_id'] == 'theme-dark')
        self.assertEqual((theme['shared_words'], theme['overlap'], theme['ratio']), (['tema'], 1, 0.5))
        evaluate.assert_not_called()
        self.assertEqual(before, self.snapshot(self.vault))

    def test_same_subject_first_even_without_shared_words(self):
        rows = self.seed()
        rows += [self.record('a', 'Sessiz.', 'sound'), self.record('b', 'Sesli.', 'sound')]
        self.catalog(rows)
        result = audit.active_conflict_audit(self.vault, jev_pairs=0)
        first = result['pairs'][0]
        self.assertEqual((first['a_id'], first['b_id'], first['reason']), ('a', 'b', 'same_subject_key'))
        self.assertEqual((first['overlap'], first['ratio']), (0, 0))

    def test_order_and_truncation_are_deterministic(self):
        rows = self.three_pairs()
        complete = audit.active_conflict_audit(self.vault, jev_pairs=0)
        self.assertEqual([(p['a_id'], p['b_id']) for p in complete['pairs']],
                         [('a', 'b'), ('a', 'c'), ('b', 'c')])
        self.catalog(list(reversed(rows)))
        self.assertEqual(complete, audit.active_conflict_audit(self.vault, jev_pairs=0))
        bounded = audit.active_conflict_audit(self.vault, jev_pairs=0, max_candidates=1)
        self.assertEqual(bounded['pairs'], complete['pairs'][:1])
        self.assertEqual((bounded['candidate_count'], bounded['omitted_count']), (3, 2))
        empty = audit.active_conflict_audit(self.vault, max_candidates=0)
        self.assertEqual((empty['pairs'], empty['omitted_count'], empty['jev_checked']), ([], 3, 0))

    def test_common_inflected_name_does_not_add_false_alarms(self):
        rows = self.seed(prefix='Deniz ')
        # word_match must also count an inflected spelling toward frequency.
        rows[0] = self.record('theme-dark', 'Denizin koyu tema tercihi.', 'arayuz-tema-rengi')
        self.catalog(rows)
        result = audit.active_conflict_audit(self.vault, jev_pairs=0)
        self.assertEqual(self.pair_ids(result),
                         {('theme-dark', 'theme-light'), ('speech-long', 'speech-short')})
        self.assertTrue(all(not any(word.startswith('deniz') for word in pair['shared_words'])
                            for pair in result['pairs']))

    def test_concept_normalization_and_half_frequency_boundary(self):
        self.catalog([
            self.record('a', 'Kullanıcının karanlık arka plan tercihi.'),
            self.record('b', 'Kullanıcı açık zemin istiyor.'),
            self.record('c', 'Testleri Python unittest ile yaz.'),
            self.record('d', 'Commit mesajları Türkçe olsun.'),
        ])
        result = audit.active_conflict_audit(self.vault, jev_pairs=0)
        self.assertEqual(self.pair_ids(result), {('a', 'b')})
        self.assertEqual(result['pairs'][0]['shared_words'], ['zemin'])
        self.assertEqual(result['pairs'][0]['ratio'], 0.5)

    def test_scopes_never_cross_and_can_be_filtered(self):
        rows = self.seed()
        rows += [self.record('project-light', 'Kullanıcı açık tema ister.', scope='project:p'),
                 self.record('q-dark', 'Kullanıcı koyu tema ister.', scope='project:q'),
                 self.record('q-light', 'Kullanıcı açık tema ister.', scope='project:q')]
        self.catalog(rows)
        all_scopes = audit.active_conflict_audit(self.vault, jev_pairs=0)
        self.assertEqual(all_scopes['candidate_count'], 4)
        project = audit.active_conflict_audit(self.vault, scopes={'project:p'}, jev_pairs=0)
        self.assertEqual(self.pair_ids(project), {('project-light', 'project-theme')})
        self.assertEqual(project['pairs'][0]['scope'], 'project:p')
        self.assertEqual(audit.active_conflict_audit(self.vault, scopes=set())['pairs'], [])

    def test_invalid_sources_and_unretrievable_rows_are_excluded(self):
        rows = self.seed()
        rows += [self.record(ident, 'Kullanıcı koyu tema ister.', **overrides) for ident, overrides in (
            ('missing', {}), ('changed', {}), ('private', {'sensitivity': 'private'}),
            ('expired', {'valid_to': '2025-02-01'}), ('future', {'valid_from': '2999-01-01'}))]
        rows.append(self.record('secret', 'token=secret_value'))
        self.catalog(rows)
        (self.vault / 'missing.md').unlink()
        (self.vault / 'changed.md').write_text('Kaynak değişti.', encoding='utf-8')
        result = audit.active_conflict_audit(self.vault, jev_pairs=0)
        self.assertEqual(result['diagnostics'], ['excluded_invalid_source:2'])
        self.assertEqual(self.pair_ids(result),
                         {('theme-dark', 'theme-light'), ('speech-long', 'speech-short')})

    def test_incompatible_advice_never_changes_catalog_or_files(self):
        self.seed()
        before = self.snapshot(self.vault)
        catalog_before = (self.vault / hafiza.CATALOG_PATH).read_bytes()
        statuses = [row['status'] for row in hafiza.load_catalog(self.vault)]
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            result = audit.active_conflict_audit(self.vault)
        self.assertEqual(result['status'], 'advisory')
        self.assertEqual(result['jev_checked'], 2)
        self.assertEqual(evaluate.call_count, 2)
        self.assertTrue(all(pair['jev']['relation'] == 'incompatible' for pair in result['pairs']))
        self.assertIs(result['canonical_writes'], False)
        self.assertIs(result['auto_supersede'], False)
        self.assertIs(result['requires_reviewer'], True)
        self.assertEqual(catalog_before, (self.vault / hafiza.CATALOG_PATH).read_bytes())
        self.assertEqual(statuses, [row['status'] for row in hafiza.load_catalog(self.vault)])
        self.assertEqual(before, self.snapshot(self.vault))

    def test_packet_uses_exact_quotes_conditions_and_source_versions(self):
        rationale = 'Çünkü göz yorgunluğu azalır.'
        conditions = 'Yalnız akşam çalışırken geçerlidir.'
        statement = 'Kullanıcı koyu tema ister.'
        a = self.record('a', statement, content='\n'.join((statement, rationale, conditions)),
                        rationale=rationale, conditions=conditions)
        b = self.record('b', 'Kullanıcı açık tema ister.', rationale='Kaynakta olmayan gerekçe.')
        self.catalog([a, b])
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            audit.active_conflict_audit(self.vault)
        args, kwargs = evaluate.call_args
        self.assertEqual(args[0], self.vault)
        anchor = json.loads(args[1])['anchor']
        payload = json.loads(anchor['statement'])
        self.assertEqual((anchor['id'], anchor['title'], anchor['domains']), ('a', 'a', ['all']))
        self.assertEqual(payload['kind'], 'decision')
        self.assertEqual(payload['stored_claim'], statement)
        self.assertEqual(payload['applicability'], dict(rationale=rationale, conditions=conditions))
        self.assertEqual(payload['evidence'], [dict(quote=statement, source_sha256=bilgi_agi.digest(self.vault / 'a.md'))])
        self.assertEqual(json.loads(args[2][0]['statement'])['applicability'], {})
        self.assertEqual(kwargs['purpose'], 'memory_review')
        self.assertEqual(kwargs['facets'], jev_review.RELATIONS)
        self.assertEqual(kwargs['scope'], 'user')
        self.assertEqual(kwargs['source_versions'],
                         {path: bilgi_agi.digest(self.vault / path)
                          for path in (hafiza.CATALOG_PATH.as_posix(), 'a.md', 'b.md')})

    def test_degraded_advice_keeps_cheap_candidates(self):
        self.seed()
        for mode in ('on', 'off'):
            with self.subTest(mode=mode), patch.object(jev_client, 'evaluate', side_effect=lambda *a, **kw:
                    dict(mode=mode, degraded=True, diagnostics=['timeout'])):
                result = audit.active_conflict_audit(self.vault)
            self.assertEqual(result['status'], 'cheap_only')
            self.assertEqual(len(result['pairs']), 2)
            self.assertTrue(all(pair['jev'] == dict(status='degraded', diagnostics=['timeout'])
                                for pair in result['pairs']))

    def test_call_quota_and_zero_disable(self):
        self.three_pairs()
        for limit in (0, 1):
            with self.subTest(limit=limit), patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
                result = audit.active_conflict_audit(self.vault, jev_pairs=limit)
            self.assertEqual(evaluate.call_count, limit)
            self.assertEqual(result['jev_checked'], limit)
            self.assertEqual(len(result['pairs']), 3)
            self.assertTrue(all(pair['jev'] is None for pair in result['pairs'][limit:]))

    def test_jev_pair_limit_is_clamped_to_ten(self):
        self.catalog([self.record(str(i), f'Tema seçeneği {i} kullan.', 'theme') for i in range(6)])
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            result = audit.active_conflict_audit(self.vault, jev_pairs=100)
        self.assertEqual((result['candidate_count'], result['jev_checked'], result['jev_pair_limit']), (15, 10, 10))
        self.assertEqual(evaluate.call_count, 10)

    def test_real_off_mode_has_no_network_or_writes(self):
        self.seed()
        before = self.snapshot(self.vault)
        result = audit.active_conflict_audit(self.vault)
        self.assertEqual(result['status'], 'cheap_only')
        self.assertEqual(result['jev_checked'], 2)
        self.assertTrue(all(pair['jev'] == dict(status='disabled') for pair in result['pairs']))
        self.transport.assert_not_called()
        self.assertEqual(before, self.snapshot(self.vault))

    def test_ineligible_evidence_does_not_consume_quota(self):
        for quote in ('', None, 'Kısa', 'Kaynakta hiç geçmeyen kanıt.'):
            with self.subTest(quote=quote):
                self.three_pairs(evidence=quote)
                with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
                    result = audit.active_conflict_audit(self.vault, jev_pairs=1)
                self.assertEqual(evaluate.call_count, 1)
                self.assertEqual(result['jev_checked'], 1)
                self.assertEqual([p['jev']['status'] for p in result['pairs']],
                                 ['not_eligible', 'not_eligible', 'advisory'])
                self.assertEqual(result['pairs'][0]['jev']['reason'], 'exact_quote_evidence_missing')

    def test_secret_source_is_not_sent_to_jev(self):
        self.three_pairs(content='Kullanıcı koyu tema ister.\ntoken=secret_value')
        with patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            result = audit.active_conflict_audit(self.vault, jev_pairs=1)
        self.assertEqual([p['jev']['status'] for p in result['pairs']],
                         ['not_eligible', 'not_eligible', 'advisory'])
        self.assertNotIn('secret_value', json.dumps(evaluate.call_args.args, default=str))

    def test_current_source_binding_allows_revised_source(self):
        rows = self.three_pairs()
        content = rows[0]['statement'] + '\nEk kaynak açıklaması.'
        (self.vault / 'a.md').write_text(content, encoding='utf-8')
        hafiza._write_jsonl(self.vault / hafiza.SOURCE_BINDINGS, [dict(
            memory_id='a', source_path='a.md', statement_hash=rows[0]['source_hash'],
            source_content_hash=hafiza.statement_hash(content), evidence=rows[0]['evidence'],
            reviewed_by='independent-reviewer')])
        self.assertEqual(hafiza.context_record_errors(self.vault, rows[0]), [])
        with patch.object(jev_client, 'evaluate', side_effect=self.fake):
            result = audit.active_conflict_audit(self.vault, jev_pairs=1)
        self.assertEqual(result['pairs'][0]['jev']['status'], 'advisory')

    def test_evaluate_exception_does_not_stop_next_pair(self):
        self.three_pairs()
        def fake(*args, **kwargs):
            if evaluate.call_count == 1:
                raise ValueError('private provider details')
            return self.fake(*args, **kwargs)
        with patch.object(jev_client, 'evaluate', side_effect=fake) as evaluate:
            result = audit.active_conflict_audit(self.vault, jev_pairs=2)
        self.assertEqual(result['pairs'][0]['jev'], dict(status='degraded', diagnostics=['jev_evaluation_failed']))
        self.assertEqual(result['pairs'][1]['jev']['status'], 'advisory')
        self.assertIsNone(result['pairs'][2]['jev'])
        self.assertEqual(result['jev_checked'], 2)
        self.assertNotIn('private provider details', json.dumps(result))

    def test_source_or_catalog_change_discards_scores(self):
        for path in ('a.md', 'b.md', hafiza.CATALOG_PATH.as_posix()):
            with self.subTest(path=path):
                self.three_pairs()
                def fake(*args, **kwargs):
                    target = self.vault / path
                    target.write_bytes(target.read_bytes() + b'\n')
                    return self.fake(*args, **kwargs)
                with patch.object(jev_client, 'evaluate', side_effect=fake):
                    result = audit.active_conflict_audit(self.vault, jev_pairs=1)
                self.assertEqual(result['status'], 'cheap_only')
                self.assertEqual(result['pairs'][0]['jev'],
                                 dict(status='degraded', diagnostics=['source_changed_during_evaluation']))

    def test_change_before_evaluation_prevents_call(self):
        self.three_pairs()
        original = audit._evidence_packet
        def packet(*args):
            result = original(*args)
            if args[1]['memory_id'] == 'b':
                target = self.vault / hafiza.CATALOG_PATH
                target.write_bytes(target.read_bytes() + b'\n')
            return result
        with patch.object(audit, '_evidence_packet', side_effect=packet), \
                patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
            result = audit.active_conflict_audit(self.vault, jev_pairs=1)
        evaluate.assert_not_called()
        self.assertEqual(result['jev_checked'], 0)
        self.assertTrue(all(pair['jev']['diagnostics'] == ['source_changed_during_evaluation']
                            for pair in result['pairs']))

    def test_string_facet_keys_and_ambiguous_relations(self):
        self.three_pairs()
        for values, relation in (((0, 1.5, 0), 'incompatible'), ((2, 2, 0), 'uncertain'),
                                 ((0, 0, 0), 'uncertain'), ((0, 0, 2), 'narrows')):
            with self.subTest(values=values):
                def fake(vault, query, cards, **kwargs):
                    return dict(mode='on', facet_scores={str(i): {cards[0]['id']: value}
                                                        for i, value in enumerate(values)})
                with patch.object(jev_client, 'evaluate', side_effect=fake):
                    result = audit.active_conflict_audit(self.vault, jev_pairs=1)
                advice = result['pairs'][0]['jev']
                self.assertEqual(advice['relation'], relation)
                self.assertEqual(advice['scores'], dict(zip(('same_claim', 'incompatible', 'narrows'), values)))

    def test_review_pending_does_not_persist_conflicts_even_with_apply(self):
        self.seed()
        quote = 'Kaynak doğrulama adımını ayrı inceleyen uygulasın.'
        (self.vault / 'candidate.md').write_text(quote, encoding='utf-8')
        hafiza.add_candidate(self.vault, statement=quote, kind='semantic', scope='project:p',
                             subject_key='review-policy', source_path='candidate.md',
                             source_anchor='review', confidence='explicit-user', sensitivity='normal',
                             proposed_by='author', evidence=quote)
        catalog_before = (self.vault / hafiza.CATALOG_PATH).read_bytes()
        result = hafiza_dongusu.review_pending(self.vault, project_id='p', apply=True)
        self.assertEqual(len(result['reviews']), 1)
        self.assertIs(result['active_conflicts']['canonical_writes'], False)
        self.assertEqual(result['active_conflicts']['candidate_count'], 2)
        receipts = hafiza.load_jsonl(self.vault / hafiza_dongusu.RECEIPTS)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0], result['reviews'][0]['row'])
        self.assertNotIn('active_conflicts', json.dumps(receipts))
        self.assertNotIn('theme-dark', json.dumps(receipts))
        self.assertEqual(catalog_before, (self.vault / hafiza.CATALOG_PATH).read_bytes())

    def test_review_pending_survives_conflict_audit_failure(self):
        with patch.object(audit, 'active_conflict_audit', side_effect=ValueError('broken')):
            result = hafiza_dongusu.review_pending(self.vault, project_id='p', apply=True)
        self.assertEqual(result['active_conflicts'], dict(status='degraded',
                         diagnostics=['conflict_audit_failed'], pairs=[], canonical_writes=False))
        self.assertEqual(result['reviews'], [])
        self.assertEqual(result['pending_total'], 0)
        self.assertIs(result['applied'], True)

    def test_review_pending_passes_scopes_and_clamped_budget(self):
        for limit, expected in ((-2, 0), (30, 10)):
            with self.subTest(limit=limit), patch.object(audit, 'active_conflict_audit', return_value={}) as call:
                hafiza_dongusu.review_pending(self.vault, project_id='p', conflict_pairs=limit)
            call.assert_called_once_with(self.vault, scopes={'user', 'project:p'}, jev_pairs=expected)

    def test_review_pending_clis_accept_conflict_pairs_zero(self):
        self.seed()
        for module in (hafiza_dongusu, konsolidasyon):
            output = io.StringIO()
            args = [module.__file__, '--vault', str(self.vault), 'review-pending',
                    '--project-id', 'p', '--conflict-pairs', '0']
            with self.subTest(module=module.__name__), patch.object(sys, 'argv', args), \
                    contextlib.redirect_stdout(output), \
                    patch.object(jev_client, 'evaluate', side_effect=self.fake) as evaluate:
                module.main()
            evaluate.assert_not_called()
            result = json.loads(output.getvalue())['active_conflicts']
            self.assertEqual((result['jev_pair_limit'], result['candidate_count']), (0, 2))

    def test_celiski_cli_project_filter_and_all_scopes(self):
        rows = self.seed()
        rows += [self.record('q1', 'Kullanıcı koyu tema ister.', scope='project:q'),
                 self.record('q2', 'Kullanıcı açık tema ister.', scope='project:q')]
        self.catalog(rows)
        for extra, count in (([], 3), (['--project-id', 'p'], 2)):
            output = io.StringIO()
            args = [audit.__file__, '--vault', str(self.vault), 'celiski', '--jev-pairs', '0', *extra]
            with patch.object(sys, 'argv', args), contextlib.redirect_stdout(output):
                audit.main()
            result = json.loads(output.getvalue())
            self.assertEqual((result['check'], result['candidate_count']), ('active_conflict_audit', count))
            self.assertEqual(result['jev_checked'], 0)

    def test_empty_vault_stays_empty(self):
        with tempfile.TemporaryDirectory() as empty:
            vault = Path(empty)
            before = self.snapshot(vault)
            result = audit.active_conflict_audit(vault)
            self.assertEqual(result['pairs'], [])
            self.assertEqual((result['candidate_count'], result['omitted_count'], result['jev_checked']), (0, 0, 0))
            self.assertEqual(before, self.snapshot(vault))


if __name__ == '__main__':
    unittest.main()
