#!/usr/bin/env python3
"""Track 1 keep-best: splice hosted/fan-out tactics into Strata and lake-compile.

Local docker0 is not used. Candidates come from Mistral Labs receipts or
deterministic draft fan-out. Lake on tag-pinned v4.26.0 is the oracle.
Not official Track 2. Not an Arena ranking.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

HERE = Path(__file__).resolve().parent
PAPER_ROOT = HERE.parent
OUT_DEFAULT = PAPER_ROOT / "evidence" / "canaries"
CANARY_NAME = "CallElimCorrect.substOldPostSubset"
HARDWARE_CLASS = "mistral_labs_api"
PROTOTYPE_HARDWARE = "spark_gb10"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import _jevops_path  # noqa: E402,F401
import compile_worker as lra_cw  # noqa: E402
import draft_fanout as lra_fan  # noqa: E402
import run_warmup as lra_loop  # noqa: E402
import splice as lra_splice  # noqa: E402
import track1_ledger as lra_t1  # noqa: E402
import track1_mistral_leanstral as lra_mistral  # noqa: E402

DEFAULT_STATE = _jevops_path.LRA_STATE_ROOT / "track1-lake"

FROZEN_WARMUP_SHA256 = lra_splice.FROZEN_WARMUP_SHA256


def installed_matching_pins(record: Mapping[str, Any], clone: Path) -> list[dict[str, str]]:
    """Keep version_info rows whose elan tag is installed and commit matches the clone."""

    from jevops.lean import filter_installed_pin_maps
    from jevops.outer import git_head

    head = git_head(clone) if (clone / ".git").exists() else ""
    return filter_installed_pin_maps(
        lra_cw.iter_version_pins(record.get("version_info")),
        resolve_fn=lambda pin: lra_cw.resolve_pin(pin, require_installed=True),
        head=head,
    )


def splice_src(path: Path, original_src: str, replacement: str) -> None:
    """Replace the frozen JSONL ``src`` substring. Does not search for ``:=``."""

    from jevops.outer import replace_once

    replace_once(
        path,
        original_src,
        replacement,
        error_cls=RuntimeError,
        miss="{path}: frozen src is not a substring of the lake file",
    )


def candidate_source(record: Mapping[str, Any], tactics: str) -> str:
    split = lra_splice.split_statement_body(record)
    return lra_splice.lake_candidate_source(
        header="",
        statement=split.statement,
        tactic_block=tactics,
    )


def compile_tactics(
    record: Mapping[str, Any],
    tactics: str,
    *,
    state_root: Path,
    timeout: float,
    restore: bytes,
) -> dict[str, Any]:
    from jevops.lean import compile_closed, compile_keepbest, pack_compile_view, splice_span
    from jevops.outer import elapsed_ms, head_seq, tail_chars

    clone = lra_cw.clone_dir(str(record.get("url") or ""), state_root)

    def _pins(rec: Mapping[str, Any]) -> list[Any]:
        if str(rec.get("source") or "") == "putnambench":
            from jevops.lean import filter_installed_pin_maps

            return filter_installed_pin_maps(
                lra_cw.iter_version_pins(rec.get("version_info")),
                resolve_fn=lambda pin: lra_cw.resolve_pin(pin, require_installed=True),
            )
        return installed_matching_pins(rec, clone)

    def _compile(rec: Mapping[str, Any]) -> list[Any]:
        return lra_cw.compile_record(
            rec,
            timeout=timeout,
            state_root=state_root,
            network="allow",
            require_oleans=False,
            hardware_class=HARDWARE_CLASS,
            skip_checkout=True,
            abort_on_first_failure=True,
        )

    def _extra(
        receipt: Mapping[str, Any],
        rec: Mapping[str, Any],
        start_line: int,
        end_line: int,
        stdout: str,
        errors_in: Sequence[Mapping[str, Any]],
        errors_out: Sequence[Mapping[str, Any]],
        wall: float,
    ) -> dict[str, Any]:
        pin = lra_cw.iter_version_pins(rec.get("version_info"))[0]
        return {
            "error": receipt.get("error") or receipt.get("stderr_digest"),
            "lean_tag": pin.lean_tag,
            "theorem_span": [start_line, end_line],
            "argv": receipt.get("argv"),
            "compile_wall_ms_outer": wall,
            "stdout_tail": tail_chars(stdout, 400) if stdout else None,
            "stderr_tail": tail_chars(receipt.get("stderr"), 400)
            if isinstance(receipt.get("stderr"), str)
            else None,
            "errors": errors_in or head_seq(errors_out, 6),
        }

    from jevops.lean import patch_putnam_src

    return compile_keepbest(
        record,
        tactics,
        putnam_source="putnambench",
        token_fn=lra_loop.token_count,
        closed_fn=compile_closed,
        pins_fn=_pins,
        compile_fn=_compile,
        parse_errors_fn=parse_lean_errors,
        sorry_fn=sorry_in_span,
        pack_fn=pack_compile_view,
        elapsed_fn=elapsed_ms,
        now_fn=time.perf_counter,
        patch_fn=patch_putnam_src,
        statement_fn=lambda rec: lra_splice.split_statement_body(rec).statement,
        dest_fn=lambda rec: clone / lra_cw.source_relpath(rec),
        restore=restore,
        write_bytes_fn=lambda dest, data: Path(dest).write_bytes(data),
        candidate_source_fn=candidate_source,
        splice_fn=splice_src,
        span_fn=splice_span,
        line_in_span_fn=_line_in_span,
        extra_fn=_extra,
    )


def _line_in_span(pos: Any, start_line: int, end_line: int) -> bool:
    from jevops.outer import mapping_line_in_span

    return mapping_line_in_span(pos, start_line, end_line)


def sorry_in_span(stdout: str, start_line: int, end_line: int) -> bool:
    from jevops.outer import jsonl_pred_in_span

    def _pred(payload: Mapping[str, Any]) -> bool:
        if payload.get("kind") != "hasSorry" and "sorry" not in str(payload.get("data") or "").lower():
            return False
        return payload.get("severity") in {"warning", "error", None}

    return jsonl_pred_in_span(stdout, pred=_pred, start_line=start_line, end_line=end_line)


def parse_lean_errors(stdout: str) -> list[dict[str, Any]]:
    from jevops.repair import parse_jsonl_errors

    return parse_jsonl_errors(stdout)


def flatten_overindent(reference: str, tactics: str) -> str:
    """If hosted ``case`` lines are deeper than the reference, strip the extra indent."""

    from jevops.repair import flatten_overindent as _fn

    return _fn(reference, tactics, header_fn=lambda s: s.startswith("case ") and "=>" in s)


def repair_prompt(record: Mapping[str, Any], *, failed: str, errors: Sequence[Mapping[str, Any]], reference: str) -> str:
    from jevops.tactics import repair_prompt as _fn

    return _fn(record, failed=failed, errors=errors, reference=reference)


def match_reference_indent(reference: str, tactics: str) -> str:
    from jevops.repair import match_leading_indent

    return match_leading_indent(reference, tactics)


def hosted_tactics(path: Path) -> str:
    from jevops.lean import hosted_tactics_from_payload
    from jevops.outer import read_json

    return hosted_tactics_from_payload(
        read_json(path),
        extract_fn=lra_loop.extract_generated_tactics,
        error_cls=RuntimeError,
    )


def _row(item: Mapping[str, Any], compile_row: Mapping[str, Any]) -> dict[str, Any]:
    from jevops.outer import merge_head_row

    return merge_head_row(item, compile_row)


def keepbest(
    *,
    name: str,
    hosted_path: Optional[Path],
    state_root: Path,
    timeout: float,
    repair: bool = False,
) -> dict[str, Any]:
    from jevops.outer import lookup_named

    _raw, digest, records = lra_splice.load_warmup_records()
    record = lookup_named(
        records, name, error_cls=RuntimeError, miss=f"unknown warm-up problem: {name}"
    )
    clone = lra_cw.require_clone(str(record["url"]), network="allow", state_root=state_root)
    rel = lra_cw.source_relpath(record)
    dest = clone / rel
    if not dest.is_file():
        raise RuntimeError(f"missing {dest}; clone/checkout Strata first")
    restore = dest.read_bytes()
    ref_tactics = lra_splice.tactic_block_from_body(lra_splice.split_statement_body(record).body_suffix)
    drafts = lra_fan.enumerate_drafts(record, records)
    from jevops.outer import first_where
    from jevops.search import keepbest_payload, pick_min_tiers, run_keepbest

    collapse = first_where(drafts, lambda item: "collapse_simp_at" in item.ops)
    hosted = None
    flattened = None
    if hosted_path is not None and hosted_path.is_file():
        hosted = match_reference_indent(ref_tactics, hosted_tactics(hosted_path))
        flattened = flatten_overindent(ref_tactics, hosted)

    def _repair(
        rows: Sequence[Mapping[str, Any]],
        tactics_by_kind: Mapping[str, str],
        hosted_row: Mapping[str, Any],
    ) -> Optional[Mapping[str, Any]]:
        lra_mistral.load_keyfiles()
        lra_mistral.pin_paths()
        indent_row = next((row for row in rows if row.get("kind") == "hosted_indent_normalized"), None)
        failed = tactics_by_kind.get("hosted_indent_normalized") or tactics_by_kind["hosted_mistral"]
        errors = (hosted_row.get("errors") if hosted_row else None) or []
        if indent_row and indent_row.get("module_exit_0"):
            errors = [
                {
                    "pos": None,
                    "data": (
                        "The indent-normalized draft compiles but is not shorter than the "
                        "reference. Return a strictly shorter tactic block that still compiles."
                    ),
                }
            ]
        prompt = repair_prompt(record, failed=failed, errors=errors, reference=ref_tactics)
        ledger = lra_t1.ProblemLedger(name=f"{name}#repair")
        text, repair_identity, _line = lra_mistral.generate_mistral(
            prompt,
            ledger,
            max_new_tokens=1400,
            timeout=180.0,
        )
        repaired_tactics = flatten_overindent(
            ref_tactics,
            match_reference_indent(ref_tactics, lra_loop.extract_generated_tactics(text)),
        )
        compile_row = compile_tactics(
            record,
            repaired_tactics,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
        )
        return _row(
            {
                "kind": "hosted_mistral_repair",
                "generator": "labs-leanstral-1-5",
                "tactics": repaired_tactics,
                "ledger": ledger.as_dict(),
                "repair_identity": repair_identity,
            },
            compile_row,
        )

    return run_keepbest(
        name=name,
        digest=digest,
        ref_tactics=ref_tactics,
        hosted=hosted,
        flattened=flattened,
        collapse=None if collapse is None else collapse.tactics,
        span_drafts=lra_fan.span_preserving_drafts(ref_tactics),
        compile_fn=lambda body: compile_tactics(
            record,
            body,
            state_root=state_root,
            timeout=timeout,
            restore=restore,
        ),
        row_fn=_row,
        token_fn=lra_loop.token_count,
        repair=repair,
        repair_fn=_repair,
        pick_fn=pick_min_tiers,
        first_where_fn=first_where,
        pack_fn=keepbest_payload,
        clone=clone,
        rel=rel,
        hosted_path=hosted_path,
        hardware_class=HARDWARE_CLASS,
        prototype_hardware=PROTOTYPE_HARDWARE,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=CANARY_NAME)
    parser.add_argument("--names", default="", help="comma-separated warmup names; overrides --name")
    parser.add_argument("--hosted", type=Path, default=OUT_DEFAULT / "track1-mistral-latest.json")
    parser.add_argument("--no-hosted", action="store_true")
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--repair", action="store_true", help="one hosted Labs repair if drafts fail lake")
    parser.add_argument("--out", type=Path, default=OUT_DEFAULT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from jevops.outer import pin_env

    pin_env({"IPFS_ACCELERATE_LLAMA_CPP_AUTOSTART": "0"}, overwrite=False)
    from jevops.outer import split_csv

    names = split_csv(args.names) or [args.name]
    hosted = None if args.no_hosted else args.hosted
    reports = []
    for name in names:
        use_hosted = hosted if (hosted is not None and name == CANARY_NAME) else None
        reports.append(
            keepbest(
                name=name,
                hosted_path=use_hosted,
                state_root=args.state_root,
                timeout=args.timeout,
                repair=args.repair and use_hosted is not None,
            )
        )
    from jevops.outer import field_of, first_where, path_safe, print_json, utc_stamp, write_json, write_json_pair

    if len(reports) == 1:
        report = reports[0]
        latest = write_json_pair(
            args.out,
            report,
            prefix="track1-keepbest",
            latest="track1-keepbest-latest.json",
        )
        print_json({
            "ok": any(row.get("ok") for row in report.get("candidates") or []),
            "latest": str(latest),
            "kept": report.get("kept"),
            "n_valid": report.get("n_valid"),
            "repaired": report.get("repaired"),
            "candidates": [
                {
                    "kind": row.get("kind"),
                    "ok": row.get("ok"),
                    "theorem_ok": row.get("theorem_ok"),
                    "module_exit_0": row.get("module_exit_0"),
                    "tokens": row.get("token_count"),
                    "exit": row.get("exit_code"),
                    "errors": row.get("errors"),
                }
                for row in report.get("candidates") or []
            ],
            "arena_score": None,
        })
        return 0
    summary = {
        "schema": "lra-track1-keepbest-batch/v1",
        "observed_at": utc_stamp(),
        "arena_score": None,
        "called_docker0": False,
        "problems": [
            {
                "name": item.get("name"),
                "kept": item.get("kept"),
                "n_valid": item.get("n_valid"),
                "ref_tokens": field_of(
                    first_where(item.get("candidates") or [], lambda row: row.get("kind") == "reference"),
                    "token_count",
                    default=None,
                ),
            }
            for item in reports
        ],
    }
    latest = write_json_pair(
        args.out,
        summary,
        prefix="track1-keepbest-batch",
        latest="track1-keepbest-batch-latest.json",
    )
    for item in reports:
        write_json(args.out / f"track1-keepbest-{path_safe(item.get('name'))}.json", item)
    print_json({"ok": True, "latest": str(latest), "summary": summary["problems"], "arena_score": None})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
