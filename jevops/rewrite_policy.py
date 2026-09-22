"""Bounded learned span edits, not a Lean parser or proof authority.

Templates are mined from training pairs only. Literal syntax is retained and
local identifiers become copy slots. A sparse softmax chooses identity or a
template/location; zero weights choose identity. Inference never sees a target,
runs a tactic search, or compiles alternatives. Every emitted proof needs Lean.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re
import textwrap
from typing import Any, Mapping, Sequence

SCHEMA = "jevops-learned-span-edits/v1"
MAX_RULES, MAX_CHOICES, MAX_LINES, MAX_SPAN = 64, 64, 256, 8
NAME = r"[^\W\d][\w']*"
IDENT = re.compile(NAME, re.UNICODE)
FORBIDDEN = re.compile(r"\b(?:sorry|admit|axiom|unsafe|run_tac|elab|macro|syntax|set_option|"
                       r"theorem|lemma|def|instance|attribute|namespace|section|end|import)\b|#|\x00")
RESERVED = frozenset("by have let exact apply assumption rfl rw simp simpa only at using intro intros "
                      "case cases induction with constructor obtain show from fun in if then else "
                      "True False Prop Type Sort Nat Int Bool classical trivial decide skip grind".split())


def body_of(source: str) -> tuple[str, str]:
    from .autoencoder import _LEAN_HEADER

    match = _LEAN_HEADER.search(source)
    prefix, body = (source[:match.end()], source[match.end():]) if match else ("", source)
    return prefix, textwrap.dedent(body).strip("\n").rstrip()


def body_from_ir(ir: Mapping[str, Any]) -> str:
    from .autoencoder import decode_lean_ir

    return body_of(decode_lean_ir(ir))[1]


def supported(body: str) -> bool:
    return (len(body) <= 32_768 and len(body.splitlines()) <= MAX_LINES and not FORBIDDEN.search(body)
            and not any(s in body for s in ('--', '/-', '-/', '"', '`', '\t', '$')))


def local_names(source: str) -> set[str]:
    """Lexical copy eligibility only; not elaborated scope/type information."""
    prefix, body = body_of(source)
    names = set()
    for match in re.finditer(r"[({]\s*([^:(){}\[\]]+)\s*:", prefix):
        names.update(IDENT.findall(match[1]))
    for line in body.splitlines():
        line = line.strip()
        binding = re.match(r"(?:have|let)\s+(" + NAME + r")\b", line)
        if binding:
            names.add(binding[1])
        for split in re.finditer(r"\bby_cases\s+(" + NAME + r")\s*:", line):
            names.add(split[1])
        introduced = re.match(r"(?:intro|intros|rename_i)\s+([^;]+)$", line)
        branch = re.match(r"case\s+" + NAME + r"\s+(.*?)\s*=>", line)
        if introduced or branch:
            names.update(IDENT.findall((introduced or branch)[1]))
    return names - RESERVED


def _parts(text: str, slots: Mapping[str, int]) -> list[str | int]:
    parts: list[str | int] = []
    cursor = 0
    for match in IDENT.finditer(text):
        if match[0] not in slots:
            continue
        parts.extend((text[cursor:match.start()], slots[match[0]]))
        cursor = match.end()
    parts.append(text[cursor:])
    return parts


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def mine_template(source: str, target_body: str) -> dict[str, Any] | None:
    """Extract one bounded changed span; never mine from evaluation labels."""
    _, before = body_of(source)
    after = textwrap.dedent(target_body).strip("\n").rstrip()
    if not supported(before) or not supported(after) or before == after:
        return None
    a, b = before.splitlines(), after.splitlines()
    left = 0
    while left < min(len(a), len(b)) and a[left] == b[left]:
        left += 1
    right = 0
    while right < min(len(a), len(b)) - left and a[-1-right] == b[-1-right]:
        right += 1
    aa, bb = a[left:len(a)-right], b[left:len(b)-right]
    if not aa or max(len(aa), len(bb)) > MAX_SPAN:
        return None  # Pure insertions and large structural changes abstain.
    nonempty = [line for line in aa if line.strip()]
    if not nonempty:
        return None
    indent = min(len(line) - len(line.lstrip()) for line in nonempty)
    if any(line.strip() and len(line)-len(line.lstrip()) < indent for line in bb):
        return None
    old = "\n".join(line[indent:] for line in aa)
    new = "\n".join(line[indent:] for line in bb)
    names = local_names(source)
    slots = {name: i for i, name in enumerate(dict.fromkeys(m[0] for m in IDENT.finditer(old) if m[0] in names))}
    if len(slots) > 16 or any(m[0] in names and m[0] not in slots for m in IDENT.finditer(new)):
        return None  # No out-of-span free-local name memorization.
    payload = {"before": _parts(old, slots), "after": _parts(new, slots), "slots": len(slots),
               "lines": len(aa), "scope": "lexical_local_copy_requires_Lean"}
    return {"id": _digest(payload), **payload}


def validate_templates(templates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(templates, list) or len(templates) > MAX_RULES:
        raise ValueError("invalid rewrite template bank")
    out = []
    for raw in templates:
        row = dict(raw)
        if set(row) != {"id", "before", "after", "slots", "lines", "scope"}:
            raise ValueError("invalid rewrite template fields")
        if not isinstance(row["slots"], int) or not 0 <= row["slots"] <= 16:
            raise ValueError("invalid copy slots")
        if not isinstance(row["lines"], int) or not 1 <= row["lines"] <= MAX_SPAN:
            raise ValueError("invalid rewrite span")
        before_slots = set()
        for key in ("before", "after"):
            parts = row[key]
            if not isinstance(parts, list) or not parts or len(parts) > 256:
                raise ValueError("invalid template syntax")
            if any(type(p) not in (str, int) or (type(p) is int and not 0 <= p < row["slots"]) for p in parts):
                raise ValueError("invalid template part")
            text = "".join(p if isinstance(p, str) else "slot" for p in parts)
            if not supported(text) or len(text.splitlines()) > MAX_SPAN:
                raise ValueError("unsafe or oversized template")
            if key == "before":
                before_slots = {p for p in parts if type(p) is int}
                if len(text.splitlines()) != row["lines"]:
                    raise ValueError("inconsistent span length")
            elif not {p for p in parts if type(p) is int} <= before_slots:
                raise ValueError("unbound output copy slot")
        payload = {k: v for k, v in row.items() if k != "id"}
        if row["id"] != _digest(payload) or before_slots != set(range(row["slots"])):
            raise ValueError("template digest/slot mismatch")
        if any(r["id"] == row["id"] for r in out):
            raise ValueError("duplicate rewrite template")
        out.append(row)
    return out


def _pattern(parts: Sequence[str | int]) -> re.Pattern:
    seen, chunks = set(), []
    for part in parts:
        if isinstance(part, str):
            chunks.append(re.escape(part))
        else:
            chunks.append(f"(?P<s{part}>{NAME})" if part not in seen else f"(?P=s{part})")
            seen.add(part)
    return re.compile("".join(chunks))


def choices(source: str, templates: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic applicability enumeration, not solver/teacher search."""
    _, body = body_of(source)
    rows = [{"body": body, "features": {}, "rule_id": None, "start": None}]
    if not supported(body):
        return rows
    lines, names, seen = body.splitlines(), local_names(source), {body}
    for rule in templates:
        pattern = _pattern(rule["before"])
        width = rule["lines"]
        for start in range(len(lines) - width + 1):
            block = lines[start:start+width]
            nonempty = [line for line in block if line.strip()]
            if not nonempty:
                continue
            indent = min(len(line) - len(line.lstrip()) for line in nonempty)
            match = pattern.fullmatch("\n".join(line[indent:] for line in block))
            if match is None or any(value not in names for value in match.groupdict().values()):
                continue
            replacement = "".join(p if isinstance(p, str) else match[f"s{p}"] for p in rule["after"])
            replaced = [" " * indent + line for line in replacement.splitlines()] if replacement else []
            candidate = "\n".join(lines[:start] + replaced + lines[start+width:]).rstrip()
            if not candidate.strip() or candidate in seen:
                continue
            seen.add(candidate)
            previous = lines[start-1].strip().split()[0] if start and lines[start-1].strip() else "bos"
            following = lines[start+width].strip().split()[0] if start+width < len(lines) and lines[start+width].strip() else "eos"
            features = {"bias": 1.0, "first": float(start == 0), "last": float(start+width == len(lines)),
                        "nested": float(indent > 0), "prev:"+previous: 1.0, "next:"+following: 1.0}
            prefix, _ = body_of(source)
            for domain in ("Prop", "Nat", "Int", "Bool", "List", "Fin", "PLift"):
                features["domain:"+domain] = float(bool(re.search(r"\b"+domain+r"\b", prefix)))
            rows.append({"body": candidate, "features": {rule["id"]+"|"+k: v for k, v in features.items()},
                         "rule_id": rule["id"], "start": start})
            if len(rows) >= MAX_CHOICES:
                return rows
    return rows


