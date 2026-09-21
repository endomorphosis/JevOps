#!/usr/bin/env python3
"""Router-guided Lean proof shortening and autoencoder tuning.

This module is intentionally narrower than :mod:`jevops.harness`.  The
general harness asks an LLM router for source-code actions; this loop asks the
router for bounded tactic/IR suggestions for one theorem and gives every
suggestion to the Lean compiler before it can affect the search state.

The router is a proposal generator, never a proof oracle.  The loop keeps the
following order of authority:

1. Lean/Lake admission;
2. proof-body token count among admitted candidates;
3. IR/cosine, CE, NCA, and router-confidence signals as learning/tie-break
   signals only.

The default route is ``ipfs_accelerate_py.llm_router`` with the configurable
``codex_cli`` / ``gpt-5.6-luna`` pair.  Tests and offline users can inject a
``router_generate(prompt)`` callback, so importing this module never requires
the optional accelerator checkout.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence

from . import autoencoder as ae
from . import tactics as tactic_ops
from .autoencoder_training import (
    AutoencoderConfig,
    LeanIRAutoencoder,
    coerce_training_example,
    loss_for_example,
    nca_feedback_for_example,
    record_autoencoder_nca_feedback,
)
from .outer import head_chars, make_llm_router_generate


_BY_MARKER = re.compile(r":=\s*by\b", re.IGNORECASE)
_OP_HEAD = re.compile(r"^(?P<op>[A-Za-z_][A-Za-z0-9_']*)(?:\s+(?P<args>.*))?$", re.DOTALL)
_BANNED_TACTIC_TEXT = re.compile(
    r"(?:\b(?:sorry|admit|unsafe|run_tac|elab|macro|quote|import|namespace|open|set_option|theorem|lemma|example)\b"
    r"|#(?:eval|check|print|reduce)\b|\b(?:exact|apply)\?\b|:=)",
    re.IGNORECASE,
)
_BANNED_IR_ARG = re.compile(
    r"(?:\b(?:sorry|admit|unsafe|run_tac|elab|macro|quote|import|namespace|open|set_option)\b|<;>|\||;)",
    re.IGNORECASE,
)

# These names are the only tactic transformations a router can request.  The
# implementations are local, deterministic JevOps functions; the model does
# not receive a code-execution surface.
ROUTER_STRATEGIES = (
    "closed_tree",
    "guided_mca",
    "span_preserving",
    "drop_unused_haves",
    "drop_rename_i",
    "drop_have_after_induction",
    "collapse_simp_at",
    "drop_redundant_simp_at",
    "collapse_rw_to_simp",
    "join_consecutive_exacts",
    "join_consecutive_applies",
    "drop_last_simp_all",
    "drop_bare_simp_all",
    "try_simp_all",
    "pca_prefix",
    "keep_calc_only",
    "hammer_variants",
    "closed_edits",
)
_ROUTER_STRATEGY_SET = frozenset(ROUTER_STRATEGIES)
_MCA_FAMILIES = (
    "dead_code",
    "strength_reduction",
    "loop_invariant",
    "search_space",
    "algebraic_simplification",
)


def _clip01(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return max(0.0, min(1.0, float(default)))
    if not math.isfinite(number):
        return max(0.0, min(1.0, float(default)))
    return max(0.0, min(1.0, number))


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalise_model_name(value: Any) -> str:
    # The local router CLI documents the id with hyphens.  Accepting the
    # human-friendly ``gpt-5.6 luna`` spelling avoids a needless route miss.
    return "-".join(str(value or "gpt-5.6-luna").strip().split()) or "gpt-5.6-luna"


@dataclass(frozen=True)
class RouterTuningConfig:
    """Bounded policy for one router-assisted theorem search."""

    provider: str = "codex_cli"
    model_name: str = "gpt-5.6-luna"
    reasoning_effort: str = "high"
    rounds: int = 3
    max_router_candidates: int = 8
    max_candidate_pool: int = 48
    max_tactic_lines: int = 80
    max_candidate_chars: int = 12_000
    max_prompt_chars: int = 16_000
    n_variations: int = 8
    strategy_cap: int = 12
    seed: int = 17
    train: bool = True
    strict_router: bool = True
    router_kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", str(self.provider or "codex_cli"))
        object.__setattr__(self, "model_name", _normalise_model_name(self.model_name))
        object.__setattr__(self, "reasoning_effort", str(self.reasoning_effort or "high"))
        for name in (
            "rounds",
            "max_router_candidates",
            "max_candidate_pool",
            "max_tactic_lines",
            "max_candidate_chars",
            "max_prompt_chars",
            "n_variations",
            "strategy_cap",
        ):
            object.__setattr__(self, name, max(1, int(getattr(self, name))))
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "router_kwargs", dict(self.router_kwargs or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "reasoning_effort": self.reasoning_effort,
            "rounds": self.rounds,
            "max_router_candidates": self.max_router_candidates,
            "max_candidate_pool": self.max_candidate_pool,
            "max_tactic_lines": self.max_tactic_lines,
            "max_candidate_chars": self.max_candidate_chars,
            "max_prompt_chars": self.max_prompt_chars,
            "n_variations": self.n_variations,
            "strategy_cap": self.strategy_cap,
            "seed": self.seed,
            "train": self.train,
            "strict_router": self.strict_router,
        }

    def llm_kwargs(self) -> dict[str, Any]:
        kwargs = dict(self.router_kwargs)
        kwargs.setdefault("reasoning_effort", self.reasoning_effort)
        if self.strict_router:
            kwargs.setdefault("allow_cross_provider_fallback", False)
        return kwargs


def _source_parts(source: str) -> tuple[str, str, bool]:
    text = str(source or "")
    marker = _BY_MARKER.search(text)
    if marker is None:
        return "", text.strip(), False
    return text[: marker.end()], text[marker.end() :].lstrip("\n"), True


def _render_source(prefix: str, body: str, *, has_theorem: bool) -> str:
    clean = str(body or "").strip("\n")
    if not has_theorem:
        return clean + ("\n" if clean else "")
    lines = clean.splitlines()
    nonempty = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    if nonempty and min(nonempty) < 2:
        shift = 2 - min(nonempty)
        lines = [(" " * shift + line) if line.strip() else line for line in lines]
        clean = "\n".join(lines)
    return str(prefix).rstrip() + "\n" + clean + ("\n" if clean else "")


def _tactic_body(value: Any, config: RouterTuningConfig) -> Optional[str]:
    text = str(value or "").replace("\x00", "").strip()
    if text.startswith("by\n"):
        text = text[3:].lstrip("\n")
    elif text == "by":
        return None
    if not text or len(text) > config.max_candidate_chars:
        return None
    if _BANNED_TACTIC_TEXT.search(text):
        return None
    lines = text.splitlines()
    if len(lines) > config.max_tactic_lines:
        return None
    # Tactic candidates may contain normal Lean combinators, but they may not
    # smuggle a second declaration or a command into the theorem body.
    if any(line.lstrip().startswith(("theorem ", "lemma ", "example ", "import ", "namespace ", "open ")) for line in lines):
        return None
    return text


def _normalise_ir_ops(raw: Any, config: RouterTuningConfig) -> Optional[list[dict[str, Any]]]:
    if not isinstance(raw, (list, tuple)) or not raw:
        return None
    if len(raw) > 32:
        return None
    operations: list[dict[str, Any]] = []
    allowed = set(ae.LEAN_IR_OPS)
    for item in raw:
        if isinstance(item, Mapping):
            op = str(item.get("op") or "").strip().lower()
            raw_args = item.get("args")
            if raw_args is None and item.get("arg") is not None:
                raw_args = [item.get("arg")]
        else:
            match = _OP_HEAD.match(str(item or "").strip())
            if match is None:
                return None
            op = str(match.group("op") or "").strip().lower()
            raw_args = [match.group("args")] if match.group("args") else []
        if op == "intros":
            op = "intro"
        if op not in allowed:
            return None
        if isinstance(raw_args, str):
            raw_args = [raw_args]
        args: list[str] = []
        for value in list(raw_args or ()):
            arg = " ".join(str(value or "").replace("\x00", " ").split())[:160]
            if not arg or _BANNED_IR_ARG.search(arg):
                return None
            args.append(arg)
        row: dict[str, Any] = {"op": op}
        if args:
            row["args"] = args
        operations.append(row)
    return operations


def _ir_body(ir: Mapping[str, Any]) -> Optional[str]:
    rendered = ae.decode_lean_ir(ir)
    marker = _BY_MARKER.search(rendered)
    if marker is None:
        return None
    return rendered[marker.end() :].lstrip("\n").strip("\n")


def _parse_json_object(text: Any) -> Optional[dict[str, Any]]:
    source = str(text or "")
    decoder = json.JSONDecoder()
    for index, char in enumerate(source):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(source, index)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def parse_router_plan(text: Any, *, config: Optional[RouterTuningConfig] = None) -> dict[str, Any]:
    """Parse a bounded router plan; never execute arbitrary model text."""

    cfg = config or RouterTuningConfig()
    raw = _parse_json_object(text)
    if raw is None:
        return {"ok": False, "reason": "bad_json", "candidates": [], "strategies": []}
    raw_strategies = raw.get("strategies")
    if raw_strategies is None:
        raw_strategies = raw.get("tactic_families")
    if isinstance(raw_strategies, str):
        raw_strategies = [raw_strategies]
    strategies: list[str] = []
    unknown: list[str] = []
    for value in list(raw_strategies or ())[: cfg.strategy_cap]:
        item = str(value or "").strip().lower().replace("-", "_")
        if item in _ROUTER_STRATEGY_SET and item not in strategies:
            strategies.append(item)
        elif item and item not in unknown:
            unknown.append(item)
    raw_candidates = raw.get("candidates")
    if raw_candidates is None:
        raw_candidates = []
        raw_candidates.extend(raw.get("ir_candidates") or ())
        raw_candidates.extend(raw.get("tactic_candidates") or ())
    if isinstance(raw_candidates, Mapping):
        raw_candidates = [raw_candidates]
    candidates: list[dict[str, Any]] = []
    rejected = 0
    for item in list(raw_candidates or ())[: cfg.max_router_candidates]:
        if isinstance(item, str):
            body = _tactic_body(item, cfg)
            if body:
                candidates.append({"kind": "router_tactic", "tactics": body})
            else:
                rejected += 1
            continue
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        row: dict[str, Any] = {
            "kind": str(item.get("kind") or item.get("family") or "router_candidate")[:80],
            "rationale": head_chars(item.get("rationale") or item.get("reason") or "", 240),
        }
        if item.get("ops") is not None or item.get("ir_ops") is not None:
            ops = _normalise_ir_ops(item.get("ops") if item.get("ops") is not None else item.get("ir_ops"), cfg)
            if ops is None:
                rejected += 1
                continue
            row["ops"] = ops
        if item.get("tactics") is not None or item.get("body") is not None:
            body = _tactic_body(item.get("tactics") if item.get("tactics") is not None else item.get("body"), cfg)
            if body is None:
                rejected += 1
                continue
            row["tactics"] = body
        strategy = str(item.get("strategy") or "").strip().lower().replace("-", "_")
        if strategy:
            if strategy not in _ROUTER_STRATEGY_SET:
                rejected += 1
                continue
            row["strategy"] = strategy
        if not any(key in row for key in ("ops", "tactics", "strategy")):
            rejected += 1
            continue
        candidates.append(row)
    return {
        "ok": True,
        "schema": "jevops-router-tuning-plan/v1",
        "focus": head_chars(raw.get("focus") or raw.get("objective") or "", 160),
        "strategies": strategies,
        "unknown_strategies": unknown,
        "candidates": candidates,
        "rejected_candidates": rejected,
        "raw_digest": _digest(raw),
    }


def _strategy_body(name: str, body: str, rng: random.Random) -> list[tuple[str, str, str]]:
    """Apply one allowlisted local strategy and return labeled body drafts."""

    text = str(body or "")
    if name == "closed_tree":
        return [(str(family), str(candidate), "closed_tree") for family, candidate, _ops in tactic_ops.closed_tree_edits(text)]
    if name == "guided_mca":
        return [
            (str(family), str(candidate), "guided_mca")
            for family, candidate, _ops in tactic_ops.guided_mca_edits(text, _MCA_FAMILIES)
        ]
    if name == "span_preserving":
        return [(str(family), str(candidate), "span_preserving") for family, candidate, _ops in tactic_ops.span_preserving_edits(text)]
    if name == "hammer_variants":
        return [(str(family), str(candidate), "hammer_variants") for family, candidate in tactic_ops.hammer_variants(text, text)]
    if name == "closed_edits":
        return [
            (str(row.get("kind") or "closed_edit"), str(row.get("tactics") or ""), "closed_edits")
            for row in tactic_ops.propose_closed_edits(text, text, rng, limit=8)
        ]
    direct: dict[str, Callable[[str], Any]] = {
        "drop_unused_haves": tactic_ops.drop_have_obtain,
        "drop_rename_i": tactic_ops.drop_rename_i,
        "drop_have_after_induction": tactic_ops.drop_have_after_induction,
        "collapse_simp_at": tactic_ops.collapse_simp_at,
        "drop_redundant_simp_at": tactic_ops.drop_redundant_simp_at,
        "collapse_rw_to_simp": tactic_ops.collapse_rw_to_simp,
        "join_consecutive_exacts": tactic_ops.join_consecutive_exacts,
        "join_consecutive_applies": tactic_ops.join_consecutive_applies,
        "drop_bare_simp_all": tactic_ops.drop_bare_simp_all,
        "try_simp_all": tactic_ops.try_simp_all,
        "pca_prefix": tactic_ops.pca_prefix,
        "keep_calc_only": tactic_ops.keep_calc_only,
    }
    if name == "drop_last_simp_all":
        result = tactic_ops.drop_last_bare_simp_all(text)
    else:
        fn = direct.get(name)
        result = fn(text) if fn is not None else None
    if result is None:
        return []
    return [(name, str(result), name)]


def _router_prompt(
    *,
    source: str,
    body: str,
    problem: str,
    current: Mapping[str, Any],
    analysis: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]],
    config: RouterTuningConfig,
) -> str:
    payload = {
        "problem": str(problem or "")[:160],
        "statement_and_header": head_chars(source, 4000),
        "current_body": head_chars(body, 5000),
        "current_metrics": dict(current),
        "tactic_analysis": dict(analysis),
        "recent_rounds": list(history)[-3:],
        "allowed_ir_ops": list(ae.LEAN_IR_OPS),
        "allowed_strategies": list(ROUTER_STRATEGIES),
    }
    preamble = (
        "You are the proof-shortening advisor inside a Lean autoencoder loop.\n"
        "Return exactly one JSON object and no markdown. Propose bounded tactic or IR alternatives; "
        "do not claim a proof is valid. Lean compilation is the only proof authority.\n"
        "The primary objective is the smallest verified proof-body token count. Preserve the theorem "
        "statement and binders. Never use sorry, admit, unsafe, run_tac, imports, declarations, exact?, "
        "or apply?. Do not return Python or source-code patches.\n\n"
        "Use this schema (all fields optional except the object itself):\n"
        '{"focus":"...","strategies":["drop_unused_haves"],'
        '"candidates":[{"kind":"ir","ops":[{"op":"simp"}]},'
        '{"kind":"tactic","tactics":"simp"}]}\n'
        f"Provide at most {config.max_router_candidates} candidates.\n"
    )
    prompt = preamble + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return prompt[: config.max_prompt_chars]


def _compact_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "origin": row.get("origin"),
        "kind": row.get("kind"),
        "body_tokens": row.get("body_tokens"),
        "lake_ok": row.get("lake_ok"),
        "reward": row.get("reward"),
        "ir_cosine_m": row.get("ir_cosine_m"),
        "ir_ce_m": row.get("ir_ce_m"),
        "rationale": row.get("rationale"),
        "reason": row.get("reason"),
    }


class RouterTuningLoop:
    """Run a bounded LLM-advised tactic search for one Lean theorem."""

    def __init__(
        self,
        memory: MutableMapping[str, Any],
        source: str,
        *,
        problem: str = "",
        compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
        config: Optional[RouterTuningConfig] = None,
        router_generate: Optional[Callable[[str], Any]] = None,
        router: Any = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.memory = memory
        self.source = str(source or "")
        self.problem = str(problem or "")
        self.compile_fn = compile_fn
        self.config = config or RouterTuningConfig()
        self.rng = rng or random.Random(self.config.seed)
        self.router_generate = router_generate or make_llm_router_generate(
            router=router,
            model_name=self.config.model_name,
            provider=self.config.provider,
            **self.config.llm_kwargs(),
        )
        self._compile_cache: dict[str, dict[str, Any]] = {}
        self._source_prefix, self._source_body, self._has_theorem = _source_parts(self.source)
        self._source_ir = ae.encode_lean_ir(self.source)

    def _compile(self, candidate: str) -> dict[str, Any]:
        key = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        if key in self._compile_cache:
            return dict(self._compile_cache[key])
        if self.compile_fn is None:
            result = {"theorem_ok": False, "reason": "compile_fn_required"}
        else:
            try:
                try:
                    result = dict(self.compile_fn(candidate, problem=self.problem) or {})
                except TypeError:
                    result = dict(self.compile_fn(candidate) or {})
            except Exception as exc:
                result = {"theorem_ok": False, "reason": type(exc).__name__}
        result.setdefault("theorem_ok", result.get("ok", False))
        result["theorem_ok"] = bool(result.get("theorem_ok"))
        result.setdefault("token_count", len(candidate.split()))
        self._compile_cache[key] = dict(result)
        return dict(result)

    def _row(self, candidate: str, *, origin: str, kind: str, rationale: str = "") -> dict[str, Any]:
        candidate = str(candidate or "")
        candidate_ir = ae.encode_lean_ir(candidate)
        compile_result = self._compile(candidate)
        body_tokens = ae.proof_body_token_count(candidate)
        source_body_tokens = max(1, ae.proof_body_token_count(self.source))
        diagnostics = ae.ir_diagnostics(self._source_ir, candidate_ir)
        lake_ok = bool(compile_result.get("theorem_ok"))
        compression = _clip01(1.0 - body_tokens / float(source_body_tokens))
        minimality = ae.minimality_score(
            {
                "body_tokens": body_tokens,
                "source_body_tokens": source_body_tokens,
                "ir_ops": len(candidate_ir.get("ops") or ()),
                "source_ops": len(self._source_ir.get("ops") or ()),
            },
            reference_tokens=source_body_tokens,
            reference_ops=len(self._source_ir.get("ops") or ()),
        )
        scored = ae.score_candidate(
            {
                "cosine_m": diagnostics["ir_cosine_m"],
                "ir_cosine_m": diagnostics["ir_cosine_m"],
                "ce_m": diagnostics["ir_ce_m"],
                "ir_ce_m": diagnostics["ir_ce_m"],
                "lake_ok": lake_ok,
                "body_tokens": body_tokens,
                "n_tokens": body_tokens,
                "source_body_tokens": source_body_tokens,
            },
            verifier_reward=1.0 if lake_ok else 0.0,
            minimality_reward=minimality,
        )
        return {
            "id": "v-" + hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:12],
            "origin": origin,
            "kind": kind,
            "rationale": str(rationale or "")[:240],
            "source": candidate,
            "body_tokens": int(body_tokens),
            "source_body_tokens": int(source_body_tokens),
            "token_count": int(compile_result.get("token_count") or len(candidate.split())),
            "lake_ok": lake_ok,
            "compile": compile_result,
            "ir": candidate_ir,
            "ir_cosine_m": int(diagnostics["ir_cosine_m"]),
            "ir_ce_m": int(diagnostics["ir_ce_m"]),
            "compression": compression,
            "minimality_reward": float(minimality),
            "reward": float(scored.get("reward") or 0.0),
            "admission": "verified" if lake_ok else "rejected",
        }

    def _push(self, rows: list[dict[str, Any]], seen: set[str], candidate: Any, *, origin: str, kind: str, rationale: str = "") -> None:
        body = _tactic_body(candidate, self.config)
        if body is None:
            return
        rendered = _render_source(self._source_prefix, body, has_theorem=self._has_theorem)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        if digest in seen or len(rows) >= self.config.max_candidate_pool:
            return
        seen.add(digest)
        rows.append(self._row(rendered, origin=origin, kind=kind, rationale=rationale))

    def _push_ir(self, rows: list[dict[str, Any]], seen: set[str], ir: Mapping[str, Any], *, origin: str, kind: str, rationale: str = "") -> None:
        body = _ir_body(ir)
        if body is None:
            return
        self._push(rows, seen, body, origin=origin, kind=kind, rationale=rationale)

    def _local_rows(self, body: str, strategies: Sequence[str]) -> list[tuple[str, str, str]]:
        names = list(strategies or ())
        if not names:
            names = ["closed_tree", "guided_mca", "span_preserving", "closed_edits", "hammer_variants"]
        rows: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for name in names[: self.config.strategy_cap]:
            if name not in _ROUTER_STRATEGY_SET:
                continue
            try:
                generated = _strategy_body(name, body, self.rng)
            except Exception:
                generated = []
            for kind, candidate, origin in generated:
                key = str(candidate or "").strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append((kind, key, origin))
                if len(rows) >= self.config.max_candidate_pool:
                    return rows
        return rows

    def _autoencoder_irs(self, current: str) -> list[dict[str, Any]]:
        current_ir = ae.encode_lean_ir(current)
        rows: list[dict[str, Any]] = [dict(current_ir)]
        try:
            store = ((self.memory.get("nca") or {}).get("autoencoder") or {})
            model = LeanIRAutoencoder.from_dict(store.get("training_state"), config=AutoencoderConfig())
            rows.append(model.predict_ir(current, source_ir=current_ir, max_ops=self.config.n_variations))
        except Exception:
            pass
        sampler = getattr(ae, "_candidate_ir_variants", None)
        if callable(sampler):
            try:
                rows.extend(sampler(current_ir, limit=self.config.n_variations, rng=self.rng))
            except Exception:
                pass
        return rows[: self.config.n_variations + 2]

    def _router_rows(
        self,
        plan: Mapping[str, Any],
        rows: list[dict[str, Any]],
        seen: set[str],
        current: str,
    ) -> None:
        current_ir = ae.encode_lean_ir(current)
        for item in list(plan.get("candidates") or ()):
            if not isinstance(item, Mapping):
                continue
            rationale = str(item.get("rationale") or "")
            kind = str(item.get("kind") or "router_candidate")
            if item.get("strategy"):
                for strategy_kind, body, origin in _strategy_body(str(item["strategy"]), _source_parts(current)[1], self.rng):
                    self._push(rows, seen, body, origin="router_strategy:" + origin, kind=strategy_kind, rationale=rationale)
            if item.get("ops") is not None:
                ops = _normalise_ir_ops(item.get("ops"), self.config)
                if ops is not None:
                    candidate_ir = dict(current_ir)
                    candidate_ir["ops"] = ops
                    self._push_ir(rows, seen, candidate_ir, origin="llm_router_ir", kind=kind, rationale=rationale)
            if item.get("tactics") is not None:
                self._push(rows, seen, item.get("tactics"), origin="llm_router_tactic", kind=kind, rationale=rationale)

    def _analysis(self, body: str) -> dict[str, Any]:
        try:
            counts = tactic_ops.count_tactics(body)
        except Exception:
            counts = {"n_tokens": len(body.split()), "n_lines": len(body.splitlines())}
        try:
            structure = tactic_ops.structure_pack(body, body)
        except Exception:
            structure = {}
        return {
            "counts": {str(key): value for key, value in dict(counts).items() if isinstance(value, (int, float))},
            "structure": {
                "n_holes": len(structure.get("mca_holes") or []),
                "n_cases": len(structure.get("pca_case_tags") or []),
                "missing_cases": list(structure.get("missing_cases") or [])[:8],
                "families": sorted({str(row.get("family") or "") for row in structure.get("mca_holes") or ()}),
            },
            "ir_ops": [str(row.get("op") or "") for row in self._source_ir.get("ops") or ()][:32],
        }

    def _train(self, winner: Optional[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        for row in rows:
            reward = float(row.get("reward") or 0.0) if row.get("lake_ok") else 0.0
            try:
                record_autoencoder_nca_feedback(
                    self.memory,
                    problem=self.problem,
                    reward=reward,
                    theorem_ok=bool(row.get("lake_ok")),
                    tokens=int(row.get("body_tokens") or 0),
                    candidate={"id": row.get("id"), "ir_digest": _digest(row.get("ir") or {}), "n_tokens": row.get("body_tokens")},
                )
            except Exception:
                pass
        if not self.config.train or winner is None or not winner.get("lake_ok"):
            return {"ok": True, "trained": False, "reason": "no_verified_winner_or_training_disabled"}
        try:
            store = self.memory.setdefault("nca", {}).setdefault("autoencoder", {})
            model = LeanIRAutoencoder.from_dict(store.get("training_state"), config=AutoencoderConfig())
            example = coerce_training_example(
                {
                    "id": self.problem or "router-tuning",
                    "text": self.source,
                    "source_ir": self._source_ir,
                    "target_ir": winner.get("ir"),
                    "problem": self.problem,
                }
            )
            feedback = nca_feedback_for_example(
                self.memory,
                example,
                candidate={"verifier_reward": 1.0, "typesafe_reward": None},
            )
            reward = _clip01(0.75 + 0.25 * _clip01(winner.get("compression")))
            train_report = model.train_batch(
                [example],
                rewards={example.sample_id: reward},
                nca_rewards={example.sample_id: feedback.reward} if feedback.active else None,
            )
            loss = loss_for_example(
                model,
                example,
                predicted_ir=winner.get("ir") if isinstance(winner.get("ir"), Mapping) else None,
                verifier_reward=1.0,
                nca_memory=self.memory,
                minimality_reward=winner.get("minimality_reward"),
            )
            train_report["loss"] = loss.to_dict()
            store["training_state"] = model.to_dict()
            return {"ok": True, "trained": True, "step": model.step, **train_report}
        except Exception as exc:
            return {"ok": False, "trained": False, "reason": type(exc).__name__}

    def run(self) -> dict[str, Any]:
        if self.compile_fn is None:
            return {
                "ok": False,
                "reason": "compile_fn_required",
                "config": self.config.to_dict(),
                "problem": self.problem,
                "router": {"provider": self.config.provider, "model_name": self.config.model_name},
                "history": [],
            }
        baseline = self._row(self.source, origin="reference", kind="reference")
        best: Optional[dict[str, Any]] = baseline if baseline["lake_ok"] else None
        current = self.source
        history: list[dict[str, Any]] = []
        router_errors = 0
        for round_index in range(self.config.rounds):
            current_body = _source_parts(current)[1]
            current_row = best or baseline
            analysis = self._analysis(current_body)
            prompt = _router_prompt(
                source=current,
                body=current_body,
                problem=self.problem,
                current=_compact_row(current_row),
                analysis=analysis,
                history=history,
                config=self.config,
            )
            try:
                raw_response = self.router_generate(prompt)
                plan = parse_router_plan(raw_response, config=self.config)
                plan["response_digest"] = _digest(raw_response)
                plan["response_head"] = head_chars(raw_response, 320)
            except Exception as exc:
                router_errors += 1
                plan = {
                    "ok": False,
                    "reason": type(exc).__name__,
                    "candidates": [],
                    "strategies": [],
                }
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            self._push(rows, seen, current_body, origin="current", kind="current")
            for kind, body, origin in self._local_rows(current_body, plan.get("strategies") or ()):
                self._push(rows, seen, body, origin="local:" + origin, kind=kind)
            for candidate_ir in self._autoencoder_irs(current):
                self._push_ir(rows, seen, candidate_ir, origin="autoencoder", kind="ir_model")
            self._router_rows(plan, rows, seen, current)
            verified = [row for row in rows if row.get("lake_ok")]
            round_winner = min(
                verified,
                key=lambda row: (
                    int(row.get("body_tokens") or 10**9),
                    int(row.get("token_count") or 10**9),
                    -float(row.get("reward") or 0.0),
                    str(row.get("id") or ""),
                ),
                default=None,
            )
            improved = False
            if round_winner is not None and (
                best is None
                or (int(round_winner["body_tokens"]), int(round_winner["token_count"]))
                < (int(best["body_tokens"]), int(best["token_count"]))
            ):
                best = round_winner
                current = str(round_winner["source"])
                improved = True
            train_report = self._train(round_winner, rows)
            history.append(
                {
                    "round": round_index + 1,
                    "prompt_digest": _digest(prompt),
                    "router": {
                        "ok": bool(plan.get("ok")),
                        "focus": plan.get("focus"),
                        "strategies": list(plan.get("strategies") or ()),
                        "unknown_strategies": list(plan.get("unknown_strategies") or ()),
                        "candidate_count": len(plan.get("candidates") or ()),
                        "rejected_candidates": int(plan.get("rejected_candidates") or 0),
                        "response_digest": plan.get("response_digest"),
                        "response_head": plan.get("response_head"),
                        "reason": plan.get("reason"),
                    },
                    "candidate_count": len(rows),
                    "verified_count": len(verified),
                    "round_winner": _compact_row(round_winner) if round_winner else None,
                    "accepted": improved,
                    "training": train_report,
                    "candidates": [_compact_row(row) for row in rows],
                }
            )
        if best is None:
            best = baseline
        self.memory.setdefault("nca", {}).setdefault("router_tuning", {})
        self.memory["nca"]["router_tuning"].update(
            {
                "problem": self.problem,
                "rounds": len(history),
                "accepted_rounds": sum(1 for row in history if row.get("accepted")),
                "router_errors": router_errors,
                "best_body_tokens": int(best.get("body_tokens") or 0),
                "best_digest": hashlib.sha256(str(best.get("source") or "").encode("utf-8")).hexdigest(),
            }
        )
        return {
            "ok": bool(best.get("lake_ok")),
            "schema": "jevops-router-tuning-result/v1",
            "config": self.config.to_dict(),
            "router": {
                "module": "ipfs_accelerate_py.llm_router",
                "provider": self.config.provider,
                "model_name": self.config.model_name,
            },
            "problem": self.problem,
            "source_body_tokens": int(ae.proof_body_token_count(self.source)),
            "best_body_tokens": int(best.get("body_tokens") or 0),
            "best_token_count": int(best.get("token_count") or 0),
            "compression": _clip01(1.0 - int(best.get("body_tokens") or 0) / float(max(1, ae.proof_body_token_count(self.source)))),
            "admission": best.get("admission"),
            "lake_ok": best.get("lake_ok"),
            "best_source": best.get("source"),
            "best_ir": best.get("ir"),
            "history": history,
            "memory": self.memory,
        }


def tune_autoencoder_with_router(
    memory: MutableMapping[str, Any],
    source: str,
    *,
    problem: str = "",
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    config: Optional[RouterTuningConfig] = None,
    router_generate: Optional[Callable[[str], Any]] = None,
    router: Any = None,
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    """Convenience wrapper for :class:`RouterTuningLoop`."""

    return RouterTuningLoop(
        memory,
        source,
        problem=problem,
        compile_fn=compile_fn,
        config=config,
        router_generate=router_generate,
        router=router,
        rng=rng,
    ).run()


def _lean_compiler(*, project_root: Path, use_lake: bool = False, timeout: float = 20.0) -> Callable[..., dict[str, Any]]:
    executable = "lake" if use_lake else "lean"

    def compile_one(source: str, problem: str = "") -> dict[str, Any]:
        del problem
        with tempfile.TemporaryDirectory(prefix="jevops-router-", dir=str(project_root)) as temp_name:
            path = Path(temp_name) / "Main.lean"
            path.write_text(str(source), encoding="utf-8")
            argv = [executable, "env", "lean", str(path)] if use_lake else [executable, str(path)]
            try:
                completed = subprocess.run(
                    argv,
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=max(1.0, float(timeout)),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {"theorem_ok": False, "reason": type(exc).__name__, "token_count": len(str(source).split())}
            return {
                "theorem_ok": completed.returncode == 0,
                "token_count": len(str(source).split()),
                "stdout_tail": (completed.stdout or "")[-240:],
                "stderr_tail": (completed.stderr or "")[-240:],
            }

    return compile_one


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run router-guided Lean tactic/autoencoder tuning")
    parser.add_argument("source_file", help="Lean theorem source file")
    parser.add_argument("--problem", default="")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--provider", default="codex_cli")
    parser.add_argument("--model", dest="model_name", default="gpt-5.6-luna")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--n-variations", type=int, default=8)
    parser.add_argument("--lake", action="store_true", help="compile with lake env lean")
    parser.add_argument("--state-path", default=None)
    parser.add_argument("--no-train", action="store_true")
    parser.add_argument("--allow-cross-provider-fallback", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    project_root = Path(args.project_root).expanduser().resolve()
    source = Path(args.source_file).expanduser().read_text(encoding="utf-8")
    memory: MutableMapping[str, Any]
    if args.state_path and Path(args.state_path).is_file():
        from .memory import load_memory

        memory = load_memory(Path(args.state_path))
    else:
        memory = {"nca": {"grid": {}, "board_edges": []}}
    config = RouterTuningConfig(
        provider=args.provider,
        model_name=args.model_name,
        reasoning_effort=args.reasoning_effort,
        rounds=args.rounds,
        n_variations=args.n_variations,
        train=not args.no_train,
        strict_router=not args.allow_cross_provider_fallback,
    )
    result = tune_autoencoder_with_router(
        memory,
        source,
        problem=args.problem or Path(args.source_file).stem,
        compile_fn=_lean_compiler(project_root=project_root, use_lake=args.lake),
        config=config,
    )
    if args.state_path:
        from .memory import save_memory

        save_memory(memory, Path(args.state_path))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("ok") else 1


__all__ = [
    "ROUTER_STRATEGIES",
    "RouterTuningConfig",
    "RouterTuningLoop",
    "parse_router_plan",
    "tune_autoencoder_with_router",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
