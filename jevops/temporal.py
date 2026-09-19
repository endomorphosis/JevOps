#!/usr/bin/env python3
"""Hawkes, CRF, submodular CALL-sets, delayed bandit, tape conv/DFT milles.

Jobs the rest of the catalog does not cover. Integer milles. Jev does not
write Lean. Lake is the oracle. Never docker0. Not Arena scores.


TypeSafe/JevOps kernel primitive. Implementations (Lean lake, LRA board, portable folds) live outside this package. Jev does not write Lean. Never docker0."""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

MILLE = 1000
EXTRA_STEMS = (
    "hawkes",
    "crf",
    "submodular",
    "set_cover",
    "delayed_bandit",
    "delay_bandit",
    "tape_conv",
    "tape_fft",
)
# cos(2π k / 7) milles for tape DFT (WINDOW=7)
COS7 = (1000, 623, -223, -901, -901, -223, 623)
SIN7 = (0, 782, 975, 434, -434, -975, -782)
KERNEL = (1, 2, 3, 2, 1)


def is_extra_stem(stem: str) -> bool:
    text = str(stem or "").lower().replace("port_", "")
    return any(tag in text for tag in EXTRA_STEMS)


def _clip(value: int, lo: int = 0, hi: int = 10**9) -> int:
    return max(lo, min(hi, int(value)))


def _stem(kind: str) -> str:
    text = str(kind or "")
    if text.startswith("port_"):
        text = text[len("port_") :]
    return text.split("_pipeline")[0]


def _bias(memory: dict[str, Any], ranked: list[str], *, kind: str, **extra: Any) -> dict[str, Any]:
    if ranked:
        memory.setdefault("nca", {})["pipeline_bias"] = ranked
    out = {
        "ok": True,
        "kind": kind,
        "ranked": ranked,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }
    out.update(extra)
    return out


def _events(memory: Mapping[str, Any]) -> list[tuple[str, int]]:
    """(stem, t) from successes then failures; t is list index as time."""

    out: list[tuple[str, int]] = []
    t = 0
    for item in list(memory.get("successes") or []) + list(memory.get("failures") or []):
        stem = _stem(str(item.get("kind") or ""))
        if not stem:
            continue
        t += 1
        stamp = int(item.get("t") or item.get("tick") or t)
        out.append((stem, stamp))
    return out


def call_hawkes(memory: dict[str, Any], *, now: int = 0) -> dict[str, Any]:
    """Mille intensity λ = μ + Σ α/(1+βΔt). Recency, not just Beta counts."""

    mu, alpha, beta = 50, 400, 1
    events = _events(memory)
    t_now = int(now) or (max((t for _s, t in events), default=0) + 1)
    lam: dict[str, int] = {}
    for stem, t_i in events:
        dt = max(0, t_now - t_i)
        bump = (alpha * MILLE) // max(1, 1 + beta * dt)
        lam[stem] = lam.get(stem, mu) + bump
    ranked = sorted(lam, key=lambda s: (-lam[s], s))
    memory.setdefault("nca", {})["hawkes"] = {"lambda_m": lam, "integer": True}
    return _bias(memory, ranked, kind="port_hawkes", n_events=len(events))