def _logits(weights: Mapping[str, float], rows: Sequence[Mapping[str, Any]], temperature: float) -> list[float]:
    if not math.isfinite(temperature) or temperature <= 0 or not rows:
        raise ValueError("invalid edit softmax domain")
    logits = [sum(weights.get(k, 0.0)*v for k, v in row["features"].items()) / temperature for row in rows]
    if not all(math.isfinite(value) for value in logits):
        raise ValueError("nonfinite edit logits")
    return logits


def probabilities(weights: Mapping[str, float], rows: Sequence[Mapping[str, Any]], temperature: float = 1.0) -> list[float]:
    logits = _logits(weights, rows, temperature)
    peak = max(logits)
    values = [math.exp(v-peak) for v in logits]
    normalizer = sum(values)
    return [v/normalizer for v in values]


def _cosine_cost(body: str, target: str) -> float:
    from .autoencoder import encode_lean_ir

    def counts(text):
        # A synthetic envelope keeps parser heads distinct from tactic names
        # that occur inside arguments. This is a bag-of-operations diagnostic.
        return Counter(r["op"] for r in encode_lean_ir("theorem editMetric : True := by\n" + textwrap.indent(text, "  "))["ops"])
    a, b = counts(body), counts(target)
    norm = math.sqrt(sum(v*v for v in a.values()) * sum(v*v for v in b.values()))
    return 1.0 - (sum(v*b.get(k, 0) for k, v in a.items())/norm if norm else float(a == b))


