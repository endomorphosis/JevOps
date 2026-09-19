#!/usr/bin/env python3
"""VAE-style text→Lean round-trip. Jev is the batch loss; lake is the oracle.

Adapts ipfs_datasets_py modal-autoencoder diagnostics (cosine / CE) as
*diagnostics only*. TypeSafe Jev replaces those as the training signal:
it scores the current variation against previous rounds in a batch.
Several VAE samples get Jev scores; among Jev-ok variants we keep the
shortest lake-valid Lean. Jev never writes Lean. Never docker0.
Not Arena scores. Not Track 2.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import hashlib
import math
import random
import re
from typing import Any, Callable, Mapping, Optional, Sequence

MILLE = 1000
LATENT_D = 16
BATCH_MAX = 8
N_VARIATIONS = 4
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _clip(value: int, lo: int = 0, hi: int = MILLE) -> int:
    return max(lo, min(hi, int(value)))


def _isqrt(n: int) -> int:
    return int(math.isqrt(max(0, int(n))))


def _tokens(text: str) -> list[str]:
    return [tok.lower() for tok in _TOKEN.findall(text or "")]


def _token_count(text: str) -> int:
    try:
        from jevops import hooks

        count_fn = hooks.get("token_count") or hooks.try_import("run_warmup", "token_count")
        if count_fn is None:
            raise RuntimeError("token_count_unavailable")
        return int(count_fn(text))
    except Exception:
        return len(_tokens(text))


def cosine_milles(left: Sequence[int], right: Sequence[int]) -> int:
    """Integer cosine in milles. Diagnostic only — Jev is the loss."""

    if not left or not right or len(left) != len(right):
        return 0
    dot = sum(int(a) * int(b) for a, b in zip(left, right))
    na = _isqrt(sum(int(a) * int(a) for a in left))
    nb = _isqrt(sum(int(b) * int(b) for b in right))
    if na <= 0 or nb <= 0:
        return 0
    return _clip((dot * MILLE) // (na * nb))


def ce_milles(target: Sequence[int], recon: Sequence[int]) -> int:
    """Integer mismatch milles (0 = identical). Diagnostic only."""

    if not target or len(target) != len(recon):
        return MILLE
    tot = sum(abs(int(a)) for a in target) or 1
    miss = sum(abs(int(a) - int(b)) for a, b in zip(target, recon))
    return _clip((miss * MILLE) // (2 * tot))


def encode_milles(text: str) -> dict[str, list[int]]:
    """Bag-of-token milles latent. Closed; no CUDA weights required."""

    toks = _tokens(text)
    mu = [0] * LATENT_D
    if not toks:
        return {"mu": mu, "logvar": [MILLE] * LATENT_D}
    for tok in toks:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        mu[digest[0] % LATENT_D] += MILLE
    n = max(1, len(toks))
    mu = [v // n for v in mu]
    peak = max(mu) if mu else 0
    logvar = [_clip(MILLE - peak) for _ in mu]
    return {"mu": mu, "logvar": logvar}


def sample_latent(
    encoded: Mapping[str, Sequence[int]],
    *,
    rng: random.Random,
) -> list[int]:
    """VAE reparameterize in milles: z = mu + (U[-std,std])."""

    mu = [int(x) for x in encoded.get("mu") or []]
    logvar = [int(x) for x in encoded.get("logvar") or []]
    z = []
    for i, mean in enumerate(mu):
        lv = logvar[i] if i < len(logvar) else MILLE
        std = max(1, lv // 4)
        z.append(_clip(mean + rng.randrange(-std, std + 1), lo=-2 * MILLE, hi=2 * MILLE))
    return z if z else [0] * LATENT_D


def kl_milles(encoded: Mapping[str, Sequence[int]]) -> int:
    """Integer KL vs milles-N(0,1): ½ Σ (μ²/1000 + var − 1000)."""

    mu = [int(x) for x in encoded.get("mu") or []]
    logvar = [int(x) for x in encoded.get("logvar") or []]
    acc = 0
    for i, mean in enumerate(mu):
        var = logvar[i] if i < len(logvar) else MILLE
        acc += (mean * mean) // MILLE + var - MILLE
    return max(0, acc // 2)


def _codebook(memory: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(((memory.get("nca") or {}).get("autoencoder") or {}).get("codebook") or [])


def decode_lean(
    latent: Sequence[int],
    *,
    source: str = "",
    codebook: Optional[Sequence[Mapping[str, Any]]] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Map latent → Lean sketch. Not a proof admit. Prefer codebook snippets."""

    rows = list(codebook or [])
    if rows:
        scored = []
        for row in rows:
            sim = cosine_milles(latent, list(row.get("mu") or []))
            toks = int(row.get("n_tokens") or _token_count(str(row.get("lean") or "")))
            scored.append((-sim, toks, str(row.get("lean") or "")))
        scored.sort()
        pieces = []
        used = 0
        budget = int(max_tokens) if max_tokens else 10**9
        for _sim, toks, lean in scored:
            if not lean.strip():
                continue
            if used + toks > budget and pieces:
                break
            pieces.append(lean.rstrip())
            used += toks
            if used >= budget:
                break
        if pieces:
            return "\n".join(pieces) + "\n"
    toks = _tokens(source)[:12]
    ident = toks[0] if toks else "roundtrip"
    ident = re.sub(r"[^A-Za-z0-9_]", "", ident) or "roundtrip"
    body = "  trivial\n"
    if max_tokens is not None and max_tokens <= 4:
        body = "  trivial\n"
    return f"theorem {ident}_rt : True := by\n{body}"


