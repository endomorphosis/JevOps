#!/usr/bin/env python3
"""Experimental JevOps autoencoder track over the frozen LRA warm-up set.

This module deliberately sits beside, rather than inside, the frozen LRA/v1
loop.  The official warm-up harness keeps TypeSafe and learned scoring off and
uses Lake as its only authority.  This adapter adds the JevOps
text -> Lean IR -> text model and router-guided search for research, but it
does not turn a search result into an Arena score.

The important boundary is the compiler callback: a router winner is only a
training target after every listed version pin compiles without ``sorryAx``.
The autoencoder's own CE/cosine diagnostics are retained separately from the
verified target diagnostics, so a short search candidate cannot masquerade as
an emitted model prediction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
REPO_ROOT = HERE.parents[3]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _jevops_path  # noqa: E402,F401
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402

from jevops.router_tuning import RouterTuningConfig, tune_autoencoder_with_router  # noqa: E402
from jevops.outer import select_limit, select_named  # noqa: E402


BRIDGE_SCHEMA = "jevops-lra-autoencoder-bridge/v1"
PROTOCOL = "LRA/v1"


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
) -> Callable[..., Mapping[str, Any]]:
    """Build a RouterTuning-compatible compiler backed by all LRA pins."""

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
            receipts = lra_loop.compile_tactics(
                record,
                tactics,
                timeout=compile_timeout,
                state_root=state_root,
                elan_home=elan_home,
                network=network,
                skip_checkout=skip_checkout,
            )
            tags_ok = lra_loop._all_tags_ok(record, receipts)
            return {
                "theorem_ok": bool(tags_ok),
                "lake_ok": bool(tags_ok),
                "token_count": lra_loop.token_count(tactics),
                "body_tokens": lra_loop.token_count(tactics),
                "compile_receipts": [item.to_dict() for item in receipts],
                "all_tags_ok": bool(tags_ok),
                "sorryAx": any(bool(item.sorryAx) for item in receipts),
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
        results.append(
            run_record(
                record,
                memory=working_memory,
                config=config,
                compile_fn=injected,
                router_generate=router_generate,
                router=router,
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
    parser.add_argument("--plan", action="store_true", help="print the frozen benchmark plan")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.plan:
        print(json.dumps(lra_loop.plan_loop(args.jsonl), indent=2, sort_keys=True))
        return 0
    config = RouterTuningConfig(rounds=args.rounds, train=not args.no_train)
    result = run_benchmark(
        jsonl=args.jsonl,
        names=args.name or None,
        limit=args.limit,
        config=config,
    )
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["reward_hacking_checks"]["official_scores_null"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
