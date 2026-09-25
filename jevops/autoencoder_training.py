"""Trainable, verifier-gated Lean IR autoencoder primitives.

The original :mod:`jevops.autoencoder` module deliberately stayed small and
dependency free, but it also made an important distinction easy to miss:
cosine and cross-entropy were reported as diagnostics while Jev selected a
candidate.  That is useful for a smoke test, not for training a refactoring
model.  This module supplies the missing training contract without making
PyTorch, Lake, or TypeSafe mandatory dependencies.

The implementation is intentionally sparse and deterministic.  It trains a
hashed-feature encoder and a teacher-forced operation decoder with clipped
SGD.  The same state can be used by an optional vectorized/torch consumer, but
the portable path remains useful in CI and in the JevOps kernel.  Lake is the
only proof authority; TypeSafe/JeV are bounded ranking and reward signals and
can never admit an unverified proof.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping, MutableMapping, Optional, Sequence

if TYPE_CHECKING:
    from .jev_surrogate import JeVFeedbackSpec


TRAINING_SCHEMA = "jevops-lean-ir-autoencoder-training/v2"
MODEL_SCHEMA = "jevops-lean-ir-autoencoder-model/v2"
CANARY_SCHEMA = "jevops-lean-ir-canary-manifest/v2"
FEATURE_BUCKETS = 256
MAX_FEATURE_TOKENS = 512
MAX_EVAL_ROWS = 256
_UNSAFE_TEXT = re.compile(r"\b(?:sorry|admit|unsafe|run_tac|exact\?)\b", re.IGNORECASE)


def _ae() -> Any:
    """Import the compatibility façade lazily to avoid a module cycle."""

    from . import autoencoder

    return autoencoder


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _clip01(value: Any, default: float = 0.0) -> float:
    return max(0.0, min(1.0, _finite(value, default)))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _text_digest(text: str) -> str:
    normalized = " ".join(str(text or "").split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _safe_arg(value: Any, *, max_chars: int = 160) -> str:
    """Keep an IR argument single-line and reject proof-escape constructs."""

    text = " ".join(str(value or "").replace("\x00", " ").split())[:max_chars]
    if not text or _UNSAFE_TEXT.search(text):
        return ""
    # The renderer is not a parser.  Refuse separators that could smuggle a
    # second command into a canonical operation argument.
    if "\n" in text or "\r" in text or ";" in text:
        return ""
    return text


def _operation_vocab() -> tuple[str, ...]:
    return tuple(str(item) for item in getattr(_ae(), "LEAN_IR_OPS", ()))


def _canonical_ops(ir: Mapping[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    vocab = set(_operation_vocab())
    aliases = {"intros": "intro"}
    result: list[tuple[str, tuple[str, ...]]] = []
    for item in ir.get("ops") or ():
        if isinstance(item, Mapping):
            op = str(item.get("op") or "").strip().lower()
            raw_args = item.get("args")
            if raw_args is None and item.get("arg") is not None:
                raw_args = [item.get("arg")]
        else:
            raw = str(item or "").strip()
            parts = raw.split(None, 1)
            op = parts[0].lower() if parts else ""
            raw_args = [parts[1]] if len(parts) > 1 else []
        op = aliases.get(op, op)
        if op not in vocab:
            continue
        if isinstance(raw_args, str):
            raw_args = [raw_args]
        args = tuple(
            arg
            for arg in (_safe_arg(value) for value in (raw_args or ()))
            if arg
        )
        result.append((op, args))
    return tuple(result or (("trivial", ()),))


def _ops_to_ir(source_ir: Mapping[str, Any], ops: Sequence[tuple[str, Sequence[str]]]) -> dict[str, Any]:
    """Copy stable IR metadata while replacing only the operation sequence."""

    operations = [
        {"op": str(op), **({"args": list(args)} if args else {})}
        for op, args in ops
    ]
    # A changed flat sequence must invalidate/project the old script too.
    # Otherwise loss measures selected operations while Lean executes an
    # unchanged source proof, concealing a failed learned edit.
    packed = _ae()._ir_with_ops(source_ir, operations)
    packed["ops_digest"] = _digest(packed["ops"])
    return packed


def _feature_vector(text: str, *, buckets: int = FEATURE_BUCKETS) -> dict[int, float]:
    """Return a bounded signed feature vector suitable for sparse updates."""

    tokens_fn = getattr(_ae(), "_tokens", None)
    tokens = list(tokens_fn(text) if tokens_fn else re.findall(r"[A-Za-z0-9_]+", str(text).lower()))
    tokens = tokens[:MAX_FEATURE_TOKENS]
    atoms = list(tokens)
    atoms.extend(f"{left}::{right}" for left, right in zip(tokens, tokens[1:]))
    if not atoms:
        atoms = ["<empty>"]
    values: dict[int, float] = {}
    scale = 1.0 / math.sqrt(float(max(1, len(atoms))))
    for atom in atoms:
        raw = hashlib.blake2b(atom.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(raw[:4], "big") % max(1, int(buckets))
        sign = 1.0 if raw[4] & 1 else -1.0
        values[bucket] = values.get(bucket, 0.0) + sign * scale
    return values


def _softmax(logits: Mapping[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not logits:
        return {}
    temp = max(1e-6, _finite(temperature, 1.0))
    finite_logits = {str(key): _finite(value) / temp for key, value in logits.items()}
    peak = max(finite_logits.values())
    exp_values = {key: math.exp(max(-60.0, value - peak)) for key, value in finite_logits.items()}
    total = sum(exp_values.values()) or 1.0
    return {key: value / total for key, value in exp_values.items()}


def _sequence_distance(left: Sequence[str], right: Sequence[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, token in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (token != other)))
        previous = current
    return previous[-1]


def _normalized_ops(example: "TrainingExample") -> tuple[str, ...]:
    return tuple(op for op, _args in example.target_ops)


def _source_ir(example: "TrainingExample") -> Mapping[str, Any]:
    """Return the observed source representation used for decoding.

    The fallback preserves compatibility with manually constructed
    ``TrainingExample`` values from before the explicit ``source_ir`` field.
    It is intentionally independent of the target label.
    """

    return example.source_ir or _ae().encode_lean_ir(example.text)


@dataclass(frozen=True)
class AutoencoderConfig:
    """Frozen training policy; values are normalized at construction time."""

    learning_rate: float = 0.08
    min_learning_rate: float = 0.0005
    max_learning_rate: float = 0.25
    warmup_steps: int = 8
    decay_steps: int = 512
    plateau_factor: float = 0.5
    plateau_patience: int = 2
    gradient_clip: float = 1.0
    weight_decay: float = 0.0001
    label_smoothing: float = 0.02
    temperature: float = 1.0
    beam_width: int = 4
    max_ops: int = 32
    train_binding_policy: bool = False
    train_rewrite_policy: bool = False
    freeze_reconstruction_heads: bool = False
    rewrite_max_edits: int = 4
    validation_fraction: float = 0.10
    holdout_fraction: float = 0.10
    canary_fraction: float = 0.10
    seed: int = 17
    loss_weights: Mapping[str, float] = field(
        default_factory=lambda: {
            "cross_entropy": 1.0,
            "cosine": 0.35,
            "reconstruction": 0.80,
            "kl": 0.01,
            "reward": 0.50,
            "length": 0.03,
            "nca": 0.20,
            "fuzzy_prover": 0.20,
            "minimality": 0.10,
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "learning_rate", max(1e-8, _finite(self.learning_rate, 0.08)))
        object.__setattr__(self, "min_learning_rate", max(1e-8, _finite(self.min_learning_rate, 0.0005)))
        object.__setattr__(self, "max_learning_rate", max(self.min_learning_rate, _finite(self.max_learning_rate, 0.25)))
        object.__setattr__(self, "warmup_steps", max(0, int(self.warmup_steps)))
        object.__setattr__(self, "decay_steps", max(1, int(self.decay_steps)))
        object.__setattr__(self, "plateau_factor", min(0.99, max(0.05, _finite(self.plateau_factor, 0.5))))
        object.__setattr__(self, "plateau_patience", max(1, int(self.plateau_patience)))
        object.__setattr__(self, "gradient_clip", max(1e-6, _finite(self.gradient_clip, 1.0)))
        object.__setattr__(self, "weight_decay", max(0.0, _finite(self.weight_decay, 0.0001)))
        object.__setattr__(self, "label_smoothing", min(0.25, max(0.0, _finite(self.label_smoothing, 0.02))))
        object.__setattr__(self, "temperature", max(0.05, _finite(self.temperature, 1.0)))
        object.__setattr__(self, "beam_width", max(1, int(self.beam_width)))
        object.__setattr__(self, "max_ops", max(1, int(self.max_ops)))
        object.__setattr__(self, "train_binding_policy", bool(self.train_binding_policy))
        object.__setattr__(self, "train_rewrite_policy", bool(self.train_rewrite_policy))
        object.__setattr__(self, "freeze_reconstruction_heads", bool(self.freeze_reconstruction_heads))
        if self.freeze_reconstruction_heads and not self.train_rewrite_policy:
            raise ValueError("freezing reconstruction heads requires rewrite training")
        object.__setattr__(self, "rewrite_max_edits", max(1, min(8, int(self.rewrite_max_edits))))
        object.__setattr__(self, "validation_fraction", min(0.45, max(0.0, _finite(self.validation_fraction, 0.10))))
        object.__setattr__(self, "holdout_fraction", min(0.45, max(0.0, _finite(self.holdout_fraction, 0.10))))
        object.__setattr__(self, "canary_fraction", min(0.45, max(0.0, _finite(self.canary_fraction, 0.10))))
        split_total = self.validation_fraction + self.holdout_fraction + self.canary_fraction
        if split_total > 0.8:
            split_scale = 0.8 / split_total
            object.__setattr__(self, "validation_fraction", self.validation_fraction * split_scale)
            object.__setattr__(self, "holdout_fraction", self.holdout_fraction * split_scale)
            object.__setattr__(self, "canary_fraction", self.canary_fraction * split_scale)
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(
            self,
            "loss_weights",
            {str(key): max(0.0, _finite(value)) for key, value in dict(self.loss_weights or {}).items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "decay_steps": self.decay_steps,
            "gradient_clip": self.gradient_clip,
            "holdout_fraction": self.holdout_fraction,
            "label_smoothing": self.label_smoothing,
            "learning_rate": self.learning_rate,
            "loss_weights": dict(sorted(self.loss_weights.items())),
            "max_learning_rate": self.max_learning_rate,
            "max_ops": self.max_ops,
            "train_binding_policy": self.train_binding_policy,
            "train_rewrite_policy": self.train_rewrite_policy,
            "freeze_reconstruction_heads": self.freeze_reconstruction_heads,
            "rewrite_max_edits": self.rewrite_max_edits,
            "min_learning_rate": self.min_learning_rate,
            "plateau_factor": self.plateau_factor,
            "plateau_patience": self.plateau_patience,
            "beam_width": self.beam_width,
            "seed": self.seed,
            "temperature": self.temperature,
            "validation_fraction": self.validation_fraction,
            "warmup_steps": self.warmup_steps,
            "weight_decay": self.weight_decay,
            "canary_fraction": self.canary_fraction,
        }


@dataclass(frozen=True)
class TrainingExample:
    sample_id: str
    text: str
    target_ir: Mapping[str, Any]
    target_ops: tuple[tuple[str, tuple[str, ...]], ...]
    source_digest: str
    problem: str = ""
    # Kept at the end with a default so callers using the original positional
    # constructor remain valid. Training/evaluation must decode from this
    # source IR, never from ``target_ir``; otherwise paired refactor examples
    # can report artificially perfect reconstruction.
    source_ir: Mapping[str, Any] = field(default_factory=dict)
    # Auxiliary provenance for router/NCA teachers.  This is not proof
    # evidence; the compiler gate still decides whether a target is usable.
    rule_id: str = ""
    rule_features: tuple[str, ...] = ()

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "problem": self.problem,
            "sample_id": self.sample_id,
            "source_digest": self.source_digest,
            "source_ir_digest": _digest(self.source_ir),
            "target_ir_digest": _digest(self.target_ir),
            "rule_id": self.rule_id,
            "rule_features": list(self.rule_features),
            "target_ops": [
                {"op": op, **({"args": list(args)} if args else {})}
                for op, args in self.target_ops
            ],
        }
        if include_text:
            out["text"] = self.text
        return out


def coerce_training_example(value: Any, index: int = 0) -> TrainingExample:
    if isinstance(value, TrainingExample):
        return value
    if isinstance(value, str):
        text = value
        row: Mapping[str, Any] = {}
    elif isinstance(value, Mapping):
        row = value
        text = str(row.get("text") or row.get("source") or row.get("tactics") or row.get("lean") or "")
    else:
        text = str(value or "")
        row = {}
    source_ir_raw = row.get("source_ir") if isinstance(row, Mapping) else None
    if isinstance(source_ir_raw, Mapping):
        source_ir = _ops_to_ir(dict(source_ir_raw), _canonical_ops(source_ir_raw))
    else:
        source_ir = dict(_ae().encode_lean_ir(text))
    target_ir_raw = None
    if isinstance(row, Mapping):
        target_ir_raw = row.get("target_ir")
        if not isinstance(target_ir_raw, Mapping):
            target_ir_raw = row.get("ir")
    if not isinstance(target_ir_raw, Mapping):
        target_ir = dict(source_ir)
    else:
        target_ir = dict(target_ir_raw)
    ops = _canonical_ops(target_ir)
    target_ir = _ops_to_ir(target_ir, ops)
    sample_id = str(row.get("sample_id") or row.get("id") or "").strip() if isinstance(row, Mapping) else ""
    if not sample_id:
        sample_id = _text_digest(text)[:24] or f"sample-{index:08d}"
    raw_rule_features = row.get("rule_features") if isinstance(row, Mapping) else ()
    if isinstance(raw_rule_features, str):
        raw_rule_features = (raw_rule_features,)
    return TrainingExample(
        sample_id=sample_id,
        text=text,
        target_ir=target_ir,
        target_ops=ops,
        source_digest=_text_digest(text),
        problem=str(row.get("problem") or "") if isinstance(row, Mapping) else "",
        source_ir=source_ir,
        rule_id=str(row.get("rule_id") or "") if isinstance(row, Mapping) else "",
        rule_features=(
            tuple(
                str(item)[:80]
                for item in (raw_rule_features or ())
                if str(item).strip()
            )[:16]
            if isinstance(row, Mapping)
            else ()
        ),
    )


@dataclass(frozen=True)
class CanaryManifest:
    """Content-addressed split assignment with no metric outcomes."""

    seed: int
    assignments: Mapping[str, str]
    source_digests: Mapping[str, str]
    split_digests: Mapping[str, str]
    corpus_digest: str
    validation_fraction: float = 0.10
    holdout_fraction: float = 0.10
    canary_fraction: float = 0.10
    target_digests: Mapping[str, str] = field(default_factory=dict)
    frozen: bool = True
    schema: str = CANARY_SCHEMA

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        out = {
            "assignments": dict(sorted((str(k), str(v)) for k, v in self.assignments.items())),
            "corpus_digest": self.corpus_digest,
            "frozen": bool(self.frozen),
            "schema": self.schema,
            "seed": int(self.seed),
            "source_digests": dict(sorted((str(k), str(v)) for k, v in self.source_digests.items())),
            "split_digests": dict(sorted((str(k), str(v)) for k, v in self.split_digests.items())),
            "target_digests": dict(sorted((str(k), str(v)) for k, v in self.target_digests.items())),
            "validation_fraction": float(self.validation_fraction),
            "holdout_fraction": float(self.holdout_fraction),
            "canary_fraction": float(self.canary_fraction),
        }
        if include_digest:
            out["manifest_digest"] = self.digest
        return out


def build_canary_manifest(
    examples: Iterable[Any],
    *,
    config: Optional[AutoencoderConfig] = None,
    seed: Optional[int] = None,
) -> CanaryManifest:
    cfg = config or AutoencoderConfig()
    rows = [coerce_training_example(item, index) for index, item in enumerate(examples)]
    by_id: dict[str, TrainingExample] = {}
    for row in rows:
        if row.sample_id in by_id:
            raise ValueError(f"duplicate sample_id in training manifest: {row.sample_id}")
        by_id[row.sample_id] = row
    actual_seed = int(cfg.seed if seed is None else seed)
    assignments: dict[str, str] = {}
    source_digests: dict[str, str] = {}
    target_digests: dict[str, str] = {}
    digest_split: dict[str, str] = {}
    canary_cut = cfg.canary_fraction
    holdout_cut = canary_cut + cfg.holdout_fraction
    validation_cut = holdout_cut + cfg.validation_fraction
    for row in sorted(by_id.values(), key=lambda item: item.sample_id):
        source_digests[row.sample_id] = row.source_digest
        target_digests[row.sample_id] = _digest(row.target_ir)
        if row.source_digest in digest_split:
            split = digest_split[row.source_digest]
        else:
            raw = hashlib.sha256(f"{actual_seed}:{row.source_digest}".encode("utf-8")).hexdigest()
            bucket = int(raw[:12], 16) / float(16**12)
            if bucket < canary_cut:
                split = "canary"
            elif bucket < holdout_cut:
                split = "holdout"
            elif bucket < validation_cut:
                split = "validation"
            else:
                split = "train"
            digest_split[row.source_digest] = split
        assignments[row.sample_id] = split
    split_digests: dict[str, str] = {}
    for split in ("train", "validation", "canary", "holdout"):
        members = [
            f"{source_digests[sample_id]}:{target_digests[sample_id]}"
            for sample_id, assigned in assignments.items()
            if assigned == split
        ]
        split_digests[split] = hashlib.sha256("\n".join(sorted(members)).encode("utf-8")).hexdigest()
    corpus_digest = _digest(
        {"seed": actual_seed, "source_digests": source_digests, "target_digests": target_digests}
    )
    return CanaryManifest(
        seed=actual_seed,
        assignments=assignments,
        source_digests=source_digests,
        split_digests=split_digests,
        corpus_digest=corpus_digest,
        target_digests=target_digests,
        validation_fraction=cfg.validation_fraction,
        holdout_fraction=cfg.holdout_fraction,
        canary_fraction=cfg.canary_fraction,
    )


def validate_canary_manifest(manifest: CanaryManifest | Mapping[str, Any], examples: Iterable[Any]) -> dict[str, Any]:
    if not isinstance(manifest, CanaryManifest):
        data = dict(manifest)
        manifest = CanaryManifest(
            seed=int(data.get("seed") or 0),
            assignments=dict(data.get("assignments") or {}),
            source_digests=dict(data.get("source_digests") or {}),
            split_digests=dict(data.get("split_digests") or {}),
            corpus_digest=str(data.get("corpus_digest") or ""),
            target_digests=dict(data.get("target_digests") or {}),
            validation_fraction=_finite(data.get("validation_fraction"), 0.10),
            holdout_fraction=_finite(data.get("holdout_fraction"), 0.10),
            canary_fraction=_finite(data.get("canary_fraction"), 0.10),
            frozen=bool(data.get("frozen", True)),
            schema=str(data.get("schema") or CANARY_SCHEMA),
        )
    rows = [coerce_training_example(item, index) for index, item in enumerate(examples)]
    actual = {row.sample_id: row.source_digest for row in rows}
    actual_targets = {row.sample_id: _digest(row.target_ir) for row in rows}
    reasons: list[str] = []
    if len(actual) != len(rows):
        reasons.append("duplicate_sample_id")
    if manifest.schema != CANARY_SCHEMA:
        reasons.append("schema")
    if not manifest.frozen:
        reasons.append("not_frozen")
    if actual != dict(manifest.source_digests):
        reasons.append("source_digest_mismatch")
    if actual_targets != dict(manifest.target_digests):
        reasons.append("target_digest_mismatch")
    if set(manifest.assignments) != set(actual):
        reasons.append("assignment_mismatch")
    if len(set(manifest.assignments.values()) - {"train", "validation", "canary", "holdout"}) > 0:
        reasons.append("unknown_split")
    recomputed = build_canary_manifest(
        rows,
        config=AutoencoderConfig(
            seed=manifest.seed,
            validation_fraction=manifest.validation_fraction,
            holdout_fraction=manifest.holdout_fraction,
            canary_fraction=manifest.canary_fraction,
        ),
        seed=manifest.seed,
    )
    if dict(recomputed.assignments) != dict(manifest.assignments):
        reasons.append("assignment_digest_mismatch")
    if dict(recomputed.split_digests) != dict(manifest.split_digests):
        reasons.append("split_digest_mismatch")
    if recomputed.corpus_digest != manifest.corpus_digest:
        reasons.append("corpus_digest_mismatch")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "manifest_digest": manifest.digest,
        "corpus_digest": manifest.corpus_digest,
        "n_examples": len(rows),
    }


def split_training_examples(
    examples: Sequence[TrainingExample],
    manifest: CanaryManifest,
) -> dict[str, list[TrainingExample]]:
    splits: dict[str, list[TrainingExample]] = {"train": [], "validation": [], "canary": [], "holdout": []}
    for row in examples:
        split = str(manifest.assignments.get(row.sample_id) or "")
        if split not in splits:
            raise ValueError(f"example is not assigned by frozen manifest: {row.sample_id}")
        splits[split].append(row)
    return splits


def learning_rate_for_step(
    config: AutoencoderConfig,
    step: int,
    *,
    plateau_factor: float = 1.0,
) -> float:
    """Warm up, cosine-decay, then apply a bounded plateau multiplier."""

    position = max(0, int(step))
    if config.warmup_steps and position < config.warmup_steps:
        warm = (position + 1) / float(config.warmup_steps)
        base = config.learning_rate * warm
    else:
        progress = min(1.0, max(0.0, (position - config.warmup_steps) / float(config.decay_steps)))
        base = config.min_learning_rate + 0.5 * (config.learning_rate - config.min_learning_rate) * (1.0 + math.cos(math.pi * progress))
    return min(config.max_learning_rate, max(config.min_learning_rate, base * max(0.05, _finite(plateau_factor, 1.0))))


@dataclass(frozen=True)
class LossBreakdown:
    total: float
    cross_entropy: float
    cosine_loss: float
    cosine_similarity: float
    reconstruction_loss: float
    ir_exact_match: float
    kl_loss: float
    reward_loss: float
    reward: Optional[float]
    verifier_reward: Optional[float]
    typesafe_reward: Optional[float]
    fuzzy_prover_reward: Optional[float]
    nca_reward: Optional[float]
    nca_loss: float
    minimality_reward: float
    length_penalty: float
    copy_penalty: float
    binding_cross_entropy: Optional[float] = None
    rewrite_cross_entropy: Optional[float] = None
    rewrite_expected_cosine_loss: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cosine_loss": self.cosine_loss,
            "cosine_similarity": self.cosine_similarity,
            "copy_penalty": self.copy_penalty,
            "cross_entropy": self.cross_entropy,
            "binding_cross_entropy": self.binding_cross_entropy,
            "rewrite_cross_entropy": self.rewrite_cross_entropy,
            "rewrite_expected_cosine_loss": self.rewrite_expected_cosine_loss,
            "fuzzy_prover_reward": self.fuzzy_prover_reward,
            "ir_exact_match": self.ir_exact_match,
            "kl_loss": self.kl_loss,
            "length_penalty": self.length_penalty,
            "minimality_reward": self.minimality_reward,
            "nca_loss": self.nca_loss,
            "nca_reward": self.nca_reward,
            "reconstruction_loss": self.reconstruction_loss,
            "reward": self.reward,
            "reward_loss": self.reward_loss,
            "total": self.total,
            "typesafe_reward": self.typesafe_reward,
            "verifier_reward": self.verifier_reward,
        }


class LeanIRAutoencoder:
    """Sparse hashed-feature encoder and sequence decoder.

    The state is ordinary JSON.  Each update touches only the observed
    feature buckets, decoder operation rows, transition rows, and latent
    dimensions.  This makes the portable path suitable for sharded corpora;
    a caller can merge independently trained state shards with weighted
    averaging instead of retaining token text.
    """

    def __init__(self, *, config: Optional[AutoencoderConfig] = None, state: Optional[Mapping[str, Any]] = None) -> None:
        self.config = config or AutoencoderConfig()
        self.state: dict[str, Any] = self._new_state()
        if state:
            self._load_state(state)

    def _new_state(self) -> dict[str, Any]:
        from .binding_policy import FEATURES

        vocab = list(_operation_vocab()) + ["<eos>"]
        return {
            "schema": MODEL_SCHEMA,
            "version": 2,
            "step": 0,
            "accepted_steps": 0,
            "plateau_factor": 1.0,
            "vocab": vocab,
            "feature_buckets": FEATURE_BUCKETS,
            "op_bias": {op: 0.0 for op in vocab},
            "transition": {},
            "feature_op": {},
            "latent_bias": [0.0] * int(getattr(_ae(), "LATENT_D", 16)),
            "feature_latent": {},
            "binding_steps": 0,
            "binding_weights": dict.fromkeys(FEATURES, 0.0),
            "rewrite_steps": 0,
            "rewrite_templates": [],
            "rewrite_weights": {},
        }

    def _load_state(self, state: Mapping[str, Any]) -> None:
        loaded = copy.deepcopy(dict(state))
        if loaded.get("schema") not in {None, MODEL_SCHEMA, "jevops-lean-ir-autoencoder-model/v1"}:
            raise ValueError("unsupported autoencoder model schema")
        base = self._new_state()
        for key, value in loaded.items():
            if key in base:
                base[key] = value
        vocab = list(_operation_vocab()) + ["<eos>"]
        saved_vocab = loaded.get("vocab")
        if isinstance(saved_vocab, list) and saved_vocab:
            # A vocabulary expansion changes the softmax denominator and CE.
            # Frozen checkpoints must retain their evaluation vocabulary.
            if any(not isinstance(op, str) or op not in vocab for op in saved_vocab):
                raise ValueError("checkpoint has unsupported operation vocabulary")
            vocab = list(dict.fromkeys([*saved_vocab, "<eos>"]))
        base["vocab"] = vocab
        raw_bias = base.get("op_bias") if isinstance(base.get("op_bias"), Mapping) else {}
        base["op_bias"] = {op: _finite(raw_bias.get(op)) for op in vocab}
        base["feature_buckets"] = FEATURE_BUCKETS
        try:
            base["step"] = max(0, int(base.get("step") or 0))
        except (TypeError, ValueError):
            base["step"] = 0
        try:
            base["accepted_steps"] = max(0, int(base.get("accepted_steps") or 0))
        except (TypeError, ValueError):
            base["accepted_steps"] = 0
        base["plateau_factor"] = max(0.05, min(1.0, _finite(base.get("plateau_factor"), 1.0)))
        latent_d = len(base["latent_bias"]) if isinstance(base.get("latent_bias"), Sequence) else 0
        if latent_d != int(getattr(_ae(), "LATENT_D", 16)):
            base["latent_bias"] = (
                list(base["latent_bias"] if isinstance(base.get("latent_bias"), Sequence) else ())
                + [0.0] * int(getattr(_ae(), "LATENT_D", 16))
            )[: int(getattr(_ae(), "LATENT_D", 16))]
        base["latent_bias"] = [_finite(value) for value in base["latent_bias"]]
        for field_name in ("transition", "feature_op"):
            raw_outer = base.get(field_name) if isinstance(base.get(field_name), Mapping) else {}
            sanitized: dict[str, dict[str, float]] = {}
            for outer_key, raw_row in raw_outer.items():
                if not isinstance(raw_row, Mapping):
                    continue
                sanitized[str(outer_key)] = {str(key): _finite(value) for key, value in raw_row.items()}
            base[field_name] = sanitized
        raw_latent_rows = base.get("feature_latent") if isinstance(base.get("feature_latent"), Mapping) else {}
        base["feature_latent"] = {
            str(key): [_finite(item) for item in value[: int(getattr(_ae(), "LATENT_D", 16))]]
            for key, value in raw_latent_rows.items()
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        }
        from .binding_policy import FEATURES

        base["binding_steps"] = max(0, int(_finite(base.get("binding_steps"))))
        raw_binding = base.get("binding_weights") if isinstance(base.get("binding_weights"), Mapping) else {}
        base["binding_weights"] = {key: _finite(raw_binding.get(key)) for key in FEATURES}
        from .rewrite_policy import validate_templates

        base["rewrite_templates"] = validate_templates(base["rewrite_templates"])
        base["rewrite_steps"] = max(0, int(_finite(base.get("rewrite_steps"))))
        raw_rewrite = base.get("rewrite_weights")
        if not isinstance(raw_rewrite, Mapping) or len(raw_rewrite) > 8192:
            raise ValueError("invalid rewrite weights")
        base["rewrite_weights"] = {str(key): _finite(value) for key, value in raw_rewrite.items()}
        self.state = base

    @classmethod
    def from_dict(cls, state: Optional[Mapping[str, Any]], *, config: Optional[AutoencoderConfig] = None) -> "LeanIRAutoencoder":
        return cls(config=config, state=state or None)

    def copy(self) -> "LeanIRAutoencoder":
        return LeanIRAutoencoder(config=self.config, state=self.to_dict())

    def extend_operation_vocabulary(self) -> list[str]:
        """Explicit migration for training; CE changes and needs a new baseline."""
        added = [op for op in _operation_vocab() if op not in self.state["vocab"]]
        self.state["vocab"].extend(added)
        for op in added:
            self.state["op_bias"][op] = 0.0
        return added

    @property
    def step(self) -> int:
        return int(self.state.get("step") or 0)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.state)

    def learning_rate(self) -> float:
        return learning_rate_for_step(
            self.config,
            self.step,
            plateau_factor=_finite(self.state.get("plateau_factor"), 1.0),
        )

    def feature_vector(self, text: str) -> dict[int, float]:
        return _feature_vector(text, buckets=FEATURE_BUCKETS)

    def predict_latent(self, text: str) -> list[float]:
        dim = int(getattr(_ae(), "LATENT_D", 16))
        result = [_finite(value) for value in list(self.state.get("latent_bias") or [])[:dim]]
        result.extend([0.0] * (dim - len(result)))
        rows = self.state.setdefault("feature_latent", {})
        for bucket, value in self.feature_vector(text).items():
            row = rows.get(str(bucket)) or []
            for index in range(min(dim, len(row))):
                result[index] += _finite(row[index]) * value
        return result

    def _logits(self, features: Mapping[int, float], previous: str) -> dict[str, float]:
        vocab = list(self.state.get("vocab") or (list(_operation_vocab()) + ["<eos>"]))
        bias = self.state.setdefault("op_bias", {})
        logits = {op: _finite(bias.get(op)) for op in vocab}
        transition = self.state.setdefault("transition", {}).get(str(previous)) or {}
        for op in vocab:
            logits[op] += _finite(transition.get(op))
        feature_rows = self.state.setdefault("feature_op", {})
        for bucket, value in features.items():
            row = feature_rows.get(str(bucket)) or {}
            for op in vocab:
                logits[op] += _finite(row.get(op)) * value
        return logits

    def operation_probabilities(self, text: str, previous: str = "<bos>") -> dict[str, float]:
        return _softmax(self._logits(self.feature_vector(text), previous), self.config.temperature)

    @staticmethod
    def _binding_features(text: str, operations: Sequence[tuple[str, Sequence[str]]]) -> dict[str, Any]:
        from .binding_policy import source_features

        marker = _ae()._LEAN_HEADER.search(str(text))
        body = str(text)[marker.end():] if marker else str(text)
        return source_features(body, operations)

    def _binding_training_data(self, example: TrainingExample) -> Optional[tuple[list[dict[str, Any]], list[int]]]:
        from .binding_policy import subsequence_labels

        source = _source_ir(example)
        if any(source.get(key) != example.target_ir.get(key) for key in ("goal", "binders")):
            return None
        operations = _canonical_ops(source)
        features = self._binding_features(example.text, operations)
        if not features["supported"] or not features["rows"]:
            return None
        labels = subsequence_labels(operations, example.target_ops)
        if labels is None or any(not keep and operations[i][0] != "have" for i, keep in enumerate(labels)):
            return None
        return features["rows"], labels

    def binding_cross_entropy(self, example: TrainingExample) -> Optional[float]:
        from .binding_policy import loss_and_gradient

        if not self.config.train_binding_policy and not self.state.get("binding_steps"):
            return None
        data = self._binding_training_data(example)
        return None if data is None else loss_and_gradient(self.state["binding_weights"], *data)[0]

    def prepare_rewrite_training(self, examples: Sequence[TrainingExample]) -> dict[str, Any]:
        """Explicitly expand the edit grammar BEFORE taking metric baselines.

        Low-level supervised API: callers must supply verified, training-only
        pairs. The distillation runner and router enforce that contract. Never
        call this on validation/canary/holdout examples or in predict_ir.
        """
        from .rewrite_policy import MAX_RULES, body_from_ir, mine_template, validate_templates

        if not self.config.train_rewrite_policy:
            raise ValueError("rewrite training is not enabled")
        bank = copy.deepcopy(self.state["rewrite_templates"])
        before = _digest(bank)
        skipped = []
        for example in examples:
            observed = _source_ir(example)
            if any(observed.get(k) != example.target_ir.get(k) for k in ("goal", "binders")):
                raise ValueError("rewrite teacher changes theorem envelope")
            if not set(_normalized_ops(example)) <= set(self.state["vocab"]):
                raise ValueError("training target requires explicit vocabulary migration and rebaselining")
            rule = mine_template(example.text, body_from_ir(example.target_ir))
            if rule is None:
                skipped.append(example.sample_id)
            elif not any(r["id"] == rule["id"] for r in bank):
                if len(bank) == MAX_RULES:
                    skipped.append(example.sample_id)
                else:
                    bank.append(rule)
        bank = validate_templates(bank)
        added = len(bank) - len(self.state["rewrite_templates"])
        self.state["rewrite_templates"] = bank
        return {"added_templates": added, "template_count": len(bank), "not_mined": skipped,
                "before_digest": before, "after_digest": _digest(bank),
                "requires_new_edit_ce_baseline": bool(added)}

    def rewrite_objective(self, example: TrainingExample) -> Optional[dict[str, Any]]:
        from .rewrite_policy import body_from_ir, choices, loss_and_gradient

        if not self.config.train_rewrite_policy and not self.state["rewrite_steps"]:
            return None
        if any(_source_ir(example).get(k) != example.target_ir.get(k) for k in ("goal", "binders")):
            return None
        return loss_and_gradient(self.state["rewrite_weights"], choices(example.text, self.state["rewrite_templates"]),
                                 body_from_ir(example.target_ir), temperature=self.config.temperature,
                                 smoothing=self.config.label_smoothing,
                                 cosine_weight=self.config.loss_weights.get("rewrite_cosine", .35))

    def jev_feedback_request(self, source: str, *, spec: JeVFeedbackSpec, split: str) -> dict[str, Any]:
        """Freeze a training-only JeV request; no scoring or weight update occurs."""
        from .jev_surrogate import make_request

        if not self.config.train_rewrite_policy:
            raise ValueError("rewrite training is not enabled")
        return make_request(source, self.state["rewrite_templates"], self.state["rewrite_weights"],
                            spec=spec, split=split, temperature=self.config.temperature, step=self.step)

    def train_jev_feedback(
        self, source: str, receipt: Mapping[str, Any], *, spec: JeVFeedbackSpec, split: str,
        weight: float = 0.0, learning_rate: Optional[float] = None,
        reference_weights: Optional[Mapping[str, float]] = None, kl_weight: float = 0.0,
    ) -> dict[str, Any]:
        """Opt-in expected-utility SGD on edit weights, never proof admission.

        Invalid/lossy candidates may receive repair-quality feedback. This API
        neither mines templates nor creates supervised teachers. CE/cosine
        training and promotion gates remain separate. Reference weights, when
        used, must be a caller-owned frozen checkpoint, not the current policy.
        """
        from .jev_surrogate import _number, digest, expected_utility_gradient, feedback_utilities
        from .rewrite_policy import choices

        report: dict[str, Any] = {"schema": "jevops-jev-edit-update/v1", "updated": False,
                                  "reason": "disabled", "proof_admitted": False,
                                  "teacher_created": False, "score_coverage": 0.0}
        try:
            weight = _number(weight, "surrogate weight")
            if not 0 <= weight <= 1:
                raise ValueError("surrogate weight must be between 0 and 1")
            if weight == 0:
                return report
            request = self.jev_feedback_request(source, spec=spec, split=split)
            utilities = feedback_utilities(request, receipt)
            lr = _number(self.learning_rate() if learning_rate is None else learning_rate, "learning rate")
            if not 0 < lr <= self.config.max_learning_rate:
                raise ValueError("learning rate outside configured bounds")
            rows = choices(source, self.state["rewrite_templates"])
            weights = self.state["rewrite_weights"]
            reference = None if reference_weights is None else dict(reference_weights)
            before = expected_utility_gradient(weights, rows, utilities, temperature=self.config.temperature,
                                               reference_weights=reference, kl_weight=kl_weight)
            gradient = before["gradient"]
            norm = math.hypot(*gradient.values())
            scale = min(1.0, self.config.gradient_clip / (weight * norm)) if norm else 1.0
            updated = dict(weights)
            for key, value in gradient.items():
                if value != 0:
                    updated[key] = updated.get(key, 0.0) - lr * weight * scale * value
            # All checks and measurements precede the atomic state update.
            after = expected_utility_gradient(updated, rows, utilities, temperature=self.config.temperature,
                                              reference_weights=reference, kl_weight=kl_weight)
            report.update(request_id=request["request_id"], feedback_id=receipt["feedback_id"],
                          score_coverage=1.0, choice_count=len(rows), weight=weight, learning_rate=lr,
                          gradient_norm=norm, applied_gradient_norm=weight * scale * norm,
                          surrogate_loss_before=before["surrogate_loss"], surrogate_loss_after=after["surrogate_loss"],
                          expected_utility_before=before["expected_utility"], expected_utility_after=after["expected_utility"],
                          reference_kl_before=before["reference_kl"], reference_kl_after=after["reference_kl"],
                          objective_before=before["total"], objective_after=after["total"], kl_weight=kl_weight,
                          reference_sha256=None if reference is None else digest(reference),
                          reconstruction_parameters_unchanged=True)
            if updated == weights:
                report["reason"] = "zero_update"
                return report
            next_step = self.step + 1
            next_rewrite_step = self.state["rewrite_steps"] + 1
            self.state.update(rewrite_weights=updated, rewrite_steps=next_rewrite_step, step=next_step)
            report.update(updated=True, reason="surrogate_update")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            report["reason"] = str(exc) if isinstance(exc, ValueError) else "malformed_feedback_or_configuration"
        return report

    def predict_ir(
        self,
        text: str,
        *,
        source_ir: Optional[Mapping[str, Any]] = None,
        max_ops: Optional[int] = None,
        dependency_guard: bool = True,
        binding_policy: Optional[bool] = None,
        rewrite_policy: Optional[bool] = None,
    ) -> dict[str, Any]:
        """Decode an operation sequence while preserving source symbols.

        Operation selection is learned; arguments are copied only from the
        parsed source IR and are independently sanitized by the renderer.  We
        never let a model hallucinate arbitrary Lean text into the output.
        Normal evaluation considers the complete observed sequence but may
        learn to omit operations. A lexical dependency guard retains needed
        bindings and stateful steps; Lean must still verify the result. The
        ``max_ops`` proposal limit may be exceeded to retain prerequisites.
        ``dependency_guard=False`` is an explicit raw-model ablation, not an
        admission bypass. No teacher target is consulted by either path.
        """

        source = dict(source_ir or _ae().encode_lean_ir(text))
        if self.state["rewrite_steps"] and rewrite_policy is not False:
            import textwrap
            from .rewrite_policy import body_of, decode

            edited = decode(text, self.state["rewrite_templates"], self.state["rewrite_weights"],
                            max_edits=self.config.rewrite_max_edits, temperature=self.config.temperature)
            prefix, _ = body_of(text)
            rendered = prefix + "\n" + textwrap.indent(edited["body"], "  ") if prefix else edited["body"]
            prediction = dict(_ae().encode_lean_ir(rendered))
            for key in ("goal", "binders", "ident"):
                if key in source:
                    prediction[key] = copy.deepcopy(source[key])
            prediction["rewrite_policy"] = {k: v for k, v in edited.items() if k != "body"}
            prediction["dependency_guard"] = {"enabled": False, "reason": "span_edits_require_Lean_not_deletion_closure",
                                               "restored": [], "teacher_used": False}
            prediction["binding_policy"] = {"mode": "superseded_by_span_editor", "teacher_used": False}
            return prediction
        target = list(_canonical_ops(source))
        selected_indices: list[int] = []
        policy = {"mode": "legacy_eos_filter", "teacher_used": False}
        if self.state.get("binding_steps") and binding_policy is not False:
            from .binding_policy import keep_probability

            features = self._binding_features(text, target)
            policy = {"mode": "learned_binding_keep", "supported": features["supported"],
                      "reason": features["reason"], "steps": self.state["binding_steps"],
                      "feature_source": "symbolic_dependency_graph", "teacher_used": False, "decisions": []}
            # Unsupported structured proofs explicitly abstain. This is source
            # preservation, not a learned success or the static guard acting.
            selected_indices = list(range(len(target)))
            if features["supported"]:
                for row in features["rows"]:
                    probability = keep_probability(self.state["binding_weights"], row["features"])
                    policy["decisions"].append({"index": row["index"], "keep_probability": probability})
                    if probability < .5:
                        selected_indices.remove(row["index"])
            else:
                policy["mode"] = "unsupported_identity"
        elif self.step <= 0:
            selected_indices = list(range(len(target)))
        else:
            features = self.feature_vector(text)
            previous = "<bos>"
            limit = len(target) if max_ops is None else max(1, min(int(max_ops), self.config.max_ops))
            for index, (op, _args) in enumerate(target[:limit]):
                logits = self._logits(features, previous)
                op_score = logits.get(op, -60.0)
                eos_score = logits.get("<eos>", -60.0)
                # The margin keeps one-step updates from erasing the source;
                # later updates can learn deletions, subject to the guard.
                if op_score + 2.0 >= eos_score:
                    selected_indices.append(index)
                    previous = op
        if dependency_guard:
            from .ir_dependencies import close_deletions

            marker = _ae()._LEAN_HEADER.search(str(text))
            body = str(text)[marker.end():] if marker else str(text)
            guard = close_deletions(body, target, selected_indices)
            selected_indices = guard["kept_indices"]
        else:
            guard = {"enabled": False, "reason": "raw_model_ablation", "proposed_indices": selected_indices,
                     "kept_indices": selected_indices, "restored": [], "teacher_used": False}
        selected = [target[index] for index in selected_indices]
        if not selected:
            selected = [("trivial", ())]
        prediction = _ops_to_ir(source, selected)
        prediction["dependency_guard"] = guard
        prediction["binding_policy"] = policy
        return prediction

    def _sequence_loss(self, example: TrainingExample) -> float:
        features = self.feature_vector(example.text)
        previous = "<bos>"
        total = 0.0
        targets = list(_normalized_ops(example)) + ["<eos>"]
        for target in targets:
            probs = _softmax(self._logits(features, previous), self.config.temperature)
            smoothing = self.config.label_smoothing
            p_target = max(1e-12, _finite(probs.get(target), 0.0))
            if smoothing and len(probs) > 1:
                uniform = sum(-math.log(max(1e-12, value)) for value in probs.values()) / len(probs)
                total += (1.0 - smoothing) * -math.log(p_target) + smoothing * uniform
            else:
                total += -math.log(p_target)
            previous = target
        return total / float(max(1, len(targets)))

    def _apply_logit_update(
        self,
        features: Mapping[int, float],
        previous: str,
        target: str,
        *,
        learning_rate: float,
        scale: float,
    ) -> float:
        vocab = list(self.state.get("vocab") or ())
        probs = _softmax(self._logits(features, previous), self.config.temperature)
        smoothing = self.config.label_smoothing
        gradients = {
            # Match _sequence_loss exactly: smoothing is uniform over the
            # whole vocabulary, including the target. Softmax temperature
            # contributes the additional chain-rule factor.
            op: (probs.get(op, 0.0) - ((1.0 - smoothing if op == target else 0.0)
                                     + smoothing / max(1, len(vocab)))) / self.config.temperature
            for op in vocab
        }
        norm = math.sqrt(sum(value * value for value in gradients.values())) or 1.0
        clip_scale = min(1.0, self.config.gradient_clip / norm)
        step = max(1e-8, _finite(learning_rate, self.config.learning_rate)) * _finite(scale, 1.0) * clip_scale
        bias = self.state.setdefault("op_bias", {})
        transition = self.state.setdefault("transition", {}).setdefault(str(previous), {})
        feature_rows = self.state.setdefault("feature_op", {})
        for op, gradient in gradients.items():
            delta = step * gradient
            bias[op] = _finite(bias.get(op)) * (1.0 - step * self.config.weight_decay) - delta
            transition[op] = _finite(transition.get(op)) * (1.0 - step * self.config.weight_decay) - delta
            for bucket, value in features.items():
                row = feature_rows.setdefault(str(bucket), {})
                row[op] = _finite(row.get(op)) * (1.0 - step * self.config.weight_decay) - delta * value
        return norm * clip_scale

    def _apply_latent_update(self, text: str, *, learning_rate: float, scale: float) -> float:
        target = [float(value) / 1000.0 for value in _ae().encode_milles(text)["mu"]]
        predicted = self.predict_latent(text)
        errors = [predicted[i] - target[i] for i in range(min(len(predicted), len(target)))]
        norm = math.sqrt(sum(error * error for error in errors)) or 1.0
        clip_scale = min(1.0, self.config.gradient_clip / norm)
        step = max(1e-8, _finite(learning_rate)) * max(0.0, _finite(scale, 1.0)) * clip_scale
        bias = self.state.setdefault("latent_bias", [])
        rows = self.state.setdefault("feature_latent", {})
        features = self.feature_vector(text)
        for index, error in enumerate(errors):
            delta = step * error
            bias[index] = _finite(bias[index] if index < len(bias) else 0.0) * (1.0 - step * self.config.weight_decay) - delta
            for bucket, value in features.items():
                row = rows.setdefault(str(bucket), [0.0] * len(target))
                if index >= len(row):
                    row.extend([0.0] * (index + 1 - len(row)))
                row[index] = _finite(row[index]) * (1.0 - step * self.config.weight_decay) - delta * value
        return norm * clip_scale

    def train_example(
        self,
        example: TrainingExample,
        *,
        learning_rate: Optional[float] = None,
        reward: Optional[float] = None,
    ) -> dict[str, Any]:
        if not set(_normalized_ops(example)) <= set(self.state["vocab"]):
            raise ValueError("training target requires explicit vocabulary migration and rebaselining")
        lr = float(learning_rate if learning_rate is not None else self.learning_rate())
        # A low reward increases caution but does not erase a useful teacher
        # signal; verifier reward is an auxiliary weight, never the target.
        update_scale = 0.5 + 0.5 * _clip01(reward, 1.0) if reward is not None else 1.0
        ce = self._sequence_loss(example)
        features = self.feature_vector(example.text)
        previous = "<bos>"
        gradient_norm = 0.0
        targets = [] if self.config.freeze_reconstruction_heads else list(_normalized_ops(example)) + ["<eos>"]
        for target in targets:
            gradient_norm += self._apply_logit_update(
                features,
                previous,
                target,
                learning_rate=lr,
                scale=update_scale / max(1, len(example.target_ops) + 1),
            )
            previous = target
        latent_norm = (0.0 if self.config.freeze_reconstruction_heads else
                       self._apply_latent_update(example.text, learning_rate=lr, scale=update_scale))
        binding_loss = None
        if self.config.train_binding_policy:
            from .binding_policy import loss_and_gradient

            data = self._binding_training_data(example)
            if data is not None:
                binding_loss, gradients = loss_and_gradient(self.state["binding_weights"], *data)
                norm = math.sqrt(sum(v * v for v in gradients.values())) or 1.0
                scale = min(1.0, self.config.gradient_clip / norm)
                step = lr * update_scale * self.config.loss_weights.get("binding_cross_entropy", .25)
                for key, gradient in gradients.items():
                    old = self.state["binding_weights"].get(key, 0.0)
                    self.state["binding_weights"][key] = old * (1 - step * self.config.weight_decay) - step * scale * gradient
                self.state["binding_steps"] += 1
        rewrite_loss = self.rewrite_objective(example) if self.config.train_rewrite_policy else None
        if rewrite_loss is not None and rewrite_loss["choice_count"] > 1:
            gradient = rewrite_loss["gradient"]
            norm = math.sqrt(sum(v*v for v in gradient.values())) or 1.0
            scale = min(1.0, self.config.gradient_clip / norm)
            step = lr * update_scale * self.config.loss_weights.get("rewrite_cross_entropy", 1.0)
            weights = self.state["rewrite_weights"]
            for key, value in gradient.items():
                weights[key] = weights.get(key, 0.0) * (1-step*self.config.weight_decay) - step*scale*value
            self.state["rewrite_steps"] += 1
        self.state["step"] = self.step + 1
        return {"cross_entropy": ce, "gradient_norm": gradient_norm, "latent_gradient_norm": latent_norm,
                "learning_rate": lr, "binding_cross_entropy": binding_loss,
                "rewrite_cross_entropy": None if rewrite_loss is None else rewrite_loss["cross_entropy"],
                "rewrite_expected_cosine_loss": None if rewrite_loss is None else rewrite_loss["expected_cosine_loss"]}

    def train_batch(
        self,
        examples: Sequence[TrainingExample],
        *,
        rewards: Optional[Mapping[str, float]] = None,
        nca_rewards: Optional[Mapping[str, float]] = None,
    ) -> dict[str, Any]:
        if not examples:
            return {"sample_count": 0, "cross_entropy": 0.0, "gradient_norm": 0.0}
        # Reject incompatible batches before updating any weights. Otherwise
        # a late new operation could leave a partially trained checkpoint.
        vocab = set(self.state["vocab"])
        if any(not set(_normalized_ops(row)) <= vocab for row in examples):
            raise ValueError("training target requires explicit vocabulary migration and rebaselining")
        reports = []
        for row in examples:
            reward = (rewards or {}).get(row.sample_id)
            nca_reward = (nca_rewards or {}).get(row.sample_id)
            if nca_reward is not None:
                reward = (
                    _clip01(nca_reward)
                    if reward is None
                    else 0.75 * _clip01(reward) + 0.25 * _clip01(nca_reward)
                )
            reports.append(self.train_example(row, reward=reward))
        return {
            "sample_count": len(reports),
            "cross_entropy": sum(float(row["cross_entropy"]) for row in reports) / len(reports),
            "gradient_norm": sum(float(row["gradient_norm"]) for row in reports) / len(reports),
            "latent_gradient_norm": sum(float(row["latent_gradient_norm"]) for row in reports) / len(reports),
            "learning_rate": self.learning_rate(),
            "binding_updates": sum(r["binding_cross_entropy"] is not None for r in reports),
            "rewrite_labeled_examples": sum(r["rewrite_cross_entropy"] is not None for r in reports),
        }


def merge_model_states(
    states: Sequence[Mapping[str, Any] | LeanIRAutoencoder],
    *,
    weights: Optional[Sequence[float]] = None,
    config: Optional[AutoencoderConfig] = None,
) -> dict[str, Any]:
    """Merge independently trained sparse shards into one deterministic state.

    This is a bounded parameter merge, not an example/text merge.  Shards are
    expected to use the same model schema and disjoint examples; scalar and
    sparse rows are weighted by shard weight, while update counters are
    summed.  Invalid checkpoints are skipped so one failed worker cannot
    poison the aggregate.
    """

    cfg = config or AutoencoderConfig()
    source_states = list(states)
    raw_weights = list(weights or ())
    if raw_weights and len(raw_weights) != len(source_states):
        raise ValueError("weights must match the number of input model states")
    models: list[LeanIRAutoencoder] = []
    kept_weights: list[float] = []
    for index, item in enumerate(source_states):
        try:
            models.append(item if isinstance(item, LeanIRAutoencoder) else LeanIRAutoencoder.from_dict(item, config=cfg))
            kept_weights.append(raw_weights[index] if raw_weights else 1.0)
        except Exception:
            continue
    if not models:
        return LeanIRAutoencoder(config=cfg).to_dict()
    if any(model.state["vocab"] != models[0].state["vocab"] for model in models[1:]):
        raise ValueError("cannot merge different operation vocabularies; migrate and rebaseline explicitly")
    if any(model.state["rewrite_templates"] != models[0].state["rewrite_templates"] for model in models[1:]):
        raise ValueError("cannot merge different rewrite grammars; align them before training")
    positive = [max(0.0, _finite(value)) for value in kept_weights]
    total_weight = sum(positive)
    if total_weight <= 0.0:
        positive = [1.0] * len(models)
        total_weight = float(len(models))
    norm = [value / total_weight for value in positive]
    base = models[0].to_dict()

    def weighted_scalar(path: str, default: float = 0.0) -> float:
        return sum(weight * _finite(model.state.get(path), default) for weight, model in zip(norm, models))

    def merge_nested_rows(path: str) -> dict[str, Any]:
        keys: set[str] = set()
        for model in models:
            value = model.state.get(path)
            if isinstance(value, Mapping):
                keys.update(str(key) for key in value)
        merged: dict[str, Any] = {}
        for key in sorted(keys):
            row_keys: set[str] = set()
            for model in models:
                value = model.state.get(path)
                row = value.get(key) if isinstance(value, Mapping) else None
                if isinstance(row, Mapping):
                    row_keys.update(str(item) for item in row)
            row_out: dict[str, float] = {}
            for row_key in sorted(row_keys):
                row_out[row_key] = sum(
                    weight
                    * _finite(
                        ((model.state.get(path) or {}).get(key) or {}).get(row_key)
                        if isinstance(model.state.get(path), Mapping)
                        else 0.0
                    )
                    for weight, model in zip(norm, models)
                )
            if row_out:
                merged[key] = row_out
        return merged

    def merge_nested_vectors(path: str, dimension: int) -> dict[str, list[float]]:
        keys: set[str] = set()
        for model in models:
            value = model.state.get(path)
            if isinstance(value, Mapping):
                keys.update(str(key) for key in value)
        merged: dict[str, list[float]] = {}
        for key in sorted(keys):
            result = []
            for index in range(dimension):
                result.append(
                    sum(
                        weight
                        * _finite(
                            ((model.state.get(path) or {}).get(key) or [])[index]
                            if isinstance(model.state.get(path), Mapping)
                            and isinstance((model.state.get(path) or {}).get(key), Sequence)
                            and index < len((model.state.get(path) or {}).get(key))
                            else 0.0
                        )
                        for weight, model in zip(norm, models)
                    )
                )
            merged[key] = result
        return merged

    latent_dim = int(getattr(_ae(), "LATENT_D", 16))
    base["step"] = sum(model.step for model in models)
    base["accepted_steps"] = sum(int(model.state.get("accepted_steps") or 0) for model in models)
    base["plateau_factor"] = max(0.05, min(1.0, weighted_scalar("plateau_factor", 1.0)))
    base["op_bias"] = {
        op: sum(weight * _finite(model.state.get("op_bias", {}).get(op)) for weight, model in zip(norm, models))
        for op in base.get("vocab") or ()
    }
    base["latent_bias"] = [
        sum(
            weight
            * _finite((model.state.get("latent_bias") or [])[index] if index < len(model.state.get("latent_bias") or []) else 0.0)
            for weight, model in zip(norm, models)
        )
        for index in range(latent_dim)
    ]
    base["transition"] = merge_nested_rows("transition")
    base["feature_op"] = merge_nested_rows("feature_op")
    base["feature_latent"] = merge_nested_vectors("feature_latent", latent_dim)
    from .binding_policy import FEATURES

    base["binding_steps"] = sum(int(model.state.get("binding_steps") or 0) for model in models)
    base["binding_weights"] = {key: sum(weight * model.state.get("binding_weights", {}).get(key, 0.0)
                                      for weight, model in zip(norm, models)) for key in FEATURES}
    base["rewrite_steps"] = sum(model.state["rewrite_steps"] for model in models)
    rewrite_keys = {k for model in models for k in model.state["rewrite_weights"]}
    base["rewrite_weights"] = {k: sum(w*m.state["rewrite_weights"].get(k, 0.0) for w, m in zip(norm, models))
                               for k in rewrite_keys}
    return LeanIRAutoencoder(config=cfg, state=base).to_dict()


def _verifier_reward(compile_fn: Optional[Callable[..., Any]], lean: str, problem: str = "") -> Optional[float]:
    if compile_fn is None:
        return None
    try:
        try:
            result = compile_fn(lean, problem=problem)
        except TypeError:
            result = compile_fn(lean)
    except Exception:
        return 0.0
    if not isinstance(result, Mapping):
        return 1.0 if bool(result) else 0.0
    if "theorem_ok" in result:
        return 1.0 if bool(result.get("theorem_ok")) else 0.0
    if "ok" in result:
        return 1.0 if bool(result.get("ok")) else 0.0
    return None


def _typesafe_reward(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _clip01(value)
    if isinstance(value, Mapping):
        if value.get("reward") is not None:
            return _clip01(value.get("reward"))
        if value.get("score") is not None:
            score = _finite(value.get("score"))
            return _clip01(score if 0.0 <= score <= 1.0 else score / 1000.0)
        if value.get("confidence") is not None:
            return _clip01(value.get("confidence")) * (1.0 - _clip01(value.get("noul"), 0.0))
    for attr in ("reward", "confidence"):
        if hasattr(value, attr):
            return _clip01(getattr(value, attr))
    return None


@dataclass(frozen=True)
class NCAFeedback:
    """Bounded NCA signal used as an auxiliary learning signal.

    This is deliberately not a proof result.  Energy, neighborhood state,
    residual help, and historical wins/losses are policy memory.  The Lean
    compiler still decides whether a candidate is admissible.
    """

    active: bool = False
    reward: float = 0.5
    confidence: float = 0.0
    energy: float = 0.5
    neighbor_energy: float = 0.5
    win_rate: float = 0.5
    help_score: float = 0.0
    unsafe: float = 0.0
    contrastive_quality: float = 0.5
    cells: tuple[str, ...] = ()
    reason: str = "no_nca_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": bool(self.active),
            "cells": list(self.cells),
            "confidence": _clip01(self.confidence),
            "contrastive_quality": _clip01(self.contrastive_quality),
            "energy": _clip01(self.energy),
            "help_score": max(0.0, _finite(self.help_score)),
            "neighbor_energy": _clip01(self.neighbor_energy),
            "reason": self.reason,
            "reward": _clip01(self.reward),
            "unsafe": _clip01(self.unsafe),
            "win_rate": _clip01(self.win_rate),
        }


def nca_feedback_for_example(
    memory: Optional[Mapping[str, Any]],
    example: TrainingExample,
    *,
    candidate: Optional[Mapping[str, Any]] = None,
    problem: Optional[str] = None,
) -> NCAFeedback:
    """Read NCA state into a stable, bounded autoencoder reward.

    The lookup is intentionally read-only.  It uses the autoencoder skill
    cell, a problem/theorem cell when available, operation residual cells,
    explicit graph neighbors, and the stored contrastive diagnostic.  A
    missing NCA state is neutral rather than punitive, which keeps offline
    training deterministic.
    """

    if not isinstance(memory, Mapping):
        return NCAFeedback()
    nca_state = memory.get("nca")
    if not isinstance(nca_state, Mapping):
        return NCAFeedback()
    grid = nca_state.get("grid")
    grid = grid if isinstance(grid, Mapping) else {}
    store = nca_state.get("autoencoder")
    store = store if isinstance(store, Mapping) else {}
    feedback_store = store.get("feedback")
    feedback_store = feedback_store if isinstance(feedback_store, Mapping) else {}
    row = candidate if isinstance(candidate, Mapping) else {}
    problem_text = str(problem if problem is not None else example.problem or "")
    cells: list[str] = []
    try:
        from . import nca as nca_kernel

        cells.append(nca_kernel.canonical_cell_id("port_autoencoder", kind="skill"))
        if problem_text:
            cells.append(nca_kernel.canonical_cell_id(f"proof:{problem_text}", kind="theorem"))
        rule_id = str(row.get("rule_id") or example.rule_id or "").strip()
        if rule_id:
            cells.append(nca_kernel.canonical_cell_id(rule_id, kind="rule"))
        # NCA context is derived from observed source structure, not target
        # labels; this keeps the auxiliary signal from reintroducing the
        # source→target leakage that the explicit source_ir field prevents.
        for op, _args in _canonical_ops(_source_ir(example))[:8]:
            cells.append(nca_kernel.canonical_cell_id(f"residual:{op}", kind="residual"))
    except Exception:
        cells.append("ptr://skill/port_autoencoder")
    cells = list(dict.fromkeys(cell for cell in cells if cell))
    selected = [cell for cell in cells if isinstance(grid.get(cell), Mapping)]

    values = [grid[cell] for cell in selected]
    energy = (
        sum(_clip01(_finite(value.get("energy"), 0.5)) for value in values) / len(values)
        if values
        else _clip01(_finite(feedback_store.get("energy"), 0.5))
    )
    help_score = (
        sum(max(0.0, _finite(value.get("help"))) for value in values) / len(values)
        if values
        else max(0.0, _finite(feedback_store.get("help_score")))
    )
    unsafe = (
        sum(_clip01(_finite(value.get("unsafe"))) for value in values) / len(values)
        if values
        else _clip01(_finite(feedback_store.get("unsafe")))
    )
    wins = sum(max(0, int(_finite(value.get("wins")))) for value in values)
    losses = sum(max(0, int(_finite(value.get("losses")))) for value in values)
    if wins + losses:
        win_rate = wins / float(wins + losses)
    else:
        win_rate = _clip01(_finite(feedback_store.get("win_rate"), 0.5))

    neighbor_values: list[float] = []
    try:
        from . import nca as nca_kernel

        for cell in selected:
            for neighbor in nca_kernel.neighborhood(cell, memory):
                neighbor_row = grid.get(neighbor)
                if isinstance(neighbor_row, Mapping):
                    neighbor_values.append(_clip01(_finite(neighbor_row.get("energy"), 0.5)))
    except Exception:
        pass
    neighbor_energy = sum(neighbor_values) / len(neighbor_values) if neighbor_values else energy
    contrastive_m = row.get("contrastive_m")
    if contrastive_m is None:
        contrastive_m = store.get("contrastive_m")
    contrastive_quality = 1.0 - _clip01(_finite(contrastive_m, 500.0) / 1000.0)
    typesafe_reward = _typesafe_reward(row.get("typesafe_reward"))
    if typesafe_reward is None:
        typesafe_reward = _typesafe_reward(feedback_store.get("typesafe_reward"))

    # Help is stored on a wider scale in the NCA grid; normalize it before it
    # enters the loss.  Unsafe is a penalty, never an affirmative proof.
    reward = (
        0.38 * energy
        + 0.18 * neighbor_energy
        + 0.18 * win_rate
        + 0.10 * _clip01(help_score / 2.0)
        + 0.10 * contrastive_quality
        + 0.06 * (typesafe_reward if typesafe_reward is not None else 0.5)
    )
    reward *= 1.0 - 0.70 * unsafe
    verifier = row.get("verifier_reward")
    if verifier is not None:
        reward = 0.70 * reward + 0.30 * _clip01(verifier)
    # A candidate outcome can modulate existing NCA state, but it must not
    # manufacture an NCA signal when the NCA store is absent.  This preserves
    # the dependency-free/offline baseline as a true ablation.
    active = bool(selected or feedback_store)
    confidence = 0.0
    if active:
        confidence = min(1.0, 0.25 + 0.10 * len(selected) + 0.05 * min(5, wins + losses))
    return NCAFeedback(
        active=active,
        reward=_clip01(reward),
        confidence=confidence,
        energy=energy,
        neighbor_energy=neighbor_energy,
        win_rate=win_rate,
        help_score=help_score,
        unsafe=unsafe,
        contrastive_quality=contrastive_quality,
        cells=tuple(selected),
        reason="grid_and_history" if selected else ("stored_feedback" if feedback_store else "candidate_only"),
    )


def router_rule_id(rule: Mapping[str, Any]) -> str:
    """Return a stable id for a normalized router/NCA rule description."""

    parent_rule_ids = rule.get("parent_rule_ids") or ()
    if isinstance(parent_rule_ids, str):
        parent_rule_ids = (parent_rule_ids,)
    normalized = {
        "kind": str(rule.get("kind") or "router_rule")[:80],
        "strategy": str(rule.get("strategy") or "")[:80],
        "ops": list(rule.get("ops") or ())[:32],
        "candidate_digest": str(rule.get("candidate_digest") or "")[:80],
        "rationale_digest": str(rule.get("rationale_digest") or "")[:80],
        "plan_digest": str(rule.get("plan_digest") or "")[:80],
        "origin": str(rule.get("origin") or "")[:80],
        "commit": str(rule.get("commit") or "")[:80],
        "path": str(rule.get("path") or "")[:240],
        "parent_rule_ids": [str(item)[:80] for item in list(parent_rule_ids)[:8]],
    }
    return "rule-" + _digest(normalized)[:24]


def record_autoencoder_rule_feedback(
    memory: Optional[MutableMapping[str, Any]],
    *,
    problem: str = "",
    rule: Optional[Mapping[str, Any]] = None,
    outcome: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Persist a bounded proposal/outcome record and connect it to NCA.

    Rules are an auditable bridge between the router and the autoencoder.  The
    record contains normalized operation/strategy metadata and digests, never
    executable model text.  A rule becomes training-eligible only when the
    current compiler reports ``lake_ok``; proposal and rejection observations
    remain useful NCA data but cannot become a target.
    """

    if not isinstance(memory, MutableMapping):
        return {"ok": False, "reason": "memory_required"}
    raw = dict(rule or {})
    parent_rule_ids = raw.get("parent_rule_ids") or ()
    if isinstance(parent_rule_ids, str):
        parent_rule_ids = (parent_rule_ids,)
    normalized: dict[str, Any] = {
        "kind": str(raw.get("kind") or "router_rule")[:80],
        "strategy": str(raw.get("strategy") or "")[:80],
        "ops": [
            dict(item)
            if isinstance(item, Mapping)
            else str(item)[:160]
            for item in list(raw.get("ops") or ())[:32]
        ],
        "candidate_digest": str(raw.get("candidate_digest") or "")[:80],
        "rationale_digest": str(raw.get("rationale_digest") or "")[:80],
        "plan_digest": str(raw.get("plan_digest") or "")[:80],
        "origin": str(raw.get("origin") or "")[:80],
        "commit": str(raw.get("commit") or "")[:80],
        "path": str(raw.get("path") or "")[:240],
        "parent_rule_ids": [str(item)[:80] for item in list(parent_rule_ids)[:8]],
    }
    supplied_id = str(raw.get("rule_id") or "").strip()
    rule_id = supplied_id if supplied_id.startswith("rule-") else router_rule_id(normalized)
    normalized["rule_id"] = rule_id
    normalized["problem"] = str(problem or "")[:160]
    store = memory.setdefault("nca", {})
    rules = store.setdefault("router_rules", [])
    if not isinstance(rules, list):
        rules = []
        store["router_rules"] = rules
    existing = next(
        (row for row in rules if isinstance(row, Mapping) and str(row.get("rule_id") or "") == rule_id),
        None,
    )
    if existing is None:
        row: dict[str, Any] = {
            **normalized,
            "proposal_count": 0,
            "observation_count": 0,
            "verified_count": 0,
            "rejected_count": 0,
            "training_eligible": False,
            "best_tokens": None,
        }
        rules.append(row)
    else:
        row = dict(existing)
        row.update(
            {
                key: value
                for key, value in normalized.items()
                if value is not None and value != "" and value != []
            }
        )
        for index, item in enumerate(rules):
            if item is existing:
                rules[index] = row
                break
    row["proposal_count"] = int(row.get("proposal_count") or 0) + (0 if outcome else 1)
    if outcome is not None:
        result = dict(outcome)
        lake_ok = bool(result.get("lake_ok") or result.get("theorem_ok"))
        tokens = max(0, int(result.get("body_tokens") or result.get("tokens") or 0))
        reward = _clip01(result.get("reward"), 0.0)
        row["observation_count"] = int(row.get("observation_count") or 0) + 1
        row["verified_count"] = int(row.get("verified_count") or 0) + int(lake_ok)
        row["rejected_count"] = int(row.get("rejected_count") or 0) + int(not lake_ok)
        row["lake_verified"] = lake_ok
        row["training_eligible"] = bool(row.get("training_eligible") or lake_ok)
        old_tokens = row.get("best_tokens")
        if lake_ok and tokens and (old_tokens is None or tokens < int(old_tokens)):
            row["best_tokens"] = tokens
        row["last_reward"] = reward
        row["last_body_tokens"] = tokens
        row["last_outcome"] = "verified" if lake_ok else "rejected"
    row["rule_digest"] = _digest(normalized)
    store["router_rules"] = rules[-512:]
    try:
        from . import nca as nca_kernel

        rule_ptr = nca_kernel.canonical_cell_id(rule_id, kind="rule")
        lake_ok = None if outcome is None else bool(dict(outcome).get("lake_ok") or dict(outcome).get("theorem_ok"))
        reward = 0.5 if outcome is None else _clip01(dict(outcome).get("reward"), 0.5)
        tokens = 0 if outcome is None else int(dict(outcome).get("body_tokens") or dict(outcome).get("tokens") or 0)
        theorem_ptr = (
            nca_kernel.canonical_cell_id(f"proof:{problem}", kind="theorem")
            if problem
            else ""
        )
        nca_kernel.upsert_from_event(
            memory,
            ptr=rule_ptr,
            kind="rule",
            energy=reward,
            theorem_ok=lake_ok,
            tokens=tokens,
            parent_ptr=theorem_ptr,
        )
        edges = store.setdefault("board_edges", [])
        for edge in (
            ["ptr://skill/port_autoencoder", rule_ptr],
            [rule_ptr, theorem_ptr] if theorem_ptr else None,
        ):
            if edge and edge not in edges:
                edges.append(edge)
        nca_kernel.journal_event(
            memory,
            event="router_rule_observation" if outcome is not None else "router_rule_proposal",
            ptr=rule_ptr,
            op="RULE_OBSERVE" if outcome is not None else "RULE_PROPOSE",
            extra={"problem": str(problem or "")[:160], "lake_ok": lake_ok},
        )
    except Exception as exc:
        row["nca_error"] = type(exc).__name__
    return {"ok": True, "rule_id": rule_id, "record": dict(row)}


