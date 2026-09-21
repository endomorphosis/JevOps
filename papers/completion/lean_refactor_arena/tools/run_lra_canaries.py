#!/usr/bin/env python3
"""Few-shot canaries: Leanstral generator + TypeSafe Jev gates + lake/lean oracle.

Not official Track 2. Not an Arena ranking. Jev does not generate Lean.
Never LOCK_EX. Never start llama-server. API keys are never written to receipts.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
HARNESS = PAPER_ROOT / "harness"
LRA_REPO = HERE.parents[4]
ROOT_ACCEL = Path("/home/barberb/lift_coding/external/ipfs_accelerate")
KEYFILE = Path.home() / ".config/ipfs_accelerate_py/typesafe.env"
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
AUTOSTART = "IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART"

FOL_CANARIES = (
    {
        "goal_id": "h.fol_identity",
        "declaration": "theorem recovery_goal (U : Type) (P : U → Prop) : ∀ x, P x → P x",
        "expected_provable": True,
        "expected_solver_status": "unsat",
    },
    {
        "goal_id": "h.fol_protected_write",
        "declaration": (
            "theorem recovery_goal (Protected Approved Write : Prop) : "
            "(Protected ∧ ¬ Approved) → ¬ Write"
        ),
        "expected_provable": False,
        "expected_solver_status": "sat",
    },
)
LRA_CANARIES = (
    "CallElimCorrect.substOldPostSubset",
    "Cslib.CCS.bisimilarity_congr_choice",
)


def load_keyfile() -> None:
    if not KEYFILE.is_file():
        return
    for line in KEYFILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def pin_paths() -> None:
    for path in (HARNESS, LRA_REPO / "external/ipfs_datasets", LRA_REPO / "external/ipfs_accelerate"):
        text = str(path)
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    # Live TypeSafe client lives on origin/main accelerate, not the LRA law pin.
    sys.path.insert(0, str(ROOT_ACCEL))
    import _jevops_path  # noqa: F401

    os.environ[AUTOSTART] = "0"
    os.environ.setdefault("IPFS_ACCEL_SKIP_CORE", "1")
    os.environ.setdefault("IPFS_AUTO_INSTALL", "false")
    os.environ.setdefault("LRA_TYPESAFE", "distill")
    os.environ.setdefault("IPFS_ACCELERATE_LLAMA_CPP_BASE_URL", "http://172.17.0.1:8080/v1")
    import typesafe_router as lra_ts

    lra_ts.ACCEL_ROOT = ROOT_ACCEL
    lra_ts.TYPESAFE_INFERENCE_PATH = ROOT_ACCEL / "ipfs_accelerate_py" / "typesafe_inference.py"


def redact(payload: Any) -> Any:
    if isinstance(payload, Mapping):
        out = {}
        for key, value in payload.items():
            name = str(key).lower()
            if "key" in name or "token" in name and "input_tokens" not in name and "output_tokens" not in name:
                if name in {"input_tokens", "output_tokens", "total_tokens"}:
                    out[key] = redact(value)
                elif isinstance(value, str) and value:
                    out[key] = "[redacted]"
                else:
                    out[key] = redact(value)
            else:
                out[key] = redact(value)
        return out
    if isinstance(payload, list):
        return [redact(item) for item in payload]
    if isinstance(payload, str) and payload.startswith("apikey_"):
        return "[redacted]"
    return payload


def kernel_check_fol(declaration: str, body: str, timeout: float = 30.0) -> dict[str, Any]:
    """Self-contained Lean 4 check. Not a Mathlib/Strata lake oracle."""

    text = declaration.rstrip()
    if not text.endswith(":="):
        text += " :="
    proof = body.strip()
    if proof and not proof.startswith("by"):
        proof = "by\n" + proof
    source = text + " " + proof + "\n"
    started = time.perf_counter()
    lean = Path.home() / ".elan/bin/lean"
    try:
        with tempfile.TemporaryDirectory(prefix="lra-fol-") as tmp:
            path = Path(tmp) / "Canary.lean"
            path.write_text(source, encoding="utf-8")
            proc = subprocess.run(
                [str(lean), str(path)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, AUTOSTART: "0"},
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        from jevops.outer import elapsed_ms, exc_text

        return {
            "ok": False,
            "exit_code": None,
            "error": exc_text(exc),
            "wall_ms": elapsed_ms(started),
            "source_chars": len(source),
        }
    from jevops.outer import elapsed_ms

    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": (proc.stdout or "")[-800:],
        "stderr_tail": (proc.stderr or "")[-800:],
        "wall_ms": elapsed_ms(started),
        "source_chars": len(source),
        "error": "" if proc.returncode == 0 else "lean_nonzero_exit",
    }


def run_fol_canary(spec: Mapping[str, Any]) -> dict[str, Any]:
    from ipfs_accelerate_py.leanstral_typesafe import LeanstralGoal, propose_and_solve

    goal = LeanstralGoal(
        goal_id=str(spec["goal_id"]),
        declaration=str(spec["declaration"]),
        expected_provable=spec.get("expected_provable"),
        expected_solver_status=str(spec.get("expected_solver_status") or ""),
    )
    from jevops.outer import elapsed_ms

    started = time.perf_counter()
    payload = propose_and_solve(
        goal,
        leanstral_base_url="http://172.17.0.1:8080/v1",
        max_tokens=256,
        leanstral_timeout=120.0,
        typesafe_timeout=30.0,
        call_typesafe=True,
    )
    parsed = payload.get("parsed") or {}
    body = str(parsed.get("body") or "")
    kernel = None
    if parsed.get("kind") == "proof_body" and body:
        kernel = kernel_check_fol(goal.declaration, body)
    verdict = payload.get("verdict") or {}
    expected_provable = bool(spec.get("expected_provable"))
    kernel_ok = bool(kernel and kernel.get("ok"))
    match = None
    if expected_provable:
        match = kernel_ok
    elif parsed.get("kind") == "abstain":
        match = True
    elif kernel is not None:
        match = not kernel_ok
    return redact(
        {
            "kind": "fol",
            "goal_id": goal.goal_id,
            "expected_provable": expected_provable,
            "expected_solver_status": spec.get("expected_solver_status"),
            "parsed": parsed,
            "verdict": verdict,
            "kernel": kernel,
            "leanstral_usage": payload.get("leanstral_usage"),
            "leanstral_finish_reason": payload.get("leanstral_finish_reason"),
            "typesafe_skipped": payload.get("typesafe_skipped"),
            "match_expected": match,
            "advisory_only": True,
            "arena_score": None,
            "wall_ms": elapsed_ms(started),
        }
    )


def run_lra_canary(name: str, *, max_new_tokens: int, generate_timeout: float) -> dict[str, Any]:
    import generate_text as lra_gt
    import retrieve as lra_retrieve
    import splice as lra_splice
    import typesafe_router as lra_ts
    import docker0_client as lra_d0
    import run_warmup as lra_loop

    record, records, digest = lra_ts._load_named_record(name)
    neighbors = lra_ts._neighbors_for(record, records)
    state = lra_ts.problem_state(record, neighbors=neighbors)
    started = time.perf_counter()
    route = lra_ts.TypeSafeLraRouter(mode="distill").route(
        state, neighbor_names=[item["name"] for item in neighbors]
    )
    route_dict = route.as_dict()
    jev_wants_llm = None if route.skipped else lra_ts.should_call_leanstral(route_dict, record)
    from jevops.outer import elapsed_ms

    health = lra_d0.probe_docker0_health()
    generation = None
    tactics = ""
    admission = None
    if health.ok:
        retrieval = lra_retrieve.retrieve_record(record, records)
        prompt = lra_loop.render_loop_prompt(record, retrieval)
        generation = lra_loop.maybe_generate(
            prompt,
            health=health,
            source=str(record.get("source") or ""),
            max_new_tokens=max_new_tokens,
            timeout=generate_timeout,
        )
        tactics = lra_loop.extract_generated_tactics(generation.text)
        admission = lra_splice.admission_view(record, tactics).as_dict() if hasattr(
            lra_splice.admission_view(record, tactics), "as_dict"
        ) else None
        if admission is None:
            view = lra_splice.admission_view(record, tactics)
            admission = {
                "accepted": bool(view.accepted),
                "code": str(view.failure_code),
                "reason": str(view.reason),
            }
    candidate_state = lra_ts.problem_state(
        record,
        neighbors=neighbors,
        candidate={"tactics_head": tactics[:400], "n_chars": len(tactics)},
    )
    candidate_gate = None
    if not route.skipped and tactics:
        candidate_gate = lra_ts.TypeSafeLraRouter(mode="distill").route(
            candidate_state, neighbor_names=[item["name"] for item in neighbors]
        ).as_dict()
    gen_payload = None
    if generation is not None:
        gen_payload = {
            "error": generation.error,
            "skipped": generation.skipped,
            "text_head": (generation.text or "")[:400],
            "n_chars": len(generation.text or ""),
            "tactics_head": tactics[:400],
            "n_tactics_chars": len(tactics),
            "identity": generation.identity.__dict__,
        }
    return redact(
        {
            "kind": "lra_warmup",
            "name": name,
            "source": record.get("source"),
            "proof_length": record.get("proof_length"),
            "num_lines": record.get("num_lines"),
            "warmup_jsonl_sha256": digest,
            "health_ok": bool(health.ok),
            "route": route_dict,
            "jev_recommends_llm": jev_wants_llm,
            "called_leanstral": bool(health.ok),
            "generation": gen_payload,
            "admission": admission,
            "candidate_gate": candidate_gate,
            "compile": {
                "attempted": False,
                "reason": "tag-pinned lake/oleans not installed for live Strata/CSLib; FOL kernel is the live oracle on this pass",
            },
            "arena_score": None,
            "official_score": None,
            "jev_generated_lean": False,
            "wall_ms": elapsed_ms(started),
        }
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--generate-timeout", type=float, default=180.0)
    args = parser.parse_args(list(argv) if argv is not None else None)
    load_keyfile()
    pin_paths()
    from ipfs_accelerate_py.typesafe_inference import typesafe_configured
    import docker0_client as lra_d0

    health = lra_d0.probe_docker0_health()
    started = time.perf_counter()
    rows = []
    errors = []
    for spec in FOL_CANARIES:
        try:
            rows.append(run_fol_canary(spec))
        except Exception as exc:  # noqa: BLE001 — retain the canary failure
            from jevops.outer import exc_text

            errors.append({"kind": "fol", "goal_id": spec["goal_id"], "error": exc_text(exc)})
            rows.append({"kind": "fol", "goal_id": spec["goal_id"], "ok": False, "error": exc_text(exc), "arena_score": None})
    for name in LRA_CANARIES:
        try:
            rows.append(run_lra_canary(name, max_new_tokens=args.max_new_tokens, generate_timeout=args.generate_timeout))
        except Exception as exc:  # noqa: BLE001
            from jevops.outer import exc_text

            errors.append({"kind": "lra_warmup", "name": name, "error": exc_text(exc)})
            rows.append({"kind": "lra_warmup", "name": name, "ok": False, "error": exc_text(exc), "arena_score": None})
    fol = [row for row in rows if row.get("kind") == "fol"]
    lra = [row for row in rows if row.get("kind") == "lra_warmup"]
    from jevops.outer import elapsed_ms, print_json, utc_stamp, write_json_pair

    summary = {
        "schema": "lra-canary-run/v1",
        "observed_at": utc_stamp(),
        "leanstral_health_ok": bool(health.ok),
        "typesafe_configured": bool(typesafe_configured()),
        "typesafe_key_in_receipt": False,
        "lock_ex": False,
        "llama_server_started": False,
        "official_track2": False,
        "arena_score": None,
        "n_canaries": len(rows),
        "fol_n": len(fol),
        "fol_kernel_ok": sum(1 for row in fol if (row.get("kernel") or {}).get("ok")),
        "fol_match_expected": sum(1 for row in fol if row.get("match_expected") is True),
        "lra_n": len(lra),
        "lra_admitted": sum(1 for row in lra if (row.get("admission") or {}).get("accepted")),
        "lra_jev_called": sum(1 for row in lra if (row.get("route") or {}).get("called_typesafe")),
        "errors": errors,
        "wall_ms": elapsed_ms(started),
        "canaries": rows,
    }
    summary = redact(summary)
    latest = write_json_pair(
        args.out,
        summary,
        prefix="canary-run",
        latest="latest.json",
        refuse="apikey_",
    )
    print_json({
        "ok": not errors and bool(health.ok) and bool(typesafe_configured()),
        "latest": str(latest),
        "leanstral_health_ok": summary["leanstral_health_ok"],
        "typesafe_configured": summary["typesafe_configured"],
        "fol_match_expected": summary["fol_match_expected"],
        "fol_kernel_ok": summary["fol_kernel_ok"],
        "lra_jev_called": summary["lra_jev_called"],
        "lra_admitted": summary["lra_admitted"],
        "errors": errors,
        "arena_score": None,
    })
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
