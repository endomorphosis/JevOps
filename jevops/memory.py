#!/usr/bin/env python3
"""NCA working memory: successes, failures, blacklist, research, installed folds.

Does not write Lean. Paths and ephemeral-kind rules are injected.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

EPHEMERAL_PREFIXES = ("pca_", "sweep_rand_")
EPHEMERAL_MARKERS = ("_MCA_",)
ALLOWED_KEEP = frozenset(
    {
        "intro",
        "intros",
        "constructor",
        "grind",
        "induction",
        "case",
        "exact",
        "use",
        "have",
        "simp_all",
    }
)
_STEM_OK = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")


def empty_memory() -> dict[str, Any]:
    return {
        "successes": [],
        "failures": [],
        "blacklist": [],
        "research": [],
        "expanded": [],
        "skills": [],
        "skill_params": {},
        "observations": {},
        "subloop_returns": [],
        "nca": {},
        "tape": {},
    }


def is_ephemeral_kind(
    kind: str,
    *,
    prefixes: Sequence[str] = EPHEMERAL_PREFIXES,
    markers: Sequence[str] = EPHEMERAL_MARKERS,
) -> bool:
    text = str(kind)
    return text.startswith(tuple(prefixes)) or any(m in text for m in markers)


def blacklist_key(name: str, kind: str, tactics: str = "") -> str:
    if is_ephemeral_kind(kind):
        from jevops.outer import digest_prefix

        digest = digest_prefix((tactics or "").strip("\n"))
        text = str(kind)
        if "_MCA_" in text:
            family = text.rsplit("_MCA_", 1)[0]
        else:
            family = text.split("_d")[0]
        return f"{name}::{family}::{digest}"
    return f"{name}::{kind}"


def scrub_blacklist(memory: dict[str, Any], *, patched_unban: Sequence[str] = ()) -> dict[str, Any]:
    banned = set(patched_unban or ())
    kept: list[str] = []
    for key in memory.get("blacklist") or []:
        parts = str(key).split("::")
        if len(parts) < 2:
            continue
        kind = parts[1]
        if kind in banned or str(key) in banned:
            continue
        if is_ephemeral_kind(kind) and len(parts) < 3:
            continue
        kept.append(str(key))
    memory["blacklist"] = kept
    return memory


def load_memory(
    path: Path,
    *,
    rehydrate_path: Optional[Path] = None,
    patched_unban: Sequence[str] = (),
) -> dict[str, Any]:
    if not path.is_file():
        data = empty_memory()
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = {}
        data = empty_memory()
        if isinstance(loaded, dict):
            data.update(loaded)
    for key, default in empty_memory().items():
        data.setdefault(key, list(default) if isinstance(default, list) else dict(default) if isinstance(default, dict) else default)
    scrub_blacklist(data, patched_unban=patched_unban)
    if rehydrate_path is not None:
        rehydrate_from_gaps(data, path=rehydrate_path)
    return data


def save_memory(
    memory: Mapping[str, Any], path: Path, *, patched_unban: Sequence[str] = ()
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = scrub_blacklist(dict(memory), patched_unban=patched_unban)
    payload = {
        "successes": list(cleaned.get("successes") or []),
        "failures": list(cleaned.get("failures") or []),
        "blacklist": list(cleaned.get("blacklist") or []),
        "research": list(cleaned.get("research") or []),
        "expanded": list(cleaned.get("expanded") or []),
        "skills": list(cleaned.get("skills") or []),
        "skill_params": dict(cleaned.get("skill_params") or {}),
        "observations": dict(cleaned.get("observations") or {}),
        "subloop_returns": list(cleaned.get("subloop_returns") or [])[-32:],
        "nca": dict(cleaned.get("nca") or {}),
        "tape": dict(cleaned.get("tape") or {}),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def rehydrate_from_gaps(memory: dict[str, Any], *, path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"ok": False, "reason": "no_skill_analysis", "n_blacklist": 0, "n_research": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"ok": False, "reason": "bad_json", "n_blacklist": 0, "n_research": 0}
    gaps = list(payload.get("gaps") or [])
    empty = not (memory.get("blacklist") or memory.get("failures") or memory.get("research"))
    if not empty:
        return {
            "ok": True,
            "reason": "already_populated",
            "n_blacklist": len(memory.get("blacklist") or []),
            "n_research": len(memory.get("research") or []),
        }
    blacklist = memory.setdefault("blacklist", [])
    research = memory.setdefault("research", [])
    n_bl = 0
    n_rs = 0
    for gap in gaps:
        name = str(gap.get("name") or "")
        if not name:
            continue
        for stem in gap.get("failed_stems") or []:
            kind = str(stem)
            if not kind.startswith("port_"):
                kind = f"port_{kind}"
            key = f"{name}::{kind}"
            if key not in blacklist:
                blacklist.append(key)
                n_bl += 1
        help_scores = {
            str(row.get("residual")): float(row.get("help") or 0.0)
            for row in (gap.get("top_help") or [])
            if row.get("residual")
        }
        unsafe = {
            str(row.get("residual")): float(row.get("unsafe") or 0.0)
            for row in (gap.get("top_help") or [])
            if row.get("residual")
        }
        if help_scores or unsafe:
            research.append({"name": name, "help": help_scores, "unsafe": unsafe})
            n_rs += 1
    scrub_blacklist(memory)
    return {"ok": True, "reason": "rehydrated", "n_blacklist": n_bl, "n_research": n_rs}


def keep_named_tail(rows: list[Any], name: str, *, keep: int = 8) -> list[Any]:
    others = [row for row in rows if (row or {}).get("name") != name]
    mine = [row for row in rows if (row or {}).get("name") == name][-int(keep) :]
    return others + mine


def record_named_notes(
    memory: dict[str, Any],
    bucket: str,
    name: str,
    notes: Sequence[Mapping[str, Any]],
    *,
    keep: int = 8,
) -> None:
    memory.setdefault(bucket, []).append({"name": name, "notes": list(notes)})
    memory[bucket] = keep_named_tail(list(memory.get(bucket) or []), name, keep=keep)


def remember_research(
    memory: dict[str, Any],
    *,
    name: str,
    residuals: Mapping[str, Any],
    unsafe: Mapping[str, Any],
    help_scores: Mapping[str, Any],
    skill: str,
    compose: str,
) -> None:
    memory.setdefault("research", []).append(
        {
            "name": name,
            "residuals": dict(residuals or {}),
            "unsafe": {str(k): float(v) for k, v in (unsafe or {}).items()},
            "help": {str(k): float(v) for k, v in (help_scores or {}).items()},
            "skill": skill,
            "compose": compose,
        }
    )
    memory["research"] = keep_named_tail(list(memory.get("research") or []), name, keep=8)


def remember_intent(
    memory: dict[str, Any],
    *,
    name: str,
    tactics: str,
    intent: Mapping[str, Any],
    residual_fn: Optional[Any] = None,
) -> None:
    """Store AutoResearch residuals/unsafe/help from an intent payload. No Lean."""

    residuals = residual_fn(tactics) if residual_fn is not None else {}
    remember_research(
        memory,
        name=name,
        residuals=residuals or {},
        unsafe=intent.get("residual_unsafe") or {},
        help_scores=intent.get("residual_help") or {},
        skill=str(intent.get("skill") or "keep"),
        compose=str(intent.get("compose") or "single"),
    )


def named_success_kinds(memory: Mapping[str, Any], name: str, *, limit: int = 8) -> list[str]:
    return sorted(
        {
            str(item.get("kind"))
            for item in memory.get("successes") or []
            if item.get("name") == name
        }
    )[: int(limit)]


def prior_research(memory: Mapping[str, Any], name: str) -> dict[str, Any]:
    rows = [row for row in memory.get("research") or [] if row.get("name") == name]
    return dict(rows[-1]) if rows else {}


def failed_skill_stems(memory: Mapping[str, Any], name: str) -> set[str]:
    stems: set[str] = set()
    prefix = f"{name}::"
    for key in memory.get("blacklist") or []:
        if not str(key).startswith(prefix):
            continue
        kind = str(key).split("::")[1]
        if kind.startswith("port_"):
            stems.add(kind[len("port_") :])
            stems.add(kind)
    for row in memory.get("failures") or []:
        if row.get("name") != name:
            continue
        kind = str(row.get("kind") or "")
        if kind.startswith("port_"):
            stems.add(kind[len("port_") :].split("_pipeline")[0])
            stems.add(kind)
    return stems


def remember_success(
    memory: dict[str, Any],
    *,
    name: str,
    kind: str,
    family: str,
    from_tokens: int,
    to_tokens: int,
) -> None:
    memory.setdefault("successes", []).append(
        {
            "name": name,
            "kind": kind,
            "family": family,
            "from_tokens": int(from_tokens),
            "to_tokens": int(to_tokens),
        }
    )


def remember_failure(
    memory: dict[str, Any],
    *,
    name: str,
    kind: str,
    error_class: str = "",
    unknown: Optional[Sequence[str]] = None,
    tactics: str = "",
) -> None:
    key = blacklist_key(name, kind, tactics)
    memory.setdefault("failures", []).append(
        {
            "name": name,
            "kind": kind,
            "error_class": error_class,
            "unknown": list(unknown or []),
            "key": key,
        }
    )
    blacklist = memory.setdefault("blacklist", [])
    if key not in blacklist:
        blacklist.append(key)
    if tactics:
        from jevops.outer import digest_prefix

        digest = digest_prefix(tactics.strip("\n"))
        body_key = f"{name}::body::{digest}"
        if body_key not in blacklist:
            blacklist.append(body_key)


def is_blacklisted(memory: Mapping[str, Any], name: str, kind: str, tactics: str = "") -> bool:
    keys = set(memory.get("blacklist") or [])
    if blacklist_key(name, kind, tactics) in keys:
        return True
    if not is_ephemeral_kind(kind) and f"{name}::{kind}" in keys:
        return True
    if tactics:
        from jevops.outer import digest_prefix

        digest = digest_prefix(tactics.strip("\n"))
        if any(str(key).endswith(f"::{digest}") for key in keys):
            return True
    return False


def install_memory_skill(
    memory: dict[str, Any],
    spec: Mapping[str, Any],
    *,
    allowed_keep: Optional[set[str]] = None,
) -> dict[str, Any]:
    keep_ok = allowed_keep if allowed_keep is not None else ALLOWED_KEEP
    stem = str(spec.get("stem") or "").strip()
    old = str(spec.get("old") or "")
    new = str(spec.get("new") or "")
    keep = [str(item) for item in (spec.get("keep") or []) if str(item) in keep_ok]
    if not _STEM_OK.match(stem):
        return {"ok": False, "reason": "bad_stem"}
    if not old or old == new:
        return {"ok": False, "reason": "empty_fold"}
    if len(old) > 400 or len(new) > 400:
        return {"ok": False, "reason": "fold_too_long"}
    for word in keep:
        if word in old and word not in new:
            return {"ok": False, "reason": f"drops_{word}"}
    row = {
        "stem": stem,
        "old": old,
        "new": new,
        "keep": keep,
        "family": str(spec.get("family") or "search_space"),
        "count": max(1, int(spec.get("count") or 1)),
    }
    skills = memory.setdefault("skills", [])
    skills[:] = [item for item in skills if str(item.get("stem")) != stem]
    skills.append(row)
    return {"ok": True, "skill": row}


def propose_skill_from_research(
    memory: Mapping[str, Any],
    name: str,
    *,
    keep_mints: Optional[Mapping[str, Sequence[str]]] = None,
    unsafe_cut: float = 0.45,
) -> dict[str, Any]:
    prior = prior_research(memory, name)
    help_scores = dict(prior.get("help") or {})
    unsafe = dict(prior.get("unsafe") or {})
    best = None
    best_help = -1.0
    for residual, help in help_scores.items():
        u = float(unsafe.get(residual) or 0.0)
        h = float(help or 0.0)
        if u < unsafe_cut and h > best_help:
            best = residual
            best_help = h
    if best is not None:
        return {
            "residual": best,
            "help": best_help,
            "unsafe": float(unsafe.get(best) or 0.0),
            "keep_structure": False,
        }
    ranked = sorted(help_scores, key=lambda key: float(help_scores.get(key) or 0.0), reverse=True)
    mints = dict(keep_mints or {})
    for residual in ranked:
        mint = mints.get(residual)
        if mint:
            return {
                "residual": residual,
                "help": float(help_scores.get(residual) or 0.0),
                "unsafe": float(unsafe.get(residual) or 0.0),
                "keep_structure": True,
                "mint": list(mint),
            }
    return {}


def gap_report(
    memory: Mapping[str, Any],
    *,
    keep_mints: Optional[Mapping[str, Sequence[str]]] = None,
    compose_plan_fn: Optional[Any] = None,
    unsafe_cut: float = 0.45,
) -> list[dict[str, Any]]:
    """Per-name next-skill notes from AutoResearch snapshots + bans. No Lean."""

    from jevops.outer import head_seq

    rows: list[dict[str, Any]] = []
    names: list[str] = []
    for snap in memory.get("research") or []:
        n = str(snap.get("name") or "")
        if n and n not in names:
            names.append(n)
    for name in names:
        prior = prior_research(memory, name)
        prop = propose_skill_from_research(memory, name, keep_mints=keep_mints, unsafe_cut=unsafe_cut)
        help_scores = dict(prior.get("help") or {})
        unsafe = dict(prior.get("unsafe") or {})
        ranked_residuals = sorted(
            help_scores,
            key=lambda key: float(help_scores.get(key) or 0.0),
            reverse=True,
        )
        plan = []
        if compose_plan_fn is not None:
            try:
                plan = list(compose_plan_fn(name) or [])
            except Exception:
                plan = []
        rows.append(
            {
                "name": name,
                "proposed": prop,
                "keep_intro": "intro_then_simp_all" in unsafe,
                "keep_constructor": "ctor_lone" in unsafe,
                "keep_structure": list(prop.get("mint") or []),
                "compose_plan": plan,
                "failed_stems": sorted(failed_skill_stems(memory, name)),
                "top_help": [
                    {
                        "residual": key,
                        "help": round(float(help_scores.get(key) or 0.0), 3),
                        "unsafe": round(float(unsafe.get(key) or 0.0), 3),
                        "do_not_cut": float(unsafe.get(key) or 0.0) >= unsafe_cut,
                    }
                    for key in head_seq(ranked_residuals, 4)
                ],
            }
        )
    return rows


def expand_keep_notes(
    memory: dict[str, Any],
    *,
    name: str,
    tactics: str = "",
    keep_mints: Optional[Mapping[str, Sequence[str]]] = None,
    residual_fn: Optional[Any] = None,
    keep_stems: Sequence[str] = (),
    residual_map: Optional[Mapping[str, str]] = None,
    unsafe_cut: float = 0.45,
) -> list[dict[str, Any]]:
    """Record keep-structure mints when AutoResearch says do not cut. No Lean."""

    prop = propose_skill_from_research(
        memory, name, keep_mints=keep_mints, unsafe_cut=unsafe_cut
    )
    notes: list[dict[str, Any]] = []
    if prop.get("keep_structure") and prop.get("mint"):
        notes.append({**prop, "name": name, "action": "keep_structure"})
    if tactics and residual_fn is not None:
        residuals = dict(residual_fn(tactics) or {})
        mapping = dict(residual_map or {})
        for stem in keep_stems:
            residual = mapping.get(stem, stem)
            if residuals.get(residual):
                notes.append(
                    {
                        "name": name,
                        "action": "keep_structure",
                        "residual": residual,
                        "mint": [stem],
                        "present": residuals.get(residual),
                    }
                )
    if notes:
        record_named_notes(memory, "expanded", name, notes, keep=8)
    return notes


def kind_stem(kind: str, *, extra: Sequence[str] = ("drop_unused_binders", "collapse_simp_at")) -> str:
    """port_foo_pipeline_a → foo; named extra kinds keep their name."""

    text = str(kind or "")
    if text.startswith("port_"):
        return text[len("port_") :].split("_pipeline")[0]
    if text in set(extra):
        return text
    return ""


def stem_win_loss(
    memory: Optional[Mapping[str, Any]] = None,
    *,
    extra: Sequence[str] = ("drop_unused_binders", "collapse_simp_at"),
) -> tuple[dict[str, int], dict[str, int]]:
    """Count port_ stem wins/losses. Extra named kinds count as wins only."""

    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    extra_kinds = tuple(extra)
    for row in (memory or {}).get("successes") or []:
        stem = kind_stem(str(row.get("kind") or ""), extra=extra_kinds)
        if stem:
            wins[stem] = wins.get(stem, 0) + 1
    for row in (memory or {}).get("failures") or []:
        stem = kind_stem(str(row.get("kind") or ""), extra=())
        if stem:
            losses[stem] = losses.get(stem, 0) + 1
    return wins, losses


def research_help(
    memory: Optional[Mapping[str, Any]],
    stem: str,
    *,
    name: str = "",
    residual_map: Optional[Mapping[str, str]] = None,
) -> float:
    """Average AutoResearch help for a stem's residual. Recurses unnamed if empty."""

    residual = str((residual_map or {}).get(stem) or "")
    if not residual:
        return 0.0
    total = 0.0
    n = 0
    for row in (memory or {}).get("research") or []:
        if name and row.get("name") != name:
            continue
        help_scores = row.get("help") or {}
        if residual in help_scores:
            total += float(help_scores.get(residual) or 0.0)
            n += 1
    if n:
        return total / n
    if name:
        return research_help(memory, stem, name="", residual_map=residual_map)
    return 0.0


