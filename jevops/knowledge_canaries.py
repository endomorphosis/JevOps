"""One-shot synthetic relation canaries; no training, tuning or promotion.

The protected boundary is this harness and its explicit training-admission API,
not every unrelated trainer in the repository. A retained DuckDB ledger prevents
relabeling exposed alpha-equivalent groups as new canaries within that ledger.
This is not a secret/blind dataset, semantic decontamination, or an Arena score.
"""
from __future__ import annotations

from dataclasses import asdict
from itertools import permutations
import json
from pathlib import Path
import random
import re

from .arena import content_hash, source_hash
from .constructive_proofs import read_proposition
from .knowledge_index import DATABASE_CONFIG, _duckdb
from .knowledge_relations import DeclarationBinding, EvidenceRelation, PropositionNode, RelationGraph, RelationLimits
from .knowledge_trial import RENDERINGS
from .lean import VersionPin
from .logic_ir import parse_formula, variables
from .proof_ca import canonical_json

SCHEMA = "jevops-protected-relation-canaries/v1"
PINS = (VersionPin("v4.26.0", "core-library-control"), VersionPin("v4.29.1", "core-library-control"))
FILES = ("knowledge_canaries.py", "knowledge_trial.py", "knowledge_relations.py", "constructive_proofs.py",
         "constructive_terms.py", "arena_trial.py", "premise_search.py", "knowledge_index.py", "skillcenter_corpus.py")

# Fixed BEFORE observing evaluation results. Reference bodies use constructors,
# not the nominated shortcut. No outcome-dependent case selection or resizing.
CASES = (
    ("and-assoc", "", "((p ∧ q) ∧ r) ↔ (p ∧ (q ∧ r))",
     "exact ⟨fun h => ⟨h.left.left, ⟨h.left.right, h.right⟩⟩, fun h => ⟨⟨h.left, h.right.left⟩, h.right.right⟩⟩",
     (("left", "(p ∧ q) ∧ r"), ("right", "p ∧ (q ∧ r)")),
     (("assoc", "left", "right", "and_assoc", ("p", "q", "r")),)),
    ("or-assoc", "", "((p ∨ q) ∨ r) ↔ (p ∨ (q ∨ r))",
     "exact ⟨fun h => h.elim (fun ab => ab.elim Or.inl (fun b => Or.inr (Or.inl b))) (fun c => Or.inr (Or.inr c)), "
     "fun h => h.elim (fun a => Or.inl (Or.inl a)) (fun bc => bc.elim (fun b => Or.inl (Or.inr b)) Or.inr)⟩",
     (("left", "(p ∨ q) ∨ r"), ("right", "p ∨ (q ∨ r)")),
     (("assoc", "left", "right", "or_assoc", ("p", "q", "r")),)),
    ("and-or-distrib", "", "(p ∧ (q ∨ r)) ↔ ((p ∧ q) ∨ (p ∧ r))",
     "exact ⟨fun h => h.right.elim (fun b => Or.inl ⟨h.left, b⟩) (fun c => Or.inr ⟨h.left, c⟩), "
     "fun h => h.elim (fun ab => ⟨ab.left, Or.inl ab.right⟩) (fun ac => ⟨ac.left, Or.inr ac.right⟩)⟩",
     (("left", "p ∧ (q ∨ r)"), ("right", "(p ∧ q) ∨ (p ∧ r)")),
     (("distrib", "left", "right", "and_or_left", ("p", "q", "r")),)),
    ("or-and-distrib", "", "(p ∨ (q ∧ r)) ↔ ((p ∨ q) ∧ (p ∨ r))",
     "exact ⟨fun h => h.elim (fun a => ⟨Or.inl a, Or.inl a⟩) (fun bc => ⟨Or.inr bc.left, Or.inr bc.right⟩), "
     "fun h => h.left.elim Or.inl (fun b => h.right.elim Or.inl (fun c => Or.inr ⟨b, c⟩))⟩",
     (("left", "p ∨ (q ∧ r)"), ("right", "(p ∨ q) ∧ (p ∨ r)")),
     (("distrib", "left", "right", "or_and_left", ("p", "q", "r")),)),
    ("nested-or-swap", "(h : (p ∧ q) ∨ r)", "r ∨ (p ∧ q)",
     "exact h.elim Or.inr Or.inl",
     (("left", "(p ∧ q) ∨ r"), ("right", "r ∨ (p ∧ q)")),
     (("swap", "left", "right", "Or.comm", ("p ∧ q", "r")),)),
    ("three-edge-permutation", "(h : p ∧ (q ∧ r))", "(r ∧ p) ∧ q",
     "exact ⟨⟨h.right.right, h.left⟩, h.right.left⟩",
     (("pq_r", "(p ∧ q) ∧ r"), ("p_qr", "p ∧ (q ∧ r)"),
      ("r_pq", "r ∧ (p ∧ q)"), ("rp_q", "(r ∧ p) ∧ q")),
     (("first", "pq_r", "p_qr", "and_assoc", ("p", "q", "r")),
      ("second", "pq_r", "r_pq", "And.comm", ("p ∧ q", "r")),
      ("third", "rp_q", "r_pq", "and_assoc", ("r", "p", "q")))),
)


