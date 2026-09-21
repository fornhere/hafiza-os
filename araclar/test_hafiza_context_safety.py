"""Decision details must not weaken a canonical claim; no external I/O."""
import copy
import unittest

import hafiza as h


class DecisionDetailSafetyTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(
            memory_id="presentation-rule", status="active", scope="project:alpha",
            rationale="Kısa cümleler küçük ekranda daha rahat okunur.",
            conditions="Yalnız küçük ekran için hazırlanan sunumlarda.",
        )
        self.item = dict(memory="Sunum metninde kısa cümleler kullanılır.",
                         metadata=copy.deepcopy(self.row))

    def package(self, item=None, **kwargs):
        return h.context_from_results(
            [self.item if item is None else item], query="sunum",
            scope="project:alpha", **kwargs)

    def test_canonical_details_override_nonempty_remote_details(self):
        item = copy.deepcopy(self.item)
        item["metadata"].update(rationale="Eski uzak gerekçe metni.",
                                conditions="Her durumda uygulanır.")
        before = copy.deepcopy(item)
        result = self.package(item, records=[self.row])
        self.assertEqual(["presentation-rule"], result["memory_ids"])
        for field in ("rationale", "conditions"):
            self.assertIn(self.row[field], result["text"])
            self.assertNotIn(item["metadata"][field], result["text"])
        self.assertEqual(before, item)

    def test_remote_cannot_add_fields_absent_from_canonical_record(self):
        row = {k: v for k, v in self.row.items() if k not in ("rationale", "conditions")}
        result = self.package(records=[row])
        self.assertIn(self.item["memory"], result["text"])
        self.assertNotIn("Gerekçe:", result["text"])
        self.assertNotIn("Geçerlilik koşulu:", result["text"])

    def test_invalid_or_secret_details_omit_entire_record(self):
        for field in ("rationale", "conditions"):
            for value in (["koşul"], {"text": "koşul"}, True, 42,
                          "api_key = " + "TEST-ONLY-NOT-A-CREDENTIAL"):
                for canonical in (False, True):
                    with self.subTest(field=field, value=value, canonical=canonical):
                        row = dict(self.row, **{field: value})
                        item = dict(self.item, metadata=row)
                        result = (self.package(records=[row]) if canonical
                                  else self.package(item))
                        self.assertEqual([], result["memory_ids"])
                        self.assertEqual("", result["text"])

    def test_none_and_blank_optional_fields_keep_legacy_format(self):
        absent = {k: v for k, v in self.row.items() if k not in ("rationale", "conditions")}
        expected = self.package(dict(self.item, metadata=absent))["text"]
        for value in (None, "", "  "):
            row = dict(absent, rationale=value, conditions=value)
            result = self.package(dict(self.item, metadata=row))
            self.assertEqual(expected, result["text"])
            self.assertEqual(["presentation-rule"], result["memory_ids"])


if __name__ == "__main__":
    unittest.main()
