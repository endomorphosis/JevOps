"""No cached passes: injected advisors nominate but cannot grant authority."""
import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from jevops import arena_providers as providers
from jevops.arena import content_hash, reference_tokens
from jevops.arena_pareto import _draft, selection_plan
from jevops.arena_trial import Candidate
from jevops.premise_search import Premise, PremiseIndex, PremiseScope

STATEMENT = "theorem provider_example : True"
SOURCE = STATEMENT + " := by\n  have one : True := True.intro\n  have two : True := one\n  exact two"
RECORD = {"name": "provider_example", "statement": STATEMENT, "src": SOURCE,
          "version_info": [{"v4.26.0": "fixture"}]}
ENV = content_hash("fixture environment, not verified")


@pytest.fixture
def inventory():
    index = PremiseIndex((Premise("True.intro", "True", "stdlib@v4.26.0"),), environment_sha256=ENV)
    scope = PremiseScope(content_hash(RECORD), ENV, ("True.intro",))
    return index, scope


def response(inventory, rows, **request_kwargs):
    request, _ = providers.proposal_request(RECORD, *inventory, **request_kwargs)
    return json.dumps({"request_sha256": request["request_sha256"], "proposals": rows})


GOOD = {"kind": "premise", "name": "True.intro", "method": "term"}


def test_default_providers_emit_only_unverified_four_field_drafts(inventory):
    batch = providers.propose_batch(RECORD, *inventory)
    assert batch == providers.propose_batch(RECORD, *inventory)
    assert len(batch["drafts"]) == 3
    assert all(set(d) == {"name", "label", "source", "provenance"} for d in batch["drafts"])
    assert batch["drafts"][0]["source"] == STATEMENT + " := _root_.True.intro"
    assert all(reference_tokens(d["source"], STATEMENT) < batch["base_tokens"] for d in batch["drafts"])
    assert batch["native_verifier_calls"] == batch["external_calls_attempted"] == 0
    assert batch["proof_verified"] is batch["training_enabled"] is batch["promoted"] is False
    assert batch["official_score"] is None


def test_small_budget_covers_distinct_premises_before_method_variants():
    entries = (Premise("Alpha.proof", "True", "library"), Premise("Beta.proof", "True", "library"))
    index = PremiseIndex(entries, environment_sha256=ENV)
    scope = PremiseScope(content_hash(RECORD), ENV, tuple(p.name for p in entries))
    batch = providers.propose_batch(RECORD, index, scope, cap=2, proposal_limit=2,
                                    providers=(providers.PremiseProvider(),))
    assert len(batch["drafts"]) == 2
    outcomes = batch["attempts"][0]["outcomes"]
    assert [o["nomination"]["name"] for o in outcomes] == ["Alpha.proof", "Beta.proof"]
    assert all(o["nomination"]["method"] == "term" for o in outcomes)


@pytest.mark.parametrize("bad", [
    {**GOOD, "verified": True}, {**GOOD, "tokens": 0}, {**GOOD, "reward": 999},
    {**GOOD, "name": "provider_example"}, {**GOOD, "name": "Other.lemma"},
    {**GOOD, "method": "sorry"}, {"kind": "source", "source": "sorry"},
    {"kind": "path", "rules": ["exec"]}, {"kind": "path", "rules": ["port_exact_hyp"] * 4},
])
def test_bad_provider_response_is_atomic_and_baseline_fallback_runs(inventory, bad):
    adversary = providers.JsonProvider("bad", response(inventory, [GOOD, bad]))
    batch = providers.propose_batch(RECORD, *inventory, providers=(adversary, providers.PremiseProvider()))
    assert batch["attempts"][0]["status"] == "ERROR"
    assert batch["attempts"][0]["outcomes"] == []
    assert len(batch["drafts"]) == 3
    assert "premise-baseline" in batch["drafts"][0]["provenance"]


@pytest.mark.parametrize("raw", ['{"request_sha256":"a","request_sha256":"b","proposals":[]}',
                                '{"request_sha256":NaN,"proposals":[]}', "[]", "[" * 2000])
def test_duplicate_nonfinite_and_deep_json_fail_closed(inventory, raw):
    batch = providers.propose_batch(RECORD, *inventory, providers=(providers.JsonProvider("bad", raw),))
    assert batch["drafts"] == [] and batch["attempts"][0]["status"] == "ERROR"


