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

    def test_unused_alias_never_suppresses_direct_matches(self):
        rows = [self.row("m1", "Kullanıcı mikrofon kazancını ayarlar."),
                self.row("m2", "Kullanıcı mikrofon yerini seçer."), self.row("t", TEMPO)]
        self.write_concepts({"kavramlar": [{"id": "c", "title": "C", "selectors": ["kazanç"], "aliases": ["gain"]}]})
        plain = [r["memory_id"] for r in g.rank_records(rows, "mikrofon")]
        keyed = [r["memory_id"] for r in k.ranker(self.vault, g.rank_records)(rows, "mikrofon")]
        self.assertEqual(sorted(plain), ["m1", "m2"])
        self.assertEqual(sorted(keyed), sorted(plain))

    def test_concepts_only_ever_add_to_the_original_ranking(self):
        import random
        rng = random.Random(7)
        vocab = ["mikrofon", "kazanç", "seviye", "kapak", "maskot", "metin", "tempo", "kurgu", "çekim", "gain"]
        for trial in range(300):
            rows = [self.row(f"r{i}", "Kullanıcı " + " ".join(rng.sample(vocab, 3)) + " ister.") for i in range(5)]
            sel = rng.sample(vocab, 2)
            self.write_concepts({"kavramlar": [{"id": "c", "title": "C", "selectors": sel[:1],
                                                "aliases": [w for w in rng.sample(vocab, 2) if w not in sel[:1]] or ["gain"]}]})
            query = " ".join(rng.sample(vocab, rng.randint(1, 4)))
            context = rng.choice([None, " ".join(rng.sample(vocab, 2))])
            plain = g.rank_records(rows, query, context=context)
            keyed = k.ranker(self.vault, g.rank_records)(rows, query, context=context)
            self.assertEqual(keyed[:len(plain)], plain, (trial, query))
            aliases = json.loads((self.vault / k.DEFINITIONS).read_text())["kavramlar"][0]["aliases"]
            if not any(g.word_match(t, a) for t in g.content_words(query) for a in g.content_words(" ".join(aliases))):
                self.assertEqual(keyed, plain, (trial, query))

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

    def test_secret_paths_never_echoed_in_results_or_errors(self):
        secret = "sk-" + "a1B2c3D4" * 5
        k.export(self.vault, apply=True)
        note = next((self.vault / "beyin" / "hafıza").glob("*.md"))
        note.rename(note.with_name(f"{secret}.md"))
        dry = k.export(self.vault)
        self.assertNotIn(secret, json.dumps(dry))
        done = k.export(self.vault, apply=True)
        self.assertNotIn(secret, json.dumps(done))
        self.write_concepts({"kavramlar": [{"id": "s", "title": "sk/" + "a1B2c3D4" * 5, "selectors": ["mikrofon"]}]})
        with self.assertRaises(ValueError) as caught:
            k.export(self.vault, apply=True)
        self.assertNotIn("a1B2c3D4" * 5, str(caught.exception))

    def test_memory_note_names_never_collide(self):
        rows = [self.row(f"memory-{i:04d}", TEMPO) for i in range(400)]
        h._write_jsonl(self.vault / h.CATALOG_PATH, rows)
        k.export(self.vault, apply=True)
        self.assertEqual(len(list((self.vault / "beyin" / "hafıza").glob("*.md"))), 400)

    def test_colliding_concept_filenames_are_rejected(self):
        self.write_concepts({"kavramlar": [{"id": "a", "title": "Ses/Ayar", "selectors": ["ses"]},
                                           {"id": "b", "title": "Ses:Ayar", "selectors": ["ayar"]}]})
        with self.assertRaises(ValueError):
            k.definitions(self.vault)

    def test_dry_run_writes_nothing(self):
        result = k.export(self.vault)
        self.assertFalse(result["applied"])
        self.assertFalse((self.vault / "beyin").exists())


