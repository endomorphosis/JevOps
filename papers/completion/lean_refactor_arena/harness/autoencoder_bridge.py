#!/usr/bin/env python3
"""Experimental JevOps autoencoder track over the frozen LRA warm-up set.

This module deliberately sits beside, rather than inside, the frozen LRA/v1
loop.  The official warm-up harness keeps TypeSafe and learned scoring off and
uses Lake as its only authority.  This adapter adds the JevOps
text -> Lean IR -> text model and router-guided search for research, but it
does not turn a search result into an Arena score.  Its compiler callback
uses the same theorem-span splice/restore authority as the local Track 1
keep-best benchmark, so the JSONL theorem body is never mistaken for a
standalone Lean file with imports omitted.

The important boundary is the compiler callback: a router winner is only a
training target after the theorem-span Lake gate accepts it without a
theorem-local ``sorry``.
The autoencoder's own CE/cosine diagnostics are retained separately from the
verified target diagnostics, so a short search candidate cannot masquerade as
an emitted model prediction.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _jevops_path  # noqa: E402,F401
import binder_use as lra_bind  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_keepbest as lra_keepbest  # noqa: E402

from jevops.router_tuning import RouterTuningConfig, tune_autoencoder_with_router  # noqa: E402
from jevops.outer import select_limit, select_named  # noqa: E402


BRIDGE_SCHEMA = "jevops-lra-autoencoder-bridge/v1"
PROTOCOL = "LRA/v1"
# Keep the bridge on the exact pinned Lake workspace used by random_canary.
# Passing LRA_STATE_ROOT itself points one directory too high and makes the
# compile worker report a missing cached clone under network=deny.
DEFAULT_STATE_ROOT = _jevops_path.LRA_STATE_ROOT / "track1-lake"


def load_records(path: Optional[Path] = None) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Load the frozen benchmark through the authoritative splice checker."""

    return lra_splice.load_warmup_records(path)


def _candidate_tactics(record: Mapping[str, Any], candidate_source: str) -> Optional[str]:
    """Recover only a body suffix after an exact JSONL statement prefix."""

    statement = str(record.get("statement") or "")
    candidate = str(candidate_source or "")
    if not statement or not candidate.startswith(statement):
        return None
    suffix = candidate[len(statement) :]
    try:
        return lra_splice.tactic_block_from_body(suffix)
    except Exception:
        return None


def compiler_for_record(
    record: Mapping[str, Any],
    *,
    compile_timeout: float = lra_loop.WARMUP_TAG_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "deny",
    skip_checkout: bool = True,
    kernel_only: bool = False,
) -> Callable[..., Mapping[str, Any]]:
    """Build a RouterTuning-compatible compiler backed by the LRA splice oracle."""

    if network not in {"allow", "deny"}:
        raise ValueError("network must be allow or deny")
    if not skip_checkout:
        raise ValueError("splice compilation requires an already pinned checkout")

    resolved_state_root = (
        Path(state_root).expanduser().resolve()
        if state_root is not None
        else DEFAULT_STATE_ROOT
    )

    def compile_candidate(candidate_source: str, problem: str = "") -> dict[str, Any]:
        del problem
        tactics = _candidate_tactics(record, candidate_source)
        if tactics is None:
            return {
                "theorem_ok": False,
                "lake_ok": False,
                "reason": "statement_prefix_mismatch",
                "token_count": lra_loop.token_count(str(candidate_source or "")),
            }
        try:
            # The warm-up JSONL stores the frozen theorem body, not module
            # imports. Track1 keep-best replaces only that body inside the
            # checked-out source file, compiles it with Lake, and restores the
            # file. Feeding theorem-only text to run_warmup.compile_tactics
            # would erase imports and produce false failures.
            restore = b""  # Putnam compiles a generated module, not a Git splice.
            if str(record.get("source") or "") != "putnambench":
                clone = lra_keepbest.lra_cw.clone_dir(str(record.get("url") or ""), resolved_state_root)
                relpath = str(lra_keepbest.lra_cw.source_relpath(record))
                dest = clone / relpath
                if not dest.is_file():
                    return {"theorem_ok": False, "lake_ok": False, "reason": "cached_source_missing",
                            "token_count": lra_loop.token_count(tactics)}
                restore = dest.read_bytes()
                original = subprocess.run(
                    ["git", "-C", str(clone), "show", f"HEAD:{relpath}"],
                    capture_output=True, check=False,
                )
                # Never silently overwrite another run's or a user's edits.
                if original.returncode != 0 or original.stdout != restore:
                    return {"theorem_ok": False, "lake_ok": False, "reason": "cached_source_modified",
                            "token_count": lra_loop.token_count(tactics)}
            result = lra_keepbest.compile_tactics(
                record,
                tactics,
                state_root=resolved_state_root,
                timeout=compile_timeout,
                restore=restore,
                network=network,
                elan_home=elan_home,
                kernel_only=kernel_only,
            )
            # ``sorryAx`` may occur elsewhere in a large source module; the
            # benchmark's theorem-span gate is the default local authority.
            # kernel_only additionally requires the target's transitive axiom
            # audit; compile_tactics folds its decision into theorem_ok.
            # Preserve both values for auditability.
            tags_ok = bool(result.get("theorem_ok")) and not bool(
                result.get("sorry_in_theorem")
            )
            return {
                "theorem_ok": bool(tags_ok),
                "lake_ok": bool(tags_ok),
                "token_count": int(
                    result.get("token_count") or lra_loop.token_count(tactics)
                ),
                "body_tokens": lra_loop.token_count(tactics),
                "compile_receipts": [dict(result)],
                "all_tags_ok": bool(tags_ok),
                "all_requested_tags_ok": bool(result.get("all_requested_tags_ok")),
                "selected_version_info": result.get("selected_version_info", []),
                "sorryAx": bool(result.get("sorryAx")),
                "sorry_in_theorem": bool(result.get("sorry_in_theorem")),
                "compile": dict(result),
                "kernel_audit": result.get("kernel_audit"),
                "kernel_only": kernel_only,
            }
        except Exception as exc:  # compile failures are retained, never rewarded
            return {
                "theorem_ok": False,
                "lake_ok": False,
                "token_count": lra_loop.token_count(tactics),
                "reason": type(exc).__name__,
                "error": str(exc)[:400],
                "compile_receipts": [],
            }

    return compile_candidate


