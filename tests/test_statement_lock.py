"""Offline source-envelope checks. No sibling checkout, model or Lean required."""
from __future__ import annotations

import hashlib

import pytest

from jevops import statement_lock as lock


PATTERNS = (
    {"kind": "threshold", "fail": 19, "meet": 20},
    {"kind": "conjunction", "bounds": [20, 30]},
    {"kind": "amount", "base": 100, "extra": 10, "cutoff": 5},
)
SOURCE = lock.render_lean(PATTERNS[0])


@pytest.mark.parametrize("pattern", PATTERNS)
def test_every_renderer_package_is_preserved_exactly(pattern):
    source = lock.render_lean(pattern)
    result = lock.lock_statement(source, source)
    assert result["ok"], result
    assert result["source"] == source
    assert result["lock"]["verification_performed"] is False
    assert result["lock"]["candidate_source_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert result["lock"]["expected_source_sha256"] == result["lock"]["candidate_source_sha256"]


@pytest.mark.parametrize("reply", [
    "decide", "rfl", "exact rfl", "unfold meets bound\ndecide",
    "constructor <;> decide", "constructor\n· decide\n· rfl",
    "unfold meets bound; constructor <;> decide",
    "simp only [meets, bound]", "simpa [meets, bound]",
    "constructor\nall_goals decide", "simp only []",
])
def test_bounded_proof_edits_only_change_the_body(reply):
    result = lock.lock_statement(SOURCE, reply)
    assert result["ok"], result
    head = SOURCE.partition(":= by")[0] + ":= by"
    assert result["source"].startswith(head)
    assert all(not line.strip() or line.startswith("  ") for line in result["source"][len(head):].splitlines())
    assert result["lock"]["protected_sha256"] == lock.lock_statement(SOURCE, SOURCE)["lock"]["protected_sha256"]


def test_helper_substitution_that_preserves_boundary_examples_is_rejected():
    malicious = SOURCE.replace("decide (bound <= n)", "decide (n = bound)")
    # The old statement-only comparison accepted this change, which changes
    # behavior for n > bound while retaining the checked boundary examples.
    assert lock.statements(SOURCE) == lock.statements(malicious)
    result = lock.lock_statement(SOURCE, malicious)
    assert result == {"ok": False, "error": "definitions_changed", "source": ""}


@pytest.mark.parametrize("mutate", [
    lambda s: s.replace("def bound : Nat := 20", "def bound : Nat := 21"),
    lambda s: s.replace("def bound : Nat := 20\n", ""),
    lambda s: "def extra : Nat := 0\n" + s,
    lambda s: s.replace("bound <= n", "bound < n"),
    lambda s: s.replace("def bound : Nat", "def bound : Int"),
    lambda s: s.replace("def bound :", "def bound  :"),
])
def test_any_definition_edit_or_added_helper_is_rejected(mutate):
    result = lock.lock_statement(SOURCE, mutate(SOURCE))
    assert not result["ok"] and not result["source"]


@pytest.mark.parametrize("mutate", [
    lambda s: s.replace("theorem boundary", "theorem weaker"),
    lambda s: s.replace("meets 20 = true", "meets 21 = true"),
    lambda s: s.replace(" /\\ ", " \\/ "),
    lambda s: s.replace("theorem boundary :", "theorem boundary (h : False) :"),
    lambda s: s + "theorem injected : True := by trivial\n",
])
def test_changed_names_types_binders_and_theorem_count_fail(mutate):
    result = lock.lock_statement(SOURCE, mutate(SOURCE))
    assert not result["ok"] and not result["source"]


@pytest.mark.parametrize("tactic", [
    "sorry", "(sorry)", "exact sorryAx", "admit", "exact (by sorry)",
    "native_decide", "decide +native", "run_tac pure ()", "set_option maxRecDepth 0 in decide",
    "exact (unsafeCast True.intro)", "simp [unknown]", "unfold unknown",
    "rfl\n#eval IO.println 1", "rfl\naxiom falseProof : False",
    "rfl\ndef replacement : Nat := 0", "rfl\nnamespace Evil", "rfl\nend",
    'rfl\nrun_tac logInfo "x"', "rfl -- ignored", "rfl /- comment -/",
    "rfl\n/- unfinished", "rfl\nattribute [simp] bound", "rfl;", ";rfl",
    "all_goals all_goals decide", "simp [bound,]", "simp [bound,,meets]",
    "rfl\r#eval 1", "rfl\x00", "rfl\u2028#eval 1", "rfl\t", "rfl\u00a0",
])
def test_unsupported_or_escaping_proofs_fail_in_both_reply_forms(tactic):
    head = SOURCE.partition(":= by")[0] + ":= by"
    for reply in (tactic, head + "\n  " + tactic.replace("\n", "\n  ") + "\n"):
        result = lock.lock_statement(SOURCE, reply)
        assert not result["ok"], reply
        assert result["source"] == ""


@pytest.mark.parametrize("prefix", ["import Mathlib\n", "import\tMathlib\n", "import\nMathlib\n"])
def test_imports_keep_the_legacy_error_before_execution(prefix):
    assert lock.lock_statement(SOURCE, prefix + SOURCE)["error"] == "imports_refused"
    assert lock.lock_statement(prefix + SOURCE, SOURCE)["error"] == "imports_refused"


@pytest.mark.parametrize("suffix", [
    "#eval 1\n", "def changed : Nat := 1\n", "end\n", "set_option autoImplicit true\n",
    "namespace Extra\n", "@[simp] theorem x : True := by trivial\n",
])
def test_trailing_commands_are_not_swallowed_as_proof(suffix):
    assert not lock.lock_statement(SOURCE, SOURCE + suffix)["ok"]


@pytest.mark.parametrize("pattern", PATTERNS[1:])
def test_multiple_theorems_keep_individual_slots_and_order(pattern):
    source = lock.render_lean(pattern)
    # One proof per theorem in a full package; no bare-reply ambiguity.
    edited = source.replace("  decide\n", "  rfl\n")
    result = lock.lock_statement(source, edited)
    assert result["ok"] and result["source"] == edited
    assert len(result["lock"]["theorems"]) == 2
    assert lock.lock_statement(source, "decide")["error"] == "proof_per_theorem_required"
    start = source.index("theorem ")
    first, second = source[start:].split("theorem ")[1:]
    reordered = source[:start] + "theorem " + second + "theorem " + first
    assert lock.lock_statement(source, reordered)["error"] == "statement_changed"
    missing = source[:start] + "theorem " + first
    assert lock.lock_statement(source, missing)["error"] == "statement_changed"


def test_inline_and_missing_final_newline_and_theorem_only_compatibility():
    source = "theorem boundary : True := by\n  trivial\n"
    result = lock.lock_statement(source, "theorem boundary : True := by trivial")
    assert result["ok"] and result["source"].endswith("by trivial\n")
    assert lock.lock_statement(source.rstrip(), "trivial")["ok"]
    assert not lock.lock_statement(source, "theorem boundary : True := byrfl")["ok"]


def test_content_identities_separate_proof_changes_from_protected_context():
    first = lock.lock_statement(SOURCE, "decide")["lock"]
    second = lock.lock_statement(SOURCE, "rfl")["lock"]
    assert first["protected_sha256"] == second["protected_sha256"]
    assert first["candidate_source_sha256"] != second["candidate_source_sha256"]
    changed = SOURCE.replace("Nat := 20", "Nat := 21")
    assert lock.lock_statement(changed, "decide")["lock"]["protected_sha256"] != first["protected_sha256"]
    # `ok` is not proof: even a false trusted target is only source-locked.
    false_target = "theorem boundary : False := by\n  rfl\n"
    assert lock.lock_statement(false_target, "rfl")["lock"]["verification_performed"] is False


@pytest.mark.parametrize("bad", [None, False, 7, b"rfl", {}, ["rfl"], "\ud800"])
def test_invalid_input_types_and_unicode_fail_closed(bad):
    assert not lock.lock_statement(SOURCE, bad)["ok"]
    assert not lock.lock_statement(bad, "rfl")["ok"]


def test_bounds_apply_to_input_and_assembled_source(monkeypatch):
    assert lock.lock_statement(SOURCE, "rfl" + " " * lock.MAX_SOURCE_BYTES)["error"] == "source_too_large"
    assert not lock.lock_statement(SOURCE, "rfl\n" * (lock.MAX_PROOF_LINES + 1))["ok"]
    assert not lock.lock_statement(SOURCE, " <;> ".join(["rfl"] * (lock.MAX_PROOF_STEPS + 1)))["ok"]
    many = "".join(f"theorem t{i} : True := by trivial\n" for i in range(lock.MAX_THEOREMS + 1))
    assert not lock.lock_statement(many, many)["ok"]
    monkeypatch.setattr(lock, "MAX_SOURCE_BYTES", len(SOURCE.encode()))
    assert lock.lock_statement(SOURCE, SOURCE)["ok"]
    # Reply fits by itself, but inserting it into the immutable prefix does not.
    reply = "rfl\n" * 20
    assert len(reply.encode()) < lock.MAX_SOURCE_BYTES
    assert lock.lock_statement(SOURCE, reply)["error"] == "source_too_large"


def test_byte_limit_not_character_count_and_normalized_newline_is_charged(monkeypatch):
    assert lock.lock_statement(SOURCE, "·" * (lock.MAX_SOURCE_BYTES // 2 + 1))["error"] == "source_too_large"
    source = "theorem t : True := by trivial"
    monkeypatch.setattr(lock, "MAX_SOURCE_BYTES", len(source.encode()))
    assert lock.lock_statement(source, source)["error"] == "source_too_large"


def test_exact_proof_line_and_step_boundaries_are_not_defaults():
    # The inserted newline after `by` counts toward the line limit.
    exact_lines = "rfl\n" * (lock.MAX_PROOF_LINES - 1)
    assert lock.lock_statement(SOURCE, exact_lines)["ok"]
    assert not lock.lock_statement(SOURCE, exact_lines + "rfl\n")["ok"]
    exact_steps = " <;> ".join(["rfl"] * lock.MAX_PROOF_STEPS)
    assert lock.lock_statement(SOURCE, exact_steps)["ok"]
    assert not lock.lock_statement(SOURCE, exact_steps + " <;> rfl")["ok"]


@pytest.mark.parametrize("bound", [1, 2, 19, 20, 31, 100, 365, 10000])
def test_generated_numeric_contexts_keep_proof_edits_and_reject_helper_drift(bound):
    source = lock.render_lean({"kind": "threshold", "fail": bound - 1, "meet": bound})
    assert lock.lock_statement(source, "unfold meets bound\ndecide")["ok"]
    for replacement in ("n = bound", "bound < n", "True", "False"):
        forged = source.replace("bound <= n", replacement)
        assert lock.statements(source) == lock.statements(forged)
        assert lock.lock_statement(source, forged)["error"] == "definitions_changed"


@pytest.mark.parametrize("source", [
    "def bound : Nat := 20\n", "", "namespace N\n" + SOURCE,
    SOURCE.replace("Nat := 20", "Nat := by decide"),
    SOURCE.replace("  decide", "  native_decide"),
    SOURCE + "theorem boundary : True := by trivial\n",
])
def test_unsupported_expected_packages_are_not_guessed(source):
    assert not lock.lock_statement(source, "rfl")["ok"]


def test_failed_proof_edit_cannot_mutate_a_later_lock():
    initial = lock.lock_statement(SOURCE, SOURCE)
    assert not lock.lock_statement(SOURCE, SOURCE.replace("<=", "="))["ok"]
    assert lock.lock_statement(SOURCE, SOURCE) == initial
