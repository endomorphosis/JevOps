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

The default route is the in-tree ``jevops.llm_router`` facade with the
configurable ``codex_cli`` / ``gpt-5.6-luna`` pair.  Tests and offline users
can inject a ``router_generate(prompt)`` callback, so importing this module
never requires the deprecated accelerator checkout.
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
    advance_autoencoder_nca,
    record_autoencoder_nca_feedback,
    record_autoencoder_rule_feedback,
    router_rule_id,
)
from .outer import head_chars, make_llm_router_generate


_BY_MARKER = re.compile(r":=\s*by\b", re.IGNORECASE)
_OP_HEAD = re.compile(r"^(?P<op>[A-Za-z_][A-Za-z0-9_']*)(?:\s+(?P<args>.*))?$", re.DOTALL)
_BANNED_TACTIC_TEXT = re.compile(
    r"(?:\b(?:sorry|admit|unsafe|run_tac|elab|macro|quote|import|namespace|open|set_option|theorem|lemma|example)\b"
    r"|#(?:eval|check|print|reduce)\b|\b(?:exact|apply)\?\b)",
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
    "shortcut_closers",
    "goal_directed",
    "hammer_sweep",
    "compose_verified",
    "ir_crossover",
    "pca_mca_cross",
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
    strategy_cap: int = 16
    hammer_sweep: bool = True
    max_hammer_candidates: int = 24
    max_composed_candidates: int = 12
    max_composition_sources: int = 6
    teacher_replay: bool = True
    max_replay_teachers: int = 8
    seed: int = 17
    train: bool = True
    strict_router: bool = True
    design_hint: Mapping[str, Any] = field(default_factory=dict)
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
            "max_hammer_candidates",
            "max_composed_candidates",
            "max_composition_sources",
            "max_replay_teachers",
        ):
            object.__setattr__(self, name, max(1, int(getattr(self, name))))
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(self, "hammer_sweep", bool(self.hammer_sweep))
        object.__setattr__(self, "teacher_replay", bool(self.teacher_replay))
        object.__setattr__(self, "design_hint", dict(self.design_hint or {}))
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
            "hammer_sweep": self.hammer_sweep,
            "max_hammer_candidates": self.max_hammer_candidates,
            "max_composed_candidates": self.max_composed_candidates,
            "max_composition_sources": self.max_composition_sources,
            "teacher_replay": self.teacher_replay,
            "max_replay_teachers": self.max_replay_teachers,
            "seed": self.seed,
            "train": self.train,
            "strict_router": self.strict_router,
            "design_hint": dict(self.design_hint),
        }

    def llm_kwargs(self) -> dict[str, Any]:
        kwargs = dict(self.router_kwargs)
        kwargs.setdefault("reasoning_effort", self.reasoning_effort)
        if self.strict_router:
            # ``allow_cross_provider_fallback`` is understood by some router
            # versions, but older accelerator releases accept it through
            # ``**kwargs`` without enforcing it.  Set both controls and let
            # the adapter attest the route actually used.
            kwargs["allow_cross_provider_fallback"] = False
            kwargs["allow_local_fallback"] = False
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


