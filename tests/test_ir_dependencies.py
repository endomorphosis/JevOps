from __future__ import annotations

import pytest

from jevops import autoencoder as ae
from jevops.autoencoder_training import _canonical_ops
from jevops.ir_dependencies import close_deletions


def close(body: str, selected: list[int]) -> dict:
    source = "theorem fixture (p : Prop) (h : p) : p := by\n" + "\n".join("  " + s for s in body.splitlines())
    return close_deletions(body, _canonical_ops(ae.encode_lean_ir(source)), selected)


def test_dependency_closure_keeps_transitive_live_chain_but_drops_dead_chain() -> None:
    body = "have first : p := h\nhave second : p := first\nexact second"
    report = close(body, [2])
    assert report["supported"] and report["kept_indices"] == [0, 1, 2]
    assert report["restored"] == [
        {"index": 0, "reason": "required_dependency", "required_by": 1},
        {"index": 1, "reason": "required_dependency", "required_by": 2},
    ]
    assert close(body.replace("exact second", "exact h"), [2])["kept_indices"] == [2]


@pytest.mark.parametrize("body", [
    "have proof : p := h\nassumption",
    "have proof : p := h\nsimp_all",
    "have proof : p := h\nexact _",
    "have proof : p := h\nrefine ?_",
])
def test_context_search_and_holes_retain_local_facts(body: str) -> None:
    assert close(body, [1])["kept_indices"] == [0, 1]


@pytest.mark.parametrize("body", [
    "have α' : p := h\nexact α'",
    "have : p := h\nexact this",
    "have := h\nexact this",
    "have n : Nat := 3\nhave hn : n = n := rfl\nexact hn",
])
def test_unicode_anonymous_and_type_dependencies_are_retained(body: str) -> None:
    count = len(body.splitlines())
    report = close(body, [count - 1])
    assert report["supported"] and report["kept_indices"] == list(range(count))


@pytest.mark.parametrize("body", [
    "have h : p := h\nhave h : p := h\nexact h",
    "have ⟨a, b⟩ := h\nexact a",
    "have h : p := by\n  exact h\nexact h",
    "have h : p := h -- evidence\nexact h",
    "cases h\ncase left =>\n  exact h",
    "have h : p := h; exact h",
    "have h : p := h\nexact (by assumption)",
    "have h : p := h\nexact «h»",
    "have h : p := h\nlet x := h\nexact x",
])
def test_unsupported_scope_or_lexical_ambiguity_suppresses_deletions(body: str) -> None:
    report = close(body, [])
    assert not report["supported"]
    assert report["kept_indices"] and len(report["restored"]) == len(report["kept_indices"])


def test_stateful_steps_and_proof_closers_cannot_be_deleted_by_the_guarded_decoder() -> None:
    assert close("intro hp\nexact hp", [1])["kept_indices"] == [0, 1]
    assert close("have unused : True := True.intro\nexact h", [0])["kept_indices"] == [0, 1]


def test_guard_refuses_analysis_over_budget_or_misaligned_ir() -> None:
    assert close_deletions("x" * 40_000, [("exact", ["h"])], [])["reason"] == "analysis_budget"
    assert close_deletions("exact h", [("exact", ["k"])], [])["reason"] == "source_ir_alignment"


def test_model_reports_raw_selection_separately_and_never_uses_a_teacher() -> None:
    source = "theorem live (p : Prop) (h : p) : p := by\n  have proof : p := h\n  exact proof"
    model = ae.LeanIRAutoencoder()
    model.state["step"] = 1
    model.state["op_bias"].update(have=-9.0, exact=2.0)
    raw = model.predict_ir(source, dependency_guard=False)
    guarded = model.predict_ir(source)
    assert len(raw["ops"]) == 1 and len(guarded["ops"]) == 2
    assert "have proof" not in ae.decode_lean_ir(raw)
    assert "have proof" in ae.decode_lean_ir(guarded)
    assert guarded["dependency_guard"]["proposed_indices"] == [1]
    assert not guarded["dependency_guard"]["teacher_used"]
    # A proposed length cap is not allowed to sever the proof's prerequisites.
    bounded = model.predict_ir(source, max_ops=1)
    assert len(bounded["ops"]) == 2