def _initial_memory(memory: Optional[MutableMapping[str, Any]]) -> MutableMapping[str, Any]:
    if memory is not None:
        return memory
    return {"nca": {"grid": {}, "board_edges": []}}


def _bind_result(record: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    best_source = result.get("best_source")
    bound = isinstance(best_source, str) and best_source.startswith(
        str(record.get("statement") or "")
    )
    out = dict(result)
    out["benchmark"] = {
        "name": str(record.get("name") or ""),
        "source": str(record.get("source") or ""),
        "statement_prefix_bound": bound,
        "statement_chars": len(str(record.get("statement") or "")),
        "version_tags": [
            item.to_dict()
            for item in lra_loop.lra_cw.iter_version_pins(record.get("version_info"))
        ],
        "official_score": None,
        "arena_score": None,
    }
    # A learned/search result must never be presented as accepted if it lost
    # the frozen statement bind, even if a test compiler returned true.
    if not bound:
        out["ok"] = False
        out["admission"] = "statement_prefix_mismatch"
    return out


def run_record(
    record: Mapping[str, Any],
    *,
    memory: Optional[MutableMapping[str, Any]] = None,
    config: Optional[RouterTuningConfig] = None,
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    router_generate: Optional[Callable[[str], Any]] = None,
    router: Any = None,
    seed_candidates: Optional[Sequence[Any]] = None,
    design_hint: Optional[Mapping[str, Any]] = None,
    compile_timeout: float = lra_loop.WARMUP_TAG_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "deny",
    skip_checkout: bool = True,
) -> dict[str, Any]:
    """Tune one frozen record with verified-target/model-loss separation."""

    working_memory = _initial_memory(memory)
    compiler = compile_fn or compiler_for_record(
        record,
        compile_timeout=compile_timeout,
        state_root=state_root,
        elan_home=elan_home,
        network=network,
        skip_checkout=skip_checkout,
    )
    result = tune_autoencoder_with_router(
        working_memory,
        str(record.get("src") or ""),
        problem=str(record.get("name") or ""),
        compile_fn=compiler,
        config=config,
        router_generate=router_generate,
        router=router,
        seed_candidates=seed_candidates,
        design_hint=design_hint,
    )
    return _bind_result(record, result)


def run_benchmark(
    *,
    jsonl: Optional[Path] = None,
    names: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
    memory: Optional[MutableMapping[str, Any]] = None,
    config: Optional[RouterTuningConfig] = None,
    compile_fn_factory: Optional[Callable[[Mapping[str, Any]], Callable[..., Mapping[str, Any]]]] = None,
    router_generate: Optional[Callable[[str], Any]] = None,
    router: Any = None,
    seed_candidates: Optional[Sequence[Any]] = None,
    seed_history: bool = False,
    design_hint: Optional[Mapping[str, Any]] = None,
    compile_timeout: float = lra_loop.WARMUP_TAG_TIMEOUT_SECONDS,
    state_root: Optional[Path] = None,
    elan_home: Optional[Path] = None,
    network: str = "deny",
    skip_checkout: bool = True,
) -> dict[str, Any]:
    """Run the experimental adapter over selected frozen benchmark records."""

    raw, digest, records = load_records(jsonl)
    selected = select_limit(
        select_named(
            records,
            names,
            error_cls=lra_loop.LoopError,
            miss_fmt="unknown warm-up names: {missing}",
        ),
        limit,
    )
    working_memory = _initial_memory(memory)
    results: list[dict[str, Any]] = []
    for record in selected:
        injected = compile_fn_factory(record) if compile_fn_factory is not None else None
        record_seeds: list[Any] = list(seed_candidates or ())
        if seed_history:
            try:
                from historical_seeds import load_historical_seeds

                record_seeds = [
                    *load_historical_seeds(
                        str(record.get("name") or ""),
                        token_fn=lra_loop.token_count,
                    ),
                    *record_seeds,
                ]
            except Exception:
                pass
        results.append(
            run_record(
                record,
                memory=working_memory,
                config=config,
                compile_fn=injected,
                router_generate=router_generate,
                router=router,
                seed_candidates=record_seeds,
                design_hint=design_hint,
                compile_timeout=compile_timeout,
                state_root=state_root,
                elan_home=elan_home,
                network=network,
                skip_checkout=skip_checkout,
            )
        )
    verified = [row for row in results if row.get("ok") and row.get("benchmark", {}).get("statement_prefix_bound")]
    model_rows = [row for row in results if row.get("model_body_tokens_after") is not None]
    losses = [row.get("model_loss_after") or {} for row in results]
    ce = [float(item.get("cross_entropy")) for item in losses if item.get("cross_entropy") is not None]
    cosine = [float(item.get("cosine_similarity")) for item in losses if item.get("cosine_similarity") is not None]
    return {
        "schema": BRIDGE_SCHEMA,
        "protocol": PROTOCOL,
        "experimental": True,
        "official_v1_compatible": False,
        "frozen_warmup_sha256": digest,
        "jsonl_bytes": len(raw),
        "n_selected": len(selected),
        "n_results": len(results),
        "historical_seed_enabled": bool(seed_history),
        "historical_seeded_results": sum(
            1
            for row in results
            if any(
                str(candidate.get("seed_provenance") or "") == "git_history"
                for history in row.get("history") or ()
                for candidate in history.get("candidates") or ()
                if isinstance(candidate, Mapping)
            )
        ),
        "n_verified": len(verified),
        "source_body_tokens_total": sum(int(row.get("source_body_tokens") or 0) for row in results),
        "best_body_tokens_total": sum(int(row.get("best_body_tokens") or 0) for row in verified),
        "model_body_tokens_after_total": sum(int(row.get("model_body_tokens_after") or 0) for row in model_rows),
        "mean_model_cross_entropy": (sum(ce) / len(ce)) if ce else None,
        "mean_model_cosine_similarity": (sum(cosine) / len(cosine)) if cosine else None,
        "reward_hacking_checks": {
            "statement_prefix_bound_for_verified": all(
                bool(row.get("benchmark", {}).get("statement_prefix_bound")) for row in verified
            ),
            "model_loss_is_separate_from_candidate_target": all(
                all(
                    key in (history.get("training") or {})
                    for key in ("loss", "candidate_target_loss")
                )
                for row in results
                for history in row.get("history") or ()
                if history.get("training", {}).get("trained")
            ),
            "official_scores_null": all(
                row.get("benchmark", {}).get("arena_score") is None
                and row.get("benchmark", {}).get("official_score") is None
                for row in results
            ),
        },
        "results": results,
        "memory": working_memory,
        "arena_score": None,
        "official_score": None,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jsonl", type=Path, default=None)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--no-train", action="store_true")
    parser.add_argument(
        "--memory-path",
        type=Path,
        default=None,
        help="persist the autoencoder/NCA state outside the curated benchmark tree",
    )
    parser.add_argument(
        "--teacher",
        type=Path,
        action="append",
        default=[],
        help="verified tactic-body file(s) to re-admit as teacher candidates",
    )
    parser.add_argument(
        "--seed-history",
        action="store_true",
        help="read shortest bodies from the pinned lift_coding Git history as untrusted teacher proposals",
    )
    parser.add_argument("--plan", action="store_true", help="print the frozen benchmark plan")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.plan:
        print(json.dumps(lra_loop.plan_loop(args.jsonl), indent=2, sort_keys=True))
        return 0
    config = RouterTuningConfig(rounds=args.rounds, train=not args.no_train)
    teachers = [path.read_text(encoding="utf-8") for path in args.teacher]
    memory = lra_bind.load_memory(args.memory_path) if args.memory_path else None
    result = run_benchmark(
        jsonl=args.jsonl,
        names=args.name or None,
        limit=args.limit,
        config=config,
        seed_candidates=teachers,
        seed_history=args.seed_history,
        memory=memory,
    )
    if args.memory_path:
        result["memory_path"] = str(lra_bind.save_memory(result["memory"], args.memory_path))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["reward_hacking_checks"]["official_scores_null"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
