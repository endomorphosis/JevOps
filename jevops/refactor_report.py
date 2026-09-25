"""Deterministic, offline reports from rewrite-training and evaluation receipts.

No LLM, Lean invocation, training, repair, or promotion. This formats saved
measurements; it does not establish their truth. Large JSON stays on disk.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def _digest(value):
    # Same canonical state contract as rewrite_distillation.digest, without
    # importing the training/router stack or changing its token-count hooks.
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _select(data, keys):
    return {k: data[k] for k in keys.split() if k in data}


def _receipt(data):
    return _select(data, "theorem_ok kernel_audit diagnostics_source_sha256")


def build_bundle(run, *, arena=None, expressions=None, comparison=None):
    """Project raw receipts into stable regression artifacts; never change gates."""
    if run.get("schema") != "jevops-verified-rewrite-distillation/v1":
        raise ValueError("unsupported training receipt schema")
    if _digest(run["state"]) != run["state_sha256"]:
        raise ValueError("checkpoint state digest mismatch")
    if _digest(run["manifest"]) != run["manifest_sha256"]:
        raise ValueError("manifest digest mismatch")
    for label, receipt in (("arena", arena), ("expressions", expressions)):
        if receipt is not None and receipt.get("state_sha256") != run["state_sha256"]:
            raise ValueError(f"{label} checkpoint digest mismatch")
    synthetic = _select(run, """schema tokenizer_id scope split_policy semantic_family_decontamination
        ok epochs fixture_seed manifest_sha256 state_sha256 extended_curriculum compositional_holdout
        trajectory_training solver_feedback_enabled typed_terms_enabled reconstruction_heads_unchanged
        model_step rewrite_steps grammar config train_ids train_parent_ids development_gates holdout_gate
        holdout_valid holdout_accessed_after_freeze tuning_allowed_after_holdout checkpoint_promoted
        arena_data_used live_llm_used production_memory_used cost_guard_enabled cost_gate constructive_terms_enabled difference_curriculum""")
    for key in ("before", "after", "zero_weight_ablation", "holdout", "holdout_zero_weight_ablation"):
        synthetic[key] = {split: {k: v for k, v in data.items() if k != "rows"}
                          for split, data in run[key].items()}
    attempts = run["compile_attempts"]
    synthetic["unique_compile_count"] = len(attempts)
    synthetic["rejected_compile_count"] = sum(r["receipt"].get("theorem_ok") is not True for r in attempts)
    synthetic["holdout_predictions"] = [
        {**{k: v for k, v in r.items() if k != "compile" and (k not in ("proof_metrics", "source_proof_metrics") or v is not None)},
         "kernel_audit": r["compile"].get("kernel_audit")}
        for r in run["holdout"]["holdout"]["rows"]]
    synthetic["teachers"] = []
    synthetic["typed_training_probes"] = {}
    for row in run["manifest"]:
        if row["split"] not in ("train", "holdout"):
            continue
        teacher = run["teachers"][row["id"]]
        synthetic["teachers"].append({
            **_select(row, "id split family"),
            **_select(teacher, "source target source_tokens target_tokens"),
            **_select(teacher, "cost_guard cost_checks constructive_terms"),
            "source_compile": _receipt(teacher["source_compile"]),
            "trace": [{**{k: v for k, v in step.items() if k != "compile"},
                       "compile": _receipt(step["compile"])} for step in teacher["trace"]]})
        if row["split"] == "train" and teacher.get("typed_terms") and row.get("family", "").startswith("typed_"):
            synthetic["typed_training_probes"][row["id"]] = teacher["typed_terms"]
    synthetic["epoch_history"] = run["history"]
    if "structural_pairs" in run:
        pairs = run["structural_pairs"]
        synthetic["structural_pairs"] = _select(pairs, "schema ok accepted_count train_proposal_count compile_calls graph_bytes tokenizer_id dependency_environment_sha256 dependency_closure_verified semantic_family_decontamination manifest_sha256 decisions")
        synthetic["structural_pairs"]["pair_sha256"] = [p["pair_sha256"] for p in pairs["pairs"]]
        synthetic.update(_select(run, "structural_pair_targets_used graph_features_used_for_training"))
    checkpoint = _select(run, """config state state_sha256 manifest manifest_sha256 train_parent_ids train_ids
        tokenizer_id checkpoint_promoted arena_data_used reconstruction_heads_unchanged""")
    checkpoint.update(schema="jevops-typed-edit-checkpoint/v1", scope=run["scope"],
                      expression_nonregression_accepted=(expressions.get("expression_gates_accepted")
                                                        if expressions is not None else None))
    evidence = {"schema": "jevops-typed-edit-evidence/v1", "synthetic": synthetic,
                "checkpoint_promoted": run["checkpoint_promoted"]}
    if expressions is not None:
        evidence["expressions"] = expressions
    if arena is not None:
        compact = {k: v for k, v in arena.items() if k not in ("evaluations", "history", "reference_compile")}
        compact["reference_kernel_audit"] = arena["reference_compile"].get("kernel_audit")
        compact["evaluations"] = []
        for row in arena["evaluations"]:
            result = {k: v for k, v in row.items() if k not in ("source_compile", "trained", "untrained", "zero_edit_weights")}
            for key in ("trained", "untrained", "zero_edit_weights"):
                result[key] = {**{k: v for k, v in row[key].items() if k != "compile"},
                               "kernel_audit": row[key]["compile"].get("kernel_audit")}
            compact["evaluations"].append(result)
        evidence["arena"] = compact
    if comparison is not None:
        evidence["previous_checkpoint_typed_comparison"] = comparison
    return checkpoint, evidence


def _number(value):
    return "unavailable" if value is None else f"{value:.6g}"


def _gate(value):
    return "PASS" if value is True else "FAIL" if value is False else "UNAVAILABLE"


def render_summary(evidence):
    """Small fixed template; no generated claims of generalization or high scores."""
    data = evidence["synthetic"]
    before, after = data["before"]["canary"], data["after"]["canary"]
    holdout = data["holdout"]["holdout"]
    ablation = data["holdout_zero_weight_ablation"]["holdout"]
    lines = ["# Lean rewrite run", "", "Generated by `python -m jevops.refactor_report`; do not hand-edit.", "",
             f"Checkpoint: `{data['state_sha256']}`.",
             "Saved receipt summary only; no training, proof checking, or promotion occurs during reporting.", "",
             "| Evaluation | Valid / total | Shortened | Source tokens → prediction tokens |",
             "| --- | --- | --- | --- |"]
    for label, row in (("Canary", after), ("Holdout", holdout), ("Holdout, zero edit weights", ablation)):
        lines.append(f"| {label} | {row['verified']}/{row['sample_count']} | {row['verified_shortening']} | "
                     f"{row['source_tokens']} → {row['prediction_tokens']} |")
    lines += ["", f"Canary operation CE: {_number(before.get('cross_entropy'))} → {_number(after.get('cross_entropy'))}.",
              f"Canary output cosine: {_number(before.get('cosine_similarity'))} → {_number(after.get('cosine_similarity'))}.",
              f"Canary path CE: {_number(before.get('trajectory_cross_entropy'))} → {_number(after.get('trajectory_cross_entropy'))}.",
              f"Canary path cosine loss: {_number(before.get('trajectory_expected_cosine_loss'))} → {_number(after.get('trajectory_expected_cosine_loss'))}.",
              f"Holdout step labels: {holdout.get('trajectory_labeled_step_count', 'unavailable')}/{holdout.get('trajectory_step_count', 'unavailable')}; "
              f"complete examples: {holdout.get('trajectory_complete_examples', 'unavailable')}/{holdout['sample_count']}.",
              f"Holdout CE/cosine gate: {_gate(data.get('holdout_gate', {}).get('accepted'))}."]
    if data.get("cost_guard_enabled"):
        cost_gate = data.get("cost_gate", {})
        lines += [f"Teacher/prediction cost guard: {_gate(cost_gate.get('accepted'))}; "
                  f"{cost_gate.get('nonregressing_count', 'unavailable')}/{cost_gate.get('evaluated_count', 'unavailable')} predictions non-growing."]
        rejected = sum(c.get("accepted") is False for t in data["teachers"] for c in t.get("cost_checks", []))
        lines += [f"Rejected teacher cost checks in retained train/holdout traces: {rejected}."]
    if "structural_pairs" in data:
        pairs = data["structural_pairs"]
        lines += [f"Structural training-pair gate: {_gate(pairs['ok'])}; {pairs['accepted_count']} compressed pairs, "
                  f"{pairs['compile_calls']} fresh compilation calls.",
                  "DAGs are retained as supervision artifacts; graph features do not drive this sparse-model update."]
    if "arena" in evidence:
        arena = evidence["arena"]
        counts = "; ".join(f"{r['source_tokens']} → {r['trained']['body_tokens']}" for r in arena["evaluations"])
        lines += [f"Arena inputs: {counts}. Arena metric gate: {_gate(arena.get('metric_gates_accepted'))}."]
    expression = evidence.get("expressions", {})
    lines += [f"Expression non-growth gate: {_gate(expression.get('expression_gates_accepted'))}."]
    if expression:
        selection = expression.get("selection", {})
        lines += [f"Expression selection: {selection.get('evaluated_count', 'unavailable')}/{selection.get('matched_count', 'unavailable')}; "
                  f"complete: {_gate(selection.get('complete'))}."]
        failures = [r for r in expression["evaluations"] if r.get("expression_nonregression") is False]
        for row in failures[:5]:
            counts = [row["receipts"][k]["proof_metrics"]["proof"]["tree_nodes"] for k in ("source", "prediction")]
            lines += [f"Expression growth: `{row['id']}`; source tokens {row['source_tokens']} → {row['prediction_tokens']}, "
                      f"expression tree nodes {counts[0]} → {counts[1]}."]
        if len(failures) > 5:
            lines += [f"Additional expression-growth cases: {len(failures) - 5}; see evidence.json."]
    lines += ["", f"Recorded checkpoint promotion: {data['checkpoint_promoted']}.",
              f"Semantic-family decontamination: {data['semantic_family_decontamination']}.",
              "Source-token savings are not proof-term savings or kernel-time speedups.",
              "Full measurements and lineage: [evidence](evidence.json), [checkpoint](checkpoint.json), [provenance](provenance.json).", ""]
    return "\n".join(lines)


def _invalid_constant(value):
    raise ValueError(f"non-finite JSON constant: {value}")


def generate_report(run_path, output_dir, *, arena_path=None, expressions_path=None, comparison_path=None, archive_inputs=False):
    paths = {"run": Path(run_path), **({"arena": Path(arena_path)} if arena_path else {}),
             **({"expressions": Path(expressions_path)} if expressions_path else {}),
             **({"comparison": Path(comparison_path)} if comparison_path else {})}
    raw = {key: gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes() for key, path in paths.items()}
    docs = {key: json.loads(value, parse_constant=_invalid_constant) for key, value in raw.items()}
    comparison = docs.get("comparison")
    if comparison is not None:
        comparison = comparison.get("previous_checkpoint_typed_comparison", comparison)
    checkpoint, evidence = build_bundle(docs["run"], arena=docs.get("arena"),
                                        expressions=docs.get("expressions"), comparison=comparison)
    encode = lambda data: json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
    outputs = {"checkpoint.json": encode(checkpoint), "evidence.json": encode(evidence),
               "summary.md": render_summary(evidence)}
    archives = {f"inputs/{key}.json.gz": gzip.compress(value, mtime=0) for key, value in raw.items()} if archive_inputs else {}
    provenance = {"schema": "jevops-refactor-report/v1", "generator": "jevops.refactor_report",
                  "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  "input_sha256": {key: hashlib.sha256(value).hexdigest() for key, value in raw.items()},
                  "output_sha256": {key: hashlib.sha256(value.encode()).hexdigest() for key, value in outputs.items()},
                  "state_sha256": checkpoint["state_sha256"], "new_measurements_performed": False}
    if archives:
        provenance["archived_input_sha256"] = {name: hashlib.sha256(value).hexdigest() for name,value in archives.items()}
    outputs["provenance.json"] = encode(provenance)
    directory = Path(output_dir)
    if any((directory / name).exists() for name in (*outputs, *archives)):
        raise FileExistsError("report output already exists; use a new output directory")
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in outputs.items():
        with (directory / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(value)
    for name, value in archives.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(value)
    return {"summary": str(directory / "summary.md"), "artifacts": [*outputs, *archives],
            "state_sha256": checkpoint["state_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--arena", type=Path)
    parser.add_argument("--expressions", type=Path)
    parser.add_argument("--comparison", type=Path, help="Optional previous-checkpoint comparison or archived evidence containing it")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive-inputs", action="store_true", help="retain byte-exact input receipts as deterministic gzip archives")
    args = parser.parse_args(argv)
    try:
        result = generate_report(args.run, args.output_dir, arena_path=args.arena,
                                 expressions_path=args.expressions, comparison_path=args.comparison, archive_inputs=args.archive_inputs)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result))  # Paths only; never stream the full evidence into the agent.
    return 0  # Report generation success, not proof/metric-gate success.


if __name__ == "__main__":
    raise SystemExit(main())
