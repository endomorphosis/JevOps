"""Bounded local-term search over source-bound InfoTree observations.

Structural type matching is a proposal filter, NOT Lean unification or proof
authority. Native regenerated-context replay and whole-source admission must
still precede training. No observation is decoded into a trusted open Expr.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from . import proof_state as ps
from .expr_dag import _bytes
from .proof_replay import _check_capture, digest, replace_event
from .proof_tokens import proof_source_tokens
from .rewrite_policy import FORBIDDEN, IDENT, RESERVED

SCHEMA = "jevops-scoped-local-proposals/v1"


class _Exhausted(ValueError):
    pass


class _Graph:
    """Hash-consed alpha-normalized nodes; no expansion of shared DAGs.

    Binder names and metadata are erased only in this search representation.
    Binder annotations, universe levels and free-variable identities remain.
    This is intentionally not the lossless storage codec.
    """

    def __init__(self, expressions, *, limit=8192, work_limit=100_000):
        self.nodes, self.index, self.needs, self.heights = [], {}, [], []
        self.limit, self.work_limit, self.work = limit, work_limit, 0
        self.substitutions = {}
        self.refs = []
        for row in expressions:
            tag = row[0]
            ref = lambda n: self.refs[int(n)]
            if tag == "mdata":
                self.refs.append(ref(row[2]))
                continue
            if tag in {"bvar", "nat"}:
                node = (tag, int(row[1]))
            elif tag in {"fvar", "mvar"}:
                node = (tag, _bytes(row[1]))
            elif tag == "sort":
                node = (tag, int(row[1]))
            elif tag == "const":
                node = (tag, _bytes(row[1]), tuple(map(int, row[2])))
            elif tag == "app":
                node = (tag, ref(row[1]), ref(row[2]))
            elif tag in {"lam", "forall"}:
                node = (tag, row[2], ref(row[3]), ref(row[4]))
            elif tag == "let":
                node = (tag, row[2], ref(row[3]), ref(row[4]), ref(row[5]))
            elif tag == "proj":
                node = (tag, _bytes(row[1]), int(row[2]), ref(row[3]))
            elif tag == "string":
                node = tuple(row)
            else:
                raise ValueError("unsupported expression")
            self.refs.append(self.intern(node))

    @staticmethod
    def child_positions(node):
        return {"app": (1, 2), "lam": (2, 3), "forall": (2, 3),
                "let": (2, 3, 4), "proj": (3,)}.get(node[0], ())

    def intern(self, node):
        if node in self.index:
            return self.index[node]
        if len(self.nodes) >= self.limit:
            raise _Exhausted("node budget")
        positions = self.child_positions(node)
        height = 1 + max((self.heights[node[p]] for p in positions), default=0)
        if height > 160:
            raise _Exhausted("depth budget")
        need = node[1] + 1 if node[0] == "bvar" else 0
        for p in positions:
            bound = int(node[0] in {"lam", "forall", "let"} and p == positions[-1])
            need = max(need, self.needs[node[p]] - bound)
        i = len(self.nodes)
        self.index[node] = i
        self.nodes.append(node)
        self.needs.append(need)
        self.heights.append(height)
        return i

    def instantiate(self, body, argument):
        """Substitute binder zero by a locally closed term, avoiding capture.

        Arguments contain only scoped fvars/applications, so lifting them under
        binders is the identity. Outer de Bruijn indices still decrement.
        Memoization includes depth: a DAG node may occur under several binders.
        """
        if self.needs[argument]:
            raise ValueError("substitution argument has loose bound variables")

        def visit(i, depth):
            key = (i, argument, depth)
            if key in self.substitutions:
                return self.substitutions[key]
            self.work += 1
            if self.work > self.work_limit:
                raise _Exhausted("substitution work budget")
            node = self.nodes[i]
            if self.needs[i] <= depth:
                result = i
            elif node[0] == "bvar":
                result = argument if node[1] == depth else self.intern(("bvar", node[1] - 1))
            else:
                positions = self.child_positions(node)
                changed = list(node)
                for p in positions:
                    bound = int(node[0] in {"lam", "forall", "let"} and p == positions[-1])
                    changed[p] = visit(node[p], depth + bound)
                result = self.intern(tuple(changed))
            self.substitutions[key] = result
            return result

        return visit(body, 0)


@dataclass(frozen=True)
class _Term:
    expr: int
    type: int
    head: str
    arguments: tuple
    explicit: bool
    applications: int
    locals: frozenset

    def render(self):
        head = ("@" if self.explicit else "") + self.head
        args = [f"({a.render()})" if a.arguments else a.render() for a in self.arguments]
        return " ".join([head, *args])


def _spelling(name):
    if len(name) != 1 or name[0][0] != "s":
        return None  # Includes hygienic/inaccessible and hierarchical names.
    s = name[0][1]
    if (s == "_" or len(s.encode()) > 128 or not IDENT.fullmatch(s)
            or s in RESERVED or FORBIDDEN.search(s)):
        return None
    return s


def local_terms(state, *, max_applications=3, max_terms=128, max_checks=16_384, node_budget=4096):
    """Enumerate local references/applications matching one observed goal type.

    Types must match structurally after alpha/metadata normalization. No delta,
    beta, typeclass search, coercion, metavariable solving, or external constants
    are synthesized. Limits can truncate discovery, never certify a candidate.
    """
    if (type(max_applications) is not int or not 0 <= max_applications <= 4
            or type(max_terms) is not int or not 1 <= max_terms <= 256
            or type(max_checks) is not int or not 1 <= max_checks <= 65_536):
        raise ValueError("invalid search budget")
    analysis = ps.analyze_state(state, node_budget=node_budget)
    result = {"candidates": [], "checks": 0, "term_count": 0, "truncated": False,
              "reason": None, "state_sha256": analysis["state_sha256"],
              "kernel_typechecked": False, "proof_admitted": False}
    if len(state["goals"]) != 1:
        return {**result, "reason": "requires_single_goal"}
    goal = next(m for m in state["metavariables"] if m["id"] == state["goals"][0])
    if goal["assignment"] is not None:
        return {**result, "reason": "assigned_goal"}
    if state["universe_metavariables"] or any(e[0] == "mvar" for e in state["expressions"]):
        return {**result, "reason": "metavariable_context"}
    if len(goal["locals"]) > 64:
        return {**result, "reason": "local_budget", "truncated": True}
    names = Counter(_bytes(d["name"]) for d in goal["locals"])
    graph = _Graph(state["expressions"], limit=2 * node_budget + max_terms * 8)
    terms, seen = [], set()
    try:
        for d in goal["locals"]:
            spelling = _spelling(d["name"])
            if d["kind"] != "default" or spelling is None or names[_bytes(d["name"])] != 1:
                continue
            if len(terms) >= max_terms:
                raise _Exhausted("term budget")
            expr, typ = graph.intern(("fvar", _bytes(d["id"]))), graph.refs[int(d["type"])]
            node = graph.nodes[typ]
            explicit = node[0] == "forall" and node[1] != "explicit"
            terms.append(_Term(expr, typ, spelling, (), explicit, 0, frozenset([ps._id(d["id"])])))
            seen.add(expr)
        for size in range(1, max_applications + 1):
            previous = list(terms)
            for fn in previous:
                typ = graph.nodes[fn.type]
                if typ[0] != "forall":
                    continue
                for arg in previous:
                    if fn.applications + arg.applications + 1 != size:
                        continue
                    if result["checks"] >= max_checks:
                        raise _Exhausted("matching budget")
                    result["checks"] += 1
                    if typ[2] != arg.type:
                        continue
                    expr = graph.intern(("app", fn.expr, arg.expr))
                    if expr in seen:
                        continue
                    if len(terms) >= max_terms:
                        raise _Exhausted("term budget")
                    term = _Term(expr, graph.instantiate(typ[3], arg.expr), fn.head,
                                 (*fn.arguments, arg), fn.explicit or typ[1] != "explicit",
                                 size, fn.locals | arg.locals)
                    if len(term.render().encode()) > 4000:
                        continue
                    terms.append(term)
                    seen.add(expr)
    except _Exhausted as exc:
        result.update(truncated=True, reason=str(exc))
    target = graph.refs[int(goal["type"])]
    result["candidates"] = sorted([
        {"candidate": "exact " + t.render(), "applications": t.applications,
         "local_ids": sorted(t.locals)} for t in terms if t.type == target
    ], key=lambda r: (proof_source_tokens(r["candidate"]), r["candidate"]))
    result.update(term_count=len(terms), search_nodes=len(graph.nodes), substitution_work=graph.work)
    return result


def propose_scoped(source, capture, *, environment_sha256, limit=8, max_events=32, **search):
    """Collector-compatible proposals plus diagnostics; no compiler or model call.

    Inspect only before-contexts of closing spans. A later alias is never copied
    into an earlier context. Checksums bind observations, not their authenticity;
    callers must still use the native replay/whole-source collector.
    """
    if (type(limit) is not int or not 1 <= limit <= 16
            or type(max_events) is not int or not 1 <= max_events <= 64):
        raise ValueError("invalid proposal budget")
    _check_capture(source, capture, environment_sha256)
    events = [e for e in capture["trace"]["events"] if e["status"] == "captured"
              and e["before"]["goals"] and not e["after"]["goals"]
              and e["start"] is not None and e["end"] is not None]
    events.sort(key=lambda e: (int(e["start"]) - int(e["end"]), int(e["id"])))
    diagnostics, proposals, seen, cache = [], [], set(), {}
    truncated = len(events) > max_events
    for e in events[:max_events]:
        try:
            replace_event(source, e, "exact True.intro")  # Envelope check only.
        except ValueError:
            continue
        key = digest(e["before"])
        if key not in cache:
            cache[key] = local_terms(e["before"], node_budget=capture["node_budget"], **search)
        found = cache[key]
        diagnostics.append({"event_id": int(e["id"]), **found})
        for c in found["candidates"]:
            target = replace_event(source, e, c["candidate"])
            if target in seen or proof_source_tokens(target) >= proof_source_tokens(source):
                continue
            seen.add(target)
            proposals.append({"event_id": int(e["id"]), "candidate": c["candidate"],
                              "target_tokens": proof_source_tokens(target)})
    proposals.sort(key=lambda p: (p["target_tokens"], p["event_id"], p["candidate"]))
    return {"schema": SCHEMA, "source_sha256": capture["source_sha256"],
            "trace_sha256": capture["trace_sha256"], "events": diagnostics,
            "proposals": [{k: p[k] for k in ("event_id", "candidate")} for p in proposals[:limit]],
            "truncated": truncated or len(proposals) > limit or any(d["truncated"] for d in diagnostics),
            "kernel_typechecked": False, "proof_admitted": False, "model_trained": False}


def scoped_proposals(source, capture, *, environment_sha256, **kwargs):
    """Inject with partial(..., environment_sha256=...) as proposal_fn."""
    return propose_scoped(source, capture, environment_sha256=environment_sha256, **kwargs)["proposals"]


def premise_query(state, *, node_budget=4096, max_query_nodes=256):
    """Extract library-retrieval features from one BEFORE goal and local types.

    These are constant names, not pretty-printed Lean or type unification. Never
    inspect proof values, other goals, unrelated DAG nodes or an after-context.
    A query traversal overflow abstains rather than ranking a partial query.
    Full observation validation is separate, bounded global work.
    """
    if type(max_query_nodes) is not int or not 0 <= max_query_nodes <= 4096:
        raise ValueError("invalid query node budget")
    analysis = ps.analyze_state(state, node_budget=node_budget)
    result = {"feature_method": "goal-and-local-type-constants/v1",
              "state_sha256": analysis["state_sha256"], "query": "",
              "nodes_visited": 0, "status": "NO_CONSTANTS"}
    if len(state["goals"]) != 1:
        return {**result, "status": "REQUIRES_SINGLE_GOAL"}
    goal = next(m for m in state["metavariables"] if m["id"] == state["goals"][0])
    if goal["assignment"] is not None:
        return {**result, "status": "ASSIGNED_GOAL"}
    pending = [int(goal["type"]), *(int(d["type"]) for d in goal["locals"])]
    seen, constants = set(), set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        if len(seen) >= max_query_nodes:
            return {**result, "nodes_visited": len(seen), "status": "QUERY_BUDGET"}
        seen.add(ref)
        row = state["expressions"][ref]
        tag = row[0]
        if tag in {"const", "proj"}:
            # Numeric/hygienic names are not source-level retrieval spellings.
            if row[1] and all(part[0] == "s" for part in row[1]):
                constants.add(".".join(part[1] for part in row[1]))
        children = ({"app": row[1:3], "lam": row[3:5], "forall": row[3:5],
                     "let": row[3:6], "mdata": row[2:3], "proj": row[3:4]}.get(tag, ()))
        pending.extend(int(child) for child in children)
    query = " ".join(sorted(constants))
    if len(query.encode()) > 16384:
        return {**result, "nodes_visited": len(seen), "status": "QUERY_BUDGET"}
    return {**result, "nodes_visited": len(seen), "query": query,
            "status": "READY" if query else "NO_CONSTANTS"}


def goal_head(state, *, node_budget=4096, max_steps=256):
    """Raw BEFORE-goal head; bounded observation traversal, never unification.

    Full state validation is additional bounded setup work. Do not inspect local
    values or the reference after-state to decide this retrieval feature.
    """
    from .premise_search import ExprHead, bounded_int
    bounded_int(max_steps, 0, 4096)
    ps.analyze_state(state, node_budget=node_budget)
    if len(state["goals"]) != 1:
        return None
    goal = next(m for m in state["metavariables"] if m["id"] == state["goals"][0])
    if goal["assignment"] is not None:
        return None
    ref, arity = int(goal["type"]), 0
    for _ in range(max_steps):
        row = state["expressions"][ref]
        if row[0] == "app":
            arity += 1
            if arity > 256:
                return None
            ref = int(row[1])
        elif row[0] == "mdata":
            ref = int(row[2])
        elif row[0] == "const" and row[1] and all(p[0] == "s" for p in row[1]):
            return ExprHead("const", ".".join(p[1] for p in row[1]), arity)
        else:
            return ExprHead({"bvar": "bound", "fvar": "bound", "sort": "sort"}.get(row[0], "other"), arity=arity)
    return None
