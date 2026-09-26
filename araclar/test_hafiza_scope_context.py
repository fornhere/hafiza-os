"""Scope/condition contract regressions; real CLI/catalog, fake remote I/O only."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hafiza as h


STATEMENT = "Sunumlarda kısa cümle kullan."
ALTERNATIVE = "Sunumlarda ayrıntılı açıklamalar kullan."
RATIONALE = "Çünkü okunabilirlik önceliklidir."
CONDITIONS = "Yalnız küçük ekranda gösterilen sunumlarda geçerlidir."


class VaultFixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        self.source = self.vault / "source.md"
        self.source.write_text("\n".join(
            (STATEMENT, ALTERNATIVE, RATIONALE, CONDITIONS)), encoding="utf-8")
        self.row = dict(
            memory_id="presentation-style", kind="semantic", scope="project:alpha",
            subject_key="presentation.style", statement=STATEMENT, status="active",
            source_path="source.md", source_anchor="sunum",
            source_hash=h.statement_hash(STATEMENT),
            source_content_hash=h.statement_hash(self.source.read_text(encoding="utf-8")),
            observed_at="2020-01-01", valid_from="2020-01-01", valid_to=None,
            confidence="explicit-user", sensitivity="normal", mem0_id=None,
            supersedes=None, reviewed_by="reviewer", schema_version=1,
            rationale=RATIONALE, conditions=CONDITIONS,
        )
        h._write_jsonl(self.vault / h.CATALOG_PATH, [self.row])

    def queue(self, scope, statement=STATEMENT, subject_key="presentation.style"):
        return h.add_candidate(
            self.vault, statement=statement, scope=scope, subject_key=subject_key,
            kind="semantic", source_path="source.md", source_anchor="sunum",
            confidence="explicit-user", sensitivity="normal", proposed_by="worker",
        )

    def item(self, row=None):
        row = self.row if row is None else row
        return {"memory": row["statement"], "metadata": copy.deepcopy(row)}

    def remote_item(self):
        # Matches the real index metadata: rationale/conditions are intentionally absent.
        return {"id": "remote-result", "memory": "stale remote text",
                "metadata": {"memory_id": self.row["memory_id"], "status": "active",
                             "scope": self.row["scope"], "source_path": "source.md"}}

    def package(self, items=None, **kwargs):
        return h.context_from_results(
            [self.item()] if items is None else items,
            query="sunum", scope="project:alpha", **kwargs)

    def cli(self, *flags, query="sunum"):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = h.main(["--vault", str(self.vault), "context", query,
                           "--scope", "project:alpha", *flags])
        return code, json.loads(output.getvalue())

    def assert_details(self, package):
        self.assertEqual([self.row["memory_id"]], package["memory_ids"])
        self.assertIn(STATEMENT, package["text"])
        self.assertIn("Gerekçe: " + RATIONALE, package["text"])
        self.assertIn("Geçerlilik koşulu: " + CONDITIONS, package["text"])
        self.assertIn("kaynak: source.md", package["text"])


class ScopeContractTests(VaultFixture):
    def test_queue_same_statement_in_different_projects(self):
        first = self.queue("project:alpha")
        second = self.queue("project:beta")
        self.assertEqual("queued", first["result"])
        self.assertEqual("queued", second["result"])
        self.assertNotEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(2, len(h.load_jsonl(self.vault / h.CANDIDATE_PATH)))

    def test_queue_normalized_same_statement_in_same_scope_is_duplicate(self):
        first = self.queue("project:alpha")
        second = self.queue("project:alpha", "  " + STATEMENT.replace(" ", "  ") + "  ")
        self.assertEqual("duplicate", second["result"])
        self.assertEqual(first["candidate_id"], second["candidate_id"])
        self.assertEqual(1, len(h.load_jsonl(self.vault / h.CANDIDATE_PATH)))

    def test_assess_same_statement_in_different_projects(self):
        candidate = dict(self.row, scope="project:beta")
        self.assertEqual("eligible", h.assess_candidate(candidate, [self.row])["result"])

    def test_assess_same_subject_key_in_different_projects(self):
        candidate = dict(self.row, scope="project:beta", statement=ALTERNATIVE)
        self.assertEqual("eligible", h.assess_candidate(candidate, [self.row])["result"])

    def test_assess_conflict_in_same_scope(self):
        candidate = dict(self.row, statement=ALTERNATIVE)
        self.assertEqual(
            {"result": "conflict", "conflicts_with": self.row["memory_id"]},
            h.assess_candidate(candidate, [self.row]))

    def test_foreign_match_cannot_hide_same_scope_conflict(self):
        candidate = dict(self.row, statement=ALTERNATIVE)
        foreign = dict(candidate, scope="project:beta", memory_id="foreign")
        self.assertEqual(
            {"result": "conflict", "conflicts_with": self.row["memory_id"]},
            h.assess_candidate(candidate, [foreign, self.row]))

    def test_user_and_project_are_independent_in_both_directions(self):
        for left, right in (("user", "project:alpha"), ("project:alpha", "user")):
            for statement in (STATEMENT, ALTERNATIVE):
                with self.subTest(left=left, right=right, statement=statement):
                    candidate = dict(self.row, scope=left, statement=statement)
                    existing = dict(self.row, scope=right)
                    self.assertEqual("eligible", h.assess_candidate(candidate, [existing])["result"])
        self.assertEqual("queued", self.queue("user")["result"])
        self.assertEqual("queued", self.queue("project:alpha")["result"])

    def test_legacy_missing_scope_keeps_user_conflict_behavior(self):
        existing = dict(self.row)
        existing.pop("scope")
        candidate = dict(existing, statement=ALTERNATIVE)
        self.assertEqual("conflict", h.assess_candidate(candidate, [existing])["result"])
        candidate["scope"] = "project:alpha"
        self.assertEqual("eligible", h.assess_candidate(candidate, [existing])["result"])

    def test_same_scope_exact_statement_still_duplicates_across_subject_keys(self):
        candidate = dict(self.row, subject_key="other.key", statement="  " + STATEMENT + "  ")
        self.assertEqual("duplicate", h.assess_candidate(candidate, [self.row])["result"])

    def test_project_promotion_does_not_supersede_user_or_other_project(self):
        h._write_jsonl(self.vault / h.CATALOG_PATH, [dict(self.row, scope="user")])
        for scope, ident in (("project:alpha", "alpha-style"), ("project:beta", "beta-style")):
            queued = self.queue(scope, ALTERNATIVE)
            result = h.promote_candidate(
                self.vault, queued["candidate_id"], memory_id=ident,
                reviewed_by="reviewer", apply=True)
            self.assertEqual("promoted", result["result"])
        rows = h.load_catalog(self.vault)
        self.assertEqual(3, len(rows))
        self.assertTrue(all(row["status"] == "active" and row["supersedes"] is None for row in rows))
        self.assertEqual({"user", "project:alpha", "project:beta"}, {row["scope"] for row in rows})

    def test_review_gate_is_not_removed(self):
        queued = self.queue("project:beta")
        with self.assertRaisesRegex(ValueError, "inceleyen"):
            h.promote_candidate(self.vault, queued["candidate_id"],
                                memory_id="beta-style", reviewed_by=None, apply=True)
        self.assertEqual([self.row], h.load_catalog(self.vault))


class ContextContractTests(VaultFixture):
    def test_formatter_preserves_both_details(self):
        self.assert_details(self.package())

    def test_legacy_record_without_optional_fields_keeps_output(self):
        row = dict(self.row)
        row.pop("rationale")
        row.pop("conditions")
        result = self.package([self.item(row)])
        self.assertEqual(
            "Aranan kapsam: user + project:alpha\n- [presentation-style] " + STATEMENT
            + " (kaynak: source.md; tarih: 2020-01-01; güven: explicit-user; "
            "kapsam: project:alpha; sınıf: incelenmiş kayıt)", result["text"])

    def test_source_class_labels_follow_evidence_and_review_priority(self):
        cases = [({}, "aday"), ({"evidence_source": "", "reviewed_by": None}, "aday"),
                 ({"reviewed_by": "reviewer"}, "incelenmiş kayıt"),
                 ({"evidence_source": None, "reviewed_by": "reviewer"}, "incelenmiş kayıt"),
                 ({"evidence_source": "user-message.md"}, "doğrulanmış kullanıcı beyanı"),
                 ({"evidence_source": "user-message.md", "reviewed_by": "reviewer"},
                  "doğrulanmış kullanıcı beyanı")]
        for fields, expected in cases:
            row = dict(self.row)
            row.pop("reviewed_by")
            row.update(fields)
            for canonical in (False, True):
                with self.subTest(fields=fields, canonical=canonical):
                    result = (self.package([self.remote_item()], records=[row]) if canonical
                              else self.package([self.item(row)]))
                    self.assertIn("sınıf: " + expected + ")", result["text"])

    def test_canonical_scope_and_class_override_remote_metadata(self):
        item = self.item(dict(self.row, evidence_source="remote-message.md"))
        row = dict(self.row, scope="user")
        result = self.package([item], records=[row])
        self.assertIn("kapsam: user; sınıf: incelenmiş kayıt)", result["text"])
        row.pop("scope")
        row.pop("reviewed_by")
        result = self.package([item], records=[row])
        self.assertIn("kapsam: bilinmiyor; sınıf: aday)", result["text"])

    def test_missing_metadata_scope_is_unknown(self):
        row = dict(self.row)
        row.pop("scope")
        result = h.context_from_results([self.item(row)], query="sunum", scope=None)
        self.assertIn("kapsam: bilinmiyor; sınıf: incelenmiş kayıt)", result["text"])

    def test_scope_header_is_first_and_does_not_count_as_record(self):
        for scope, expected in ((None, "tümü"), ("user", "user"),
                                ("project:alpha", "user + project:alpha")):
            with self.subTest(scope=scope):
                result = h.context_from_results(
                    [self.item(dict(self.row, scope="user"))], query="sunum", scope=scope)
                self.assertEqual("Aranan kapsam: " + expected, result["text"].splitlines()[0])
                self.assertEqual(1, result["included"])
                self.assertEqual([self.row["memory_id"]], result["memory_ids"])
                self.assertIn("kapsam: user; sınıf: incelenmiş kayıt)", result["text"])

    def test_scope_header_deduplicates_extra_scopes_in_order(self):
        self.assertEqual(
            "Aranan kapsam: user + project:alpha + project:w + project:z",
            h.context_scope_header("project:alpha",
                                   ["project:w", "project:alpha", "user", "project:z", "project:w"]))

    def test_no_records_means_no_scope_header(self):
        for items in ([], [self.item(dict(self.row, scope="project:beta"))]):
            with self.subTest(items=items):
                result = self.package(items)
                self.assertEqual("", result["text"])
                self.assertEqual(0, result["included"])
                self.assertEqual([], result["memory_ids"])

    def test_budget_is_atomic_and_later_small_record_can_fit(self):
        full = self.package()
        size = len(full["text"])
        exact = self.package(char_budget=size)
        self.assert_details(exact)
        self.assertEqual(full["text"], exact["text"])
        self.assertEqual(1, exact["included"])
        for budget in (0, size - 1):
            with self.subTest(budget=budget):
                result = self.package(char_budget=budget)
                self.assertEqual(0, result["included"])
                self.assertEqual([], result["memory_ids"])
                self.assertEqual("", result["text"])
        short = dict(self.row, memory_id="short", statement="Kısa not.")
        short.pop("rationale")
        short.pop("conditions")
        result = self.package([self.item(), self.item(short)], char_budget=size - 1)
        self.assertEqual(["short"], result["memory_ids"])
        self.assertNotIn(STATEMENT, result["text"])
        self.assertLessEqual(len(result["text"]), size - 1)

    def test_formatter_does_not_mutate_results_or_catalog(self):
        items = [self.remote_item()]
        rows = [self.row]
        before = copy.deepcopy((items, rows))
        self.package(items, records=rows)
        self.assertEqual(before, (items, rows))

    def test_mem0_builder_restores_missing_details_by_memory_id(self):
        remote = self.remote_item()
        remote["memory"] = STATEMENT
        client = FakeSearch(remote)
        result = h.build_context_package(
            client, query="sunum", scope="project:alpha", records=[self.row])
        self.assert_details(result)
        self.assertEqual(1, len(client.calls))

    def test_mem0_builder_budget_includes_restored_conditions(self):
        remote = self.remote_item()
        remote["memory"] = STATEMENT
        bare = self.package([remote])
        result = h.build_context_package(
            FakeSearch(remote), query="sunum", scope="project:alpha",
            records=[self.row], char_budget=len(bare["text"]))
        self.assertEqual([], result["memory_ids"])
        self.assertEqual("", result["text"])

    def test_local_cli_keeps_conditions_and_rationale(self):
        with patch.object(h, "Mem0HttpClient", side_effect=AssertionError("unexpected remote I/O")):
            code, result = self.cli("--local")
        self.assertEqual(0, code)
        self.assertEqual("local", result["mode"])
        self.assert_details(result)

    def remote_cli(self, *flags):
        client = FakeSearch(self.remote_item())
        with patch.object(h, "Mem0HttpClient", return_value=client), patch.object(
                h, "load_api_key", return_value="test-placeholder"):
            # No lexical overlap: a silent fallback cannot make this test pass.
            code, result = self.cli(*flags, query="xyzunmatchedquery")
        self.assertEqual(1, len(client.calls))
        self.assertEqual("remote+local", result["mode"])
        self.assertIsNone(result["fallback_reason"])
        return code, result

    def test_remote_cli_hydrates_missing_details_from_current_catalog(self):
        code, result = self.remote_cli("--remote")
        self.assertEqual(0, code)
        self.assert_details(result)
        self.assertNotIn("stale remote text", result["text"])

    def test_enabled_mem0_config_uses_same_formatter_without_remote_flag(self):
        config = self.vault / "komuta/mem0.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"enabled": True, "user_id": "test-user"}), encoding="utf-8")
        code, result = self.remote_cli()
        self.assertEqual(0, code)
        self.assert_details(result)

    def test_local_cli_skips_whole_record_when_conditions_do_not_fit(self):
        code, full = self.cli("--local")
        self.assertEqual(0, code)
        code, result = self.cli("--local", "--char-budget", str(len(full["text"]) - 1))
        self.assertEqual(0, code)
        self.assertEqual(0, result["included"])
        self.assertEqual("", result["text"])

    def test_remote_cli_skips_whole_record_when_conditions_do_not_fit(self):
        code, full = self.remote_cli("--remote")
        self.assertEqual(0, code)
        code, result = self.remote_cli("--remote", "--char-budget", str(len(full["text"]) - 1))
        self.assertEqual(0, code)
        self.assertEqual(0, result["included"])
        self.assertEqual("", result["text"])

    def test_remote_cli_does_not_restore_a_changed_source(self):
        self.source.write_text("Changed source revision.", encoding="utf-8")
        code, result = self.remote_cli("--remote")
        self.assertEqual(1, code)
        self.assertTrue(result["catalog_errors"])
        self.assertEqual([], result["memory_ids"])
        self.assertEqual("", result["text"])

    def test_project_context_can_include_user_and_project_but_not_other_project(self):
        rows = [self.row, dict(self.row, memory_id="general", scope="user"),
                dict(self.row, memory_id="other-project", scope="project:beta")]
        h._write_jsonl(self.vault / h.CATALOG_PATH, rows)
        code, result = self.cli("--local", "--char-budget", "2000")
        self.assertEqual(0, code)
        self.assertEqual({"presentation-style", "general"}, set(result["memory_ids"]))
        self.assertEqual(2, result["text"].count(CONDITIONS))
        self.assertEqual("Aranan kapsam: user + project:alpha", result["text"].splitlines()[0])
        self.assertEqual(2, result["included"])
        self.assertIn("kapsam: project:alpha; sınıf: incelenmiş kayıt)", result["text"])
        self.assertIn("kapsam: user; sınıf: incelenmiş kayıt)", result["text"])


class FakeSearch:
    def __init__(self, result):
        self.result = copy.deepcopy(result)
        self.user_id = "test-user"
        self.calls = []

    def search_memories(self, query, filters, top_k=10, threshold=0.1):
        self.calls.append((query, filters, top_k, threshold))
        return [copy.deepcopy(self.result)]


if __name__ == "__main__":
    unittest.main()