def first_fold(
    tactics: str,
    skills: Sequence[Mapping[str, Any]],
    *,
    fold_fn: Any,
) -> Optional[dict[str, Any]]:
    """First memory skill that actually shortens tactics. fold_fn is injected."""

    body = str(tactics or "")
    for spec in skills or ():
        nxt = fold_fn(body, spec)
        if nxt and str(nxt) != body:
            return {"stem": spec.get("stem"), "tactics": nxt}
    return None


def apply_literal_fold(
    tactics: str,
    spec: Mapping[str, Any],
    *,
    token_fn: Optional[Any] = None,
) -> str:
    """old→new substring fold. Keeps listed tactic words. Strictly shorter when token_fn set."""

    old = str(spec.get("old") or "")
    new = str(spec.get("new") or "")
    if not old or old not in tactics:
        return tactics
    keep = [str(item) for item in (spec.get("keep") or [])]
    nxt = tactics.replace(old, new, max(1, int(spec.get("count") or 1)))
    for word in keep:
        if word in old and word not in nxt:
            return tactics
    if token_fn is not None and int(token_fn(nxt)) >= int(token_fn(tactics)):
        return tactics
    return nxt


def port_wins(memory: Optional[Mapping[str, Any]] = None, *, prefix: str = "port_") -> dict[str, int]:
    """kind → 1 for each success whose kind starts with prefix."""

    return {
        str(row.get("kind")): 1
        for row in (memory or {}).get("successes") or []
        if str(row.get("kind") or "").startswith(prefix)
    }
