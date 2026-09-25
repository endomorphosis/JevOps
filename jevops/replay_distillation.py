"""Bounded replay-to-edit-head training experiment; not an arena scorer.

Only independently checked, shorter whole proofs become teachers. Native open
states guide teacher search; they are not inputs to a trained graph encoder.
"""
from __future__ import annotations

import argparse
from functools import partial
import hashlib
import json
from pathlib import Path
import random

from . import autoencoder as ae
from .autoencoder_training import (AutoencoderConfig, LeanIRAutoencoder, canary_gate,
                                   coerce_training_example, loss_for_example)
from .expr_dag import CODEC
from .proof_replay import closing_proposals, collect_replay_pairs, digest, replay_candidate
from .proof_state import capture_source
from .proof_tokens import TOKENIZER_ID, proof_source_tokens
from .replay_curriculum import compound_regressions, compound_rows, transfer_rows
from .rewrite_distillation import _aggregate
from .rewrite_policy import choices
from .router_tuning import _ir_body, _render_source, _source_parts
from .structural_training import _checked_export, _envelope

SCHEMA = "jevops-replay-distillation/v1"
HEADS = ("vocab", "op_bias", "transition", "feature_op", "latent_bias", "feature_latent")


def control_rows(seed=20260922):
    """Renamed members of ONE family, not decontaminated mathematical holdouts."""
    rows = []
    for split in ("train", "validation", "canary", "holdout"):
        n = random.Random(f"{seed}:{split}").randrange(10**8)
        p, h = f"p_{n}", f"h_{n}"
        name = f"replay_{split}_{n}"
        prefix = f"theorem {name} ({p} : Prop) ({h} : {p}) : {p} := by\n"
        rows.append({"id": name, "split": split, "source": prefix + f"  exact id {h}\n",
                     "target": prefix + "  assumption\n"})
    return rows