def alpha_group(source):
    """Exact propositional alpha/context normalization, NOT logical equivalence.

    Four-atom bound keeps exhaustive renaming canonicalization <=24 variants.
    Local names, hypothesis order/duplication and leading implication binders
    do not create fresh groups. Unsupported sources fail closed.
    """
    _, goal, assumptions = read_proposition(source)
    hypotheses = [f for _, f in assumptions]
    while goal.op == "imp":
        hypotheses.append(goal.args[0])
        goal = goal.args[1]
    names = sorted(variables(goal, *hypotheses))
    if len(names) > 4:
        raise ValueError("four-atom protected identity bound")
    hashes = []
    for order in permutations(range(len(names))):
        rename = dict(zip(names, order))
        def norm(f):
            return ["var", rename[f.name]] if f.op == "var" else [f.op, *[norm(a) for a in f.args]]
        hashes.append(content_hash({"schema": "jevops-proposition-alpha/v1", "goal": norm(goal),
                                   "context": sorted({canonical_json(norm(h)) for h in hypotheses})}))
    return min(hashes)


def make_manifest(development_records, *, seed=20260924):
    if (type(seed) is not int or not 0 <= seed < 2**32 or type(development_records) is not list
            or not 1 <= len(development_records) <= 32):
        raise ValueError("bounded explicit seed and development records required")
    development = []
    for record in development_records:
        if type(record) is not dict or type(record.get("src")) is not str or len(record["src"].encode()) > 32768:
            raise ValueError("bounded development source required")
        development.append({"record": record, "group_sha256": alpha_group(record["src"])})
    rng, cases = random.Random(seed), []
    for family, context, goal, body, nodes, edges in CASES:
        nonce = rng.randrange(2**48)
        names = {name: f"{name}_{nonce}" for name in ("p", "q", "r", "h")}
        rename = lambda s: re.sub(r"(?<![\w.'])\b[pqrh]\b", lambda m: names[m[0]], s)
        target = f"canary_{family.replace('-', '_')}_{nonce}"
        statement = f"theorem {target} ({names['p']} {names['q']} {names['r']} : Prop) {rename(context)} : {rename(goal)}"
        record = dict(name=target, statement=statement, src=statement + " := by\n  " + rename(body) + "\n",
                      version_info=[{p.lean_tag: p.git_commit} for p in PINS])
        cases.append(dict(id=target, family=family, split="canary", training_allowed=False, record=record,
            group_sha256=alpha_group(record["src"]), nodes=[(n, rename(f)) for n, f in nodes],
            edges=[(e, a, b, decl, tuple(rename(f) for f in args)) for e, a, b, decl, args in edges]))
    groups = [c["group_sha256"] for c in cases]
    if len(set(groups)) != len(groups) or set(groups).intersection(r["group_sha256"] for r in development):
        raise ValueError("canary/development alpha-group overlap; no automatic resampling")
    plan = dict(schema=SCHEMA, seed=seed, development=development, cases=cases,
        pins=[p.to_dict() for p in PINS], renderings=list(RENDERINGS), limits=asdict(RelationLimits()), repetitions=2,
        primary_policy="inferred-term", baseline_policy="local-term", max_export_processes_per_case=2,
        max_proof_processes_per_case=48, max_total_processes=300, training_enabled=False, promoted=False,
        claim_scope="synthetic_post_development_canary_smoke_not_blind_generalization",
        implementation_sha256=content_hash({name: source_hash(Path(__file__).with_name(name).read_text()) for name in FILES}))
    return {**plan, "manifest_sha256": content_hash(plan)}


def validate_manifest(manifest):
    fresh = make_manifest([r["record"] for r in manifest["development"]], seed=manifest["seed"])
    if content_hash(manifest) != content_hash(fresh):
        raise ValueError("stale or mutated frozen canary manifest")


