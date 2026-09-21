#!/usr/bin/env python3
"""Outer-loop routing: closed JSON actions, deterministic fallback, NCA snapshot.

Grok (outer) does not write Lean. Jev does not write Lean.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

# ``update_code`` is deliberately a closed outer action.  The action only
# describes a candidate; a consumer must provide the validator/updater hook
# that decides whether the candidate is allowed to touch the worktree.
ACTIONS = (
    "run",
    "nest_inner",
    "mint",
    "mint_tactic",
    "repair_tactic",
    "hypothesis_refactor",
    "skip_stem",
    "install_fold",
    "update_code",
    "patch",
    "stop",
)

# These are declarative design requests. They are intentionally kept here,
# beside the outer action parser, so a model can choose a bounded tactic
# search without being allowed to smuggle arbitrary code into the loop.
TACTIC_DESIGN_STRATEGIES = (
    "closed_tree",
    "guided_mca",
    "span_preserving",
    "closed_edits",
    "hammer_variants",
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
    "shortcut_closers",
    "goal_directed",
    "hammer_sweep",
    "compose_verified",
    "ir_crossover",
    "pca_mca_cross",
)


def split_after_prefix(
    src: str,
    prefix: str,
    *,
    name: str = "",
    error_cls: Any = ValueError,
    miss_msg: Optional[str] = None,
) -> str:
    """Require src.startswith(prefix); return the suffix. Never scans for :=."""

    if not isinstance(prefix, str) or not prefix:
        raise error_cls(f"{name}: prefix must be a non-empty string" if name else "prefix must be a non-empty string")
    if not isinstance(src, str) or not src:
        raise error_cls(f"{name}: src must be a non-empty string" if name else "src must be a non-empty string")
    if not src.startswith(prefix):
        raise error_cls(
            miss_msg
            or (f"{name}: src does not start with prefix" if name else "src does not start with prefix")
        )
    return src[len(prefix) :]


def strip_leading_prefixes(
    text: str,
    prefixes: Sequence[str],
    *,
    error_cls: Any = ValueError,
    empty_msg: str = "body is empty",
    miss_msg: str = "body does not start with a known prefix",
) -> str:
    if not isinstance(text, str) or not text:
        raise error_cls(empty_msg)
    for prefix in prefixes:
        if text.startswith(prefix):
            return text[len(prefix) :]
    raise error_cls(miss_msg)


def join_decl(
    statement: str,
    tactics: str,
    *,
    header: str = "",
    by_marker: str = " := by\n",
) -> str:
    core = str(statement) + by_marker + str(tactics).lstrip("\n")
    if isinstance(header, str) and header.strip():
        return header.rstrip() + "\n\n" + core
    return core


def head_lines(text: str, n: int) -> str:
    return "\n".join(str(text or "").splitlines()[: max(0, int(n))]).strip("\n")


def head_chars(value: Any, n: int) -> str:
    """First n characters. None is empty. n<=0 is empty."""

    text = "" if value is None else str(value)
    return text[: max(0, int(n))]


def tail_chars(value: Any, n: int) -> str:
    """Last n characters. None is empty. n<=0 is empty (not the whole string)."""

    text = "" if value is None else str(value)
    n = max(0, int(n))
    return text[-n:] if n else ""


def head_seq(items: Any, n: int) -> list[Any]:
    """First n items. None/empty is []. n<=0 is []."""

    return list(items or ())[: max(0, int(n))]


def tail_seq(items: Any, n: int) -> list[Any]:
    """Last n items. None/empty is []. n<=0 is [] (not the whole sequence)."""

    n = max(0, int(n))
    return list(items or ())[-n:] if n else []


def exc_head(exc: Any, n: int = 300) -> str:
    """str(exc) truncated for receipts/logs. Default 300."""

    return head_chars(exc, n)


def head_tail(
    value: Any,
    head: int,
    tail: int,
    *,
    sep: str = "\n...\n",
    limit: Optional[int] = None,
) -> str:
    """Keep head+tail chars with a middle marker when the text is long enough.

    ``limit`` defaults to head+tail. Shorter text is returned unchanged.
    """

    text = "" if value is None else str(value)
    h = max(0, int(head))
    t = max(0, int(tail))
    cap = h + t if limit is None else max(0, int(limit))
    if len(text) <= cap:
        return text
    if t == 0:
        return text[:h]
    if h == 0:
        return text[-t:]
    return text[:h] + sep + text[-t:]


def ensure_sys_path(path: Any) -> None:
    import sys

    text = str(path)
    if text and text not in sys.path:
        sys.path.insert(0, text)


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_canonical(payload: Any) -> str:
    return digest_hex(canonical_bytes(payload))


def exclude_named(
    records: Sequence[Mapping[str, Any]],
    query: str,
    *,
    name_key: str = "name",
) -> list[Mapping[str, Any]]:
    want = str(query or "")
    return [row for row in records if str(row.get(name_key) or "") != want]


def unique_names(
    records: Sequence[Mapping[str, Any]],
    *,
    name_key: str = "name",
) -> list[str]:
    return [str(row.get(name_key) or "") for row in records]


def require_unique_n(
    records: Sequence[Mapping[str, Any]],
    n: int,
    *,
    name_key: str = "name",
    error_cls: Any = ValueError,
    fmt: str = "must contain {n} uniquely named records",
) -> list[str]:
    """Require exactly n uniquely named records. Returns names in order."""

    names = unique_names(records, name_key=name_key)
    want = int(n)
    if len(names) != want or len(set(names)) != want:
        raise error_cls(fmt.format(n=want))
    return names


def require_len(
    items: Any,
    n: int,
    *,
    error_cls: Any = ValueError,
    fmt: str = "expected {n} items, got {got}",
) -> Any:
    """Require ``len(items) == n``. Returns items unchanged."""

    got = len(items)
    want = int(n)
    if got != want:
        raise error_cls(fmt.format(n=want, got=got))
    return items


def digest_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_jsonl_objects(
    path: Path,
    *,
    expected_digest: Optional[str] = None,
    expected_n: Optional[int] = None,
    required_fields: Sequence[str] = (),
    mismatch_exc: Any = ValueError,
    record_exc: Any = ValueError,
) -> tuple[bytes, str, list[dict[str, Any]]]:
    """Load JSONL objects. Optional digest/count/field checks. No Lean."""

    raw = Path(path).read_bytes()
    digest = digest_hex(raw)
    if expected_digest is not None and digest != expected_digest:
        raise mismatch_exc(f"JSONL hash mismatch: {digest} != {expected_digest}")
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if expected_n is not None and len(records) != int(expected_n):
        raise record_exc(f"JSONL must contain {expected_n} records, got {len(records)}")
    required = tuple(required_fields)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise record_exc(f"record {index} is not an object")
        missing = [field for field in required if field not in record]
        if missing:
            raise record_exc(f"record {index} missing fields: {missing}")
    return raw, digest, records


def parse_action(text: str, *, actions: tuple[str, ...] = ACTIONS) -> dict[str, Any]:
    """First JSON object in outer-loop text; fail closed to action=run."""

    source = str(text or "")
    decoder = json.JSONDecoder()
    raw: Any = None
    saw_object_start = False
    for index, char in enumerate(source):
        if char != "{":
            continue
        saw_object_start = True
        try:
            candidate, _end = decoder.raw_decode(source, index)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            raw = candidate
            break
    if raw is None:
        return {"action": "run", "reason": "bad_json" if saw_object_start else "no_json"}
    action = str(raw.get("action") or "run").strip()
    if action not in actions:
        return {"action": "run", "reason": "unknown_action"}
    out = {"action": action, "reason": str(raw.get("reason") or "router")}
    for key in (
        "stem",
        "name",
        "old",
        "new",
        "family",
        "strategy",
        "target",
        "hypothesis",
        "constraints",
        "evaluation",
        "focus",
        "path",
        "file",
        "diff",
    ):
        if key in raw:
            out[key] = str(raw.get(key) or "")
    if "keep" in raw and isinstance(raw["keep"], list):
        out["keep"] = [str(item) for item in raw["keep"]]
    if "changes" in raw and isinstance(raw["changes"], list):
        changes: list[dict[str, str]] = []
        for item in raw["changes"]:
            if not isinstance(item, dict):
                continue
            row: dict[str, str] = {}
            for key in ("path", "file", "old", "new"):
                if key in item:
                    row[key] = str(item.get(key) or "")
            if row:
                changes.append(row)
        out["changes"] = changes
    if "count" in raw:
        try:
            out["count"] = int(raw["count"])
        except (TypeError, ValueError):
            out["count"] = 1
    return out


def deterministic_route(
    *,
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    stalled: bool,
    memory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Closed-vocab next action from gaps + last oracle rows (no grok)."""

    failed = [
        row
        for row in last_lake
        if row.get("ok") is False and str(row.get("kind") or "").startswith("port_")
    ]
    if failed:
        kind = str(failed[0].get("kind") or "")
        stem = kind[len("port_") :] if kind.startswith("port_") else kind
        return {
            "action": "skip_stem",
            "stem": stem.split("_pipeline")[0],
            "name": str(failed[0].get("name") or ""),
            "reason": "lake_failed_port",
        }
    # A blacklist is a negative observation, not a permanent ban.  Once a
    # theorem has failed a portable fold, reserve one declarative repair pass
    # before spending another outer turn on the same generic portfolio.  The
    # inner loop supplies the concrete body and Lake is still the only gate.
    prior_designs = list(((memory or {}).get("nca") or {}).get("tactic_design_history") or [])
    attempted_repairs = {
        (
            str(row.get("name") or ""),
            str(row.get("repair_stem") or "").removeprefix("port_"),
        )
        for row in prior_designs
        if isinstance(row, Mapping)
        and str(row.get("action") or "") == "repair_tactic"
        and not int(row.get("verified_repairs") or 0)
    }
    for gap in gaps:
        name = str(gap.get("name") or "")
        if not name:
            continue
        for raw_stem in list(gap.get("failed_stems") or ()):
            stem = str(raw_stem or "").strip()
            if stem.startswith("port_"):
                stem = stem[len("port_") :]
            if not stem or (name, stem) in attempted_repairs:
                continue
            top_help = list(gap.get("top_help") or [])
            residual = str(top_help[0].get("residual") or "") if top_help else ""
            strategy = {
                "use_then_exact": "join_consecutive_exacts",
                "repeated_simp_list": "collapse_simp_at",
                "intro_then_simp_all": "closed_edits",
                "apply_seq_assumption": "join_consecutive_applies",
            }.get(residual, "closed_edits")
            return {
                "action": "repair_tactic",
                "name": name,
                "stem": stem,
                "family": residual or "search_space",
                "strategy": strategy,
                "focus": f"revalidate the blacklisted portable stem {stem}",
                "reason": "revalidate_blacklisted_portable_stem",
            }
    # Once the normal tactic/fold portfolio has stalled, use the next outer
    # turn for an explicit, testable hypothesis rather than silently repeating
    # the same search.  The inner loop still owns candidate construction and
    # Lake verification; this branch only supplies a bounded research prompt.
    if stalled:
        target = next(
            (str(gap.get("name") or "") for gap in gaps if str(gap.get("name") or "")),
            "",
        )
        gap = next(
            (gap for gap in gaps if str(gap.get("name") or "") == target),
            {},
        )
        top_help = list(gap.get("top_help") or [])
        residual = str(top_help[0].get("residual") or "") if top_help else ""
        if target:
            return {
                "action": "hypothesis_refactor",
                "name": target,
                "family": residual or "search_space",
                "strategy": "guided_mca",
                "hypothesis": (
                    "A structure-preserving reduction around "
                    f"{residual or 'the dominant residual'} may shorten the proof without changing its theorem shape."
                ),
                "constraints": "preserve the statement, binders, branch coverage, and no-sorry policy",
                "evaluation": "Lake theorem/module success, no sorry, then body-token reduction",
                "reason": "stalled_outer_hypothesis_probe",
            }
        return {"action": "stop", "reason": "no_token_cut"}
    for gap in gaps:
        mints = list((gap.get("proposed") or {}).get("mint") or gap.get("keep_structure") or [])
        if mints:
            return {
                "action": "mint",
                "stem": str(mints[0]),
                "name": str(gap.get("name") or ""),
                "reason": "autoresearch_mint",
            }
    # The fold catalog is exhausted for this gap. Schedule a theorem-specific
    # design pass; the inner compiler gate creates the actual tactic body.
    for gap in gaps:
        name = str(gap.get("name") or "")
        if name:
            top_help = list(gap.get("top_help") or [])
            residual = str(top_help[0].get("residual") or "") if top_help else ""
            return {
                "action": "mint_tactic",
                "name": name,
                "family": residual,
                "strategy": "closed_edits",
                "reason": "autoresearch_design_pass",
            }
    if last_lake and all(str(row.get("skipped") or "") == "nca_budget" for row in last_lake):
        return {"action": "stop", "reason": "nca_budget"}
    if stalled:
        return {"action": "stop", "reason": "no_token_cut"}
    return {"action": "nest_inner", "reason": "continue_typesafe"}


def route_next(
    *,
    gaps: list[dict[str, Any]],
    last_lake: list[dict[str, Any]],
    stalled: bool,
    llm: bool = False,
    memory: Optional[Mapping[str, Any]] = None,
    generate_fn: Optional[Any] = None,
    prompt: str = "",
    charge_fn: Optional[Any] = None,
    ledger: Any = None,
) -> dict[str, Any]:
    """Halt/budget stop, else deterministic route, else optional LLM JSON action."""

    nca = nca_status(memory)
    if nca.get("budget_dead"):
        return {"action": "stop", "reason": "nca_budget", "router": "nca"}
    if nca.get("halt"):
        return {"action": "stop", "reason": "nca_halt", "router": "nca"}
    fallback = deterministic_route(
        gaps=gaps,
        last_lake=last_lake,
        stalled=stalled,
        memory=memory,
    )
    if not llm or generate_fn is None:
        fallback["router"] = "deterministic"
        return fallback
    try:
        text = generate_fn(prompt)
        if isinstance(text, tuple):
            text = text[0]
    except Exception as exc:
        fallback["router"] = "llm_router_error"
        fallback["error"] = exc_head(exc, 240)
        return fallback
    action = parse_action(str(text))
    action["router"] = "llm_router"
    action["raw_head"] = head_chars(text, 240)
    if fallback.get("action") == "skip_stem" and action.get("action") not in {"skip_stem", "stop"}:
        # A fresh Lake failure is an immediate quarantine signal.  Do not let
        # the model spend the next turn repeating the same rejected draft.
        original = dict(action)
        action = dict(fallback)
        action.update(
            {
                "source_action": str(original.get("action") or "run"),
                "router": "llm_router",
                "raw_head": original.get("raw_head") or head_chars(text, 240),
                "reason": "lake_failure_quarantine_prioritized",
            }
        )
    elif (
        fallback.get("action") == "repair_tactic"
        and action.get("action") not in {"repair_tactic", "stop"}
    ):
        # A model may prefer another generic mint after seeing a blacklist.
        # That is useful only after the known negative stem has had a fresh
        # compiler-backed repair attempt.  Promote the deterministic repair
        # request while retaining the model's rationale as the diagnostic
        # focus; the inner loop still decides whether any replacement works.
        original = dict(action)
        action = dict(fallback)
        action.update(
            {
                "source_action": str(original.get("action") or "run"),
                "router": "llm_router",
                "raw_head": original.get("raw_head") or head_chars(text, 240),
                "focus": str(
                    original.get("focus")
                    or fallback.get("focus")
                    or "repair and recompile the known failed portable stem"
                ),
                "reason": "blacklist_repair_prioritized",
            }
        )
    if stalled and action.get("action") not in {"stop", "hypothesis_refactor"}:
        # A saturated model occasionally returns another mint/run action even
        # after being told to form a hypothesis. Promote that rationale into a
        # closed hypothesis request so the reserved outer turn cannot silently
        # repeat an exhausted tactic portfolio. The inner loop remains the
        # only component allowed to construct and verify Lean candidates.
        fallback_hypothesis = deterministic_route(
            gaps=gaps,
            last_lake=last_lake,
            stalled=True,
            memory=memory,
        )
        if fallback_hypothesis.get("action") == "hypothesis_refactor":
            original = dict(action)
            strategy = str(action.get("strategy") or fallback_hypothesis.get("strategy") or "guided_mca")
            if strategy not in TACTIC_DESIGN_STRATEGIES:
                strategy = str(fallback_hypothesis.get("strategy") or "guided_mca")
            action = dict(fallback_hypothesis)
            action.update(
                {
                    "action": "hypothesis_refactor",
                    "name": str(original.get("name") or fallback_hypothesis.get("name") or ""),
                    "family": str(original.get("family") or fallback_hypothesis.get("family") or ""),
                    "strategy": strategy,
                    "hypothesis": str(
                        original.get("hypothesis")
                        or original.get("reason")
                        or fallback_hypothesis.get("hypothesis")
                        or "Test a new structure-preserving refactoring hypothesis."
                    ),
                    "constraints": str(
                        original.get("constraints")
                        or "preserve the theorem statement, binders, branches, and no-sorry policy"
                    ),
                    "evaluation": str(
                        original.get("evaluation")
                        or "Lake theorem/module success, no sorry, then body-token reduction"
                    ),
                    "source_action": str(original.get("action") or "run"),
                    "router": "llm_router",
                    "raw_head": original.get("raw_head") or head_chars(text, 240),
                    "reason": "stalled_action_promoted_to_hypothesis",
                }
            )
    if isinstance(memory, dict):
        try:
            charger = charge_fn
            if charger is None:
                from jevops.nca import charge_budget

                charger = charge_budget
            charger(memory, ledger=ledger, event="grok")
        except Exception:
            pass
    return action


def load_ipfs_accelerate_router(*, search_paths: Optional[Sequence[Any]] = None) -> Any:
    """Load the JevOps router facade, with legacy external opt-in.

    The in-tree :mod:`jevops.llm_router` has the narrow API used by JevOps and
    is the default, so an Endomorphosis sibling checkout is not required.
    Set ``JEVOPS_USE_EXTERNAL_ROUTER=1`` (or pass ``search_paths``) only for
    compatibility with the deprecated ``ipfs_accelerate_py`` router.  The
    legacy path remains lazy and fail-closed.
    """

    import importlib
    import os
    import sys
    import warnings

    use_external = str(os.environ.get("JEVOPS_USE_EXTERNAL_ROUTER") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not use_external and not search_paths:
        from . import llm_router

        return llm_router
    warnings.warn(
        "ipfs_accelerate_py.llm_router is deprecated; use jevops.llm_router "
        "or set JEVOPS_USE_EXTERNAL_ROUTER=1 only for compatibility",
        DeprecationWarning,
        stacklevel=2,
    )

    try:
        return importlib.import_module("ipfs_accelerate_py.llm_router")
    except ModuleNotFoundError as initial:
        candidates: list[Path] = []
        values = list(search_paths or ())
        values.extend(
            value
            for value in (
                os.environ.get("JEVOPS_IPFS_ACCELERATE_PATH"),
                os.environ.get("IPFS_ACCELERATE_PY_PATH"),
            )
            if value
        )
        candidates.extend(Path(value).expanduser() for value in values)
        candidates.extend(
            [
                Path.cwd() / "external" / "ipfs_accelerate",
                Path(__file__).resolve().parents[2] / "external" / "ipfs_accelerate",
            ]
        )
        seen: set[str] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if (resolved / "ipfs_accelerate_py").is_dir():
                import_root = resolved
            elif resolved.name == "ipfs_accelerate_py" and resolved.is_dir():
                import_root = resolved.parent
            else:
                continue
            key = str(import_root)
            if key in seen:
                continue
            seen.add(key)
            if key not in sys.path:
                sys.path.insert(0, key)
            try:
                return importlib.import_module("ipfs_accelerate_py.llm_router")
            except ModuleNotFoundError:
                continue
        raise ImportError(
            "deprecated ipfs_accelerate_py.llm_router is unavailable; use "
            "jevops.llm_router or set JEVOPS_IPFS_ACCELERATE_PATH"
        ) from initial


def _router_text(value: Any) -> str:
    """Normalize the router's string/tuple/OpenAI-compatible return shapes."""

    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)) and value:
        return _router_text(value[0])
    if isinstance(value, Mapping):
        for key in ("text", "generated_text", "content", "response"):
            if key in value:
                return str(value[key] or "")
        choices = value.get("choices")
        if isinstance(choices, list) and choices:
            return _router_text(choices[0])
        message = value.get("message")
        if message is not None:
            return _router_text(message)
    for key in ("text", "generated_text", "content"):
        value_attr = getattr(value, key, None)
        if value_attr is not None:
            return str(value_attr)
    choices = getattr(value, "choices", None)
    if isinstance(choices, (tuple, list)) and choices:
        return _router_text(choices[0])
    message = getattr(value, "message", None)
    if message is not None:
        return _router_text(message)
    return str(value or "")


