"""Bounded JeV feedback and exact finite-edit expected-utility gradients.

No provider is selected and no Lean is admitted here. Receipt hashes bind local
observations to a request; they are not signatures or proof of scorer identity.
The caller owns the environment fingerprint, training split and scorer setup.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

REQUEST_SCHEMA = "jevops-jev-edit-request/v1"
FEEDBACK_SCHEMA = "jevops-jev-edit-feedback/v1"
MAX_REQUEST_CHARS = 262_144


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"invalid {name}")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(f"invalid {name}") from exc
    if not math.isfinite(result):
        raise ValueError(f"nonfinite {name}")
    return result


@dataclass(frozen=True)
class JeVFeedbackSpec:
    """Pinned caller configuration; utilities are ordinal, not probabilities."""

    context_sha256: str
    scorer_id: str
    rubric_id: str
    utilities: Mapping[str, float]

    def __post_init__(self) -> None:
        if (not isinstance(self.context_sha256, str) or len(self.context_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.context_sha256)):
            raise ValueError("context_sha256 must fingerprint the pinned environment")
        for value in (self.scorer_id, self.rubric_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError("scorer and rubric IDs must be nonempty and bounded")
        if not isinstance(self.utilities, Mapping) or not 1 <= len(self.utilities) <= 32:
            raise ValueError("invalid utility rubric")
        utilities = {}
        for label, raw in self.utilities.items():
            if not isinstance(label, str) or not label or len(label) > 32:
                raise ValueError("invalid rubric label")
            utility = _number(raw, "utility")
            if not -1 <= utility <= 1:
                raise ValueError("utility must be between -1 and 1")
            utilities[label] = utility
        object.__setattr__(self, "utilities", MappingProxyType(utilities))

    def to_dict(self) -> dict[str, Any]:
        return {"context_sha256": self.context_sha256, "scorer_id": self.scorer_id,
                "rubric_id": self.rubric_id, "utilities": dict(self.utilities)}


def make_request(source: str, templates: list[dict[str, Any]], weights: Mapping[str, float], *,
                 spec: JeVFeedbackSpec, split: str, temperature: float, step: int) -> dict[str, Any]:
    """Build a complete, bounded, training-only request without changing state."""
    import textwrap
    from .rewrite_policy import body_of, choices, validate_templates

    if split != "train":
        raise ValueError("JeV policy feedback is training-only")
    if not isinstance(source, str) or not source or len(source) > 65_536:
        raise ValueError("invalid or oversized source")
    prefix, _ = body_of(source)
    if not prefix:
        raise ValueError("source requires a theorem envelope")
    bank = validate_templates(templates)
    rows = choices(source, bank)
    # Validate the exact policy domain before calling an external scorer.
    expected_utility_gradient(weights, rows, [0.0] * len(rows), temperature=temperature)
    variations = []
    for index, row in enumerate(rows):
        lean = source if index == 0 else prefix + "\n" + textwrap.indent(row["body"], "  ")
        identity = {"source": source, "context_sha256": spec.context_sha256, "lean": lean}
        variations.append({"id": digest(identity), "lean": lean,
                           "rule_id": row["rule_id"], "start": row["start"]})
    if len({row["id"] for row in variations}) != len(variations):
        raise ValueError("duplicate rendered candidates")
    if len(source) + sum(len(row["lean"]) for row in variations) > MAX_REQUEST_CHARS:
        raise ValueError("candidate request exceeds text budget")
    request = {"schema": REQUEST_SCHEMA, "task": "lean_edit_surrogate_utility", "split": split,
               "source": source, "spec": spec.to_dict(), "grammar_sha256": digest(bank),
               "policy_sha256": digest({"weights": dict(weights), "temperature": temperature, "step": step}),
               "variations": variations, "authority": "surrogate_only"}
    return {**request, "request_id": digest(request)}


def _validate_request(request: Mapping[str, Any]) -> None:
    if (request.get("schema") != REQUEST_SCHEMA or request.get("split") != "train"
            or request.get("request_id") != digest({k: v for k, v in request.items() if k != "request_id"})):
        raise ValueError("invalid request binding")


def bind_feedback(request: Mapping[str, Any], response: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a local scorer response, failing closed on incomplete/invalid scores.

    Response scores use candidate IDs and rubric labels. ``abstain`` is explicit;
    optional ``noul`` is preserved, not interpreted as a correctness probability.
    Choice-only responses are not silently converted to cardinal utilities.
    """
    _validate_request(request)
    ids = [row["id"] for row in request["variations"]]
    receipt: dict[str, Any] = {"schema": FEEDBACK_SCHEMA, "request_id": request["request_id"],
                             "scorer_id": request["spec"]["scorer_id"], "status": "skipped",
                             "reason": "malformed_feedback", "scores": {}, "score_coverage": 0.0,
                             "noul": None, "authority": "surrogate_only"}
    if isinstance(response, Mapping):
        try:
            if response.get("request_id", request["request_id"]) != request["request_id"]:
                raise ValueError("response_request_mismatch")
            if response.get("scorer_id", receipt["scorer_id"]) != receipt["scorer_id"]:
                raise ValueError("response_scorer_mismatch")
            if type(response.get("abstain", False)) is not bool:
                raise ValueError("invalid_abstention")
            if response.get("noul") is not None:
                noul = _number(response["noul"], "noul")
                if not 0 <= noul <= 1:
                    raise ValueError("invalid_noul")
                receipt["noul"] = noul
            if response.get("abstain", False):
                receipt.update(status="abstained", reason="scorer_abstained")
            else:
                scores = response.get("scores")
                if not isinstance(scores, Mapping) or not set(scores) <= set(ids):
                    raise ValueError("invalid_score_ids")
                receipt["score_coverage"] = len(scores) / len(ids)
                if set(scores) != set(ids):
                    raise ValueError("incomplete_scores")
                labels = {}
                for candidate_id, raw in scores.items():
                    if type(raw) is str:
                        label = raw
                    else:
                        value = _number(raw, "score")
                        if not value.is_integer():
                            raise ValueError("nonordinal_score")
                        label = str(int(value))
                    if label not in request["spec"]["utilities"]:
                        raise ValueError("score_outside_rubric")
                    labels[candidate_id] = label
                receipt.update(status="scored", reason="complete_scores", scores=labels)
        except (ValueError, TypeError, OverflowError) as exc:
            receipt["reason"] = str(exc) if isinstance(exc, ValueError) else "malformed_feedback"
    return {**receipt, "feedback_id": digest(receipt)}


