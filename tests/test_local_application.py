"""Search-to-term controls; fixtures are not native verification evidence."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
import os
from pathlib import Path

import pytest

from jevops import arena_local as local, arena_lean as native, arena_providers as providers
from jevops.arena import VerificationRequest, content_hash, reference_tokens
from jevops.lean import VersionPin
from jevops.premise_search import Premise, PremiseIndex, PremiseScope
from tests.test_arena_local import guard, stage, PIN, OTHER, RECORD, SOURCE
from tests.test_local_premise_replay import capture_fixture, inventory, rehash, BLOCK

CONTROL_PATH = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/run_local_application_control.py"
CONTROL_SPEC = importlib.util.spec_from_file_location("local_application_control", CONTROL_PATH)
control = importlib.util.module_from_spec(CONTROL_SPEC)
CONTROL_SPEC.loader.exec_module(control)


def test_control_is_plan_only_and_reserves_before_even_resolving_compilers(monkeypatch):
    monkeypatch.setattr(control, "pinned_lean", lambda *a: pytest.fail("unexpected native setup"))
    report = control.run(["v4.26.0", "v4.29.1"])
    assert report["status"] == "PLANNED" and report["process_ceiling"] == 8
    assert report["native_processes"] == 0 and report["official_score"] is None
    for budget in (0, 7):
        with pytest.raises(ValueError, match="ceiling"):
            control.run(["v4.26.0", "v4.29.1"], execute=True, max_processes=budget)


@pytest.mark.parametrize("tags,budget", [([], 0), (["v4.26.0"] * 2, 8), (["v4.26.0"], True),
                                       (["v4.26.0"], -1), (["v4.26.0"], 17)])
def test_bad_control_limits(tags, budget):
    with pytest.raises(ValueError): control.run(tags, max_processes=budget)


def application_stage(binding, payload):
    if payload["mode"] != "application":
        return stage(binding, payload)
    value = stage(binding, {**payload, "mode": "replay"})
    value["request_sha256"] = payload["request_sha256"]
    search = value["report"]
    extracted = "exact True.intro"
    value["report"] = {"schema": "jevops-local-application/v1",
        "lean_version": search["lean_version"], "lean_githash": search["lean_githash"],
        "search": search, "extracted_candidate": extracted,
        "roundtrip": {**deepcopy(search), "candidate": extracted}}
    return value


def runtime(guard, processes=2, runner=application_stage):
    return local.ArenaLocalRuntime(guard, RECORD, max_processes=processes, runner=runner)


def plan(**limits):
    from tests.test_local_premise_replay import RECORD as record
    return providers.plan_local_applications(record, capture_fixture(), *inventory(), **limits)


def test_planning_is_deterministic_untrusted_and_does_not_filter_long_search():
    result = plan(max_applications=1)
    assert result == plan(max_applications=1)
    assert result["applications"] == [{"event_id": 0, "premise": "True.intro"}]
    assert not result["truncated"]
    assert result["drafts"] == [] and result["native_verifier_calls"] == 0
    assert not result["proof_admitted"] and not result["proof_verified"]
    assert result["request"]["request_sha256"] != plan(span_order="smallest-v1")["request"]["request_sha256"]


@pytest.mark.parametrize("field", ["cap", "max_events", "max_query_nodes", "max_applications"])
def test_zero_plans_never_query(field, monkeypatch):
    monkeypatch.setattr(PremiseIndex, "rank", lambda *a, **kw: pytest.fail("zero budget queried"))
    assert plan(**{field: 0})["status"] == "BUDGET_EXHAUSTED"


@pytest.mark.parametrize("value", [-1, True, 65, 1.0])
def test_invalid_application_limits(value):
    with pytest.raises(ValueError): plan(max_applications=value)


def test_headroom_selection_and_duplicate_span_exclusion():
    from tests.test_local_premise_replay import RECORD as record
    capture = capture_fixture()
    event = capture["trace"]["events"][0]
    smaller = {**deepcopy(event), "id": "1", "start": str(SOURCE.encode().rindex(b"exact True.intro")),
               "end": str(len(SOURCE.encode()) - 1)}
    capture["trace"]["events"].extend([smaller, {**deepcopy(event), "id": "2"}])
    rehash(capture)
    runs = [providers.plan_local_applications(record, capture, *inventory(), max_events=1,
            max_applications=1, span_order=order) for order in ("headroom-v1", "smallest-v1")]
    assert [r["applications"][0]["event_id"] for r in runs] == [0, 1]
    assert all(r["truncated"] for r in runs)
    with pytest.raises(ValueError): plan(span_order="random")


def test_exclusions_and_scan_overflow_still_apply():
    from tests.test_local_premise_replay import RECORD as record
    index, scope = inventory()
    result = providers.plan_local_applications(record, capture_fixture(), index,
        replace(scope, excluded_names=("True.intro",)))
    assert not result["applications"]
    index, scope = inventory((Premise("A.proof", "True", "fixture"), Premise("B.proof", "True", "fixture")))
    result = providers.plan_local_applications(record, capture_fixture(), index, scope, max_scan=1)
    assert not result["applications"] and result["truncated"]


def test_fixture_roundtrip_and_exact_budget(guard):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_application(PIN, SOURCE, capture, 0, "True.intro")
    assert result["ok"] and result["closing_reproduced"]
    assert result["extracted_candidate"] == "exact True.intro"
    assert result["application_attempts"] == result["roundtrip_attempts"] == 1
    assert result["evidence_mode"] == "fixture"
    assert not result["whole_source_checked"] and not result["proof_admitted"]
    assert rt.discover_application(PIN, SOURCE, capture, 0, "True.intro")["status"] == "BUDGET_EXHAUSTED"
    assert rt.reserved == rt.attempts == 2 and guard.processes == 0


@pytest.mark.parametrize("damage", ["text", "roundtrip", "event", "flag", "missing", "schema", "axiom"])
def test_forged_or_mismatched_extraction_rejected(guard, damage):
    def corrupt(binding, payload):
        value = application_stage(binding, payload)
        if payload["mode"] == "application":
            report = value["report"]
            if damage == "text": report["extracted_candidate"] = "exact False.elim missing"
            elif damage == "roundtrip": report["roundtrip"]["environment"] = "b" * 64
            elif damage == "event": report["roundtrip"]["event"]["start"] = "0"
            elif damage == "flag": report["roundtrip"]["proof_admitted"] = True
            elif damage == "missing": report["roundtrip"] = None
            elif damage == "schema": report["schema"] = "foreign"
            else: report["search"]["proposed"]["axioms"] = ["sorryAx"]
        return value
    rt = runtime(guard, runner=corrupt)
    capture = rt.capture(PIN)["capture"]
    result = rt.discover_application(PIN, SOURCE, capture, 0, "True.intro")
    assert result["status"] == "ERROR" and not result["closing_reproduced"]
    assert result["extracted_candidate"] is None


@pytest.mark.parametrize("damage", ["source", "origin", "pin", "premise", "event"])
def test_stale_context_or_injected_code_rejects_before_launch(guard, damage):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    pin, source, event, premise = PIN, SOURCE, 0, "True.intro"
    if damage == "source": source += "\n"
    elif damage == "origin": capture["origin"]["target"] = "other"
    elif damage == "pin": pin = OTHER
    elif damage == "premise": premise = "True.intro <;> sorry"
    else: event = True
    with pytest.raises(ValueError): rt.discover_application(pin, source, capture, event, premise)
    assert rt.attempts == 1


def test_batch_fixture_drafts_are_not_verification_and_zero_runtime_stops(guard):
    rt = runtime(guard)
    capture = rt.capture(PIN)["capture"]
    env = rt.context.context_id
    index = PremiseIndex((Premise("True.intro", "True", "fixture"),), environment_sha256=env)
    scope = PremiseScope(content_hash(RECORD), env, ("True.intro",))
    result = rt.discover_batch(PIN, capture, index, scope, max_applications=1)
    assert result["status"] == "FIXTURE_DRAFTS_ONLY" and len(result["drafts"]) == 1
    assert result["native_verifier_calls"] == 0 and result["attempted_processes"] == 1
    assert result["drafts"][0]["source"] == SOURCE.replace(BLOCK, "exact True.intro")
    assert not result["proof_verified"] and not result["proof_admitted"]
    assert rt.discover_batch(PIN, capture, index, scope)["status"] == "BUDGET_EXHAUSTED"


@pytest.mark.parametrize("failure", ["open", "roundtrip", "timeout", "not_shorter", "duplicate"])
def test_batch_failed_discovery_never_emits_a_draft(guard, failure):
    def outcome(binding, payload):
        if payload["mode"] == "application" and failure == "timeout":
            raise TimeoutError("fixture infrastructure failure")
        value = application_stage(binding, payload)
        if payload["mode"] == "application":
            report = value["report"]
            if failure in {"open", "roundtrip"}:
                report["search" if failure == "open" else "roundtrip"]["proposed"] = {
                    "status": "open_goals", "closed_goals_checked": "0", "remaining_goals": "1", "axioms": []}
                if failure == "open":
                    report.update(extracted_candidate=None, roundtrip=None)
            else:
                text = ("exact True.intro" + " " * 2) if failure == "duplicate" else "exact " + "id (" * 30 + "True.intro" + ")" * 30
                # The duplicate case is a second plan event/nominee producing
                # the same final source, not a second charge for one cached run.
                report["extracted_candidate"] = text
                report["roundtrip"]["candidate"] = text
        return value
    rt = runtime(guard, processes=3, runner=outcome)
    capture = rt.capture(PIN)["capture"]
    env = rt.context.context_id
    index = PremiseIndex(tuple(Premise(n, "True", "fixture") for n in ("True.intro", "Other.proof")), environment_sha256=env)
    scope = PremiseScope(content_hash(RECORD), env, tuple(index.entries))
    result = rt.discover_batch(PIN, capture, index, scope, max_applications=2)
    if failure == "duplicate":
        assert len(result["drafts"]) == 1
        assert result["attempts"][1]["status"] == "DUPLICATE"
        assert rt.attempts == 3
    else:
        assert not result["drafts"]
    if failure == "timeout":
        assert result["status"] == "ERROR" and rt.reserved == 2
    elif failure == "not_shorter":
        assert result["attempts"][0]["status"] == "NOT_SHORTER"


@pytest.mark.no_seal(reason="explicit installed Lean application/materialization; no models/downloads")
@pytest.mark.parametrize("case", ["arguments", "conjunction", "missing_premise", "wrong_conclusion", "forbidden_axiom", "typeclass", "defeq", "shadowing"])
def test_native_application_materialization_and_full_source(tmp_path, case):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit opt-in; installed toolchains only")
    tag = os.environ.get("JEVOPS_APPLICATION_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "application-materialization-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix = "theorem library_step {p : Prop} (h : p) : p ∨ True := Or.inl h\n"
    statement = "theorem sample (p : Prop)" + ("" if case == "missing_premise" else " (h : p)") + " : p ∨ True"
    answer = "Or.inr (id True.intro)" if case == "missing_premise" else "Or.inl (id h)"
    if case == "wrong_conclusion": prefix = "theorem library_step : True := True.intro\n"
    if case == "forbidden_axiom": prefix = "axiom library_step {p : Prop} : p ∨ True\n"
    if case == "typeclass":
        prefix = "theorem library_step {α : Type} [Inhabited α] : Nonempty α := ⟨default⟩\n"
        statement = "theorem sample (α : Type) [Inhabited α] : Nonempty α"
        answer = "Nonempty.intro (id (id (default : α)))"
    if case == "defeq":
        prefix = "abbrev Alias := True\ntheorem library_step : True := True.intro\n"
        statement, answer = "theorem sample : Alias", "id (id (id True.intro))"
    if case == "conjunction":
        prefix = "theorem library_step {p q : Prop} (hp : p) (hq : q) : p ∧ q := And.intro hp hq\n"
        statement = "theorem sample (p q : Prop) (hp : p) (hq : q) : p ∧ q"
        answer = "And.intro (id hp) (id hq)"
    if case == "shadowing":
        statement = "theorem sample (p : Prop) (library_step : p) : p ∨ True"
        answer = "Or.inl (id (id library_step))"
    source = statement + " := by\n  exact " + answer + "\n"
    record = {"name": "Suite.sample", "statement": statement, "src": source,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix + "namespace Suite\n", project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(verifier, record, max_processes=2)
    observed = rt.capture(pin)
    assert observed["ok"], observed
    capture = observed["capture"]
    event = next(e for e in capture["trace"]["events"]
                 if source.encode()[int(e["start"]):int(e["end"])].startswith(b"exact "))
    result = rt.discover_application(pin, source, capture, int(event["id"]), "library_step")
    assert result["ok"], result
    positive = case in {"arguments", "typeclass", "defeq", "conjunction", "shadowing"}
    assert result["closing_reproduced"] == positive, result
    assert rt.reserved == rt.attempts == 2
    assert verifier(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    if positive:
        from jevops.proof_replay import replace_event
        candidate = result["extracted_candidate"]
        draft = replace_event(source, event, candidate)
        assert verifier(VerificationRequest(rt.context, draft, pin)).outcome.value == "VERIFIED"
        assert reference_tokens(draft, statement) < reference_tokens(source, statement)
        if case == "arguments":
            search_source = replace_event(source, event, result["native"]["search"]["candidate"])
            assert reference_tokens(search_source, statement) >= reference_tokens(source, statement)
    else:
        assert result["extracted_candidate"] is None and not result["roundtrip_attempts"]
    assert not result["proof_admitted"] and not result["whole_source_checked"]


@pytest.mark.no_seal(reason="native failed application followed by independent successful application")
def test_native_failed_application_does_not_poison_next_attempt(tmp_path):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit opt-in; installed toolchains only")
    tag = os.environ.get("JEVOPS_APPLICATION_LEAN_TAG", "v4.26.0")
    pin = VersionPin(tag, "application-rollback-control")
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    prefix = ("theorem A_bad : True := True.intro\n"
              "theorem B_good {p : Prop} (h : p) : p ∨ True := Or.inl h\nnamespace Suite\n")
    record = {"name": "Suite.sample", "statement": control.STATEMENT, "src": control.SOURCE,
              "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix, project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=2, timeout=60)
    rt = local.ArenaLocalRuntime(verifier, record, max_processes=3)
    observed = rt.capture(pin)
    assert observed["ok"], observed
    env = rt.context.context_id
    # Deliberately dishonest type-text hints: only native types can authorize closure.
    index = PremiseIndex(tuple(Premise(n, "Or True", "fixture-nomination") for n in ("A_bad", "B_good")),
                         environment_sha256=env)
    scope = PremiseScope(content_hash(record), env, tuple(index.entries))
    batch = rt.discover_batch(pin, observed["capture"], index, scope, max_events=1,
                             max_applications=2, cap=1, top_k=2)
    assert [a["status"] for a in batch["attempts"]] == ["NO_CHECKED_CLOSURE", "DRAFT"], batch
    assert batch["application_attempts"] == 2 and batch["roundtrip_attempts"] == 1
    assert rt.attempts == rt.reserved == 3 and batch["status"] == "DRAFTS_ONLY"
    for source in (control.SOURCE, batch["drafts"][0]["source"]):
        assert verifier(VerificationRequest(rt.context, source, pin)).outcome.value == "VERIFIED"
    assert not batch["proof_admitted"] and not batch["whole_source_checked"]