class TaskPackageTests(unittest.TestCase):
    """An addition must not push a scope-profile record out of the card limit."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        statements = ["Kullanıcı video gain değerini " + a + " tercih eder." for a in
                      ("kayıt öncesinde denetlemeyi", "sabit tutmayı", "denemeyle belirlemeyi",
                       "cihaz üzerinden ayarlamayı", "işlem sonrasında yeniden ölçmeyi")]
        statements.append("Kullanıcı video anlatımını kısa tutmayı tercih eder.")
        (self.root / "komuta").mkdir(exist_ok=True)
        (self.root / "working").mkdir()
        (self.root / "komuta" / "gorev-baglam.json").write_text(json.dumps(
            {"projects": [dict(id="atlas", aliases=["atlas"], roots=[str(self.root / "working")])]}))
        (self.root / "komuta" / "jev.json").write_text('{"mode":"off"}\n')
        self.catalog(statements)

    def catalog(self, statements):
        source = self.root / "projeler" / "atlas" / "tercihler.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("\n".join(statements) + "\n", encoding="utf-8")
        rows = [dict(memory_id=f"r{i:02}", kind="semantic", scope="project:atlas" if i % 2 else "user",
                     subject_key=f"test.r{i:02}", statement=text, status="active",
                     source_path="projeler/atlas/tercihler.md", source_anchor="a",
                     source_hash=h.statement_hash(text), source_content_hash=h.statement_hash(source.read_text()),
                     observed_at="2026-10-01", valid_from="2026-10-01", valid_to=None,
                     confidence="explicit-user", sensitivity="normal", mem0_id=None, supersedes=None,
                     reviewed_by="reviewer", schema_version=1)
                for i, text in enumerate(statements)]
        h._write_jsonl(self.root / h.CATALOG_PATH, rows)

    def package(self, aliases, selectors=("anlatım",), budget=5000):
        (self.root / k.DEFINITIONS).write_text(json.dumps({"kavramlar": [
            {"id": "c", "title": "Anlatım", "selectors": list(selectors), "aliases": aliases}]}), encoding="utf-8")
        result = g.build_task_package(self.root, "video gain seviye metin", cwd=str(self.root / "working"),
                                      budget=budget, history="never", view="resume")
        self.assertNotIn("kavram_anahtarlari", json.dumps(result, ensure_ascii=False))
        return result

    def test_addition_never_displaces_profile_record(self):
        base = self.package([])
        keyed = self.package(["gain"])
        self.assertLessEqual(set(base["summary"]["record_ids"]), set(keyed["summary"]["record_ids"]))
        self.assertNotIn("r05:card_limit", keyed["omitted_reasons"])

    def test_addition_only_uses_leftover_budget(self):
        self.catalog(["Kullanıcı video gain değerini " + a + " tercih eder." for a in
                      ("kayıt öncesinde denetlemeyi", "sabit tutmayı", "denemeyle belirlemeyi",
                       "cihaz üzerinden ayarlamayı")] +
                     ["Kullanıcı video konuşmasını doğal tutmayı tercih eder.",
                      "Kullanıcı video anlatımını kısa tutmayı tercih eder."])
        for budget in (800, 1800):
            base = self.package([], selectors=("konuşma",), budget=budget)
            keyed = self.package(["gain"], selectors=("konuşma",), budget=budget)
            self.assertLessEqual(set(base["summary"]["record_ids"]), set(keyed["summary"]["record_ids"]), budget)


class ProjectAndUpkeepTests(Fixture):
    def projects(self, *ids):
        path = self.vault / "komuta" / "gorev-baglam.json"
        path.write_text(json.dumps({"projects": [{"id": i, "aliases": [i + " videosu"]} for i in ids]}), encoding="utf-8")

    def test_project_concepts_join_by_scope_and_never_touch_retrieval(self):
        self.rows[1] = dict(self.rows[1], scope="project:atlas")
        h._write_jsonl(self.vault / h.CATALOG_PATH, self.rows)
        self.projects("atlas", "bos")
        log = self.vault / "günlük" / "oturumlar" / "2026-01-02 Bir oturum.md"
        log.parent.mkdir(parents=True)
        log.write_text('---\nprojeler: ["atlas"]\n---\n\n# Bir oturum\n', encoding="utf-8")
        k.export(self.vault, apply=True)
        page = (self.vault / "beyin" / "kavramlar" / "Proje atlas.md").read_text(encoding="utf-8")
        self.assertIn("hızlı tempoyu", page)
        self.assertNotIn("mikrofon", page)
        self.assertIn("[[günlük/oturumlar/2026-01-02 Bir oturum|", page)
        self.assertNotIn("proje-atlas", json.dumps(k.concept_keys(self.vault, self.rows)))
        before = [r["memory_id"] for r in g.rank_records([r for r in self.rows if h.retrievable(r)], "atlas tempo")]
        after = [r["memory_id"] for r in k.ranker(self.vault, g.rank_records)([r for r in self.rows if h.retrievable(r)], "atlas tempo")]
        self.assertEqual(before, after)

    def test_project_concept_yields_to_hand_written_one(self):
        self.write_concepts({"kavramlar": CONCEPTS["kavramlar"] + [
            {"id": "proje-kurgu", "title": "Elle", "selectors": ["kurgu"]}]})
        self.projects("kurgu")
        ids = [c["id"] for c in k.project_concepts(self.vault, k.definitions(self.vault))]
        self.assertEqual(ids, [])

    def test_suggestions_skip_boilerplate_and_covered_topics(self):
        folder = self.vault / "günlük" / "oturumlar"
        folder.mkdir(parents=True)
        for i in range(4):
            (folder / f"o{i}.md").write_text(f"# Kullanıcı zeplin yol haritası {i}\n", encoding="utf-8")
        (folder / "m.md").write_text("# Mikrofon zeplin\n", encoding="utf-8")
        words = [x["word"] for x in k.status(self.vault)["suggestions"]]
        self.assertIn("zeplin", words)
        self.assertNotIn("kullanıcı", words)
        self.assertNotIn("mikrofon", words)

    def test_upkeep_runs_every_step_and_reports_failure(self):
        folder = self.vault / "bilgi" / "konu-sentezleri"
        folder.mkdir(parents=True)
        (folder / "user.md").write_text("elle yazılmış\n", encoding="utf-8")
        result = k.maintain(self.vault, apply=True)
        self.assertFalse(result["ok"])
        self.assertTrue((self.vault / "beyin" / "Beyin.md").is_file())
        self.assertEqual((folder / "user.md").read_text(encoding="utf-8"), "elle yazılmış\n")
        self.assertTrue(any("error" in step for step in result["steps"]))


if __name__ == "__main__":
    unittest.main()
