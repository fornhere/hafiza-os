import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import hafiza


class SearchKeyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.vault = Path(temp.name)
        self.statement = 'Kullanıcı kısa ve net cevapları tercih eder.'
        self.source = self.vault / 'source.md'
        self.source.write_text(self.statement, encoding='utf-8')
        queued = hafiza.add_candidate(
            self.vault, statement=self.statement, kind='semantic', scope='user',
            subject_key='communication.conciseness', source_path='source.md',
            source_anchor='cevap', confidence='explicit-user', sensitivity='normal',
            proposed_by='worker', evidence=self.statement)
        self.candidate_id = queued['candidate_id']

    def promote(self, **kwargs):
        return hafiza.promote_candidate(self.vault, self.candidate_id, memory_id='pref',
                                        reviewed_by='reviewer', **kwargs)

    @staticmethod
    def invalid_keys():
        return [None, 'anlatım', ('anlatım',), {}, [], [''], ['  '], ['a'], ['x' * 41],
                ['api_key=synthetic-secret'], [str(i) for i in range(100, 113)],
                ['Video', ' video '], ['Straße', 'STRASSE'], [1], [None],
                ['iki\nsatır'], ['iki\rsatır'], ['anlatım\n'], ['iki\u2028satır']]

    def test_search_key_validation_boundaries(self):
        for keys in (['ab'], ['x' * 40], [str(i) for i in range(100, 112)], [' anlatım ', 'ses tonu']):
            with self.subTest(keys=keys):
                self.assertEqual(hafiza.search_key_errors(keys), [])
        for keys in self.invalid_keys():
            with self.subTest(keys=keys):
                self.assertTrue(hafiza.search_key_errors(keys))

    def test_promote_search_keys_preserves_statement_hash_and_evidence(self):
        baseline = self.promote()['record']
        keys = [' anlatım ', 'ses tonu']
        result = self.promote(search_keys=keys, apply=True)
        self.assertEqual(result['result'], 'promoted')
        record = hafiza.load_catalog(self.vault)[0]
        self.assertEqual(record, dict(baseline, arama_anahtarlari=['anlatım', 'ses tonu']))
        self.assertEqual(record['statement'], self.statement)
        self.assertEqual(record['source_hash'], hafiza.statement_hash(self.statement))
        self.assertEqual(self.source.read_text(encoding='utf-8'), self.statement)
        self.assertEqual(keys, [' anlatım ', 'ses tonu'])
        self.assertEqual(hafiza.validate_catalog(self.vault, [record]), [])
        self.assertEqual(hafiza.context_record_errors(self.vault, record), [])

    def test_promote_rejects_invalid_search_keys_without_writes(self):
        events = hafiza.load_jsonl(self.vault / hafiza.EVENT_PATH)
        for keys in self.invalid_keys():
            if keys is None: continue  # None omits the optional parameter.
            for apply in (False, True):
                with self.subTest(keys=keys, apply=apply):
                    with self.assertRaisesRegex(ValueError, 'geçersiz arama_anahtarlari'):
                        self.promote(search_keys=keys, apply=apply)
                    self.assertEqual(hafiza.load_catalog(self.vault), [])
                    self.assertEqual(hafiza.load_jsonl(self.vault / hafiza.EVENT_PATH), events)

    def test_promote_ignores_candidate_search_keys(self):
        candidates = hafiza.load_jsonl(self.vault / hafiza.CANDIDATE_PATH)
        candidates[0]['arama_anahtarlari'] = ['api_key=synthetic-secret']
        hafiza._write_jsonl(self.vault / hafiza.CANDIDATE_PATH, candidates)
        self.assertEqual(self.promote(search_keys=['anlatım'])['record']['arama_anahtarlari'], ['anlatım'])
        self.promote(apply=True)
        self.assertNotIn('arama_anahtarlari', hafiza.load_catalog(self.vault)[0])

    def test_catalog_and_context_reject_invalid_search_keys(self):
        baseline = self.promote()['record']
        for keys in self.invalid_keys():
            with self.subTest(keys=keys):
                row = dict(baseline, arama_anahtarlari=keys)
                expected = ['pref: geçersiz arama_anahtarlari']
                self.assertEqual(hafiza.validate_catalog(self.vault, [row]), expected)
                self.assertEqual(hafiza.context_record_errors(self.vault, row), expected)
        hafiza._write_jsonl(self.vault / hafiza.CATALOG_PATH, [dict(baseline, arama_anahtarlari=[])])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = hafiza.main(['--vault', str(self.vault), 'context', 'kısa', '--local'])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())['memory_ids'], [])

    def test_promote_cli_repeated_search_keys_stay_out_of_context_and_remote_metadata(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = hafiza.main(['--vault', str(self.vault), 'promote', self.candidate_id,
                                 '--memory-id', 'pref', '--reviewed-by', 'reviewer',
                                 '--search-key', ' anlatım ', '--search-key', 'ses tonu', '--apply'])
        self.assertEqual(result, 0)
        record = hafiza.load_catalog(self.vault)[0]
        self.assertEqual(record['arama_anahtarlari'], ['anlatım', 'ses tonu'])
        self.assertNotIn('arama_anahtarlari', hafiza.memory_metadata(self.vault, record))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = hafiza.main(['--vault', str(self.vault), 'context', 'anlatım', '--local'])
        self.assertEqual(result, 0)
        package = json.loads(output.getvalue())
        self.assertEqual(package['memory_ids'], ['pref'])
        self.assertIn(self.statement, package['text'])
        self.assertNotIn('arama_anahtarlari', package['text'])
        self.assertNotIn('anlatım', package['text'])
        self.assertNotIn('ses tonu', package['text'])


class FakeMem0:
    def __init__(self, remote, search_results=None):
        self.remote = {item["id"]: dict(item) for item in remote}
        self.search_results = search_results or []
        self.updated = []
        self.added = []
        self.deleted = []

    def list_memories(self):
        return list(self.remote.values())

    def search_memories(self, query, filters, top_k=10, threshold=0.1):
        return list(self.search_results)[:top_k]

    def update_memory(self, memory_id, text, metadata, expiration_date=None):
        self.updated.append((memory_id, text, metadata, expiration_date))
        self.remote[memory_id]["memory"] = text
        self.remote[memory_id]["metadata"] = dict(metadata)
        self.remote[memory_id]["expiration_date"] = expiration_date
        return self.remote[memory_id]

    def add_memory(self, text, metadata):
        memory_id = "22222222-2222-2222-2222-222222222222"
        item = {"id": memory_id, "memory": text, "metadata": dict(metadata)}
        self.added.append(item)
        self.remote[memory_id] = item
        return item

    def delete_memory(self, memory_id):
        self.deleted.append(memory_id)
        self.remote.pop(memory_id)


class HafizaDogrulamaTesti(unittest.TestCase):
    def test_gecerli_katalogu_okur_ve_hashi_dogrular(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin" / "kaynak.md").write_text("# Kaynak\n", encoding="utf-8")
            statement = "Kullanıcı Türkçe iletişimi tercih eder."
            record = {
                "memory_id": "ornek-pref-language",
                "kind": "semantic",
                "scope": "user",
                "subject_key": "communication.language",
                "statement": statement,
                "status": "active",
                "source_path": "zihin/kaynak.md",
                "source_anchor": "dil",
                "source_hash": "sha256:" + hashlib.sha256(statement.encode()).hexdigest(),
                "observed_at": "2026-09-04",
                "valid_from": "2026-09-04",
                "valid_to": None,
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "mem0_id": "11111111-1111-1111-1111-111111111111",
                "supersedes": None,
                "reviewed_by": "ornek",
                "schema_version": 1,
            }
            (vault / "zihin" / "hafıza-kataloğu.jsonl").write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )

            records = hafiza.load_catalog(vault)
            errors = hafiza.validate_catalog(vault, records)

            self.assertEqual([record], records)
            self.assertEqual([], errors)

    def test_aday_sir_iceriyorsa_reddeder(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            with self.assertRaisesRegex(ValueError, "gizli bilgi"):
                hafiza.add_candidate(
                    vault,
                    statement="Mem0 api_key = " + "ÖRNEK-DEĞER-BURAYA-GİRMEZ",
                    kind="semantic",
                    scope="user",
                    subject_key="security.api-key",
                    source_path="günlük/2026-09-04.md",
                    source_anchor="anahtar",
                    confidence="explicit-user",
                    sensitivity="secret",
                    proposed_by="claude",
                )

    def test_aday_ekler_ve_ayni_gercegi_tekrar_eklemez(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin/çekirdek.md").write_text("Kullanıcı dosya adlarında Türkçe kullanır.")
            kwargs = {
                "statement": "Kullanıcı dosya adlarında Türkçe kullanır.",
                "kind": "semantic",
                "scope": "user",
                "subject_key": "files.naming-language",
                "source_path": "zihin/çekirdek.md",
                "source_anchor": "dosya-adları",
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "proposed_by": "codex",
            }
            first = hafiza.add_candidate(vault, **kwargs)
            second = hafiza.add_candidate(vault, **kwargs)

            queue = hafiza.load_jsonl(vault / hafiza.CANDIDATE_PATH)
            events = hafiza.load_jsonl(vault / hafiza.EVENT_PATH)
            self.assertEqual("queued", first["result"])
            self.assertEqual("duplicate", second["result"])
            self.assertEqual(1, len(queue))
            self.assertEqual("candidate.queued", events[0]["event_type"])

    def test_senkron_driftli_kaydi_gunceller_ve_yeniden_okuyarak_dogrular(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin" / "kaynak.md").write_text("# Kaynak\n", encoding="utf-8")
            statement = "Kullanıcı Türkçe iletişimi tercih eder."
            record = {
                "memory_id": "ornek-pref-language",
                "kind": "semantic",
                "scope": "user",
                "subject_key": "communication.language",
                "statement": statement,
                "status": "active",
                "source_path": "zihin/kaynak.md",
                "source_anchor": "dil",
                "source_hash": hafiza.statement_hash(statement),
                "observed_at": "2026-09-04",
                "valid_from": "2026-09-04",
                "valid_to": "2027-03-04",
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "mem0_id": "11111111-1111-1111-1111-111111111111",
                "supersedes": None,
                "reviewed_by": "ornek",
                "schema_version": 1,
            }
            client = FakeMem0([
                {"id": record["mem0_id"], "memory": "Old text", "metadata": {}}
            ])

            receipt = hafiza.sync_existing(vault, [record], client, apply=True)

            self.assertEqual(1, receipt["updated"])
            self.assertEqual(1, receipt["verified"])
            self.assertEqual(statement, client.remote[record["mem0_id"]]["memory"])
            metadata = client.remote[record["mem0_id"]]["metadata"]
            self.assertEqual("obsidian", metadata["source"])
            self.assertEqual("active", metadata["status"])
            self.assertEqual("2027-03-04", client.updated[0][3])
            self.assertNotIn("statement", metadata)

    def test_senkron_baglantisiz_aktif_kaydi_ekler_ve_katalogu_gunceller(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin" / "kaynak.md").write_text("# Kaynak\n", encoding="utf-8")
            statement = "Kullanıcı açıklayıcı dosya adlarını tercih eder."
            record = {
                "memory_id": "ornek-pref-file-names",
                "kind": "semantic",
                "scope": "user",
                "subject_key": "files.naming-style",
                "statement": statement,
                "status": "active",
                "source_path": "zihin/kaynak.md",
                "source_anchor": "dosya-adları",
                "source_hash": hafiza.statement_hash(statement),
                "observed_at": "2026-09-04",
                "valid_from": "2026-09-04",
                "valid_to": None,
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "mem0_id": None,
                "supersedes": None,
                "reviewed_by": "ornek",
                "schema_version": 1,
            }
            (vault / hafiza.CATALOG_PATH).write_text(
                json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            client = FakeMem0([])

            receipt = hafiza.sync_existing(vault, [record], client, apply=True)

            self.assertEqual(1, receipt["added"])
            persisted = hafiza.load_catalog(vault)[0]
            self.assertEqual("22222222-2222-2222-2222-222222222222", persisted["mem0_id"])
            self.assertEqual(1, receipt["verified"])

    def test_unutma_onaysiz_silmez(self):
        record = {
            "memory_id": "ornek-pref-language",
            "mem0_id": "11111111-1111-1111-1111-111111111111",
        }
        client = FakeMem0([{"id": record["mem0_id"], "memory": "x", "metadata": {}}])

        with self.assertRaisesRegex(ValueError, "açık onay"):
            hafiza.forget_remote(record, client, approved_by=None, apply=True)

        self.assertEqual([], client.deleted)

    def test_baglam_paketi_yalniz_aktif_kayitlari_ve_butceyi_kullanir(self):
        client = FakeMem0([], search_results=[
            {
                "id": "a",
                "memory": "Kullanıcı Türkçe iletişimi tercih eder.",
                "metadata": {
                    "memory_id": "ornek-pref-language",
                    "status": "active",
                    "scope": "user",
                    "source_path": "zihin/çekirdek.md",
                    "observed_at": "2026-09-04",
                    "confidence": "explicit-user",
                },
                "score": 0.91,
            },
            {
                "id": "b",
                "memory": "Geçici proje durumu.",
                "metadata": {"memory_id": "temp", "status": "quarantined", "scope": "project"},
                "score": 0.88,
            },
        ])

        package = hafiza.build_context_package(
            client,
            query="Hangi dilde konuşmalıyım?",
            scope="user",
            limit=5,
            char_budget=300,
        )

        self.assertIn("ornek-pref-language", package["text"])
        self.assertNotIn("Geçici proje", package["text"])
        self.assertLessEqual(len(package["text"]), 300)
        self.assertEqual(1, package["included"])

    def test_degerlendirme_beklenen_kaydi_top_k_icinde_ister(self):
        client = FakeMem0([], search_results=[
            {
                "id": "a",
                "memory": "Kullanıcı Türkçe iletişimi tercih eder.",
                "metadata": {"memory_id": "ornek-pref-language", "status": "active", "scope": "user"},
                "score": 0.91,
            }
        ])
        cases = [{
            "id": "dil-1",
            "query": "Kullanıcı ile hangi dilde konuşmalıyım?",
            "scope": "user",
            "expected_memory_ids": ["ornek-pref-language"],
            "forbidden_memory_ids": [],
            "top_k": 3,
        }]

        report = hafiza.evaluate_retrieval(client, cases)

        self.assertEqual(1, report["passed"])
        self.assertEqual(1.0, report["accuracy"])
        self.assertTrue(hafiza.evaluation_passes({"accuracy": 0.94}, minimum_accuracy=0.9))
        self.assertFalse(hafiza.evaluation_passes({"accuracy": 0.89}, minimum_accuracy=0.9))

    def test_konsolidasyon_ayni_konudaki_farkli_ifadeyi_celiski_sayar(self):
        existing = [{
            "memory_id": "ornek-pref-language",
            "subject_key": "communication.language",
            "statement": "Kullanıcı Türkçe iletişimi tercih eder.",
            "status": "active",
        }]
        candidate = {
            "candidate_id": "c1",
            "subject_key": "communication.language",
            "statement": "Kullanıcı İngilizce iletişimi tercih eder.",
        }

        assessment = hafiza.assess_candidate(candidate, existing)

        self.assertEqual("conflict", assessment["result"])
        self.assertEqual("ornek-pref-language", assessment["conflicts_with"])

    def test_terfi_inceleyen_olmadan_katalog_yazmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin/çekirdek.md").write_text("Kullanıcı kısa ve net cevapları tercih eder.")
            hafiza.add_candidate(
                vault,
                statement="Kullanıcı kısa ve net cevapları tercih eder.",
                kind="semantic",
                scope="user",
                subject_key="communication.conciseness",
                source_path="zihin/çekirdek.md",
                source_anchor="cevap-tarzı",
                confidence="explicit-user",
                sensitivity="normal",
                proposed_by="gemini",
            )
            candidate = hafiza.load_jsonl(vault / hafiza.CANDIDATE_PATH)[0]

            with self.assertRaisesRegex(ValueError, "inceleyen"):
                hafiza.promote_candidate(
                    vault,
                    candidate["candidate_id"],
                    memory_id="ornek-pref-conciseness",
                    reviewed_by=None,
                    apply=True,
                )

            self.assertEqual([], hafiza.load_catalog(vault))

    def test_denetim_yetim_ve_drifti_raporlar(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin" / "kaynak.md").write_text("# Kaynak\n", encoding="utf-8")
            statement = "Kullanıcı Türkçe iletişimi tercih eder."
            record = {
                "memory_id": "ornek-pref-language",
                "kind": "semantic",
                "scope": "user",
                "subject_key": "communication.language",
                "statement": statement,
                "status": "active",
                "source_path": "zihin/kaynak.md",
                "source_anchor": "dil",
                "source_hash": hafiza.statement_hash(statement),
                "observed_at": "2026-09-04",
                "valid_from": "2026-09-04",
                "valid_to": None,
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "mem0_id": "11111111-1111-1111-1111-111111111111",
                "supersedes": None,
                "reviewed_by": "ornek",
                "schema_version": 1,
            }
            client = FakeMem0([
                {"id": record["mem0_id"], "memory": "Yanlış metin", "metadata": {}},
                {"id": "99999999-9999-9999-9999-999999999999", "memory": "Yetim", "metadata": {}},
            ])

            report = hafiza.audit(vault, [record], client)

            self.assertEqual([record["memory_id"]], report["drifted"])
            self.assertEqual(["99999999-9999-9999-9999-999999999999"], report["orphan_remote_ids"])
            self.assertEqual([], report["missing_remote"])

    def test_cli_dogrula_json_makbuz_dondurur(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = hafiza.main(["--vault", str(vault), "validate"])

            self.assertEqual(0, exit_code)
            self.assertEqual({"catalog_errors": [], "record_count": 0}, json.loads(buffer.getvalue()))

    def test_kullanici_kimligi_ortamdan_okunur_ve_bayrakla_ezilir(self):
        original = os.environ.get("HAFIZA_MEM0_USER_ID")
        try:
            os.environ["HAFIZA_MEM0_USER_ID"] = "ayse"
            self.assertEqual("ayse", hafiza.resolve_user_id(None))
            self.assertEqual("mehmet", hafiza.resolve_user_id("mehmet"))
            del os.environ["HAFIZA_MEM0_USER_ID"]
            self.assertEqual(hafiza.DEFAULT_USER_ID, hafiza.resolve_user_id(None))
        finally:
            if original is None:
                os.environ.pop("HAFIZA_MEM0_USER_ID", None)
            else:
                os.environ["HAFIZA_MEM0_USER_ID"] = original


    def test_ayni_ifade_farkli_proje_kapsamlarinda_tekrar_sayilmaz(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            (vault / "zihin").mkdir()
            (vault / "zihin/kaynak.md").write_text(
                "Sunumlarda kısa cümle kullan.", encoding="utf-8"
            )
            kwargs = {
                "statement": "Sunumlarda kısa cümle kullan.",
                "kind": "semantic",
                "subject_key": "presentation.sentence-length",
                "source_path": "zihin/kaynak.md",
                "source_anchor": "sunum",
                "confidence": "explicit-user",
                "sensitivity": "normal",
                "proposed_by": "codex",
            }

            first = hafiza.add_candidate(vault, scope="project:a", **kwargs)
            second = hafiza.add_candidate(vault, scope="project:b", **kwargs)

            self.assertEqual("queued", first["result"])
            self.assertEqual("queued", second["result"])
            self.assertEqual(2, len(hafiza.load_jsonl(vault / hafiza.CANDIDATE_PATH)))

    def test_yerel_baglam_gerekce_ve_kosulu_korur(self):
        result = {
            "memory": "Sunumlarda kısa cümle kullan.",
            "metadata": {
                "memory_id": "presentation-style",
                "status": "active",
                "scope": "project:p",
                "source_path": "zihin/kaynak.md",
                "observed_at": "2026-09-21",
                "confidence": "explicit-user",
                "rationale": "Dinleyicinin takibini kolaylaştırır.",
                "conditions": "Yalnız sözlü sunumlarda geçerlidir.",
            },
        }

        package = hafiza.context_from_results(
            [result], query="Nasıl anlatmalıyım?", scope="project:p", char_budget=500
        )

        self.assertIn("Gerekçe: Dinleyicinin takibini kolaylaştırır.", package["text"])
        self.assertIn(
            "Geçerlilik koşulu: Yalnız sözlü sunumlarda geçerlidir.", package["text"]
        )

    def test_mem0_baglam_kosullari_kanonik_kayittan_tamamlar(self):
        client = FakeMem0([], search_results=[{
            "id": "remote-presentation-style",
            "memory": "Sunumlarda kısa cümle kullan.",
            "metadata": {
                "memory_id": "presentation-style",
                "status": "active",
                "scope": "project:p",
                "source_path": "zihin/kaynak.md",
                "observed_at": "2026-09-21",
                "confidence": "explicit-user",
            },
        }])
        records = [{
            "memory_id": "presentation-style",
            "rationale": "Dinleyicinin takibini kolaylaştırır.",
            "conditions": "Yalnız sözlü sunumlarda geçerlidir.",
        }]

        package = hafiza.build_context_package(
            client,
            query="Nasıl anlatmalıyım?",
            scope="project:p",
            char_budget=500,
            records=records,
        )

        self.assertIn("Dinleyicinin takibini kolaylaştırır.", package["text"])
        self.assertIn("Yalnız sözlü sunumlarda geçerlidir.", package["text"])

    def test_dar_butce_kosullu_kaydi_butun_olarak_atlar(self):
        result = {
            "memory": "Sunumlarda kısa cümle kullan.",
            "metadata": {
                "memory_id": "presentation-style",
                "status": "active",
                "scope": "project:p",
                "rationale": "Dinleyicinin takibini kolaylaştırır.",
                "conditions": "Yalnız sözlü sunumlarda geçerlidir.",
            },
        }

        package = hafiza.context_from_results(
            [result], query="Nasıl anlatmalıyım?", scope="project:p", char_budget=80
        )

        self.assertEqual(0, package["included"])
        self.assertEqual("", package["text"])

    def test_ayni_anahtar_farkli_projede_celiski_sayilmaz(self):
        existing = [{
            "memory_id": "project-a-style",
            "scope": "project:a",
            "subject_key": "presentation.style",
            "statement": "Sunumlarda kısa cümle kullan.",
            "status": "active",
        }]
        candidate = {
            "scope": "project:b",
            "subject_key": "presentation.style",
            "statement": "Sunumlarda uzun cümle kullan.",
        }

        assessment = hafiza.assess_candidate(candidate, existing)

        self.assertEqual("eligible", assessment["result"])

    def test_ayni_kapsam_ve_anahtar_gercek_celiski_sayilir(self):
        existing = [{
            "memory_id": "project-a-style",
            "scope": "project:a",
            "subject_key": "presentation.style",
            "statement": "Sunumlarda kısa cümle kullan.",
            "status": "active",
        }]
        candidate = {
            "scope": "project:a",
            "subject_key": "presentation.style",
            "statement": "Sunumlarda uzun cümle kullan.",
        }

        assessment = hafiza.assess_candidate(candidate, existing)

        self.assertEqual("conflict", assessment["result"])


def _kayit(statement, **overrides):
    record = {
        "memory_id": "ornek-pref-language",
        "kind": "semantic",
        "scope": "user",
        "subject_key": "communication.language",
        "statement": statement,
        "status": "active",
        "source_path": "zihin/kaynak.md",
        "source_anchor": "dil",
        "source_hash": hafiza.statement_hash(statement),
        "observed_at": "2026-09-04",
        "valid_from": "2026-09-04",
        "valid_to": None,
        "confidence": "explicit-user",
        "sensitivity": "normal",
        "mem0_id": None,
        "supersedes": None,
        "reviewed_by": "ornek",
        "schema_version": 1,
    }
    record.update(overrides)
    return record


class KategoriTesti(unittest.TestCase):
    def _vault(self, tmp):
        vault = Path(tmp)
        (vault / "zihin").mkdir(parents=True, exist_ok=True)
        (vault / "zihin" / "kaynak.md").write_text("# Kaynak\n", encoding="utf-8")
        return vault

    def test_kategorisiz_kayit_gecerli_kalir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            record = _kayit("Kullanıcı Türkçe iletişimi tercih eder.")

            self.assertNotIn("category", record)
            self.assertEqual([], hafiza.validate_catalog(vault, [record]))

    def test_gecersiz_kategori_reddedilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            record = _kayit("Kullanıcı Türkçe iletişimi tercih eder.", category="duygu")

            errors = hafiza.validate_catalog(vault, [record])

            self.assertTrue(any("geçersiz category" in error for error in errors))

    def test_kind_ve_kategori_uyumsuzlugu_reddedilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            semantik = _kayit("Kullanıcı deneme sonucunu anlatır.", kind="semantic", category="case")
            olay = _kayit("Kullanıcı koyu temayı seçti.", kind="episodic", category="preference")
            uyumlu = _kayit("Kullanıcı Türkçe iletişimi tercih eder.", category="preference")

            self.assertTrue(any("uyumsuz" in e for e in hafiza.validate_catalog(vault, [semantik])))
            self.assertTrue(any("uyumsuz" in e for e in hafiza.validate_catalog(vault, [olay])))
            self.assertEqual([], hafiza.validate_catalog(vault, [uyumlu]))

    def test_aday_kategorisi_terfide_kataloga_tasinir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "zihin/çekirdek.md").write_text(
                "Kullanıcı kısa ve net cevapları tercih eder.", encoding="utf-8"
            )
            hafiza.add_candidate(
                vault,
                statement="Kullanıcı kısa ve net cevapları tercih eder.",
                kind="semantic",
                scope="user",
                subject_key="communication.conciseness",
                source_path="zihin/çekirdek.md",
                source_anchor="cevap-tarzı",
                confidence="explicit-user",
                sensitivity="normal",
                proposed_by="claude",
                category="preference",
            )
            candidate = hafiza.load_jsonl(vault / hafiza.CANDIDATE_PATH)[0]
            self.assertEqual("preference", candidate["category"])

            assessment = hafiza.assess_candidate(candidate, hafiza.load_catalog(vault))
            self.assertEqual("eligible", assessment["result"])
            self.assertEqual("tercih", assessment["category_label"])

            hafiza.promote_candidate(
                vault,
                candidate["candidate_id"],
                memory_id="ornek-pref-conciseness",
                reviewed_by="ornek",
                apply=True,
            )

            kayitlar = hafiza.load_catalog(vault)
            self.assertEqual("preference", kayitlar[0]["category"])
            self.assertEqual([], hafiza.validate_catalog(vault, kayitlar))

    def test_aday_gecersiz_kategoriyi_kabul_etmez(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "zihin/çekirdek.md").write_text("Kullanıcı koyu temayı seçti.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "uyumsuz"):
                hafiza.add_candidate(
                    vault,
                    statement="Kullanıcı koyu temayı seçti.",
                    kind="episodic",
                    scope="user",
                    subject_key="ui.theme",
                    source_path="zihin/çekirdek.md",
                    source_anchor="tema",
                    confidence="explicit-user",
                    sensitivity="normal",
                    proposed_by="claude",
                    category="preference",
                )

    def test_baglam_satirinda_turkce_kategori_etiketi_gorunur(self):
        results = [
            {"memory": "Kullanıcı Türkçe iletişimi tercih eder.",
             "metadata": {"memory_id": "ornek-pref-language", "status": "active", "scope": "user",
                          "category": "preference", "source_path": "zihin/çekirdek.md"}},
            {"memory": "Hermes AWS üzerine taşındı.",
             "metadata": {"memory_id": "hermes-aws", "status": "active", "scope": "user",
                          "source_path": "projeler/hermes/DURUM.md"}},
        ]

        paket = hafiza.context_from_results(results, query="dil", scope="user", char_budget=1200)

        self.assertIn("[ornek-pref-language] (tercih) Kullanıcı", paket["text"])
        self.assertIn("[hermes-aws] Hermes AWS", paket["text"])

    def test_kategori_raporu_kategorisiz_aktifleri_sayar(self):
        records = [
            _kayit("bir", memory_id="a"),
            _kayit("iki", memory_id="b", category="preference"),
            _kayit("üç", memory_id="c", category="preference"),
            _kayit("dört", memory_id="d", kind="episodic", category="event"),
            _kayit("beş", memory_id="e", status="superseded", category="entity"),
        ]

        rapor = hafiza.category_report(records)

        self.assertEqual(4, rapor["active_total"])
        self.assertEqual(1, rapor["uncategorized"])
        self.assertEqual(3, rapor["categorized"])
        self.assertEqual(2, rapor["distribution"]["preference"])
        self.assertEqual(1, rapor["distribution"]["event"])
        self.assertEqual(0, rapor["distribution"]["entity"])
        self.assertEqual("gidişat", rapor["labels"]["trajectory"])


class NotAramaTesti(unittest.TestCase):
    def _vault(self, tmp):
        vault = Path(tmp)
        for name in ("projeler/hermes", "zihin", "komuta", "günlük"):
            (vault / name).mkdir(parents=True, exist_ok=True)
        return vault

    def test_kapsamdan_varsayilan_dizin_turetilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "projeler" / "hermes" / "DURUM.md").write_text("# Hermes\n", encoding="utf-8")

            proje = hafiza.note_uri_targets(vault, None, "project:hermes")
            kullanici = hafiza.note_uri_targets(vault, None, "user")

            self.assertEqual([vault / "projeler" / "hermes"], proje)
            self.assertEqual(
                [vault / "projeler", vault / "zihin", vault / "komuta"], kullanici
            )

    def test_yasak_dizin_uri_olarak_reddedilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            for yasak in ("günlük", "gelen-kutusu", "arşiv", "araclar", "projeler/arşiv"):
                with self.assertRaises(ValueError):
                    hafiza.note_uri_targets(vault, [yasak], "user")

    def test_baslik_eslesmesi_govdeden_agir_basar(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "komuta" / "kayit.md").write_text(
                "# Kayit\n\n## Tempo kararı\nAyrıntı yok.\n\n"
                "## Diğer başlık\ntempo tempo tempo tempo tempo\n",
                encoding="utf-8",
            )

            notes = hafiza.search_notes(vault, "tempo", uris=["komuta"])

            self.assertEqual("tempo-kararı", notes[0]["anchor"])
            self.assertGreater(notes[0]["score"], notes[1]["score"])

    def test_butce_asiminda_not_satirlari_kesilir(self):
        paket = {"query": "hermes", "scope": "user", "included": 0, "memory_ids": [],
                 "char_budget": 200, "text": ""}
        notes = [
            {"path": "projeler/hermes/DURUM.md", "anchor": "bir", "score": 9.0,
             "excerpt": "kısa", "modified": "2026-09-01"},
            {"path": "projeler/hermes/DURUM.md", "anchor": "iki", "score": 8.0,
             "excerpt": "x" * 240, "modified": "2026-09-01"},
        ]

        sonuc = hafiza.attach_notes(paket, notes, limit=5, char_budget=200)

        self.assertEqual(["bir"], [note["anchor"] for note in sonuc["notes"]])
        self.assertLessEqual(len(sonuc["text"]), 200)
        self.assertIn(hafiza.NOTE_SEPARATOR, sonuc["text"])

    def test_sir_iceren_bolum_disarida_kalir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "komuta" / "anahtar.md").write_text(
                "# Anahtarlar\n\n## Hermes gizli\napi_key: sk-" + "a" * 30 + "\n"
                "\n## Hermes açık\nHermes AWS üzerine taşınacak.\n",
                encoding="utf-8",
            )

            notes = hafiza.search_notes(vault, "hermes", uris=["komuta"])

            self.assertEqual(["hermes-açık"], [note["anchor"] for note in notes])
            self.assertNotIn("sk-", json.dumps(notes, ensure_ascii=False))

    def test_ozet_dosyasi_on_filtre_olarak_kullanilir(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            klasor = vault / "projeler" / "hermes"
            (klasor / "DURUM.md").write_text("# Durum\n\n## Taşıma\nBulut kararı.\n", encoding="utf-8")
            (klasor / "ESKI.md").write_text("# Eski\n\n## Taşıma\nBulut kararı.\n", encoding="utf-8")
            (klasor / ".ozet.md").write_text(
                "---\nad: hermes\n---\n\n# hermes\n\nProje özeti.\n\n## Dosyalar\n"
                "- `DURUM.md` — bulut taşıma durumu [başlıklar: Taşıma]\n"
                "- `ESKI.md` — kapatılmış deneme [başlıklar: Not]\n",
                encoding="utf-8",
            )

            notes = hafiza.search_notes(vault, "bulut taşıma", uris=["projeler/hermes"])

            self.assertEqual({"projeler/hermes/DURUM.md"}, {note["path"] for note in notes})

    def test_ozet_dosyasinin_kendisi_sonuc_olarak_donmez(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            klasor = vault / "projeler" / "hermes"
            (klasor / "DURUM.md").write_text("# Durum\n\n## Bulut\nBulut kararı.\n", encoding="utf-8")
            (klasor / ".ozet.md").write_text(
                "# hermes\n\nBulut özeti.\n\n## Dosyalar\n- `DURUM.md` — bulut kararı\n",
                encoding="utf-8",
            )

            notes = hafiza.search_notes(vault, "bulut", uris=["projeler/hermes"])

            self.assertTrue(notes)
            self.assertNotIn(".ozet.md", {note["path"] for note in notes})

    def test_uzun_katalog_satirlari_not_payini_yemez(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "projeler" / "hermes" / "DURUM.md").write_text(
                "# Hermes\n\n## Yeni yön\nAWS üzerinde 7/24 çalışacak.\n", encoding="utf-8"
            )
            results = [
                {"memory": "Hermes AWS taşıması " + "uzun ayrıntı " * 22,
                 "metadata": {"memory_id": f"hermes-{i}", "status": "active", "scope": "user",
                              "source_path": "projeler/hermes/DURUM.md"}}
                for i in range(4)
            ]

            paket = hafiza.context_package_with_notes(
                vault, results, query="hermes AWS", scope="user",
                uris=["projeler/hermes"], limit=5, char_budget=1200,
            )

            self.assertIn(hafiza.NOTE_SEPARATOR, paket["text"])
            self.assertIn("projeler/hermes/DURUM.md#yeni-yön", paket["text"])
            self.assertTrue(paket["notes"])
            self.assertLessEqual(len(paket["text"]), 1200)
            self.assertEqual(1200, paket["char_budget"])

    def test_not_yoksa_katalog_tum_butceyi_kullanir(self):
        self.assertEqual(1200, hafiza.catalog_budget(1200, False))
        self.assertEqual(720, hafiza.catalog_budget(1200, True))

    def test_context_komutu_not_satirlarini_ekler(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = self._vault(tmp)
            (vault / "projeler" / "hermes" / "DURUM.md").write_text(
                "# Hermes\n\n## Yeni yön\nAWS üzerinde 7/24 çalışacak.\n", encoding="utf-8"
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                exit_code = hafiza.main([
                    "--vault", str(vault), "context", "hermes AWS", "--limit", "5",
                    "--char-budget", "1200",
                ])

            paket = json.loads(buffer.getvalue())
            self.assertEqual(0, exit_code)
            self.assertIn(hafiza.NOTE_SEPARATOR, paket["text"])
            self.assertIn("projeler/hermes/DURUM.md#yeni-yön", paket["text"])
            self.assertEqual("projeler/hermes/DURUM.md", paket["notes"][0]["path"])


if __name__ == "__main__":
    unittest.main()
