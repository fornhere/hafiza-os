"""Kavram ağı: eş sözcük yalnız tamamlar, gürültü sınırı ve yönetilen Obsidian dökümü."""
import json
import tempfile
import unittest
from pathlib import Path

import gorev_baglam as g
import hafiza as h
import kavram_agi as k


GAIN = "Kullanıcı mikrofon kazancını kendisi ayarlar."
TEMPO = "Kullanıcı video kurgusunda hızlı tempoyu tercih eder."
COLOR = "Kullanıcı kapak yazılarında sarı-beyaz rengi tercih eder."
HIDDEN = "Kullanıcı kapakta gizli bir deney yapar."
CONCEPTS = {"kavramlar": [
    {"id": "cekim", "title": "Çekim ve ses", "selectors": ["mikrofon", "kazanç"], "aliases": ["gain", "seviye"],
     "related": ["kurgu"]},
    {"id": "kurgu", "title": "Kurgu", "selectors": ["kurgu", "tempo"], "aliases": ["montaj"]},
    {"id": "kapak", "title": "Kapak", "selectors": ["kapak"], "aliases": ["thumbnail"]},
]}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name).resolve()
        source = self.vault / "source.md"
        source.write_text("\n".join((GAIN, TEMPO, COLOR, HIDDEN)), encoding="utf-8")
        self.rows = [self.row("gain", GAIN), self.row("tempo", TEMPO), self.row("color", COLOR),
                     self.row("hidden", HIDDEN, status="quarantined")]
        h._write_jsonl(self.vault / h.CATALOG_PATH, self.rows)
        self.write_concepts(CONCEPTS)

    def row(self, memory_id, statement, status="active"):
        source = self.vault / "source.md"
        return dict(memory_id=memory_id, kind="semantic", scope="user", subject_key="test." + memory_id,
                    statement=statement, status=status, source_path="source.md", source_anchor="a",
                    source_hash=h.statement_hash(statement),
                    source_content_hash=h.statement_hash(source.read_text(encoding="utf-8")),
                    observed_at="2020-01-01", valid_from="2020-01-01", valid_to=None,
                    confidence="explicit-user", sensitivity="normal", mem0_id=None, supersedes=None,
                    reviewed_by="reviewer", schema_version=1)

    def write_concepts(self, data):
        path = self.vault / k.DEFINITIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def rank(self, query):
        active = [r for r in self.rows if h.retrievable(r)]
        return [r["memory_id"] for r in k.ranker(self.vault, g.rank_records)(active, query)]


class RetrievalTests(Fixture):
    def test_alias_completes_record_its_own_word_anchors(self):
        query = "mikrofon sesi düşük gain artırayım mı"
        self.assertEqual(g.rank_records([r for r in self.rows if h.retrievable(r)], query), [])
        self.assertEqual(self.rank(query), ["gain"])

    def test_alias_alone_never_selects(self):
        self.assertEqual(self.rank("gain seviye montaj"), [])

    def test_long_prompt_ignores_concept_synonyms(self):
        query = "kanka mikrofon sesi düşük gain artırayım mı yoksa başka bir yol mu deneyelim bugün"
        active = [r for r in self.rows if h.retrievable(r)]
        self.assertEqual(self.rank(query), [r["memory_id"] for r in g.rank_records(active, query)])

    def test_keys_never_leak_into_returned_rows(self):
        active = [r for r in self.rows if h.retrievable(r)]
        ranked = k.ranker(self.vault, g.rank_records)(active, "mikrofon gain")
        self.assertTrue(ranked)
        self.assertTrue(all(any(r is a for a in active) for r in ranked))
        self.assertFalse(any("kavram_anahtarlari" in r for r in ranked))

    def test_area_expansion_cannot_select_by_synonym(self):
        self.write_concepts({"kavramlar": [{"id": "cekim", "title": "Çekim", "selectors": ["mikrofon"],
                                            "aliases": ["çekim", "anlatım", "konuşma"]}]})
        active = [r for r in self.rows if h.retrievable(r)]
        ranked = k.ranker(self.vault, g.rank_records)(active, "çekim", expansion=g.area_expansion("çekim"))
        self.assertNotIn("gain", [r["memory_id"] for r in ranked])

    def test_missing_or_invalid_definitions_are_a_no_op(self):
        (self.vault / k.DEFINITIONS).unlink()
        self.assertEqual(self.rank("mikrofon sesi düşük gain artırayım mı"), [])
        self.write_concepts({"kavramlar": [{"id": "x", "title": "X", "selectors": ["a"], "related": ["yok"]}]})
        with self.assertRaises(ValueError):
            k.definitions(self.vault)
        self.assertEqual(self.rank("mikrofon sesi düşük gain artırayım mı"), [])