def advance_autoencoder_nca(
    memory: Optional[MutableMapping[str, Any]],
    *,
    problem: str = "",
) -> dict[str, Any]:
    """Run one focused NCA propagation step for an autoencoder batch."""

    if not isinstance(memory, MutableMapping):
        return {"ok": False, "reason": "memory_required", "tick": 0, "n_cells": 0}
    try:
        from . import nca as nca_kernel

        result = dict(
            nca_kernel.tick(
                memory,
                problem=problem,
                focus="ptr://skill/port_autoencoder",
            )
            or {}
        )
        return {
            "ok": bool(result.get("ok", True)),
            "tick": int(result.get("tick") or 0),
            "n_cells": int(result.get("n_cells") or 0),
        }
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "tick": 0, "n_cells": 0}


def record_autoencoder_nca_feedback(
    memory: Optional[MutableMapping[str, Any]],
    *,
    problem: str = "",
    reward: float = 0.5,
    theorem_ok: Optional[bool] = None,
    typesafe_reward: Optional[float] = None,
    tokens: int = 0,
    candidate: Optional[Mapping[str, Any]] = None,
    advance_nca: bool = True,
) -> dict[str, Any]:
    """Feed one bounded autoencoder outcome back into NCA working memory.

    ``advance_nca`` is false for per-candidate batch observations. Callers
    can then perform one focused cellular update after the batch, avoiding an
    O(number-of-candidates × number-of-cells) propagation cost while keeping
    every verifier outcome in the skill statistics.
    """

    if not isinstance(memory, MutableMapping):
        return {"ok": False, "reason": "memory_required"}
    reward_value = _clip01(reward, 0.5)
    store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
    previous = store.get("feedback") if isinstance(store.get("feedback"), Mapping) else {}
    count = max(0, int(_finite(previous.get("count")))) + 1
    old_mean = _clip01(_finite(previous.get("mean_reward"), reward_value))
    mean_reward = old_mean + (reward_value - old_mean) / float(count)
    feedback = {
        "count": count,
        "energy": reward_value,
        "mean_reward": mean_reward,
        "last_reward": reward_value,
        "typesafe_reward": None if typesafe_reward is None else _clip01(typesafe_reward),
        "unsafe": 0.0 if theorem_ok is True else (1.0 if theorem_ok is False else _clip01(previous.get("unsafe"))),
        "win_rate": 1.0 if theorem_ok is True else (0.0 if theorem_ok is False else _clip01(previous.get("win_rate"), 0.5)),
        "last_problem_digest": _text_digest(problem) if problem else "",
        "last_candidate_digest": _digest(
            {
                "id": candidate.get("id") if isinstance(candidate, Mapping) else "",
                "ir": candidate.get("ir_digest") if isinstance(candidate, Mapping) else "",
                "n_tokens": candidate.get("n_tokens") if isinstance(candidate, Mapping) else tokens,
                "rule_id": candidate.get("rule_id") if isinstance(candidate, Mapping) else "",
            }
        ),
    }
    store["feedback"] = feedback
    try:
        from . import nca as nca_kernel

        parent = ""
        if problem:
            parent = nca_kernel.canonical_cell_id(f"proof:{problem}", kind="theorem")
        skill_ptr = "ptr://skill/port_autoencoder"
        nca_kernel.upsert_from_event(
            memory,
            ptr=skill_ptr,
            kind="skill",
            energy=reward_value,
            theorem_ok=theorem_ok,
            tokens=max(0, int(tokens)),
            parent_ptr=parent,
        )
        if parent:
            edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
            edge = [skill_ptr, parent]
            if edge not in edges:
                edges.append(edge)
        rule_id = str((candidate or {}).get("rule_id") or "").strip() if isinstance(candidate, Mapping) else ""
        if rule_id:
            rule_ptr = nca_kernel.canonical_cell_id(rule_id, kind="rule")
            nca_kernel.upsert_from_event(
                memory,
                ptr=rule_ptr,
                kind="rule",
                energy=reward_value,
                theorem_ok=theorem_ok,
                tokens=max(0, int(tokens)),
                parent_ptr=parent,
            )
            edges = memory.setdefault("nca", {}).setdefault("board_edges", [])
            for edge in ([skill_ptr, rule_ptr], [rule_ptr, parent] if parent else None):
                if edge and edge not in edges:
                    edges.append(edge)
        if advance_nca:
            tick_result = advance_autoencoder_nca(memory, problem=problem)
            feedback["nca_tick"] = int(tick_result.get("tick") or 0)
            feedback["nca_cells"] = int(tick_result.get("n_cells") or 0)
        nca_kernel.journal_event(
            memory,
            event="autoencoder_feedback",
            ptr=skill_ptr,
            op="AE_FEEDBACK",
            energy_delta=0.0,
            extra={"reward": reward_value, "theorem_ok": theorem_ok, "problem_digest": feedback["last_problem_digest"]},
        )
    except Exception as exc:
        feedback["nca_error"] = type(exc).__name__
    return {"ok": True, "feedback": feedback}