def assert_training_disjoint(manifest, rows):
    """Explicit future admission seam; this module exports NO training pairs."""
    validate_manifest(manifest)
    if type(rows) is not list or len(rows) > 256:
        raise ValueError("bounded explicit training rows required")
    protected = {c["group_sha256"] for c in manifest["cases"]}
    ids = {c["id"] for c in manifest["cases"]}
    for row in rows:
        if (type(row) is not dict or row.get("split") != "train" or row.get("id") in ids
                or alpha_group(row["source"]) in protected):
            raise ValueError("protected canary or non-training row")


def bind_graph(case, index, corpus, evidence_cid):
    """Instantiate the frozen recipe; missing inventory mappings fail explicitly."""
    return RelationGraph(content_hash(case["record"]), index.environment_sha256, corpus.identity["snapshot_sha256"],
        content_hash({"manual_canary_recipe": case}),
        tuple(PropositionNode(n, parse_formula(f)) for n, f in case["nodes"]),
        tuple(EvidenceRelation(e, "iff", a, b, (evidence_cid,)) for e, a, b, _, _ in case["edges"]),
        tuple(DeclarationBinding(e, decl, content_hash(asdict(index.entries[decl])),
            content_hash(index.signatures[decl].to_dict()), tuple(parse_formula(f) for f in args))
              for e, _, _, decl, args in case["edges"]))


class CanaryLedger:
    """Single-writer DuckDB exposure ledger. Never delete rows to refresh holdouts."""
    def __init__(self, path):
        path = Path(path)
        if path.is_symlink():
            raise ValueError("owned ledger path required")
        existing = path.exists()
        self.db = _duckdb().connect(str(path), config=DATABASE_CONFIG)
        try:
            if not existing:
                self.db.execute("BEGIN")
                self.db.execute("CREATE TABLE metadata (schema VARCHAR PRIMARY KEY)")
                self.db.execute("INSERT INTO metadata VALUES (?)", [SCHEMA])
                self.db.execute("CREATE TABLE runs (manifest VARCHAR PRIMARY KEY, status VARCHAR NOT NULL)")
                self.db.execute("CREATE TABLE exposed (group_id VARCHAR PRIMARY KEY, manifest VARCHAR NOT NULL)")
                self.db.execute("COMMIT")
            if self.db.execute("SELECT schema FROM metadata").fetchall() != [(SCHEMA,)]:
                raise ValueError("foreign canary ledger schema")
        except Exception:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def claim(self, manifest):
        validate_manifest(manifest)
        self.db.execute("BEGIN")
        try:
            groups = [c["group_sha256"] for c in manifest["cases"]]
            if self.db.execute("SELECT count(*) FROM exposed WHERE group_id IN (SELECT unnest(?))", [groups]).fetchone()[0]:
                raise ValueError("previously exposed canary groups; classify future use as regression")
            self.db.execute("INSERT INTO runs VALUES (?, 'CLAIMED')", [manifest["manifest_sha256"]])
            self.db.executemany("INSERT INTO exposed VALUES (?, ?)", [(g, manifest["manifest_sha256"]) for g in groups])
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def finish(self, manifest, status):
        if status not in {"COMPLETE", "INCOMPLETE"}:
            raise ValueError("terminal measurement status required")
        changed = self.db.execute("UPDATE runs SET status=? WHERE manifest=? AND status='CLAIMED' RETURNING manifest",
                                  [status, manifest["manifest_sha256"]]).fetchall()
        if len(changed) != 1:
            raise ValueError("one claimed run required")


def summarize(manifest, results):
    """Keep the full frozen denominator; rejected/missing/fallback outputs are not wins."""
    rows = []
    for case in manifest["cases"]:
        result = results.get(case["id"], {})
        report = result.get("report", {})
        plan = report.get("plan", {})
        policies = plan.get("policies", {})
        comparison = report.get("rendering_comparisons", {}).get("inferred-term", {}).get("versus_compact_local", {})
        native = report.get("measurement", {}).get("evidence_mode") == "local_lean"
        eligible = (result.get("status") == "COMPLETE" and native and comparison.get("graph_proposal_verified") is True
                    and policies.get("local-term", {}).get("status") == "PROPOSED")
        rows.append(dict(id=case["id"], family=case["family"], status=result.get("status", "NOT_RUN"),
            proposal_status=policies.get("inferred-term", {}).get("status", "NOT_RUN"),
            baseline_status=policies.get("local-term", {}).get("status", "NOT_RUN"),
            witness_status=policies.get("mapped-relations", {}).get("status", "NOT_RUN"),
            measured_native_pair=eligible, local_tokens=comparison.get("reference_tokens"),
            inferred_tokens=comparison.get("candidate_tokens"), heartbeat_result=comparison.get("heartbeat_result", "INCOMPLETE"),
            strict_joint_improvement=eligible and comparison.get("observed_pareto_improvement") is True,
            reason=result.get("reason", "")))
    return dict(schema="jevops-relation-canary-summary/v1", manifest_sha256=manifest["manifest_sha256"],
        denominator=len(rows), measured_native_pairs=sum(r["measured_native_pair"] for r in rows),
        strict_joint_improvements=sum(r["strict_joint_improvement"] for r in rows), cases=rows,
        training_enabled=False, promoted=False, official_score=None, blind_generalization_claimed=False,
        status="COMPLETE" if all(r["status"] == "COMPLETE" for r in rows) else "INCOMPLETE")


