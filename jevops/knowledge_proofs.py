"""Bounded propositional proof hypergraphs in an unchanged local Lean context.

This first slice handles implication application, conjunction projections, and
equivalence directions/introduction. It does NOT interpret arbitrary KG edges,
parse dependent types, add assumptions, or certify Lean proofs in Python.
Only an explicitly injected Arena evaluator can provide native observations.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .arena import ArenaEvaluator, Outcome, content_hash, intake_error, source_hash
from .constructive_proofs import read_proposition
from .logic_ir import Formula, variables
from .premise_search import bounded_int, digest_field

SCHEMA = "jevops-local-proof-hypergraph/v1"


@dataclass(frozen=True)
class ProofStep:
    rule: str
    conclusion: Formula
    parents: tuple[int, ...] = ()
    reference: str = ""


@dataclass(frozen=True)
class LocalProofPlan:
    source_sha256: str
    statement_sha256: str
    environment_sha256: str
    steps: tuple[ProofStep, ...]
    root: int

    def to_dict(self):
        return {"schema": SCHEMA, **asdict(self), "proof_verified": False,
                "authority": "proposal_only", "minimality_proven": False}

    @property
    def plan_sha256(self):
        return content_hash(self.to_dict())


def _context(source: str, statement: str):
    error = intake_error(source, statement)
    if error:
        raise ValueError(error)
    _, goal, assumptions = read_proposition(source)
    return goal, dict(assumptions)


def render_plan(plan: LocalProofPlan, *, source: str, statement: str, environment_sha256: str) -> str:
    """Validate every local inference before deterministically rendering Lean.

    This is syntactic IR validation, not native type checking. A standalone
    imported claim cannot appear as an assumption: references must already be
    named hypotheses in the exact source theorem.
    """
    digest_field(environment_sha256)
    if (type(plan) is not LocalProofPlan or plan.source_sha256 != source_hash(source)
            or plan.statement_sha256 != source_hash(statement)
            or plan.environment_sha256 != environment_sha256):
        raise ValueError("proof plan/source/environment mismatch")
    if (type(plan.steps) is not tuple or not 1 <= len(plan.steps) <= 256
            or type(plan.root) is not int or not 0 <= plan.root < len(plan.steps)):
        raise ValueError("proof plan budget/root")
    goal, assumptions = _context(source, statement)
    terms, types = [], []
    for index, step in enumerate(plan.steps):
        if (type(step) is not ProofStep or type(step.conclusion) is not Formula
                or type(step.rule) is not str or type(step.reference) is not str
                or type(step.parents) is not tuple or len(step.parents) > 2
                or any(type(parent) is not int or not 0 <= parent < index for parent in step.parents)):
            raise ValueError("invalid or forward proof step")
        variables(step.conclusion)
        ps = [types[parent] for parent in step.parents]
        ts = [terms[parent] for parent in step.parents]
        inferred = None
        term = ""
        if step.rule == "assumption" and not ps and step.reference in assumptions:
            inferred, term = assumptions[step.reference], step.reference
        elif step.reference:
            raise ValueError("reference only allowed for existing assumptions")
        elif step.rule == "apply" and len(ps) == 2 and ps[0].op == "imp" and ps[0].args[0] == ps[1]:
            inferred, term = ps[0].args[1], f"({ts[0]}) ({ts[1]})"
        elif step.rule in {"iff_mp", "iff_mpr"} and len(ps) == 1 and ps[0].op == "iff":
            args = ps[0].args if step.rule == "iff_mp" else tuple(reversed(ps[0].args))
            inferred = Formula("imp", args)
            term = f"({ts[0]}).{'mp' if step.rule == 'iff_mp' else 'mpr'}"
        elif step.rule in {"and_left", "and_right"} and len(ps) == 1 and ps[0].op == "and":
            side = int(step.rule == "and_right")
            inferred, term = ps[0].args[side], f"({ts[0]}).{'right' if side else 'left'}"
        elif step.rule == "iff_intro" and len(ps) == 2 and all(p.op == "imp" for p in ps) and ps[0].args == tuple(reversed(ps[1].args)):
            inferred, term = Formula("iff", ps[0].args), f"Iff.intro ({ts[0]}) ({ts[1]})"
        elif step.rule == "and_intro" and len(ps) == 2:
            inferred, term = Formula("and", tuple(ps)), f"And.intro ({ts[0]}) ({ts[1]})"
        if inferred is None or inferred != step.conclusion:
            raise ValueError("unjustified inference or mismatched conclusion")
        if len(term.encode()) > 16384:
            raise ValueError("rendered term byte budget")
        types.append(inferred)
        terms.append(term)
    if types[plan.root] != goal:
        raise ValueError("plan does not conclude the unchanged goal")
    seen, pending = set(), [plan.root]
    while pending:
        node = pending.pop()
        if node not in seen:
            seen.add(node)
            pending.extend(plan.steps[node].parents)
    if len(seen) != len(plan.steps):
        raise ValueError("unreachable proof steps")
    candidate = statement + " := by\n  exact " + terms[plan.root] + "\n"
    if intake_error(candidate, statement):
        raise ValueError("rendered proof failed intake")
    return candidate


def propose_local(source: str, *, statement: str, environment_sha256: str,
                  max_steps: int = 128, max_applications: int = 2048) -> dict:
    """Forward hypergraph search. First proof found, not a shortest-proof claim."""
    digest_field(environment_sha256)
    bounded_int(max_steps, 1, 256)
    bounded_int(max_applications, 1, 65536)
    report = {"schema": SCHEMA, "status": "NO_PLAN", "plan": None, "candidate": None,
              "proof_verified": False, "training_enabled": False, "minimality_proven": False,
              "source_sha256": source_hash(source), "environment_sha256": environment_sha256,
              "applications_considered": 0, "max_steps": max_steps, "max_applications": max_applications}
    try:
        goal, assumptions = _context(source, statement)
    except ValueError as exc:
        return {**report, "status": "UNSUPPORTED", "reason": str(exc)}
    steps, known, tried = [], {}, set()

    class BudgetExceeded(Exception):
        pass

    def add(rule, conclusion, parents=(), reference=""):
        if conclusion in known:
            return
        if len(steps) >= max_steps:
            raise BudgetExceeded()
        known[conclusion] = len(steps)
        steps.append(ProofStep(rule, conclusion, parents, reference))

    try:
        for name, formula in assumptions.items():
            add("assumption", formula, reference=name)
        while goal not in known:
            before = len(steps)
            for index, step in enumerate(tuple(steps)):
                if step.conclusion.op == "iff":
                    a, b = step.conclusion.args
                    add("iff_mp", Formula("imp", (a, b)), (index,))
                    add("iff_mpr", Formula("imp", (b, a)), (index,))
                elif step.conclusion.op == "and":
                    for side, formula in enumerate(step.conclusion.args):
                        add("and_right" if side else "and_left", formula, (index,))
                elif step.conclusion.op == "imp" and step.conclusion.args[0] in known:
                    argument = known[step.conclusion.args[0]]
                    if (index, argument) not in tried:
                        if len(tried) >= max_applications:
                            raise BudgetExceeded()
                        tried.add((index, argument))
                        add("apply", step.conclusion.args[1], (index, argument))
            if goal.op == "iff":
                a, b = goal.args
                forward, backward = Formula("imp", (a, b)), Formula("imp", (b, a))
                if forward in known and backward in known:
                    add("iff_intro", goal, (known[forward], known[backward]))
            elif goal.op == "and" and all(arg in known for arg in goal.args):
                add("and_intro", goal, tuple(known[arg] for arg in goal.args))
            if before == len(steps):
                break
    except BudgetExceeded:
        return {**report, "status": "SEARCH_BUDGET", "applications_considered": len(tried)}
    report["applications_considered"] = len(tried)
    if goal not in known:
        return report
    # Keep the actual proof hypergraph, not irrelevant explored hypotheses.
    needed, pending = set(), [known[goal]]
    while pending:
        node = pending.pop()
        if node not in needed:
            needed.add(node)
            pending.extend(steps[node].parents)
    remap = {old: new for new, old in enumerate(sorted(needed))}
    compact = tuple(ProofStep(steps[i].rule, steps[i].conclusion,
                             tuple(remap[parent] for parent in steps[i].parents), steps[i].reference)
                    for i in sorted(needed))
    plan = LocalProofPlan(source_hash(source), source_hash(statement), environment_sha256,
                          compact, remap[known[goal]])
    try:
        candidate = render_plan(plan, source=source, statement=statement, environment_sha256=environment_sha256)
    except ValueError as exc:
        return {**report, "status": "UNSUPPORTED", "reason": str(exc)}
    return {**report, "status": "PROPOSED", "plan": plan, "candidate": candidate}


def evaluate_plan(plan: LocalProofPlan, *, evaluator: ArenaEvaluator) -> dict:
    """Explicit bridge to existing all-pin evaluation; no auto-training/promotion.

    Evaluator and environment provenance are trusted infrastructure, not objects
    supplied by an LLM. Fixture evaluators remain fixtures even if they pass.
    """
    if type(evaluator) is not ArenaEvaluator:
        raise ValueError("explicit ArenaEvaluator required")
    ctx = evaluator.context
    source = render_plan(plan, source=ctx.reference_source, statement=ctx.statement,
                         environment_sha256=ctx.context_id)
    evaluation = evaluator.evaluate(source)
    all_pins = (evaluation.status == "MEASURED" and len(evaluation.receipts) == len(ctx.versions)
                and all(r.outcome == Outcome.VERIFIED for r in evaluation.receipts))
    return {"schema": "jevops-knowledge-plan-evaluation/v1", "plan_sha256": plan.plan_sha256,
            "plan": plan.to_dict(), "candidate": source, "evaluation": evaluation.to_dict(),
            "all_pins_passed": all_pins,
            "proof_verified": all_pins and evaluation.evidence_mode == "local_lean",
            "training_enabled": False, "promoted": False, "official_score": None}