def loss_for_example(
    model: LeanIRAutoencoder,
    example: TrainingExample,
    *,
    predicted_ir: Optional[Mapping[str, Any]] = None,
    verifier_reward: Optional[float] = None,
    typesafe_reward: Optional[float] = None,
    fuzzy_prover_reward: Optional[float] = None,
    nca_memory: Optional[Mapping[str, Any]] = None,
    minimality_reward: Optional[float] = None,
    config: Optional[AutoencoderConfig] = None,
) -> LossBreakdown:
    cfg = config or model.config
    prediction = dict(predicted_ir or model.predict_ir(example.text, source_ir=_source_ir(example)))
    predicted_ops = _canonical_ops(prediction)
    target_names = _normalized_ops(example)
    predicted_names = tuple(op for op, _args in predicted_ops)
    target_counts = _ae().ir_counts(example.target_ir)
    pred_counts = _ae().ir_counts(prediction)
    cosine_m = _ae().cosine_milles(target_counts, pred_counts) / 1000.0
    cosine_similarity = max(0.0, min(1.0, cosine_m))
    distance = _sequence_distance(target_names + ("<eos>",), predicted_names + ("<eos>",))
    reconstruction_loss = distance / float(max(1, len(target_names) + len(predicted_names) + 1))
    exact = 1.0 if example.target_ops == predicted_ops else 0.0
    target_latent = [float(value) / 1000.0 for value in _ae().encode_milles(example.text)["mu"]]
    predicted_latent = model.predict_latent(example.text)
    latent_cos = _ae().cosine_milles(
        [int(value * 1000) for value in target_latent],
        [int(value * 1000) for value in predicted_latent],
    ) / 1000.0
    cosine_similarity = max(0.0, min(1.0, 0.5 * cosine_similarity + 0.5 * latent_cos))
    cosine_loss = 1.0 - cosine_similarity
    kl_loss = sum(value * value for value in predicted_latent) / float(max(1, len(predicted_latent)))
    length_penalty = max(0.0, (len(predicted_names) - len(target_names)) / float(max(1, len(target_names))))
    nca_signal = nca_feedback_for_example(
        nca_memory,
        example,
            candidate={
            "verifier_reward": verifier_reward,
            "typesafe_reward": typesafe_reward,
            "rule_id": example.rule_id,
        },
    )
    nca_reward = nca_signal.reward if nca_signal.active else None
    nca_loss = 0.0 if nca_reward is None else 1.0 - nca_reward
    fuzzy = None if fuzzy_prover_reward is None else _clip01(fuzzy_prover_reward)
    minimality = (
        _clip01(minimality_reward)
        if minimality_reward is not None
        else 1.0 - _clip01(length_penalty)
    )
    # Short text is not a successful refactor without a positive compiler
    # result. This applies even to a caller-supplied minimality score: failed
    # and unevaluated predictions must not earn a compression bonus in loss.
    if _finite(verifier_reward, -1.0) != 1.0:
        minimality = 0.0
    reward_values = [value for value in (verifier_reward, typesafe_reward, fuzzy) if value is not None]
    reward = None if not reward_values else sum(_clip01(value) for value in reward_values) / len(reward_values)
    if verifier_reward is not None and _finite(verifier_reward, -1.0) != 1.0:
        reward = 0.0  # Preserve soft advisor fields, but never override a failed verifier.
    reward_loss = 0.0 if reward is None else 1.0 - reward
    copy_penalty = 0.0
    weights = cfg.loss_weights
    binding_ce = model.binding_cross_entropy(example)
    rewrite_loss = model.rewrite_objective(example)
    total = (
        weights.get("cross_entropy", 1.0) * model._sequence_loss(example)
        + weights.get("cosine", 0.35) * cosine_loss
        + weights.get("reconstruction", 0.8) * reconstruction_loss
        + weights.get("kl", 0.01) * kl_loss
        + weights.get("reward", 0.5) * reward_loss
        + weights.get("length", 0.03) * length_penalty
        + weights.get("nca", 0.20) * nca_loss
        + weights.get("fuzzy_prover", 0.20) * (0.0 if fuzzy is None else 1.0 - fuzzy)
        + weights.get("minimality", 0.10) * (1.0 - minimality)
        + weights.get("binding_cross_entropy", .25) * (binding_ce if binding_ce is not None else 0.0)
        + weights.get("rewrite_cross_entropy", 1.0) * (rewrite_loss["total"] if rewrite_loss is not None else 0.0)
    )
    return LossBreakdown(
        total=max(0.0, total),
        cross_entropy=max(0.0, model._sequence_loss(example)),
        cosine_loss=max(0.0, cosine_loss),
        cosine_similarity=cosine_similarity,
        reconstruction_loss=max(0.0, reconstruction_loss),
        ir_exact_match=exact,
        kl_loss=max(0.0, kl_loss),
        reward_loss=max(0.0, reward_loss),
        reward=reward,
        verifier_reward=None if verifier_reward is None else _clip01(verifier_reward),
        typesafe_reward=None if typesafe_reward is None else _clip01(typesafe_reward),
        fuzzy_prover_reward=fuzzy,
        nca_reward=nca_reward,
        nca_loss=nca_loss,
        minimality_reward=minimality,
        length_penalty=length_penalty,
        copy_penalty=copy_penalty,
        binding_cross_entropy=binding_ce,
        rewrite_cross_entropy=None if rewrite_loss is None else rewrite_loss["cross_entropy"],
        rewrite_expected_cosine_loss=None if rewrite_loss is None else rewrite_loss["expected_cosine_loss"],
    )


