"""Opt-in source-DAG-conditioned sparse edit selection, not a graph autoencoder.

Ordered, hashed neighborhoods are fixed features; CE/cosine trains the readout.
Every context describes the original source, so decoding is exactly one step.
No target DAG, candidate compilation, or teacher is available during prediction.
"""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import dataclass
import hashlib
import math
import re
import textwrap
from typing import Any, Mapping

from .expr_dag import CODEC, _bytes, validate_dag
from .rewrite_policy import body_of, choices, loss_and_gradient, probabilities, validate_templates
from .solver_feedback import source_digest
from .structural_training import _checked_export, _envelope, _sha

FEATURE_SCHEMA = "jevops-source-dag-neighborhoods/v1"
MODEL_SCHEMA = "jevops-structural-edit-policy/v1"
BUCKETS, ROUNDS = 64, 4
POSITIONS = {"app": (1, 2), "lam": (3, 4), "forall": (3, 4),
             "let": (3, 4, 5), "mdata": (2,), "proj": (3,)}
FEATURE_KEY = re.compile(r"(?:proof|type)/r[0-4]/(?:hist|root)/(?:[0-9]|[1-5][0-9]|6[0-3])\Z")


def digest(value: Any) -> str:
    return hashlib.sha256(_bytes(value)).hexdigest()


def graph_features(wire: Mapping[str, Any]) -> dict[str, float]:
    """Bounded, numbering/name-insensitive, lossy features of proof and type.

    Scope is represented by de Bruijn indices, not by treating shared variables
    as semantically identical. Hash collisions and discarded names mean these
    features cannot certify equality or truth. Counts visit DAG nodes, not an
    exponentially expanded tree. No corpus-fitted vocabulary/normalizer is used.
    """
    validate_dag(wire, environment=wire["environment"])
    if len(wire["roots"]) != 2:
        raise ValueError("source proof/type roots required")
    universes = []
    for row in wire["levels"]:
        tag = row[0]
        children = [universes[int(i)] for i in row[1:]] if tag in {"succ", "max", "imax"} else []
        universes.append(digest([tag, children]))  # Parameter names deliberately omitted.
    edges, labels = [], []
    for row in wire["expressions"]:
        tag = row[0]
        edges.append([int(row[p]) for p in POSITIONS.get(tag, ())])
        payload = []
        if tag == "bvar":
            payload = [min(8, int(row[1]))]
        elif tag in {"lam", "forall", "let"}:
            payload = [row[2]]
        elif tag == "sort":
            payload = [universes[int(row[1])]]
        elif tag == "const":
            payload = [universes[int(i)] for i in row[2]]
        elif tag == "proj":
            payload = [min(8, int(row[2]))]
        # No names, literal values, metadata contents, theorem IDs or source hashes.
        labels.append(digest([tag, payload]))
    reachable = []
    for root in wire["roots"]:
        seen, pending = set(), [int(root)]
        while pending:
            i = pending.pop()
            if i not in seen:
                seen.add(i)
                pending.extend(edges[i])
        reachable.append(sorted(seen))
    features: dict[str, float] = {}
    for radius in range(ROUNDS + 1):
        for side, root, nodes in zip(("proof", "type"), wire["roots"], reachable):
            block = f"{side}/r{radius}/"
            counts = Counter(int(labels[i][:8], 16) % BUCKETS for i in nodes)
            for bucket, count in sorted(counts.items()):
                features[block + f"hist/{bucket}"] = math.sqrt(count / len(nodes))
            features[block + f"root/{int(labels[int(root)][:8], 16) % BUCKETS}"] = 1.0
        if radius < ROUNDS:
            labels = [digest([label, [labels[j] for j in children]]) for label, children in zip(labels, edges)]
    norm = math.sqrt(sum(v*v for v in features.values()))
    return {k: v/norm for k, v in sorted(features.items())}