def make_llm_router_generate(
    *,
    router: Any = None,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    verify_route: bool = False,
    **kwargs: Any,
) -> Any:
    """Return a ``generate(prompt)`` callable backed by the router facade.

    The import is lazy.  ``jevops.llm_router`` is the default and tests may
    still inject a fixture router.  When ``verify_route`` is true and the
    router exposes ``get_last_generation_trace()``, the requested
    provider/model are checked against the route actually used.  This matters
    for proof search: an unverified fallback response must not be mistaken for
    a response from the configured tuning model.
    """

    def generate(prompt: str) -> str:
        module = router or load_ipfs_accelerate_router()
        call_kwargs = dict(kwargs)
        if model_name is not None:
            call_kwargs.setdefault("model_name", model_name)
        if provider is not None:
            call_kwargs.setdefault("provider", provider)
        result = _router_text(module.generate_text(str(prompt), **call_kwargs))
        trace_getter = getattr(module, "get_last_generation_trace", None)
        trace: Mapping[str, Any] = {}
        if callable(trace_getter):
            try:
                candidate_trace = trace_getter()
            except Exception:
                candidate_trace = {}
            if isinstance(candidate_trace, Mapping):
                trace = dict(candidate_trace)

        expected_provider = str(provider or "").strip().lower().replace("-", "_")
        actual_provider = str(
            trace.get("effective_provider_name")
            or trace.get("provider_name")
            or ""
        ).strip().lower().replace("-", "_")
        provider_aliases = {"codex": "codex_cli", "copilot": "copilot_cli"}
        expected_provider = provider_aliases.get(expected_provider, expected_provider)
        actual_provider = provider_aliases.get(actual_provider, actual_provider)
        expected_model = str(model_name or "").strip()
        actual_model = str(
            trace.get("effective_model_name")
            or trace.get("model_name")
            or ""
        ).strip()

        attestation: dict[str, Any] = {
            "requested_provider": expected_provider or None,
            "requested_model": expected_model or None,
            "actual_provider": actual_provider or None,
            "actual_model": actual_model or None,
            "trace_available": bool(trace),
            "verified": False,
        }
        if verify_route:
            # The production accelerator router is expected to expose a
            # trace.  A fixture callback may omit it, so only enforce this
            # requirement for the real module (or a router that supplied a
            # trace).  A supplied trace with a mismatch always fails closed.
            is_accelerate_router = str(getattr(module, "__name__", "")) == "ipfs_accelerate_py.llm_router"
            if trace or is_accelerate_router:
                provider_ok = not expected_provider or actual_provider == expected_provider
                model_ok = not expected_model or actual_model == expected_model
                attestation["verified"] = bool(provider_ok and model_ok)
                if not attestation["verified"]:
                    generate.last_route_attestation = attestation
                    raise RuntimeError(
                        "llm router route mismatch: "
                        f"requested {expected_provider or 'auto'}/{expected_model or 'default'}, "
                        f"used {actual_provider or 'unknown'}/{actual_model or 'unknown'}"
                    )
        generate.last_route_attestation = attestation
        return result

    generate.last_route_attestation = {
        "requested_provider": str(provider or "").strip() or None,
        "requested_model": str(model_name or "").strip() or None,
        "actual_provider": None,
        "actual_model": None,
        "trace_available": False,
        "verified": False,
    }
    return generate


