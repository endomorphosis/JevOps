"""Portable-rule routing and untrusted nominations, never proof admission."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

import pytest

from jevops import arena_compositions as compositions, arena_rules as rules, folds, hooks
from jevops.arena import content_hash, reference_tokens, source_hash
from jevops.arena_trial import Candidate

STATEMENT = "theorem rule_fixture (h : True) : True"
SOURCE = STATEMENT + " := by\n  exact h"
RECORD = {"name": "rule_fixture", "statement": STATEMENT, "src": SOURCE}


@pytest.fixture(autouse=True)
def no_legacy_measurement_or_oracle(monkeypatch):
    def forbidden(*_a, **_kw):
        pytest.fail("portable draft routing must not use legacy hooks, counts or native processes")
    from jevops import arena_lean, lean
    monkeypatch.setattr(hooks, "get", forbidden)
    monkeypatch.setattr(folds, "_token_count", forbidden)
    monkeypatch.setattr(lean, "token_count", forbidden)
    monkeypatch.setattr(arena_lean, "run_native", forbidden)


@pytest.mark.parametrize("rule,body", [
    ("port_exact_hyp", "  exact h"),
    ("port_use_exact", "  use n\n  exact ⟨rfl, h⟩"),
    ("port_use_exact_reuse", "  use (n + 0)\n  exact ⟨.refl (n + 0), h⟩"),
    ("port_ctor_pair_exacts", "  constructor\n  · exact h\n  · exact h"),
    ("port_semi_assumption", "  apply h <;> assumption\n  simp_all"),
    ("port_repeat_par_grind", "  apply ParallelReduction.par <;>\n    apply ParallelReduction.par <;>\n    grind"),
    ("port_grind_only_to_grind", "  grind only [Nat.add_comm]"),
    ("port_drop_unfold_before_split", "  unfold hidden\n  split"),
    ("port_drop_try_simp_all", "  induction n <;>\n    simp [id] at * <;>\n    try simp_all"),
    ("port_drop_intro_before_simp_all", "  intro\n  simp_all"),
    ("port_trim_intro_names", "  intro unused\n  trivial"),
    ("port_unused_intros", "  intros x Hin\n  trivial"),
    ("port_trailing_tuple_comma", "  exact ⟨h, h,⟩"),
    ("port_redundant_inner_simp", "  induction n <;>\n    simp [id] at *\n  case zero =>\n    simp [id]\n    trivial"),
    ("port_hoist_repeated_simp", "  induction n <;>\n    simp [id] at *\n  case zero =>\n    simp [Nat.add_comm] at *\n    trivial\n  case succ =>\n    simp [Nat.add_comm] at *\n    trivial"),
])
def test_portable_rules_produce_only_unverified_body_edits(rule, body):
    source = STATEMENT + " := by\n" + body
    result = rules.portable_proposal(source, STATEMENT, rule)
    assert result is not None and result != source
    assert result.startswith(STATEMENT + " := by\n")
    record = {**RECORD, "src": source}
    batch = compositions.draft_batch(record, [[rule]])
    assert batch["drafts"][0]["source"] == result
    step = batch["attempts"][0]["steps"][0]
    assert step["before_tokens"] == reference_tokens(source, STATEMENT)
    assert step["after_tokens"] == reference_tokens(result, STATEMENT)
    assert not batch["proof_verified"] and not batch["training_enabled"]
    assert batch["native_processes"] == 0
    assert batch["tokenizer_id"] == "lra-reference-lexical/v1"
    assert set(batch["rule_sources_sha256"]) == {"arena_rules.py", "folds.py"}


@pytest.mark.parametrize("name,old,new", folds.SHORTEN_IDENTS)
def test_qualified_name_shortening_cannot_earn_legacy_only_tokens(name, old, new):
    source = STATEMENT + " := by\n  exact " + old
    assert reference_tokens(source, STATEMENT) == reference_tokens(source.replace(old, new), STATEMENT)
    assert rules.portable_proposal(source, STATEMENT, "port_shorten_" + name) is None


def test_reuse_fold_abstains_when_tuple_packing_has_no_net_token_savings():
    source = STATEMENT + " := by\n  use n\n  exact ⟨.refl n, h⟩"
    assert rules.portable_proposal(source, STATEMENT, "port_use_exact_reuse") is None


@pytest.mark.parametrize("term", ["H.foo", "h argument", "HlongerThanSupported", "H_field", "h'.foo"])
def test_exact_hyp_does_not_rewrite_qualified_names_or_partial_applications(term):
    source = STATEMENT + " := by\n  exact " + term
    assert folds.fold_exact_hyp(source) == source
    assert rules.portable_proposal(source, STATEMENT, "port_exact_hyp") is None


@pytest.mark.parametrize("tail", [" -- exact h", '\n  /- exact h -/', '\n  «exact h»',
                                   '\n  "exact h"', '\n  `exact h', '\n\texact h', '\r'])
def test_unsupported_lexical_shapes_abstain(tail):
    assert rules.portable_proposal(SOURCE + tail, STATEMENT, "port_exact_hyp") is None


def test_unknown_term_large_and_mismatched_inputs():
    with pytest.raises(ValueError, match="unknown"):
        rules.portable_proposal(SOURCE, STATEMENT, "__import__")
    assert rules.portable_proposal(STATEMENT + " := h", STATEMENT, "port_exact_hyp") is None
    assert rules.portable_proposal(SOURCE, "theorem different : True", "port_exact_hyp") is None
    assert rules.portable_proposal(SOURCE + " " * 32768, STATEMENT, "port_exact_hyp") is None
    assert rules.portable_proposal(SOURCE + "\n" * 257, STATEMENT, "port_exact_hyp") is None
    assert rules.portable_proposal(SOURCE + "\n  sorry", STATEMENT, "port_exact_hyp") is None


@pytest.mark.parametrize("operator", [";", "<;>"])
def test_try_simp_fold_matches_both_combinators_without_eating_following_tactics(operator):
    body = f"  simp [id] at * {operator}\n    try simp_all\n  case zero =>\n    exact h"
    assert folds.fold_drop_try_simp_all(body) == "  simp [id] at *\n  case zero =>\n    exact h"
    for tail in (" only [h]", " <;> exact h", "_other"):
        unsupported = f"  simp [id] at * {operator}\n    try simp_all" + tail
        assert folds.fold_drop_try_simp_all(unsupported) == unsupported


def test_statement_with_inner_assignment_is_never_transformed():
    statement = "theorem inner_assignment (n : Nat := 0) (h : True) : True"
    source = statement + " := by\n  exact h"
    result = rules.portable_proposal(source, statement, "port_exact_hyp")
    assert result == statement + " := by\n  assumption"


def test_seed_keeps_original_record_and_cost_baseline():
    record = {**RECORD, "src": STATEMENT + " := by\n  have other : True := h\n  exact other"}
    seed = Candidate("historical", SOURCE, "unverified historical seed")
    batch = compositions.draft_batch(record, [["port_exact_hyp"]], seed=seed)
    assert batch["record_sha256"] == content_hash(record)
    assert batch["reference_source_sha256"] == source_hash(record["src"])
    assert batch["reference_tokens"] == reference_tokens(record["src"], STATEMENT)
    assert batch["base_source_sha256"] == source_hash(SOURCE)
    assert batch["base_tokens"] == reference_tokens(SOURCE, STATEMENT)
    assert batch["seed"] == asdict(seed)
    assert batch["attempts"][0]["steps"][0]["before_sha256"] == source_hash(SOURCE)
    assert batch["drafts"][0]["source"] == STATEMENT + " := by\n  assumption"


@pytest.mark.parametrize("seed", ["raw source", Candidate("bad", "theorem other : True := by trivial", "wrong target"),
                                   Candidate("bad", STATEMENT + " := by sorry", "forbidden source")])
def test_invalid_seed_cannot_change_theorem_or_bypass_intake(seed):
    with pytest.raises(ValueError, match="seed"):
        compositions.draft_batch(RECORD, [["port_exact_hyp"]], seed=seed)


def test_external_nominations_are_hash_bound_paths_not_authority():
    proposal = {"record_sha256": content_hash(RECORD), "base_source_sha256": source_hash(SOURCE),
                "paths": [["port_exact_hyp"]]}
    assert compositions.proposal_paths(RECORD, proposal) == proposal["paths"]
    for key, value in [("record_sha256", "0" * 64), ("base_source_sha256", "0" * 64),
                       ("verified", True), ("reward", 999), ("source", SOURCE), ("kernel_accepted", True)]:
        with pytest.raises(ValueError, match="hashes and paths"):
            compositions.proposal_paths(RECORD, {**proposal, key: value})
    seed = Candidate("different", SOURCE + "\n", "different source bytes")
    with pytest.raises(ValueError):
        compositions.proposal_paths(RECORD, proposal, seed=seed)


def test_cli_seed_and_model_nominations_roundtrip(tmp_path, monkeypatch, capsys):
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(json.dumps(RECORD) + "\n")
    seed = Candidate("seed", SOURCE + "\n", "unverified")
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps({"name": RECORD["name"], **asdict(seed)}))
    proposal = {"record_sha256": content_hash(RECORD), "base_source_sha256": source_hash(seed.source),
                "paths": [["port_exact_hyp"]]}
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps(proposal))
    output = tmp_path / "drafts"
    argv = ["arena_compositions", "--corpus", str(corpus), "--problem", RECORD["name"],
            "--seed", str(seed_path), "--proposal-file", str(proposal_path), "--output-dir", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    assert compositions.main() == 0
    assert json.loads(capsys.readouterr().out)["count"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["seed"] == asdict(seed) and not manifest["proof_verified"]
    # A producer claiming verification cannot create a second output directory.
    proposal_path.write_text(json.dumps({**proposal, "verified": True}))
    argv[-1] = str(tmp_path / "must-not-exist")
    with pytest.raises(SystemExit) as exc:
        compositions.main()
    assert exc.value.code == 2 and not Path(argv[-1]).exists()


@pytest.mark.parametrize("paths", [[["exec"]], [["port_exact_hyp"] * 4], [["port_exact_hyp"]] * 9])
def test_nominations_cannot_expand_vocabulary_or_search_budget(paths):
    proposal = {"record_sha256": content_hash(RECORD), "base_source_sha256": source_hash(SOURCE), "paths": paths}
    with pytest.raises(ValueError):
        compositions.draft_batch(RECORD, compositions.proposal_paths(RECORD, proposal))


def test_oversized_proposal_is_rejected_before_json_parsing(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b" " * 1_048_577)
    with pytest.raises(ValueError, match="byte limit"):
        compositions._read_json(path)


@pytest.mark.parametrize("extra", [{"verified": True}, {"token_count": 1}, {"kernel_accepted": True}, {"name": "other"}])
def test_cli_rejects_seed_authority_claims_and_wrong_target(tmp_path, monkeypatch, extra):
    corpus, seed_path, output = tmp_path / "corpus.jsonl", tmp_path / "seed.json", tmp_path / "out"
    corpus.write_text(json.dumps(RECORD))
    seed_path.write_text(json.dumps({"name": RECORD["name"], "label": "seed", "source": SOURCE,
                                     "provenance": "unverified", **extra}))
    monkeypatch.setattr(sys, "argv", ["arena_compositions", "--corpus", str(corpus), "--problem", RECORD["name"],
        "--seed", str(seed_path), "--path", "port_exact_hyp", "--output-dir", str(output)])
    with pytest.raises(SystemExit) as exc:
        compositions.main()
    assert exc.value.code == 2 and not output.exists()