class ExportTests(Fixture):
    def test_export_is_managed_idempotent_and_excludes_inactive(self):
        first = k.export(self.vault, apply=True)
        self.assertTrue(first["applied"])
        root = self.vault / "beyin"
        hub = (root / "Beyin.md").read_text(encoding="utf-8")
        self.assertIn("[[beyin/kavramlar/Çekim ve ses|Çekim ve ses]]", hub)
        concept = (root / "kavramlar" / "Çekim ve ses.md").read_text(encoding="utf-8")
        self.assertIn("[[beyin/kavramlar/Kurgu|Kurgu]] — tanım", concept)
        self.assertIn("mikrofon kazancını", concept)
        everything = "".join(p.read_text(encoding="utf-8") for p in root.rglob("*.md"))
        self.assertNotIn("gizli bir deney", everything)
        self.assertNotIn("kavram_anahtarlari", everything)
        second = k.export(self.vault, apply=True)
        self.assertFalse(second["applied"])
        self.assertEqual(second["changed"], [])

    def test_manual_edit_blocks_and_stale_files_are_removed(self):
        k.export(self.vault, apply=True)
        note = next((self.vault / "beyin" / "hafıza").glob("*.md"))
        note.write_text(note.read_text(encoding="utf-8") + "elle not\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            k.export(self.vault, apply=True)
        note.unlink()
        k.export(self.vault, apply=True)
        self.rows = self.rows[:2]
        h._write_jsonl(self.vault / h.CATALOG_PATH, self.rows)
        result = k.export(self.vault, apply=True)
        self.assertTrue(result["removed"])
        self.assertFalse(any("sarı-beyaz" in p.read_text(encoding="utf-8")
                             for p in (self.vault / "beyin").rglob("*.md")))

    def test_sessions_link_by_title_without_editing_them(self):
        log = self.vault / "günlük" / "oturumlar" / "2026-01-01 Mikrofon ayarı konuşuldu.md"
        log.parent.mkdir(parents=True)
        log.write_text("# Mikrofon ayarı konuşuldu\n\nGövde.\n", encoding="utf-8")
        before = log.read_bytes()
        k.export(self.vault, apply=True)
        concept = (self.vault / "beyin" / "kavramlar" / "Çekim ve ses.md").read_text(encoding="utf-8")
        self.assertIn("[[günlük/oturumlar/2026-01-01 Mikrofon ayarı konuşuldu|", concept)
        self.assertNotIn("Mikrofon ayarı", (self.vault / "beyin" / "kavramlar" / "Kurgu.md").read_text(encoding="utf-8"))
        self.assertEqual(log.read_bytes(), before)

    def test_symlinked_subfolder_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        (self.vault / "beyin").mkdir()
        (self.vault / "beyin" / "kavramlar").symlink_to(outside.name, target_is_directory=True)
        with self.assertRaises(ValueError):
            k.export(self.vault, apply=True)
        self.assertEqual(list(Path(outside.name).iterdir()), [])

    def test_secret_in_session_title_is_not_exported(self):
        log = self.vault / "günlük" / "oturumlar" / "gizli.md"
        log.parent.mkdir(parents=True)
        secret = "sk-" + "a1B2c3D4" * 5
        log.write_text(f"# Oturum makbuzu {secret}\n\nMikrofon ayarları konuşuldu.\n", encoding="utf-8")
        k.export(self.vault, apply=True)
        everything = "".join(p.read_text(encoding="utf-8") for p in (self.vault / "beyin").rglob("*.md"))
        self.assertNotIn(secret, everything)

    def test_secret_in_session_filename_is_not_exported(self):
        secret = "sk-" + "a1B2c3D4" * 5
        log = self.vault / "günlük" / "oturumlar" / f"Mikrofon {secret}.md"
        log.parent.mkdir(parents=True)
        log.write_text("# Mikrofon ayarları\n", encoding="utf-8")
        k.export(self.vault, apply=True)
        everything = "".join(p.read_text(encoding="utf-8") for p in (self.vault / "beyin").rglob("*.md"))
        self.assertNotIn(secret, everything)

    def test_secret_in_any_record_field_is_not_exported(self):
        secret = "sk-" + "a1B2c3D4" * 5
        source = self.vault / f"kaynak-{secret}.md"
        source.write_text(GAIN, encoding="utf-8")
        leaky = dict(self.row("leaky", GAIN), source_path=source.name,
                     source_content_hash=h.statement_hash(GAIN))
        scoped = dict(self.row("scoped", TEMPO), scope=f"project:{secret}")
        h._write_jsonl(self.vault / h.CATALOG_PATH, self.rows + [leaky, scoped])
        k.export(self.vault, apply=True)
        everything = "".join(p.name + p.read_text(encoding="utf-8") for p in (self.vault / "beyin").rglob("*.md"))
        self.assertNotIn(secret, everything)

    def test_colliding_concept_filenames_are_rejected(self):
        self.write_concepts({"kavramlar": [{"id": "a", "title": "Ses/Ayar", "selectors": ["ses"]},
                                           {"id": "b", "title": "Ses:Ayar", "selectors": ["ayar"]}]})
        with self.assertRaises(ValueError):
            k.definitions(self.vault)

    def test_dry_run_writes_nothing(self):
        result = k.export(self.vault)
        self.assertFalse(result["applied"])
        self.assertFalse((self.vault / "beyin").exists())


if __name__ == "__main__":
    unittest.main()
