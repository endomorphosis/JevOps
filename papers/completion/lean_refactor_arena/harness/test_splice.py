#!/usr/bin/env python3
"""Unit tests for prefix splice on all 15 frozen Lean Refactor Arena warm-up records.

Asserts ``src.startswith(statement)`` and that the body is the suffix after the
statement. Named ``:=`` inside types stays in the frozen statement. Lexical
admission uses ``statement + " := by\\nsorry"`` plus tactic-only proof_text.
Does not compile, does not rewrite the JSONL, and does not claim Arena scores.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import splice  # noqa: E402

FROZEN = splice.FROZEN_WARMUP_SHA256
CCS_NAME = "Cslib.CCS.bisimilarity_congr_choice"
FOLD_NAME = "Binius.BinaryBasefold.fold_advances_evaluation_poly"
WICK_NAME = "FieldSpecification.WickAlgebra.ι_timeOrderF_superCommuteF_eq_time"
NAMED_ASSIGN_NAMES = (
    "CallElimCorrect.substOldPostSubset",
    CCS_NAME,
    "Binius.BinaryBasefold.fiberwise_dist_lt_imp_dist_lt_unique_decoding_radius",
    FOLD_NAME,
    "interleaved_affine_gaps_imply_tensor_gaps",
)


def _load() -> tuple[bytes, str, list[dict]]:
    return splice.load_warmup_records()


def _by_name(records: list[dict]) -> dict[str, dict]:
    return {record["name"]: record for record in records}


def _naive_first_assign_body(src: str) -> str:
    """The forbidden split: cut at the first ``:=``. Tests use this only as a counterexample."""

    index = src.find(":=")
    if index < 0:
        raise AssertionError("src has no := to misuse")
    return src[index:]


class TestFrozenWarmupJsonl(unittest.TestCase):
    def test_sha256_is_frozen_and_file_is_not_rewritten(self) -> None:
        path = splice.WARMUP_JSONL
        before = splice.sha256_file(path)
        raw, digest, records = _load()
        after = splice.sha256_file(path)
        self.assertEqual(before, FROZEN)
        self.assertEqual(digest, FROZEN)
        self.assertEqual(after, FROZEN)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), FROZEN)
        self.assertEqual(len(records), splice.WARMUP_N)
        self.assertEqual(len(records), 15)
        self.assertEqual(len(raw), 113826)

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "warmup.jsonl"
            fake.write_text('{"name":"x"}\n', encoding="utf-8")
            with self.assertRaises(splice.DigestMismatch):
                splice.load_warmup_records(fake)

    def test_schema_has_twelve_fields_and_putnam_omits_line_span(self) -> None:
        _, _, records = _load()
        self.assertEqual(len(splice.JSONL_FIELDS), 12)
        seen: set[str] = set()
        for record in records:
            with self.subTest(name=record["name"]):
                self.assertTrue(set(splice.REQUIRED_JSONL_FIELDS).issubset(record.keys()))
                seen.update(record.keys())
                if record["source"] == "putnambench":
                    self.assertNotIn("start_line", record)
                    self.assertNotIn("end_line", record)
                else:
                    self.assertIn("start_line", record)
                    self.assertIn("end_line", record)
        self.assertTrue(set(splice.JSONL_FIELDS).issubset(seen))


class TestPrefixBindAllFifteen(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw, cls.digest, cls.records = _load()
        cls.named = _by_name(cls.records)

    def test_covers_exactly_fifteen_records(self) -> None:
        self.assertEqual(len(self.records), 15)
        self.assertEqual(len(self.named), 15)
        self.assertEqual(self.digest, FROZEN)

    def test_every_record_src_startswith_statement(self) -> None:
        for record in self.records:
            with self.subTest(name=record["name"]):
                statement = record["statement"]
                src = record["src"]
                self.assertIsInstance(statement, str)
                self.assertIsInstance(src, str)
                self.assertTrue(statement)
                self.assertTrue(src.startswith(statement), record["name"])

    def test_body_is_the_suffix_after_the_statement(self) -> None:
        for record in self.records:
            with self.subTest(name=record["name"]):
                split = splice.split_statement_body(record)
                expected = record["src"][len(record["statement"]) :]
                self.assertEqual(split.body_suffix, expected)
                self.assertEqual(split.statement, record["statement"])
                self.assertEqual(split.reconstructed_src, record["src"])
                self.assertNotEqual(split.body_suffix, record["src"])
                self.assertTrue(
                    any(split.body_suffix.startswith(prefix) for prefix in splice.BODY_BY_PREFIXES),
                    record["name"],
                )

    def test_split_raises_when_prefix_bind_fails(self) -> None:
        record = dict(self.records[0])
        record["src"] = "not-the-statement " + record["src"]
        with self.assertRaises(splice.PrefixBindError):
            splice.split_statement_body(record)


class TestNamedAssignStaysInStatement(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, _, records = _load()
        cls.named = _by_name(records)

    def test_five_statements_contain_named_assign(self) -> None:
        present = [name for name in NAMED_ASSIGN_NAMES if ":=" in self.named[name]["statement"]]
        self.assertEqual(present, list(NAMED_ASSIGN_NAMES))
        self.assertEqual(len(present), 5)

    def test_ccs_first_assign_is_inside_the_117_byte_statement(self) -> None:
        record = self.named[CCS_NAME]
        statement = record["statement"]
        self.assertEqual(len(statement), 117)
        self.assertEqual(statement.find(":="), 55)
        self.assertIn("(defs := defs)", statement)
        split = splice.split_statement_body(record)
        self.assertIn("(defs := defs)", split.statement)
        self.assertTrue(split.body_suffix.lstrip().startswith(":= by"))

    def test_arklib_fold_keeps_twenty_seven_assigns_in_the_statement(self) -> None:
        record = self.named[FOLD_NAME]
        statement = record["statement"]
        self.assertEqual(statement.count(":="), 27)
        self.assertIn("by omega", statement)
        split = splice.split_statement_body(record)
        self.assertEqual(split.statement, statement)
        self.assertEqual(split.statement.count(":="), 27)
        self.assertIn("by omega", split.statement)

    def test_naive_first_assign_scan_is_not_the_body(self) -> None:
        for name in NAMED_ASSIGN_NAMES:
            record = self.named[name]
            with self.subTest(name=name):
                split = splice.split_statement_body(record)
                first = record["src"].find(":=")
                self.assertGreaterEqual(first, 0)
                self.assertLess(first, len(record["statement"]), name)
                naive = _naive_first_assign_body(record["src"])
                self.assertNotEqual(naive, split.body_suffix, name)
                self.assertEqual(naive, record["src"][first:])
                stolen = record["statement"][first:]
                self.assertTrue(naive.startswith(stolen), name)
                self.assertIn(":=", split.statement)


class TestNeverScanFirstAssign(unittest.TestCase):
    def test_splice_module_has_no_bare_assign_needle(self) -> None:
        source = Path(splice.__file__).read_text(encoding="utf-8")
        self.assertEqual(splice.source_assign_scan_issues(source), [])
        self.assertNotIn('.find(":=")', source)
        self.assertNotIn(".find(':=')", source)
        self.assertNotIn('.index(":=")', source)
        self.assertNotIn('.rfind(":=")', source)
        self.assertNotIn('.split(":=")', source)
        self.assertNotIn('.partition(":=")', source)
        self.assertNotIn('":=" in', source)
        self.assertNotIn("':=' in", source)

    def test_split_statement_body_source_uses_startswith_only(self) -> None:
        source = Path(splice.__file__).read_text(encoding="utf-8")
        start = source.index("def split_statement_body")
        end = source.index("\ndef ", start + 1)
        fragment = source[start:end]
        self.assertIn("src.startswith(statement)", fragment)
        self.assertIn("src[len(statement)", fragment)
        self.assertNotIn("find(", fragment)
        self.assertNotIn("index(", fragment)


class TestLexicalAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _, _, cls.records = _load()
        cls.named = _by_name(cls.records)

    def test_sorry_template_is_statement_plus_by_sorry_on_all_records(self) -> None:
        for record in self.records:
            with self.subTest(name=record["name"]):
                split = splice.split_statement_body(record)
                template = splice.statement_sorry_template(split.statement)
                self.assertTrue(template.startswith(split.statement))
                self.assertTrue(template.endswith(" := by\nsorry"))
                self.assertEqual(template, split.statement + " := by\nsorry")
                self.assertEqual(template.count("sorry"), 1)
                self.assertNotEqual(template, record["src"])

    def test_tactic_only_simp_on_all_fifteen_uses_the_sorry_template(self) -> None:
        for record in self.records:
            with self.subTest(name=record["name"]):
                view = splice.admission_view(record, "simp")
                self.assertTrue(view.native_source_starts_with_statement, record["name"])
                self.assertFalse(view.used_full_src_as_native)
                self.assertFalse(view.used_full_src_as_canonical)
                self.assertIsNone(view.arena_score)
                self.assertTrue(view.accepted, f"{record['name']}: {view.reason}")

    def test_forbidden_theorem_lemma_import_open_are_rejected(self) -> None:
        record = self.named[CCS_NAME]
        cases = {
            "theorem": "theorem foo : True := rfl",
            "lemma": "lemma bar : True := rfl",
            "import": "import Mathlib",
            "open": "open Nat",
        }
        for token, proof in cases.items():
            with self.subTest(token=token):
                self.assertIn(token, splice.forbidden_proof_tokens(proof))
                view = splice.admission_view(record, proof)
                self.assertFalse(view.accepted, token)
                self.assertIn(
                    view.failure_code,
                    {"forbidden_declaration", "forbidden_import", "theorem_substitution"},
                )

    def test_canonical_source_equal_to_src_trips_source_copy(self) -> None:
        record = self.named["putnam_1964_a4"]
        split = splice.split_statement_body(record)
        tactics = splice.tactic_block_from_body(split.body_suffix)
        admit = splice._admit_lean_proof_text()
        admission = admit(
            tactics,
            splice.statement_sorry_template(split.statement),
            theorem_id=split.name,
            canonical_source=record["src"],
            expected_statement="",
        )
        self.assertFalse(admission.accepted)
        self.assertEqual(admission.failure_code.value, "source_copy")

    def test_original_src_is_not_native_source(self) -> None:
        record = self.named["putnam_1964_a4"]
        admit = splice._admit_lean_proof_text()
        admission = admit(
            "simp",
            record["src"],
            theorem_id=record["name"],
            canonical_source="",
            expected_statement="",
        )
        self.assertFalse(admission.accepted)
        self.assertNotEqual(admission.failure_code.value, "")

    def test_putnam_header_stays_out_of_proof_text(self) -> None:
        for name in ("putnam_1964_a4", "putnam_1964_b2", "putnam_1995_a3"):
            record = self.named[name]
            with self.subTest(name=name):
                split = splice.split_statement_body(record)
                self.assertTrue(split.header.strip())
                self.assertIn("import Mathlib", split.header)
                self.assertFalse(record["src"].startswith(split.header))
                tactics = splice.tactic_block_from_body(split.body_suffix)
                self.assertNotIn("import", splice.forbidden_proof_tokens(tactics))
                self.assertNotRegex(tactics, r"(?im)^import\b")
                lake = splice.lake_candidate_source(
                    header=split.header,
                    statement=split.statement,
                    tactic_block="simp",
                )
                self.assertTrue(lake.startswith("import Mathlib"))
                self.assertIn(split.statement, lake)
                self.assertIn(" := by\nsimp", lake)

    def test_expected_statement_is_not_the_jsonl_prefix_bind(self) -> None:
        record = self.named[FOLD_NAME]
        split = splice.split_statement_body(record)
        admit = splice._admit_lean_proof_text()
        admission = admit(
            "simp",
            splice.statement_sorry_template(split.statement),
            theorem_id=split.name,
            canonical_source="",
            expected_statement=split.statement,
        )
        self.assertFalse(admission.accepted)
        self.assertEqual(admission.failure_code.value, "statement_mismatch")
        view = splice.admission_view(record, "simp")
        self.assertTrue(view.accepted)


class TestSelfCheck(unittest.TestCase):
    def test_self_check_covers_all_fifteen_and_keeps_digest(self) -> None:
        report = splice.self_check()
        self.assertTrue(report["ok"], json.dumps({k: report[k] for k in report if k != "records"}, indent=2))
        self.assertEqual(report["n_records"], 15)
        self.assertEqual(report["warmup_jsonl_sha256"], FROZEN)
        self.assertTrue(report["jsonl_unchanged"])
        self.assertTrue(report["prefix_bind_all"])
        self.assertTrue(report["never_scans_first_assign"])
        self.assertIsNone(report["arena_score"])
        self.assertFalse(report["compiled"])
        names = [item["name"] for item in report["records"]]
        self.assertEqual(len(names), 15)
        self.assertEqual(len(set(names)), 15)


def _install_per_record_prefix_tests() -> None:
    _, _, records = _load()
    assert len(records) == 15
    for record in records:
        safe = "".join(ch if ch.isalnum() else "_" for ch in record["name"])

        def _test(self: unittest.TestCase, rec: dict = record) -> None:
            split = splice.split_statement_body(rec)
            self.assertTrue(rec["src"].startswith(rec["statement"]), rec["name"])
            self.assertEqual(split.body_suffix, rec["src"][len(rec["statement"]) :])
            self.assertEqual(split.statement + split.body_suffix, rec["src"])
            tactics = splice.tactic_block_from_body(split.body_suffix)
            self.assertTrue(tactics)
            self.assertNotIn("import Mathlib", tactics)

        setattr(TestPrefixBindAllFifteen, f"test_record_{safe}", _test)


_install_per_record_prefix_tests()


def main(argv: list[str] | None = None) -> int:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    sys.stdout.write(stream.getvalue())
    report = {
        "ok": result.wasSuccessful(),
        "testsRun": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "n_records": splice.WARMUP_N,
        "frozen_warmup_sha256": FROZEN,
        "compiled": False,
        "arena_score": None,
    }
    if result.failures or result.errors:
        report["failure_details"] = [
            {"test": str(test), "detail": detail} for test, detail in result.failures + result.errors
        ]
    from jevops.outer import print_json

    print_json(report)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
