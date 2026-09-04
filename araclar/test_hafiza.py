import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import hafiza


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
                "reviewed_by": "kullanici",
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
                "reviewed_by": "kullanici",
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
                "reviewed_by": "kullanici",
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
                "metadata": {"memory_id": "ornek-pref-language", "status": "active"},
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
                "reviewed_by": "kullanici",
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


if __name__ == "__main__":
    unittest.main()
