#!/usr/bin/env python3
"""Text→canonical Lean IR→text round-trip and training façade.

The parser/renderer is dependency-free.  The companion
``autoencoder_training`` module adds teacher-forced operation cross-entropy,
cosine-aware latent updates, canary/holdout splits, learning-rate control,
and verifier-gated TypeSafe/JeV rewards.  Lake remains the proof oracle and
this kernel never writes Lean files or claims Lean Refactor Arena scores.
Never docker0. Not Track 2.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from typing import Any, Callable, Mapping, Optional, Sequence

MILLE = 1000
LATENT_D = 16
BATCH_MAX = 8
N_VARIATIONS = 4
# ``v1`` accepted on input for old memory, ``v2`` emitted by the canonical
# parser.  The IR remains a functional Lean IR; legal/modal IR families are
# intentionally outside this kernel.
LEAN_IR_SCHEMA = "jevops-lean-ir/v2"
LEAN_IR_LEGACY_SCHEMA = "jevops-lean-ir/v1"
# Keep the vocabulary bounded so the decoder can be grammar constrained while
# still covering the common refactoring surface.  Arguments are structured
# separately from operation names.
LEAN_IR_OPS = (
    "intro",
    "intros",  # v1 alias; canonical IR normalizes it to ``intro``.
    "exact",
    "apply",
    "assumption",
    "cases",
    "induction",
    "simp",
    "simp_all",
    "rw",
    "nth_rewrite",
    "dsimp",
    "unfold",
    "change",
    "show",
    "have",
    "use",
    "refine",
    "exfalso",
    "contradiction",
    "left",
    "right",
    "rfl",
    "trivial",
    "constructor",
    "omega",
    "linarith",
    "nlinarith",
    "norm_num",
    "ring",
    "ring_nf",
    "aesop",
    "grind",
    "decide",
)
_FUNCTIONAL_BODY = frozenset(LEAN_IR_OPS)
_TOKEN = re.compile(r"[A-Za-z0-9_]+")
_LEAN_HEADER = re.compile(
    r"\b(?:theorem|lemma|example)\s+(?P<ident>[A-Za-z_][A-Za-z0-9_']*)"
    r"(?P<header>.*?)\s*:=\s*by\b",
    re.IGNORECASE | re.DOTALL,
)
_UNSAFE_IR_TEXT = re.compile(
    r"(?:\b(?:sorry|admit|unsafe|run_tac|exact\?|import|namespace|open|set_option|macro|elab|quote)\b|<;>|\|)",
    re.IGNORECASE,
)


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


def proof_body_token_count(text: str) -> int:
    """Count tokens in the proof body while leaving theorem headers out.

    Arena-style compression is measured on the proof source, not on the
    repeated theorem declaration.  Tactic snippets have no header, so they
    naturally fall back to the ordinary token count.
    """

    source = str(text or "")
    marker = re.search(r":=\s*by\b", source, re.IGNORECASE)
    return _token_count(source[marker.end() :] if marker else source)


def _safe_ir_arg(value: Any, *, max_chars: int = 160) -> str:
    """Return a single-line, non-admitting IR argument or an empty string."""

    text = " ".join(str(value or "").replace("\x00", " ").split())[:max_chars]
    if not text or _UNSAFE_IR_TEXT.search(text) or ";" in text:
        return ""
    return text


def _op_item(item: Any) -> tuple[str, tuple[str, ...]]:
    if isinstance(item, Mapping):
        op = str(item.get("op") or "").strip().lower()
        raw_args = item.get("args")
        if raw_args is None and item.get("arg") is not None:
            raw_args = [item.get("arg")]
    else:
        parts = str(item or "").strip().split(None, 1)
        op = parts[0].lower() if parts else ""
        raw_args = [parts[1]] if len(parts) > 1 else []
    if op == "intros":
        op = "intro"
    if op not in LEAN_IR_OPS:
        return "", ()
    if isinstance(raw_args, str):
        raw_args = [raw_args]
    args = tuple(arg for arg in (_safe_ir_arg(value) for value in (raw_args or ())) if arg)
    return op, args


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


def encode_lean_ir(text: str) -> dict[str, Any]:
    """Parse text into deterministic, grammar-constrained Lean IR.

    The old implementation treated every matching word as an operation and
    discarded all arguments.  That made ``exact h`` indistinguishable from
    ``exact k`` and made a round trip impossible to train.  The v2 parser
    retains bounded operation arguments and theorem goals, while still
    defaulting plain tactic snippets to the historical ``True`` exercise.
    """

    source = str(text or "")
    match = _LEAN_HEADER.search(source)
    if match:
        ident = re.sub(r"[^A-Za-z0-9_]", "", str(match.group("ident") or "roundtrip")) or "roundtrip"
        header = " ".join(str(match.group("header") or "").split())
        goal = header.rsplit(":", 1)[-1].strip() if ":" in header else "True"
        goal = goal.strip("() ") or "True"
        binder_source = header.rsplit(":", 1)[0].strip() if ":" in header else ""
        binders = [
            _safe_ir_arg(found.group(0), max_chars=240)
            for found in re.finditer(r"(?:\([^()]+\)|\[[^\[\]]+\]|\{[^{}]+\})", binder_source)
        ]
        binders = [binder for binder in binders if binder]
        body = source[match.end() :]
    else:
        plain_head = _tokens(source)
        ident = re.sub(r"[^A-Za-z0-9_]", "", plain_head[0] if plain_head else "roundtrip") or "roundtrip"
        goal = "True"
        binders = []
        body = source
    if _UNSAFE_IR_TEXT.search(goal):
        goal = "True"

    parsed: list[dict[str, Any]] = []
    # Parse line heads first so arguments stay attached to their operation.
    # Semicolon-separated tactic syntax is split only at the outer textual
    # level; semicolons are never accepted inside stored arguments.
    chunks: list[str] = []
    for line in body.splitlines() or [body]:
        cleaned = re.sub(r"^\s*(?:\.|·|case\s+[^:]+:)\s*", "", line).strip()
        chunks.extend(piece.strip() for piece in re.split(r"\s*;\s*", cleaned) if piece.strip())
    if not chunks:
        chunks = [body]
    for chunk in chunks:
        if not match:
            op_pattern = r"(?<![A-Za-z0-9_])(" + "|".join(sorted(LEAN_IR_OPS, key=len, reverse=True)) + r")(?![A-Za-z0-9_])"
            op_matches = list(re.finditer(op_pattern, chunk, re.IGNORECASE))
            if len(op_matches) > 1:
                for pos, found in enumerate(op_matches):
                    end = op_matches[pos + 1].start() if pos + 1 < len(op_matches) else len(chunk)
                    op, args = _op_item({"op": found.group(1), "args": [chunk[found.end() : end].strip()]})
                    if op:
                        parsed.append({"op": op, **({"args": list(args)} if args else {})})
                continue
        match_op = re.match(r"^(?P<op>[A-Za-z_][A-Za-z0-9_']*)(?:\s+(?P<args>.*))?$", chunk)
        if match_op:
            op, args = _op_item({"op": match_op.group("op"), "args": [match_op.group("args")] if match_op.group("args") else []})
            if op:
                parsed.append({"op": op, **({"args": list(args)} if args else {})})
    if not parsed:
        toks = _tokens(source)
        parsed = [{"op": tok} for tok in toks if tok in LEAN_IR_OPS]
    if not parsed:
        parsed = [{"op": "trivial"}]
    canonical_ops = []
    for item in parsed:
        op, args = _op_item(item)
        if op:
            canonical_ops.append({"op": op, **({"args": list(args)} if args else {})})
    canonical_ops = canonical_ops or [{"op": "trivial"}]
    payload = {
        "schema": LEAN_IR_SCHEMA,
        "goal": goal,
        "ident": ident,
        "binders": binders,
        "ops": canonical_ops,
        "families": [],
        "legal_ir": False,
        "functional_lean": True,
        "source_digest": hashlib.sha256(" ".join(source.split()).encode("utf-8")).hexdigest(),
        "ops_digest": hashlib.sha256(json.dumps(canonical_ops, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "source_copy": False,
    }
    return payload


def ir_counts(ir: Mapping[str, Any]) -> list[int]:
    """Bag of functional Lean IR ops as milles. Not a legal-IR family vector."""

    bag = {op: 0 for op in LEAN_IR_OPS}
    for item in ir.get("ops") or ():
        op = str(item.get("op") or "") if isinstance(item, Mapping) else str(item)
        if op == "intros":
            op = "intro"
        if op in bag:
            bag[op] += MILLE
    return [bag[op] for op in LEAN_IR_OPS]


def decode_lean_ir(ir: Mapping[str, Any]) -> str:
    """Render Lean IR without admitting goals or executing arbitrary text."""

    ident = re.sub(r"[^A-Za-z0-9_]", "", str(ir.get("ident") or "roundtrip")) or "roundtrip"
    goal = _safe_ir_arg(ir.get("goal") or "True", max_chars=600) or "True"
    raw_binders = ir.get("binders") or ()
    if isinstance(raw_binders, str):
        raw_binders = [raw_binders]
    binders = [binder for binder in (_safe_ir_arg(value, max_chars=240) for value in raw_binders) if binder]
    lines: list[str] = []
    for item in ir.get("ops") or ():
        op, args = _op_item(item)
        if not op:
            continue
        # A no-argument exact/apply/change/etc. is not a meaningful Lean
        # command.  Render a closed fallback so malformed model output cannot
        # become a syntactically plausible but unsafe candidate.
        if op in {"exact", "apply", "cases", "induction", "rw", "nth_rewrite", "change", "show", "have", "use", "refine", "unfold"} and not args:
            lines.append("  trivial")
            continue
        rendered = op
        if args:
            rendered += " " + " ".join(args)
        lines.append(f"  {rendered}")
    if not lines:
        lines = ["  trivial"]
    body = "\n".join(lines)
    telescope = (" " + " ".join(binders)) if binders else ""
    return f"theorem {ident}_rt{telescope} : {goal} := by\n{body}\n"


def perturb_lean_ir(ir: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    """Drop/replace functional closers. Stays ``True := by`` Lean."""

    nxt = dict(ir)
    ops = [dict(item) if isinstance(item, Mapping) else {"op": str(item)} for item in (ir.get("ops") or ())]
    if ops and rng.randrange(2):
        ops.pop()
    if rng.randrange(2):
        ops.append({"op": rng.choice(("trivial", "rfl", "constructor", "simp"))})
    if not ops:
        ops = [{"op": "trivial"}]
    nxt["ops"] = ops
    nxt["families"] = []
    nxt["legal_ir"] = False
    nxt["functional_lean"] = True
    nxt["schema"] = LEAN_IR_SCHEMA
    nxt["ops_digest"] = hashlib.sha256(json.dumps(ops, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return nxt


def _ir_with_ops(ir: Mapping[str, Any], ops: Sequence[Any]) -> dict[str, Any]:
    """Copy an IR envelope while replacing only its bounded operation list."""

    normalized: list[dict[str, Any]] = []
    for item in ops:
        op, args = _op_item(item)
        if op:
            normalized.append({"op": op, **({"args": list(args)} if args else {})})
    if not normalized:
        normalized = [{"op": "trivial"}]
    out = dict(ir)
    out["ops"] = normalized
    out["families"] = []
    out["legal_ir"] = False
    out["functional_lean"] = True
    out["schema"] = LEAN_IR_SCHEMA
    out["source_copy"] = False
    out["ops_digest"] = hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return out


def _candidate_ir_variants(
    base_ir: Mapping[str, Any],
    *,
    limit: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    """Create bounded shrink candidates before stochastic perturbations.

    The old sampler could only remove one operation, which made a proof such
    as ``simp; simp`` or a chain of redundant ``have`` declarations almost
    impossible to shorten.  Deterministic one-command probes are cheap, and
    Lake still decides whether any of them are legal.
    """

    variants: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: Mapping[str, Any]) -> None:
        if len(variants) >= max(1, int(limit)):
            return
        key = json.dumps(candidate.get("ops") or (), sort_keys=True, separators=(",", ":"))
        if key in seen:
            return
        seen.add(key)
        variants.append(dict(candidate))

    add(base_ir)
    goal = str(base_ir.get("goal") or "").strip()
    preferred: list[Any] = []
    if goal.lower() == "true":
        preferred.append("trivial")
    if "=" in goal:
        preferred.extend(("rfl", "simp"))
    else:
        preferred.extend(("assumption", "simp", "rfl"))
    binder_names: list[str] = []
    for binder in base_ir.get("binders") or ():
        match = re.match(r"[([{]\s*([A-Za-z_][A-Za-z0-9_']*)", str(binder))
        if match:
            binder_names.append(match.group(1))
    preferred.extend({"op": "exact", "args": [name]} for name in binder_names[:4])
    preferred.extend(("decide", "omega", "norm_num", "constructor"))
    for op in preferred:
        add(_ir_with_ops(base_ir, [op]))

    raw_ops = list(base_ir.get("ops") or ())
    for size in range(max(1, len(raw_ops) - 1), 0, -1):
        for start in range(0, len(raw_ops) - size + 1):
            add(_ir_with_ops(base_ir, raw_ops[start : start + size]))
            if len(variants) >= max(1, int(limit)):
                break
        if len(variants) >= max(1, int(limit)):
            break
    while len(variants) < max(1, int(limit)):
        add(perturb_lean_ir(base_ir, rng))
        if len(seen) > max(2, int(limit)) * 3:
            break
    return variants[: max(1, int(limit))]


def ir_diagnostics(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, int]:
    """IR-op CE and cosine. Diagnostic only — Jev is the loss."""

    a = ir_counts(left)
    b = ir_counts(right)
    return {"ir_cosine_m": cosine_milles(a, b), "ir_ce_m": ce_milles(a, b)}


def decode_lean(
    latent: Sequence[int],
    *,
    source: str = "",
    codebook: Optional[Sequence[Mapping[str, Any]]] = None,
    max_tokens: Optional[int] = None,
    ir: Optional[Mapping[str, Any]] = None,
    force_ir: bool = False,
) -> str:
    """Map latent / Lean IR → functional Lean sketch. Not a proof admit."""

    rows = [] if force_ir else list(codebook or [])
    if rows:
        scored = []
        for row in rows:
            sim = cosine_milles(latent, list(row.get("mu") or []))
            toks = int(row.get("n_tokens") or _token_count(str(row.get("lean") or "")))
            scored.append((-sim, toks, str(row.get("lean") or "")))
        scored.sort()
        budget = int(max_tokens) if max_tokens else 10**9
        # A codebook is a nearest-neighbour warm start, not a proof-script
        # concatenator.  Concatenating independent theorem declarations was a
        # silent validity bug and made token rewards meaningless.
        for _sim, toks, lean in scored:
            if lean.strip() and (toks <= budget or not max_tokens):
                return lean.rstrip() + "\n"
    packed = dict(ir or encode_lean_ir(source))
    if max_tokens is not None and int(max_tokens) <= 4:
        packed = dict(packed)
        packed["ops"] = [{"op": "trivial"}]
    return decode_lean_ir(packed)


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


def lean_ir_roundtrip(
    text: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    rng: Optional[random.Random] = None,
    ir: Optional[Mapping[str, Any]] = None,
    max_tokens: Optional[int] = None,
    force_ir: bool = True,
) -> dict[str, Any]:
    """text → Lean IR → functional Lean → IR. CE/cosine diagnostics; Jev is gold."""

    rng = rng or random.Random(0)
    packed = dict(ir or encode_lean_ir(text))
    if rng.randrange(3) == 0:
        packed = perturb_lean_ir(packed, rng)
    encoded = encode_milles(text)
    lean = decode_lean(
        encoded["mu"],
        source=text,
        codebook=_codebook(memory or {}),
        max_tokens=max_tokens,
        ir=packed,
        force_ir=force_ir,
    )
    recon_ir = encode_lean_ir(lean)
    recon = encode_milles(lean)
    ird = ir_diagnostics(packed, recon_ir)
    return {
        "text": text,
        "ir": packed,
        "recon_ir": recon_ir,
        "lean": lean,
        "mu": encoded["mu"],
        "z": encoded["mu"],
        "recon_mu": recon["mu"],
        "cosine_m": cosine_milles(encoded["mu"], recon["mu"]),
        "ce_m": ce_milles(encoded["mu"], recon["mu"]),
        "ir_cosine_m": ird["ir_cosine_m"],
        "ir_ce_m": ird["ir_ce_m"],
        "kl_m": kl_milles(encoded),
        "n_tokens": _token_count(lean),
        "body_tokens": proof_body_token_count(lean),
        "datasets": _datasets_diagnostics(encoded["mu"], recon["mu"]),
        "gold": False,
        "loss_gold": "jev",
        "legal_ir": False,
        "functional_lean": True,
        "writes_lean": False,
        "integer": True,
    }


def roundtrip_once(
    text: str,
    *,
    memory: Optional[Mapping[str, Any]] = None,
    rng: Optional[random.Random] = None,
    max_tokens: Optional[int] = None,
    latent: Optional[Sequence[int]] = None,
    ir: Optional[Mapping[str, Any]] = None,
    force_ir: bool = False,
    use_model: bool = True,
) -> dict[str, Any]:
    rng = rng or random.Random(0)
    encoded = encode_milles(text)
    z = list(latent) if latent is not None else sample_latent(encoded, rng=rng)
    packed = dict(ir or encode_lean_ir(text))
    model_step = 0
    if use_model:
        try:
            from .autoencoder_training import LeanIRAutoencoder

            training_state = ((memory or {}).get("nca") or {}).get("autoencoder") or {}
            if training_state.get("training_state"):
                model = LeanIRAutoencoder.from_dict(training_state.get("training_state"))
                model_step = model.step
                if model_step > 0:
                    packed = model.predict_ir(text, source_ir=packed, max_ops=max(1, int(max_tokens or model.config.max_ops)))
                    z = [int(round(value * MILLE)) for value in model.predict_latent(text)]
        except Exception:
            # A malformed optional checkpoint must not break the portable
            # kernel; the deterministic parser remains the safe fallback.
            model_step = 0
    lean = decode_lean(
        z,
        source=text,
        codebook=_codebook(memory or {}),
        max_tokens=max_tokens,
        ir=packed,
        force_ir=force_ir,
    )
    recon = encode_milles(lean)
    recon_ir = encode_lean_ir(lean)
    ird = ir_diagnostics(packed, recon_ir)
    cos = cosine_milles(encoded["mu"], recon["mu"])
    ce = ce_milles(encoded["mu"], recon["mu"])
    return {
        "text": text,
        "ir": packed,
        "recon_ir": recon_ir,
        "lean": lean,
        "mu": encoded["mu"],
        "z": z,
        "recon_mu": recon["mu"],
        "cosine_m": cos,
        "ce_m": ce,
        "ir_cosine_m": ird["ir_cosine_m"],
        "ir_ce_m": ird["ir_ce_m"],
        "kl_m": kl_milles(encoded),
        "n_tokens": _token_count(lean),
        "body_tokens": proof_body_token_count(lean),
        "datasets": _datasets_diagnostics(encoded["mu"], recon["mu"]),
        "gold": False,
        "loss_gold": "jev",
        "legal_ir": False,
        "functional_lean": True,
        "writes_lean": False,
        "integer": True,
        "model_step": model_step,
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

    from jevops.outer import head_chars

    pool = list(variations) + list(previous)
    if not pool:
        return {"ok": False, "reason": "empty", "order": [], "writes_lean": False}
    from .autoencoder_training import score_candidate

    if jev_fn is None:
        scored = sorted(
            enumerate(pool),
            key=lambda item: (
                -float(score_candidate(item[1]).get("reward") or 0.0),
                int(item[1].get("n_tokens") or 10**9),
                item[0],
            ),
        )
        order = [i for i, _row in scored]
        current_order = [i for i in order if i < len(variations)]
        return {
            "ok": True,
            "used_jev": False,
            "order": order,
            "current_order": current_order,
            "best": pool[current_order[0]] if current_order else (pool[order[0]] if order else None),
            "proxy": "composite_semantic_fallback",
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
                "ir_cosine_m": int(row.get("ir_cosine_m") or 0),
                "ir_ce_m": int(row.get("ir_ce_m") or 0),
                "from_previous": i >= len(variations),
                "lean_head": head_chars(row.get("lean"), 80),
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
        order.sort(key=lambda i: (-float(score_candidate(pool[i]).get("reward") or 0.0), int(pool[i].get("n_tokens") or 10**9)))
    current_order = [i for i in order if i < len(variations)]
    # Previous rounds are comparison references, never the candidate for a
    # new source.  This closes a subtle cross-sample leakage path in the old
    # batch ranker.
    best_index = current_order[0] if current_order else (order[0] if order else -1)
    best = pool[best_index] if best_index >= 0 else None
    return {
        "ok": True,
        "used_jev": True,
        "choice": choice,
        "order": order,
        "current_order": current_order,
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
    force_ir: bool = False,
    typesafe_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    fuzzy_prover_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    train: bool = True,
) -> dict[str, Any]:
    """Sample, score, verify, and perform one bounded online update.

    TypeSafe/JeV may rank candidates, but Lake (when supplied) is the hard
    admission gate.  All current candidates are verified at most once, and a
    previous batch row can never become the output for a new source.
    """

    rng = rng or random.Random(0)
    from .autoencoder_training import _canonical_ops, _clip01, minimality_score, nca_feedback_for_example

    source = str(text or tactics or "")
    encoded = encode_milles(source)
    base_ir = encode_lean_ir(source)
    ir_variants = _candidate_ir_variants(
        base_ir,
        limit=max(1, int(n_variations)),
        rng=rng,
    )
    variations: list[dict[str, Any]] = []
    for i, packed in enumerate(ir_variants):
        z = sample_latent(encoded, rng=rng)
        # Deterministic shrink probes must retain their requested operation;
        # the historical tiny-token cap would otherwise replace ``rfl`` or
        # ``simp`` with ``trivial`` before the verifier sees it.
        row = roundtrip_once(
            source,
            memory=memory,
            rng=rng,
            max_tokens=None,
            latent=z,
            ir=packed,
            force_ir=force_ir,
        )
        row["variation"] = i
        variations.append(row)
    previous = _batch(memory)
    ranked = jev_rank_variations(variations, previous=previous, jev_fn=jev_fn)
    current_order = [idx for idx in (ranked.get("current_order") or ranked.get("order") or []) if idx < len(variations)]
    if not current_order:
        current_order = list(range(len(variations)))
    type_result: dict[str, Any] = {}
    if typesafe_fn is not None:
        try:
            compact = [
                {
                    "id": f"v{idx}",
                    "n_tokens": int(variations[idx].get("n_tokens") or 0),
                    "cosine_m": int(variations[idx].get("cosine_m") or 0),
                    "ce_m": int(variations[idx].get("ce_m") or 0),
                    "ir_cosine_m": int(variations[idx].get("ir_cosine_m") or 0),
                    "ir_ce_m": int(variations[idx].get("ir_ce_m") or 0),
                }
                for idx in current_order
            ]
            type_result = dict(typesafe_fn(compact) or {})
        except Exception as exc:
            type_result = {"ok": False, "reason": type(exc).__name__}
    fuzzy_result: dict[str, Any] = {}
    if fuzzy_prover_fn is not None:
        try:
            fuzzy_rows = []
            for idx in current_order:
                candidate_ir = variations[idx].get("ir")
                candidate_ops = [op for op, _args in _canonical_ops(candidate_ir)] if isinstance(candidate_ir, Mapping) else []
                fuzzy_rows.append(
                    {
                        "id": f"v{idx}",
                        "ir_digest": hashlib.sha256(
                            json.dumps(candidate_ir or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
                        ).hexdigest(),
                        "ir_ops": candidate_ops,
                        "n_tokens": int(variations[idx].get("n_tokens") or 0),
                        "cosine_m": int(variations[idx].get("cosine_m") or 0),
                        "ce_m": int(variations[idx].get("ce_m") or 0),
                        "ir_cosine_m": int(variations[idx].get("ir_cosine_m") or 0),
                        "ir_ce_m": int(variations[idx].get("ir_ce_m") or 0),
                    }
                )
            try:
                fuzzy_result = dict(
                    fuzzy_prover_fn(
                        problem=problem,
                        variations=fuzzy_rows,
                        goal=str(base_ir.get("goal") or source),
                    )
                    or {}
                )
            except TypeError:
                fuzzy_result = dict(fuzzy_prover_fn(problem, fuzzy_rows) or {})
        except Exception as exc:
            fuzzy_result = {"ok": False, "reason": type(exc).__name__, "verified": False}
    type_choice = str(type_result.get("choice") or type_result.get("best_id") or "")
    type_scores = dict(type_result.get("scores") or {})
    type_reward = type_result.get("reward")
    if type_reward is not None:
        try:
            type_reward = max(0.0, min(1.0, float(type_reward)))
        except (TypeError, ValueError):
            type_reward = None

    # Verify each current candidate once.  This is more expensive than
    # trusting Jev's first pick, but avoids selecting an uncompiled shorter
    # script merely because it won a soft ranking.
    compile_cache: dict[str, Mapping[str, Any]] = {}
    if compile_fn is not None:
        for idx in current_order:
            candidate = variations[idx]
            lean_text = str(candidate.get("lean") or "")
            cache_key = hashlib.sha256(lean_text.encode("utf-8")).hexdigest()
            if cache_key in compile_cache:
                lake = compile_cache[cache_key]
            else:
                try:
                    try:
                        lake = dict(compile_fn(lean_text, problem=problem) or {})
                    except TypeError:
                        lake = dict(compile_fn(lean_text) or {})
                except Exception as exc:
                    lake = {"theorem_ok": False, "reason": type(exc).__name__}
                compile_cache[cache_key] = lake
            candidate["lake_ok"] = bool(lake.get("theorem_ok", lake.get("ok", False)))
            candidate["lake_tokens"] = int(lake.get("token_count") or candidate.get("n_tokens") or 0)
            candidate["lake_body_tokens"] = int(
                lake.get("body_token_count")
                or candidate.get("body_tokens")
                or candidate.get("lake_tokens")
                or candidate.get("n_tokens")
                or 0
            )
            candidate["verifier_reward"] = 1.0 if candidate["lake_ok"] else 0.0
    source_tokens = _token_count(source)
    source_body_tokens = proof_body_token_count(source)
    source_ops = len(_canonical_ops(base_ir))
    fuzzy_scores = dict(fuzzy_result.get("candidate_rewards") or {})
    for idx in current_order:
        candidate = variations[idx]
        candidate["source_tokens"] = source_tokens
        candidate["source_body_tokens"] = source_body_tokens
        candidate["source_ops"] = source_ops
        candidate["ir_ops"] = len(_canonical_ops(candidate.get("ir") or {}))
        candidate["minimality_reward"] = minimality_score(
            candidate,
            reference_tokens=source_body_tokens,
            reference_ops=source_ops,
        )
        if type_choice == f"v{idx}":
            candidate["typesafe_reward"] = type_reward
        elif f"v{idx}" in type_scores:
            try:
                candidate["typesafe_reward"] = max(0.0, min(1.0, float(type_scores[f"v{idx}"])))
            except (TypeError, ValueError):
                candidate["typesafe_reward"] = None
        candidate["fuzzy_prover_reward"] = _clip01(fuzzy_scores.get(f"v{idx}")) if f"v{idx}" in fuzzy_scores else None
        scored = score_candidate(
            candidate,
            typesafe_reward=candidate.get("typesafe_reward"),
            fuzzy_prover_reward=candidate.get("fuzzy_prover_reward"),
            minimality_reward=candidate.get("minimality_reward"),
        )
        candidate.update(scored)
    eligible = [variations[idx] for idx in current_order if compile_fn is None or variations[idx].get("lake_ok")]
    ranked_candidates = eligible or [variations[idx] for idx in current_order]
    if compile_fn is not None and eligible:
        # This is the Arena objective: once candidates are verified, proof
        # body length is the primary key.  Soft semantic/TypeSafe rewards are
        # tie-breakers and can never make a longer proof beat a shorter one.
        winner = min(
            ranked_candidates,
            key=lambda row: (
                int(row.get("lake_body_tokens") or row.get("body_tokens") or row.get("lake_tokens") or row.get("n_tokens") or 10**9),
                -float(row.get("reward") or 0.0),
                int(row.get("variation") or 0),
            ),
        )
    else:
        winner = max(
            ranked_candidates,
            key=lambda row: (
                float(row.get("reward") or 0.0),
                -int(row.get("lake_body_tokens") or row.get("body_tokens") or row.get("lake_tokens") or row.get("n_tokens") or 10**9),
            ),
        )
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
    lake_ok = None if compile_fn is None else bool(winner.get("lake_ok"))
    if compile_fn is not None and not eligible:
        winner["admission"] = "rejected"

    training_report: dict[str, Any] = {}
    if train:
        try:
            from .autoencoder_training import AutoencoderConfig, LeanIRAutoencoder, coerce_training_example, loss_for_example

            store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
            model = LeanIRAutoencoder.from_dict(store.get("training_state"), config=AutoencoderConfig())
            example = coerce_training_example({"text": source, "ir": base_ir, "problem": problem})
            prior_nca = nca_feedback_for_example(memory, example, candidate=winner)
            training_report = model.train_batch(
                [example],
                rewards={example.sample_id: float(winner.get("reward") or 0.0)},
                nca_rewards={example.sample_id: prior_nca.reward} if prior_nca.active else None,
            )
            training_report["loss"] = loss_for_example(
                model,
                example,
                predicted_ir=winner.get("ir") if isinstance(winner.get("ir"), Mapping) else None,
                verifier_reward=winner.get("verifier_reward"),
                typesafe_reward=winner.get("typesafe_reward"),
                fuzzy_prover_reward=winner.get("fuzzy_prover_reward"),
                nca_memory=memory,
                minimality_reward=winner.get("minimality_reward"),
            ).to_dict()
            store["training_state"] = model.to_dict()
            winner["model_step"] = model.step
        except Exception as exc:
            training_report = {"ok": False, "reason": type(exc).__name__}
    try:
        from .autoencoder_training import record_autoencoder_nca_feedback

        record_autoencoder_nca_feedback(
            memory,
            problem=problem,
            reward=float(winner.get("reward") or 0.0),
            theorem_ok=lake_ok,
            typesafe_reward=winner.get("typesafe_reward"),
            tokens=int(
                winner.get("lake_body_tokens")
                or winner.get("body_tokens")
                or winner.get("lake_tokens")
                or winner.get("n_tokens")
                or 0
            ),
            candidate={
                "id": f"v{winner.get('variation', 0)}",
                "ir_digest": hashlib.sha256(
                    json.dumps(winner.get("ir") or {}, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest(),
                "n_tokens": winner.get("n_tokens"),
            },
        )
    except Exception:
        pass
    store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
    batch = list(store.get("batch") or [])
    from jevops.outer import head_chars, tail_seq

    batch.append(
        {
            "problem": problem,
            "cosine_m": int(winner.get("cosine_m") or 0),
            "ce_m": int(winner.get("ce_m") or 0),
            "ir_cosine_m": int(winner.get("ir_cosine_m") or 0),
            "ir_ce_m": int(winner.get("ir_ce_m") or 0),
            "n_tokens": int(
                winner.get("lake_body_tokens")
                or winner.get("body_tokens")
                or winner.get("n_tokens")
                or 0
            ),
            "lean": head_chars(winner.get("lean"), 400),
            "mu": list(winner.get("mu") or []),
            "used_jev": bool(ranked.get("used_jev")),
            "reward": float(winner.get("reward") or 0.0),
            "lake_ok": winner.get("lake_ok"),
            "typesafe_reward": winner.get("typesafe_reward"),
        }
    )
    store["batch"] = tail_seq(batch, BATCH_MAX)
    if winner.get("lake_ok") or compile_fn is None:
        code = list(store.get("codebook") or [])
        code.append(
            {
                "mu": list(encoded["mu"]),
                "lean": str(winner.get("lean") or ""),
                "n_tokens": int(
                    winner.get("lake_body_tokens")
                    or winner.get("body_tokens")
                    or winner.get("n_tokens")
                    or 0
                ),
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
        "n_tokens": int(
            winner.get("lake_body_tokens")
            or winner.get("body_tokens")
            or winner.get("n_tokens")
            or 0
        ),
        "body_tokens": int(
            winner.get("lake_body_tokens")
            or winner.get("body_tokens")
            or winner.get("n_tokens")
            or 0
        ),
        "lake_tokens": winner.get("lake_tokens"),
        "lean": winner.get("lean"),
        "lake_ok": winner.get("lake_ok"),
        "reward": float(winner.get("reward") or 0.0),
        "admission": winner.get("admission") or ("verified" if lake_ok else "unverified"),
        "typesafe": type_result,
        "fuzzy_prover": fuzzy_result,
        "minimality_reward": float(winner.get("minimality_reward") or 0.0),
        "source_tokens": source_tokens,
        "source_body_tokens": source_body_tokens,
        "source_ops": source_ops,
        "training": training_report,
        "jev": {k: ranked[k] for k in ranked if k != "best"},
        "datasets": winner.get("datasets"),
        "ir": winner.get("ir"),
        "ir_cosine_m": int(winner.get("ir_cosine_m") or 0),
        "ir_ce_m": int(winner.get("ir_ce_m") or 0),
        "gold": False,
        "legal_ir": False,
        "functional_lean": True,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
        "loss": "jev_batch" if ranked.get("used_jev") else "reconstruction",
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
    typesafe_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    fuzzy_prover_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
) -> dict[str, Any]:
    source = str(text or tactics or problem or "")
    text_stem = str(stem or "").lower()
    # Autoencoder candidates must be decoded from the current source IR.  The
    # codebook remains an explicit warm-start API, never a silent source-copy
    # or cross-problem theorem retrieval path.
    force_ir = True
    out = teach_roundtrip(
        memory,
        source,
        tactics=tactics,
        problem=problem,
        jev_fn=jev_fn,
        compile_fn=compile_fn,
        rng=rng,
        n_variations=N_VARIATIONS,
        force_ir=force_ir,
        typesafe_fn=typesafe_fn,
        fuzzy_prover_fn=fuzzy_prover_fn,
    )
    if "lean_ir" in text_stem:
        out["kind"] = "port_lean_ir"
    elif "vae" in text_stem:
        out["kind"] = "port_vae"
    return out


def refactor_smallest(
    memory: dict[str, Any],
    text: str,
    *,
    problem: str = "",
    compile_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    typesafe_client: Any = None,
    typesafe_timeout: float = 45.0,
    typesafe_fn: Optional[Callable[..., Mapping[str, Any]]] = None,
    rng: Optional[random.Random] = None,
    n_variations: int = N_VARIATIONS,
    train: bool = True,
) -> dict[str, Any]:
    """Run the proof-preserving smallest-candidate autoencoder loop.

    TypeSafe receives only bounded IR/metric summaries.  It can improve
    fuzzy candidate ranking, but Lake remains the hard gate and no candidate
    is described as verified unless ``compile_fn`` says so.
    """

    from .autoencoder_training import typesafe_fuzzy_prove

    def fuzzy_adapter(**kwargs: Any) -> Mapping[str, Any]:
        return typesafe_fuzzy_prove(
            str(kwargs.get("problem") or problem),
            list(kwargs.get("variations") or ()),
            client=typesafe_client,
            timeout=typesafe_timeout,
            goal=str(kwargs.get("goal") or text),
        )

    return teach_roundtrip(
        memory,
        text,
        problem=problem,
        compile_fn=compile_fn,
        typesafe_fn=typesafe_fn,
        fuzzy_prover_fn=fuzzy_adapter,
        rng=rng,
        n_variations=n_variations,
        force_ir=True,
        train=train,
    )


# The training implementation lives in a separate module so deployments that
# only need the deterministic parser do not pay import-time costs.  Re-export
# the public contract here to keep ``jevops.autoencoder`` the single stable
# integration surface.
from .autoencoder_training import (  # noqa: E402  (intentional late import)
    AutoencoderConfig,
    CanaryManifest,
    CANARY_SCHEMA,
    MODEL_SCHEMA,
    LeanIRAutoencoder,
    LossBreakdown,
    NCAFeedback,
    TrainingExample,
    build_canary_manifest,
    canary_gate,
    coerce_training_example,
    evaluate_frozen_holdout,
    evaluate_model,
    evaluate_stream_split,
    learning_rate_for_step,
    loss_for_example,
    merge_model_states,
    minimality_score,
    advance_autoencoder_nca,
    nca_feedback_for_example,
    record_autoencoder_nca_feedback,
    score_candidate,
    split_training_examples,
    train_autoencoder,
    train_autoencoder_stream,
    TRAINING_SCHEMA,
    typesafe_fuzzy_prove,
    typesafe_rank_variations,
    validate_canary_manifest,
)