def test_stale_seed_inventory_scope_and_request_are_not_replayed(inventory):
    old = providers.JsonProvider("old", response(inventory, [GOOD]))
    seed = Candidate("seed", STATEMENT + " := by exact True.intro", "unverified seed")
    batch = providers.propose_batch(RECORD, *inventory, seed=seed, providers=(old,))
    assert batch["attempts"][0]["status"] == "ERROR" and not batch["drafts"]
    index, scope = inventory
    with pytest.raises(ValueError, match="record"):
        providers.propose_batch({**RECORD, "src": SOURCE + "\n"}, index, scope)
    different = PremiseIndex((Premise("True.intro", "True", "new-origin"),), environment_sha256=ENV)
    assert providers.propose_batch(RECORD, different, scope, providers=(old,))["attempts"][0]["status"] == "ERROR"
    assert providers.propose_batch(RECORD, index, replace(scope, excluded_names=("True.intro",)),
                                   providers=(old,))["attempts"][0]["status"] == "ERROR"


@pytest.mark.parametrize("before,after", [
    ('by\n  have text := "a  b"\n  exact True.intro',
     'by\n  have text := "a b"\n  exact True.intro'),
    ('by\n  exact True.intro', 'by\n    exact True.intro'),
    ('by\n  have text := "e\u0301"\n  exact True.intro',
     'by\n  have text := "\u00e9"\n  exact True.intro'),
], ids=["string-whitespace", "layout", "unicode-normalization"])
def test_raw_seed_identity_cannot_be_replaced_by_text_normalization(inventory, before, after):
    # Retrieval normalization is not a safe cache identity for Lean source:
    # whitespace and Unicode can change literals, and layout controls parsing.
    # These are unverified inputs; this test asserts binding, not proof validity.
    first = Candidate("seed", STATEMENT + " := " + before, "unverified seed")
    second = Candidate("seed", STATEMENT + " := " + after, "unverified seed")
    old_request, _ = providers.proposal_request(RECORD, *inventory, seed=first)
    new_request, _ = providers.proposal_request(RECORD, *inventory, seed=second)
    assert old_request["base_source_sha256"] != new_request["base_source_sha256"]
    assert old_request["request_sha256"] != new_request["request_sha256"]
    old = providers.JsonProvider("old", response(inventory, [GOOD], seed=first))
    batch = providers.propose_batch(RECORD, *inventory, seed=second, providers=(old,))
    assert batch["attempts"][0]["status"] == "ERROR"
    assert batch["drafts"] == []
    assert batch["native_verifier_calls"] == 0


def test_global_cap_duplicate_drafts_and_no_provider_calls_at_zero(inventory, monkeypatch):
    a = providers.JsonProvider("a", response(inventory, [GOOD, GOOD]))
    b = providers.JsonProvider("b", response(inventory, [GOOD]))
    batch = providers.propose_batch(RECORD, *inventory, providers=(a, b))
    assert len(batch["drafts"]) == 1
    assert [x["status"] for x in batch["attempts"][0]["outcomes"]] == ["DRAFT", "DUPLICATE"]
    assert batch["attempts"][1]["outcomes"][0]["status"] == "DUPLICATE"
    monkeypatch.setattr(providers, "_generate", lambda *a: pytest.fail("zero cap must not call providers"))
    assert providers.propose_batch(RECORD, *inventory, cap=0)["attempts"] == []


def test_rewrite_nominations_use_existing_composition_path(inventory):
    statement = "theorem provider_example (h : True) : True"
    record = {**RECORD, "statement": statement, "src": statement + " := by exact h"}
    index, scope = inventory
    scope = replace(scope, record_sha256=content_hash(record))
    batch = providers.propose_batch(record, index, scope, providers=(providers.RuleProvider((("port_exact_hyp",),)),))
    assert len(batch["drafts"]) == 1 and batch["drafts"][0]["source"].endswith("assumption")


def test_request_and_response_caps_before_external_or_render_work(inventory, monkeypatch):
    large = {**RECORD, "src": STATEMENT + " := by\n" + "  skip\n" * 2000 + "  trivial"}
    index, scope = inventory
    monkeypatch.setattr(providers, "_generate", lambda *a: pytest.fail("oversized request must not call provider"))
    with pytest.raises(ValueError, match="request byte"):
        providers.propose_batch(large, index, replace(scope, record_sha256=content_hash(large)),
                                limits=providers.ProviderLimits(request_bytes=1024))


@pytest.mark.parametrize("value", [True, -1, 9, 1.5])
def test_bad_batch_cap_rejected(inventory, value):
    with pytest.raises(ValueError):
        providers.propose_batch(RECORD, *inventory, cap=value)


def test_unknown_and_duplicate_providers_rejected_before_execution(inventory):
    for sources in ((lambda *_: [],), (providers.PremiseProvider(),) * 2, (providers.PremiseProvider(),) * 9):
        with pytest.raises(ValueError):
            providers.propose_batch(RECORD, *inventory, providers=sources)


def command(code, *, name="command"):
    return providers.CommandProvider(name, (sys.executable, "-I", "-B", "-c", code))


