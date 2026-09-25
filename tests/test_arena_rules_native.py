"""Explicit installed-Lean checks of generated portable drafts, not fixtures."""
import os
from pathlib import Path

import pytest

from jevops import arena_lean as native
from jevops.arena import Outcome, VerificationRequest
from jevops.arena_rules import portable_proposal
from jevops.lean import VersionPin

pytestmark = pytest.mark.no_seal(reason="fresh pinned Lean proof checks; external toolchain inputs")


@pytest.mark.parametrize("rule,statement,body", [
    ("port_exact_hyp", "theorem rule_native (h : True) : True", "  exact h"),
    ("port_ctor_pair_exacts", "theorem rule_native (p q : Prop) (hp : p) (hq : q) : p ∧ q",
     "  constructor\n  · exact hp\n  · exact hq"),
    ("port_trim_intro_names", "theorem rule_native : ∀ n : Nat, True", "  intro n\n  trivial"),
    ("port_trailing_tuple_comma", "theorem rule_native (h : True) : True ∧ True", "  exact ⟨h, h,⟩"),
    ("port_drop_try_simp_all", "theorem rule_native (n : Nat) : n = n",
     "  cases n <;>\n    simp at * <;>\n    try simp_all"),
])
def test_portable_generated_candidate_is_checked_with_its_original(tmp_path, rule, statement, body):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no downloads or PATH toolchain")
    tag = "v4.26.0"
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    pin = VersionPin(tag, "local-portable-rules-regression")
    source = statement + " := by\n" + body
    candidate = portable_proposal(source, statement, rule)
    assert candidate is not None and candidate != source
    record = {"name": "rule_native", "statement": statement, "src": source,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, "", project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    receipt = verifier(VerificationRequest(verifier.context(record), candidate, pin))
    assert receipt.outcome == Outcome.VERIFIED, receipt
    assert verifier.processes == 1 and receipt.type_preserved