@dataclass(frozen=True)
class SourceDAGContext:
    source_sha256: str
    environment_sha256: str
    toolchain: tuple[str, str]
    dag_sha256: str
    features: tuple[tuple[str, float], ...]
    feature_schema: str = FEATURE_SCHEMA

    def validate(self, source: str, environment: str, toolchain: tuple[str, str]) -> None:
        if (self.source_sha256 != source_digest(source) or self.environment_sha256 != environment
                or self.toolchain != toolchain or self.feature_schema != FEATURE_SCHEMA
                or not _sha(self.dag_sha256)):
            raise ValueError("stale/mismatched source DAG context")
        if not 1 <= len(self.features) <= 1024 or len(dict(self.features)) != len(self.features):
            raise ValueError("invalid graph feature count")
        for key, value in self.features:
            if (not isinstance(key, str) or not FEATURE_KEY.fullmatch(key)
                    or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("invalid graph feature")
        if not math.isclose(sum(v*v for _, v in self.features), 1.0, abs_tol=1e-9):
            raise ValueError("unnormalized graph features")

    def receipt(self) -> dict[str, Any]:
        return {"source_sha256": self.source_sha256, "environment_sha256": self.environment_sha256,
                "toolchain": list(self.toolchain), "dag_sha256": self.dag_sha256,
                "feature_schema": self.feature_schema, "features": dict(self.features),
                "features_sha256": digest(dict(self.features))}


def source_context(source: str, receipt: Mapping[str, Any], *, environment_sha256: str) -> SourceDAGContext:
    """Use a fresh trusted compiler receipt; hashes do not authenticate callbacks."""
    if not _sha(environment_sha256):
        raise ValueError("dependency environment fingerprint required")
    declaration = _envelope(source, source)
    report, wire = _checked_export(receipt, source, declaration, environment_sha256,
                                   hashlib.sha256(CODEC.read_bytes()).hexdigest(), 50_000)
    return SourceDAGContext(source_digest(source), environment_sha256,
                            (wire["lean_version"], wire["lean_githash"]), report["dag_sha256"],
                            tuple(graph_features(wire).items()))


class StructuralEditPolicy:
    """One-step optional structural head over the existing autoencoder edit grammar.

    Low-level supervised API: callers must supply verified training-only targets.
    The isolated comparison runner below is responsible for compiler admission.
    Missing or stale context fails, rather than silently using another model.
    """
    def __init__(self, templates, *, environment_sha256: str, toolchain: tuple[str, str], structural: bool):
        if not _sha(environment_sha256) or type(structural) is not bool:
            raise ValueError("invalid structural policy configuration")
        if (not isinstance(toolchain, tuple) or len(toolchain) != 2
                or any(not isinstance(s, str) or not s or len(s) > 256 for s in toolchain)):
            raise ValueError("invalid toolchain identity")
        self.templates = copy.deepcopy(validate_templates(templates))
        self.environment = environment_sha256
        self.toolchain = toolchain
        self.structural = structural
        self.weights: dict[str, float] = {}
        self.steps = 0

    def rows(self, source: str, context: SourceDAGContext | None = None):
        if self.structural and not isinstance(context, SourceDAGContext):
            raise ValueError("structural policy requires source DAG context")
        if context is not None:
            context.validate(source, self.environment, self.toolchain)
        rows = choices(source, self.templates)
        if self.structural:
            for row in rows[1:]:
                row["features"].update({row["rule_id"] + "|dag:" + k: v for k, v in context.features})
        return rows

    def objective(self, source: str, target: str, context=None):
        if body_of(source)[0] != body_of(target)[0]:
            raise ValueError("training target changes theorem envelope")
        return loss_and_gradient(self.weights, self.rows(source, context), body_of(target)[1],
                                 smoothing=.02, cosine_weight=.35)

    def train_step(self, source: str, target: str, context=None, *, split: str, learning_rate: float = .15):
        if split != "train":
            raise ValueError("only the training split may update a structural head")
        if type(learning_rate) not in (int, float) or not math.isfinite(learning_rate) or not 0 < learning_rate <= .25:
            raise ValueError("invalid learning rate")
        result = self.objective(source, target, context)
        if result is None:
            raise ValueError("unreachable one-step teacher; no update performed")
        gradient = result["gradient"]
        scale = min(1.0, 1.0 / (math.sqrt(sum(v*v for v in gradient.values())) or 1.0))
        updated = dict(self.weights)
        for key, value in gradient.items():
            updated[key] = updated.get(key, 0.0)*(1-learning_rate*.0001) - learning_rate*scale*value
        if not all(math.isfinite(v) for v in updated.values()):
            raise ValueError("nonfinite structural update")
        self.weights = updated
        self.steps += 1
        return {k: v for k, v in result.items() if k != "gradient"}

    def predict(self, source: str, context=None, *, ablation: str = "none") -> dict[str, Any]:
        if ablation not in {"none", "drop_graph", "zero_weights"}:
            raise ValueError("unknown ablation")
        rows = self.rows(source, context)
        weights = ({} if ablation == "zero_weights" else
                   {k: v for k, v in self.weights.items() if ablation != "drop_graph" or "|dag:" not in k})
        probs = probabilities(weights, rows)
        i = max(range(len(rows)), key=lambda j: probs[j])
        prefix, _ = body_of(source)
        return {"source": prefix + "\n" + textwrap.indent(rows[i]["body"], "  ") + "\n",
                "choice": i, "probability": probs[i], "choice_count": len(rows),
                "teacher_used": False, "solver_used": False, "max_edits": 1, "ablation": ablation,
                "structural_features_used": self.structural and ablation == "none"}

    def to_dict(self):
        return {"schema": MODEL_SCHEMA, "feature_schema": FEATURE_SCHEMA, "structural": self.structural,
                "environment_sha256": self.environment, "toolchain": list(self.toolchain),
                "templates": copy.deepcopy(self.templates), "weights": dict(sorted(self.weights.items())), "steps": self.steps}

    @classmethod
    def from_dict(cls, state):
        if (not isinstance(state, dict) or set(state) != {"schema", "feature_schema", "structural", "environment_sha256",
                                                         "toolchain", "templates", "weights", "steps"}
                or state["schema"] != MODEL_SCHEMA or state["feature_schema"] != FEATURE_SCHEMA
                or not isinstance(state["toolchain"], list) or type(state["steps"]) is not int or state["steps"] < 0):
            raise ValueError("invalid structural checkpoint")
        model = cls(state["templates"], environment_sha256=state["environment_sha256"],
                    toolchain=tuple(state["toolchain"]), structural=state["structural"])
        weights = state["weights"]
        prefixes = tuple(t["id"] + "|" for t in model.templates)
        if not isinstance(weights, dict) or len(weights) > 65_536:
            raise ValueError("invalid structural weights")
        for key, value in weights.items():
            if (not isinstance(key, str) or len(key) > 4096 or not key.startswith(prefixes)
                    or type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6
                    or ("|dag:" in key and (not model.structural or not FEATURE_KEY.fullmatch(key.split("|dag:", 1)[1])))):
                raise ValueError("invalid structural weight")
        model.weights, model.steps = dict(weights), state["steps"]
        return model