def run_experiment(*, capture_fn, replay_fn, compile_fn, environment_sha256, rows=None,
                   epochs=24, max_compiles=None,
                   proposal_fn=None, event=None, curriculum="control", seed=20260922,
                   refine_fn=None, refinement_rounds=0, max_teacher_proposals=8):
    """Fixed-budget SGD, frozen reconstruction, final holdout after checkpoint freeze.

    Callback implementations and caller-owned splits are trusted. Evaluation
    never repairs a prediction, mines a template, or updates any parameters.
    """
    if max_compiles is None:
        max_compiles = 128 if curriculum == "compound" else 48
    if type(epochs) is not int or not 1 <= epochs <= 200 or type(max_compiles) is not int or not 1 <= max_compiles <= 256:
        raise ValueError("invalid experiment budget")
    if curriculum not in ("control", "transfer", "compound") or type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("invalid curriculum or seed")
    provided_rows = rows is not None
    builders = {"control": control_rows, "transfer": transfer_rows, "compound": compound_rows}
    rows = builders[curriculum](seed) if rows is None else rows
    if proposal_fn is None:
        proposal_fn = partial(closing_proposals, candidates=("rfl", "assumption", "trivial")
                              if curriculum != "control" else ("rfl", "assumption"))
    if not isinstance(rows, list) or not 4 <= len(rows) <= 32:
        raise ValueError("bounded four-way manifest required")
    ids = [r["id"] for r in rows]
    if (any(not isinstance(i, str) or not i or len(i) > 256 for i in ids) or len(set(ids)) != len(ids)
            or {r["split"] for r in rows} != {"train", "validation", "canary", "holdout"}):
        raise ValueError("unique identities and four known splits required")
    for row in rows:
        if any(not isinstance(row.get(k, "unspecified"), str) or not 1 <= len(row.get(k, "unspecified")) <= 128
               for k in ("family", "context")):
            raise ValueError("invalid curriculum metadata")
    cache, attempts, events, source_owners = {}, [], [], {}

    def bind_source(row):
        source = row["source"]
        if not isinstance(source, str) or len(source.encode()) > 65_536:
            raise ValueError("source budget")
        # Lazy binding: holdout content is not read until after freeze. This is
        # an exact/whitespace duplicate check, not semantic decontamination.
        key = digest(" ".join(source.split()))
        owner = (row["id"], row["split"])
        if key in source_owners and source_owners[key] != owner:
            raise ValueError("duplicate or cross-split source leakage")
        source_owners[key] = owner
        return source

    for row in rows:
        if row["split"] == "train":
            bind_source(row)

    def notify(kind, **data):
        events.append({"event": kind, **data})
        if event:
            event(events[-1])

    def compile_one(source):
        if source not in cache:
            if len(attempts) >= max_compiles:
                return {"theorem_ok": False, "reason": "compile_budget"}
            try:
                receipt = compile_fn(source)
            except Exception as exc:
                receipt = {"theorem_ok": False, "reason": type(exc).__name__}
            cache[source] = receipt
            attempts.append({"source": source, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                             "receipt": receipt})
        return cache[source]

    notify("training_teacher_search")
    teachers = collect_replay_pairs(rows, capture_fn=capture_fn, replay_fn=replay_fn,
        compile_fn=compile_one, environment_sha256=environment_sha256, proposal_fn=proposal_fn,
        refine_fn=refine_fn, refinement_rounds=refinement_rounds, max_proposals=max_teacher_proposals)
    if not teachers["ok"]:
        return {"schema": SCHEMA, "ok": False, "reason": "replay_teacher_gate", "training_pairs": teachers,
                "model_step": 0, "checkpoint_promoted": False, "events": events, "compile_attempts": attempts}
    train = [coerce_training_example(p) for p in teachers["pairs"]]
    train_targets = {p["id"]: p["target_text"] for p in teachers["pairs"]}
    cfg = AutoencoderConfig(train_rewrite_policy=True, freeze_reconstruction_heads=True,
                            learning_rate=.15, warmup_steps=0, decay_steps=1000, rewrite_max_edits=1, seed=17)
    model = LeanIRAutoencoder(config=cfg)
    grammar = model.prepare_rewrite_training(train)
    unreachable = [ex.sample_id for ex in train if model.rewrite_objective(ex) is None]
    if unreachable:
        return {"schema": SCHEMA, "ok": False, "reason": "unreachable_edit_teacher",
                "unreachable_train_ids": unreachable, "training_pairs": teachers, "grammar": grammar,
                "model_step": 0, "checkpoint_promoted": False, "events": events, "compile_attempts": attempts}
    initial = model.to_dict()
    notify("grammar_frozen", train_ids=[ex.sample_id for ex in train], digest=grammar["after_digest"])
    codec_sha = hashlib.sha256(CODEC.read_bytes()).hexdigest()
    training_wire = next(iter(teachers["graphs"].values()))
    toolchain = (training_wire["lean_version"], training_wire["lean_githash"])

    def assess(source, candidate):
        try:
            declaration = _envelope(source, candidate)
            a, aw = _checked_export(compile_one(source), source, declaration, environment_sha256, codec_sha, 50_000)
            b, bw = _checked_export(compile_one(candidate), candidate, declaration, environment_sha256, codec_sha, 50_000)
            same = (all((w["lean_version"], w["lean_githash"]) == toolchain for w in (aw, bw))
                    and a["type"] == b["type"] and a["export"]["level_parameters"] == b["export"]["level_parameters"]
                    and set(b["export"]["axioms"]) <= set(a["export"]["axioms"]))
            cost = same and all(b["proof"][k] <= a["proof"][k]
                                for k in ("unique_expression_nodes", "expanded_expression_nodes"))
            return {"verified": same, "expression_nonregression": cost,
                    "source_proof": a["proof"], "candidate_proof": b["proof"],
                    "reason": None if cost else "proof_expression_growth" if same else "type_toolchain_or_axiom_mismatch"}
        except (ValueError, TypeError, KeyError) as exc:
            return {"verified": False, "expression_nonregression": False, "reason": str(exc)[:240]}

    def evaluate(selected, decoder):
        snapshot, outputs = decoder.to_dict(), []
        for row in selected:
            source = bind_source(row)
            applicable = len(choices(source, decoder.state["rewrite_templates"])) - 1
            # Decode and commit raw output BEFORE accessing any target label.
            predicted_ir = decoder.predict_ir(source, source_ir=ae.encode_lean_ir(source))
            prefix, _, theorem = _source_parts(source)
            prediction = _render_source(prefix, _ir_body(predicted_ir), has_theorem=theorem)
            target = train_targets[row["id"]] if row["split"] == "train" else row["target"]
            if not isinstance(target, str) or len(target.encode()) > 65_536:
                raise ValueError("evaluation target budget")
            teacher_check, check = assess(source, target), assess(source, prediction)
            tokens, source_tokens = proof_source_tokens(prediction), proof_source_tokens(source)
            target_tokens = proof_source_tokens(target)
            shorter = check["expression_nonregression"] and tokens < source_tokens
            loss = None
            if teacher_check["expression_nonregression"]:
                ex = coerce_training_example({"id": row["id"], "text": source, "target_ir": ae.encode_lean_ir(target)})
                loss = loss_for_example(decoder, ex, predicted_ir=predicted_ir, verifier_reward=float(check["verified"]),
                                        minimality_reward=float(shorter))
            output = {"id": row["id"], "split": row["split"], "prediction": prediction,
                "family": row.get("family", "unspecified"), "context": row.get("context", "unspecified"),
                "target_kind": "compression" if target_tokens < source_tokens else "preservation",
                "target_tokens": target_tokens, "applicable_edits": applicable,
                "target_reachable": None if loss is None else loss.rewrite_cross_entropy is not None,
                "metric_status": "unverified_target" if loss is None else
                                 "unreachable_edit_label" if loss.rewrite_cross_entropy is None else "measured",
                "prediction_unchanged": prediction.strip() == source.strip(),
                "prediction_sha256": hashlib.sha256(prediction.encode()).hexdigest(), "check": check,
                "rewrite_policy": predicted_ir.get("rewrite_policy"),
                "teacher_check": teacher_check, "source_tokens": source_tokens, "prediction_tokens": tokens,
                "verified": check["verified"], "expression_nonregression": check["expression_nonregression"],
                "verified_shortening": shorter, "minimality_reward": float(shorter),
                "loss": None if loss is None else loss.to_dict()}
            if row["split"] == "regression":
                output.update(provenance=row["provenance"], previous_reference=row["previous_reference"],
                              previous_reference_check=assess(source, row["previous_reference"]))
            outputs.append(output)
        if decoder.to_dict() != snapshot:
            raise ValueError("evaluation mutated checkpoint")
        return {s: summarize_rows([r for r in outputs if r["split"] == s])
                for s in dict.fromkeys(r["split"] for r in selected)}

    development = [r for r in rows if r["split"] != "holdout"]
    before = evaluate(development, model)
    history = []
    notify("training", epochs=epochs)
    for epoch in range(epochs):
        batch = model.train_batch(train)
        if epoch in {0, epochs//2, epochs-1}:
            history.append({"epoch": epoch+1, **batch})
    frozen = model.to_dict()
    if any(initial[k] != frozen[k] for k in HEADS):
        raise ValueError("reconstruction heads changed")
    notify("checkpoint_frozen", sha256=digest(frozen))
    after = evaluate(development, model)
    zeroed = model.copy()
    zeroed.state["rewrite_weights"] = {}
    notify("final_holdout")
    holdout_rows = [r for r in rows if r["split"] == "holdout"]
    holdout, zero = evaluate(holdout_rows, model), evaluate(holdout_rows, zeroed)
    regressions, regression_manifest = {}, []
    if curriculum == "compound" and not provided_rows:
        notify("known_regression_probes")
        regression_manifest = compound_regressions()  # No earlier content access or rule mining.
        regressions = evaluate(regression_manifest, model)
    if model.to_dict() != frozen:
        raise ValueError("checkpoint changed after freeze")
    gates = {s: canary_gate(before[s], after[s]) for s in ("validation", "canary")}
    gates["holdout"] = canary_gate(zero["holdout"], holdout["holdout"])
    measured = all(g["verified_target_count"] == g["rewrite_sample_count"] == g["sample_count"] and
                   all(r["expression_nonregression"] for r in g["rows"])
                   for g in [*after.values(), *holdout.values()])
    gates["coverage_and_cost"] = {"accepted": measured,
        "reason": None if measured else "unverified_target_missing_edit_labels_or_expression_cost_regression"}
    return {"schema": SCHEMA, "ok": all(g["accepted"] for g in gates.values()),
        "scope": ("caller_supplied_manifest_not_semantically_decontaminated" if provided_rows else
                  "atomic_compound_shared_motifs_known_regressions_separate_not_arena" if curriculum == "compound" else
                  "cross_structure_shared_rewrite_motifs_not_arena_or_unseen_mathematics" if curriculum == "transfer" else
                  "same_family_replay_distillation_not_arena_or_unseen_mathematics"),
        "curriculum": "custom" if provided_rows else curriculum, "fixture_seed": seed,
        "epochs": epochs, "config": cfg.to_dict(), "grammar": grammar, "training_pairs": teachers,
        "before": before, "after": after, "holdout": holdout, "holdout_zero_weights": zero, "gates": gates,
        "known_regressions": regressions, "regression_manifest": regression_manifest,
        "regression_manifest_sha256": digest(regression_manifest),
        "known_regressions_used_for_training_or_gates": False,
        "checkpoint": frozen, "checkpoint_sha256": digest(frozen), "initial_checkpoint": initial,
        "manifest": rows, "manifest_sha256": digest(rows), "events": events, "history": history,
        "compile_attempts": attempts, "compile_calls": len(attempts), "max_compiles": max_compiles, "model_step": model.step,
        "reconstruction_heads_unchanged": True, "sparse_edit_head_trained": True,
        "open_state_encoder_trained": False, "holdout_accessed_after_freeze": True,
        "tuning_allowed_after_holdout": False, "checkpoint_promoted": False, "arena_data_used": False,
        "official_score": None, "dependency_closure_verified": False, "semantic_family_decontamination": False,
        "live_llm_used": False, "nca_trained": False, "jev_updates_used": False, "tokenizer_id": TOKENIZER_ID}


def summarize_rows(rows, *, families=True):
    # Missing teacher metrics must not remove failed rows from denominators or
    # become numeric zero losses. Report measured coverage and gate it explicitly.
    labeled = [r for r in rows if r["loss"] is not None]
    result = _aggregate(labeled)
    result.update(sample_count=len(rows), loss_sample_count=len(labeled), rows=list(rows),
                  verified_target_count=sum(r["teacher_check"]["expression_nonregression"] for r in rows),
                  verified=sum(r["verified"] for r in rows),
                  verifier_success_rate=sum(r["verified"] for r in rows)/len(rows) if rows else None,
                  verifier_evaluated_count=len(rows),
                  verified_shortening=sum(r["verified_shortening"] for r in rows),
                  source_tokens=sum(r["source_tokens"] for r in rows),
                  prediction_tokens=sum(r["prediction_tokens"] for r in rows),
                  verified_saved_tokens=sum(r["source_tokens"]-r["prediction_tokens"] for r in rows if r["verified_shortening"]))
    result.update(compression_sample_count=sum(r["target_kind"] == "compression" for r in rows),
                  preservation_sample_count=sum(r["target_kind"] == "preservation" for r in rows),
                  target_reachable_count=sum(r["target_reachable"] is True for r in rows),
                  identity_only_count=sum(r["applicable_edits"] == 0 for r in rows),
                  applicable_edit_sample_count=sum(r["applicable_edits"] > 0 for r in rows))
    if families:
        result["families"] = {f: summarize_rows([r for r in rows if r["family"] == f], families=False)
                              for f in dict.fromkeys(r["family"] for r in rows)}
    return result


def render_summary(run):
    if (run.get("schema") != SCHEMA or run.get("checkpoint_sha256") != digest(run["checkpoint"])
            or run.get("manifest_sha256") != digest(run["manifest"])
            or ("regression_manifest_sha256" in run and
                run["regression_manifest_sha256"] != digest(run.get("regression_manifest")))
            or ("router_refinement" in run and
                run.get("router_refinement_sha256") != digest(run["router_refinement"]))):
        raise ValueError("invalid experiment receipt")
    lines = ["# Replay-to-edit-head experiment", "", "Generated from saved receipts, not a fresh verification.",
             "Bounded controls sharing rewrite motifs; no arena or mathematical generalization claim.", "",
             "| Measurement | Verified shortening | Operation CE | Edit CE | Expected cosine loss |",
             "| --- | --- | --- | --- | --- |"]
    for label, group in [("Train before", run["before"]["train"]), ("Train after", run["after"]["train"]),
                          ("Holdout trained", run["holdout"]["holdout"]),
                          ("Holdout zero weights", run["holdout_zero_weights"]["holdout"])]:
        fmt = lambda n: "unavailable" if n is None else f"{n:.6g}"
        lines.append(f"| {label} | {group['verified_shortening']}/{group['sample_count']} | "
                     f"{fmt(group['cross_entropy'])} | {fmt(group['rewrite_cross_entropy'])} | "
                     f"{fmt(group['rewrite_expected_cosine_loss'])} |")
    holdout = run["holdout"]["holdout"]
    lines += ["", f"Scope: {run['scope']}. Seed: {run.get('fixture_seed', 'not recorded')}."]
    coverage = ("compression_sample_count", "preservation_sample_count", "identity_only_count",
                "target_reachable_count", "verified_target_count")
    if all(k in holdout for k in coverage):
        lines += [f"Holdout: {holdout['compression_sample_count']} compression targets; "
                  f"{holdout['preservation_sample_count']} preservation controls; "
                  f"{holdout['identity_only_count']} have no applicable edit. "
                  f"Reachable labels: {holdout['target_reachable_count']}/{holdout['sample_count']}.",
                  f"Cost-approved reference targets: {holdout['verified_target_count']}/{holdout['sample_count']}; "
                  "loss means use approved targets only; incomplete coverage fails the experiment."]
    else:
        lines.append("Per-family/target coverage diagnostics unavailable in this legacy receipt.")
    if len(holdout.get("families", {})) > 1:
        lines += ["", "| Holdout family | Valid / total | Cost-safe / total | Verified savings | Applicable edits |",
                  "| --- | --- | --- | --- | --- |"]
        for family, group in sorted(holdout["families"].items()):
            label = family.replace("|", "\\|").replace("\n", " ").replace("\r", " ")
            lines.append(f"| {label} | {group['verified']}/{group['sample_count']} | "
                         f"{sum(r['expression_nonregression'] for r in group['rows'])}/{group['sample_count']} | "
                         f"{group['verified_saved_tokens']} | {sum(r['applicable_edits'] for r in group['rows'])} |")
    regression = run.get("known_regressions", {}).get("regression")
    if regression:
        lines += ["", f"Known regression probes (not fresh holdouts or gate inputs): "
                  f"{regression['verified_shortening']}/{regression['sample_count']} cost-safe shortenings; "
                  f"{regression['verified_saved_tokens']} saved tokens. Previous references are retained in run.json."]
    router = run.get("router_refinement")
    if router:
        lines += ["", f"Router refinement: {router['calls_attempted']} provider calls "
                  f"({router['mode']}); training-only feedback; no evaluation proposals.",
                  "Hypotheses are diagnostics. Only native replay plus whole-proof admission creates teachers."]
    lines += ["", f"Updates: {run['model_step']}; cached compiler calls: {run['compile_calls']}.",
              f"Gates: {json.dumps(run['gates'], sort_keys=True)}.",
              "Only the sparse edit head is trained; reconstruction/latent heads are frozen.",
              "Native replay plus independent whole-proof type, axiom and expression-cost gates select teachers.",
              "Open-state JSON is not a replay checkpoint; native contexts are regenerated from source.",
              "No LLM-weight, JeV or NCA updates; no promotion; dependency closure is not authenticated.", ""]
    return "\n".join(lines)


def save_run(result, output_dir):
    """Code-generated receipt/report; refuses overwrites and invalid summaries."""
    destination = Path(output_dir)
    summary = render_summary(result) if "checkpoint" in result else None
    serialized = json.dumps(result, sort_keys=True, indent=2, allow_nan=False)
    destination.mkdir(parents=True, exist_ok=False)
    with (destination / "run.json").open("x") as stream:
        stream.write(serialized)
    if summary is not None:
        with (destination / "summary.md").open("x") as stream:
            stream.write(summary)
    return destination


def main(argv=None):
    from .router_tuning import _lean_compiler
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("/tmp"))
    parser.add_argument("--lake", action="store_true")
    parser.add_argument("--environment-sha256", required=True)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--curriculum", choices=("control", "transfer", "compound"), default="control")
    parser.add_argument("--seed", type=int, default=20260922)
    parser.add_argument("--max-compiles", type=int, help="default: 128 for compound, 48 otherwise")
    parser.add_argument("--router-refinement-rounds", type=int, choices=range(4), default=0,
                        help="opt-in training-only llm_router feedback rounds (default disabled)")
    parser.add_argument("--router-provider", help="explicit provider required when router refinement is enabled")
    parser.add_argument("--router-model", help="explicit model required when router refinement is enabled")
    parser.add_argument("--max-router-calls", type=int, default=16)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output_dir.exists():
        parser.error("output directory exists; choose a new destination")
    if not 1 <= args.max_router_calls <= 48:
        parser.error("max router calls must be in 1..48")
    if bool(args.router_refinement_rounds) != bool(args.router_provider and args.router_model):
        parser.error("router refinement requires both an explicit provider and model")
    if not args.router_refinement_rounds and (args.router_provider or args.router_model):
        parser.error("router provider/model supplied but refinement is disabled")
    kwargs = dict(project_root=args.project_root.resolve(), use_lake=args.lake,
                  environment_sha256=args.environment_sha256)
    run, router_args = run_experiment, {}
    if args.router_refinement_rounds:
        from .outer import make_llm_router_generate
        from .replay_router import run_router_experiment
        run = run_router_experiment
        router_args = dict(router_generate=make_llm_router_generate(
            provider=args.router_provider, model_name=args.router_model, verify_route=True,
            timeout=45, allow_cross_provider_fallback=False, allow_local_fallback=False),
            router_mode="live_requested", refinement_rounds=args.router_refinement_rounds,
            max_router_calls=args.max_router_calls)
    result = run(capture_fn=partial(capture_source, **kwargs),
        replay_fn=partial(replay_candidate, **kwargs),
        compile_fn=_lean_compiler(**kwargs, kernel_only=True, export_dags=True, timeout=45),
        environment_sha256=args.environment_sha256, epochs=args.epochs, curriculum=args.curriculum,
        seed=args.seed, max_compiles=args.max_compiles,
        event=lambda e: print(json.dumps(e), flush=True), **router_args)
    save_run(result, args.output_dir)
    print(json.dumps({"ok": result["ok"], "output_dir": str(args.output_dir)}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