def _tactic_body(
    value: Any,
    config: RouterTuningConfig,
    *,
    max_lines: Optional[int] = None,
) -> Optional[str]:
    # Preserve leading indentation until common-indent normalisation below;
    # stripping only newlines avoids making the first tactic shallower than
    # its sibling lines.
    text = str(value or "").replace("\x00", "").strip("\n")
    if text.startswith("by\n"):
        text = text[3:].lstrip("\n")
    elif text.startswith("by "):
        text = text[3:].lstrip()
    elif text == "by":
        return None
    if not text or len(text) > config.max_candidate_chars:
        return None
    if _BANNED_TACTIC_TEXT.search(text):
        return None
    lines = text.splitlines()
    # Candidate files often carry the theorem's two-space base indent.  A
    # plain ``str.strip`` removes it only from the first line and shifts all
    # continuation tactics one level deeper, which can change Lean's layout
    # semantics.  Remove the common indentation while preserving nesting;
    # ``_render_source`` adds the theorem-body base indent back.
    indents = [len(line) - len(line.lstrip()) for line in lines if line.strip()]
    if indents:
        common = min(indents)
        if common:
            lines = [line[common:] if line.strip() else line for line in lines]
            text = "\n".join(lines)
    line_limit = config.max_tactic_lines if max_lines is None else max(1, int(max_lines))
    if len(lines) > line_limit:
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
        if not raw_candidates and raw.get("tactics") is not None:
            raw_candidates.append({"kind": "router_tactic", "tactics": raw.get("tactics")})
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
        tactic_value = item.get("tactics")
        if tactic_value is None:
            tactic_value = item.get("tactic")
        if tactic_value is not None or item.get("body") is not None:
            body = _tactic_body(tactic_value if tactic_value is not None else item.get("body"), cfg)
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
    if name == "hammer_sweep":
        return [
            (str(family), str(candidate), "hammer_sweep")
            for family, candidate, _ops in tactic_ops.hammer_sweep_variants(text, text, cap=32)
        ]
    if name == "shortcut_closers":
        return [
            (str(family), str(candidate), "shortcut_closers")
            for family, candidate in tactic_ops.shortcut_variants(text, cap=24)
        ]
    if name == "goal_directed":
        return [
            (str(family), str(candidate), "goal_directed")
            for family, candidate in tactic_ops.closer_variants(text)
        ]
    if name == "pca_mca_cross":
        rows = tactic_ops.closed_tree_edits(text, case_replace_cap=4)
        rows.extend(tactic_ops.guided_mca_edits(text, _MCA_FAMILIES))
        return [(str(family), str(candidate), "pca_mca_cross") for family, candidate, _ops in rows]
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
    design_hint: Optional[Mapping[str, Any]] = None,
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
        "outer_design_directive": dict(design_hint or {}),
    }
    preamble = (
        "You are the proof-shortening advisor inside a Lean autoencoder loop.\n"
        "Return exactly one JSON object and no markdown. Propose bounded tactic or IR alternatives; "
        "do not claim a proof is valid. Lean compilation is the only proof authority.\n"
        "The primary objective is the smallest verified proof-body token count. Preserve the theorem "
        "statement and binders. Never use sorry, admit, unsafe, run_tac, imports, declarations, exact?, "
        "or apply?. Do not return Python or source-code patches.\n\n"
        "The outer controller may provide a design directive. Treat it as a focused search hint, not proof evidence; still return bounded candidates and let Lake decide.\n"
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
        "rule_id": row.get("rule_id"),
        "rule_kind": row.get("rule_kind"),
        "seed_provenance": row.get("seed_provenance"),
        "claimed_tokens": row.get("claimed_tokens"),
        "seed_commit": row.get("seed_commit"),
        "seed_path": row.get("seed_path"),
        "composition_parent_ids": row.get("composition_parent_ids"),
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
        seed_candidates: Optional[Sequence[Any]] = None,
        design_hint: Optional[Mapping[str, Any]] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.memory = memory
        self.source = str(source or "")
        self.problem = str(problem or "")
        self.compile_fn = compile_fn
        self.config = config or RouterTuningConfig()
        self.design_hint = dict(design_hint or self.config.design_hint or {})
        self.rng = rng or random.Random(self.config.seed)
        self.router_generate = router_generate or make_llm_router_generate(
            router=router,
            model_name=self.config.model_name,
            provider=self.config.provider,
            verify_route=self.config.strict_router,
            **self.config.llm_kwargs(),
        )
        # Teacher candidates still pass through the compiler below before
        # they can win or become a training target.  This lets a verified
        # shorter refactor improve the autoencoder without leaking the target
        # into the model's own prediction/loss diagnostics.
        seed_specs: list[dict[str, Any]] = []
        for item in seed_candidates or ():
            spec = self._normalise_seed_candidate(item)
            if spec.get("body"):
                seed_specs.append(spec)
        self.seed_candidates = tuple(seed_specs[: self.config.max_candidate_pool])
        self._rules: dict[str, dict[str, Any]] = {}
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

    @staticmethod
    def _normalise_seed_candidate(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            body = value.get("body")
            if body is None:
                body = value.get("tactics")
            if body is None:
                body = value.get("source")
            metadata = {
                key: value.get(key)
                for key in (
                    "schema",
                    "source",
                    "provenance",
                    "commit",
                    "path",
                    "claimed_tokens",
                    "actual_tokens",
                    "body_digest",
                    "seed_digest",
                )
                if value.get(key) not in (None, "")
            }
            return {"body": str(body or ""), "metadata": metadata}
        return {"body": str(value or ""), "metadata": {}}

    def _register_rule(self, rule: Mapping[str, Any]) -> str:
        normalized = dict(rule)
        supplied_id = str(normalized.get("rule_id") or "")
        normalized["rule_id"] = supplied_id if supplied_id.startswith("rule-") else router_rule_id(normalized)
        rule_id = str(normalized["rule_id"])
        self._rules[rule_id] = normalized
        try:
            record_autoencoder_rule_feedback(
                self.memory,
                problem=self.problem,
                rule=normalized,
            )
        except Exception:
            pass
        return rule_id

    def _row(
        self,
        candidate: str,
        *,
        origin: str,
        kind: str,
        rationale: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
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
        row = {
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
        for key, value in dict(metadata or {}).items():
            if key not in {
                "rule_id",
                "rule_kind",
                "seed_provenance",
                "seed_commit",
                "seed_path",
                "claimed_tokens",
                "actual_tokens",
                "body_digest",
                "seed_digest",
                "composition_parent_ids",
            }:
                continue
            if value is None or value == "":
                continue
            if key in {"claimed_tokens", "actual_tokens"}:
                row[key] = int(value)
            elif key == "composition_parent_ids":
                parent_ids = value if isinstance(value, (list, tuple)) else (value,)
                row[key] = [str(item)[:80] for item in parent_ids[:8] if str(item).strip()]
            else:
                row[key] = str(value)[:320]
        return row

    def _push(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
        candidate: Any,
        *,
        origin: str,
        kind: str,
        rationale: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        seed_lines = self.config.max_tactic_lines
        rule_kind = str((metadata or {}).get("rule_kind") or "")
        if (
            str((metadata or {}).get("seed_provenance") or "") == "git_history"
            or rule_kind in {"verified_composition", "ir_crossover", "teacher_replay"}
        ):
            # Historical keep-bests and their compiler-gated compositions may
            # contain harmless layout lines beyond the tighter LLM response
            # budget.  Keep the exception bounded and apply the same
            # unsafe-text/declaration checks.
            seed_lines = min(160, max(seed_lines, seed_lines + 64))
        body = _tactic_body(candidate, self.config, max_lines=seed_lines)
        if body is None:
            return
        rendered = _render_source(self._source_prefix, body, has_theorem=self._has_theorem)
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        if digest in seen:
            # A router proposal can be textually identical to an
            # autoencoder/local proposal.  Do not lose the rule observation
            # merely because candidate deduplication kept one proof row.
            rule_id = str((metadata or {}).get("rule_id") or "")
            if rule_id:
                for existing in rows:
                    if str(existing.get("id") or "") == "v-" + digest[:12]:
                        existing.setdefault("rule_id", rule_id)
                        existing.setdefault("rule_kind", (metadata or {}).get("rule_kind"))
                        break
            return
        if len(rows) >= self.config.max_candidate_pool:
            return
        seen.add(digest)
        rows.append(
            self._row(
                rendered,
                origin=origin,
                kind=kind,
                rationale=rationale,
                metadata=metadata,
            )
        )

    def _seed_body(self, value: Any) -> str:
        """Accept either a tactic body or this theorem's complete source."""

        if isinstance(value, Mapping):
            value = value.get("body") or value.get("tactics") or value.get("source")
        text = str(value or "").strip("\n")
        if self._has_theorem and text.startswith(self._source_prefix.rstrip()):
            return text[len(self._source_prefix) :].lstrip("\n")
        return text

    def _push_ir(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
        ir: Mapping[str, Any],
        *,
        origin: str,
        kind: str,
        rationale: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> None:
        body = _ir_body(ir)
        if body is None:
            return
        self._push(
            rows,
            seen,
            body,
            origin=origin,
            kind=kind,
            rationale=rationale,
            metadata=metadata,
        )

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
        plan_digest = str(plan.get("response_digest") or plan.get("raw_digest") or "")
        for item in list(plan.get("candidates") or ()):
            if not isinstance(item, Mapping):
                continue
            rationale = str(item.get("rationale") or "")
            kind = str(item.get("kind") or "router_candidate")
            if item.get("strategy"):
                strategy = str(item["strategy"])
                rule_id = self._register_rule(
                    {
                        "kind": "router_strategy",
                        "strategy": strategy,
                        "origin": "llm_router_strategy",
                        "rationale_digest": _digest(rationale),
                        "plan_digest": plan_digest,
                    }
                )
                for strategy_kind, body, origin in _strategy_body(str(item["strategy"]), _source_parts(current)[1], self.rng):
                    self._push(
                        rows,
                        seen,
                        body,
                        origin="router_strategy:" + origin,
                        kind=strategy_kind,
                        rationale=rationale,
                        metadata={"rule_id": rule_id, "rule_kind": "router_strategy"},
                    )
            if item.get("ops") is not None:
                ops = _normalise_ir_ops(item.get("ops"), self.config)
                if ops is not None:
                    rule_id = self._register_rule(
                        {
                            "kind": kind,
                            "ops": ops,
                            "origin": "llm_router_ir",
                            "rationale_digest": _digest(rationale),
                            "plan_digest": plan_digest,
                        }
                    )
                    candidate_ir = dict(current_ir)
                    candidate_ir["ops"] = ops
                    self._push_ir(
                        rows,
                        seen,
                        candidate_ir,
                        origin="llm_router_ir",
                        kind=kind,
                        rationale=rationale,
                        metadata={"rule_id": rule_id, "rule_kind": "llm_router_ir"},
                    )
            if item.get("tactics") is not None:
                tactic_text = str(item.get("tactics") or "")
                rule_id = self._register_rule(
                    {
                        "kind": kind,
                        "candidate_digest": _digest(tactic_text),
                        "origin": "llm_router_tactic",
                        "rationale_digest": _digest(rationale),
                        "plan_digest": plan_digest,
                    }
                )
                self._push(
                    rows,
                    seen,
                    tactic_text,
                    origin="llm_router_tactic",
                    kind=kind,
                    rationale=rationale,
                    metadata={"rule_id": rule_id, "rule_kind": "llm_router_tactic"},
                )

    def _verified_sources(self, rows: Sequence[Mapping[str, Any]], current: str) -> list[dict[str, Any]]:
        """Return distinct Lake-admitted teachers in shortest-first order."""

        candidates = [
            dict(row)
            for row in rows
            if row.get("lake_ok") and str(row.get("source") or "").strip()
        ]
        if str(current or "").strip() and not any(str(row.get("source") or "") == str(current) for row in candidates):
            current_row = self._row(current, origin="current", kind="composition_source")
            if current_row.get("lake_ok"):
                candidates.append(current_row)
        candidates.sort(
            key=lambda row: (
                int(row.get("body_tokens") or 10**9),
                int(row.get("token_count") or 10**9),
                str(row.get("id") or ""),
            )
        )
        distinct: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in candidates:
            digest = hashlib.sha256(str(row.get("source") or "").encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            distinct.append(row)
            if len(distinct) >= self.config.max_composition_sources:
                break
        return distinct

    def _compose_verified_rows(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
        current: str,
    ) -> int:
        """Crossover separately Lake-admitted high-score teachers."""

        before = len(rows)
        sources = self._verified_sources(rows, current)
        for left_index, left in enumerate(sources):
            for right in sources[left_index + 1 :]:
                left_body = _source_parts(str(left.get("source") or ""))[1]
                right_body = _source_parts(str(right.get("source") or ""))[1]
                parent_ids = [
                    str(left.get("rule_id") or left.get("id") or "")[:80],
                    str(right.get("rule_id") or right.get("id") or "")[:80],
                ]
                for kind, body, ops in tactic_ops.compose_tactic_bodies(
                    left_body,
                    right_body,
                    cap=self.config.max_composed_candidates,
                ):
                    digest = _digest(body)
                    rule_id = self._register_rule(
                        {
                            "kind": "verified_composition",
                            "strategy": "compose_verified",
                            "ops": list(ops),
                            "origin": "verified_composition",
                            "candidate_digest": digest,
                            "parent_rule_ids": parent_ids,
                        }
                    )
                    self._push(
                        rows,
                        seen,
                        body,
                        origin="composition:" + str(kind),
                        kind="verified_composition",
                        rationale="crossover of two independently Lake-admitted teachers",
                        metadata={
                            "rule_id": rule_id,
                            "rule_kind": "verified_composition",
                            "composition_parent_ids": parent_ids,
                        },
                    )
                    if len(rows) - before >= self.config.max_composed_candidates:
                        return len(rows) - before
        return len(rows) - before

    def _crossover_ir_rows(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
        current: str,
    ) -> int:
        """Crossover operation sequences from distinct verified teachers."""

        before = len(rows)
        sources = self._verified_sources(rows, current)
        for left_index, left in enumerate(sources):
            left_ir = left.get("ir") if isinstance(left.get("ir"), Mapping) else ae.encode_lean_ir(str(left.get("source") or ""))
            for right in sources[left_index + 1 :]:
                right_ir = right.get("ir") if isinstance(right.get("ir"), Mapping) else ae.encode_lean_ir(str(right.get("source") or ""))
                parent_ids = [
                    str(left.get("rule_id") or left.get("id") or "")[:80],
                    str(right.get("rule_id") or right.get("id") or "")[:80],
                ]
                for candidate_ir in ae.crossover_lean_ir(
                    left_ir,
                    right_ir,
                    limit=self.config.max_composed_candidates,
                ):
                    rule_id = self._register_rule(
                        {
                            "kind": "ir_crossover",
                            "strategy": "ir_crossover",
                            "ops": list(candidate_ir.get("ops") or ())[:32],
                            "origin": "verified_ir_crossover",
                            "candidate_digest": str(candidate_ir.get("ops_digest") or ""),
                            "parent_rule_ids": parent_ids,
                        }
                    )
                    self._push_ir(
                        rows,
                        seen,
                        candidate_ir,
                        origin="ir_crossover",
                        kind="ir_crossover",
                        metadata={
                            "rule_id": rule_id,
                            "rule_kind": "ir_crossover",
                            "composition_parent_ids": parent_ids,
                        },
                    )
                    if len(rows) - before >= self.config.max_composed_candidates:
                        return len(rows) - before
        return len(rows) - before

    def _hammer_sweep_rows(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
        current: str,
        *,
        requested: Sequence[str] = (),
    ) -> int:
        """Explore all bounded local strategies over the best admitted bases."""

        if not self.config.hammer_sweep:
            return 0
        before = len(rows)
        sources = self._verified_sources(rows, current)
        remaining = max(0, int(self.config.max_hammer_candidates))
        if not sources or remaining <= 0:
            return 0
        strategy_names = [
            str(name)
            for name in requested
            if str(name) not in {"hammer_sweep", "compose_verified", "ir_crossover"}
        ]
        strategy_names.extend(
            name
            for name in ROUTER_STRATEGIES
            if name not in {"hammer_sweep", "compose_verified", "ir_crossover"}
            and name not in strategy_names
        )
        for base in sources:
            body = _source_parts(str(base.get("source") or ""))[1]
            generated = tactic_ops.hammer_sweep_variants(
                body,
                body,
                cap=min(remaining, 32),
            )
            for kind, candidate, ops in generated:
                rule_id = self._register_rule(
                    {
                        "kind": "hammer_sweep",
                        "strategy": "hammer_sweep",
                        "ops": list(ops),
                        "origin": "bounded_hammer",
                        "candidate_digest": _digest(candidate),
                        "parent_rule_ids": [str(base.get("rule_id") or base.get("id") or "")[:80]],
                    }
                )
                self._push(
                    rows,
                    seen,
                    candidate,
                    origin="hammer:" + str(kind),
                    kind="hammer_sweep",
                    metadata={"rule_id": rule_id, "rule_kind": "hammer_sweep"},
                )
                remaining = int(self.config.max_hammer_candidates) - (len(rows) - before)
                if remaining <= 0:
                    return len(rows) - before
            # Now visit every direct allowlisted strategy, with the outer
            # model's requested choices first.  The global row budget keeps
            # this exhaustive enumeration from multiplying compiler calls.
            for strategy in strategy_names:
                for kind, candidate, origin in _strategy_body(strategy, body, self.rng):
                    rule_id = self._register_rule(
                        {
                            "kind": "hammer_strategy",
                            "strategy": strategy,
                            "origin": "bounded_hammer_strategy",
                            "candidate_digest": _digest(candidate),
                            "parent_rule_ids": [str(base.get("rule_id") or base.get("id") or "")[:80]],
                        }
                    )
                    self._push(
                        rows,
                        seen,
                        candidate,
                        origin="hammer_strategy:" + str(origin),
                        kind=str(kind),
                        metadata={"rule_id": rule_id, "rule_kind": "hammer_strategy"},
                    )
                    remaining = int(self.config.max_hammer_candidates) - (len(rows) - before)
                    if remaining <= 0:
                        return len(rows) - before
        return len(rows) - before

    def _teacher_source_digest(self) -> str:
        """Identify the theorem envelope used by the persisted teacher rows."""

        return hashlib.sha256(self.source.encode("utf-8")).hexdigest()

    def _remember_verified_teachers(self, rows: Sequence[Mapping[str, Any]]) -> int:
        """Persist a bounded set of compiler-admitted strict-cut teachers.

        The buffer is deliberately a candidate cache, not proof authority.  It
        stores only enough data to propose a body again; ``_replay_teacher_rows``
        sends that body through the current compiler before it becomes a row or
        a training target.  Keying by the exact theorem source prevents a proof
        body learned for one declaration from silently becoming a target for a
        different declaration with similar text.
        """

        source_tokens = max(1, ae.proof_body_token_count(self.source))
        source_digest = self._teacher_source_digest()
        store = self.memory.setdefault("nca", {}).setdefault("autoencoder", {})
        buffer = store.setdefault("teacher_buffer", [])
        if not isinstance(buffer, list):
            buffer = []
        entries: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in buffer:
            if not isinstance(item, Mapping):
                continue
            problem = str(item.get("problem") or "")[:160]
            digest = str(item.get("source_digest") or "")[:80]
            candidate_digest = str(item.get("candidate_digest") or "")[:80]
            if digest and candidate_digest:
                entries[(problem, digest, candidate_digest)] = dict(item)

        added = 0
        for row in rows:
            if not row.get("lake_ok") or not isinstance(row.get("ir"), Mapping):
                continue
            try:
                body_tokens = int(row.get("body_tokens") or 0)
            except (TypeError, ValueError):
                continue
            if body_tokens <= 0 or body_tokens >= source_tokens:
                continue
            source = str(row.get("source") or "")
            if not source.strip():
                continue
            body = _source_parts(source)[1].strip("\n")
            if not body or len(body) > self.config.max_candidate_chars:
                continue
            candidate_digest = _digest(body)
            key = (self.problem[:160], source_digest, candidate_digest)
            entry = {
                "schema": "jevops-router-teacher/v1",
                "problem": self.problem[:160],
                "source_digest": source_digest,
                "candidate_digest": candidate_digest,
                "body": body[: self.config.max_candidate_chars],
                "body_tokens": body_tokens,
                "rule_id": str(row.get("rule_id") or "")[:80],
                "rule_kind": str(row.get("rule_kind") or row.get("kind") or "verified_teacher")[:80],
                "origin": str(row.get("origin") or "")[:120],
                "seed_provenance": str(row.get("seed_provenance") or "")[:80],
                "composition_parent_ids": [
                    str(item)[:80]
                    for item in (
                        row.get("composition_parent_ids")
                        if isinstance(row.get("composition_parent_ids"), (list, tuple))
                        else ((row.get("composition_parent_ids"),) if row.get("composition_parent_ids") else ())
                    )[:8]
                    if str(item).strip()
                ],
            }
            if key not in entries:
                added += 1
            entries[key] = entry
        ordered = sorted(
            entries.values(),
            key=lambda item: (
                int(item.get("body_tokens") or 10**9),
                str(item.get("problem") or ""),
                str(item.get("candidate_digest") or ""),
            ),
        )
        # Keep enough history for a theorem family while preventing a long
        # outer run from turning the persistent memory into an unbounded corpus.
        store["teacher_buffer"] = ordered[:512]
        store["teacher_buffer_schema"] = "jevops-router-teacher/v1"
        return added

    def _replay_teacher_rows(
        self,
        rows: list[dict[str, Any]],
        seen: set[str],
    ) -> int:
        """Re-admit persisted teachers through the current compiler.

        Replaying a body never trusts its old ``lake_ok`` bit.  This is the
        guard against stale Lake environments, changed imports, or a bad
        historical receipt becoming a training target merely because it was
        once successful.
        """

        if not self.config.teacher_replay:
            return 0
        store = ((self.memory.get("nca") or {}).get("autoencoder") or {})
        buffer = store.get("teacher_buffer") if isinstance(store, Mapping) else None
        if not isinstance(buffer, list):
            return 0
        source_digest = self._teacher_source_digest()
        source_tokens = max(1, ae.proof_body_token_count(self.source))
        candidates: list[dict[str, Any]] = []
        for item in buffer:
            if not isinstance(item, Mapping):
                continue
            if str(item.get("problem") or "")[:160] != self.problem[:160]:
                continue
            if str(item.get("source_digest") or "") != source_digest:
                continue
            body = str(item.get("body") or "").strip("\n")
            try:
                body_tokens = int(item.get("body_tokens") or 0)
            except (TypeError, ValueError):
                continue
            if not body or body_tokens <= 0 or body_tokens >= source_tokens:
                continue
            candidate = dict(item)
            candidate["body"] = body
            candidate["body_tokens"] = body_tokens
            candidates.append(candidate)
        candidates.sort(
            key=lambda item: (
                int(item.get("body_tokens") or 10**9),
                str(item.get("candidate_digest") or ""),
            )
        )
        before = len(rows)
        for item in candidates[: self.config.max_replay_teachers]:
            source_rule_id = str(item.get("rule_id") or "")[:80]
            candidate_digest = str(item.get("candidate_digest") or _digest(item.get("body")))[:80]
            replay_rule_id = "rule-" + _digest(
                {
                    "kind": "teacher_replay",
                    "problem": self.problem[:160],
                    "source_digest": source_digest,
                    "candidate_digest": candidate_digest,
                    "source_rule_id": source_rule_id,
                }
            )[:24]
            parent_ids = [source_rule_id] if source_rule_id else []
            stored_parents = item.get("composition_parent_ids") or ()
            if isinstance(stored_parents, str):
                stored_parents = (stored_parents,)
            parent_ids.extend(
                str(value)[:80]
                for value in stored_parents
                if str(value).strip() and str(value)[:80] not in parent_ids
            )
            rule_id = self._register_rule(
                {
                    "rule_id": replay_rule_id,
                    "kind": "teacher_replay",
                    "strategy": "teacher_replay",
                    "origin": "teacher_replay",
                    "candidate_digest": candidate_digest,
                    "parent_rule_ids": parent_ids[:8],
                }
            )
            self._push(
                rows,
                seen,
                item.get("body"),
                origin="teacher_replay",
                kind="teacher_replay",
                rationale="persisted teacher re-admitted by the current compiler",
                metadata={
                    "rule_id": rule_id,
                    "rule_kind": "teacher_replay",
                    "seed_provenance": item.get("seed_provenance"),
                    "composition_parent_ids": parent_ids[:8],
                },
            )
        return len(rows) - before

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

    def _model_diagnostics(
        self,
        model: LeanIRAutoencoder,
        example: Any,
        *,
        phase: str,
    ) -> dict[str, Any]:
        """Measure the autoencoder's own prediction, never a search winner.

        A verified router/local candidate can be used as the supervised target,
        but passing that candidate as ``predicted_ir`` would turn CE/cosine
        into target diagnostics rather than model diagnostics.  Decode and
        compile the model's actual prediction so the training receipt cannot
        reward a prediction the model did not make.
        """

        predicted_ir = model.predict_ir(example.text, source_ir=self._source_ir)
        predicted_source = ae.decode_lean_ir(predicted_ir)
        row = self._row(
            predicted_source,
            origin="autoencoder:" + str(phase),
            kind="model_prediction",
        )
        loss = loss_for_example(
            model,
            example,
            predicted_ir=predicted_ir,
            verifier_reward=1.0 if row.get("lake_ok") else 0.0,
            nca_memory=self.memory,
            minimality_reward=row.get("minimality_reward"),
        )
        return {
            "loss": loss.to_dict(),
            "row": row,
            "prediction": predicted_ir,
        }

    def _train(self, winner: Optional[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Record every outcome, then train only on verified strict cuts.

        The winner remains the primary teacher.  Other shorter, verified
        router/seed rules become bounded contrastive teachers, which gives the
        autoencoder more than a scalar reward while keeping failed proposals
        out of the target set.
        """

        for row in rows:
            reward = float(row.get("reward") or 0.0) if row.get("lake_ok") else 0.0
            candidate = {
                "id": row.get("id"),
                "ir_digest": _digest(row.get("ir") or {}),
                "n_tokens": row.get("body_tokens"),
                "rule_id": row.get("rule_id"),
            }
            try:
                record_autoencoder_nca_feedback(
                    self.memory,
                    problem=self.problem,
                    reward=reward,
                    theorem_ok=bool(row.get("lake_ok")),
                    tokens=int(row.get("body_tokens") or 0),
                    candidate=candidate,
                    advance_nca=False,
                )
                rule_id = str(row.get("rule_id") or "")
                if rule_id:
                    record_autoencoder_rule_feedback(
                        self.memory,
                        problem=self.problem,
                        rule=self._rules.get(rule_id, {"rule_id": rule_id, "kind": row.get("kind")}),
                        outcome={
                            "lake_ok": bool(row.get("lake_ok")),
                            "body_tokens": int(row.get("body_tokens") or 0),
                            "reward": reward,
                        },
                    )
            except Exception:
                # A policy-memory write must never turn a compiler receipt into
                # a false failure.  The row itself remains in the receipt.
                pass
        nca_step = advance_autoencoder_nca(self.memory, problem=self.problem)
        source_tokens = max(1, ae.proof_body_token_count(self.source))
        teacher_buffer_added = 0
        if winner is not None and winner.get("lake_ok"):
            try:
                if int(winner.get("body_tokens") or source_tokens) < source_tokens:
                    teacher_buffer_added = self._remember_verified_teachers(rows)
            except (TypeError, ValueError):
                teacher_buffer_added = 0
        if not self.config.train or winner is None or not winner.get("lake_ok"):
            return {
                "ok": True,
                "trained": False,
                "reason": "no_verified_winner_or_training_disabled",
                "nca": nca_step,
                "teacher_buffer_added": teacher_buffer_added,
            }
        if int(winner.get("body_tokens") or source_tokens) >= source_tokens:
            return {
                "ok": True,
                "trained": False,
                "reason": "no_strict_shortening",
                "nca": nca_step,
                "teacher_buffer_added": teacher_buffer_added,
            }
        try:
            store = self.memory.setdefault("nca", {}).setdefault("autoencoder", {})
            model = LeanIRAutoencoder.from_dict(store.get("training_state"), config=AutoencoderConfig())
            eligible: list[Mapping[str, Any]] = [
                row
                for row in rows
                if row.get("lake_ok")
                and isinstance(row.get("ir"), Mapping)
                and int(row.get("body_tokens") or source_tokens) < source_tokens
            ]
            eligible.sort(
                key=lambda row: (
                    int(row.get("body_tokens") or 10**9),
                    -float(row.get("reward") or 0.0),
                    str(row.get("id") or ""),
                )
            )
            teacher_rows: list[Mapping[str, Any]] = []
            seen_ir: set[str] = set()
            # Always put the chosen winner first; at most four additional
            # verified cuts provide rule supervision without a batch explosion.
            for row in [winner, *eligible]:
                if not isinstance(row, Mapping):
                    continue
                digest = _digest(row.get("ir") or {})
                if digest in seen_ir:
                    continue
                seen_ir.add(digest)
                teacher_rows.append(row)
                if len(teacher_rows) >= 5:
                    break
            examples = [
                coerce_training_example(
                    {
                        "id": f"{self.problem or 'router-tuning'}:{index}:{row.get('id')}",
                        "text": self.source,
                        "source_ir": self._source_ir,
                        "target_ir": row.get("ir"),
                        "problem": self.problem,
                        "rule_id": row.get("rule_id") or "",
                        "rule_features": [
                            str(row.get("kind") or "")[:80],
                            str(row.get("origin") or "")[:80],
                        ],
                    },
                    index,
                )
                for index, row in enumerate(teacher_rows)
            ]
            if not examples:
                return {
                    "ok": True,
                    "trained": False,
                    "reason": "no_verified_teacher_examples",
                    "nca": nca_step,
                    "teacher_buffer_added": teacher_buffer_added,
                }
            feedback_by_id: dict[str, Any] = {}
            rewards: dict[str, float] = {}
            nca_rewards: dict[str, float] = {}
            for example, row in zip(examples, teacher_rows):
                feedback = nca_feedback_for_example(
                    self.memory,
                    example,
                    candidate={
                        "verifier_reward": 1.0,
                        "typesafe_reward": None,
                        "rule_id": example.rule_id,
                    },
                )
                feedback_by_id[example.sample_id] = feedback
                rewards[example.sample_id] = _clip01(0.75 + 0.25 * _clip01(row.get("compression")))
                if feedback.active:
                    nca_rewards[example.sample_id] = feedback.reward
            primary = examples[0]
            model_snapshot = model.to_dict()
            before = self._model_diagnostics(model, primary, phase="before")
            train_report = model.train_batch(
                examples,
                rewards=rewards,
                nca_rewards=nca_rewards or None,
            )
            after = self._model_diagnostics(model, primary, phase="after")
            before_loss = before["loss"]
            after_loss = after["loss"]
            ce_rise = float(after_loss.get("cross_entropy") or 0.0) - float(
                before_loss.get("cross_entropy") or 0.0
            )
            cosine_drop = float(before_loss.get("cosine_similarity") or 0.0) - float(
                after_loss.get("cosine_similarity") or 0.0
            )
            update_accepted = ce_rise <= 0.02 and cosine_drop <= 0.02
            if not update_accepted:
                # A high verifier reward must not hide a representation
                # regression.  Roll back decoder/latent weights and keep the
                # failed update as an auditable training attempt.
                model = LeanIRAutoencoder.from_dict(model_snapshot, config=AutoencoderConfig())
                after = self._model_diagnostics(model, primary, phase="rollback")
                train_report["update_rejection"] = {
                    "cross_entropy_rise": ce_rise,
                    "cosine_drop": cosine_drop,
                    "cross_entropy_tolerance": 0.02,
                    "cosine_tolerance": 0.02,
                }
            # This is intentionally named separately: it measures the
            # verified candidate used as the teacher target, not the model's
            # prediction.  The public ``loss`` below is always ``after``.
            candidate_loss = loss_for_example(
                model,
                primary,
                predicted_ir=winner.get("ir") if isinstance(winner.get("ir"), Mapping) else None,
                verifier_reward=1.0,
                nca_memory=self.memory,
                minimality_reward=winner.get("minimality_reward"),
            )
            rule_examples = []
            for example, row in zip(examples, teacher_rows):
                target_loss = loss_for_example(
                    model,
                    example,
                    predicted_ir=row.get("ir") if isinstance(row.get("ir"), Mapping) else None,
                    verifier_reward=1.0,
                    nca_memory=self.memory,
                    minimality_reward=row.get("minimality_reward"),
                )
                rule_examples.append(
                    {
                        "sample_id": example.sample_id,
                        "rule_id": example.rule_id,
                        "kind": row.get("kind"),
                        "origin": row.get("origin"),
                        "body_tokens": row.get("body_tokens"),
                        "loss": target_loss.to_dict(),
                        "nca": feedback_by_id[example.sample_id].to_dict(),
                    }
                )
            train_report["loss"] = after["loss"]
            train_report["model_loss_before"] = before["loss"]
            train_report["candidate_target_loss"] = candidate_loss.to_dict()
            train_report["model_prediction"] = _compact_row(before["row"])
            train_report["model_prediction_after"] = _compact_row(after["row"])
            train_report["update_accepted"] = update_accepted
            train_report["teacher_example_count"] = len(examples)
            train_report["teacher_buffer_added"] = teacher_buffer_added
            train_report["rule_examples"] = rule_examples
            store["training_state"] = model.to_dict()
            return {
                "ok": True,
                "trained": bool(update_accepted),
                "step": model.step,
                "nca": nca_step,
                **train_report,
            }
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
        model_prediction_after: Optional[dict[str, Any]] = None
        model_loss_after: Optional[dict[str, Any]] = None
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
                design_hint=self.design_hint,
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
            route_attestation = getattr(self.router_generate, "last_route_attestation", None)
            if isinstance(route_attestation, Mapping):
                route_attestation = dict(route_attestation)
            else:
                route_attestation = None
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            composition_count = 0
            ir_crossover_count = 0
            hammer_count = 0
            replay_count = 0
            self._push(rows, seen, current_body, origin="current", kind="current")
            for seed in self.seed_candidates:
                seed_body = self._seed_body(seed.get("body"))
                seed_meta = dict(seed.get("metadata") or {})
                seed_rule_id = self._register_rule(
                    {
                        "kind": "historical_seed" if seed_meta.get("provenance") == "git_history" else "teacher_seed",
                        "origin": str(seed_meta.get("provenance") or "teacher_seed"),
                        "candidate_digest": str(seed_meta.get("body_digest") or _digest(seed_body)),
                        "commit": str(seed_meta.get("commit") or ""),
                        "path": str(seed_meta.get("path") or ""),
                    }
                )
                seed_metadata = {
                    "rule_id": seed_rule_id,
                    "rule_kind": "historical_seed" if seed_meta.get("provenance") == "git_history" else "teacher_seed",
                    "seed_provenance": str(seed_meta.get("provenance") or seed_meta.get("source") or "teacher"),
                    "seed_commit": str(seed_meta.get("commit") or ""),
                    "seed_path": str(seed_meta.get("path") or ""),
                    "claimed_tokens": seed_meta.get("claimed_tokens"),
                    "actual_tokens": seed_meta.get("actual_tokens"),
                    "body_digest": seed_meta.get("body_digest") or _digest(seed_body),
                }
                self._push(
                    rows,
                    seen,
                    seed_body,
                    origin="verified_seed",
                    kind="teacher_refactor",
                    rationale="candidate must re-pass the compiler before training",
                    metadata=seed_metadata,
                )
            replay_count = self._replay_teacher_rows(rows, seen)
            self._router_rows(plan, rows, seen, current)
            composition_count = self._compose_verified_rows(rows, seen, current)
            ir_crossover_count = self._crossover_ir_rows(rows, seen, current)
            hammer_count = self._hammer_sweep_rows(
                rows,
                seen,
                current,
                requested=plan.get("strategies") or (),
            )
            for kind, body, origin in self._local_rows(current_body, plan.get("strategies") or ()):
                rule_id = self._register_rule(
                    {
                        "kind": "local_strategy",
                        "strategy": origin,
                        "origin": "local_strategy",
                    }
                )
                self._push(
                    rows,
                    seen,
                    body,
                    origin="local:" + origin,
                    kind=kind,
                    metadata={"rule_id": rule_id, "rule_kind": "local_strategy"},
                )
            # Keep model-generated IR in the same bounded pool, but after the
            # verified-teacher crossover and hammer probes.  A tiny diagnostic
            # run must not crowd out the very compositions it is meant to
            # evaluate; the model still receives the admitted winner below.
            for candidate_ir in self._autoencoder_irs(current):
                self._push_ir(rows, seen, candidate_ir, origin="autoencoder", kind="ir_model")
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
            if isinstance(train_report.get("model_prediction_after"), Mapping):
                model_prediction_after = dict(train_report["model_prediction_after"])
            if isinstance(train_report.get("loss"), Mapping):
                model_loss_after = dict(train_report["loss"])
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
                        "route_attestation": route_attestation,
                    },
                    "candidate_count": len(rows),
                    "verified_count": len(verified),
                    "search": {
                        "hammer_enabled": self.config.hammer_sweep,
                        "hammer_candidates": hammer_count,
                        "composed_candidates": composition_count,
                        "ir_crossover_candidates": ir_crossover_count,
                        "replay_teachers": replay_count,
                    },
                    "round_winner": _compact_row(round_winner) if round_winner else None,
                    "accepted": improved,
                    "training": train_report,
                    "rules": [
                        {
                            "rule_id": row.get("rule_id"),
                            "kind": row.get("rule_kind"),
                            "origin": row.get("origin"),
                            "lake_ok": row.get("lake_ok"),
                            "body_tokens": row.get("body_tokens"),
                        }
                        for row in rows
                        if row.get("rule_id")
                    ],
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
                "seed_candidate_count": len(self.seed_candidates),
                "rule_count": len(self._rules),
                "accepted_rounds": sum(1 for row in history if row.get("accepted")),
                "router_errors": router_errors,
                "hammer_sweep": bool(self.config.hammer_sweep),
                "composed_candidates": sum(
                    int((row.get("search") or {}).get("composed_candidates") or 0) for row in history
                ),
                "ir_crossover_candidates": sum(
                    int((row.get("search") or {}).get("ir_crossover_candidates") or 0) for row in history
                ),
                "hammer_candidates": sum(
                    int((row.get("search") or {}).get("hammer_candidates") or 0) for row in history
                ),
                "replay_teachers": sum(
                    int((row.get("search") or {}).get("replay_teachers") or 0) for row in history
                ),
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
            "model_prediction_after": model_prediction_after,
            "model_body_tokens_after": (
                None if model_prediction_after is None else model_prediction_after.get("body_tokens")
            ),
            "model_loss_after": model_loss_after,
            "history": history,
            "search_summary": {
                "hammer_sweep": bool(self.config.hammer_sweep),
                "composed_candidates": sum(
                    int((row.get("search") or {}).get("composed_candidates") or 0) for row in history
                ),
                "ir_crossover_candidates": sum(
                    int((row.get("search") or {}).get("ir_crossover_candidates") or 0) for row in history
                ),
                "hammer_candidates": sum(
                    int((row.get("search") or {}).get("hammer_candidates") or 0) for row in history
                ),
                "replay_teachers": sum(
                    int((row.get("search") or {}).get("replay_teachers") or 0) for row in history
                ),
            },
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
    seed_candidates: Optional[Sequence[Any]] = None,
    design_hint: Optional[Mapping[str, Any]] = None,
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
        seed_candidates=seed_candidates,
        design_hint=design_hint,
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