def collect_feedback(request: Mapping[str, Any], scorer: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> dict[str, Any]:
    """Call only the injected scorer, isolating it from the caller's request."""
    _validate_request(request)
    try:
        response = scorer(json.loads(json.dumps(request, allow_nan=False)))
    except Exception:
        # Do not expose provider exception messages, which may contain secrets.
        receipt = bind_feedback(request, {})
        receipt["reason"] = "scorer_error"
        receipt["feedback_id"] = digest({k: v for k, v in receipt.items() if k != "feedback_id"})
        return receipt
    return bind_feedback(request, response)


def feedback_utilities(request: Mapping[str, Any], receipt: Mapping[str, Any]) -> list[float]:
    """Validate a receipt against a freshly reconstructed local request."""
    _validate_request(request)
    if not isinstance(receipt, Mapping) or receipt.get("schema") != FEEDBACK_SCHEMA:
        raise ValueError("malformed_receipt")
    if (receipt.get("request_id") != request["request_id"]
            or receipt.get("scorer_id") != request["spec"]["scorer_id"]):
        raise ValueError("stale_or_mismatched_feedback")
    if receipt.get("feedback_id") != digest({k: v for k, v in receipt.items() if k != "feedback_id"}):
        raise ValueError("invalid_receipt_digest")
    if receipt.get("status") != "scored":
        raise ValueError("feedback_not_scored")
    canonical = bind_feedback(request, {"scores": receipt.get("scores"), "noul": receipt.get("noul")})
    if dict(receipt) != canonical:
        raise ValueError("malformed_scored_receipt")
    return [request["spec"]["utilities"][receipt["scores"][row["id"]]] for row in request["variations"]]


def expected_utility_gradient(weights: Mapping[str, float], rows: Sequence[Mapping[str, Any]],
                              utilities: Sequence[float], *, temperature: float = 1.0,
                              reference_weights: Mapping[str, float] | None = None,
                              kl_weight: float = 0.0) -> dict[str, Any]:
    """Exact gradient of -E[utility] + beta KL(policy || frozen reference).

    Utilities and reference parameters are constants. This is neither a gradient
    through JeV nor through Lean; it differentiates finite edit probabilities.
    """
    from .rewrite_policy import MAX_CHOICES, _logits

    temperature, kl_weight = _number(temperature, "temperature"), _number(kl_weight, "kl_weight")
    if temperature <= 0 or not 0 <= kl_weight <= 1 or (kl_weight and reference_weights is None):
        raise ValueError("invalid temperature or reference KL configuration")
    if not 1 <= len(rows) <= MAX_CHOICES or len(utilities) != len(rows):
        raise ValueError("invalid utility coverage")
    rewards = [_number(value, "utility") for value in utilities]
    if any(not -1 <= value <= 1 for value in rewards):
        raise ValueError("utility must be between -1 and 1")
    for mapping in (weights, reference_weights if reference_weights is not None else {}):
        if not isinstance(mapping, Mapping) or len(mapping) > 8192:
            raise ValueError("invalid policy weights")
        for key, value in mapping.items():
            if not isinstance(key, str):
                raise ValueError("invalid policy feature key")
            _number(value, "weight")
    for row in rows:
        if not isinstance(row.get("features"), Mapping) or len(row["features"]) > 128:
            raise ValueError("invalid edit features")
        for key, value in row["features"].items():
            if not isinstance(key, str):
                raise ValueError("invalid edit feature key")
            _number(value, "feature")

    def log_probs(params: Mapping[str, float]) -> list[float]:
        logits = _logits(params, rows, temperature)
        peak = max(logits)
        shifted = [value - peak for value in logits]
        normalizer = math.log(math.fsum(math.exp(value) for value in shifted))
        result = [value - normalizer for value in shifted]
        if not all(math.isfinite(value) for value in result):
            raise ValueError("nonfinite log probabilities")
        return result

    logs = log_probs(weights)
    probs = [math.exp(value) for value in logs]
    expected = rewards[0] if len(set(rewards)) == 1 else math.fsum(p*r for p, r in zip(probs, rewards))
    ratios = ([a-b for a, b in zip(logs, log_probs(reference_weights))]
              if kl_weight else [0.0] * len(rows))
    kl = math.fsum(p*r for p, r in zip(probs, ratios))
    gradient: dict[str, float] = {}
    for p, reward, ratio, row in zip(probs, rewards, ratios, rows):
        delta = p * (expected - reward + kl_weight * (ratio - kl)) / temperature
        for key, feature in row["features"].items():
            gradient[key] = gradient.get(key, 0.0) + delta * feature
    total = -expected + kl_weight * kl
    if not all(math.isfinite(v) for v in [total, *gradient.values()]):
        raise ValueError("nonfinite surrogate objective")
    return {"total": total, "expected_utility": expected, "surrogate_loss": -expected,
            "reference_kl": kl, "gradient": gradient, "probabilities": probs,
            "choice_count": len(rows)}