def _datasets_diagnostics(left: Sequence[int], right: Sequence[int]) -> dict[str, Any]:
    """Optional ipfs_datasets_py cosine/CE. Diagnostic, never gold."""

    out: dict[str, Any] = {"ok": False}
    try:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder import (
            cosine_loss,
            cosine_similarity,
        )

        lf = [float(x) / float(MILLE) for x in left]
        rf = [float(x) / float(MILLE) for x in right]
        out = {
            "ok": True,
            "cosine_similarity": cosine_similarity(lf, rf),
            "cosine_loss": cosine_loss(lf, rf),
            "gold": False,
        }
    except Exception as exc:
        out = {"ok": False, "reason": type(exc).__name__, "gold": False}
    return out


def roundtrip_once(
    text: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    rng: Optional[random.Random] = None,
    max_tokens: Optional[int] = None,
    latent: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    rng = rng or random.Random(0)
    encoded = encode_milles(text)
    z = list(latent) if latent is not None else sample_latent(encoded, rng=rng)
    lean = decode_lean(z, source=text, codebook=_codebook(memory or {}), max_tokens=max_tokens)
    recon = encode_milles(lean)
    cos = cosine_milles(encoded["mu"], recon["mu"])
    ce = ce_milles(encoded["mu"], recon["mu"])
    return {
        "text": text,
        "lean": lean,
        "mu": encoded["mu"],
        "z": z,
        "recon_mu": recon["mu"],
        "cosine_m": cos,
        "ce_m": ce,
        "kl_m": kl_milles(encoded),
        "n_tokens": _token_count(lean),
        "datasets": _datasets_diagnostics(encoded["mu"], recon["mu"]),
        "writes_lean": False,
        "integer": True,
    }


def _batch(memory: dict[str, Any]) -> list[dict[str, Any]]:
    store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
    batch = list(store.get("batch") or [])
    return batch


def jev_rank_variations(
    variations: Sequence[Mapping[str, Any]],
    *,
    previous: Sequence[Mapping[str, Any]] = (),
    jev_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    """Jev replaces CE/cosine as the batch loss. Compares current vs previous rounds."""

    pool = list(variations) + list(previous)
    if not pool:
        return {"ok": False, "reason": "empty", "order": [], "writes_lean": False}
    if jev_fn is None:
        scored = sorted(
            enumerate(pool),
            key=lambda item: (
                -int(item[1].get("cosine_m") or 0),
                int(item[1].get("ce_m") or MILLE),
                int(item[1].get("n_tokens") or 10**9),
            ),
        )
        order = [i for i, _row in scored]
        return {
            "ok": True,
            "used_jev": False,
            "order": order,
            "best": pool[order[0]] if order else None,
            "proxy": "milles_fallback",
            "writes_lean": False,
        }
    ids = [f"v{i}" for i in range(len(pool))]
    payload = {
        "variations": [
            {
                "id": ids[i],
                "n_tokens": int(row.get("n_tokens") or 0),
                "cosine_m": int(row.get("cosine_m") or 0),
                "ce_m": int(row.get("ce_m") or 0),
                "from_previous": i >= len(variations),
                "lean_head": str(row.get("lean") or "")[:80],
            }
            for i, row in enumerate(pool)
        ]
    }
    try:
        result = dict(jev_fn(payload) or {})
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "used_jev": True, "writes_lean": False}
    choice = str(result.get("choice") or result.get("best_id") or "")
    scores = dict(result.get("scores") or {})
    noul = float(result.get("noul") or result.get("reconstruction_broke") or 0.0)
    order = list(range(len(pool)))
    if choice in ids:
        order.sort(key=lambda i: (0 if ids[i] == choice else 1, -int(scores.get(ids[i]) or 0), int(pool[i].get("n_tokens") or 10**9)))
    elif scores:
        order.sort(key=lambda i: (-int(scores.get(ids[i]) or 0), int(pool[i].get("n_tokens") or 10**9)))
    else:
        order.sort(key=lambda i: int(pool[i].get("n_tokens") or 10**9))
    best = pool[order[0]]
    return {
        "ok": True,
        "used_jev": True,
        "choice": choice,
        "order": order,
        "best": best,
        "noul": noul,
        "scores": scores,
        "writes_lean": False,
        "called_docker0": False,
    }


def teach_roundtrip(
    memory: dict[str, Any],
    text: str,
    *,
    tactics: str = "",
    problem: str = "",
    jev_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    rng: Optional[random.Random] = None,
    n_variations: int = N_VARIATIONS,
) -> dict[str, Any]:
    """Sample VAE variations, Jev-rank vs previous batch, keep shortest lake-ok Lean."""

    rng = rng or random.Random(0)
    source = str(text or tactics or "")
    encoded = encode_milles(source)
    lengths = [None, max(4, _token_count(source) * 3 // 4), max(3, _token_count(source) // 2), 4]
    variations: list[dict[str, Any]] = []
    for i in range(max(1, int(n_variations))):
        z = sample_latent(encoded, rng=rng)
        cap = lengths[i] if i < len(lengths) else None
        row = roundtrip_once(source, memory=memory, rng=rng, max_tokens=cap, latent=z)
        row["variation"] = i
        variations.append(row)
    previous = _batch(memory)
    ranked = jev_rank_variations(variations, previous=previous, jev_fn=jev_fn)
    winner = dict(ranked.get("best") or variations[0])
    if ranked.get("used_jev"):
        try:
            from jevops import plan as lra_plan

            lra_plan.record_jev(
                memory,
                choice=str(ranked.get("choice") or ""),
                score_m=int(winner.get("cosine_m") or 0),
                noul_m=int(float(ranked.get("noul") or 0) * 1000) if float(ranked.get("noul") or 0) <= 2 else int(ranked.get("noul") or 0),
                task_id="",
                skill="autoencoder",
                text="vae batch jev",
            )
        except Exception:
            pass
    lake_ok = None
    if compile_fn is not None:
        try:
            lake = compile_fn(winner.get("lean") or "", problem=problem)
            lake_ok = bool((lake or {}).get("theorem_ok"))
            winner["lake_ok"] = lake_ok
            winner["lake_tokens"] = int((lake or {}).get("token_count") or winner.get("n_tokens") or 0)
        except Exception as exc:
            lake_ok = False
            winner["lake_ok"] = False
            winner["lake_reason"] = type(exc).__name__
        if lake_ok is False:
            for idx in ranked.get("order") or []:
                if idx >= len(variations):
                    continue
                cand = variations[idx]
                try:
                    lake = compile_fn(cand.get("lean") or "", problem=problem)
                except Exception:
                    continue
                if lake.get("theorem_ok"):
                    winner = dict(cand)
                    winner["lake_ok"] = True
                    winner["lake_tokens"] = int(lake.get("token_count") or cand.get("n_tokens") or 0)
                    lake_ok = True
                    break
    # Prefer minimal length among Jev-ok variations that laked (or all if no lake).
    jev_ok = [variations[i] for i in (ranked.get("order") or []) if i < len(variations)]
    if lake_ok:
        jev_ok = [row for row in jev_ok if row.get("lake_ok") or row is winner]
    if jev_ok:
        shortest = min(jev_ok, key=lambda row: int(row.get("n_tokens") or 10**9))
        if lake_ok is None or shortest.get("lake_ok") or shortest is winner:
            if int(shortest.get("n_tokens") or 10**9) <= int(winner.get("n_tokens") or 10**9):
                winner = dict(shortest)
                winner["picked"] = "shortest_jev_ok"
    store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
    batch = list(store.get("batch") or [])
    batch.append(
        {
            "problem": problem,
            "cosine_m": int(winner.get("cosine_m") or 0),
            "ce_m": int(winner.get("ce_m") or 0),
            "n_tokens": int(winner.get("n_tokens") or 0),
            "lean": str(winner.get("lean") or "")[:400],
            "mu": list(winner.get("mu") or []),
            "used_jev": bool(ranked.get("used_jev")),
        }
    )
    store["batch"] = batch[-BATCH_MAX:]
    if winner.get("lake_ok") or compile_fn is None:
        code = list(store.get("codebook") or [])
        code.append(
            {
                "mu": list(encoded["mu"]),
                "lean": str(winner.get("lean") or ""),
                "n_tokens": int(winner.get("n_tokens") or 0),
                "problem": problem,
            }
        )
        store["codebook"] = code[-32:]
    try:
        from jevops.nca import upsert_from_event

        upsert_from_event(
            memory,
            ptr="ptr://skill/port_autoencoder",
            kind="skill",
            energy=min(0.9, 0.4 + 0.0005 * int(winner.get("cosine_m") or 0)),
        )
    except Exception:
        pass
    return {
        "ok": True,
        "kind": "port_autoencoder",
        "n_variations": len(variations),
        "n_previous": len(previous),
        "used_jev": bool(ranked.get("used_jev")),
        "cosine_m": int(winner.get("cosine_m") or 0),
        "ce_m": int(winner.get("ce_m") or 0),
        "kl_m": int(winner.get("kl_m") or 0),
        "n_tokens": int(winner.get("n_tokens") or 0),
        "lean": winner.get("lean"),
        "lake_ok": winner.get("lake_ok"),
        "jev": {k: ranked[k] for k in ranked if k != "best"},
        "datasets": winner.get("datasets"),
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
        "loss": "jev_batch" if ranked.get("used_jev") else "milles_fallback",
    }


def call_autoencoder(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
    text: str = "",
    jev_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    rng: Optional[random.Random] = None,
) -> dict[str, Any]:
    source = str(text or tactics or problem or "")
    out = teach_roundtrip(
        memory,
        source,
        tactics=tactics,
        problem=problem,
        jev_fn=jev_fn,
        compile_fn=compile_fn,
        rng=rng,
        n_variations=N_VARIATIONS,
    )
    if "vae" in str(stem or "").lower():
        out["kind"] = "port_vae"
    return out