def run_canaries(manifest, *, evaluate_case, ledger, output_dir, resource_check, max_processes=0,
                 evidence_mode="local_lean"):
    """Trusted, budget-owning backend injection; frozen before the first observation.

    Backend must enforce two export + 48 proof processes per case and return
    status, report (run_relation_trial), and setup_processes; artifacts may be
    attached. It owns prepared dependencies. There are no retries or tuning
    callbacks. Budget reservations include failures. Low storage stops the run.
    """
    validate_manifest(manifest)
    if (type(max_processes) is not int or max_processes != manifest["max_total_processes"]
            or evidence_mode not in {"local_lean", "offline_fixture"}):
        raise ValueError("explicit full frozen process allowance required")
    resource_check()
    directory = Path(output_dir)
    directory.mkdir()  # exclusive: never overwrite another receipt set
    ledger.claim(manifest)  # durable BEFORE any preparation/compiler calls
    def write(name, value):
        with (directory / name).open("x") as stream:
            stream.write(canonical_json(value))
    write("manifest.json", manifest)
    results, reserved = {}, 0
    for case in manifest["cases"]:
        try:
            resource_check()
            validate_manifest(manifest)
        except (OSError, ValueError) as exc:
            results[case["id"]] = dict(status="STOPPED", reason=str(exc)[:300])
            break
        reserved += 50  # includes setup that may fail before producing a report
        try:
            result = evaluate_case(case, manifest, directory)
            trial = result["report"]["measurement"]
            if (content_hash(trial["record"]) != content_hash(case["record"])
                    or trial["evidence_mode"] != evidence_mode
                    or trial["planned_requests"] != 48 or trial["requests_reserved"] != 48
                    or not 0 <= result["setup_processes"] <= 2 or not 0 <= trial["verifier_invocations"] <= 48
                    or result["report"]["plan"]["renderings"] != manifest["renderings"]
                    or result["report"]["plan"]["limits"] != manifest["limits"]):
                raise ValueError("backend departed from the frozen case/budget")
            result["status"] = result["report"]["status"]
        except Exception as exc:
            result = dict(status="ERROR", reason=f"{type(exc).__name__}: {exc}"[:300])
        results[case["id"]] = result
        # Do not silently accept an implementation edited during evaluation.
        try:
            validate_manifest(manifest)
        except ValueError:
            result["status"] = "IMPLEMENTATION_CHANGED"
        write(case["family"] + ".json", result)
        if result["status"] == "IMPLEMENTATION_CHANGED":
            break
    summary = {**summarize(manifest, results), "processes_reserved": reserved, "max_processes": max_processes}
    write("summary.json", summary)
    lines = ["# Protected relation canary smoke test", "",
        "Synthetic post-development cases, not a blind dataset or an all-15 Arena score.", "",
        f"Native paired coverage: {summary['measured_native_pairs']}/{summary['denominator']}; "
        f"strict joint improvements: {summary['strict_joint_improvements']}/{summary['denominator']}.", "",
        "| Case | Inferred proposal | Compact local tokens | Inferred tokens | Heartbeats vs local | Run |",
        "| --- | --- | ---: | ---: | --- | --- |"]
    for row in summary["cases"]:
        lines.append(f"| {row['family']} | {row['proposal_status']} | {row['local_tokens']} | {row['inferred_tokens']} | "
                     f"{row['heartbeat_result']} | {row['status']} |")
    lines.extend(["", "All frozen cases stay in the denominator. No training, promotion, model calls, or outcome-dependent tuning.",
                  "The ledger consumes these alpha groups even on partial failure; future reuse is regression, not a fresh canary.", ""])
    with (directory / "summary.md").open("x") as stream:
        stream.write("\n".join(lines))
    ledger.finish(manifest, summary["status"])
    return summary
