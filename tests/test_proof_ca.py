from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from jevops.proof_ca import (
    ActionProposal,
    ActionType,
    Atom,
    ContextIdentity,
    DeterministicPolicy,
    EvidenceKind,
    EvidenceStatus,
    JevPolicyAdapter,
    PolicyAnswer,
    ProofGraphCA,
    ResourceLedger,
    Rule,
    RunStatus,
    ValidationError,
    VerificationReceipt,
    VerificationStatus,
    canonical_json,
    sha256_digest,
)


def atoms(*names: str) -> list[Atom]:
    return [Atom(name) for name in names]


def diamond(*, policy=None, operation_budget=None, seed=None, extra: bool = False) -> ProofGraphCA:
    a, b, c, goal = atoms("A", "B", "C", "Goal")
    declared = [a, b, c, goal]
    rules = [
        Rule("r_ab", (a,), b),
        Rule("r_ac", (a,), c),
        Rule("r_goal", (b, c), goal),
    ]
    if extra:
        x, y = atoms("X", "Y")
        declared.extend([x, y])
        rules.append(Rule("r_disconnected", (x,), y))
    return ProofGraphCA(
        atoms=declared,
        rules=rules,
        assumptions=[a],
        targets=[goal],
        policy=policy,
        operation_budget=operation_budget,
        schedule_seed=seed,
    )