@pytest.mark.no_seal(reason="fresh provider process and environment boundary")
def test_injected_command_uses_json_stdin_no_inherited_secret_and_no_authority(inventory, monkeypatch):
    monkeypatch.setenv("PRIVATE_PROVIDER_SECRET", "must-not-be-inherited")
    code = ("import json,sys,os; r=json.load(sys.stdin); assert 'PRIVATE_PROVIDER_SECRET' not in os.environ; "
            "print(json.dumps({'request_sha256':r['request_sha256'],'proposals':"
            "[{'kind':'premise','name':'True.intro','method':'term'}]}))")
    batch = providers.propose_batch(RECORD, *inventory, providers=(command(code),))
    assert len(batch["drafts"]) == 1 and batch["external_calls_attempted"] == 1
    assert batch["native_verifier_calls"] == 0 and not batch["proof_verified"]


@pytest.mark.no_seal(reason="real timeout, output bound and child cleanup")
@pytest.mark.parametrize("code,expected", [("import time; time.sleep(20)", "TIMEOUT"),
                                          ("print('x'*100000)", "ERROR"),
                                          ("raise RuntimeError('PRIVATE_SECRET')", "ERROR")])
def test_command_failure_is_bounded_redacted_and_falls_back(inventory, code, expected):
    start = time.monotonic()
    batch = providers.propose_batch(RECORD, *inventory,
        providers=(command(code), providers.PremiseProvider()),
        limits=providers.ProviderLimits(per_provider_seconds=1, total_seconds=5, response_bytes=1024))
    assert time.monotonic() - start < 5
    assert batch["attempts"][0]["status"] == expected
    assert "PRIVATE_SECRET" not in json.dumps(batch)
    assert len(batch["drafts"]) == 3


def test_total_deadline_stops_next_provider(inventory, monkeypatch):
    ticks = iter([0, 21])
    monkeypatch.setattr(providers.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(providers, "_generate", lambda *a: pytest.fail("deadline exceeded"))
    batch = providers.propose_batch(RECORD, *inventory)
    assert batch["attempts"][0]["status"] == "TOTAL_TIMEOUT" and not batch["drafts"]


def test_cli_outputs_import_into_existing_selector_and_never_overwrites(inventory, tmp_path, monkeypatch, capsys):
    index, scope = inventory
    corpus, premises, scopes = (tmp_path / n for n in ("corpus.jsonl", "premises.json", "scope.json"))
    corpus.write_text(json.dumps(RECORD) + "\n")
    premises.write_text(json.dumps({"schema": "jevops-premise-index/v1", "environment_sha256": ENV,
                                   "premises": [asdict(p) for p in index.entries.values()]}))
    scopes.write_text(json.dumps({"schema": "jevops-premise-scope/v1", **asdict(scope)}))
    out = tmp_path / "drafts"
    monkeypatch.setattr(sys, "argv", ["arena_providers", "--corpus", str(corpus), "--problem", RECORD["name"],
        "--premises", str(premises), "--scope", str(scopes), "--output-dir", str(out)])
    assert providers.main() == 0 and json.loads(capsys.readouterr().out)["status"] == "DRAFTS_ONLY"
    manifest = (out / "manifest.json").read_bytes()
    drafts = [_draft(out / f"provider-{i}.json", RECORD["name"]) for i in range(3)]
    plan = selection_plan(RECORD, drafts, selection_objective="strict-dual-v1")
    assert plan["required_request_budget"] > 0
    with pytest.raises(SystemExit) as exc:
        providers.main()
    assert exc.value.code == 2 and (out / "manifest.json").read_bytes() == manifest


@pytest.mark.no_seal(reason="fresh pinned Lean verification, never cache a pass")
@pytest.mark.parametrize("name,prefix,expected", [
    ("True.intro", "", "VERIFIED"),
    ("Nonexistent.proof", "", "REJECTED"),
    ("Bad.poison", "axiom forbidden : False\ntheorem Bad.poison : True := False.elim forbidden\n", "REJECTED"),
])
def test_native_gate_not_inventory_metadata_decides_proof_acceptance(tmp_path, name, prefix, expected):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no toolchain downloads")
    from jevops import arena_lean as native
    from jevops.arena import VerificationRequest
    from jevops.lean import VersionPin

    tag = "v4.26.0"
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    pin = VersionPin(tag, "local-provider-regression")
    record = {**RECORD, "version_info": [{tag: pin.git_commit}]}
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix, project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    context = verifier.context(record)
    index = PremiseIndex((Premise(name, "True", "caller-claimed-library"),), environment_sha256=context.context_id)
    scope = PremiseScope(content_hash(record), context.context_id, (name,))
    batch = providers.propose_batch(record, index, scope, cap=1)
    candidate = batch["drafts"][0]["source"]
    receipt = verifier(VerificationRequest(context, candidate, pin))
    assert receipt.outcome.value == expected, receipt
    assert verifier.processes == 1
    if expected == "VERIFIED":
        assert receipt.type_preserved
    elif name == "Bad.poison":
        assert receipt.reason == "axioms_policy"
