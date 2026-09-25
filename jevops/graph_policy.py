"""Optional CPU graph learner over source-only, closed Lean expression DAGs.

This is a lossy proposal model, not a lossless autoencoder or typed-by-construction
decoder. The bounded lexical edit/copy grammar is unchanged; Lean must check its
outputs. Training targets and compiler callbacks belong to trusted infrastructure.
No solver, target DAG, provider, or candidate compilation runs during prediction.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math
import textwrap

import torch
from torch import nn

from .expr_dag import CODEC, _bytes, validate_dag
from .jev_surrogate import JeVFeedbackSpec, feedback_utilities, make_request
from .rewrite_policy import _cosine_cost, body_of, choices, validate_templates
from .solver_feedback import source_digest
from .structural_policy import POSITIONS, digest
from .structural_training import _checked_export, _envelope, _sha

SCHEMA = "jevops-trained-source-dag-policy/v1"
MULTISCALE_SCHEMA = "jevops-trained-source-dag-policy/v2"
GRAPH_SCHEMA = "jevops-ordered-binder-dag-tensors/v1"
MAX_NODES, MAX_WIRE_BYTES = 4096, 1_048_576
TAGS = ("bvar", "sort", "const", "app", "lam", "forall", "let", "nat", "string", "mdata", "proj")
BINDERS = (None, "explicit", "implicit", "strictImplicit", "instance", False, True)
LEXICAL = ("bias", "first", "last", "nested", "prev:bos", "next:eos",
           "domain:Prop", "domain:Nat", "domain:Int", "domain:Bool", "domain:List", "domain:Fin", "domain:PLift")


@dataclass(frozen=True)
class GraphContext:
    """Immutable source-bound input. Digests bind data; they are not signatures."""

    source_sha256: str
    environment_sha256: str
    toolchain: tuple[str, str]
    dag_sha256: str
    wire_bytes: bytes

    def wire(self, source, environment, toolchain):
        if (self.source_sha256 != source_digest(source) or self.environment_sha256 != environment
                or self.toolchain != toolchain or type(self.wire_bytes) is not bytes
                or not 1 <= len(self.wire_bytes) <= MAX_WIRE_BYTES
                or hashlib.sha256(self.wire_bytes).hexdigest() != self.dag_sha256):
            raise ValueError("stale/mismatched graph context")
        wire = json.loads(self.wire_bytes)
        validate_dag(wire, environment=wire["environment"], toolchain=toolchain, node_budget=MAX_NODES)
        if len(wire["roots"]) != 2:
            raise ValueError("source proof/type roots required")
        return wire


def graph_context(source, receipt, *, environment_sha256):
    if not _sha(environment_sha256):
        raise ValueError("dependency environment fingerprint required")
    declaration = _envelope(source, source)
    report, wire = _checked_export(receipt, source, declaration, environment_sha256,
                                   hashlib.sha256(CODEC.read_bytes()).hexdigest(), MAX_NODES)
    context = GraphContext(source_digest(source), environment_sha256,
                           (wire["lean_version"], wire["lean_githash"]), report["dag_sha256"], _bytes(wire))
    context.wire(source, environment_sha256, context.toolchain)
    return context


def graph_tensors(wire):
    """O(nodes + edges), never expand shared subtrees into occurrences.

    Preserve ordered child roles, binder flags and local de Bruijn indices.
    A shared bvar denotes a *relative index*, not one globally identified local.
    Binder names and theorem/source IDs are excluded. Payload hashing is lossy;
    these tensors cannot certify alpha equivalence, type equality, or truth.
    """
    validate_dag(wire, environment=wire["environment"], node_budget=MAX_NODES)
    if len(wire["roots"]) != 2:
        raise ValueError("source proof/type roots required")
    levels = []
    for row in wire["levels"]:
        levels.append(digest([row[0], [levels[int(j)] for j in row[1:]]
                              if row[0] in {"succ", "max", "imax"} else row[1:]]))
    tags, payloads, binders, numbers, edges, bound_edges = [], [], [], [], [], []
    for row in wire["expressions"]:
        tag = row[0]
        children = [int(row[p]) for p in POSITIONS.get(tag, ())]
        tags.append(TAGS.index(tag))
        flag = row[2] if tag in {"lam", "forall", "let"} else None
        binders.append(next(i for i, b in enumerate(BINDERS) if type(b) is type(flag) and b == flag))
        payload = []
        index = int(row[1]) if tag == "bvar" else 0
        if tag == "sort":
            payload = [levels[int(row[1])]]
        elif tag == "const":
            payload = [row[1], [levels[int(i)] for i in row[2]]]
        elif tag in {"nat", "string", "bvar"}:
            payload = [row[1]]
        elif tag == "proj":
            payload = row[1:3]
        payloads.append(int(digest([tag, payload])[:8], 16) % 256)
        numbers.append([math.log1p(index) / math.log(65536), float(tag == "bvar")])
        edges.append(children + [-1] * (3-len(children)))
        bound_edges.append([float(tag in {"lam", "forall", "let"} and j == len(children)-1)
                            for j in range(3)])
    reachable = []
    for root in wire["roots"]:
        seen, pending = set(), [int(root)]
        while pending:
            i = pending.pop()
            if i not in seen:
                seen.add(i)
                pending.extend(j for j in edges[i] if j >= 0)
        reachable.append(torch.tensor(sorted(seen), dtype=torch.long))
    return {"tags": torch.tensor(tags), "payloads": torch.tensor(payloads), "binders": torch.tensor(binders),
            "numbers": torch.tensor(numbers, dtype=torch.float64), "edges": torch.tensor(edges),
            "bound_edges": torch.tensor(bound_edges, dtype=torch.float64),
            "roots": [int(i) for i in wire["roots"]], "reachable": reachable}


class DAGEncoder(nn.Module):
    def __init__(self, width, rounds, pooling="last"):
        super().__init__()
        self.pooling = pooling
        self.tag = nn.Embedding(len(TAGS), width)
        self.payload = nn.Embedding(256, width)
        self.binder = nn.Embedding(len(BINDERS), width)
        self.numeric = nn.Linear(2, width, bias=False)
        # Separate ordered-edge maps and a map for crossing into a binder body.
        self.layers = nn.ModuleList(nn.ModuleList(nn.Linear(width, width, bias=False) for _ in range(5))
                                    for _ in range(rounds))

    def pooled_stages(self, graph):
        """Retain differentiable radius-zero and intermediate representations."""
        def pool(h):
            return torch.cat([part for root, ids in zip(graph["roots"], graph["reachable"])
                              for part in (h[root], h[ids].mean(dim=0))])
        h = torch.tanh(self.tag(graph["tags"]) + self.payload(graph["payloads"])
                       + self.binder(graph["binders"]) + self.numeric(graph["numbers"]))
        stages = [pool(h)]
        edges = graph["edges"]
        for layer in self.layers:
            message = layer[0](h)
            for slot in range(3):
                child = h[edges[:, slot].clamp_min(0)] * (edges[:, slot] >= 0).unsqueeze(1)
                message = message + layer[slot+1](child)
                message = message + layer[4](child) * graph["bound_edges"][:, slot].unsqueeze(1)
            h = torch.tanh(message / 2)
            stages.append(pool(h))
        return stages

    def forward(self, graph):
        stages = self.pooled_stages(graph)
        return stages[-1] if self.pooling == "last" else torch.cat(stages)


def candidate_loss(logits, rows, target, *, utilities=None, reference_logits=None,
                   surrogate_weight=0.0, kl_weight=0.0):
    """CE + operation-bag cosine + bounded expected utility and reference KL.

    Utilities and reference logits are detached constants. Cosine is a proxy,
    never a semantic equivalence test. Supervised CE/cosine are never disabled.
    """
    for v in (surrogate_weight, kl_weight):
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1:
            raise ValueError("invalid auxiliary loss weight")
    if logits.shape != (len(rows),) or not torch.isfinite(logits).all():
        raise ValueError("invalid candidate logits")
    normalize = lambda text: "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    labels = [i for i, row in enumerate(rows) if normalize(row["body"]) == normalize(target)]
    if len(labels) != 1:
        raise ValueError("unreachable one-step teacher")
    logs = torch.log_softmax(logits, dim=0)
    p = logs.exp()
    desired = torch.full_like(logits, .02 / len(rows))
    desired[labels[0]] += .98
    ce = -(desired * logs).sum()
    cosine = (p * logits.new_tensor([_cosine_cost(row["body"], target) for row in rows])).sum()
    expected, kl = logits.new_zeros(()), logits.new_zeros(())
    if utilities is not None:
        if (not isinstance(utilities, (list, tuple)) or len(utilities) != len(rows)
                or any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in utilities)):
            raise ValueError("invalid utility coverage/range")
        expected = (p * logits.new_tensor(utilities)).sum()
    elif surrogate_weight:
        raise ValueError("surrogate feedback required")
    if reference_logits is not None:
        if reference_logits.shape != logits.shape or not torch.isfinite(reference_logits).all():
            raise ValueError("invalid frozen reference")
        kl = (p * (logs - torch.log_softmax(reference_logits.detach(), dim=0))).sum()
    elif kl_weight:
        raise ValueError("frozen reference required")
    return {"total": ce + .35*cosine - surrogate_weight*expected + kl_weight*kl,
            "cross_entropy": ce, "expected_cosine_loss": cosine, "expected_utility": expected,
            "reference_kl": kl, "label": labels[0], "choice_count": len(rows)}


def metrics(loss):
    return {key: float(value.detach()) if isinstance(value, torch.Tensor) else value for key, value in loss.items()}


class GraphEditPolicy(nn.Module):
    """Learn an encoder and readout; preserve the baseline one-edit copy grammar.

    Low-level supervised API: caller must admit training-only teacher pairs.
    The isolated experiment runner provides that boundary, not this constructor.
    CPU/float64, bounded graphs and plain JSON checkpoints keep this prototype
    inspectable; this is not a trillion-token throughput implementation.
    """
    def __init__(self, templates, *, environment_sha256, toolchain, width=16, rounds=2,
                 seed=17, freeze_encoder=False, pooling="last"):
        super().__init__()
        if (not _sha(environment_sha256) or not isinstance(toolchain, tuple) or len(toolchain) != 2
                or any(not isinstance(s, str) or not s or len(s) > 256 for s in toolchain)
                or type(width) is not int or not 4 <= width <= 64
                or type(rounds) is not int or not 0 <= rounds <= 4
                or type(seed) is not int or not 0 <= seed < 2**32 or type(freeze_encoder) is not bool
                or not isinstance(pooling, str) or pooling not in {"last", "multiscale"}):
            raise ValueError("invalid graph model configuration")
        self.templates = copy.deepcopy(validate_templates(templates))
        self.environment, self.toolchain = environment_sha256, toolchain
        self.width, self.rounds, self.seed, self.freeze_encoder = width, rounds, seed, freeze_encoder
        self.pooling = pooling
        self.steps = 0
        # Keep model construction from changing the caller's RNG stream.
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(seed)
            self.encoder = DAGEncoder(width, rounds, pooling).double()
            scales = 1 if pooling == "last" else rounds+1
            self.head = nn.Linear(4*width*scales + len(LEXICAL), max(1, len(self.templates)), bias=False).double()
            nn.init.zeros_(self.head.weight)  # Initial tie abstains to identity.
        if freeze_encoder:
            self.encoder.requires_grad_(False)

    def rows(self, source, context):
        if not isinstance(source, str) or len(source.encode()) > 65_536 or not isinstance(context, GraphContext):
            raise ValueError("source graph context required")
        context.wire(source, self.environment, self.toolchain)
        _envelope(source, source)
        return choices(source, self.templates)

    def logits(self, source, context, *, ablation="none"):
        if ablation not in {"none", "drop_graph", "zero_weights"}:
            raise ValueError("unknown graph ablation")
        rows = self.rows(source, context)
        graph = graph_tensors(context.wire(source, self.environment, self.toolchain))
        encoded = self.encoder(graph)
        if ablation == "drop_graph":
            encoded = torch.zeros_like(encoded)
        indexes = {rule["id"]: i for i, rule in enumerate(self.templates)}
        values = [self.head.weight.sum() * 0]
        for row in rows[1:]:
            prefix = row["rule_id"] + "|"
            lexical = encoded.new_tensor([row["features"].get(prefix + key, 0.0) for key in LEXICAL])
            values.append((self.head.weight[indexes[row["rule_id"]]] * torch.cat((encoded, lexical))).sum())
        logits = torch.stack(values)
        return rows, logits * 0 if ablation == "zero_weights" else logits

    def objective(self, source, target, context, **kwargs):
        _envelope(source, target)
        rows, logits = self.logits(source, context)
        return candidate_loss(logits, rows, body_of(target)[1], **kwargs)

    def feedback_request(self, source, context, *, spec: JeVFeedbackSpec, split):
        self.rows(source, context)
        if spec.context_sha256 != self.environment:
            raise ValueError("JeV environment mismatch")
        request = make_request(source, self.templates, {}, spec=spec, split=split, temperature=1.0, step=self.steps)
        request["policy_sha256"] = digest({"model": self.to_dict(), "dag": context.dag_sha256})
        request["request_id"] = digest({k: v for k, v in request.items() if k != "request_id"})
        return request

    def train_step(self, source, target, context, *, split, learning_rate=.15,
                   feedback=None, spec=None, surrogate_weight=0.0, reference=None, kl_weight=0.0):
        if split != "train":
            raise ValueError("only the training split may update the graph model")
        if (type(learning_rate) not in (int, float) or not math.isfinite(learning_rate)
                or not 0 < learning_rate <= .25):
            raise ValueError("invalid learning rate")
        utilities, ref_logits = None, None
        if feedback is not None:
            if not isinstance(spec, JeVFeedbackSpec):
                raise ValueError("pinned JeV spec required")
            request = self.feedback_request(source, context, spec=spec, split=split)
            utilities = feedback_utilities(request, feedback)
        if reference is not None:
            if (not isinstance(reference, GraphEditPolicy) or reference is self
                    or reference.templates != self.templates or reference.environment != self.environment
                    or reference.toolchain != self.toolchain):
                raise ValueError("incompatible frozen reference")
            with torch.no_grad():
                _, ref_logits = reference.logits(source, context)
        result = self.objective(source, target, context, utilities=utilities, reference_logits=ref_logits,
                                surrogate_weight=surrogate_weight, kl_weight=kl_weight)
        return self._apply_loss(result, learning_rate)

    def train_batch(self, examples, *, split, learning_rate=.15):
        """One atomic mean-gradient update, without per-example clipping/order bias.

        Low-level admitted-supervision API, not a source of verified teachers.
        All rows must be training rows; validate this before reading any targets.
        The single-example API remains available for request-bound JeV feedback.
        ``steps`` counts optimizer updates, not examples or epochs.
        """
        if split != "train":
            raise ValueError("only the training split may update the graph model")
        if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 32:
            raise ValueError("invalid graph batch size")
        for row in examples:
            if (not isinstance(row, dict) or set(row) != {"source", "target", "context", "split"}
                    or row["split"] != "train"):
                raise ValueError("graph batch requires training rows only")
        losses = [self.objective(row["source"], row["target"], row["context"]) for row in examples]
        result = {key: torch.stack([loss[key] for loss in losses]).mean()
                  for key in ("total", "cross_entropy", "expected_cosine_loss", "expected_utility", "reference_kl")}
        result["sample_count"] = len(examples)
        return self._apply_loss(result, learning_rate)

    def _apply_loss(self, result, learning_rate):
        if (type(learning_rate) not in (int, float) or not math.isfinite(learning_rate)
                or not 0 < learning_rate <= .25):
            raise ValueError("invalid learning rate")
        parameters = [p for p in self.parameters() if p.requires_grad]
        gradients = torch.autograd.grad(result["total"], parameters, allow_unused=True)
        present = [g for g in gradients if g is not None]
        norm = torch.sqrt(sum((g*g).sum() for g in present))
        if not torch.isfinite(norm):
            raise ValueError("nonfinite graph gradient")
        scale = min(1.0, 1.0 / (float(norm) or 1.0))
        updated = [p.detach() - learning_rate*scale*g if g is not None else p.detach().clone()
                   for p, g in zip(parameters, gradients)]
        if any(not torch.isfinite(p).all() or (p.abs() > 1e6).any() for p in updated):
            raise ValueError("nonfinite or oversized graph update")
        # Commit only after the complete objective/update is validated.
        with torch.no_grad():
            for parameter, value in zip(parameters, updated):
                parameter.copy_(value)
        self.steps += 1
        return {**metrics(result), "gradient_norm": float(norm), "gradient_scale": scale}

    def predict(self, source, context, *, ablation="none"):
        with torch.no_grad():
            rows, logits = self.logits(source, context, ablation=ablation)
            if not torch.isfinite(logits).all():
                raise ValueError("nonfinite prediction")
            probs = torch.softmax(logits, dim=0)
            index = int(probs.argmax())
        prefix, _ = body_of(source)
        return {"source": source if index == 0 else prefix + "\n" + textwrap.indent(rows[index]["body"], "  ") + "\n",
                "choice": index, "probability": float(probs[index]), "choice_count": len(rows), "max_edits": 1,
                "teacher_used": False, "solver_used": False, "ablation": ablation,
                "decoder_type_safe_by_construction": False, "authority": "model_proposal_requires_Lean"}

    def to_dict(self):
        state = {"schema": SCHEMA, "graph_schema": GRAPH_SCHEMA, "environment_sha256": self.environment,
                "toolchain": list(self.toolchain), "templates": copy.deepcopy(self.templates),
                "width": self.width, "rounds": self.rounds, "seed": self.seed, "freeze_encoder": self.freeze_encoder,
                "steps": self.steps, "weights": {k: v.detach().tolist() for k, v in self.state_dict().items()}}
        if self.pooling != "last":
            state.update(schema=MULTISCALE_SCHEMA, pooling=self.pooling)
        return state

    @classmethod
    def from_dict(cls, state):
        fields = {"schema", "graph_schema", "environment_sha256", "toolchain", "templates", "width", "rounds",
                  "seed", "freeze_encoder", "steps", "weights"}
        multiscale = isinstance(state, dict) and state.get("schema") == MULTISCALE_SCHEMA
        if multiscale:
            fields.add("pooling")
        if (not isinstance(state, dict) or set(state) != fields or state["schema"] not in {SCHEMA, MULTISCALE_SCHEMA}
                or state["graph_schema"] != GRAPH_SCHEMA or not isinstance(state["toolchain"], list)
                or type(state["steps"]) is not int or not 0 <= state["steps"] <= 10**9
                or (multiscale and state["pooling"] != "multiscale")):
            raise ValueError("invalid graph checkpoint")
        model = cls(state["templates"], environment_sha256=state["environment_sha256"], toolchain=tuple(state["toolchain"]),
                    pooling="multiscale" if multiscale else "last",
                    **{key: state[key] for key in ("width", "rounds", "seed", "freeze_encoder")})
        weights = state["weights"]
        expected = model.state_dict()
        if not isinstance(weights, dict) or set(weights) != set(expected):
            raise ValueError("invalid graph checkpoint weights")
        def validate(value, shape):
            if shape:
                if not isinstance(value, list) or len(value) != shape[0]:
                    raise ValueError("invalid graph weight shape")
                for child in value:
                    validate(child, shape[1:])
            elif type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6:
                raise ValueError("invalid graph weight value")
        for name, tensor in expected.items():
            validate(weights[name], tuple(tensor.shape))
        model.load_state_dict({k: torch.tensor(v, dtype=torch.float64) for k, v in weights.items()})
        model.steps = state["steps"]
        return model