def ipfs_accelerate_generate(
    prompt: str,
    *,
    router: Any = None,
    model_name: Optional[str] = None,
    provider: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """Generate one outer-loop response through ``ipfs_accelerate_py``."""

    return make_llm_router_generate(
        router=router,
        model_name=model_name,
        provider=provider,
        **kwargs,
    )(prompt)


def compact_gaps(gaps: Sequence[Mapping[str, Any]], *, help_n: int = 2) -> list[dict[str, Any]]:
    return [
        {
            "name": item.get("name"),
            "proposed": item.get("proposed"),
            "keep_structure": item.get("keep_structure"),
            "failed_stems": list(item.get("failed_stems") or [])[:8],
            "top_help": (item.get("top_help") or [])[: int(help_n)],
        }
        for item in gaps
    ]


def compact_lake(rows: Sequence[Mapping[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "name": row.get("name"),
            "kind": row.get("kind"),
            "ok": row.get("ok"),
            "tokens": row.get("tokens"),
            "skipped": row.get("skipped"),
            "error_class": row.get("error_class"),
        }
        for row in list(rows)[: int(limit)]
    ]


def seed_runtime(
    memory: dict[str, Any],
    *,
    seed_fn: Any,
    overlay_fn: Any,
    keepbest_fn: Optional[Any] = None,
) -> None:
    """Seed board, overlay live status, optional keep-best. Fail closed."""

    try:
        seed_fn(memory)
        overlay_fn(memory)
        if keepbest_fn is not None:
            try:
                keepbest_fn(memory)
            except Exception:
                pass
    except Exception:
        pass


def memory_counts(memory: Mapping[str, Any]) -> dict[str, int]:
    return {
        "n_successes": len(memory.get("successes") or []),
        "n_failures": len(memory.get("failures") or []),
        "n_blacklist": len(memory.get("blacklist") or []),
    }


def board_total(board: Mapping[str, int]) -> int:
    return int(sum(board.values()))


def lookup_named(
    records: Sequence[Mapping[str, Any]],
    name: str,
    *,
    error_cls: Optional[Any] = None,
    miss: str = "",
) -> Optional[Mapping[str, Any]]:
    want = str(name or "")
    hit = next((item for item in records if str(item.get("name") or "") == want), None)
    if hit is None and error_cls is not None:
        raise error_cls(miss or f"unknown name: {want}")
    return hit


def without_keys(mapping: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    deny = {str(key) for key in keys}
    return {key: value for key, value in dict(mapping or {}).items() if str(key) not in deny}


def unique_extend(dest: list[Any], extra: Sequence[Any], *, key_fn: Any) -> list[Any]:
    """Append extra items whose key_fn is not already in dest."""

    seen = {key_fn(item) for item in dest}
    for item in extra or ():
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        dest.append(item)
    return dest


def last_component(text: str, *, sep: str = ".") -> str:
    blob = str(text or "")
    return blob.rsplit(sep, 1)[-1] if blob else ""


def nonempty_strs(items: Sequence[Any]) -> list[str]:
    return [str(item) for item in items or () if str(item)]


def overlay_str(base: Mapping[str, Any], *overlays: Mapping[str, Any]) -> dict[str, str]:
    """Stringify base keys; overlays may replace existing keys only."""

    out = {str(key): "" if value is None else str(value) for key, value in dict(base or {}).items()}
    for overlay in overlays:
        if not overlay:
            continue
        for key, value in dict(overlay).items():
            if key in out and value is not None:
                out[str(key)] = str(value)
    return out


def read_bytes_if(path: Any, default: bytes = b"") -> bytes:
    dest = Path(path)
    return dest.read_bytes() if dest.is_file() else default


def env_copy(
    extra: Optional[Mapping[str, Any]] = None,
    *,
    base: Optional[Mapping[str, str]] = None,
) -> dict[str, str]:
    """Copy os.environ (or base) and stringify extra keys."""

    import os

    out = dict(os.environ if base is None else base)
    for key, value in dict(extra or {}).items():
        out[str(key)] = str(value)
    return out


def under_or_tmp(root: Any, *parts: str, tmp_name: str = "") -> Path:
    """root/parts when root is set, else tempfile/tmp_name. Creates the directory."""

    import tempfile

    if root is not None:
        dest = Path(root).joinpath(*(str(part) for part in parts))
    else:
        dest = Path(tempfile.gettempdir()) / str(tmp_name or (parts[-1] if parts else "tmp"))
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def posix_slash(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def path_to_dots(path: str, *, suffix: str = ".py") -> str:
    text = posix_slash(path)
    if suffix and text.endswith(suffix):
        text = text[: -len(suffix)]
    return text.replace("/", ".")


def require_str(
    value: Any,
    *,
    error_cls: Any = ValueError,
    empty: str = "must be a non-empty string",
) -> str:
    if not isinstance(value, str) or not value:
        raise error_cls(empty)
    return value


def as_str(value: Any, default: str = "") -> str:
    """Return value when it is a str, else default."""

    return value if isinstance(value, str) else default


def nonempty(value: Any) -> bool:
    """True when str(value) has non-whitespace content."""

    return bool(str(value or "").strip())


def require_startswith(
    text: str,
    prefix: str,
    *,
    error_cls: Any = ValueError,
    fmt: str = "{name}: does not start with prefix",
    name: str = "",
) -> str:
    """Require text.startswith(prefix). Returns text unchanged."""

    raw = str(text)
    if not raw.startswith(str(prefix)):
        raise error_cls(fmt.format(name=name, prefix=prefix))
    return raw


def loads_json(text: Any, *, default: Any = None) -> Any:
    """json.loads, or ``default`` when text is None/empty."""

    if text in (None, ""):
        return default
    return json.loads(text)


def read_json(
    path: Any,
    *,
    encoding: str = "utf-8",
    require_object: bool = True,
    error_cls: Any = ValueError,
    not_object: str = "JSON is not an object",
) -> Any:
    """Load JSON from a file. Optional dict check. Missing file raises OSError."""

    payload = json.loads(read_text(path, encoding=encoding))
    if require_object and not isinstance(payload, dict):
        raise error_cls(not_object)
    return payload


def read_json_if(
    path: Any,
    *,
    default: Any = None,
    encoding: str = "utf-8",
    require_object: bool = True,
    error_cls: Any = ValueError,
    not_object: str = "JSON is not an object",
) -> Any:
    dest = Path(path)
    if not dest.is_file():
        return default
    return read_json(
        dest,
        encoding=encoding,
        require_object=require_object,
        error_cls=error_cls,
        not_object=not_object,
    )


def overlay_attr(
    base: Mapping[str, Any],
    extra: Mapping[str, Any],
    *,
    attr: str = "what",
) -> dict[str, str]:
    """Copy base strings; overlay extra[key][attr] when present."""

    out = {str(key): str(value) for key, value in dict(base or {}).items()}
    for key, spec in dict(extra or {}).items():
        if isinstance(spec, Mapping):
            val = spec.get(attr)
            if val:
                out[str(key)] = str(val)
    return out


def require_single_token(
    text: str,
    *,
    error_cls: Any = ValueError,
    empty: str = "must be a nonempty string",
    multi_fmt: str = "expected a single token, got {text!r}",
) -> str:
    if not isinstance(text, str) or not text.strip():
        raise error_cls(empty)
    stripped = text.strip()
    first = stripped.split()[0]
    if stripped != first:
        raise error_cls(multi_fmt.format(text=text))
    return first


def exc_name(exc: BaseException) -> str:
    return type(exc).__name__


def exc_text(exc: BaseException, *, sep: str = ": ") -> str:
    return f"{exc_name(exc)}{sep}{exc}"


def tagged_exc(tag: str, exc: BaseException, *, sep: str = ":") -> str:
    return f"{tag}{sep}{exc_name(exc)}"


def closed_fail(error: str, *, arena_score: Any = None, **fields: Any) -> dict[str, Any]:
    """Fail-closed JSON without an exception. Never an Arena score."""

    out: dict[str, Any] = {"ok": False, "error": str(error), "arena_score": arena_score}
    out.update(fields)
    return out


def failed_check(exc: BaseException, *, arena_score: Any = None, **fields: Any) -> dict[str, Any]:
    """Fail-closed JSON payload. Never an Arena score."""

    return closed_fail(str(exc), arena_score=arena_score, error_type=exc_name(exc), **fields)


def bullet_lines(
    items: Sequence[Any],
    *,
    prefix: str = "- ",
    limit: Optional[int] = None,
    fmt: Any = None,
    empty: str = "",
) -> str:
    seq = list(items or ())
    if limit is not None:
        seq = seq[: max(0, int(limit))]
    render = fmt if fmt is not None else (lambda item: item)
    lines = [f"{prefix}{render(item)}" for item in seq]
    return "\n".join(str(line) for line in lines) if lines else empty


def mapped_nonempty(items: Sequence[Any], fn: Any) -> set[str]:
    return {str(value) for value in (fn(item) for item in items or ()) if value}


def utc_stamp(*, fmt: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    return now.strftime(fmt) if fmt else now.isoformat()


def remap_get(
    pack: Mapping[str, Any],
    mapping: Mapping[str, str],
    *,
    lists: Sequence[str] = (),
) -> dict[str, Any]:
    """Copy pack[src] onto dest. Dest names in lists become list(value or [])."""

    list_dests = {str(name) for name in lists}
    row = dict(pack or {})
    out: dict[str, Any] = {}
    for dest, src in dict(mapping or {}).items():
        val = row.get(src)
        out[str(dest)] = list(val or []) if str(dest) in list_dests else val
    return out


def closed_evidence(**extra: Any) -> dict[str, Any]:
    """Evidence flags that never claim Lean, docker0, Track 2, or Arena scores."""

    out: dict[str, Any] = {
        "called_docker0": False,
        "official_track2": False,
        "arena_score": None,
        "jev_writes_lean": False,
    }
    out.update(extra)
    return out


def namespace(**kwargs: Any) -> Any:
    """Closed attribute bag (argparse-compatible). No Lean."""

    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


def inner_budget(
    args: Any,
    *,
    min_steps: int,
    rounds_key: str = "rounds",
    depth_key: str = "nest_depth",
    default_depth: int = 3,
) -> tuple[int, int]:
    """(max_steps, max_depth) from args. No Lean."""

    max_steps = max(int(arg_value(args, rounds_key, 1, cast=int) or 1), int(min_steps))
    max_depth = int(arg_value(args, depth_key, default_depth, cast=int) or default_depth)
    return max_steps, max_depth


def token_map(
    records: Sequence[Mapping[str, Any]],
    *,
    token_fn: Any,
    body_fn: Optional[Any] = None,
) -> dict[str, int]:
    """name → token count. body_fn/token_fn injected. Fail closed per row."""

    out: dict[str, int] = {}
    for rec in records:
        name = str(rec.get("name") or "")
        if not name:
            continue
        try:
            body = body_fn(rec) if body_fn is not None else str(rec.get("src") or "")
            if not body:
                continue
            out[name] = int(token_fn(body))
        except Exception:
            continue
    return out


def arg_value(args: Any, key: str, default: Any, *, cast: Any = None) -> Any:
    """getattr with None→default, optional cast. No Lean."""

    raw = default
    if args is not None:
        raw = getattr(args, key, default)
    if raw is None:
        raw = default
    return cast(raw) if cast is not None else raw


def safe_call(fn: Any, *args: Any, default: Any = None, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except Exception:
        return default


def starting_body(
    fallback: str,
    directory: Any,
    name: str,
    *,
    glob_fmt: str = "random-best-{safe}-*.lean",
    extras: Optional[Mapping[str, str]] = None,
) -> str:
    """Keep-best glob, then a named extra file, else fallback. Does not generate Lean."""

    if directory is None:
        return fallback
    out = Path(directory)
    body = read_shortest_glob(out, glob_fmt.format(safe=file_stem(name or "canary"), name=name))
    if body is not None:
        return body
    fname = dict(extras or {}).get(str(name or ""))
    if fname:
        path = out / fname
        if path.is_file():
            return path.read_text(encoding="utf-8").strip("\n")
    return fallback


def file_stem(name: str, *, limit: int = 80, empty: str = "canary") -> str:
    """Filesystem-safe stem from a theorem/problem name."""

    return str(name or empty).replace("/", "_")[: int(limit)]


def load_json_object(path: Path) -> dict[str, Any]:
    """Fail closed to {}. No Lean."""

    target = Path(path)
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def read_shortest_glob(directory: Path, pattern: str, *, encoding: str = "utf-8") -> Optional[str]:
    """Read the shortest glob_stem_int hit. None if missing."""

    bests = glob_stem_int(directory, pattern)
    if not bests:
        return None
    return bests[0][1].read_text(encoding=encoding).strip("\n")


def merge_keep_best(
    directory: Path,
    names: Sequence[str],
    *,
    latest_json: str = "",
    glob_fmt: str = "random-best-{safe}-*.lean",
    extras: Optional[Mapping[str, tuple[str, int]]] = None,
) -> dict[str, int]:
    """JSON canary tokens, then glob files, then optional named extras."""

    out = Path(directory)
    board: dict[str, int] = {}
    if latest_json:
        board.update(tokens_from_canaries(load_json_object(out / latest_json), names=names))
    extra = dict(extras or {})
    for name in names:
        safe = file_stem(name)
        bests = glob_stem_int(out, glob_fmt.format(safe=safe, name=name))
        if bests:
            file_tok = int(bests[0][0])
            board[name] = min(int(board.get(name) or file_tok), file_tok)
            continue
        if name in extra:
            fname, tok = extra[name]
            if (out / fname).is_file():
                board[name] = min(int(board.get(name) or int(tok)), int(tok))
    return board


def write_best_body(
    directory: Path,
    name: str,
    tokens: int,
    body: str,
    *,
    prefix: str = "random-best",
    suffix: str = ".lean",
) -> Path:
    """Write a keep-best body next to other evidence. Does not generate Lean."""

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{prefix}-{file_stem(name)}-{int(tokens)}{suffix}"
    path.write_text(str(body) + "\n", encoding="utf-8")
    return path


def landscape_rows(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compact analysis rows for canary evidence. No Lean."""

    rows: list[dict[str, Any]] = []
    for item in items:
        families = list(item.get("families") or [])
        counts = dict(item.get("counts") or {})
        rows.append(
            {
                "name": item.get("name"),
                "source": item.get("source"),
                "n_tokens": item.get("n_tokens"),
                "n_mca_holes": item.get("n_mca_holes"),
                "n_have": counts.get("n_have"),
                "n_simp_at": counts.get("n_simp_at"),
                "n_rw": counts.get("n_rw"),
                "n_induction": counts.get("n_induction"),
                "top_family": (families[0].get("family") if families else None),
            }
        )
    return rows


def restore_if(path: Any, data: bytes) -> bool:
    """Write bytes back if the file still exists. Returns True if written."""

    target = Path(path)
    if target.is_file() and data:
        target.write_bytes(data)
        return True
    return False


def tokens_from_canaries(
    payload: Mapping[str, Any],
    *,
    names: Optional[Sequence[str]] = None,
) -> dict[str, int]:
    """Read n_tokens from canary analysis rows."""

    allow = set(names) if names is not None else None
    board: dict[str, int] = {}
    for row in payload.get("canaries") or []:
        name = str((row.get("analysis") or {}).get("name") or "")
        tok = (row.get("analysis") or {}).get("n_tokens")
        if name and tok and (allow is None or name in allow):
            board[name] = int(tok)
    return board


def write_json_pair(
    directory: Path,
    payload: Mapping[str, Any],
    *,
    prefix: str,
    latest: str,
    refuse: Any = (),
    error_cls: Any = SystemExit,
    refuse_msg: str = "refusing to write a receipt that contains an API key",
) -> Path:
    """Write stamped JSON and a latest alias. Optional substring refuse. No Lean."""

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    stamp = utc_stamp(fmt="%Y%m%dT%H%M%SZ")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n"
    needles = (refuse,) if isinstance(refuse, str) else tuple(refuse or ())
    if any(needle and needle in text for needle in needles):
        raise error_cls(refuse_msg)
    write_text(out / f"{prefix}-{stamp}.json", text)
    return write_text(out / latest, text)


def glob_stem_int(directory: Path, pattern: str) -> list[tuple[int, Path]]:
    """Files whose last stem token is an int (token count), shortest first."""

    rows: list[tuple[int, Path]] = []
    for path in Path(directory).glob(pattern):
        tail = path.stem.rsplit("-", 1)[-1]
        tok = int(tail) if tail.isdigit() else 10**9
        rows.append((tok, path))
    rows.sort()
    return rows


def stall_after(total: int, best_total: int, stalled: int) -> tuple[int, int, bool]:
    """Shorter board total is improvement. Returns (best_total, stalled, improved)."""

    improved = int(total) < int(best_total) and int(total) > 0
    if improved:
        return int(total), 0, True
    return int(best_total), int(stalled) + 1, False


def should_stop_outer(
    *,
    action: Mapping[str, Any],
    applied: Mapping[str, Any],
    stalled: int,
    stalled_limit: int = 2,
    hard_stopped: bool = False,
    halt: Optional[Mapping[str, Any]] = None,
    hypothesis_attempted: bool = False,
) -> str:
    """Closed stop reason, or empty to keep looping."""

    if str(action.get("action") or "") == "stop" or str(applied.get("applied") or "") == "stop":
        return str(action.get("reason") or "stop")
    if hard_stopped:
        return "ledger_hard_stop"
    if halt:
        if halt.get("budget_dead"):
            return "nca_budget"
        if halt.get("halt"):
            return "nca_halt"
    if int(stalled) >= int(stalled_limit):
        # Reserve one additional outer turn for a hypothesis probe.  The
        # caller marks it attempted when the closed hypothesis action is
        # applied; after that probe, an unchanged board is terminal.
        if not hypothesis_attempted:
            return ""
        return "no_token_cut"
    return ""


def history_row(
    *,
    step: int,
    llm: bool,
    board: Mapping[str, Any],
    total: int,
    improved: bool,
    last_lake: Sequence[Mapping[str, Any]],
    action: Mapping[str, Any],
    applied: Mapping[str, Any],
    traces: Sequence[Any],
    flatten_fn: Optional[Any] = None,
    payload: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    flatten = flatten_fn
    depths = []
    if flatten is not None:
        depths = [
            int(ev.get("depth") or 0)
            for tr in traces
            for ev in flatten(list(tr or []))
        ]
    return {
        "step": step,
        "outer": "grok" if llm else "deterministic",
        "inner": "typesafe_nested",
        "board": dict(board),
        "total": int(total),
        "improved": bool(improved),
        "n_lake": len(list(last_lake or [])),
        "n_ok": sum(1 for item in last_lake or [] if item.get("ok")),
        "action": dict(action),
        "applied": dict(applied),
        "n_traces": len(list(traces or [])),
        "max_trace_depth": max(depths, default=0),
        "jev_calls": ((payload or {}).get("ledger") or {}).get("jev_calls"),
    }


def format_prompt(
    *,
    preamble: str,
    actions: Sequence[str],
    extra: str = "",
    board: Mapping[str, Any],
    gaps: Sequence[Mapping[str, Any]],
    last_lake: Sequence[Mapping[str, Any]],
    nca_status: Optional[Mapping[str, Any]] = None,
    total: Optional[int] = None,
    self_analysis: Optional[Mapping[str, Any]] = None,
    code_context: str = "",
) -> str:
    """Closed outer-router prompt. Does not write Lean or source files."""

    tot = int(total) if total is not None else int(sum(int(v) for v in dict(board).values() if str(v).lstrip("-").isdigit() or isinstance(v, int)))
    return (
        str(preamble)
        + f"action must be one of: {', '.join(actions)}.\n"
        + str(extra)
        + f"keep_best_tokens={json.dumps(dict(board), sort_keys=True)}\n"
        + f"total={tot}\n"
        + f"gaps={json.dumps(compact_gaps(gaps), sort_keys=True)}\n"
        + f"last_lake={json.dumps(compact_lake(last_lake), sort_keys=True)}\n"
        + f"nca={json.dumps(dict(nca_status or {}), sort_keys=True)}\n"
        + f"inner_self_analysis={json.dumps(dict(self_analysis or {}), sort_keys=True)}\n"
        + (f"code_context={code_context}\n" if code_context else "")
    )


def run_steps(
    *,
    n: int,
    memory: dict[str, Any],
    llm: bool,
    gaps_fn: Any,
    route_fn: Any,
    apply_fn: Any,
    inner_fn: Any,
    board_fn: Any,
    persist_fn: Optional[Any] = None,
    halt_fn: Optional[Any] = None,
    flatten_fn: Optional[Any] = None,
    hard_stop_fn: Optional[Any] = None,
    stalled_limit: int = 2,
    on_inner_start: Optional[Any] = None,
) -> dict[str, Any]:
    """OUTER route/apply then INNER payload. Implementations inject lake/Jev."""

    history: list[dict[str, Any]] = []
    board, best_total = board_fn()
    stalled = 0
    hypothesis_attempted = False
    stop_reason = ""
    last_lake: list[dict[str, Any]] = []
    gaps = list(gaps_fn() or [])
    total = int(best_total)
    for step in range(max(1, int(n))):
        action = dict(
            route_fn(
                board=board,
                gaps=gaps,
                last_lake=last_lake,
                stalled=stalled >= int(stalled_limit),
            )
            or {}
        )
        applied = dict(apply_fn(memory, action) or {})
        if (
            str(action.get("action") or "") == "hypothesis_refactor"
            and bool(applied.get("ok", True))
        ):
            hypothesis_attempted = True
        if persist_fn is not None:
            persist_fn(memory)
        payload: dict[str, Any] = {}
        traces: list[Any] = []
        if str(action.get("action") or "") != "stop":
            if on_inner_start is not None:
                on_inner_start(memory)
            payload = dict(inner_fn(step) or {})
            gaps = list(payload.get("skill_analysis") or gaps_fn() or [])
            last_lake = list(payload.get("lake") or [])
            traces = [row.get("trace") for row in payload.get("canaries") or [] if row.get("trace")]
        board, total = board_fn()
        if int(best_total) <= 0 and int(total) > 0:
            # A fresh artifact directory has no persisted board yet.  Treat
            # the first observed verified board as the baseline; otherwise a
            # legitimate shortening can never satisfy ``total < best_total``
            # because the sentinel is zero.
            best_total = int(total)
            stalled = 0
            improved = False
        else:
            best_total, stalled, improved = stall_after(total, best_total, stalled)
        row = history_row(
            step=step,
            llm=llm,
            board=board,
            total=total,
            improved=improved,
            last_lake=last_lake,
            action=action,
            applied=applied,
            traces=traces,
            flatten_fn=flatten_fn,
            payload=payload,
        )
        history.append(row)
        halt = None
        if halt_fn is not None:
            try:
                halt = halt_fn(memory)
                row["nca_halt"] = halt
            except Exception:
                halt = None
        stop_reason = should_stop_outer(
            action=action,
            applied=applied,
            stalled=stalled,
            stalled_limit=stalled_limit,
            hard_stopped=bool(hard_stop_fn() if hard_stop_fn is not None else False),
            halt=halt,
            hypothesis_attempted=hypothesis_attempted,
        )
        if stop_reason:
            break
    if not stop_reason and stalled >= int(stalled_limit):
        stop_reason = "no_token_cut"
    return {
        "history": history,
        "stop_reason": stop_reason,
        "best_total": best_total,
        "board": dict(board),
        "total": int(total),
        "gaps": gaps,
        "last_lake": last_lake,
    }


def apply_action(
    memory: dict[str, Any],
    action: Mapping[str, Any],
    *,
    code_updater: Optional[Any] = None,
) -> dict[str, Any]:
    """Apply a closed action to memory or a consumer-provided code gate.

    ``update_code``/``patch`` never write files in the kernel.  The optional
    ``code_updater`` (or the ``apply_code_change`` hook) must validate a
    candidate and return a receipt.  This keeps the router connected to the
    outer loop without allowing arbitrary model text to become ``exec``.
    """

    from jevops import hooks

    kind = str(action.get("action") or "run")
    if kind == "skip_stem":
        stem = str(action.get("stem") or "")
        name = str(action.get("name") or "")
        if not stem:
            return {"ok": False, "reason": "no_stem"}
        key = f"{name}::port_{stem}" if name else f"*::port_{stem}"
        blacklist = memory.setdefault("blacklist", [])
        if key not in blacklist:
            blacklist.append(key)
        return {"ok": True, "applied": "skip_stem", "key": key}
    if kind == "mint":
        stem = str(action.get("stem") or "")
        name = str(action.get("name") or "")
        if not stem:
            return {"ok": False, "reason": "no_stem"}
        memory.setdefault("expanded", []).append(
            {
                "name": name,
                "notes": [{"action": "keep_structure", "mint": [stem], "source": "loop"}],
            }
        )
        return {"ok": True, "applied": "mint", "stem": stem}
    if kind in {"mint_tactic", "repair_tactic", "hypothesis_refactor"}:
        name = str(action.get("name") or action.get("target") or "").strip()[:160]
        family = str(action.get("family") or "").strip()[:80]
        strategy = str(action.get("strategy") or "closed_edits").strip().lower().replace("-", "_")
        if not name:
            return {"ok": False, "reason": "no_design_target"}
        if strategy not in TACTIC_DESIGN_STRATEGIES:
            return {"ok": False, "reason": "unknown_design_strategy", "strategy": strategy}
        directive = {
            "action": kind,
            "name": name,
            "family": family,
            "strategy": strategy,
            "repair_stem": str(action.get("stem") or "").strip()[:80],
            "focus": str(action.get("focus") or action.get("reason") or "").strip()[:240],
            "source": "outer_llm",
            "status": "pending",
        }
        if kind == "hypothesis_refactor":
            hypothesis = str(action.get("hypothesis") or action.get("focus") or "").strip()[:600]
            if not hypothesis:
                return {"ok": False, "reason": "no_refactor_hypothesis"}
            directive.update(
                {
                    "hypothesis": hypothesis,
                    "constraints": str(action.get("constraints") or "").strip()[:400],
                    "evaluation": str(action.get("evaluation") or "").strip()[:400],
                }
            )
        nca = memory.setdefault("nca", {})
        queue = nca.get("tactic_design_queue")
        if not isinstance(queue, list):
            queue = []
            nca["tactic_design_queue"] = queue
        queue[:] = [
            row
            for row in queue
            if not (
                isinstance(row, Mapping)
                and str(row.get("name") or "") == name
                and str(row.get("strategy") or "") == strategy
            )
        ][-7:]
        queue.append(directive)
        nca["active_tactic_design"] = dict(directive)
        if kind == "hypothesis_refactor":
            hypothesis_queue = nca.get("hypothesis_queue")
            if not isinstance(hypothesis_queue, list):
                hypothesis_queue = []
                nca["hypothesis_queue"] = hypothesis_queue
            hypothesis_queue[:] = [
                row
                for row in hypothesis_queue
                if not (
                    isinstance(row, Mapping)
                    and str(row.get("name") or "") == name
                    and str(row.get("hypothesis") or "") == hypothesis
                )
            ][-7:]
            hypothesis_queue.append(dict(directive))
            nca["active_hypothesis_refactor"] = dict(directive)
        else:
            nca["active_hypothesis_refactor"] = None
        return {"ok": True, "applied": kind, "directive": dict(directive)}
    if kind == "install_fold":
        install = hooks.resolve("install_fold", "binder_use", "install_memory_skill")
        if install is None:
            return {"ok": False, "reason": "no_install_fold"}
        installed = install(memory, action)
        return {"ok": bool(installed.get("ok")), **installed}
    if kind in {"update_code", "patch"}:
        updater = code_updater or hooks.get("apply_code_change")
        if updater is None:
            return {"ok": False, "reason": "no_code_updater"}
        try:
            result = updater(action, memory=memory)
        except TypeError:
            # Consumer hooks historically use the compact ``(memory, action)``
            # shape.  Keep that shape working while preferring the named form.
            result = updater(memory, action)
        receipt = dict(result or {}) if isinstance(result, Mapping) else {"result": result}
        receipt.setdefault("ok", bool(receipt.get("accepted")))
        receipt.setdefault("applied", "update_code" if receipt.get("ok") else "update_code_rejected")
        return receipt
    return {"ok": True, "applied": kind}


def nca_status(memory: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compact NCA snapshot for the outer loop."""

    mem = dict(memory or {})
    try:
        from jevops import nca as lra_nca
        from jevops import board as lra_board

        halt = lra_nca.should_halt(mem)
        window = lra_board.board_window(mem)
    except Exception:
        halt, window = {}, []
    budget = (((mem.get("nca") or {}).get("grid") or {}).get("ptr://tool/budget") or {})
    plan = {}
    try:
        from jevops import plan as lra_plan

        plan = lra_plan.plan_window(mem)
    except Exception:
        plan = {}
    kern = dict((mem.get("nca") or {}).get("kernel") or {})
    stats = dict(kern.get("stats") or {})
    nca_mem = dict(mem.get("nca") or {})
    active_design = nca_mem.get("active_tactic_design")
    if isinstance(active_design, Mapping):
        active_design = {
            key: active_design.get(key)
            for key in ("action", "name", "family", "strategy", "repair_stem", "status")
            if active_design.get(key)
        }
    else:
        active_design = None
    return {
        "halt": bool(halt.get("halt")),
        "budget_dead": bool(halt.get("budget_dead")),
        "budget_energy": halt.get("budget_energy", budget.get("energy")),
        "n_hot_tasks": halt.get("n_hot_tasks"),
        "active_tactic_design": active_design,
        "tactic_design_queue_len": len(nca_mem.get("tactic_design_queue") or []),
        "active_hypothesis_refactor": nca_mem.get("active_hypothesis_refactor")
        if isinstance(nca_mem.get("active_hypothesis_refactor"), Mapping)
        else None,
        "hypothesis_queue_len": len(nca_mem.get("hypothesis_queue") or [])
        if isinstance(nca_mem.get("hypothesis_queue"), list)
        else 0,
        "hypothesis_history": [
            {
                key: row.get(key)
                for key in (
                    "name",
                    "hypothesis",
                    "strategy",
                    "accepted",
                    "candidate_count",
                    "lake_verified_count",
                )
                if row.get(key) is not None
            }
            for row in list(nca_mem.get("hypothesis_history") or [])[-4:]
            if isinstance(row, Mapping)
        ],
        "inner_analysis": list(nca_mem.get("inner_analysis") or [])[:8],
        "tactic_design_history": [
            {
                key: row.get(key)
                for key in (
                    "name",
                    "strategy",
                    "family",
                    "repair_stem",
                    "candidate_count",
                    "lake_verified_count",
                    "accepted",
                )
                if row.get(key) is not None
            }
            for row in list(nca_mem.get("tactic_design_history") or [])[-4:]
            if isinstance(row, Mapping)
        ],
        "board_window": head_seq(window, 6),
        "plan": plan,
        "kernel": {
            "policy": kern.get("policy") or "arc",
            "tick": kern.get("tick") or 0,
            "n_l1": len(kern.get("l1") or {}),
            "n_negative": len(kern.get("negative") or {}),
            "n_in_flight": len(kern.get("in_flight") or []),
            "stats": stats,
        },
    }


def load_env_file(
    path: Any,
    *,
    environ: Optional[Any] = None,
    encoding: str = "utf-8",
    strip_quotes: bool = False,
) -> dict[str, str]:
    """KEY=VALUE lines. setdefault into environ (os.environ by default)."""

    import os

    loaded: dict[str, str] = {}
    target = Path(path) if path else None
    if target is None or not target.is_file():
        return loaded
    dest = os.environ if environ is None else environ
    for line in target.read_text(encoding=encoding).splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        name, value = text.split("=", 1)
        key, val = name.strip(), value.strip()
        if strip_quotes and len(val) >= 2 and val[0] == val[-1] and val[0] in {"'", '"'}:
            val = val[1:-1]
        dest.setdefault(key, val)
        loaded[key] = val
    return loaded


def pin_sys_path(
    path: Any,
    *,
    environ: Optional[Any] = None,
    defaults: Optional[Mapping[str, str]] = None,
) -> None:
    """Move path to sys.path[0]. setdefault env defaults."""

    import os
    import sys

    text = str(path or "")
    if text:
        if text in sys.path:
            sys.path.remove(text)
        sys.path.insert(0, text)
    dest = os.environ if environ is None else environ
    for key, value in dict(defaults or {}).items():
        dest.setdefault(str(key), str(value))


def is_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "503" in text or "unavailable" in text or "429" in text


def retry_call(
    fn: Any,
    *,
    attempts: int = 4,
    sleep_fn: Optional[Any] = None,
    unavailable_pred: Optional[Any] = None,
    backoff: Optional[Any] = None,
) -> Any:
    """Retry fn on unavailable (503/429). Last exception is raised."""

    import time

    sleep = sleep_fn or time.sleep
    pred = unavailable_pred or is_unavailable
    delay_fn = backoff or (lambda index: min(20.0, 2.0 ** int(index)))
    last: Optional[BaseException] = None
    for attempt in range(max(1, int(attempts))):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not pred(exc) or attempt + 1 >= int(attempts):
                raise
            sleep(delay_fn(attempt))
    raise last or RuntimeError("retry exhausted")


def failed_leaves_from_history(
    payload: Mapping[str, Any],
    *,
    lake_fail_actions: Sequence[str] = ("lake",),
    skip_actions: Sequence[str] = ("skip_lake", "skip_not_shorter"),
) -> set[str]:
    """Leaf ids from JSON history that lake-failed or were skipped."""

    failed: set[str] = set()
    lake = {str(x) for x in lake_fail_actions}
    skip = {str(x) for x in skip_actions}
    for row in (payload or {}).get("history") or []:
        picked = row.get("picked") if isinstance(row, Mapping) else None
        leaf = str((picked or {}).get("leaf") or "") if isinstance(picked, Mapping) else ""
        if not leaf:
            continue
        action = str(row.get("action") or "")
        if action in lake and row.get("ok") is False:
            failed.add(leaf)
        if action in skip:
            failed.add(leaf)
    return failed


def fill_template(
    template: str,
    values: Mapping[str, Any],
    *,
    left: str = "{{",
    right: str = "}}",
) -> str:
    """Replace ``{{key}}`` placeholders. No Lean."""

    filled = str(template)
    for key, value in dict(values or {}).items():
        filled = filled.replace(f"{left}{key}{right}", str(value))
    return filled


def version_sort_key(tag: str, *, strip_prefix: str = "v") -> tuple[tuple[int, int, int], str]:
    """Numeric (major, minor, patch) then suffix. ``v4.26.0-rc1`` → ((4,26,0), 'rc1')."""

    text = str(tag or "")
    if strip_prefix and text.startswith(strip_prefix):
        text = text[len(strip_prefix) :]
    main, _, suffix = text.partition("-")
    parts = main.split(".")
    nums = [int(part) if part.isdigit() else 0 for part in parts[:3]]
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2]), suffix


def mean_nonneg(rows: Sequence[Any], *, getter: Any) -> float:
    """Mean of max(0, getter(item)). Empty → 0.0."""

    items = list(rows or ())
    if not items:
        return 0.0
    return sum(max(0.0, float(getter(item))) for item in items) / float(len(items))


def flatten_version_tags(version_info: Any) -> list[str]:
    """Dict keys or bare strings from a version_info list."""

    listed: list[str] = []
    for item in version_info or []:
        if isinstance(item, Mapping):
            listed.extend(str(tag) for tag in item.keys() if str(tag).strip())
        elif isinstance(item, str) and item.strip():
            listed.append(item)
    return listed


def iter_tag_commit_pins(
    version_info: Any,
    *,
    pin_fn: Any,
    normalize_fn: Any = None,
    error_cls: Any = ValueError,
    not_list: str = "version_info must be a list of {tag: commit} maps",
    empty_tag: str = "version_info[{index}] has an empty tag",
    bad_commit: str = "version_info[{index}] git commit must be a string, not {type}",
    not_map: str = "version_info[{index}] is not a {{tag: commit}} map",
    empty: str = "version_info is empty",
) -> list[Any]:
    """List of {tag: commit} maps → pin objects. normalize_fn/pin_fn injected."""

    if not isinstance(version_info, list):
        raise error_cls(not_list)
    pins: list[Any] = []
    for index, item in enumerate(version_info):
        if isinstance(item, dict) and item:
            for tag, commit in item.items():
                if not isinstance(tag, str) or not tag.strip():
                    raise error_cls(empty_tag.format(index=index))
                if commit is None:
                    commit_text = ""
                elif isinstance(commit, str):
                    commit_text = commit.strip()
                else:
                    raise error_cls(bad_commit.format(index=index, type=type(commit).__name__))
                text = normalize_fn(tag) if normalize_fn is not None else tag.strip()
                pins.append(pin_fn(text, commit_text))
            continue
        raise error_cls(not_map.format(index=index))
    if not pins:
        raise error_cls(empty)
    return pins


def listed_all_ok(
    listed: Sequence[str],
    items: Sequence[Any],
    *,
    id_fn: Any,
    ok_fn: Any,
) -> bool:
    """True iff every listed id is present and ok_fn(item). Empty listed → False."""

    rows = list(listed or ())
    if not rows:
        return False
    by_id = {id_fn(item): item for item in items or ()}
    if any(tag not in by_id for tag in rows):
        return False
    return all(ok_fn(by_id[tag]) for tag in rows)


def load_module_from_path(path: Any, name: str) -> Optional[Any]:
    """Load a Python module from a file path. None if missing."""

    import importlib.util
    import sys

    target = Path(path)
    if not target.is_file():
        return None
    spec = importlib.util.spec_from_file_location(str(name), target)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def http_get(url: str, *, timeout: float, accept: str = "application/json") -> tuple[Optional[int], str]:
    """GET url. Returns (status, error). Transport errors → (None, 'Type: msg')."""

    import urllib.error
    import urllib.request

    request = urllib.request.Request(str(url), method="GET", headers={"Accept": str(accept)})
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            return int(getattr(response, "status", 200) or 200), ""
    except urllib.error.HTTPError as exc:
        return int(exc.code), str(exc.reason or exc)
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def require_positive_above(
    value: Any,
    floor: float,
    *,
    error_cls: Any = ValueError,
    too_small_cls: Optional[Any] = None,
    not_positive: str = "must be a positive number",
    too_small: str = "must exceed {floor}",
) -> float:
    """Reject bool/non-numeric/≤0; reject ≤ floor with too_small.format(value, floor)."""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise error_cls(not_positive)
    number = float(value)
    if number <= float(floor):
        raise (too_small_cls or error_cls)(str(too_small).format(value=number, floor=floor))
    return number


def first_group(text: str, pattern: Any, *, group: int = 1, method: str = "search") -> Optional[str]:
    """First regex group as str, or None. Empty text → None."""

    if not isinstance(text, str) or not text.strip():
        return None
    finder = getattr(pattern, method, None)
    if finder is None:
        return None
    match = finder(text)
    if match is None:
        return None
    got = match.group(int(group))
    return None if got is None else str(got)


def first_group_int(text: str, pattern: Any) -> Optional[int]:
    """First regex group as int, or None. Empty text → None."""

    raw = first_group(text, pattern)
    return None if raw is None else int(raw)


def first_nonempty(mapping: Mapping[str, Any], *keys: str, default: str = "") -> str:
    """First stripped non-empty mapping[key]."""

    row = dict(mapping or {})
    for key in keys:
        val = str(row.get(key) or "").strip()
        if val:
            return val
    return str(default)


def contains_flags(text: str, checks: Mapping[str, Any]) -> dict[str, bool]:
    """Lowercased membership flags. spec is a needle, all-tuple, or {all|any|absent}."""

    blob = str(text or "").lower()
    out: dict[str, bool] = {}
    for key, spec in dict(checks or {}).items():
        if isinstance(spec, Mapping):
            if spec.get("absent") is not None:
                needles = list(spec.get("absent") or ())
                out[str(key)] = all(str(item).lower() not in blob for item in needles)
            elif spec.get("any") is not None:
                needles = list(spec.get("any") or ())
                out[str(key)] = any(str(item).lower() in blob for item in needles)
            else:
                needles = list(spec.get("all") or ())
                out[str(key)] = all(str(item).lower() in blob for item in needles)
        elif isinstance(spec, (list, tuple)):
            out[str(key)] = all(str(item).lower() in blob for item in spec)
        else:
            out[str(key)] = str(spec).lower() in blob
    return out


def first_env_path(*names: str, default: Any, environ: Optional[Any] = None) -> Path:
    """First nonempty env path, else default."""

    import os

    dest = os.environ if environ is None else environ
    for name in names:
        raw = dest.get(name)
        if raw is not None and str(raw).strip():
            return Path(str(raw)).expanduser()
    return Path(default)


def allow_or_deny(
    value: Optional[str] = None,
    *,
    deny: Sequence[str] = (),
    default: str = "allow",
    env_keys: Sequence[str] = (),
    environ: Optional[Any] = None,
) -> str:
    """allow unless value/env is in deny."""

    import os

    dest = os.environ if environ is None else environ
    raw = value
    if raw is None or not str(raw).strip():
        for key in env_keys:
            got = dest.get(key)
            if got is not None and str(got).strip():
                raw = got
                break
    if raw is None or not str(raw).strip():
        return str(default)
    text = str(raw).strip().lower()
    if text in {str(item).lower() for item in deny}:
        return "deny"
    return str(default)


def is_executable(path: Any) -> bool:
    import stat

    target = Path(path)
    try:
        mode = target.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode) and bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


def url_cache_key(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(str(url or ""))
    host = parsed.netloc or "no-host"
    path = parsed.path.strip("/") or "unnamed"
    return f"{host}/{path}"


def normalize_tag(
    value: str,
    *,
    prefix: str = "",
    error_cls: Any = ValueError,
    empty: str = "tag must be a nonempty string",
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise error_cls(empty)
    text = value.strip()
    if prefix and text.startswith(prefix):
        text = text[len(prefix) :]
    elif ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.strip()
    if not text:
        raise error_cls(f"tag {value!r} normalized to empty")
    return text


def copy_tree(src: Any, dest: Any) -> None:
    source = Path(src)
    target_root = Path(dest)
    target_root.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        target = target_root / entry.name
        if entry.is_dir():
            copy_tree(entry, target)
        else:
            target.write_bytes(entry.read_bytes())


def copy_dir_required(
    src: Any,
    dest: Any,
    *,
    error_cls: Any = FileNotFoundError,
    miss: str = "expected directory at {src}",
) -> Path:
    """Copy a directory tree. Raise if src is missing. Never PATH lookup."""

    source = Path(src)
    if not source.is_dir():
        raise error_cls(miss.format(src=source))
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    copy_tree(source, dest_path)
    return dest_path


def redact_secret(text: str, secret: str, *, token: str = "[redacted]") -> str:
    if not text:
        return ""
    if secret:
        return str(text).replace(str(secret), str(token))
    return str(text)


def require_host(
    url: str,
    expected: str,
    *,
    forbidden: Sequence[str] = (),
    error_cls: Any = ValueError,
    prototype_fmt: str = "refusing prototype host {host!r}",
    mismatch_fmt: str = "refusing host {host!r}; expected {expected}",
) -> str:
    from urllib.parse import urlparse

    host = (urlparse(str(url)).hostname or "").lower()
    banned = {str(item).lower() for item in forbidden}
    if host in banned or host.endswith(".local"):
        raise error_cls(prototype_fmt.format(host=host, expected=expected))
    if host != str(expected).lower():
        raise error_cls(mismatch_fmt.format(host=host, expected=expected))
    return host


def estimate_tokens_chars(text: str, *, width: int = 4, minimum: int = 1) -> int:
    """Ceil(len/width) token estimate. Empty → minimum."""

    if not text:
        return int(minimum)
    return max(int(minimum), (len(text) + int(width) - 1) // int(width))


def first_match(rules: Sequence[tuple[Any, str]], *, default: str = "") -> str:
    """First (pred, action) whose pred() is true."""

    for pred, action in rules:
        if pred():
            return str(action)
    return str(default)


def poll_until(
    probe_fn: Any,
    *,
    ok_fn: Any,
    timeout: float,
    interval: float = 0.25,
    sleep_fn: Optional[Any] = None,
    min_interval: float = 0.01,
) -> Any:
    """Call probe_fn until ok_fn(result) or timeout. Returns last result."""

    import time

    sleep = sleep_fn or time.sleep
    deadline = time.monotonic() + max(0.0, float(timeout))
    last = probe_fn()
    while not ok_fn(last) and time.monotonic() < deadline:
        sleep(max(float(min_interval), float(interval)))
        last = probe_fn()
    return last


def sanitize_ident(
    name: str,
    *,
    pattern: str = r"[^A-Za-z0-9._-]+",
    error_cls: Any = ValueError,
    empty: str = "name sanitizes empty",
) -> str:
    cleaned = re.sub(pattern, "_", str(name)).strip("._")
    if not cleaned:
        raise error_cls(empty)
    return cleaned


def write_cas(
    root: Any,
    data: bytes,
    *,
    prefix: str = "artifacts",
    filename: str = "blob",
) -> str:
    """Write data under root/prefix/aa/<digest>/filename. Returns digest hex."""

    digest = digest_hex(data)
    folder = Path(root) / str(prefix) / digest[:2] / digest
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / str(filename)
    if not path.exists():
        path.write_bytes(data)
    return digest


def dump_tiny(
    payload: Any,
    *,
    max_bytes: int,
    error_cls: Any = ValueError,
    fmt: str = "payload {n} bytes exceeds cap {max_bytes}",
) -> str:
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    n = len(blob.encode("utf-8"))
    if n > int(max_bytes):
        raise error_cls(fmt.format(n=n, max_bytes=int(max_bytes)))
    return blob


def keyed_pair(
    key: str,
    table: Mapping[str, tuple[Any, ...]],
    default: tuple[Any, ...],
) -> tuple[Any, ...]:
    return tuple(table.get(str(key or "").strip().lower(), default))


def stat_dev_ino(path: Any) -> Optional[tuple[int, int, int]]:
    import os

    try:
        st = Path(path).stat()
    except OSError:
        return None
    return os.major(st.st_dev), os.minor(st.st_dev), st.st_ino


def object_fields(
    obj: Any,
    fields: Sequence[str],
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Project an object or mapping onto fields. None → None."""

    more = dict(extra or {})
    if obj is None:
        return None
    if isinstance(obj, Mapping):
        out = dict(obj)
        out.update(more)
        return out
    if fields and hasattr(obj, str(fields[0])):
        out = {str(name): getattr(obj, name, None) for name in fields}
        out.update(more)
        return out
    out = {"repr": str(obj)}
    out.update(more)
    return out


def digest_file(path: Any) -> str:
    return digest_hex(Path(path).read_bytes())


def digest_text(text: str) -> str:
    return digest_hex(str(text).encode("utf-8"))


def digest_prefix(text: str, n: int = 12) -> str:
    """First n hex chars of digest_text. Used for short blacklist keys."""

    return head_chars(digest_text(text), n)


def write_executable(path: Any, text: str, *, encoding: str = "utf-8") -> Path:
    import stat

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding=encoding)
    mode = target.stat().st_mode
    target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target


def write_json(path: Any, payload: Any, *, indent: int = 2) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=indent, sort_keys=True) + "\n", encoding="utf-8")
    return target


def first_where(
    items: Sequence[Any],
    pred: Any,
    *,
    error_cls: Optional[Any] = None,
    miss: str = "",
) -> Any:
    for item in items or ():
        if pred(item):
            return item
    if error_cls is not None:
        raise error_cls(miss)
    return None


def after_named(
    records: Sequence[Mapping[str, Any]],
    after_name: str,
    *,
    name_key: str = "name",
    pred: Optional[Any] = None,
) -> list[Mapping[str, Any]]:
    """Items after the named record (the named record itself excluded)."""

    found = False
    out: list[Mapping[str, Any]] = []
    want = str(after_name or "")
    for record in records or ():
        if not found:
            if str(record.get(name_key) or "") == want:
                found = True
            continue
        if pred is None or pred(record):
            out.append(record)
    return out


def unique_keep(items: Sequence[Any]) -> list[Any]:
    out: list[Any] = []
    for item in items or ():
        if item in out:
            continue
        out.append(item)
    return out


def merge_head_row(
    item: Mapping[str, Any],
    compiled: Mapping[str, Any],
    *,
    drop: Sequence[str] = ("tactics",),
    head: int = 240,
) -> dict[str, Any]:
    body = str(item.get("tactics") or "")
    payload = {
        **dict(item),
        **dict(compiled),
        "n_chars": len(body),
        "tactics_head": head_chars(body, head),
    }
    for key in drop:
        payload.pop(key, None)
    return payload


def http_post(
    url: str,
    data: bytes,
    *,
    timeout: float,
    headers: Optional[Mapping[str, str]] = None,
) -> tuple[Optional[int], str, str, str]:
    """POST bytes. Returns (status, body, final_url, error). Transport → error string."""

    import urllib.error
    import urllib.request

    request = urllib.request.Request(
        str(url),
        data=data,
        method="POST",
        headers=dict(headers or {}),
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
            getter = getattr(response, "geturl", None)
            final = str(getter() if callable(getter) else url)
            return status, body, final, ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return int(exc.code), detail, str(url), ""
    except Exception as exc:  # noqa: BLE001
        return None, "", str(url), f"{type(exc).__name__}: {exc}"


def xdg_runtime_dir(*, environ: Optional[Any] = None) -> Path:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get("XDG_RUNTIME_DIR")
    if raw and str(raw).strip():
        return Path(str(raw))
    return Path(f"/run/user/{os.getuid()}")


def try_import(name: str) -> Any:
    try:
        return __import__(name)
    except ImportError:
        return None


def dir_has_markers(path: Any, markers: Sequence[str]) -> bool:
    target = Path(path)
    if not target.is_dir():
        return False
    return any((target / str(marker)).exists() for marker in markers)


def require_marked_dir(
    path: Any,
    markers: Sequence[str],
    *,
    error_cls: Any = None,
    miss: str = "",
) -> Path:
    """Return path. Raise only when markers are missing and error_cls is set."""

    dest = Path(path)
    if dir_has_markers(dest, markers):
        return dest
    if error_cls is not None:
        raise error_cls(miss.format(path=dest) if miss else str(dest))
    return dest


def run_process(
    argv: Sequence[str],
    *,
    cwd: Any = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    error_cls: Optional[Any] = None,
    fail_fmt: str = "{stderr}",
) -> dict[str, Any]:
    import subprocess

    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd is not None else None,
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if env is not None:
        kwargs["env"] = {str(key): str(value) for key, value in env.items()}
    if timeout is not None:
        kwargs["timeout"] = float(timeout)
    try:
        completed = subprocess.run([str(item) for item in argv], **kwargs)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        result = {
            "ok": False,
            "exit_code": None,
            "stdout": stdout or "",
            "stderr": stderr or "",
            "cwd": str(cwd) if cwd is not None else "",
            "timeout": True,
            "error": f"TimeoutExpired: {exc}",
            "pid": getattr(exc, "pid", None),
        }
        if error_cls is not None:
            raise error_cls(
                fail_fmt.format(stderr=result["error"], code="timeout")
            ) from exc
        return result
    if int(completed.returncode) != 0 and error_cls is not None:
        raise error_cls(
            fail_fmt.format(
                stderr=(completed.stderr or "").strip() or (completed.stdout or "").strip(),
                code=int(completed.returncode),
            )
        )
    return {
        "ok": int(completed.returncode) == 0,
        "exit_code": int(completed.returncode),
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
        "cwd": str(cwd) if cwd is not None else "",
        "timeout": False,
        "error": "",
        "pid": None,
    }


def run_pinned_bin(
    argv: Sequence[Any],
    *,
    basename: str,
    cwd: Any = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    error_cls: Any = RuntimeError,
    miss_cls: Optional[Any] = None,
    installed: bool = True,
    miss: str = "not installed",
    timeout_fmt: str = "timed out: {error}",
    basename_fmt: str = "expected tag-pinned {name}, got {path!r}",
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Run a basename-pinned argv. Never PATH. Timeout raises error_cls."""

    rows = [str(item) for item in argv]
    if not installed:
        raise (miss_cls or error_cls)(miss)
    if not rows:
        raise error_cls(basename_fmt.format(name=basename, path=""))
    require_basename(rows[0], basename, error_cls=error_cls, fmt=basename_fmt)
    ran = run_process(rows, cwd=cwd, env=env, timeout=timeout)
    if ran.get("timeout"):
        raise error_cls(timeout_fmt.format(error=ran.get("error") or "TimeoutExpired"))
    out: dict[str, Any] = {
        "argv": rows,
        "cwd": str(cwd) if cwd is not None else str(ran.get("cwd") or ""),
        "exit_code": ran.get("exit_code"),
        "stdout": ran.get("stdout") or "",
        "stderr": ran.get("stderr") or "",
        "ok": bool(ran.get("ok")),
        "timeout": False,
        "error": ran.get("error") or "",
    }
    if extra:
        out.update(dict(extra))
    return out


def usage_tokens(usage: Mapping[str, Any], *, fallback_in: int = 0) -> tuple[int, int]:
    inn = int(usage.get("input_tokens") or usage.get("prompt_tokens") or fallback_in)
    out = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    return inn, out


def usage_or_estimate(
    usage: Mapping[str, Any],
    *,
    fallback_in: int,
    estimate_fn: Callable[[Any], int],
    text: Any = "",
) -> tuple[int, int]:
    """usage_tokens, with estimate_fn(text) when output tokens are missing."""

    inn, out = usage_tokens(usage, fallback_in=int(fallback_in))
    return inn, out or int(estimate_fn(text))


def chat_choice_texts(payload: Mapping[str, Any]) -> tuple[str, list[str], Mapping[str, Any]]:
    """OpenAI/Mistral-style choices[].message.content. Returns (first, all, usage)."""

    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    texts: list[str] = []
    for choice in choices:
        if not isinstance(choice, Mapping):
            continue
        message = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
        content = str(message.get("content") or "")
        if content:
            texts.append(content)
    message: Mapping[str, Any] = {}
    if choices and isinstance(choices[0], Mapping):
        raw = choices[0].get("message")
        message = raw if isinstance(raw, Mapping) else {}
    text = texts[0] if texts else str(message.get("content") or "")
    usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    return text, texts, usage


def integrity_conflict(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    needles = ("constraint", "unique", "duplicate", "primary key", "integrity")
    return any(item in name for item in needles) or any(item in text for item in needles)


def guard_sql(
    sql: str,
    *,
    allowed_head: Any,
    forbidden: Any,
    error_cls: Any = ValueError,
    empty: str = "empty SQL",
    forbidden_fmt: str = "forbidden mutating SQL: {sql}",
    outside_fmt: str = "SQL outside allowed: {sql}",
) -> str:
    text = str(sql or "").strip()
    if not text:
        raise error_cls(empty)
    if forbidden.search(text):
        raise error_cls(forbidden_fmt.format(sql=head_chars(text, 120)))
    if not allowed_head.match(text):
        raise error_cls(outside_fmt.format(sql=head_chars(text, 120)))
    return text


def contains_any(text: str, markers: Sequence[str]) -> bool:
    blob = str(text or "").casefold()
    return any(str(marker).casefold() in blob for marker in markers)


def replace_once(
    path: Any,
    original: str,
    replacement: str,
    *,
    error_cls: Any = ValueError,
    miss: str = "{path}: substring missing",
    encoding: str = "utf-8",
) -> None:
    target = Path(path)
    text = target.read_text(encoding=encoding)
    if original not in text:
        raise error_cls(miss.format(path=target))
    target.write_text(text.replace(original, replacement, 1), encoding=encoding)


def mapping_line_in_span(pos: Any, start_line: int, end_line: int) -> bool:
    if not isinstance(pos, Mapping):
        return False
    try:
        line = int(pos.get("line"))
    except (TypeError, ValueError):
        return False
    return int(start_line) <= line <= int(end_line)


def jsonl_pred_in_span(
    stdout: str,
    *,
    pred: Any,
    start_line: int,
    end_line: int,
) -> bool:
    for line in str(stdout or "").splitlines():
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not pred(payload):
            continue
        if mapping_line_in_span(payload.get("pos"), start_line, end_line):
            return True
    return False


def proc_exclusive_holder(
    path: Any,
    *,
    proc_locks: Any = "/proc/locks",
) -> tuple[Optional[bool], Optional[int], str]:
    """Parse /proc/locks for an exclusive FLOCK/WRITE holder of path. Query only."""

    ident = stat_dev_ino(path)
    if ident is None:
        return False, None, "missing"
    maj, minr, ino = ident
    tokens = (
        f"{maj:x}:{minr:x}:{ino}",
        f"{maj:02x}:{minr:02x}:{ino}",
        f"{maj:08x}:{minr:08x}:{ino}",
    )
    try:
        text = Path(proc_locks).read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, f"proc_locks_unreadable: {exc}"
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        kind = parts[1].upper()
        mode = parts[3].upper() if len(parts) > 3 else ""
        if kind not in {"FLOCK", "POSIX", "OFDLCK"}:
            continue
        if mode not in {"WRITE", "EX", "WRLCK"}:
            continue
        if not any(token in parts[5] for token in tokens):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            pid = None
        return True, pid, "proc_locks"
    return False, None, "proc_locks"


def shared_lock_busy(path: Any, *, error_cls: Any = OSError) -> tuple[bool, str]:
    """Non-blocking shared flock probe. True means an exclusive holder exists."""

    import fcntl
    import os

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise error_cls(f"cannot open lock file for shared probe: {exc}") from exc
    try:
        sh = int(getattr(fcntl, "LOCK_SH", 1))
        nb = int(getattr(fcntl, "LOCK_NB", 4))
        un = int(getattr(fcntl, "LOCK_UN", 8))
        try:
            fcntl.flock(fd, sh | nb)
        except BlockingIOError:
            return True, "shared_probe"
        except OSError as exc:
            if getattr(exc, "errno", None) in {11, 13}:
                return True, "shared_probe"
            raise
        fcntl.flock(fd, un)
        return False, "shared_probe"
    finally:
        os.close(fd)


def git_head(clone: Any) -> str:
    ran = run_process(["git", "-C", str(clone), "rev-parse", "HEAD"])
    if not ran.get("ok"):
        return ""
    return str(ran.get("stdout") or "").strip()


def require_git_bin(
    git_bin: Any,
    *,
    error_cls: Any = FileNotFoundError,
    fmt: str = "git is not at {bin}",
) -> str:
    """Require a file-backed git binary. Never PATH lookup."""

    path = Path(git_bin)
    if not path.is_file():
        raise error_cls(fmt.format(bin=path))
    return str(path)


def url_clone_dir(root: Any, url: str, *, folder: str = "clones") -> Path:
    return join_under(root, folder, url_cache_key(url))


def git_checkout(
    clone: Any,
    commit: str,
    *,
    git_bin: Any = "git",
    detach: bool = True,
    error_cls: Any = RuntimeError,
    miss_cls: Optional[Any] = None,
    miss_fmt: str = "git is not at {bin}; cannot checkout {commit}",
    fail_fmt: str = "git checkout {commit} failed: {stderr}",
    skip_empty: bool = True,
    skip_missing_git: bool = True,
) -> dict[str, Any]:
    """Detach-checkout ``commit`` in ``clone``. Missing commit/repo can skip."""

    dest = Path(clone)
    cwd = str(dest)
    if skip_empty and not commit:
        return {"ok": True, "skipped": True, "commit": commit, "cwd": cwd}
    if skip_missing_git and not (dest / ".git").exists():
        return {"ok": True, "skipped": True, "commit": commit, "cwd": cwd}
    bin_path = require_git_bin(
        git_bin,
        error_cls=miss_cls or error_cls,
        fmt=miss_fmt.format(bin="{bin}", commit=commit),
    )
    argv = [bin_path, "-C", cwd, "checkout"]
    if detach:
        argv.append("--detach")
    argv.append(str(commit))
    ran = run_process(
        argv,
        cwd=dest,
        error_cls=error_cls,
        fail_fmt=fail_fmt.format(commit=commit, stderr="{stderr}"),
    )
    return {
        "ok": True,
        "skipped": False,
        "commit": commit,
        "cwd": cwd,
        "exit_code": ran.get("exit_code"),
    }


def git_clone_if_missing(
    url: Any,
    dest: Any,
    *,
    git_bin: str = "git",
    error_cls: Any = OSError,
    miss_cls: Optional[Any] = None,
) -> Path:
    """Clone url into dest when dest/.git is missing."""

    clone = Path(dest)
    if not (clone / ".git").is_dir():
        git_clone(url, clone, git_bin=git_bin, error_cls=error_cls, miss_cls=miss_cls)
    return clone


def git_clone(
    url: str,
    dest: Any,
    *,
    git_bin: Any = "git",
    error_cls: Any = RuntimeError,
    miss_cls: Optional[Any] = None,
    miss_fmt: str = "git is not at {bin}; cannot clone {url}",
    fail_fmt: str = "git clone failed for {url}: {stderr}",
) -> dict[str, Any]:
    """Clone ``url`` into ``dest``. Never PATH git."""

    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    bin_path = require_git_bin(
        git_bin,
        error_cls=miss_cls or error_cls,
        fmt=miss_fmt.format(bin="{bin}", url=url),
    )
    ran = run_process(
        [bin_path, "clone", "--", str(url), str(dest_path)],
        error_cls=error_cls,
        fail_fmt=fail_fmt.format(url=url, stderr="{stderr}"),
    )
    return {
        "ok": True,
        "url": url,
        "dest": str(dest_path),
        "exit_code": ran.get("exit_code"),
    }


def require_basename(
    path: Any,
    name: str,
    *,
    error_cls: Any = ValueError,
    fmt: str = "expected {name}, got {path!r}",
) -> str:
    text = str(path or "")
    if not text or Path(text).name != str(name):
        raise error_cls(fmt.format(name=name, path=path))
    return text


def print_json(
    payload: Any,
    *,
    stream: Any = None,
    indent: int = 2,
    default: Any = None,
    sort_keys: bool = True,
) -> None:
    import sys

    dest = sys.stdout if stream is None else stream
    kwargs: dict[str, Any] = {"indent": indent, "sort_keys": sort_keys}
    if default is not None:
        kwargs["default"] = default
    json.dump(payload, dest, **kwargs)
    dest.write("\n")


def print_ok(
    payload: Mapping[str, Any],
    *,
    stream: Any = None,
    default: Any = None,
    ok_key: str = "ok",
    indent: int = 2,
    sort_keys: bool = True,
) -> int:
    """print_json then 0 if payload[ok_key] else 1."""

    print_json(payload, stream=stream, default=default, indent=indent, sort_keys=sort_keys)
    return 0 if payload.get(ok_key) else 1


def with_fields(record: Mapping[str, Any], **fields: Any) -> dict[str, Any]:
    updated = dict(record)
    updated.update(fields)
    return updated


def with_field(record: Mapping[str, Any], key: str, value: Any) -> dict[str, Any]:
    return with_fields(record, **{key: value})


def join_under(root: Any, *parts: Any) -> Path:
    path = Path(root)
    for part in parts:
        path = path / str(part)
    return path


def plant_files(root: Any, files: Mapping[str, str], *, encoding: str = "utf-8") -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        path = dest / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(text), encoding=encoding)
    return dest


def write_tree(
    root: Any,
    files: Mapping[str, Any],
    *,
    encoding: str = "utf-8",
) -> dict[str, str]:
    """Write mixed text/JSON/bytes under root. Mapping/list values use write_json."""

    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    out: dict[str, str] = {}
    for rel, payload in dict(files or {}).items():
        path = dest / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, (Mapping, list)):
            write_json(path, payload)
        elif isinstance(payload, bytes):
            path.write_bytes(payload)
        else:
            write_text(path, str(payload), encoding=encoding)
        out[str(rel)] = str(path)
    return out


def plant_git_skeleton(
    clone: Any,
    *,
    head: str = "ref: refs/heads/main\n",
    files: Optional[Mapping[str, str]] = None,
    encoding: str = "utf-8",
) -> Path:
    dest = Path(clone)
    dest.mkdir(parents=True, exist_ok=True)
    git_dir = dest / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    (git_dir / "HEAD").write_text(head, encoding=encoding)
    if files:
        plant_files(dest, files, encoding=encoding)
    return dest


def prepend_argv(head: Any, *args: Any) -> list[str]:
    """``[head, *args]`` as strings."""

    return [str(head), *[str(item) for item in args]]


def python_argv(
    *args: Any,
    python: Optional[str] = None,
    flags: Sequence[str] = ("-B",),
) -> list[str]:
    import sys

    py = python or sys.executable
    return prepend_argv(py, *flags, *args)


def state_home_candidates(*, environ: Optional[Any] = None, home: Optional[Any] = None) -> list[Path]:
    import os

    dest = os.environ if environ is None else environ
    out: list[Path] = []
    raw = dest.get("XDG_STATE_HOME") if hasattr(dest, "get") else None
    if raw is not None and str(raw).strip():
        out.append(Path(str(raw).strip()))
    home_path = Path.home() if home is None else Path(home)
    out.append(home_path / ".local" / "state")
    out.append(home_path)
    return out


def exec_capable_dir(
    candidates: Sequence[Any],
    *,
    probe_name: str = ".exec-probe",
    probe_text: str = "#!/usr/bin/python3.12\nimport sys\nsys.exit(0)\n",
    check_fn: Optional[Any] = None,
    error_cls: Any = OSError,
    miss: str = "no executable filesystem",
) -> Path:
    import os

    checker = check_fn if check_fn is not None else (lambda path: os.system(str(path)) == 0)
    for base in candidates:
        try:
            root = Path(base)
            root.mkdir(parents=True, exist_ok=True)
            probe = root / str(probe_name)
            write_executable(probe, probe_text)
            ok = bool(checker(probe))
            probe.unlink(missing_ok=True)
            if ok:
                return root
        except OSError:
            continue
    raise error_cls(miss)


def inspect_lock(path: Any, *, error_cls: Any = OSError) -> dict[str, Any]:
    """Inspect a flock file without taking exclusive ownership."""

    lock_path = Path(path)
    if not lock_path.exists():
        return {
            "path": str(lock_path),
            "exists": False,
            "held": False,
            "pid": None,
            "method": "missing",
            "error": "",
        }
    held, pid, method = proc_exclusive_holder(lock_path)
    error = ""
    if held is None:
        error = method
        try:
            held, method = shared_lock_busy(lock_path, error_cls=error_cls)
            pid = None
        except Exception as exc:  # noqa: BLE001 — lock state must fail closed
            return {
                "path": str(lock_path),
                "exists": True,
                "held": True,
                "pid": None,
                "method": "error",
                "error": f"{error}; {type(exc).__name__}: {exc}",
            }
    elif held is False:
        try:
            sh_held, sh_method = shared_lock_busy(lock_path, error_cls=error_cls)
            if sh_held:
                held = True
                method = sh_method
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
    return {
        "path": str(lock_path),
        "exists": True,
        "held": bool(held),
        "pid": pid,
        "method": method,
        "error": error,
    }


def refuse_basename(
    path: Any,
    name: str,
    *,
    error_cls: Any = ValueError,
    fmt: str = "refusing {name}: {path!r}",
) -> str:
    text = str(path or "")
    if Path(text).name == str(name):
        raise error_cls(fmt.format(name=name, path=path))
    return text


def pinned_env_argv(
    driver: str,
    tool: str,
    source: str,
    *,
    driver_name: str,
    tool_name: str,
    subcmd: str = "env",
    flags: Sequence[str] = (),
    refuse: Optional[str] = None,
    error_cls: Any = ValueError,
    empty: str = "source_file is required",
    driver_fmt: str = "expected tag-pinned {name}, got {path!r}",
    tool_fmt: str = "expected tag-pinned {name}, got {path!r}",
    refuse_fmt: str = "refusing {name}: {path!r}",
) -> list[str]:
    """``driver subcmd tool [flags...] source`` with basename pins. Never PATH."""

    driver_path = require_basename(driver, driver_name, error_cls=error_cls, fmt=driver_fmt)
    tool_path = require_basename(tool, tool_name, error_cls=error_cls, fmt=tool_fmt)
    source_path = require_str(source, error_cls=error_cls, empty=empty)
    if refuse:
        refuse_basename(source_path, refuse, error_cls=error_cls, fmt=refuse_fmt)
    return [driver_path, str(subcmd), tool_path, *[str(flag) for flag in flags], source_path]


def walk_suffix_files(root: Any, suffix: str) -> list[Path]:
    import os

    target = Path(root)
    if not target.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames.sort()
        for name in sorted(filenames):
            if name.endswith(suffix):
                found.append(Path(dirpath) / name)
    return found


def existing_files(candidates: Sequence[Any], *, exclude_names: Sequence[str] = ()) -> list[Path]:
    banned = {str(name) for name in exclude_names}
    out: list[Path] = []
    for cand in candidates:
        if cand is None:
            continue
        path = Path(cand)
        try:
            if path.is_file() and path.name not in banned:
                out.append(path)
        except OSError:
            continue
    return out


def write_blobs(root: Any, files: Mapping[str, bytes]) -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for rel, data in files.items():
        path = dest / str(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return dest


def plant_executables(root: Any, files: Mapping[str, str], *, encoding: str = "utf-8") -> Path:
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        write_executable(dest / str(name), text, encoding=encoding)
    return dest


def pinned_bin_paths(
    home: Any,
    dirname: str,
    names: Sequence[str],
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    home_path = Path(home)
    toolchain_dir = home_path / "toolchains" / str(dirname)
    bin_dir = toolchain_dir / "bin"
    paths = {str(name): bin_dir / str(name) for name in names}
    installed = {name: is_executable(path) for name, path in paths.items()}
    out: dict[str, Any] = {
        "elan_home": str(home_path),
        "toolchain_dir": str(toolchain_dir),
        "bin_dir": str(bin_dir),
        "executable_paths": {name: str(path) for name, path in paths.items()},
        "installed": all(installed.values()) if installed else False,
    }
    for name, path in paths.items():
        out[f"{name}_path"] = str(path)
        out[f"{name}_installed"] = installed[name]
    if extra:
        out.update(dict(extra))
    return out


def nonempty_file(path: Any) -> bool:
    target = Path(path)
    try:
        return target.is_file() and target.stat().st_size > 0
    except OSError:
        return False


def home_config_file(
    filename: str,
    *,
    env_key: str = "",
    default_dir: str = "",
    environ: Optional[Any] = None,
    home: Optional[Any] = None,
) -> Path:
    """``$ENV/filename`` or ``<home>/<default_dir>/filename``. Does not read the file."""

    import os

    source = os.environ if environ is None else environ
    raw = ""
    if env_key and hasattr(source, "get"):
        raw = str(source.get(env_key) or "").strip()
    if raw:
        base = Path(raw).expanduser()
    else:
        base = (Path.home() if home is None else Path(home)) / str(default_dir)
    return base / str(filename)


def require_file(
    path: Any,
    *,
    error_cls: Any = FileNotFoundError,
    miss: str = "missing {path}",
) -> Path:
    """Require a file. Raise if missing. Empty files are still files."""

    dest = Path(path)
    if not dest.is_file():
        raise error_cls(miss.format(path=dest))
    return dest


def path_parts_status(
    path: Any,
    *,
    forbidden: Sequence[str] = (),
    all_markers: Sequence[str] = (),
    forbidden_reason: str = "forbidden_path",
    markers_reason: str = "marker_path",
    ok_reason: str = "ok",
) -> tuple[bool, str]:
    parts = [str(part).strip().lower() for part in Path(path).parts]
    banned = {str(item).strip().lower() for item in forbidden}
    if any(part in banned for part in parts):
        return False, forbidden_reason
    markers = [str(item).strip().lower() for item in all_markers]
    if markers and all(marker in parts for marker in markers):
        return False, markers_reason
    return True, ok_reason


def first_json_dict(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    candidates = [raw, *reversed([line.strip() for line in raw.splitlines() if line.strip()])]
    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def http_ok(
    status: Optional[int],
    error: str = "",
    *,
    max_status: int = 500,
) -> tuple[bool, str]:
    ok = status is not None and int(status) < int(max_status)
    detail = str(error or "")
    if not ok and not detail and status is not None:
        detail = f"HTTP {status}"
    return ok, detail


def name_fallback_used(
    resolved: str,
    *,
    allowed: Sequence[str],
    forbidden: Sequence[str] = (),
) -> bool:
    text = str(resolved or "").strip().lower()
    if not text:
        return False
    allowed_set = {str(item).strip().lower() for item in allowed}
    forbidden_set = {str(item).strip().lower() for item in forbidden}
    return text not in allowed_set or text in forbidden_set


def write_text(
    path: Any,
    text: str,
    *,
    encoding: str = "utf-8",
    refuse: Optional[str] = None,
    error_cls: Any = ValueError,
    refuse_fmt: str = "refusing {name}: {path!r}",
) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if refuse:
        refuse_basename(dest, refuse, error_cls=error_cls, fmt=refuse_fmt)
    dest.write_text(str(text), encoding=encoding)
    return dest


def read_text(
    path: Any,
    *,
    encoding: str = "utf-8",
    errors: str = "strict",
    max_chars: Optional[int] = None,
) -> str:
    text = Path(path).read_text(encoding=encoding, errors=errors)
    if max_chars is None:
        return text
    return text[: max(0, int(max_chars))]


def source_text(source: Optional[str] = None, *, path: Any, encoding: str = "utf-8") -> str:
    """Use ``source`` when given, else read ``path``."""

    if source is not None:
        return str(source)
    return read_text(path, encoding=encoding)


def copy_text(src: Any, dest: Any, *, encoding: str = "utf-8") -> Path:
    return write_text(dest, read_text(src, encoding=encoding), encoding=encoding)


def state_root_from_env(
    *,
    override_key: str,
    relative: Any,
    environ: Optional[Any] = None,
    home: Optional[Any] = None,
) -> Path:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get(override_key) if hasattr(dest, "get") else None
    if raw is not None and str(raw).strip():
        return Path(str(raw).strip())
    homes = state_home_candidates(environ=dest, home=home)
    rel = Path(relative)
    if homes:
        return homes[0] / rel
    return Path.home() / ".local" / "state" / rel


def mkdtemp_under(
    parent: Any,
    *,
    prefix: str = "tmp-",
    files: Optional[Mapping[str, str]] = None,
) -> Path:
    import tempfile

    root = Path(parent)
    root.mkdir(parents=True, exist_ok=True)
    dest = Path(tempfile.mkdtemp(prefix=str(prefix), dir=str(root)))
    if files:
        plant_files(dest, files)
    return dest


def mkdtemp(*, prefix: str = "tmp-", parent: Optional[Any] = None, files: Optional[Mapping[str, str]] = None) -> Path:
    """tempfile.mkdtemp as Path. Optional parent uses mkdtemp_under."""

    import tempfile

    if parent is None:
        dest = Path(tempfile.mkdtemp(prefix=str(prefix)))
        if files:
            plant_files(dest, files)
        return dest
    return mkdtemp_under(parent, prefix=prefix, files=files)


def temp_dir(*, prefix: str = "tmp-", parent: Optional[Any] = None) -> Any:
    """tempfile.TemporaryDirectory. Use as a context manager."""

    import tempfile

    kwargs: dict[str, Any] = {"prefix": str(prefix)}
    if parent is not None:
        kwargs["dir"] = str(parent)
    return tempfile.TemporaryDirectory(**kwargs)


def elapsed_ms(started: float, *, now: Optional[float] = None) -> float:
    """Milliseconds since ``started`` (perf_counter)."""

    import time

    end = float(now if now is not None else time.perf_counter())
    return max(0.0, (end - float(started)) * 1000.0)


def timed_call(fn: Any, *args: Any, **kwargs: Any) -> tuple[Any, float, float]:
    """Run fn and return (result, wall_ms, child_cpu_ms)."""

    import resource
    import time

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started = time.perf_counter()
    result = fn(*args, **kwargs)
    wall_ms = elapsed_ms(started)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_ms = max(
        0.0,
        ((after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)) * 1000.0,
    )
    return result, wall_ms, cpu_ms


def process_exit_code(result: Any, *, timeout_code: int = 124) -> tuple[int, bool]:
    timed_out = bool(getattr(result, "timed_out", False))
    if isinstance(result, Mapping):
        timed_out = timed_out or bool(result.get("timeout") or result.get("timed_out"))
    error = getattr(result, "error", None)
    if not error and isinstance(result, Mapping):
        error = result.get("error") or None
    returncode = getattr(result, "returncode", None)
    if returncode is None and isinstance(result, Mapping):
        returncode = result.get("exit_code")
    if timed_out:
        return int(timeout_code), True
    if error:
        return (1 if returncode in (None, 0) else int(returncode)), False
    if returncode is None:
        return 0, False
    return int(returncode), False


def write_named_jsons(
    dest_dir: Any,
    rows: Sequence[Any],
    *,
    name_fn: Any,
    tag_fn: Any,
    payload_fn: Any,
    empty: str = "unnamed",
) -> list[str]:
    dest = Path(dest_dir)
    written: list[str] = []
    for row in rows:
        name = str(name_fn(row) or "").replace("/", "_") or empty
        tag = str(tag_fn(row))
        path = write_json(dest / name / f"{tag}.json", payload_fn(row))
        written.append(str(path))
    return written


def which_bin(name: str, *, default: str = "") -> str:
    import shutil

    return shutil.which(str(name)) or str(default)


def any_search(texts: Sequence[Any], pattern: Any) -> bool:
    search = getattr(pattern, "search", None)
    if search is None:
        return False
    return any(bool(search(str(text or ""))) for text in texts)


def glob_after(root: Any, pattern: str, *, first: Optional[Any] = None) -> list[Path]:
    dest = Path(root)
    out: list[Path] = []
    if first is not None:
        head = Path(first)
        try:
            if head.is_file():
                out.append(head)
        except OSError:
            pass
    try:
        extra = sorted(dest.glob(str(pattern)))
    except OSError:
        extra = []
    for path in extra:
        if path not in out:
            out.append(path)
    return out


def first_file_text(
    paths: Sequence[Any],
    *,
    drop_substr: str = "",
    reject_fn: Optional[Any] = None,
    error_cls: Any = FileNotFoundError,
    miss: str = "no matching file",
) -> str:
    for path in paths:
        target = Path(path)
        try:
            if not target.is_file():
                continue
            raw = target.read_text(encoding="utf-8")
        except OSError:
            continue
        if drop_substr:
            lines = [line for line in raw.splitlines() if drop_substr not in line]
            body = "\n".join(lines).strip()
        else:
            body = raw.strip()
        if not body:
            continue
        if reject_fn is not None and reject_fn(body):
            continue
        return body + "\n"
    raise error_cls(miss)


def is_stub_text(
    text: str,
    *,
    marker: str = "",
    max_words: int = 12,
    exact: str = "",
) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return True
    if marker and marker in stripped and len(stripped.split()) < int(max_words):
        return True
    if exact and stripped == str(exact).strip():
        return True
    return False


def collect_until(
    items: Sequence[Any],
    fn: Any,
    *,
    abort_fn: Optional[Any] = None,
    remaining_fn: Optional[Any] = None,
    remaining_attr: str = "",
) -> list[Any]:
    """Map items through fn; stop after abort_fn(result). Optional remaining list."""

    out: list[Any] = []
    rest = list(items)
    for item in items or ():
        rest = rest[1:]
        result = fn(item)
        if remaining_attr and abort_fn is not None and abort_fn(result):
            leftover = remaining_fn(rest) if remaining_fn is not None else list(rest)
            try:
                setattr(result, remaining_attr, leftover)
            except Exception:
                if isinstance(result, dict):
                    result[remaining_attr] = leftover
        out.append(result)
        if abort_fn is not None and abort_fn(result):
            break
    return out


def first_or_last(
    items: Sequence[Any],
    pred: Any,
    *,
    error_cls: Any = ValueError,
    miss: str = "empty",
) -> Any:
    rows = list(items or ())
    for item in rows:
        if pred(item):
            return item
    if rows:
        return rows[-1]
    raise error_cls(miss)


def require_exact_keys(
    mapping: Any,
    keys: Sequence[str],
    *,
    error_cls: Any = ValueError,
    not_map: str = "must be a mapping",
    extra_fmt: str = "unexpected keys {keys}",
    miss_fmt: str = "missing keys {keys}",
    empty_fmt: str = "empty {key}",
) -> dict[str, str]:
    if not isinstance(mapping, Mapping):
        raise error_cls(not_map)
    got = {str(key): str(value) for key, value in mapping.items()}
    expected = [str(key) for key in keys]
    extra = sorted(set(got) - set(expected))
    if extra:
        raise error_cls(extra_fmt.format(keys=extra))
    missing = sorted(set(expected) - set(got))
    if missing:
        raise error_cls(miss_fmt.format(keys=missing))
    out: dict[str, str] = {}
    for key in expected:
        text = got[key].strip()
        if not text:
            raise error_cls(empty_fmt.format(key=key))
        out[key] = text
    return out


def reject_present_keys(
    mapping: Mapping[str, Any],
    keys: Sequence[str],
    *,
    error_cls: Any = ValueError,
    fmt: str = "forbidden field {key!r}",
    empty: Any = (None, "", []),
) -> None:
    for key in keys:
        if key in mapping and mapping[key] not in empty:
            raise error_cls(fmt.format(key=key))


def quoted_strings(text: str, *, pattern: str = r'"([a-z_]+)"') -> tuple[str, ...]:
    return tuple(re.findall(str(pattern), str(text or "")))


def is_hex_digest(text: str, *, n: int = 64) -> bool:
    blob = str(text or "")
    return bool(re.fullmatch(r"[0-9a-f]{" + str(int(n)) + r"}", blob))


def pin_env(
    pairs: Mapping[str, str],
    *,
    environ: Optional[Any] = None,
    overwrite: bool = True,
) -> None:
    import os

    dest = os.environ if environ is None else environ
    for key, value in dict(pairs).items():
        name = str(key)
        if overwrite or not dest.get(name):
            dest[name] = str(value)


def require_env_eq(
    key: str,
    expected: str,
    *,
    environ: Optional[Any] = None,
    error_cls: Any = ValueError,
    fmt: str = "{key} must be {expected}",
) -> str:
    import os

    dest = os.environ if environ is None else environ
    got = dest.get(key)
    if str(got) != str(expected):
        raise error_cls(fmt.format(key=key, expected=expected, got=got))
    return str(got)


def argv_layout(
    argv: Sequence[Any],
    *,
    min_len: int = 0,
    names: Optional[Mapping[int, str]] = None,
    eq: Optional[Mapping[int, str]] = None,
    contains: Optional[Mapping[int, str]] = None,
) -> bool:
    rows = [str(item) for item in argv or ()]
    if len(rows) < int(min_len):
        return False
    for index, name in dict(names or {}).items():
        if int(index) >= len(rows) or Path(rows[int(index)]).name != str(name):
            return False
    for index, value in dict(eq or {}).items():
        if int(index) >= len(rows) or rows[int(index)] != str(value):
            return False
    for index, needle in dict(contains or {}).items():
        if int(index) >= len(rows) or str(needle) not in rows[int(index)]:
            return False
    return True


def token_family(
    opener: str,
    *,
    prefixes: Sequence[str] = (),
    aliases: Optional[Mapping[str, str]] = None,
    trail: str = "!'",
) -> str:
    parts = str(opener or "").split()
    token = parts[0].rstrip(trail) if parts else ""
    for prefix in prefixes:
        if token.startswith(str(prefix)):
            return str(prefix)
    return str(dict(aliases or {}).get(token, token))


def row_dict(row: Any, keys: Sequence[str]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for index, key in enumerate(keys):
        try:
            out[str(key)] = row[index]
        except Exception:
            out[str(key)] = None
    return out


def row_cell(row: Any, index: int = 0, *, default: Any = None) -> Any:
    if row is None:
        return default
    try:
        value = row[int(index)]
    except Exception:
        return default
    return default if value is None else value


def path_refused(
    path: Any,
    *,
    names: Sequence[str] = (),
    needles: Sequence[str] = (),
) -> bool:
    dest = Path(path)
    text = str(dest)
    if dest.name in {str(name) for name in names}:
        return True
    return any(str(needle) in text for needle in needles)


def without_prefix(text: str, prefix: str) -> str:
    raw = str(text or "")
    if prefix and raw.startswith(prefix):
        return raw[len(prefix) :]
    return raw


def module_stem(
    name: str,
    *,
    strip_prefix: str = "",
    split_on: str = ":",
) -> Optional[str]:
    """Module path from ``ptr://kind/module:symbol``. Rejects ``..`` and abs paths."""

    raw = str(name or "").strip()
    if strip_prefix:
        raw = without_prefix(raw, strip_prefix)
    if not raw or ".." in raw or raw.startswith("/"):
        return None
    if split_on:
        raw = raw.split(split_on, 1)[0]
    return raw or None


def cut_prefix(text: str, end: int, *, suffix: str = "\n") -> str:
    return str(text or "")[: int(end)].rstrip() + str(suffix)


def dumps_compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def dumps_sorted(value: Any, *, indent: Optional[int] = None, newline: bool = False) -> str:
    """json.dumps with sort_keys. Optional indent and trailing newline."""

    text = json.dumps(value, indent=indent, sort_keys=True)
    return text + ("\n" if newline else "")


def digest_compact(value: Any) -> str:
    return digest_hex(dumps_compact(value).encode("utf-8"))


def connect_engine(path: Any, *, duckdb_module: Any = None) -> tuple[Any, str]:
    import sqlite3

    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    module = duckdb_module if duckdb_module is not None else try_import("duckdb")
    if module is not None:
        return module.connect(str(dest)), "duckdb"
    return sqlite3.connect(str(dest)), "sqlite3"


def env_str(key: str, default: str = "", *, environ: Optional[Any] = None) -> str:
    import os

    dest = os.environ if environ is None else environ
    raw = dest.get(key) if hasattr(dest, "get") else None
    return str(raw if raw not in (None, "") else default)


def env_mapping(env: Optional[Any] = None) -> Any:
    """Return env if given, else os.environ. Does not copy."""

    import os

    return os.environ if env is None else env


def optional_env_path(*names: str, environ: Optional[Any] = None) -> Optional[Path]:
    """First nonempty env value as Path, else None."""

    for name in names:
        raw = env_str(name, environ=environ)
        if raw:
            return Path(raw)
    return None


def env_int(
    key: str,
    default: Any,
    *,
    minimum: Optional[int] = None,
    environ: Optional[Any] = None,
) -> int:
    value = int(env_str(key, str(default), environ=environ) or int(default))
    if minimum is not None:
        value = max(int(minimum), value)
    return value


def partition(items: Sequence[Any], pred: Any) -> tuple[list[Any], list[Any]]:
    yes: list[Any] = []
    no: list[Any] = []
    for item in items or ():
        (yes if pred(item) else no).append(item)
    return yes, no


def map_partition(items: Sequence[Any], pred: Any, fn: Any) -> tuple[list[Any], list[Any]]:
    yes, no = partition(items, pred)
    return [fn(item) for item in yes], [fn(item) for item in no]


def first_matching_line(text: str, pred: Any) -> Optional[str]:
    for line in str(text or "").splitlines():
        if pred(line):
            return line
    return None


def first_token(text: str, *, strip: str = "") -> str:
    parts = str(text or "").split()
    token = parts[0] if parts else ""
    return token.rstrip(strip) if strip else token


def result_usage(result: Any, *, fallback_in: int = 0) -> tuple[int, int]:
    usage = getattr(result, "usage", None)
    if not isinstance(usage, Mapping):
        usage = {}
    return usage_tokens(usage, fallback_in=int(fallback_in))


def attr_map(
    container: Any,
    names: Sequence[str],
    attr: str,
    *,
    default: Any = 0.0,
    cast: Any = float,
) -> dict[str, Any]:
    row = container if isinstance(container, Mapping) else {}
    out: dict[str, Any] = {}
    for name in names:
        item = row.get(name)
        value = getattr(item, attr, default) if item is not None else default
        out[str(name)] = cast(value or default)
    return out


def client_kwargs(
    module: Any,
    *,
    timeout: float = 45.0,
    max_retries: int = 5,
    backoff_max: float = 20.0,
    retry_statuses: Sequence[int] = (429, 503, 529),
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": float(timeout)}
    policy_cls = getattr(module, "RetryPolicy", None)
    if policy_cls is None:
        return kwargs
    try:
        kwargs["retry"] = policy_cls(
            max_retries=int(max_retries),
            backoff_max=float(backoff_max),
            timeout=float(timeout),
            retry_statuses=tuple(retry_statuses),
        )
    except TypeError:
        kwargs["retry"] = policy_cls(
            max_retries=int(max_retries),
            backoff_max=float(backoff_max),
            timeout=float(timeout),
        )
    return kwargs


def after_calls(setup: Sequence[Any], fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Run setup callables, then ``fn(*args, **kwargs)``."""

    for item in setup or ():
        item()
    return fn(*args, **kwargs)


def import_names(
    module: str,
    names: Sequence[str],
    *,
    setup: Sequence[Any] = (),
) -> tuple[Optional[dict[str, Any]], Optional[BaseException]]:
    """Import named attrs. Missing module returns (None, ImportError). Never PATH."""

    for item in setup or ():
        item()
    wanted = [str(name) for name in names]
    try:
        loaded = __import__(str(module), fromlist=wanted or ["*"])
    except ImportError as exc:
        return None, exc
    return {name: getattr(loaded, name, None) for name in wanted}, None


def load_configured(path: Any, spec: str, *, configured: str = "typesafe_configured") -> Any:
    module = load_module_from_path(path, spec)
    if module is None:
        return None
    fn = getattr(module, configured, None)
    if callable(fn) and not fn():
        return None
    return module


def unique_kind_bodies(
    items: Sequence[Mapping[str, Any]],
    *,
    kind_key: str = "kind",
    body_key: str = "tactics",
    keep: Optional[Mapping[str, str]] = None,
    skip_eq: str = "",
) -> dict[str, str]:
    found = dict(keep or {})
    skip = str(skip_eq).strip("\n")
    for item in items or ():
        kind = str(item.get(kind_key) or "")
        body = str(item.get(body_key) or "").strip("\n")
        if kind and body and body != skip:
            found[kind] = body
    return found


def field_of(item: Any, *names: str, default: Any = "") -> Any:
    """First nonempty mapping key or attribute among names."""

    for name in names:
        value = None
        if isinstance(item, Mapping) and name in item:
            value = item.get(name)
        elif item is not None and hasattr(item, name):
            value = getattr(item, name, None)
        if value not in (None, ""):
            return value
    return default


def filter_map(
    items: Sequence[Any],
    *,
    pred: Any = None,
    map_fn: Any = None,
    skip_exc: Any = (),
) -> list[Any]:
    """Keep items where pred is true, optionally map. pred exceptions in skip_exc skip."""

    out: list[Any] = []
    errors = skip_exc if skip_exc else ()
    for item in items or ():
        try:
            if pred is not None and not pred(item):
                continue
        except errors:
            continue
        out.append(map_fn(item) if map_fn is not None else item)
    return out


def first_table_sql(tables: Any, mapping: Mapping[str, str]) -> Optional[str]:
    """First SQL whose table name is in the SHOW TABLES set (casefold)."""

    bag = {str(name).casefold() for name in tables or ()}
    for name, sql in dict(mapping or {}).items():
        if str(name).casefold() in bag:
            return str(sql)
    return None


def engine_tables(con: Any, *, sql: str = "SHOW TABLES") -> set[str]:
    try:
        return {str(row[0]).casefold() for row in con.execute(sql).fetchall() if row and row[0]}
    except Exception:
        return set()


def open_readonly(
    path: Any,
    *,
    refuse_names: Sequence[str] = (),
    engine_module: Any = None,
) -> tuple[Any, str]:
    """Open DuckDB (if present) read-only. Does not mkdir. Campaign names can be refused."""

    dest = Path(path)
    if path_refused(dest, names=refuse_names):
        return None, "refused"
    if not dest.is_file():
        return None, "missing"
    module = engine_module if engine_module is not None else try_import("duckdb")
    if module is None:
        return None, "unavailable"
    try:
        try:
            return module.connect(str(dest), read_only=True), "ok"
        except TypeError:
            return module.connect(str(dest)), "ok"
    except Exception:
        return None, "connect_failed"


def query_engine(
    path: Any,
    sql: str,
    params: Sequence[Any] = (),
    *,
    refuse_names: Sequence[str] = (),
    read_only: bool = True,
    row_fn: Any = None,
    engine_module: Any = None,
) -> list[Any]:
    """Optional DuckDB SELECT. Missing/refused/unavailable → []. Never campaign writes."""

    dest = Path(path)
    if not read_only:
        con, note = None, "write_unsupported"
        module = engine_module if engine_module is not None else try_import("duckdb")
        if module is None or path_refused(dest, names=refuse_names):
            return []
        try:
            con = module.connect(str(dest))
            note = "ok"
        except Exception:
            return []
    else:
        con, note = open_readonly(dest, refuse_names=refuse_names, engine_module=engine_module)
    if con is None or note not in {"ok"}:
        return []
    try:
        try:
            rows = con.execute(str(sql), list(params)).fetchall()
        except Exception:
            return []
    finally:
        try:
            con.close()
        except Exception:
            pass
    out: list[Any] = []
    for row in rows or ():
        mapped = row_fn(row) if row_fn is not None else row
        if mapped is not None:
            out.append(mapped)
    return out


def insert_ignore_conflict(
    fn: Any,
    *args: Any,
    error_cls: Any = ValueError,
    fail_fmt: str = "INSERT failed: {exc}",
    **kwargs: Any,
) -> bool:
    """Run fn; unique/integrity conflicts return False. Other errors raise error_cls."""

    try:
        fn(*args, **kwargs)
        return True
    except Exception as exc:
        if integrity_conflict(exc):
            return False
        raise error_cls(fail_fmt.format(exc=exc)) from exc


def pack_receipt_insert_params(
    receipt: Any,
    *,
    schema: str,
    dumps_fn: Callable[[Any], str],
    tiny_fn: Callable[[Mapping[str, Any]], str],
) -> tuple[Any, ...]:
    """Tiny INSERT params. SQL strings stay in the consumer."""

    payload = {
        "candidate_cid": getattr(receipt, "candidate_cid", None),
        "generator": getattr(receipt, "generator", None),
        "hardware_class": getattr(receipt, "hardware_class", None),
        "kernel_command_template": getattr(receipt, "kernel_command_template", None),
        "key_digest": getattr(receipt, "key_digest", None),
        "schema": schema,
    }
    blob = tiny_fn(payload)
    paths = getattr(receipt, "executable_paths", None)
    paths_dict = paths.to_dict() if hasattr(paths, "to_dict") else dict(paths or {})
    return (
        getattr(receipt, "key_digest", None),
        getattr(receipt, "name", None),
        getattr(receipt, "lean_tag", None),
        getattr(receipt, "body_digest", None),
        getattr(receipt, "candidate_cid", None),
        getattr(receipt, "verdict", None),
        getattr(receipt, "token_count", None),
        getattr(receipt, "elab_proxy", None),
        dumps_fn(getattr(receipt, "dimensions", None) or {}),
        dumps_fn(paths_dict),
        blob,
        getattr(receipt, "created_at", None),
    )


@dataclass(frozen=True)
class LockInspection:
    path: str
    exists: bool
    held: bool
    pid: Optional[int]
    method: str
    error: str
    lock_id: str = ""
    lock_ex_taken_by_client: bool = False


@dataclass(frozen=True)
class OwnerExec:
    attempted: bool
    executed: bool
    argv: list[str]
    argv_relative: list[str]
    pid: Optional[int]
    returncode: Optional[int]
    started_llama_server: bool
    error: str = ""


def pack_owner_exec(
    *,
    attempted: bool,
    executed: bool,
    argv: Sequence[str],
    argv_relative: Sequence[str],
    pid: Optional[int] = None,
    returncode: Optional[int] = None,
    error: str = "",
    started_llama_server: bool = False,
) -> OwnerExec:
    """Client-side owner-exec receipt. Never starts llama-server here."""

    return OwnerExec(
        attempted=bool(attempted),
        executed=bool(executed),
        argv=list(argv or ()),
        argv_relative=list(argv_relative or ()),
        pid=pid,
        returncode=returncode,
        started_llama_server=bool(started_llama_server),
        error=str(error or ""),
    )


def run_owner_exec(
    *,
    execute: bool,
    argv: Sequence[str],
    argv_relative: Sequence[str],
    pack_fn: Callable[..., Any],
    target: Any = None,
    run_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: float = 5.0,
) -> Any:
    """Optionally exec the owner script. This process still does not take EX."""

    argv = list(argv or ())
    rel = list(argv_relative or ())
    if not execute:
        return pack_fn(attempted=False, executed=False, argv=argv, argv_relative=rel)
    dest = Path(target if target is not None else (argv[2] if len(argv) > 2 else ""))
    if not dest.is_file():
        return pack_fn(
            attempted=True,
            executed=False,
            argv=argv,
            argv_relative=rel,
            error=f"owner script missing: {dest}",
        )
    if run_fn is None:
        return pack_fn(attempted=True, executed=False, argv=argv, argv_relative=rel, error="run_fn missing")
    try:
        ran = dict(run_fn(argv, env=env, timeout=float(timeout)) or {})
    except OSError as exc:
        from jevops.outer import exc_text

        return pack_fn(
            attempted=True,
            executed=False,
            argv=argv,
            argv_relative=rel,
            error=exc_text(exc),
        )
    if ran.get("timeout"):
        return pack_fn(
            attempted=True,
            executed=True,
            argv=argv,
            argv_relative=rel,
            pid=ran.get("pid"),
            error=str(ran.get("error") or "TimeoutExpired"),
        )
    code = ran.get("exit_code")
    return pack_fn(
        attempted=True,
        executed=True,
        argv=argv,
        argv_relative=rel,
        returncode=int(code) if code is not None else None,
        error="" if ran.get("ok") else (ran.get("stderr") or ran.get("stdout") or f"exit {code}"),
    )


@dataclass(frozen=True)
class ClientSession:
    action: str
    health: dict[str, Any]
    lock: dict[str, Any]
    autostart: str
    lock_ex_taken_by_client: bool
    llama_server_started: bool
    owner_exec: dict[str, Any]
    skipped: bool
    reason: str


def session_reason(
    action: str,
    *,
    lock_held: bool = False,
    allow_owner_exec: bool = False,
) -> str:
    """Normative client-protocol reason. Never an exclusive-lock action."""

    reasons = {
        "generate": "docker0 /health ok; generate_text as HTTP client without exclusive lock",
        "wait": "docker0 unhealthy and owner exclusive lock held; wait for /health",
        "skip_llm": "docker0 unhealthy; skip LLM (exclusive lock held or owner exec not permitted)",
        "exec_owner": "docker0 unhealthy and gpu-0.lock free; may exec run_leanstral_ephemeral.py",
    }
    reason = reasons.get(action, action)
    if action == "skip_llm" and lock_held:
        return "docker0 unhealthy and owner exclusive lock held; skip LLM"
    if action == "skip_llm" and not allow_owner_exec:
        return "docker0 unhealthy; owner exec not permitted; skip LLM"
    return reason


def pack_client_session(
    *,
    action: str,
    health: Any,
    lock: Any,
    autostart: str,
    owner: Any,
    reason: str,
    session_cls: Any = None,
) -> Any:
    from dataclasses import asdict as _asdict

    cls = session_cls or ClientSession

    def _row(item: Any) -> dict[str, Any]:
        if isinstance(item, Mapping):
            return dict(item)
        return _asdict(item)

    return cls(
        action=action,
        health=_row(health),
        lock=_row(lock),
        autostart=str(autostart or ""),
        lock_ex_taken_by_client=False,
        llama_server_started=False,
        owner_exec=_row(owner),
        skipped=action != "generate",
        reason=reason,
    )


def generate_client_flow(
    *,
    health: Any,
    lock: Any,
    generate_fn: Callable[[], Any],
    wait_fn: Callable[[float], Any],
    exec_fn: Callable[[bool], Any],
    skip_fn: Callable[..., Any],
    decide_fn: Callable[..., str],
    allow_owner_exec: bool = False,
    wait_seconds: float = 0.0,
    execute_owner: bool = False,
    wait_reason: str = "docker0 unhealthy after wait; owner exclusive lock held; skip LLM",
    exec_reason: str = "owner exec not started in this process; skip LLM",
    skip_reason: str = "docker0 unhealthy; skip LLM without taking owner exclusive lock",
) -> Any:
    """Client generate/wait/skip/exec-owner. Never takes exclusive lock here."""

    if getattr(health, "ok", False):
        return generate_fn()
    action = decide_fn(
        health,
        lock,
        allow_owner_exec=allow_owner_exec,
        wait_seconds=wait_seconds,
    )
    if action == "wait":
        nxt = wait_fn(float(wait_seconds))
        if getattr(nxt, "ok", False):
            return generate_fn()
        return skip_fn(nxt, wait_reason)
    if action == "exec_owner":
        owner = exec_fn(bool(execute_owner))
        if getattr(owner, "executed", False) and getattr(owner, "returncode", None) == 0:
            nxt = wait_fn(max(float(wait_seconds), 1.0))
            if getattr(nxt, "ok", False):
                return generate_fn()
        return skip_fn(health, getattr(owner, "error", "") or exec_reason)
    return skip_fn(health, skip_reason)


def spend_kind(
    kind: str,
    *,
    models: Mapping[str, str],
    counts: Mapping[str, int],
    error_cls: Any = ValueError,
    unknown_fmt: str = "unknown spend kind {kind!r}",
) -> tuple[str, str, int]:
    """(kind_key, default_model, next_call_index). Unknown kinds raise."""

    kind_key = str(kind or "").strip().lower()
    if kind_key not in models:
        raise error_cls(unknown_fmt.format(kind=kind_key))
    return kind_key, str(models[kind_key]), int(counts.get(kind_key) or 0) + 1


def select_named(
    records: Sequence[Mapping[str, Any]],
    names: Optional[Sequence[str]],
    *,
    error_cls: Any = ValueError,
    miss_fmt: str = "unknown warm-up names: {missing}",
    name_key: str = "name",
) -> list[Mapping[str, Any]]:
    """Keep records whose name is in names. Empty names keeps all."""

    rows = list(records or ())
    if not names:
        return rows
    wanted = set(names)
    selected = [item for item in rows if item.get(name_key) in wanted]
    missing = wanted - {item.get(name_key) for item in selected}
    if missing:
        raise error_cls(miss_fmt.format(missing=sorted(str(x) for x in missing)))
    return selected


def select_limit(items: Sequence[Any], limit: Optional[int]) -> list[Any]:
    rows = list(items or ())
    if limit is None:
        return rows
    return rows[: max(0, int(limit))]


def closed_skip(
    reason: str,
    *,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Fail-closed skip payload. Never a generated proof."""

    out: dict[str, Any] = {
        "ok": True,
        "skipped": True,
        "reason": str(reason),
        "called_mistral": False,
        "arena_score": None,
    }
    if extra:
        out.update(dict(extra))
    return out


def skill_loop_payload(
    *,
    outer: int,
    llm: bool,
    history: Sequence[Mapping[str, Any]],
    board: Mapping[str, int],
    total: int,
    best_total: Any,
    stop_reason: str,
    memory_path: Any,
    memory_skills: Sequence[Any],
    ledger: Any,
    protocol: str,
    pr_id: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from jevops.outer import closed_evidence, utc_stamp

    out: dict[str, Any] = {
        "schema": "lra-skill-improve-loop/v1",
        "protocol": protocol,
        "pr_id": pr_id,
        "observed_at": utc_stamp(),
        "outer": "grok",
        "llm": bool(llm),
        "inner": "typesafe_nested",
        "router": "ipfs_accelerate_py.llm_router.generate_text" if llm else "deterministic",
        "history": list(history or ()),
        "board": dict(board or {}),
        "total": int(total),
        "best_total": best_total,
        "stop_reason": str(stop_reason or ""),
        "memory_path": str(memory_path),
        "memory_skills": list(memory_skills or []),
        **closed_evidence(grok_writes_lean=False),
        "ledger": ledger.as_dict() if hasattr(ledger, "as_dict") else {"grok_calls": getattr(ledger, "grok_calls", 0)},
    }
    if extra:
        out.update(dict(extra))
    return out


@dataclass(frozen=True)
class UsageLine:
    kind: str
    input_tokens: int
    output_tokens: int
    milles: int
    call_index: int
    fixture: bool
    model: str
    skipped: bool = False
    reason: str = "recorded"
    usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        from dataclasses import asdict as _asdict

        return _asdict(self)


def spend_for(
    kind: str,
    input_tokens: int,
    output_tokens: int,
    rates: Mapping[str, tuple[Any, Any]],
    *,
    scale: Any = 1_000_000,
    money_fn: Optional[Any] = None,
    error_cls: Any = ValueError,
    unknown_fmt: str = "unknown spend kind {kind!r}",
) -> Any:
    """(in*in_rate + out*out_rate) / scale. Integer milles or Decimal USD."""

    kind_key = str(kind or "").strip().lower()
    inn = max(0, int(input_tokens))
    out = max(0, int(output_tokens))
    if kind_key not in rates:
        raise error_cls(unknown_fmt.format(kind=kind_key))
    inn_rate, out_rate = rates[kind_key]
    if isinstance(scale, (int, float)):
        qty_in: Any = inn
        qty_out: Any = out
    else:
        ctor = type(scale)
        qty_in = ctor(inn)
        qty_out = ctor(out)
    raw = (qty_in / scale) * inn_rate + (qty_out / scale) * out_rate
    return money_fn(raw) if money_fn is not None else raw


def authorize_spend(
    kind: str,
    *,
    official: bool = False,
    counts: Optional[Mapping[str, int]] = None,
    limits: Optional[Mapping[str, int]] = None,
    spent: Any = 0,
    cost: Any = 0,
    budget: Any = 0,
    zero: Any = 0,
    official_reason: str = "official_track2_off",
    hard_reason: str = "hard_stop",
) -> tuple[bool, str, Any]:
    """Fail-closed spend gate. Call-count limits then budget. No HTTP."""

    if official:
        return False, official_reason, zero
    kind_key = str(kind or "").strip().lower()
    count = (counts or {}).get(kind_key)
    limit = (limits or {}).get(kind_key)
    if count is not None and limit is not None and int(count) >= int(limit):
        return False, f"max_{kind_key}_calls", zero
    if spent + cost > budget:
        return False, hard_reason, cost
    return True, "ok", cost


def chat_request_payload(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    temperature: float = 0.0,
    n: int = 1,
    stop: Optional[Sequence[str]] = None,
    min_n_temperature: float = 0.3,
) -> dict[str, Any]:
    """Closed chat/completions body. Does not POST."""

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(temperature),
        "top_p": 1,
        "max_tokens": int(max_tokens),
    }
    if int(n) > 1:
        payload["n"] = int(n)
        if float(payload["temperature"]) <= 0.0:
            payload["temperature"] = float(min_n_temperature)
    if stop:
        payload["stop"] = nonempty_strs(stop)
    return payload


def pack_chat_response(
    data: Mapping[str, Any],
    *,
    status: Any,
    url: str,
    wall_ms: float,
    model: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    from urllib.parse import urlparse

    text, _texts, usage = chat_choice_texts(data)
    inn, out = usage_tokens(usage)
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    finish = str(field_of(choices[0] if choices else {}, "finish_reason") or "")
    packed: dict[str, Any] = {
        "text": text,
        "model": str(data.get("model") or model),
        "id": str(data.get("id") or ""),
        "object": str(data.get("object") or ""),
        "status": status,
        "url_host": urlparse(url).hostname,
        "input_tokens": inn,
        "output_tokens": out,
        "finish_reason": finish,
        "wall_ms": wall_ms,
    }
    if extra:
        packed.update(dict(extra))
    return packed


def ledger_generate(
    ledger: Any,
    kind: str,
    *,
    estimated_in: int,
    estimated_out: int,
    model: str,
    fixture: bool,
    fixture_text: str,
    live_fn: Callable[[], tuple[str, Mapping[str, Any], tuple[int, int]]],
    identity_fn: Callable[..., Mapping[str, Any]],
    error_cls: Any,
    estimate_fn: Optional[Callable[[str], int]] = None,
    refuse_fmt: str = "{kind} call refused: {reason}",
    after_fmt: str = "{kind} spend refused after call: {reason}",
) -> tuple[str, Mapping[str, Any], Any]:
    """Authorize, optional fixture, else live_fn. live_fn returns (text, extra, (in, out))."""

    allowed, reason, _cost = ledger.authorize(kind, estimated_in, estimated_out)
    if not allowed:
        line = ledger.record(
            kind,
            input_tokens=estimated_in,
            output_tokens=estimated_out,
            fixture=fixture,
            model=model,
        )
        raise error_cls(refuse_fmt.format(kind=kind, reason=reason))
    if fixture:
        identity = identity_fn(model=model, fixture=True)
        out_n = int(estimate_fn(fixture_text) if estimate_fn is not None else estimated_out)
        line = ledger.record(
            kind,
            input_tokens=estimated_in,
            output_tokens=out_n,
            fixture=True,
            model=model,
        )
        return str(fixture_text), dict(identity), line
    text, extra, usage = live_fn()
    inn, out = usage
    identity = identity_fn(model=model, fixture=False, extra=extra, text=text)
    line = ledger.record(
        kind,
        input_tokens=int(inn),
        output_tokens=int(out),
        fixture=False,
        model=str(identity.get("resolved_model") or model),
    )
    if getattr(line, "skipped", False):
        raise error_cls(after_fmt.format(kind=kind, reason=getattr(line, "reason", "")))
    return str(text), dict(identity), line


class InsertOnlyConnection:
    """Wrap a DB connection. SQL is guarded to INSERT/SELECT/CREATE IF NOT EXISTS."""

    def __init__(self, raw: Any, *, guard_fn: Any) -> None:
        self._raw = raw
        self._guard = guard_fn

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None) -> Any:
        guarded = self._guard(sql)
        if params is None:
            return self._raw.execute(guarded)
        return self._raw.execute(guarded, list(params))

    def close(self) -> None:
        close = getattr(self._raw, "close", None)
        if callable(close):
            close()


def fetch_mapped(result: Any, row_fn: Any) -> list[Any]:
    """Map fetchall/iterable rows. row_fn returning None is dropped."""

    if result is None:
        rows: Sequence[Any] = ()
    elif hasattr(result, "fetchall"):
        rows = result.fetchall()
    else:
        rows = list(result)
    out: list[Any] = []
    for row in rows or ():
        mapped = row_fn(row)
        if mapped is not None:
            out.append(mapped)
    return out


def dir_marked(path: Any, *, marker: str, suffix: str) -> bool:
    """True when ``marker`` exists and at least one ``suffix`` file is present."""

    dest = Path(path)
    return (dest / str(marker)).is_file() and bool(walk_suffix_files(dest, suffix))


def http_json(
    url: str,
    payload: Any,
    *,
    timeout: float,
    headers: Optional[Mapping[str, str]] = None,
    error_cls: Any = ValueError,
    redact_fn: Any = None,
    transport_fmt: str = "{error}",
    http_fmt: str = "HTTP {status}: {body}",
    json_fmt: str = "invalid JSON: {exc}",
    not_object: str = "non-object JSON payload",
) -> tuple[Optional[int], dict[str, Any], str]:
    """POST JSON. Returns (status, object, final_url). Never docker0."""

    def _raise(message: str) -> None:
        text = str(redact_fn(message) if redact_fn is not None else message)
        raise error_cls(text)

    status, raw, final_url, error = http_post(
        url,
        json.dumps(payload).encode("utf-8"),
        timeout=float(timeout),
        headers=headers,
    )
    if error:
        _raise(transport_fmt.format(error=error))
    if status is None or int(status) >= 400:
        _raise(http_fmt.format(status=status, body=head_chars(raw, 400)))
    try:
        data = json.loads(raw)
    except Exception as exc:
        _raise(json_fmt.format(exc=exc))
    if not isinstance(data, dict):
        _raise(not_object)
    return status, data, final_url


def hit_or_miss(
    present: bool,
    *,
    deny: bool = False,
    error_cls: Any = ValueError,
    deny_msg: str = "missing under deny",
    hit: Any = None,
    miss: Any = None,
) -> Any:
    """Return hit if present, raise when deny, otherwise miss."""

    if present:
        return hit
    if deny:
        raise error_cls(deny_msg)
    return miss


def unique_rows(items: Sequence[Any], *, key_fn: Any) -> list[Any]:
    """Keep first item per key_fn(item)."""

    seen: set[Any] = set()
    out: list[Any] = []
    for item in items or ():
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def append_line(text: str, line: str) -> str:
    return str(text or "").rstrip() + "\n" + str(line)


def exec_many(con: Any, statements: Sequence[Any]) -> None:
    """Run SQL strings or (sql, params) tuples on an open connection."""

    for item in statements or ():
        if isinstance(item, str):
            con.execute(item)
            continue
        sql = item[0]
        params = item[1] if len(item) > 1 else ()
        con.execute(str(sql), list(params) if params is not None else [])


def table_count(con: Any, table: str) -> int:
    name = str(table or "")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        return 0
    row = con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
    return int(row_cell(row, 0, default=0) or 0)


def ensure_digest(
    value: Any,
    *,
    data: Any = None,
    digest_fn: Any = None,
    error_cls: Any = ValueError,
    empty: str = "digest required",
    n: int = 64,
) -> str:
    """Keep a hex digest, or hash ``data`` with digest_fn. Else raise."""

    text = str(value or "")
    if is_hex_digest(text, n=n):
        return text
    if data is not None and digest_fn is not None:
        return str(digest_fn(data))
    raise error_cls(empty)


def path_safe(name: str, *, empty: str = "unnamed") -> str:
    text = str(name or "").replace("/", "_")
    return text or empty


def matching_nodes(
    nodes: Sequence[Mapping[str, Any]],
    query: str,
    *,
    id_key: str = "id",
    cap: int = 24,
) -> list[Mapping[str, Any]]:
    """Casefold substring hits on node[id_key]. Empty query → []."""

    needle = str(query or "").casefold()
    hits: list[Mapping[str, Any]] = []
    if not needle:
        return hits
    for node in nodes or ():
        nid = str(node.get(id_key) or "")
        if needle in nid.casefold():
            hits.append(node)
        if len(hits) >= max(0, int(cap)):
            break
    return hits


def query_first_engine(
    paths: Sequence[Any],
    table_sql: Mapping[str, str],
    params: Sequence[Any] = (),
    *,
    refuse_names: Sequence[str] = (),
    row_fn: Any = None,
    skip_empty: bool = True,
) -> tuple[list[Any], str]:
    """Open each DuckDB path read-only until a matching table yields rows."""

    last = "no_index"
    for path in paths or ():
        if path is None:
            continue
        dest = Path(path)
        if path_refused(dest, names=refuse_names) or not dest.is_file():
            continue
        con, note = open_readonly(dest, refuse_names=refuse_names)
        if con is None:
            if note == "unavailable":
                return [], "unavailable"
            continue
        try:
            sql = first_table_sql(engine_tables(con), table_sql)
            if not sql:
                last = "no_matching_table"
                continue
            rows = con.execute(str(sql), list(params)).fetchall()
            last = str(dest)
            hits: list[Any] = []
            for row in rows or ():
                mapped = row_fn(row) if row_fn is not None else row
                if mapped is not None:
                    hits.append(mapped)
            if hits or not skip_empty:
                return hits, last
        except Exception:
            last = "query_failed"
            continue
        finally:
            try:
                con.close()
            except Exception:
                pass
    return [], last


def split_csv(text: Any, *, sep: str = ",", cast: Any = None) -> list[Any]:
    """Split a comma list, strip, drop empties. Optional cast (int, Path, ...)."""

    parts = [item.strip() for item in str(text or "").split(sep) if item.strip()]
    if cast is None:
        return parts
    return [cast(item) for item in parts]


def first_csv(text: Any, *, sep: str = ",", default: str = "") -> str:
    """First CSV field, stripped. Empty text → default."""

    parts = str(text or "").split(sep)
    if not parts:
        return default
    return parts[0].strip() or default


def first_or_head(items: Sequence[Any], pred: Optional[Any] = None, *, default: Any = "") -> Any:
    """First item matching pred, else the head, else default. Not last."""

    rows = list(items or ())
    if pred is not None:
        for item in rows:
            if pred(item):
                return item
    return rows[0] if rows else default


def group_get(groups: dict[Any, Any], key: Any, *, factory: Optional[Any] = None) -> Any:
    """setdefault a group dict. factory() only runs when the key is missing."""

    group = groups.get(key)
    if group is None:
        group = factory() if factory is not None else {}
        groups[key] = group
    return group


def group_append(
    groups: dict[Any, Any],
    key: Any,
    item: Any,
    *,
    list_key: str = "names",
    factory: Optional[Any] = None,
) -> Any:
    """setdefault a group dict and append item to group[list_key]."""

    group = group_get(
        groups,
        key,
        factory=factory if factory is not None else (lambda: {list_key: []}),
    )
    group.setdefault(list_key, []).append(item)
    return group


def unique_append(seq: list[Any], item: Any) -> bool:
    """Append item if it is not already in seq."""

    if item in seq:
        return False
    seq.append(item)
    return True


def overlay_named_run_payload(
    result: Mapping[str, Any],
    *,
    digest: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """CI/live named-run overlay. Catalog extras stay in the consumer."""

    payload = dict(result)
    payload["ok"] = True
    payload["warmup_jsonl_sha256"] = digest
    if extra:
        payload.update(dict(extra))
    return payload


def coalesce_pair(
    primary: Any,
    secondary: Any,
    load_fn: Callable[[], tuple[Any, Any]],
) -> tuple[Any, Any]:
    """Keep provided pair members; load the rest. Used for generate/trace."""

    if primary is not None and secondary is not None:
        return primary, secondary
    loaded_a, loaded_b = load_fn()
    return (primary if primary is not None else loaded_a), (secondary if secondary is not None else loaded_b)


def fill_none(
    primary: Any,
    secondary: Any,
    load_fn: Callable[[], tuple[Any, Any]],
) -> tuple[Any, Any]:
    """If primary is None, load a pair and fill missing members. Secondary may stay unset."""

    if primary is not None:
        return primary, secondary
    loaded_a, loaded_b = load_fn()
    return loaded_a, secondary if secondary is not None else loaded_b


def apply_last(items: Sequence[Any], fn: Callable[[Any], Any]) -> Any:
    rows = list(items or ())
    if not rows:
        return None
    return fn(rows[-1])


def call_if(cond: Any, fn: Callable[[], Any], default: Any = None) -> Any:
    if cond:
        return fn()
    return default


def mark_skipped(obj: Any, reason: str) -> Any:
    obj.skipped = True
    obj.reason = str(reason)
    return obj


def with_defaults(kwargs: Mapping[str, Any], **defaults: Any) -> dict[str, Any]:
    out = dict(kwargs)
    for key, value in defaults.items():
        out.setdefault(key, value)
    return out


def starmap(fn: Callable[..., Any], rows: Sequence[Any]) -> list[Any]:
    return [fn(*row) for row in rows or ()]


def call_or(fn: Any, default: Any = None) -> Any:
    if fn is None:
        return default
    return fn()


def if_none(value: Any, default: Any = None, *, factory: Optional[Callable[[], Any]] = None) -> Any:
    if value is not None:
        return value
    if factory is not None:
        return factory()
    return default


def first_truthy(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value:
            return value
    return default


def attrs_dict(
    obj: Any,
    keys: Sequence[str],
    *,
    extra: Optional[Mapping[str, Any]] = None,
    transform: Optional[Mapping[str, Callable[[Any], Any]]] = None,
) -> dict[str, Any]:
    """Public attribute snapshot. Transform/extra stay injected."""

    casts = dict(transform or {})
    out: dict[str, Any] = {}
    for key in keys or ():
        value = getattr(obj, key)
        if key in casts:
            value = casts[key](value)
        out[key] = value
    if extra:
        out.update(dict(extra))
    return out


def call_then(
    fn: Callable[[Any], Any],
    first: Any,
    *,
    cond: bool,
    second: Any,
) -> Any:
    """Call fn(first), then fn(second) when cond. Used for optional repair."""

    result = fn(first)
    if cond:
        result = fn(second)
    return result


def reraise_as(
    fn: Callable[[], Any],
    from_types: tuple[type[BaseException], ...],
    error_cls: type[BaseException],
    *,
    missing: str = "",
    fmt: str = "",
    skip_types: tuple[type[BaseException], ...] = (),
) -> Any:
    """Reraise typed failures with a consumer error class."""

    try:
        return fn()
    except skip_types:
        raise
    except FileNotFoundError as exc:
        if FileNotFoundError in from_types:
            raise error_cls(missing or str(exc)) from exc
        raise
    except from_types as exc:
        raise error_cls((fmt or "{exc}").format(exc=exc) if fmt else str(exc)) from exc


def usage_line(
    cls: Any,
    *,
    kind: str,
    input_tokens: int,
    output_tokens: int,
    usd: Any,
    call_index: int,
    fixture: bool,
    model: str,
    skipped: bool,
    reason: str,
) -> Any:
    """Usage line constructor. USD stays on the consumer class."""

    return cls(
        kind=kind,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        usd=usd,
        call_index=int(call_index),
        fixture=bool(fixture),
        model=model,
        skipped=bool(skipped),
        reason=reason,
    )


def overlay_if_status(
    payload: Mapping[str, Any],
    status: str,
    extra: Mapping[str, Any],
) -> dict[str, Any]:
    out = dict(payload)
    if out.get("status") == status:
        out.update(dict(extra))
    return out


def lock_view(
    cls: Any,
    *,
    path: str,
    exists: bool,
    held: bool,
    pid: Any = None,
    method: str = "",
    error: str = "",
) -> Any:
    """Lock inspection constructor. Never LOCK_EX."""

    return cls(path=path, exists=exists, held=held, pid=pid, method=method, error=error)


def detail_with_file(
    exc: BaseException,
    path: Any,
    *,
    read_fn: Callable[..., str],
    max_chars: int = 400,
) -> str:
    """Append a file head onto an exception message when the file exists."""

    target = Path(path)
    if not target.is_file():
        return str(exc)
    head = read_fn(target, max_chars=max_chars)
    if not head:
        return str(exc)
    return f"{exc}; {target.name}={head!r}"


def pack_captured_generate(
    result: Any,
    captured: Mapping[str, Any],
    fail_closed: Mapping[str, Any],
    *,
    asdict_fn: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    """Self-check view of a client generate call. Never LOCK_EX."""

    kwargs = dict(captured.get("kwargs") or {})
    identity = getattr(result, "identity", None)
    return {
        "skipped": bool(getattr(result, "skipped", False)),
        "text": getattr(result, "text", ""),
        "identity": dict(asdict_fn(identity) if identity is not None else {}),
        "call_kwargs": {key: kwargs.get(key) for key in fail_closed},
        "call_kwargs_match": all(
            kwargs.get(key) == value for key, value in dict(fail_closed).items()
        ),
        "autostart_during_generate": captured.get("autostart"),
        "lock_ex_taken_by_client": False,
    }


def result_from_ledger(
    cls: Any,
    ledger: Any,
    *,
    skipped: bool,
    reason: str,
    mode: str,
    name: Any = None,
    used_fixture: bool = False,
    official_track2: bool = False,
    extra: Optional[Mapping[str, Any]] = None,
    remaining_default: Any = 0,
) -> Any:
    """Build a named-run result from a ledger. USD field names stay on the class."""

    payload = {
        "skipped": skipped,
        "reason": reason,
        "mode": mode,
        "official_track2": official_track2,
        "name": name,
        "used_fixture": used_fixture,
        "grok_calls": getattr(ledger, "grok_calls", 0) if ledger is not None else 0,
        "jev_calls": getattr(ledger, "jev_calls", 0) if ledger is not None else 0,
        "spent_usd": getattr(ledger, "spent_usd", 0) if ledger is not None else 0,
        "remaining_usd": (
            getattr(ledger, "remaining_usd", remaining_default) if ledger is not None else remaining_default
        ),
        "hard_stopped": bool(getattr(ledger, "hard_stopped", False)) if ledger is not None else False,
        "ledger": ledger.as_dict() if ledger is not None and hasattr(ledger, "as_dict") else None,
        "contaminates_track2": False,
        "is_default_winning_path": False,
    }
    payload.update(dict(extra or {}))
    return cls(**payload)


def overlay_skipped(
    result: Any,
    *,
    digest: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Skip overlay for a named run. Ledger fields stay on the result."""

    payload = result.as_dict() if hasattr(result, "as_dict") else dict(result)
    return overlay_named_run_payload(payload, digest=digest, extra=extra)


def all_rows(rows: Sequence[Any], pred: Callable[[Any], bool]) -> bool:
    return all(pred(item) for item in rows or ())


def any_row(rows: Sequence[Any], pred: Callable[[Any], bool]) -> bool:
    return any(pred(item) for item in rows or ())


def all_where(
    rows: Sequence[Any],
    pred: Callable[[Any], bool],
    check: Optional[Callable[[Any], bool]] = None,
) -> bool:
    selected = [item for item in rows or () if pred(item)]
    fn = check or (lambda _item: True)
    return all(fn(item) for item in selected)


def collect_where(
    rows: Sequence[Any],
    pred: Callable[[Any], bool],
    getter: Callable[[Any], Any],
) -> list[Any]:
    return [getter(item) for item in rows or () if pred(item)]


def field_eq_all(rows: Sequence[Mapping[str, Any]], key: str, value: Any) -> bool:
    return all(item.get(key) == value for item in rows or ())


def kwargs_match_all(
    calls: Sequence[Mapping[str, Any]],
    expected: Mapping[str, Any],
    *,
    kwargs_key: str = "kwargs",
) -> bool:
    return bool(calls) and all(
        all(dict(call.get(kwargs_key) or {}).get(key) == value for key, value in dict(expected).items())
        for call in calls
    )


def first_line_value(text: str, *, prefix: str, default: str = "") -> str:
    """Value after a line prefix such as ``Source:``. Empty prefix is not stripped."""

    for line in str(text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return default


def catch_error(fn: Callable[[], Any], error_cls: Any) -> tuple[bool, str]:
    """(raised, message). Used for fail-closed probes that keep the error text."""

    try:
        fn()
    except error_cls as exc:
        return True, str(exc)
    return False, ""


def call_caught(
    fn: Callable[[], Any],
    error_cls: Any = Exception,
    default: Any = None,
) -> tuple[bool, Any, Optional[BaseException]]:
    """(ok, result, exc). Typed failures return (False, default, exc)."""

    try:
        return True, fn(), None
    except error_cls as exc:
        return False, default, exc


def set_if(mapping: dict[str, Any], cond: Any, key: str, value: Any) -> dict[str, Any]:
    """Set mapping[key]=value when cond. Returns mapping."""

    if cond:
        mapping[str(key)] = value
    return mapping


def first_call(*pairs: tuple[Any, Callable[[], Any]]) -> Any:
    """Return the first fn() whose condition is true. None if none match."""

    for cond, fn in pairs:
        if cond:
            return fn()
    return None


def keyed_map(
    items: Sequence[Any],
    *,
    key_fn: Callable[[Any], Any],
    val_fn: Callable[[Any], Any],
    pred: Optional[Callable[[Any], Any]] = None,
) -> dict[Any, Any]:
    """Build a dict from items. pred/key_fn/val_fn stay injected."""

    out: dict[Any, Any] = {}
    for item in items or ():
        if pred is not None and not pred(item):
            continue
        out[key_fn(item)] = val_fn(item)
    return out


def take_keys(mapping: Mapping[str, Any], *keys: str) -> tuple[Any, ...]:
    """Unpack mapping[key] for each key. Missing keys raise."""

    return tuple(mapping[key] for key in keys)


def either(cond: Any, yes_fn: Callable[[], Any], no_fn: Callable[[], Any]) -> Any:
    """Call yes_fn when cond, else no_fn. Both stay lazy."""

    return yes_fn() if cond else no_fn()


def replace_if(cond: Any, replacement: Any, current: Any) -> Any:
    """Return replacement when cond, else current."""

    return replacement if cond else current


def require_authorized(
    ledger: Any,
    kind: str,
    estimated_in: int,
    estimated_out: int,
    *,
    fixture: bool = False,
    model: str = "",
    error_cls: Any = RuntimeError,
    fmt: str = "{reason}",
) -> tuple[Any, str, Any]:
    """Authorize spend or record a skip and raise. USD stays on the ledger."""

    allowed, reason, cost = ledger.authorize(kind, int(estimated_in), int(estimated_out))
    if allowed:
        return allowed, reason, cost
    ledger.record(
        kind,
        input_tokens=int(estimated_in),
        output_tokens=int(estimated_out),
        fixture=fixture,
        model=model,
    )
    raise error_cls(fmt.format(reason=reason)) from None


def pipe(value: Any, *fns: Callable[[Any], Any]) -> Any:
    """Thread value through fns. Implementations stay injected."""

    for fn in fns:
        value = fn(value)
    return value


def raise_if(cond: Any, error_cls: Any, msg: str) -> None:
    """Raise error_cls(msg) when cond."""

    if cond:
        raise error_cls(msg)


def require_recorded(
    line: Any,
    error_cls: Any,
    fmt: str = "spend refused after call: {reason}",
) -> Any:
    """Raise when a usage line was skipped after the call."""

    if getattr(line, "skipped", False):
        raise error_cls(fmt.format(reason=getattr(line, "reason", "")))
    return line


def assign_if(
    mapping: dict[str, Any],
    key: str,
    cond: Any,
    value: Any,
) -> dict[str, Any]:
    """Set mapping[key] when cond. value may be a thunk."""

    if cond:
        mapping[str(key)] = value() if callable(value) else value
    return mapping


def ranked_pairs(
    mapping: Optional[Mapping[str, Any]] = None,
    *,
    reverse: bool = True,
) -> list[tuple[Any, Any]]:
    """Sort mapping items by value."""

    return sorted(dict(mapping or {}).items(), key=lambda item: item[1], reverse=bool(reverse))


def kind_startswith(prefix: str, *, key: str = "kind") -> Callable[[Any], bool]:
    """Predicate: str(item[key]).startswith(prefix)."""

    def pred(item: Any) -> bool:
        row = item if isinstance(item, Mapping) else {}
        return str(row.get(key) or "").startswith(str(prefix))

    return pred


def attr_or(obj: Any, name: str, default: Any = None) -> Any:
    """getattr(obj, name) unless obj is None."""

    return default if obj is None else getattr(obj, name)


def get_str(mapping: Optional[Mapping[str, Any]], key: str, default: str = "") -> str:
    """str(mapping[key] or default). None mapping is default."""

    return str((mapping or {}).get(key) or default)


def beam_shape(
    mode: str,
    beam: int,
    *,
    greedy: str = "greedy",
    sample_cap: int,
) -> tuple[int, int]:
    """(beam_n, n_samples). Greedy is width 1."""

    width = 1 if str(mode) == str(greedy) else max(1, int(beam))
    samples = 1 if width <= 1 else min(width, int(sample_cap))
    return width, samples


def ignore_each(*fns: Callable[[], Any], error_cls: Any = Exception) -> None:
    """Swallow typed errors from each fn. Used for optional overlays."""

    for fn in fns:
        ignore_error(fn, error_cls)


def extend_if(
    dest: list[Any],
    extra: Any,
    *,
    cond: Any,
    key_fn: Any,
) -> list[Any]:
    """unique_extend when cond. extra may be a thunk."""

    if not cond:
        return dest
    rows = extra() if callable(extra) else extra
    return unique_extend(dest, rows, key_fn=key_fn)


def record_usage_line(
    obj: Any,
    cls: Any,
    *,
    allowed: bool,
    reason: str,
    cost: Any,
    usd_fn: Callable[[Any], Any],
    bump_fn: Optional[Callable[[], Any]] = None,
    refresh_fn: Optional[Callable[[], Any]] = None,
    **line_kwargs: Any,
) -> Any:
    """Append a skip or recorded usage line. USD conversion stays injected."""

    if not allowed:
        line = usage_line(cls, usd=usd_fn(cost), skipped=True, reason=reason, **line_kwargs)
        obj.lines.append(line)
        obj.skipped = True
        obj.reason = reason
        return line
    if bump_fn is not None:
        bump_fn()
    if refresh_fn is not None:
        refresh_fn()
    line = usage_line(cls, usd=usd_fn(cost), skipped=False, reason="recorded", **line_kwargs)
    obj.lines.append(line)
    return line


def ignore_error(
    fn: Callable[[], Any],
    error_cls: Any = Exception,
    default: Any = None,
) -> Any:
    """Call fn and swallow typed errors. Used for optional board/sidecar overlays."""

    try:
        return fn()
    except error_cls:
        return default


def bump_named(
    obj: Any,
    key: str,
    mapping: Mapping[str, str],
    *,
    error_cls: type[BaseException] = ValueError,
    fmt: str = "unknown spend kind {kind!r}",
) -> None:
    """Increment a named counter attribute. Unknown keys fail closed."""

    attr = mapping.get(key)
    if not attr:
        raise error_cls(fmt.format(kind=key))
    setattr(obj, attr, int(getattr(obj, attr, 0)) + 1)


def overlay_skip(
    result_fn: Callable[..., Any],
    *,
    digest: str,
    extra: Optional[Mapping[str, Any]] = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Build a skip result and overlay it. Catalog extras stay in the consumer."""

    return overlay_skipped(result_fn(**kwargs), digest=digest, extra=extra)


def map_collect(
    items: Sequence[Any],
    fn: Callable[[Any], Any],
    *,
    after_fn: Optional[Callable[[Any], Sequence[Any]]] = None,
) -> tuple[list[Any], list[Any]]:
    """Map fn over items, optionally flattening after_fn(result) into a second list."""

    results: list[Any] = []
    extra: list[Any] = []
    for item in items or ():
        result = fn(item)
        results.append(result)
        if after_fn is not None:
            extra.extend(list(after_fn(result) or ()))
    return results, extra


def finalize_ok(report: Mapping[str, Any], *flags: Any) -> dict[str, Any]:
    """Set report['ok'] from injected flags. Catalog predicates stay in the consumer."""

    out = dict(report)
    out["ok"] = bool(all(flags))
    return out


def relative_or_str(path: Any, root: Any) -> str:
    """Path relative to root, else str(path)."""

    raw = Path(path)
    try:
        return str(raw.relative_to(root))
    except ValueError:
        return str(raw)


def any_contains(items: Sequence[Any], needle: str) -> bool:
    return any(str(needle) in str(item) for item in items or ())


def none_stripped_startswith(items: Sequence[Any], prefix: str) -> bool:
    return not any(str(item).strip().startswith(prefix) for item in items or ())


def rank_named_rows(
    names: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    rank_fn: Callable[[Mapping[str, Any]], Any],
    *,
    miss: str = "unknown warm-up problem",
) -> list[Any]:
    """Lookup each name and rank. Missing names stay fail-closed rows."""

    from jevops.outer import lookup_named

    rows: list[Any] = []
    for name in names or ():
        record = lookup_named(records, name)
        if record is None:
            rows.append({"name": name, "error": miss, "arena_score": None})
            continue
        rows.append(rank_fn(record))
    return rows


def pack_live_rank(
    *,
    schema: str,
    digest: str,
    canaries: Sequence[Any],
    wall_ms: float,
    extra: Optional[Mapping[str, Any]] = None,
    redact_fn: Optional[Callable[[Mapping[str, Any]], Any]] = None,
) -> dict[str, Any]:
    """Live TypeSafe rank overlay. Catalog fields stay in extra."""

    from jevops.outer import utc_stamp

    payload: dict[str, Any] = {
        "schema": schema,
        "observed_at": utc_stamp(),
        "live": True,
        "warmup_jsonl_sha256": digest,
        "jev_generated_lean": False,
        "typesafe_key_in_receipt": False,
        "lock_ex": False,
        "llama_server_started": False,
        "official_track2": False,
        "arena_score": None,
        "wall_ms": wall_ms,
        "canaries": list(canaries or ()),
    }
    if extra:
        payload.update(dict(extra))
    if redact_fn is not None:
        return redact_fn(payload)
    return payload


def closed_on_error(fn: Callable[[], Any], error_cls: Any) -> bool:
    """True when fn raises error_cls. Used for fail-closed probes."""

    try:
        fn()
    except error_cls:
        return True
    return False


def persist_named_rows(
    rows: Sequence[Any],
    dest: Any,
    persist: Any,
    write_fn: Callable[[Sequence[Any], Any], Sequence[str]],
) -> tuple[list[str], list[str]]:
    """Write rows to dest, then optionally to persist."""

    written = list(write_fn(rows, dest) or ())
    persisted = list(write_fn(rows, persist) or ()) if persist is not None else []
    return written, persisted


def plant_named_tags(root: Any, tags: Sequence[str], plant_fn: Callable[[Any, str], Any]) -> Any:
    """Plant one fake toolchain per tag under root."""

    for tag in tags or ():
        plant_fn(root, str(tag))
    return root


def clone_restore(
    record: Mapping[str, Any],
    state_root: Any,
    *,
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[[Mapping[str, Any]], Any],
    read_fn: Optional[Callable[[Any], bytes]] = None,
    url_key: str = "url",
) -> tuple[Any, Path, bytes]:
    """Clone a record URL, then read dest bytes. Does not compile Lean."""

    clone = clone_fn(str(record.get(url_key) or ""), state_root)
    dest = Path(clone) / relpath_fn(record)
    restore = (read_fn or read_bytes_if)(dest)
    return clone, dest, restore


def load_named_pack(
    load_fn: Callable[..., Any],
    name: str,
    *,
    error_cls: Any = RuntimeError,
    miss: str = "",
    extra: Any = None,
) -> tuple[Any, list[Any], str]:
    """Load (raw, digest, records) then lookup ``name``. raw is discarded."""

    packed = load_fn() if extra is None else load_fn(extra)
    _raw, digest, records = packed
    del _raw
    record = lookup_named(
        records,
        name,
        error_cls=error_cls,
        miss=miss or f"unknown name: {name}",
    )
    return record, list(records), str(digest)


def load_and_clone(
    load_fn: Callable[..., Any],
    name: str,
    state_root: Any,
    *,
    clone_fn: Callable[..., Any],
    relpath_fn: Callable[[Mapping[str, Any]], Any],
    error_cls: Any = RuntimeError,
    miss: str = "",
    extra: Any = None,
    read_fn: Optional[Callable[[Any], bytes]] = None,
    url_key: str = "url",
) -> tuple[Any, list[Any], str, Any, Path, bytes]:
    """load_named_pack then clone_restore. Does not compile Lean."""

    record, records, digest = load_named_pack(
        load_fn, name, error_cls=error_cls, miss=miss, extra=extra
    )
    clone, dest, restore = clone_restore(
        record,
        state_root,
        clone_fn=clone_fn,
        relpath_fn=relpath_fn,
        read_fn=read_fn,
        url_key=url_key,
    )
    return record, records, digest, clone, dest, restore


def tagged_mapping(tag: str, obj: Any, *, key: str = "call") -> dict[str, Any]:
    """Prefix a mapping with a tag. Prefers as_dict()."""

    payload = obj.as_dict() if hasattr(obj, "as_dict") else dict(obj)
    return {str(key): tag, **payload}


def closed_skip_extra(
    record: Optional[Mapping[str, Any]] = None,
    extra: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> dict[str, Any]:
    """Fail-closed skip extras. Catalog flags stay in fields."""

    out: dict[str, Any] = {"contaminates_track2": False}
    if record is not None:
        out["source"] = record.get("source")
    out.update(fields)
    if extra:
        out.update(dict(extra))
    return out


def named_shots(
    records: Sequence[Mapping[str, Any]],
    names: Sequence[str],
    *,
    skip_name: str = "",
    example_fn: Callable[[Mapping[str, Any]], Any],
) -> list[Any]:
    """Lookup named records and map example_fn. Missing names are skipped."""

    shots: list[Any] = []
    skip = str(skip_name or "")
    for shot_name in names or ():
        if str(shot_name) == skip:
            continue
        rec = lookup_named(records, str(shot_name))
        if rec is not None:
            shots.append(example_fn(rec))
    return shots


def inspect_only(
    name: str,
    *,
    markers: Sequence[str],
    needles: Sequence[str] = (),
    resolve_fn: Optional[Callable[[str], Any]] = None,
    read_fn: Optional[Callable[..., str]] = None,
    max_chars: int = 8000,
) -> bool:
    """True when the name or file head contains inspect-only markers. No Lean."""

    if contains_any(name, markers):
        return True
    if resolve_fn is None or not needles:
        return False
    path = resolve_fn(name)
    if path is None:
        return False
    target = Path(path)
    if not target.is_file():
        return False
    try:
        head = read_fn(target) if read_fn is not None else read_text(
            target, errors="ignore", max_chars=max_chars
        )
    except OSError:
        return False
    return contains_any(head, needles)


def coalesce_chat_text(
    chat_out: str,
    ran: Mapping[str, Any],
    parse_fn: Callable[[str], Mapping[str, Any]],
) -> str:
    """Prefer parsed payload text unless the process timed out."""

    if ran.get("timeout"):
        return str(chat_out or "")
    payload = dict(parse_fn(str(chat_out or "")) or {})
    if payload.get("text"):
        return str(payload.get("text") or chat_out)
    return str(chat_out or "")


def generate_text_and_usage(
    raw: Optional[Mapping[str, Any]],
    *,
    fallback_in: int = 200,
) -> tuple[str, int, int]:
    """Extract text plus input/output tokens from a chat/generate payload."""

    payload = dict(raw or {})
    text = str(payload.get("text") or "")
    if not text:
        text, _texts, usage = chat_choice_texts(payload)
    else:
        usage = payload.get("usage") if isinstance(payload.get("usage"), Mapping) else {}
    usage = dict(usage or {})
    inn = int(
        payload.get("input_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or fallback_in
    )
    out = int(
        payload.get("output_tokens")
        or usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )
    return text, inn, out


def write_cli_run_artifacts(
    workspace: Any,
    *,
    prompt: str,
    cmd: Sequence[Any],
    ran: Mapping[str, Any],
    write_text_fn: Callable[..., Any],
    write_json_fn: Callable[..., Any],
) -> tuple[str, str, str]:
    """Persist prompt/argv/stdout/stderr/returncode under a workspace. Chat is not Lean."""

    root = Path(workspace)
    write_text_fn(root / "PROMPT.txt", str(prompt))
    write_json_fn(root / "grok.argv.json", list(cmd or ()))
    chat_out = str(ran.get("stdout") or "")
    stderr = str(ran.get("stderr") or "")
    code = "timeout" if ran.get("timeout") else str(ran.get("exit_code"))
    write_text_fn(root / "grok.stdout", chat_out)
    write_text_fn(root / "grok.stderr", stderr)
    write_text_fn(root / "grok.returncode", code)
    return chat_out, stderr, code


def count_where(items: Sequence[Any], pred: Any) -> int:
    return sum(1 for item in items or () if pred(item))


def where(items: Sequence[Any], pred: Any) -> list[Any]:
    return [item for item in items or () if pred(item)]


def pack_unscored(**fields: Any) -> dict[str, Any]:
    """Report overlay with arena_score/score closed. ``ok`` stays caller-owned."""

    out = dict(fields)
    out.setdefault("arena_score", None)
    out.setdefault("score", None)
    return out


def pack_ledger_receipt(
    ledger: Any,
    *,
    schema: str,
    protocol: str,
    pr: str,
    lrah: str,
    track: str,
) -> dict[str, Any]:
    """Track-1-style ledger receipt. Official Track 2 stays false."""

    payload = ledger.as_dict() if hasattr(ledger, "as_dict") else dict(ledger)
    return {
        "schema": schema,
        "protocol": protocol,
        "pr": pr,
        "lrah": lrah,
        "track": track,
        "official_track2": False,
        "contaminates_track2": False,
        "is_default_winning_path": False,
        "arena_score": None,
        "ledger": payload,
        "api_key_present_in_record": False,
    }


def false_when(value: Any, *preds: Any) -> bool:
    """Keep value unless any predicate is true, then False."""

    if any(bool(item) for item in preds):
        return False
    return bool(value)


def quoted_group(
    text: str,
    pattern: str,
    *,
    error_cls: type[BaseException] = ValueError,
    miss: str = "",
    empty: str = "",
    flags: int = re.S,
) -> tuple[str, ...]:
    """Parse quoted names from the first capturing group of ``pattern``."""

    match = re.search(pattern, str(text or ""), flags)
    if match is None:
        raise error_cls(miss or "assigned tuple missing")
    names = quoted_strings(match.group(1))
    if not names:
        raise error_cls(empty or "assigned tuple parsed empty")
    return names


def require_file_bytes(
    path: Any,
    *,
    error_cls: type[BaseException] = FileNotFoundError,
    miss: str = "",
) -> bytes:
    target = Path(path)
    if not target.is_file():
        raise error_cls(miss.format(path=target) if miss else f"missing {target}")
    return target.read_bytes()


def map_hits(
    rows: Sequence[Any],
    hit_fn: Callable[[Any], Any],
    *,
    skip_empty: bool = True,
) -> list[Any]:
    out: list[Any] = []
    for row in rows or ():
        hit = hit_fn(row)
        if skip_empty and not hit:
            continue
        out.append(hit)
    return out
