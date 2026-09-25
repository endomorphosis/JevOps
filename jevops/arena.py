"""Opt-in, offline-capable Arena measurement and selection boundary.

The scorer follows the vendored Space's 2026-09-20 leaderboard arithmetic.
The tokenizer agrees with all 15 published references; worker parity remains
unconfirmed. Neither a content hash nor a fixture receipt is a Lean proof.
Only the explicitly injected verifier supplies authoritative observations.
No provider, subprocess, global hook, or network access is used here.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Callable, Mapping, Sequence

from .lean import VersionPin
from .proof_ca import canonical_json
from .proof_trust import STANDARD_AXIOMS, audit_axioms

SCHEMA = "jevops-arena-evaluation/v1"
SCORING_ID = "lra-space-6a1384b-three-axis/v1"
TOKENIZER_ID = "lra-reference-lexical/v1"


def content_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _units(value: int, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return value


def _text(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")


def strip_comments(source: str) -> str:
    """Nested comments, strings and quoted identifiers; not a full Lean parser."""
    out, index, depth = [], 0, 0
    while index < len(source):
        if depth:
            if source.startswith("/-", index):
                depth += 1
                index += 2
            elif source.startswith("-/", index):
                depth -= 1
                index += 2
            else:
                if source[index] == "\n":
                    out.append("\n")
                index += 1
        elif source[index] in {'"', '«'}:
            closing = '"' if source[index] == '"' else '»'
            out.append(source[index])
            index += 1
            while index < len(source):
                char = source[index]
                out.append(char)
                index += 1
                if char == "\\" and closing == '"' and index < len(source):
                    out.append(source[index])
                    index += 1
                elif char == closing:
                    break
            else:
                raise ValueError("unterminated string or quoted identifier")
        elif source.startswith("/-", index):
            depth = 1
            out.append(" ")
            index += 2
        elif source.startswith("--", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
        else:
            out.append(source[index])
            index += 1
    if depth:
        raise ValueError("unterminated comment")
    return "".join(out)


def proof_suffix(source: str, statement: str) -> str:
    """Bind the known declaration boundary, including statements with inner :=."""
    _text(statement, "statement")
    if not isinstance(source, str) or not source.startswith(statement):
        raise ValueError("statement prefix mismatch")
    suffix = strip_comments(source[len(statement):]).lstrip()
    if not suffix.startswith(":=") or not suffix[2:].strip():
        raise ValueError("proof must follow the exact statement with :=")
    return suffix[2:]


def reference_tokens(source: str, statement: str) -> int:
    """Reference-compatible lexical count, including `by`, excluding comments.

    Conventions were cross-checked with upstream lean_refactor/utils.py:
    qualified names stay together, and multi-character operators count once.
    Safer comment/boundary handling is intentional; not a worker attestation.
    """
    operators = (":=", "!=", "&&", "-.", "->", "←", "..", "...", "::", ":>",
                 "<;>", ";;", "==", "||", "=>", "<=", ">=", "⁻¹", "?_")
    total = 0
    for line in proof_suffix(source, statement).strip().splitlines():
        if not line.strip():
            continue
        tokens, word = [], ""
        for char in line:
            if char.isalnum() or char in "._'":
                word += char
                continue
            if word:
                tokens.append(word)
                word = ""
            if char != " ":
                tokens.append(char)
        if word:
            tokens.append(word)
        separated = " ".join(tokens)
        for operator in operators:
            separated = separated.replace(" ".join(operator), operator)
        total += len(separated.split(" "))
    return total


def intake_error(source: str, statement: str) -> str | None:
    """Conservative local subset of Arena intake. This is not an OS sandbox."""
    if len(source.encode()) > 256 * 1024:
        return "source_byte_limit"
    try:
        body = proof_suffix(source, statement)
        clean = strip_comments(source)
    except ValueError as exc:
        return str(exc)
    forbidden = (r"#\s*(?:eval|reduce|exit|count_heartbeats)\b|\bIO\.",
                 r"\b(?:unsafe|extern|initialize|implemented_by|implementedBy|sorry|sorryAx|admit|axiom|"
                 r"native_decide|ofReduceBool|ofReduceNat|run_cmd|run_elab|macro|macro_rules|"
                 r"elab|elab_rules|notation|syntax)\b", r"\bderiving\s+instance\b",
                 r"(?m)^\s*(?:attribute|def|abbrev|instance|structure|inductive|class|opaque)\b")
    if any(re.search(pattern, clean) for pattern in forbidden):
        return "forbidden_source"
    # No auxiliary declarations, options, imports or diagnostic commands in edits.
    # Mathlib uses #(s) for finite-set cardinality, including in the frozen
    # ArkLib reference. It is not a diagnostic command. Keep other hash syntax
    # conservative; the native parser/checker remains the admission boundary.
    if re.search(r"\b(?:theorem|lemma|import|namespace|section|set_option)\b|#(?!\s*\()", body):
        return "unsupported_proof_envelope"
    return None


@dataclass(frozen=True)
class Score:
    length_reduction_pct: float
    heartbeat_reduction_pct: float
    compatibility_pct: float
    combined_pct: float

    def __post_init__(self):
        values = asdict(self).values()
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError("score must contain finite numbers")
        if self.length_reduction_pct > 100 or self.heartbeat_reduction_pct > 100 or not 0 <= self.compatibility_pct <= 100:
            raise ValueError("score axis out of range")


def score_metrics(*, reference_length: int, reference_heartbeats: int | None,
                  length: int, heartbeats: int | None, passed: int, total: int,
                  compiled: bool = True) -> Score:
    """Pure arithmetic, not evidence admission. Inputs must already be checked."""
    for name, value in (("reference_length", reference_length), ("length", length),
                        ("passed", passed), ("total", total)):
        _units(value, name)
    for name, value in (("reference_heartbeats", reference_heartbeats), ("heartbeats", heartbeats)):
        if value is not None:
            _units(value, name)
    if type(compiled) is not bool or total == 0 or passed > total:
        raise ValueError("invalid compile or compatibility dimensions")
    if not compiled:
        return Score(0.0, 0.0, 0.0, 0.0)
    length_pct = round((reference_length - length) / reference_length * 100, 2) if reference_length else 0.0
    heartbeat_pct = (round((reference_heartbeats - heartbeats) / reference_heartbeats * 100, 2)
                     if reference_heartbeats and heartbeats is not None else 0.0)
    compatibility = passed / total * 100
    return Score(length_pct, heartbeat_pct, compatibility,
                 round((length_pct + heartbeat_pct + compatibility) / 3, 2))


def aggregate_scores(names: Sequence[str], results: Mapping[str, Score | None]) -> dict:
    """Missing submissions count as zero; unknown measurements keep score null.

    Deliberately mirrors the pinned leaderboard's one-decimal compatibility
    rounding *before* computing the aggregate combined score.
    """
    if not names or len(set(names)) != len(names) or set(results) - set(names):
        raise ValueError("nonempty unique benchmark names required")
    if any(value is None for value in results.values()):
        return {"status": "INCOMPLETE", "local_combined_pct": None, "num_benchmark": len(names)}
    rows = [results.get(name, Score(0.0, 0.0, 0.0, 0.0)) for name in names]
    length = sum(row.length_reduction_pct for row in rows) / len(names)
    heartbeat = sum(row.heartbeat_reduction_pct for row in rows) / len(names)
    compatibility = round(sum(row.compatibility_pct for row in rows) / len(names), 1)
    return {"status": "MEASURED", "local_combined_pct": round((length + heartbeat + compatibility) / 3, 2),
            "avg_length_reduction_pct": round(length, 2), "avg_heartbeat_reduction_pct": round(heartbeat, 2),
            "avg_compatibility_pct": compatibility, "num_benchmark": len(names)}


class Outcome(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    UNAVAILABLE = "UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class ArenaContext:
    """One immutable problem/environment/measurement epoch. No tick identity."""
    problem: str
    statement: str
    reference_source: str
    reference_length: int
    reference_heartbeats: int | None
    versions: tuple[VersionPin, ...]
    dependency_digests: tuple[str, ...]
    verifier_id: str
    verifier_version: str
    heartbeat_method: str
    header: str = ""
    repository: str = ""
    file_path: str = ""
    verifier_options_json: str = "{}"
    allowed_axioms: tuple[str, ...] = tuple(sorted(STANDARD_AXIOMS))

    def __post_init__(self):
        for name in ("problem", "statement", "verifier_id", "verifier_version", "heartbeat_method"):
            _text(getattr(self, name), name)
        _units(self.reference_length, "reference_length")
        if self.reference_heartbeats is not None:
            _units(self.reference_heartbeats, "reference_heartbeats")
        proof_suffix(self.reference_source, self.statement)
        if (type(self.versions) is not tuple or not self.versions or
                any(type(pin) is not VersionPin for pin in self.versions) or
                len({pin.lean_tag for pin in self.versions}) != len(self.versions)):
            raise ValueError("explicit unique immutable version pins required")
        for pin in self.versions:
            _text(pin.lean_tag, "version")
            _text(pin.git_commit, "commit")
        if (type(self.dependency_digests) is not tuple or len(self.dependency_digests) != len(self.versions)
                or any(not isinstance(d, str) or not re.fullmatch(r"[0-9a-f]{64}", d) for d in self.dependency_digests)):
            raise ValueError("one dependency-manifest SHA-256 per version required")
        if type(self.allowed_axioms) is not tuple or any(not isinstance(a, str) for a in self.allowed_axioms):
            raise ValueError("immutable axiom policy required")
        options = json.loads(self.verifier_options_json)
        if not isinstance(options, dict):
            raise ValueError("verifier options must be an object")
        object.__setattr__(self, "verifier_options_json", canonical_json(options))

    @property
    def context_id(self) -> str:
        return content_hash({"schema": SCHEMA, "scoring": SCORING_ID, "tokenizer": TOKENIZER_ID, **asdict(self)})


@dataclass(frozen=True)
class VerificationRequest:
    context: ArenaContext
    source: str
    version: VersionPin

    @property
    def request_id(self) -> str:
        return content_hash({"schema": SCHEMA, "context": self.context.context_id,
                             "source": source_hash(self.source), "version": asdict(self.version)})


@dataclass(frozen=True)
class VersionReceipt:
    request_id: str
    candidate_sha256: str
    target: str
    outcome: Outcome
    # The trusted adapter must check the original target, not just process exit.
    type_preserved: bool = False
    exit_code: int | None = None
    axiom_output: str = ""
    heartbeats: int | None = None
    reason: str = ""
    observations_json: str = "{}"

    def __post_init__(self):
        if not isinstance(self.outcome, Outcome) or type(self.type_preserved) is not bool:
            raise ValueError("invalid typed verifier receipt")
        if self.exit_code is not None and type(self.exit_code) is not int:
            raise ValueError("invalid process exit code")
        if self.heartbeats is not None:
            _units(self.heartbeats, "heartbeats")
        for name in ("request_id", "candidate_sha256", "target", "axiom_output", "reason"):
            if not isinstance(getattr(self, name), str):
                raise ValueError("invalid receipt text")
        if len(self.axiom_output.encode()) > 1_048_576 or len(self.reason.encode()) > 4096:
            raise ValueError("receipt byte budget")
        if not isinstance(self.observations_json, str) or len(self.observations_json.encode()) > 131072:
            raise ValueError("observation byte budget")
        observations = json.loads(self.observations_json)
        if not isinstance(observations, dict):
            raise ValueError("observations must be an object")
        object.__setattr__(self, "observations_json", canonical_json(observations))


@dataclass(frozen=True)
class Evaluation:
    context_id: str
    candidate_sha256: str
    status: str
    length: int | None
    score: Score | None
    receipts: tuple[VersionReceipt, ...]
    evidence_mode: str
    reason: str = ""

    def to_dict(self) -> dict:
        return {"schema": SCHEMA, "scoring_id": SCORING_ID, "tokenizer_id": TOKENIZER_ID,
                "official_score": None, **asdict(self)}


class ArenaEvaluator:
    """Single-owner verifier adapter with bounded, context-bound receipt reuse.

    The adapter is trusted infrastructure, never a policy-provided callback.
    local_lean denotes caller-supplied checking, not an independent attestation.
    Transient results are not cached; terminal cache hits cost no new calls.
    """
    def __init__(self, context: ArenaContext, verifier: Callable[[VerificationRequest], VersionReceipt] | None,
                 *, max_calls: int, evidence_mode: str, max_cache_entries: int = 256, max_cache_bytes: int = 2_097_152,
                 context_validator: Callable[[VerificationRequest], None] | None = None):
        if evidence_mode not in {"offline_fixture", "local_lean"}:
            raise ValueError("explicit evidence mode required")
        if not isinstance(context, ArenaContext) or (verifier is not None and not callable(verifier)):
            raise ValueError("explicit context and verifier required")
        self.context, self.verifier = context, verifier
        if context_validator is not None and not callable(context_validator):
            raise ValueError("context validator must be callable")
        self.context_validator = context_validator
        self.max_calls = _units(max_calls, "max_calls")
        self.max_cache_entries = _units(max_cache_entries, "max_cache_entries")
        self.max_cache_bytes = _units(max_cache_bytes, "max_cache_bytes")
        self._cache_bytes = 0
        self.evidence_mode = evidence_mode
        self.calls = self.cache_hits = 0
        self._cache: dict[str, VersionReceipt] = {}

    def _verify(self, request: VerificationRequest) -> VersionReceipt:
        empty = VersionReceipt(request.request_id, source_hash(request.source), self.context.problem, Outcome.UNAVAILABLE)
        cache_allowed = self.evidence_mode != "local_lean" or self.context_validator is not None
        # Validate live dependency applicability even before reusing a receipt.
        if self.context_validator is not None:
            try:
                self.context_validator(request)
            except Exception as exc:
                return replace(empty, outcome=Outcome.ERROR, reason=f"context_validation: {str(exc)[:250]}")
        if cache_allowed and request.request_id in self._cache:
            self.cache_hits += 1
            return self._cache[request.request_id]
        if self.verifier is None:
            return replace(empty, reason="verifier_unavailable")
        if self.calls >= self.max_calls:
            return replace(empty, outcome=Outcome.BUDGET_EXHAUSTED, reason="operation_budget")
        self.calls += 1  # Reserve before work, including failures.
        try:
            receipt = self.verifier(request)
            if not isinstance(receipt, VersionReceipt):
                raise ValueError("typed_receipt_required")
            if (receipt.request_id != request.request_id or receipt.candidate_sha256 != empty.candidate_sha256
                    or receipt.target != self.context.problem):
                raise ValueError("receipt_identity_mismatch")
            if receipt.outcome == Outcome.VERIFIED:
                audit = audit_axioms(receipt.axiom_output, [self.context.problem], allowed_axioms=self.context.allowed_axioms)
                if receipt.exit_code != 0 or not receipt.type_preserved or not audit["accepted"]:
                    receipt = replace(receipt, outcome=Outcome.REJECTED, reason="target_process_or_axiom_check_failed")
        except Exception as exc:
            return replace(empty, outcome=Outcome.ERROR, reason=f"{type(exc).__name__}: {str(exc)[:250]}")
        incomplete_metrics = (receipt.outcome == Outcome.VERIFIED and request.version == self.context.versions[0]
                              and self.context.reference_heartbeats and receipt.heartbeats is None)
        receipt_bytes = len(canonical_json(asdict(receipt)).encode())
        if (cache_allowed and receipt.outcome in {Outcome.VERIFIED, Outcome.REJECTED} and not incomplete_metrics
                and self.max_cache_entries and receipt_bytes <= self.max_cache_bytes):
            while self._cache and (len(self._cache) >= self.max_cache_entries or self._cache_bytes + receipt_bytes > self.max_cache_bytes):
                removed = self._cache.pop(next(iter(self._cache)))
                self._cache_bytes -= len(canonical_json(asdict(removed)).encode())
            self._cache[request.request_id] = receipt
            self._cache_bytes += receipt_bytes
        return receipt

    def evaluate(self, source: str) -> Evaluation:
        error = intake_error(source, self.context.statement)
        identity = (self.context.context_id, source_hash(source))
        if error:
            return Evaluation(*identity, "REJECTED", None, Score(0, 0, 0, 0), (), self.evidence_mode, error)
        length = reference_tokens(source, self.context.statement)
        receipts = tuple(self._verify(VerificationRequest(self.context, source, version)) for version in self.context.versions)
        default = receipts[0]
        if default.outcome == Outcome.REJECTED:
            return Evaluation(*identity, "REJECTED", length, Score(0, 0, 0, 0), receipts, self.evidence_mode, default.reason)
        if any(r.outcome not in {Outcome.VERIFIED, Outcome.REJECTED} for r in receipts):
            return Evaluation(*identity, "INCOMPLETE", length, None, receipts, self.evidence_mode, "version_checks_incomplete")
        if self.context.reference_heartbeats and default.heartbeats is None:
            return Evaluation(*identity, "INCOMPLETE", length, None, receipts, self.evidence_mode, "heartbeat_measurement_missing")
        score = score_metrics(reference_length=self.context.reference_length,
                              reference_heartbeats=self.context.reference_heartbeats, length=length,
                              heartbeats=default.heartbeats,
                              passed=sum(r.outcome == Outcome.VERIFIED for r in receipts), total=len(receipts))
        return Evaluation(*identity, "MEASURED", length, score, receipts, self.evidence_mode)

    def verify_request(self, request: VerificationRequest) -> VersionReceipt:
        """Check one explicit pin for discovery, not all-pin score admission.

        Reuse the same receipt/axiom/context boundary as evaluate(). A caller
        cannot substitute a different context or spend work on a foreign pin.
        """
        if (type(request) is not VerificationRequest or request.context != self.context
                or request.version not in self.context.versions):
            raise ValueError("foreign discovery request")
        error = intake_error(request.source, self.context.statement)
        if error:
            return VersionReceipt(request.request_id, source_hash(request.source),
                                  self.context.problem, Outcome.REJECTED, reason=error)
        return self._verify(request)

    def compile_candidate(self, source: str, **_kwargs) -> dict:
        """Thin existing-router adapter; legacy flags cannot supply admission."""
        result = self.evaluate(source)
        return {"theorem_ok": result.status == "MEASURED", "token_count": result.length,
                "reason": result.reason, "arena_evaluation": result.to_dict(), "evidence_mode": self.evidence_mode}

    def accounting(self) -> dict:
        return {"verifier_calls": self.calls, "max_calls": self.max_calls, "remaining_calls": self.max_calls - self.calls,
                "cache_hits": self.cache_hits, "cache_entries": len(self._cache), "cache_bytes": self._cache_bytes,
                "evidence_mode": self.evidence_mode, "measured_api_cost": None, "direct_api_calls": 0,
                "adapter_cost_accounting": "caller_owned"}


def calibration_report(records: Sequence[Mapping], heartbeat_rows: Sequence[Mapping]) -> dict:
    """Readiness report, not a synthetic compilation or an Arena submission."""
    if not records or len({r["name"] for r in records}) != len(records):
        raise ValueError("nonempty unique corpus required")
    heartbeats = {r["name"]: r.get("heartbeat") for r in heartbeat_rows}
    if len(heartbeats) != len(heartbeat_rows):
        raise ValueError("duplicate reference heartbeat row")
    rows = []
    for row in records:
        _units(row["proof_length"], "reference length")
        measured = reference_tokens(row["src"], row["statement"])
        versions = []
        for pin in row["version_info"]:
            if not isinstance(pin, dict) or len(pin) != 1:
                raise ValueError("one tag/commit per version pin required")
            tag, commit = next(iter(pin.items()))
            _text(tag, "version")
            _text(commit, "commit")
            versions.append({"tag": tag, "commit": commit, "status": "UNMEASURED"})
        if not versions or len({p["tag"] for p in versions}) != len(versions):
            raise ValueError("unique nonempty versions required")
        hb = heartbeats.get(row["name"])
        if hb is not None:
            _units(hb, "reference heartbeats")
        rows.append({"name": row["name"], "reference_tokens": row["proof_length"], "measured_tokens": measured,
                     "tokens_match": measured == row["proof_length"], "reference_heartbeats": hb,
                     "versions": versions, "baseline_compiles": None, "local_combined_pct": None})
    return {"schema": "jevops-arena-calibration/v1", "tokenizer_id": TOKENIZER_ID, "official_score": None,
            "reference_token_matches": sum(r["tokens_match"] for r in rows), "problems": len(rows),
            "required_version_checks": sum(len(r["versions"]) for r in rows), "completed_version_checks": 0,
            "worker_metric_parity": "UNCONFIRMED", "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrate", action="store_true", help="check reference tokens; never runs Lean or a model")
    parser.add_argument("--corpus", type=Path, default=Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/data/benchmark_data_warmup.jsonl")
    parser.add_argument("--heartbeats", type=Path, default=Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/space/benchmark_heartbeats.jsonl")
    args = parser.parse_args()
    if not args.calibrate:
        parser.error("choose --calibrate")
    def read(path):
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    report = calibration_report(read(args.corpus), read(args.heartbeats))
    report["corpus_sha256"] = hashlib.sha256(args.corpus.read_bytes()).hexdigest()
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["reference_token_matches"] == report["problems"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