def test_ground_horn_conjunction_diamond_and_proof_carrying_trace() -> None:
    runtime = diamond(seed=3)
    report = runtime.run()

    assert report["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert report["accepted_facts"] == ["A", "B", "C", "Goal"]
    derivation = runtime.accepted_derivations("Goal")[0]
    assert derivation["kind"] == EvidenceKind.RULE_DERIVATION.value
    assert derivation["rule_id"] == "r_goal"
    assert derivation["premise_atoms"] == ["B", "C"]
    assert len(derivation["supporting_evidence"]) == 2
    assert report["metrics"]["edges_traversed"] > 0


def test_alternative_derivations_are_not_votes_and_duplicate_delivery_is_idempotent() -> None:
    a, b = atoms("A", "B")
    runtime = ProofGraphCA(
        atoms=[a, b],
        rules=[Rule("r1", (a,), b), Rule("r2", (a,), b)],
        assumptions=[a],
        targets=[b],
    )
    report = runtime.run()
    assert report["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert len(runtime.evidence_for(b)) == 2
    assert all(row.kind == EvidenceKind.RULE_DERIVATION for row in runtime.evidence_for(b))

    enqueued = [row for row in runtime.event_log if row.get("type") == "message_enqueued"]
    assert enqueued
    duplicate = runtime.deliver_message(enqueued[0]["payload"])
    assert duplicate["duplicate"] is True
    assert runtime.metrics.duplicate_messages >= 1


def test_conjunction_requires_all_premises_and_cycles_need_a_seed() -> None:
    a, b, c, goal = atoms("A", "B", "C", "Goal")
    incomplete = ProofGraphCA(
        atoms=[a, b, c, goal],
        rules=[Rule("r_goal", (a, b), goal)],
        assumptions=[a],
        targets=[goal],
    )
    assert incomplete.run()["status"] == RunStatus.QUIESCENT_INCOMPLETE.value
    assert "Goal" not in incomplete.accepted_facts

    cycle = ProofGraphCA(
        atoms=[a, b, c, goal],
        rules=[Rule("r_bc", (b,), c), Rule("r_cb", (c,), b)],
        assumptions=[a],
        targets=[c],
    )
    result = cycle.run()
    assert result["status"] == RunStatus.QUIESCENT_INCOMPLETE.value
    assert result["metrics"]["cells_visited"] == 0

    zero = ProofGraphCA(
        atoms=[c],
        rules=[Rule("r_zero", (), c)],
        assumptions=[],
        targets=[c],
    )
    assert zero.run()["status"] == RunStatus.VERIFIED_COMPLETE.value


def test_generated_finite_ground_chain_and_explicit_target_obligation() -> None:
    nodes = [Atom("node", (str(index),)) for index in range(12)]
    rules = [Rule(f"step_{index}", (nodes[index],), nodes[index + 1]) for index in range(11)]
    runtime = ProofGraphCA(
        atoms=nodes,
        predicates={"node": 1},
        rules=rules,
        assumptions=[nodes[0]],
        targets=[nodes[-1]],
        schedule_seed=4,
    )
    report = runtime.run(fair_period=2)
    target_cell = runtime.cells[runtime.fact_cell_id(nodes[-1])]
    assert report["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert len(runtime.accepted_facts) == len(nodes)
    assert target_cell.symbolic.obligation == "prove:node(11)"
    assert target_cell.symbolic.target_identity == "target:node(11)"


def test_duplicate_assumption_and_unauthorized_dependency_are_rejected() -> None:
    a, b, c = atoms("A", "B", "C")
    with pytest.raises(ValidationError):
        ProofGraphCA(atoms=[a, b], rules=[], assumptions=[a, a])

    runtime = ProofGraphCA(atoms=[a, b, c], rules=[Rule("r", (a,), b)], assumptions=[a], targets=[b])
    snapshot = runtime._snapshot(runtime.rule_by_id["r"])
    unauthorized = ActionProposal.make(
        context_id=runtime.context.context_id,
        target_cell=snapshot.cell_id,
        action=ActionType.REQUEST_DEPENDENCY,
        payload={"rule_id": "r", "dependency_cell_id": runtime.fact_cell_id(c)},
        dependency_fingerprint=snapshot.dependency_fingerprint,
    )
    result = runtime.checked_apply(unauthorized)
    assert result["outcome"] == "DEPENDENCY_NOT_LOCAL"
    assert runtime.accepted_facts == {"A"}


def test_incorrect_policy_cannot_forge_a_conclusion_or_theorem_flag() -> None:
    a, b, c = atoms("A", "B", "C")
    runtime = ProofGraphCA(atoms=[a, b, c], rules=[Rule("r", (a,), b)], assumptions=[a], targets=[b])
    valid = runtime.make_rule_proposal("r")
    forged = ActionProposal.make(
        context_id=runtime.context.context_id,
        target_cell=valid.target_cell,
        action=ActionType.ATTEMPT_RULE,
        payload={
            "rule_id": "r",
            "conclusion": "C",
            "premises": ["A"],
            "premise_evidence": [valid.payload_dict()["premise_evidence"][0]],
            "theorem_ok": True,
        },
        dependency_fingerprint=valid.dependency_fingerprint,
    )
    result = runtime.checked_apply(forged)
    assert result["outcome"] == "AUTHORITY_FIELD_REJECTED"
    assert runtime.accepted_facts == {"A"}
    assert not runtime.evidence_for(c)


class AlwaysForge:
    def propose(self, snapshot, allowed_actions):
        return {
            "selected": "attempt_rule",
            "rule_id": snapshot.rule_id,
            "conclusion": "C",
            "premises": list(snapshot.mandatory_dependencies),
            "premise_evidence": ["forged"],
            "theorem_ok": True,
        }


def test_invalid_attempt_cannot_starve_fair_fallback() -> None:
    a, b, c = atoms("A", "B", "C")
    runtime = ProofGraphCA(
        atoms=[a, b, c],
        rules=[Rule("r", (a,), b)],
        assumptions=[a],
        targets=[b],
        policy=AlwaysForge(),
    )
    result = runtime.run(fair_period=2)
    assert result["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert result["accepted_facts"] == ["A", "B"]


class WrongEvidence:
    def propose(self, snapshot, allowed_actions):
        row = snapshot.enabled_rules[0]
        return {
            "selected": "attempt_rule",
            "rule_id": row.rule_id,
            "conclusion": row.conclusion,
            "premises": list(row.premise_atoms),
            "premise_evidence": ["forged"] * len(row.premise_atoms),
        }


def test_fair_fallback_also_overrides_structurally_shaped_forged_evidence() -> None:
    a, b = atoms("A", "B")
    runtime = ProofGraphCA(
        atoms=[a, b],
        rules=[Rule("r", (a,), b)],
        assumptions=[a],
        targets=[b],
        policy=WrongEvidence(),
    )
    assert runtime.run(fair_period=2)["status"] == RunStatus.VERIFIED_COMPLETE.value


class AlwaysDefer:
    def propose(self, snapshot, allowed_actions):
        return {"selected": "defer", "reason": "neural_rejection"}


def test_fair_fifo_service_eventually_overrides_a_starving_policy() -> None:
    runtime = diamond(policy=AlwaysDefer(), seed=11)
    report = runtime.run(fair_period=3)
    assert report["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert report["accepted_facts"] == ["A", "B", "C", "Goal"]
    assert report["metrics"]["policy_rejections"] == 0
    assert report["metrics"]["policy_calls"] >= 3


class AlwaysUpdatePolicy:
    def propose(self, snapshot, allowed_actions):
        return {"selected": "update_policy", "activation": 0.25, "uncertainty": 0.75}


def test_non_authoritative_policy_actions_cannot_remove_enabled_work() -> None:
    a, b = atoms("A", "B")
    runtime = ProofGraphCA(
        atoms=[a, b],
        rules=[Rule("r", (a,), b)],
        assumptions=[a],
        targets=[b],
        policy=AlwaysUpdatePolicy(),
    )
    report = runtime.run(fair_period=2)
    assert report["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert report["accepted_facts"] == ["A", "B"]


def test_fair_interleavings_have_same_accepted_fact_set() -> None:
    left = diamond(seed=1).run(fair_period=5)
    right = diamond(seed=99).run(fair_period=5)
    assert left["status"] == right["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert left["accepted_facts"] == right["accepted_facts"]


def test_locality_does_not_visit_disconnected_region() -> None:
    runtime = diamond(extra=True, seed=2)
    result = runtime.run()
    assert result["status"] == RunStatus.VERIFIED_COMPLETE.value
    assert "X" not in runtime.accepted_facts
    assert "Y" not in runtime.accepted_facts
    assert result["metrics"]["cells_visited"] == 3
    assert result["n_cells"] == 10


def test_bounded_observation_keeps_complete_mandatory_dependency_set() -> None:
    premises = atoms(*(f"P{i}" for i in range(10)))
    goal = Atom("Goal")
    runtime = ProofGraphCA(
        atoms=[*premises, goal],
        rules=[Rule("wide", tuple(premises), goal)],
        assumptions=premises,
        targets=[goal],
        neighbor_limit=2,
    )
    snapshot = runtime._snapshot(runtime.rule_by_id["wide"])
    assert len(snapshot.mandatory_dependencies) == 10
    assert len(snapshot.neighbor_summaries) <= 2
    assert snapshot.full_neighbor_count >= 10


def test_invalid_probabilities_and_choices_are_rejected_without_symbolic_change() -> None:
    with pytest.raises(Exception):
        PolicyAnswer.from_mapping({"selected": "attempt_rule", "confidence": float("nan")}, allowed=["attempt_rule"])
    with pytest.raises(Exception):
        PolicyAnswer.from_mapping({"selected": "not_allowed"}, allowed=["attempt_rule"])

    a, b = atoms("A", "B")
    runtime = ProofGraphCA(atoms=[a, b], rules=[Rule("r", (a,), b)], assumptions=[a], targets=[b])
    bad = JevPolicyAdapter(lambda _snapshot, _allowed: {"selected": "unsupported"})
    with pytest.raises(Exception):
        bad.propose(runtime._snapshot(runtime.rule_by_id["r"]), tuple(action.value for action in ActionType))
    assert runtime.accepted_facts == {"A"}


def test_zero_budget_is_exhausted_and_not_defaulted() -> None:
    runtime = diamond(operation_budget=0)
    result = runtime.run()
    assert result["status"] == RunStatus.BUDGET_EXHAUSTED.value
    assert result["resources"]["remaining"] == 0
    assert runtime.accepted_facts == {"A"}
    ledger = ResourceLedger(operation_limit=0)
    assert ledger.reserve("one")["exhausted"] is True
    assert ledger.consumed == 0

    exact = diamond(operation_budget=3)
    assert exact.run()["status"] == RunStatus.VERIFIED_COMPLETE.value
    short = diamond(operation_budget=2)
    short_result = short.run()
    assert short_result["status"] == RunStatus.BUDGET_EXHAUSTED.value
    assert "Goal" not in short.accepted_facts

    spent = diamond(operation_budget=1)
    spent.run(max_steps=1)
    child = spent.new_epoch(ContextIdentity.create(facts_revision="next", rules_revision="same"))
    assert child.resources.operation_limit == 0
    assert child.run()["status"] == RunStatus.BUDGET_EXHAUSTED.value


def test_context_identity_is_strict_and_changed_epoch_rejects_stale_proposals() -> None:
    a, b = atoms("A", "B")
    runtime = ProofGraphCA(atoms=[a, b], rules=[Rule("r", (a,), b)], assumptions=[a], targets=[b])
    proposal = runtime.make_rule_proposal("r")
    runtime.checked_apply(proposal)
    changed = ContextIdentity.create(
        facts_revision="changed-facts",
        rules_revision=runtime.context.rules_revision,
    )
    child = runtime.new_epoch(changed)
    assert child.historical_evidence
    stale = child.checked_apply(proposal)
    assert stale["outcome"] == "STALE_CONTEXT"
    assert "B" not in child.accepted_facts

    with pytest.raises(Exception):
        canonical_json({"bad": float("inf")})
    assert sha256_digest({"x": 1}).startswith("sha256:")


def test_unrelated_policy_update_does_not_invalidate_evidence() -> None:
    a, b = atoms("A", "B")
    runtime = ProofGraphCA(atoms=[a, b], rules=[Rule("r", (a,), b)], assumptions=[a], targets=[b])
    pending_rule = runtime.make_rule_proposal("r")
    cell = runtime.cells[runtime.fact_cell_id(a)]
    fingerprint = sha256_digest({"context_id": runtime.context.context_id, "cell_id": cell.cell_id, "version": cell.runtime.version})
    update = ActionProposal.make(
        context_id=runtime.context.context_id,
        target_cell=cell.cell_id,
        action=ActionType.UPDATE_POLICY,
        payload={"activation": 0.0, "uncertainty": 1.0},
        dependency_fingerprint=fingerprint,
    )
    assert runtime.checked_apply(update)["outcome"] == "POLICY_STATE_UPDATED"
    assert runtime.checked_apply(pending_rule)["outcome"] == "FACT_ACCEPTED"
    evidence_before = [row.evidence_id for row in runtime.evidence_for(b)]
    assert evidence_before
    assert [row.evidence_id for row in runtime.evidence_for(b)] == evidence_before


def test_checkpoint_recovery_recomputes_justified_facts_and_replay_is_idempotent() -> None:
    runtime = diamond(seed=5, operation_budget=20)
    runtime.run()
    before = set(runtime.accepted_facts)
    with TemporaryDirectory() as temp:
        path = Path(temp) / "checkpoint.json"
        runtime.save_checkpoint(path)
        restored = ProofGraphCA.from_checkpoint(path)
    assert restored.accepted_facts == before
    assert restored.report()["status"] == RunStatus.VERIFIED_COMPLETE.value
    replay = restored.replay(restored.event_log + restored.event_log)
    assert replay["duplicates"] > 0
    assert restored.accepted_facts == before
    json.dumps(restored.checkpoint(), allow_nan=False)


class MockVerifier:
    def __init__(self, status: VerificationStatus = VerificationStatus.VERIFIED) -> None:
        self.status = status
        self.calls = 0

    def verify(self, request):
        self.calls += 1
        return VerificationReceipt(
            receipt_id=f"receipt-{self.calls}",
            context_id=request.context_id,
            target=request.target,
            status=self.status,
            verifier_id=request.verifier_id,
            verifier_version=request.verifier_version,
            candidate_artifact=request.candidate_artifact,
            source_dependencies=request.source_dependencies,
        )


class MismatchedVerifier:
    def __init__(self) -> None:
        self.calls = 0

    def verify(self, request):
        self.calls += 1
        return VerificationReceipt(
            receipt_id="wrong-target",
            context_id=request.context_id,
            target="Other",
            status=VerificationStatus.VERIFIED,
            verifier_id=request.verifier_id,
            verifier_version=request.verifier_version,
        )


def test_external_verifier_boundary_and_context_keyed_cache() -> None:
    checked = Atom("Checked")
    verifier = MockVerifier()
    context = ContextIdentity.create(
        facts_revision="facts",
        rules_revision="rules",
        target="Checked",
        candidate_artifact="artifact-1",
        source_dependencies=["source.py"],
        verifier_id="mock-verifier",
        verifier_version="1",
        verifier_options={"axioms": "none"},
        axiom_policy="none",
    )
    runtime = ProofGraphCA(
        atoms=[checked],
        rules=[],
        assumptions=[],
        targets=[checked],
        context=context,
        verifier=verifier,
    )
    first = runtime.checked_apply(runtime.make_external_proposal(target=checked))
    assert first["outcome"] == "EXTERNAL_VERIFIED"
    second = runtime.checked_apply(runtime.make_external_proposal(target=checked))
    assert second["outcome"] == "EXTERNAL_CACHE_HIT"
    assert verifier.calls == 1
    assert runtime.report()["status"] == RunStatus.VERIFIED_COMPLETE.value


def test_restored_cache_is_checked_before_reuse_and_can_run_without_verifier() -> None:
    checked = Atom("Checked")
    context = ContextIdentity.create(
        facts_revision="facts",
        rules_revision="rules",
        target="Checked",
        candidate_artifact="artifact-1",
        verifier_id="mock-verifier",
        verifier_version="1",
    )
    verifier = MockVerifier()
    runtime = ProofGraphCA(atoms=[checked], rules=[], assumptions=[], targets=[checked], context=context, verifier=verifier)
    assert runtime.checked_apply(runtime.make_external_proposal(target=checked))["outcome"] == "EXTERNAL_VERIFIED"
    restored = ProofGraphCA.from_checkpoint(runtime.checkpoint())
    # Current evidence and cache are sufficient; no live adapter is needed
    # for an applicable cache hit, and it is still not a new verifier event.
    cached = restored.checked_apply(restored.make_external_proposal(target=checked))
    assert cached["outcome"] == "EXTERNAL_CACHE_HIT"
    assert cached["verification_event"] is False

    # A tampered cached receipt is rejected and removed rather than trusted.
    tampered = ProofGraphCA.from_checkpoint(runtime.checkpoint(), verifier=MockVerifier())
    cache_key = next(iter(tampered.verification_cache))
    tampered.verification_cache[cache_key]["status"] = "counterexample"
    retried = tampered.checked_apply(tampered.make_external_proposal(target=checked))
    assert retried["outcome"] == "EXTERNAL_VERIFIED"
    assert tampered.verifier.calls == 1


def test_missing_and_transient_verifier_outcomes_are_not_proofs() -> None:
    checked = Atom("Checked")
    context = ContextIdentity.create(
        facts_revision="facts",
        rules_revision="rules",
        target="Checked",
        verifier_id="mock",
        verifier_version="1",
    )
    missing = ProofGraphCA(atoms=[checked], rules=[], assumptions=[], targets=[checked], context=context)
    assert missing.checked_apply(missing.make_external_proposal(target=checked))["outcome"] == "VERIFIER_UNAVAILABLE"
    transient = MockVerifier(VerificationStatus.TRANSIENT_FAILURE)
    runtime = ProofGraphCA(atoms=[checked], rules=[], assumptions=[], targets=[checked], context=context, verifier=transient)
    result = runtime.checked_apply(runtime.make_external_proposal(target=checked))
    assert result["outcome"] == "EXTERNAL_TRANSIENT_FAILURE"
    assert runtime.report()["status"] == RunStatus.QUIESCENT_INCOMPLETE.value
    assert not runtime.evidence_for(checked)
    errored = MockVerifier(VerificationStatus.ERROR)
    failed_runtime = ProofGraphCA(atoms=[checked], rules=[], assumptions=[], targets=[checked], context=context, verifier=errored)
    assert failed_runtime.checked_apply(failed_runtime.make_external_proposal(target=checked))["outcome"] == "EXTERNAL_ERROR"
    assert failed_runtime.report()["status"] == RunStatus.ERROR.value


def test_mismatched_external_receipt_is_not_authoritative() -> None:
    checked = Atom("Checked")
    context = ContextIdentity.create(
        facts_revision="facts",
        rules_revision="rules",
        target="Checked",
        verifier_id="mock",
        verifier_version="1",
    )
    verifier = MismatchedVerifier()
    runtime = ProofGraphCA(atoms=[checked], rules=[], assumptions=[], targets=[checked], context=context, verifier=verifier)
    result = runtime.checked_apply(runtime.make_external_proposal(target=checked))
    assert result["outcome"] == "RECEIPT_MISMATCH"
    assert runtime.accepted_facts == set()


def test_reverse_message_interleaving_preserves_the_accepted_fact_set() -> None:
    def run_with_order(reverse: bool) -> set[str]:
        runtime = diamond(seed=0)
        runtime.checked_apply(runtime.make_rule_proposal("r_ab"))
        runtime.checked_apply(runtime.make_rule_proposal("r_ac"))
        runtime.ready_queue.clear()
        runtime.queued_rules.clear()
        runtime.deliver_pending(reverse=reverse)
        runtime.run(fair_period=1)
        return set(runtime.accepted_facts)

    assert run_with_order(False) == run_with_order(True) == {"A", "B", "C", "Goal"}


def test_malformed_rules_and_undeclared_atoms_fail_closed() -> None:
    with pytest.raises(ValidationError):
        ProofGraphCA(atoms=[Atom("A")], rules=[Rule("r", (Atom("B"),), Atom("A"))], assumptions=[])
    with pytest.raises(ValidationError):
        ProofGraphCA(atoms=[Atom("p", ("x",))], rules=[], assumptions=[], predicates={"p": 0})


def test_existing_nca_and_tool_adapters_run_the_strict_runtime() -> None:
    from jevops import nca, tools

    runtime = diamond(seed=4)
    via_nca = nca.dispatch_tool("proof_ca_run", runtime=runtime, fair_period=1)
    assert via_nca["status"] == RunStatus.VERIFIED_COMPLETE.value
    direct = nca.run_proof_ca(diamond(seed=4), fair_period=1, max_steps=32)
    assert direct["status"] == RunStatus.VERIFIED_COMPLETE.value

    second = diamond(seed=4)
    via_tool = tools.run_tool("proof_ca_run", observations={"runtime": second, "fair_period": 1})
    assert via_tool["status"] == RunStatus.VERIFIED_COMPLETE.value


def test_legacy_nca_overlays_replay_and_neighborhood_are_idempotent() -> None:
    from jevops import nca

    memory = {
        "successes": [{"kind": "port_demo", "to_tokens": 1}],
        "failures": [],
        "nca": {
            "grid": {
                "ptr://skill/port_demo": {"kind": "skill", "energy": 0.5},
                "ptr://skill/other": {"kind": "skill", "energy": 0.5},
            },
            "board_edges": [["port_demo", "port_other"]],
        },
    }
    nca.feed_memory(memory, heal=False)
    nca.feed_memory(memory, heal=False)
    assert memory["nca"]["grid"]["ptr://skill/port_demo"]["wins"] == 1
    assert nca.neighborhood("port_demo", memory) == ["ptr://skill/port_other"]

    nca.journal_event(memory, event="test", ptr="port_demo", op="skill", energy_delta=0.1)
    first = nca.replay_journal(memory)
    energy = memory["nca"]["grid"]["ptr://skill/port_demo"]["energy"]
    second = nca.replay_journal(memory)
    assert first["n_replayed"] >= 1
    assert second["n_replayed"] == 0
    assert second["n_duplicate"] >= 1
    assert memory["nca"]["grid"]["ptr://skill/port_demo"]["energy"] == energy

    zero_parent = {"nca": {"grid": {"ptr://skill/parent": {"kind": "skill", "energy": 0.0}}}}
    nca.upsert_from_event(zero_parent, ptr="child", kind="skill", energy=1.0, parent_ptr="parent")
    assert zero_parent["nca"]["grid"]["ptr://skill/parent"]["energy"] < 0.25


def test_legacy_zero_budget_energy_and_arc_byte_limit(monkeypatch, tmp_path) -> None:
    from jevops import kernel, nca

    memory = {"nca": {"grid": {nca.BUDGET_PTR: {"energy": 0.0, "visited": True}}}}
    budget = nca.charge_budget(memory, jev_calls=0)
    assert budget["energy"] == 0.0

    cache_memory = {"nca": {"kernel": {"l1_max_bytes": 10, "l1_cap": 4}}}
    kernel.cache_put(cache_memory, {"large": "payload"}, kind="test")
    assert cache_memory["nca"]["kernel"]["l1"] == {}

    monkeypatch.setenv("JEVOPS_CAS_DIR", str(tmp_path))
    first = kernel.flight_begin({}, "same-work")
    second = kernel.flight_begin({}, "same-work")
    assert first["ok"] is True
    assert second["ok"] is False
    assert second["reason"] == "in_flight"
    kernel.flight_end({}, "same-work")