def evaluate_model(
    model: LeanIRAutoencoder,
    examples: Sequence[TrainingExample],
    *,
    split: str = "evaluation",
    compile_fn: Optional[Callable[..., Any]] = None,
    typesafe_fn: Optional[Callable[..., Any]] = None,
    nca_memory: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for example in list(examples)[:MAX_EVAL_ROWS]:
        predicted_ir = model.predict_ir(example.text, source_ir=_source_ir(example))
        lean = _ae().decode_lean_ir(predicted_ir)
        verifier = _verifier_reward(compile_fn, lean, example.problem)
        type_reward: Optional[float] = None
        if typesafe_fn is not None:
            try:
                response = typesafe_fn(
                    [{
                        "id": example.sample_id,
                        "split": split,
                        "n_ops": len(predicted_ir.get("ops") or ()),
                        "ir_exact_match": _canonical_ops(predicted_ir) == example.target_ops,
                    }]
                )
                type_reward = _typesafe_reward(response)
            except Exception:
                type_reward = None
        loss = loss_for_example(
            model,
            example,
            predicted_ir=predicted_ir,
            verifier_reward=verifier,
            typesafe_reward=type_reward,
            nca_memory=nca_memory,
        )
        rows.append(
            {
                "sample_id": example.sample_id,
                "source_digest": example.source_digest,
                "loss": loss.to_dict(),
                "predicted_ir_digest": _digest(predicted_ir),
                "lean_digest": _text_digest(lean),
                "verifier_reward": verifier,
            }
        )
    if not rows:
        return {
            "status": "not_measured",
            "split": split,
            "sample_count": 0,
            "objective": None,
            "cross_entropy": None,
            "binding_cross_entropy": None,
            "binding_sample_count": 0,
            "rewrite_cross_entropy": None,
            "rewrite_expected_cosine_loss": None,
            "rewrite_sample_count": 0,
            "cosine_similarity": None,
            "reconstruction_loss": None,
            "ir_exact_match": None,
            "minimality_reward": None,
            "nca_reward": None,
            "nca_loss": None,
            "verifier_success_rate": None,
            "verifier_evaluated_count": 0,
            "rows": [],
        }
    values = [row["loss"] for row in rows]
    verifier_values = [row["verifier_reward"] for row in rows if row["verifier_reward"] is not None]
    binding_values = [row["binding_cross_entropy"] for row in values if row["binding_cross_entropy"] is not None]
    rewrite_values = [row for row in values if row["rewrite_cross_entropy"] is not None]
    return {
        "status": "semantic_scored",
        "split": split,
        "sample_count": len(rows),
        "objective": sum(float(value["total"]) for value in values) / len(values),
        "cross_entropy": sum(float(value["cross_entropy"]) for value in values) / len(values),
        "binding_cross_entropy": sum(binding_values) / len(binding_values) if binding_values else None,
        "binding_sample_count": len(binding_values),
        "rewrite_cross_entropy": (sum(r["rewrite_cross_entropy"] for r in rewrite_values)/len(rewrite_values)
                                  if rewrite_values else None),
        "rewrite_expected_cosine_loss": (sum(r["rewrite_expected_cosine_loss"] for r in rewrite_values)/len(rewrite_values)
                                        if rewrite_values else None),
        "rewrite_sample_count": len(rewrite_values),
        "cosine_similarity": sum(float(value["cosine_similarity"]) for value in values) / len(values),
        "reconstruction_loss": sum(float(value["reconstruction_loss"]) for value in values) / len(values),
        "ir_exact_match": sum(float(value["ir_exact_match"]) for value in values) / len(values),
        "minimality_reward": sum(float(value["minimality_reward"]) for value in values) / len(values),
        "nca_reward": (
            None
            if not [value for value in values if value.get("nca_reward") is not None]
            else sum(float(value["nca_reward"]) for value in values if value.get("nca_reward") is not None)
            / len([value for value in values if value.get("nca_reward") is not None])
        ),
        "nca_loss": sum(float(value["nca_loss"]) for value in values) / len(values),
        "verifier_success_rate": None if not verifier_values else sum(verifier_values) / len(verifier_values),
        "verifier_evaluated_count": len(verifier_values),
        "rows": rows,
    }


def evaluate_stream_split(
    model: LeanIRAutoencoder,
    examples: Iterable[Any],
    *,
    split: str,
    compile_fn: Optional[Callable[..., Any]] = None,
    typesafe_fn: Optional[Callable[..., Any]] = None,
    nca_memory: Optional[Mapping[str, Any]] = None,
    max_rows: int = MAX_EVAL_ROWS,
    max_verified_rows: int = MAX_EVAL_ROWS,
    max_metric_rows: Optional[int] = MAX_EVAL_ROWS,
) -> dict[str, Any]:
    """Evaluate a split in one pass with bounded metric/verifier work.

    The stream is consumed to preserve split/assignment validation, but only
    ``max_metric_rows`` rows perform model/loss work by default.  Set it to
    ``None`` for a full evaluation.  ``stream_count`` remains the full count,
    while ``sample_count`` is the measured metric sample.
    """

    count = 0
    stream_count = 0
    sums = {
        "total": 0.0,
        "cross_entropy": 0.0,
        "cosine_similarity": 0.0,
        "reconstruction_loss": 0.0,
        "ir_exact_match": 0.0,
        "minimality_reward": 0.0,
        "nca_loss": 0.0,
    }
    verifier_sum = 0.0
    verifier_count = 0
    binding_sum = 0.0
    binding_count = 0
    rewrite_sum = rewrite_cosine_sum = 0.0
    rewrite_count = 0
    nca_reward_sum = 0.0
    nca_reward_count = 0
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_cap = max(1024, 4 * max(1, int(max_metric_rows or MAX_EVAL_ROWS)))
    for index, value in enumerate(examples):
        example = coerce_training_example(value, index)
        stream_count += 1
        if len(seen) < seen_cap and example.sample_id in seen:
            raise ValueError(f"duplicate sample_id in streaming split: {example.sample_id}")
        if len(seen) < seen_cap:
            seen.add(example.sample_id)
        if max_metric_rows is not None and count >= max(0, int(max_metric_rows)):
            continue
        prediction = model.predict_ir(example.text, source_ir=_source_ir(example))
        lean = _ae().decode_lean_ir(prediction)
        verifier = (
            _verifier_reward(compile_fn, lean, example.problem)
            if compile_fn is not None and count < max(0, int(max_verified_rows))
            else None
        )
        type_reward: Optional[float] = None
        if typesafe_fn is not None and count < max(0, int(max_verified_rows)):
            try:
                type_reward = _typesafe_reward(typesafe_fn([{"id": example.sample_id, "split": split, "n_ops": len(prediction.get("ops") or ())}]))
            except Exception:
                type_reward = None
        loss = loss_for_example(
            model,
            example,
            predicted_ir=prediction,
            verifier_reward=verifier,
            typesafe_reward=type_reward,
            nca_memory=nca_memory,
        )
        values = loss.to_dict()
        count += 1
        for key in sums:
            sums[key] += float(values[key])
        if values["binding_cross_entropy"] is not None:
            binding_sum += values["binding_cross_entropy"]
            binding_count += 1
        if values["rewrite_cross_entropy"] is not None:
            rewrite_sum += values["rewrite_cross_entropy"]
            rewrite_cosine_sum += values["rewrite_expected_cosine_loss"]
            rewrite_count += 1
        if values.get("nca_reward") is not None:
            nca_reward_sum += float(values["nca_reward"])
            nca_reward_count += 1
        if verifier is not None:
            verifier_sum += verifier
            verifier_count += 1
        if len(evidence) < max(0, int(max_rows)):
            evidence.append(
                {
                    "sample_id": example.sample_id,
                    "source_digest": example.source_digest,
                    "loss": values,
                    "predicted_ir_digest": _digest(prediction),
                    "lean_digest": _text_digest(lean),
                    "verifier_reward": verifier,
                }
            )
    if count == 0:
        return {
            "status": "not_measured",
            "split": split,
            "sample_count": 0,
            "stream_count": stream_count,
            "objective": None,
            "cross_entropy": None,
            "binding_cross_entropy": None,
            "binding_sample_count": 0,
            "rewrite_cross_entropy": None,
            "rewrite_expected_cosine_loss": None,
            "rewrite_sample_count": 0,
            "cosine_similarity": None,
            "reconstruction_loss": None,
            "ir_exact_match": None,
            "minimality_reward": None,
            "nca_reward": None,
            "nca_loss": None,
            "verifier_success_rate": None,
            "verifier_evaluated_count": 0,
            "rows": [],
        }
    return {
        "status": "semantic_scored",
        "split": split,
        "sample_count": count,
        "stream_count": stream_count,
        "objective": sums["total"] / count,
        "cross_entropy": sums["cross_entropy"] / count,
        "binding_cross_entropy": binding_sum / binding_count if binding_count else None,
        "binding_sample_count": binding_count,
        "rewrite_cross_entropy": rewrite_sum/rewrite_count if rewrite_count else None,
        "rewrite_expected_cosine_loss": rewrite_cosine_sum/rewrite_count if rewrite_count else None,
        "rewrite_sample_count": rewrite_count,
        "cosine_similarity": sums["cosine_similarity"] / count,
        "reconstruction_loss": sums["reconstruction_loss"] / count,
        "ir_exact_match": sums["ir_exact_match"] / count,
        "minimality_reward": sums["minimality_reward"] / count,
        "nca_reward": None if not nca_reward_count else nca_reward_sum / nca_reward_count,
        "nca_loss": sums["nca_loss"] / count,
        "verifier_success_rate": None if not verifier_count else verifier_sum / verifier_count,
        "verifier_evaluated_count": verifier_count,
        "rows": evidence,
    }


def train_autoencoder_stream(
    split_factory: Callable[[str], Iterable[Any]],
    *,
    manifest: CanaryManifest | Mapping[str, Any],
    state: Optional[Mapping[str, Any]] = None,
    config: Optional[AutoencoderConfig] = None,
    epochs: int = 3,
    batch_size: int = 32,
    memory: Optional[MutableMapping[str, Any]] = None,
    compile_fn: Optional[Callable[..., Any]] = None,
    typesafe_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Train from split-aware factories without materializing the corpus.

    ``split_factory`` is called only with ``train``, ``validation``, and
    ``canary``.  It must not expose the holdout stream; the separate frozen
    evaluator is the only API that requests ``holdout``.
    """

    cfg = config or AutoencoderConfig()
    if not callable(split_factory):
        return {"ok": False, "reason": "split_factory_required", "schema": TRAINING_SCHEMA}
    if not isinstance(manifest, CanaryManifest):
        data = dict(manifest)
        manifest = CanaryManifest(
            seed=int(data.get("seed") or cfg.seed),
            assignments=dict(data.get("assignments") or {}),
            source_digests=dict(data.get("source_digests") or {}),
            split_digests=dict(data.get("split_digests") or {}),
            corpus_digest=str(data.get("corpus_digest") or ""),
            target_digests=dict(data.get("target_digests") or {}),
            validation_fraction=_finite(data.get("validation_fraction"), cfg.validation_fraction),
            holdout_fraction=_finite(data.get("holdout_fraction"), cfg.holdout_fraction),
            canary_fraction=_finite(data.get("canary_fraction"), cfg.canary_fraction),
            frozen=bool(data.get("frozen", True)),
            schema=str(data.get("schema") or CANARY_SCHEMA),
        )
    if manifest.schema != CANARY_SCHEMA or not manifest.frozen:
        return {"ok": False, "reason": "invalid_frozen_manifest", "schema": TRAINING_SCHEMA}

    def stream(split: str) -> Iterable[TrainingExample]:
        for index, value in enumerate(split_factory(split)):
            example = coerce_training_example(value, index)
            if manifest.assignments.get(example.sample_id) != split:
                raise ValueError(f"stream row is assigned to a different split: {example.sample_id}")
            expected_digest = manifest.source_digests.get(example.sample_id)
            if expected_digest and expected_digest != example.source_digest:
                raise ValueError(f"stream source digest mismatch: {example.sample_id}")
            yield example

    model = LeanIRAutoencoder.from_dict(state, config=cfg)
    before = {
        split: evaluate_stream_split(
            model,
            stream(split),
            split=split,
            compile_fn=compile_fn,
            typesafe_fn=typesafe_fn,
            nca_memory=memory,
        )
        for split in ("train", "validation", "canary")
    }
    baseline = copy.deepcopy(before)
    best_state = model.to_dict()
    objective_before = before["validation"] if before["validation"]["sample_count"] else before["train"]
    best_objective = _finite(objective_before.get("objective"), float("inf"))
    history: list[dict[str, Any]] = []
    accepted_epochs = 0
    rejected_epochs = 0
    no_improvement = 0
    for epoch in range(max(0, int(epochs))):
        snapshot = model.to_dict()
        batch: list[TrainingExample] = []
        batch_reports: list[dict[str, Any]] = []
        for example in stream("train"):
            batch.append(example)
            if len(batch) >= max(1, int(batch_size)):
                nca_rewards: dict[str, float] = {}
                for row in batch:
                    feedback = nca_feedback_for_example(memory, row)
                    if feedback.active:
                        nca_rewards[row.sample_id] = feedback.reward
                batch_reports.append(
                    model.train_batch(
                        batch,
                        nca_rewards=nca_rewards,
                    )
                )
                batch = []
        if batch:
            nca_rewards: dict[str, float] = {}
            for row in batch:
                feedback = nca_feedback_for_example(memory, row)
                if feedback.active:
                    nca_rewards[row.sample_id] = feedback.reward
            batch_reports.append(model.train_batch(batch, nca_rewards=nca_rewards))
        after_train = evaluate_stream_split(
            model, stream("train"), split="train", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        after_validation = evaluate_stream_split(
            model, stream("validation"), split="validation", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        after_canary = evaluate_stream_split(
            model, stream("canary"), split="canary", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        gate = canary_gate(before["canary"], after_canary)
        objective_view = after_validation if after_validation["sample_count"] else after_train
        objective = _finite(objective_view.get("objective"), float("inf"))
        improved = objective < best_objective - 1e-9 or accepted_epochs == 0
        if not gate["accepted"]:
            model = LeanIRAutoencoder.from_dict(snapshot, config=cfg)
            model.state["plateau_factor"] = max(0.05, _finite(model.state.get("plateau_factor"), 1.0) * cfg.plateau_factor)
            accepted = False
            rejected_epochs += 1
            no_improvement += 1
        else:
            model.state["accepted_steps"] = int(model.state.get("accepted_steps") or 0) + 1
            accepted = True
            accepted_epochs += 1
            if improved:
                best_objective = objective
                best_state = model.to_dict()
                no_improvement = 0
            else:
                no_improvement += 1
        history.append(
            {
                "epoch": epoch,
                "accepted": accepted,
                "batch_reports": batch_reports,
                "train": after_train if accepted else before["train"],
                "validation": after_validation if accepted else before["validation"],
                "canary": after_canary if accepted else before["canary"],
                "canary_gate": gate,
                "learning_rate": model.learning_rate(),
            }
        )
        before = {
            "train": after_train if accepted else before["train"],
            "validation": after_validation if accepted else before["validation"],
            "canary": after_canary if accepted else before["canary"],
        }
        if no_improvement >= cfg.plateau_patience and rejected_epochs:
            break
    model = LeanIRAutoencoder.from_dict(best_state, config=cfg)
    after = {
        split: evaluate_stream_split(
            model,
            stream(split),
            split=split,
            compile_fn=compile_fn,
            typesafe_fn=typesafe_fn,
            nca_memory=memory,
        )
        for split in ("train", "validation", "canary")
    }
    report = {
        "ok": True,
        "schema": TRAINING_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "streaming": True,
        "config": cfg.to_dict(),
        "manifest": manifest.to_dict(),
        "split_counts": {split: int(before[split].get("stream_count") or before[split].get("sample_count") or 0) for split in before},
        "before": baseline,
        "after": after,
        "history": history,
        "accepted_epochs": accepted_epochs,
        "rejected_epochs": rejected_epochs,
        "learning_rate": model.learning_rate(),
        "holdout": {"accessed": False, "status": "not_measured", "reason": "stream_factory_never_called_for_holdout"},
        "state_digest": _digest(model.to_dict()),
        "state": model.to_dict(),
    }
    if memory is not None:
        objective_row = after["validation"] if after["validation"]["sample_count"] else after["train"]
        report["nca_feedback"] = record_autoencoder_nca_feedback(
            memory,
            problem="autoencoder_stream_training",
            reward=1.0 / (1.0 + max(0.0, _finite(objective_row.get("objective"), 1.0))),
            tokens=int(objective_row.get("sample_count") or 0),
        )
        store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
        store["training_state"] = model.to_dict()
        store["canary_manifest"] = manifest.to_dict()
        store["training_report"] = {key: value for key, value in report.items() if key not in {"history", "state"}}
    return report


def canary_gate(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    max_cross_entropy_regression: float = 0.0,
    max_cosine_regression: float = 0.02,
    max_reconstruction_regression: float = 0.02,
    max_nca_regression: float = 0.05,
) -> dict[str, Any]:
    """Reject a candidate when a frozen canary worsens guarded metrics."""

    before_count = int(before.get("sample_count") or 0)
    after_count = int(after.get("sample_count") or 0)
    if before_count == after_count == 0:
        return {"accepted": True, "status": "not_measured", "regressions": {}, "objective_delta": 0.0}
    regressions: dict[str, float] = {}
    if before_count > 0 and before_count != after_count:
        regressions["sample_coverage_changed"] = 1.0
    for key in ("cross_entropy", "binding_cross_entropy", "rewrite_cross_entropy", "rewrite_expected_cosine_loss", "cosine_similarity", "reconstruction_loss",
                "verifier_success_rate", "nca_reward", "trajectory_cross_entropy", "trajectory_expected_cosine_loss"):
        if before.get(key) is not None:
            try:
                valid = math.isfinite(float(after[key])) and math.isfinite(float(before[key]))
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                regressions[f"{key}_not_finite"] = 1.0
    if before.get("verifier_success_rate") is not None:
        if before.get("verifier_evaluated_count") != after.get("verifier_evaluated_count"):
            regressions["verifier_coverage_changed"] = 1.0
        verifier_drop = _finite(before["verifier_success_rate"]) - _finite(after.get("verifier_success_rate"))
        if verifier_drop > 0:
            regressions["verifier_success_rate"] = verifier_drop
    before_ce = _finite(before.get("cross_entropy"), 0.0)
    after_ce = _finite(after.get("cross_entropy"), 0.0)
    if after_ce - before_ce > max(0.0, float(max_cross_entropy_regression)):
        regressions["cross_entropy"] = after_ce - before_ce
    if before.get("binding_cross_entropy") is not None:
        if (after.get("binding_cross_entropy") is None or
                after.get("binding_sample_count") != before.get("binding_sample_count")):
            regressions["binding_coverage_changed"] = 1.0
        else:
            binding_rise = _finite(after["binding_cross_entropy"]) - _finite(before["binding_cross_entropy"])
            if binding_rise > max(0.0, float(max_cross_entropy_regression)):
                regressions["binding_cross_entropy"] = binding_rise
    before_cos = _finite(before.get("cosine_similarity"), 0.0)
    if before.get("rewrite_cross_entropy") is not None:
        if after.get("rewrite_sample_count") != before.get("rewrite_sample_count"):
            regressions["rewrite_coverage_changed"] = 1.0
        for key in ("rewrite_cross_entropy", "rewrite_expected_cosine_loss"):
            rise = _finite(after.get(key)) - _finite(before.get(key))
            if rise > max(0.0, float(max_cross_entropy_regression)):
                regressions[key] = rise
    after_cos = _finite(after.get("cosine_similarity"), 0.0)
    if "trajectory_step_count" in before:
        for key in ("trajectory_step_count", "trajectory_labeled_step_count", "trajectory_complete_examples"):
            if after.get(key) != before.get(key):
                regressions[key+"_changed"] = 1.0
        for key in ("trajectory_cross_entropy", "trajectory_expected_cosine_loss"):
            rise = _finite(after.get(key)) - _finite(before.get(key))
            if rise > max(0.0, float(max_cross_entropy_regression)):
                regressions[key] = rise
    if before_cos - after_cos > max(0.0, float(max_cosine_regression)):
        regressions["cosine_similarity"] = before_cos - after_cos
    before_rec = _finite(before.get("reconstruction_loss"), 0.0)
    after_rec = _finite(after.get("reconstruction_loss"), 0.0)
    if after_rec - before_rec > max(0.0, float(max_reconstruction_regression)):
        regressions["reconstruction_loss"] = after_rec - before_rec
    if before.get("nca_reward") is not None and after.get("nca_reward") is not None:
        before_nca = _finite(before.get("nca_reward"), 0.5)
        after_nca = _finite(after.get("nca_reward"), 0.5)
        if before_nca - after_nca > max(0.0, float(max_nca_regression)):
            regressions["nca_reward"] = before_nca - after_nca
    return {
        "accepted": not regressions,
        "status": "semantic_scored",
        "regressions": regressions,
        "objective_delta": _finite(before.get("objective"), 0.0) - _finite(after.get("objective"), 0.0),
    }


def train_autoencoder(
    examples: Iterable[Any],
    *,
    state: Optional[Mapping[str, Any]] = None,
    config: Optional[AutoencoderConfig] = None,
    manifest: Optional[CanaryManifest | Mapping[str, Any]] = None,
    epochs: int = 3,
    batch_size: int = 32,
    memory: Optional[MutableMapping[str, Any]] = None,
    compile_fn: Optional[Callable[..., Any]] = None,
    typesafe_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Train with train-only updates and a frozen canary gate.

    The holdout split is intentionally not evaluated here.  Call
    :func:`evaluate_frozen_holdout` after configuration/weights are frozen;
    this mirrors the research repository's custodian-blind holdout policy.
    """

    cfg = config or AutoencoderConfig()
    rows = [coerce_training_example(item, index) for index, item in enumerate(examples)]
    if not rows:
        return {"ok": False, "reason": "empty_dataset", "schema": TRAINING_SCHEMA}
    if manifest is None:
        split_manifest = build_canary_manifest(rows, config=cfg)
    elif isinstance(manifest, CanaryManifest):
        split_manifest = manifest
    else:
        data = dict(manifest)
        split_manifest = CanaryManifest(
            seed=int(data.get("seed") or cfg.seed),
            assignments=dict(data.get("assignments") or {}),
            source_digests=dict(data.get("source_digests") or {}),
            split_digests=dict(data.get("split_digests") or {}),
            corpus_digest=str(data.get("corpus_digest") or ""),
            target_digests=dict(data.get("target_digests") or {}),
            validation_fraction=_finite(data.get("validation_fraction"), cfg.validation_fraction),
            holdout_fraction=_finite(data.get("holdout_fraction"), cfg.holdout_fraction),
            canary_fraction=_finite(data.get("canary_fraction"), cfg.canary_fraction),
            frozen=bool(data.get("frozen", True)),
            schema=str(data.get("schema") or CANARY_SCHEMA),
        )
    manifest_check = validate_canary_manifest(split_manifest, rows)
    if not manifest_check["ok"]:
        return {"ok": False, "reason": "invalid_canary_manifest", "manifest": manifest_check, "schema": TRAINING_SCHEMA}
    splits = split_training_examples(rows, split_manifest)
    model = LeanIRAutoencoder.from_dict(state, config=cfg)
    before = {
        "train": evaluate_model(
            model, splits["train"], split="train", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
        "validation": evaluate_model(
            model, splits["validation"], split="validation", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
        "canary": evaluate_model(
            model, splits["canary"], split="canary", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
    }
    baseline = copy.deepcopy(before)
    best_state = model.to_dict()
    best_objective = _finite((before["validation"] if splits["validation"] else before["train"]).get("objective"), float("inf"))
    history: list[dict[str, Any]] = []
    accepted_epochs = 0
    rejected_epochs = 0
    no_improvement = 0
    total_epochs = max(0, int(epochs))
    for epoch in range(total_epochs):
        snapshot = model.to_dict()
        ordered = list(splits["train"])
        random.Random(cfg.seed + epoch).shuffle(ordered)
        batch_reports: list[dict[str, Any]] = []
        size = max(1, int(batch_size))
        for start in range(0, len(ordered), size):
            batch = ordered[start : start + size]
            nca_rewards: dict[str, float] = {}
            for row in batch:
                feedback = nca_feedback_for_example(memory, row)
                if feedback.active:
                    nca_rewards[row.sample_id] = feedback.reward
            batch_reports.append(model.train_batch(batch, nca_rewards=nca_rewards))
        after_train = evaluate_model(
            model, splits["train"], split="train", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        after_validation = evaluate_model(
            model, splits["validation"], split="validation", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        after_canary = evaluate_model(
            model, splits["canary"], split="canary", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        )
        previous_canary = before["canary"]
        gate = canary_gate(previous_canary, after_canary)
        objective_view = after_validation if splits["validation"] else after_train
        objective = _finite(objective_view.get("objective"), float("inf"))
        improved = objective < best_objective - 1e-9 or accepted_epochs == 0
        if not gate["accepted"] or (accepted_epochs > 0 and not improved and no_improvement >= cfg.plateau_patience):
            model = LeanIRAutoencoder.from_dict(snapshot, config=cfg)
            model.state["plateau_factor"] = max(0.05, _finite(model.state.get("plateau_factor"), 1.0) * cfg.plateau_factor)
            rejected_epochs += 1
            no_improvement += 1
            accepted = False
        else:
            model.state["accepted_steps"] = int(model.state.get("accepted_steps") or 0) + 1
            accepted_epochs += 1
            accepted = True
            if improved:
                best_objective = objective
                best_state = model.to_dict()
                no_improvement = 0
            else:
                no_improvement += 1
        history.append(
            {
                "epoch": epoch,
                "accepted": accepted,
                "batch_reports": batch_reports,
                "train": after_train if accepted else before["train"],
                "validation": after_validation if accepted else before["validation"],
                "canary": after_canary if accepted else previous_canary,
                "canary_gate": gate,
                "learning_rate": model.learning_rate(),
            }
        )
        before = {
            "train": after_train if accepted else before["train"],
            "validation": after_validation if accepted else before["validation"],
            "canary": after_canary if accepted else previous_canary,
        }
        if no_improvement >= cfg.plateau_patience and rejected_epochs:
            break
    model = LeanIRAutoencoder.from_dict(best_state, config=cfg)
    after = {
        "train": evaluate_model(
            model, splits["train"], split="train", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
        "validation": evaluate_model(
            model, splits["validation"], split="validation", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
        "canary": evaluate_model(
            model, splits["canary"], split="canary", compile_fn=compile_fn,
            typesafe_fn=typesafe_fn, nca_memory=memory,
        ),
    }
    report = {
        "ok": True,
        "schema": TRAINING_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "config": cfg.to_dict(),
        "manifest": split_manifest.to_dict(),
        "manifest_validation": manifest_check,
        "split_counts": {key: len(value) for key, value in splits.items()},
        "before": baseline,
        "after": after,
        "history": history,
        "accepted_epochs": accepted_epochs,
        "rejected_epochs": rejected_epochs,
        "learning_rate": model.learning_rate(),
        "holdout": {"accessed": False, "status": "not_measured", "reason": "frozen_holdout_requires_explicit_evaluation"},
        "state_digest": _digest(model.to_dict()),
    }
    if memory is not None:
        objective_row = after["validation"] if after["validation"]["sample_count"] else after["train"]
        report["nca_feedback"] = record_autoencoder_nca_feedback(
            memory,
            problem="autoencoder_training",
            reward=1.0 / (1.0 + max(0.0, _finite(objective_row.get("objective"), 1.0))),
            tokens=int(objective_row.get("sample_count") or 0),
        )
        store = memory.setdefault("nca", {}).setdefault("autoencoder", {})
        store["training_state"] = model.to_dict()
        store["canary_manifest"] = split_manifest.to_dict()
        store["training_report"] = {key: value for key, value in report.items() if key not in {"history"}}
    return {**report, "state": model.to_dict()}


def evaluate_frozen_holdout(
    model_or_state: LeanIRAutoencoder | Mapping[str, Any],
    examples: Iterable[Any],
    *,
    manifest: CanaryManifest | Mapping[str, Any],
    compile_fn: Optional[Callable[..., Any]] = None,
    typesafe_fn: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Explicitly evaluate only the manifest's holdout rows.

    The function does not update state and returns aggregate/per-sample digests
    only.  Callers should seal its result before using it for a benchmark
    decision; no subsequent tuning is permitted by this module.
    """

    model = model_or_state if isinstance(model_or_state, LeanIRAutoencoder) else LeanIRAutoencoder.from_dict(model_or_state)
    rows = [coerce_training_example(item, index) for index, item in enumerate(examples)]
    if not isinstance(manifest, CanaryManifest):
        data = dict(manifest)
        manifest = CanaryManifest(
            seed=int(data.get("seed") or 0),
            assignments=dict(data.get("assignments") or {}),
            source_digests=dict(data.get("source_digests") or {}),
            split_digests=dict(data.get("split_digests") or {}),
            corpus_digest=str(data.get("corpus_digest") or ""),
            target_digests=dict(data.get("target_digests") or {}),
            validation_fraction=_finite(data.get("validation_fraction"), 0.10),
            holdout_fraction=_finite(data.get("holdout_fraction"), 0.10),
            canary_fraction=_finite(data.get("canary_fraction"), 0.10),
            frozen=bool(data.get("frozen", True)),
            schema=str(data.get("schema") or CANARY_SCHEMA),
        )
    validation = validate_canary_manifest(manifest, rows)
    if not validation["ok"]:
        return {"ok": False, "status": "not_measured", "reason": "invalid_manifest", "manifest": validation, "holdout_accessed": False}
    holdout = [row for row in rows if manifest.assignments.get(row.sample_id) == "holdout"]
    result = evaluate_model(model, holdout, split="holdout", compile_fn=compile_fn, typesafe_fn=typesafe_fn)
    return {
        "ok": True,
        "status": result.get("status"),
        "holdout_accessed": True,
        "manifest_digest": manifest.digest,
        "corpus_digest": manifest.corpus_digest,
        "metrics": result,
        "model_state_digest": _digest(model.to_dict()),
        "tuning_allowed_after_access": False,
    }


def typesafe_rank_variations(
    variations: Sequence[Mapping[str, Any]],
    *,
    client: Any = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Use TypeSafe Choice/Noul as a bounded reward model when available.

    The payload contains metrics and short digests, never generated Lean.  A
    missing or malformed TypeSafe response returns ``ok=False`` and callers
    should use deterministic metrics; it is never treated as a proof failure.
    """

    rows = list(variations)
    if not rows:
        return {"ok": False, "reason": "empty", "called_typesafe": False}
    if client is None:
        try:
            from .typesafe_inference import Choice, Noul, TypeSafeClient, typesafe_configured
            if not typesafe_configured():
                return {"ok": False, "reason": "typesafe_not_configured", "called_typesafe": False}
            client = TypeSafeClient(timeout=float(timeout))
        except Exception as exc:
            return {"ok": False, "reason": type(exc).__name__, "called_typesafe": False}
    try:
        try:
            from .typesafe_inference import Choice, Noul
        except Exception:
            # A consumer may inject a TypeSafe-compatible test/client object
            # without installing the accelerator package.  Small records are
            # sufficient for clients that only inspect ``instructions`` and
            # ``criteria``.
            @dataclass(frozen=True)
            class Choice:  # type: ignore[no-redef]
                instructions: str
                criteria: Mapping[str, str]

            @dataclass(frozen=True)
            class Noul:  # type: ignore[no-redef]
                instructions: str
                criteria: Mapping[str, str]
        criteria = {
            str(row.get("id") or index): (
                f"candidate {index}; verifier={row.get('verifier_reward')}; "
                f"ir_cosine={row.get('ir_cosine_m')}; ce={row.get('ce_m')}; "
                f"tokens={row.get('n_tokens')}"
            )
            for index, row in enumerate(rows)
        }
        questions = {
            "best": Choice(
                instructions="Choose the candidate with the best verified semantic reconstruction and safe refactor potential. Never reward invalid proofs.",
                criteria=criteria,
            ),
            "unsafe": Noul(
                instructions="Probability that the selected candidate is unsafe or semantically wrong.",
                criteria={"true": "unverified, malformed, or semantically regressive", "false": "verified and non-regressive"},
            ),
        }
        state = {
            "task": "lean_ir_autoencoder_candidate_rank",
            "variations": [
                {
                    "id": str(row.get("id") or index),
                    "verifier_reward": row.get("verifier_reward"),
                    "ir_cosine_m": row.get("ir_cosine_m"),
                    "ir_ce_m": row.get("ir_ce_m"),
                    "n_tokens": row.get("n_tokens"),
                }
                for index, row in enumerate(rows)
            ],
        }
        response = client.system_one(state, questions)
        choices = getattr(response, "choices", None) or {}
        nouls = getattr(response, "nouls", None) or {}
        best = choices.get("best")
        choice = str(getattr(best, "choice", None) or (best.get("choice") if isinstance(best, Mapping) else ""))
        confidence = _clip01(getattr(best, "confidence", None) if best is not None else 0.0)
        unsafe_value = nouls.get("unsafe")
        noul = _clip01(getattr(unsafe_value, "noul", None) if unsafe_value is not None else 0.0)
        score = confidence * (1.0 - noul)
        return {
            "ok": bool(choice),
            "called_typesafe": True,
            "choice": choice,
            "confidence": confidence,
            "noul": noul,
            "reward": round(score, 12),
            "model": getattr(response, "model", None),
        }
    except Exception as exc:
        return {"ok": False, "reason": type(exc).__name__, "called_typesafe": True}


def typesafe_fuzzy_prove(
    problem: str,
    variations: Sequence[Mapping[str, Any]],
    *,
    client: Any = None,
    timeout: float = 45.0,
    goal: str = "",
    include_goal: bool = True,
) -> dict[str, Any]:
    """Ask TypeSafe for fuzzy theorem/proof-plausibility signals.

    This is an advisor, not a theorem prover in the soundness sense.  It
    receives a bounded theorem/IR summary and typed Choice/Score/Noul
    questions.  The result is explicitly marked ``verified=False`` and must
    still be checked by Lake before a candidate is admitted.
    """

    rows = list(variations)
    if not rows:
        return {"ok": False, "reason": "empty", "called_typesafe": False, "verified": False}

    def field(answer: Any, name: str, default: Any = None) -> Any:
        if isinstance(answer, Mapping):
            return answer.get(name, default)
        return getattr(answer, name, default)

    try:
        if client is None:
            from .typesafe_inference import (
                Choice,
                Noul,
                Score,
                TypeSafeClient,
                typesafe_configured,
            )

            if not typesafe_configured():
                return {
                    "ok": False,
                    "reason": "typesafe_not_configured",
                    "called_typesafe": False,
                    "verified": False,
                }
            client = TypeSafeClient(timeout=float(timeout))
        else:
            try:
                from .typesafe_inference import Choice, Noul, Score
            except Exception:
                @dataclass(frozen=True)
                class Choice:  # type: ignore[no-redef]
                    instructions: str
                    criteria: Mapping[str, Any]

                @dataclass(frozen=True)
                class Noul:  # type: ignore[no-redef]
                    instructions: str
                    criteria: Mapping[str, Any]

                @dataclass(frozen=True)
                class Score:  # type: ignore[no-redef]
                    instructions: str
                    criteria: Sequence[Any]

        candidate_rows: list[dict[str, Any]] = []
        criteria: dict[str, str] = {}
        for index, row in enumerate(rows):
            ident = str(row.get("id") or f"v{index}")
            ir = row.get("ir") if isinstance(row.get("ir"), Mapping) else {}
            if ir:
                op_names = [op for op, _args in _canonical_ops(ir)]
                ir_digest = _digest(ir)
            else:
                op_names = [str(op) for op in (row.get("ir_ops") or ())][:32]
                ir_digest = str(row.get("ir_digest") or _digest(op_names))
            packed = {
                "id": ident,
                "ir_digest": ir_digest,
                "ir_ops": op_names[:32],
                "ir_cosine_m": int(_finite(row.get("ir_cosine_m"))),
                "ce_m": int(_finite(row.get("ce_m"), 1000.0)),
                "n_tokens": int(_finite(row.get("n_tokens"))),
                "lake_ok": row.get("lake_ok"),
                "minimality_reward": _clip01(row.get("minimality_reward")),
            }
            candidate_rows.append(packed)
            criteria[ident] = (
                f"IR ops={','.join(op_names[:12])}; cosine={packed['ir_cosine_m']}; "
                f"CE={packed['ce_m']}; tokens={packed['n_tokens']}; lake={packed['lake_ok']}; "
                f"minimality={packed['minimality_reward']:.3f}"
            )
        goal_text = _safe_arg(goal or problem, max_chars=480) if include_goal else ""
        state: dict[str, Any] = {
            "task": "lean_ir_fuzzy_theorem_assessment",
            "problem_digest": _text_digest(problem),
            "goal_digest": _text_digest(goal or problem),
            "goal_preview": goal_text,
            "candidates": candidate_rows,
            "constraints": {
                "lake_is_proof_authority": True,
                "typesafe_is_fuzzy_advisor": True,
                "reject_sorry_or_unsafe": True,
            },
        }
        questions = {
            "best": Choice(
                instructions="Choose the candidate most likely to preserve the theorem while minimizing a verified Lean/IR refactor. Do not treat shortness alone as correctness.",
                criteria=criteria,
            ),
            "semantic": Score(
                instructions="Score the selected candidate's semantic/theorem plausibility, not its style. Use the rubric from 0 to 4.",
                criteria=(
                    "0: contradicted, malformed, or obviously unsafe",
                    "1: weak or incomplete plausibility",
                    "2: plausible but uncertain",
                    "3: strong theorem-preservation evidence",
                    "4: extremely strong fuzzy confidence, still not a proof",
                ),
            ),
            "unsafe": Noul(
                instructions="Is the selected candidate likely unsafe, semantically regressive, or invalid despite its metrics?",
                criteria={"true": "unsafe or likely invalid", "false": "not obviously unsafe"},
            ),
            "solves_goal": Noul(
                instructions="Does the selected candidate plausibly solve the stated theorem goal? This is a fuzzy judgment only.",
                criteria={"true": "likely solves the goal", "false": "likely does not solve the goal"},
            ),
        }
        response = client.system_one(state, questions)
        choices = getattr(response, "choices", None) or {}
        scores = getattr(response, "scores", None) or {}
        nouls = getattr(response, "nouls", None) or {}
        best = choices.get("best") if isinstance(choices, Mapping) else None
        choice = str(field(best, "choice", "") or "")
        confidence = _clip01(field(best, "confidence", 0.0))
        semantic_answer = scores.get("semantic") if isinstance(scores, Mapping) else None
        raw_score = _finite(field(semantic_answer, "score", 0.0))
        semantic_score = _clip01(raw_score / 4.0 if raw_score > 1.0 else raw_score)
        unsafe_answer = nouls.get("unsafe") if isinstance(nouls, Mapping) else None
        solves_answer = nouls.get("solves_goal") if isinstance(nouls, Mapping) else None
        unsafe = _clip01(field(unsafe_answer, "noul", 0.0))
        solves = _clip01(field(solves_answer, "noul", 0.0))
        candidate_rewards = {
            str(row["id"]): _clip01(
                0.45 * semantic_score
                + 0.25 * confidence * (1.0 if str(row["id"]) == choice else 0.5)
                + 0.20 * solves
                + 0.10 * (1.0 - unsafe)
            )
            for row in candidate_rows
        }
        return {
            "ok": bool(choice),
            "called_typesafe": True,
            "choice": choice,
            "confidence": confidence,
            "semantic_score": semantic_score,
            "unsafe": unsafe,
            "solves_goal": solves,
            "candidate_rewards": candidate_rewards,
            "reward": candidate_rewards.get(choice, 0.0),
            "proof_authority": "soft_typesafe",
            "verified": False,
            "requires_lake": True,
            "model": getattr(response, "model", None),
            "usage": dict(getattr(response, "usage", {}) or {}),
        }
    except Exception as exc:
        return {
            "ok": False,
            "reason": type(exc).__name__,
            "called_typesafe": True,
            "verified": False,
            "requires_lake": True,
        }


def score_candidate(
    row: Mapping[str, Any],
    *,
    verifier_reward: Optional[float] = None,
    typesafe_reward: Optional[float] = None,
    fuzzy_prover_reward: Optional[float] = None,
    minimality_reward: Optional[float] = None,
) -> dict[str, Any]:
    """Combine signals without allowing a soft reward to bypass verification."""

    verifier = verifier_reward
    if verifier is None and row.get("lake_ok") is not None:
        verifier = 1.0 if bool(row.get("lake_ok")) else 0.0
    semantic = (
        0.40 * _clip01(_finite(row.get("cosine_m"), 0.0) / 1000.0)
        + 0.30 * _clip01(_finite(row.get("ir_cosine_m"), 0.0) / 1000.0)
        + 0.20 * (1.0 - _clip01(_finite(row.get("ce_m"), 1000.0) / 1000.0))
        + 0.10 * (1.0 - _clip01(_finite(row.get("ir_ce_m"), 1000.0) / 1000.0))
    )
    minimality = (
        _clip01(minimality_reward)
        if minimality_reward is not None
        else _clip01(row.get("minimality_reward"))
    )
    fuzzy = fuzzy_prover_reward
    if fuzzy is None:
        fuzzy = _typesafe_reward(row.get("fuzzy_prover_reward"))
    if fuzzy is None:
        fuzzy = _typesafe_reward(row.get("typesafe_reward"))
    if verifier is None:
        base = 0.78 * semantic + 0.12 * minimality
        admission = "unverified"
    elif _clip01(verifier) <= 0.0:
        base = 0.0
        admission = "rejected"
    else:
        # Once Lake has proved the candidate, minimality is allowed to decide
        # among semantically plausible proofs.  Before that point it is only
        # a bounded ranking hint.
        base = 0.55 * _clip01(verifier) + 0.25 * semantic + 0.20 * minimality
        admission = "verified"
    soft_reward = typesafe_reward if typesafe_reward is not None else fuzzy
    if soft_reward is not None:
        base = 0.85 * base + 0.15 * _clip01(soft_reward)
    return {
        "reward": _clip01(base),
        "semantic_reward": _clip01(semantic),
        "verifier_reward": verifier,
        "typesafe_reward": typesafe_reward,
        "fuzzy_prover_reward": fuzzy,
        "minimality_reward": minimality,
        "admission": admission,
    }


def minimality_score(
    row: Mapping[str, Any],
    *,
    reference_tokens: Optional[int] = None,
    reference_ops: Optional[int] = None,
) -> float:
    """Reward compression relative to the source, never validity by itself.

    The score is intentionally relative: a candidate that is shorter than the
    source gets credit, but an invalid candidate cannot become admissible from
    this metric because :func:`score_candidate` hard-gates Lake failures.
    """

    source_tokens = max(0, int(reference_tokens if reference_tokens is not None else _finite(row.get("source_tokens"))))
    source_ops = max(0, int(reference_ops if reference_ops is not None else _finite(row.get("source_ops"))))
    candidate_tokens = max(
        0,
        int(
            _finite(
                row.get("lake_body_tokens")
                or row.get("body_tokens")
                or row.get("lake_tokens")
                or row.get("n_tokens")
            )
        ),
    )
    raw_ops = row.get("ir_ops") or row.get("n_ops")
    candidate_ops = (
        len(raw_ops)
        if isinstance(raw_ops, (list, tuple, set, frozenset))
        else max(0, int(_finite(raw_ops)))
    )
    token_gain = 0.0 if source_tokens <= 0 else _clip01(1.0 - candidate_tokens / float(source_tokens))
    op_gain = 0.0 if source_ops <= 0 else _clip01(1.0 - candidate_ops / float(source_ops))
    if source_tokens <= 0 and source_ops <= 0:
        return 0.0
    if source_tokens <= 0:
        return op_gain
    if source_ops <= 0:
        return token_gain
    return _clip01(0.70 * token_gain + 0.30 * op_gain)


__all__ = [
    "AutoencoderConfig",
    "CanaryManifest",
    "CANARY_SCHEMA",
    "LeanIRAutoencoder",
    "LossBreakdown",
    "MODEL_SCHEMA",
    "NCAFeedback",
    "TRAINING_SCHEMA",
    "TrainingExample",
    "build_canary_manifest",
    "canary_gate",
    "coerce_training_example",
    "evaluate_frozen_holdout",
    "evaluate_model",
    "evaluate_stream_split",
    "learning_rate_for_step",
    "loss_for_example",
    "merge_model_states",
    "minimality_score",
    "advance_autoencoder_nca",
    "nca_feedback_for_example",
    "record_autoencoder_nca_feedback",
    "score_candidate",
    "split_training_examples",
    "train_autoencoder",
    "train_autoencoder_stream",
    "typesafe_fuzzy_prove",
    "typesafe_rank_variations",
    "validate_canary_manifest",
]