def loss_and_gradient(weights: Mapping[str, float], rows: Sequence[Mapping[str, Any]], target: str, *,
                      temperature: float = 1.0, smoothing: float = 0.0,
                      cosine_weight: float = .35) -> dict[str, Any] | None:
    labels = [i for i, row in enumerate(rows) if row["body"] == target]
    if len(labels) != 1:
        return None  # Unsupported targets never become identity labels.
    label = labels[0]
    probs = probabilities(weights, rows, temperature)
    desired = [smoothing/len(rows) + (1-smoothing if i == label else 0) for i in range(len(rows))]
    logits = _logits(weights, rows, temperature)
    peak = max(logits)
    log_normalizer = math.log(sum(math.exp(v-peak) for v in logits))
    ce = sum(y*(log_normalizer + peak-v) for y, v in zip(desired, logits))
    costs = [_cosine_cost(row["body"], target) for row in rows]
    cosine_loss = sum(p*c for p, c in zip(probs, costs))
    gradients: dict[str, float] = {}
    for p, y, cost, row in zip(probs, desired, costs, rows):
        delta = (p-y + cosine_weight*p*(cost-cosine_loss))/temperature
        for key, value in row["features"].items():
            gradients[key] = gradients.get(key, 0.0) + delta*value
    return {"cross_entropy": ce, "expected_cosine_loss": cosine_loss,
            "total": ce + cosine_weight*cosine_loss, "gradient": gradients,
            "label": label, "choice_count": len(rows)}


def decode(source: str, templates: Sequence[Mapping[str, Any]], weights: Mapping[str, float], *,
           max_edits: int = 4, temperature: float = 1.0) -> dict[str, Any]:
    prefix, body = body_of(source)
    trace = []
    seen = {body}
    for _ in range(max(0, min(8, int(max_edits)))):
        current = prefix + "\n" + textwrap.indent(body, "  ") if prefix else body
        rows = choices(current, templates)
        probs = probabilities(weights, rows, temperature)
        # Identity is first and wins ties, including the zero-weights ablation.
        index = max(range(len(rows)), key=lambda i: probs[i])
        if not index or rows[index]["body"] in seen:
            break
        row = rows[index]
        body = row["body"]
        seen.add(body)
        trace.append({"rule_id": row["rule_id"], "start": row["start"],
                      "probability": probs[index], "choices": len(rows)})
    return {"body": body, "trace": trace, "teacher_used": False, "solver_used": False,
            "mode": "learned_span_edits", "authority": "model_proposal_requires_Lean"}