def call_crf(memory: dict[str, Any], *, tactics: str = "") -> dict[str, Any]:
    """Linear-chain Viterbi on tactic heads (unary + milles bigrams)."""

    from jevops import more_rankers as lra_more

    heads = lra_more._line_heads(tactics)
    markov = lra_more.call_markov(memory, tactics=tactics)
    trans = dict(((memory.get("nca") or {}).get("markov") or {}).get("trans_m") or {})
    vocab = sorted({h for h in heads} | {k for row in trans.values() for k in row} | set(trans))
    if not heads or not vocab:
        return {"ok": True, "reason": "no_heads", "kind": "port_crf", "writes_lean": False, "integer": True, "path": []}
    start = dict(((memory.get("nca") or {}).get("markov") or {}).get("start") or {})
    tot_s = sum(start.values()) or 1
    unary0 = {tag: (start.get(tag, 0) * MILLE) // tot_s for tag in vocab}

    def trans_m(prev: str, nxt: str) -> int:
        return int((trans.get(prev) or {}).get(nxt) or 1)

    # Viterbi milles (log-approx = scores themselves)
    prev_sc = {tag: unary0.get(tag, 0) + (MILLE if tag == heads[0] else 0) for tag in vocab}
    prev_bp: dict[str, list[str]] = {tag: [tag] for tag in vocab}
    for obs in heads[1:]:
        cur_sc: dict[str, int] = {}
        cur_bp: dict[str, list[str]] = {}
        for tag in vocab:
            emit = MILLE if tag == obs else 0
            best_p, best_s = vocab[0], -10**9
            for ptag in vocab:
                s = prev_sc[ptag] + trans_m(ptag, tag) + emit
                if s > best_s:
                    best_s, best_p = s, ptag
            cur_sc[tag] = best_s
            cur_bp[tag] = list(prev_bp[best_p]) + [tag]
        prev_sc, prev_bp = cur_sc, cur_bp
    best_tag = max(prev_sc, key=lambda t: (prev_sc[t], t))
    path = prev_bp[best_tag]
    memory.setdefault("nca", {})["crf"] = {"path": path, "integer": True}
    return _bias(memory, path, kind="port_crf", n_heads=len(heads), **{"path": path})


def call_submodular(memory: dict[str, Any], *, tactics: str = "", budget: int = 3) -> dict[str, Any]:
    """Greedy set cover of residuals under a CALL budget."""

    from jevops import hooks

    residual_of = dict(hooks.call("skill_residual_map", default=None) or {})
    if not residual_of:
        port = hooks.try_import("portable_rewrites")
        residual_of = dict(getattr(port, "SKILL_RESIDUAL", {}) or {})
    present = set()
    try:
        analyze = hooks.resolve("analyze_residuals", "portable_rewrites", "analyze_residuals")
        counts = analyze(tactics or "") if analyze else {}
        present = {k for k, v in counts.items() if int(v or 0) > 0}
    except Exception:
        present = set()
    if not present:
        present = set(residual_of.values())
    inverse: dict[str, list[str]] = {}
    for stem, res in residual_of.items():
        inverse.setdefault(res, []).append(stem)
    uncovered = set(present)
    picked: list[str] = []
    k = max(1, int(budget))
    while uncovered and len(picked) < k:
        best_stem, best_gain = "", 0
        for res in list(uncovered):
            for stem in inverse.get(res, ()):
                gain = 1 if res in uncovered else 0
                # cover all residuals this stem hits
                cover = {r for r, stems in inverse.items() if stem in stems and r in uncovered}
                gain = len(cover)
                if gain > best_gain or (gain == best_gain and stem < best_stem):
                    best_gain, best_stem = gain, stem
        if best_gain <= 0 or not best_stem:
            break
        picked.append(best_stem)
        for res, stems in inverse.items():
            if best_stem in stems:
                uncovered.discard(res)
    memory.setdefault("nca", {})["submodular"] = {"picked": picked, "budget": k, "integer": True}
    return _bias(memory, picked, kind="port_submodular", n_uncovered=len(uncovered), budget=k)


def call_delayed_bandit(memory: dict[str, Any]) -> dict[str, Any]:
    """UCB milles with pending (unresolved lake) pulls. Thompson assumes instant reward."""

    store = memory.setdefault("nca", {}).setdefault("delayed_bandit", {})
    events = _events(memory)
    t = 0
    for stem, _t in events:
        row = dict(store.get(stem) or {"n": 0, "reward_m": 0, "pending": 0})
        # successes listed first in _events
        t += 1
        ok = t <= len(memory.get("successes") or [])
        pending = int(row.get("pending") or 0)
        if pending > 0:
            pending -= 1
        n = int(row.get("n") or 0) + 1
        reward = int(row.get("reward_m") or 0) + (MILLE if ok else 0)
        store[stem] = {"n": n, "reward_m": reward, "pending": pending}
    # one pending pull on the current greedy arm so delay is visible
    T = sum(int((store.get(s) or {}).get("n") or 0) for s in store) or 1
    ucb: dict[str, int] = {}
    logt = int(math.isqrt(max(0, int(math.log(T + 1) * MILLE * MILLE)))) if T else MILLE
    # milles UCB: mean_m + isqrt(MILLE * MILLE * log(T) / (n+pending+1))
    log_m = 0
    x = T
    while x > 1:
        x //= 2
        log_m += 693  # ln(2)*1000
    for stem, row in store.items():
        n = int(row.get("n") or 0)
        pend = int(row.get("pending") or 0)
        den = max(1, n + pend)
        mean_m = int(row.get("reward_m") or 0) // max(1, n)
        bonus = int(math.isqrt(max(0, (MILLE * log_m) // den)))
        ucb[stem] = mean_m + bonus
    if ucb:
        arm = max(ucb, key=lambda s: (ucb[s], s))
        store[arm]["pending"] = int(store[arm].get("pending") or 0) + 1
    ranked = sorted(ucb, key=lambda s: (-ucb[s], s))
    store["_ucb"] = ucb
    return _bias(memory, ranked, kind="port_delayed_bandit", T=T)


def _tape_window_m(memory: Mapping[str, Any]) -> list[int]:
    try:
        from jevops import tape as lra_tape

        tape = lra_tape.Tape.from_memory(memory)
        win = tape.window()
        out = []
        for cell in win:
            try:
                e = float(cell.get("energy") or 0)
            except (TypeError, ValueError):
                e = 0.0
            out.append(int(e * MILLE) if e <= 2 else int(e))
        return out or [0] * 7
    except Exception:
        cells = list(((memory.get("nca") or {}).get("tape") or {}).get("cells") or [])
        if not cells:
            return [0] * 7
        return [
            int(float(c.get("energy") or 0) * MILLE) if float(c.get("energy") or 0) <= 2 else int(c.get("energy") or 0)
            for c in cells[-7:]
        ]


def call_tape_conv(memory: dict[str, Any], *, fft: bool = False) -> dict[str, Any]:
    """Integer conv on the tape window; optional 7-point DFT milles."""

    x = _tape_window_m(memory)
    if len(x) < 7:
        x = x + [0] * (7 - len(x))
    x = x[:7]
    k = KERNEL
    conv = []
    for i in range(7):
        acc = 0
        for j, kv in enumerate(k):
            idx = i + j - 2
            if 0 <= idx < 7:
                acc += kv * x[idx]
        conv.append(acc)
    spec: list[int] = []
    if fft:
        for freq in range(7):
            re = sum(x[n] * COS7[(freq * n) % 7] for n in range(7)) // MILLE
            im = sum(x[n] * SIN7[(freq * n) % 7] for n in range(7)) // MILLE
            spec.append(int(math.isqrt(max(0, re * re + im * im))))
    peak = max(range(7), key=lambda i: conv[i])
    memory.setdefault("nca", {})["tape_conv"] = {"conv": conv, "spec": spec, "peak": peak, "integer": True}
    return {
        "ok": True,
        "kind": "port_tape_fft" if fft else "port_tape_conv",
        "conv": conv,
        "spec": spec,
        "peak": peak,
        "writes_lean": False,
        "integer": True,
        "called_docker0": False,
    }


def call_extra(
    stem: str,
    *,
    memory: dict[str, Any],
    tactics: str = "",
    problem: str = "",
) -> dict[str, Any]:
    _ = problem
    text = str(stem or "").lower()
    if "hawkes" in text:
        return call_hawkes(memory)
    if "crf" in text:
        return call_crf(memory, tactics=tactics)
    if "submodular" in text or "set_cover" in text:
        return call_submodular(memory, tactics=tactics)
    if "delay" in text:
        return call_delayed_bandit(memory)
    if "fft" in text:
        return call_tape_conv(memory, fft=True)
    if "conv" in text or "tape" in text:
        return call_tape_conv(memory, fft=False)
    return {"ok": False, "reason": "unknown_extra", "stem": stem, "writes_lean": False}
