"""A declarative reduction catalog shared by the router and bounded hammer.

Semantic analysis and proof proposals are separate: Python truth tables inform
search, while the current Lean environment decides validity. Optional library
tactics are advertised with their requirements and may fail compilation. No
imports, global simp attributes, or theorem statements are changed here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Sequence

from .logic_ir import analyze_formula, parse_formula, render_formula, variables


@dataclass(frozen=True)
class ReductionMethod:
    strategy: str
    description: str
    tactics: tuple[str, ...]
    features: tuple[str, ...] = ()
    environment: str = "Lean core; compile in the pinned project"
    trust: str = "proof_term; inspect actual transitive axiom closure"


METHODS = (
    ReductionMethod("logic_simp", "Propositional constants, absorption, idempotence, complements, implication and De Morgan laws",
                    ("simp_all", "classical\n  simp_all", "classical\n  simp_all [not_and_or, not_or, and_or_left, or_and_left]", "tauto"),
                    ("∧", "∨", "¬", "↔", "→", "Prop"), "Lean core; tauto requires Mathlib"),
    ReductionMethod("boolean_minimize", "K-map/Quine–McCluskey DNF/CNF, Shannon decomposition and BDD support reduction", (),
                    ("∧", "∨", "¬", "↔", "→", "Prop")),
    ReductionMethod("invariant_reduce", "Equality substitution, contradictory assumptions and redundant invariants",
                    ("subst_vars\n  simp_all", "simp_all", "subst_vars\n  assumption", "contradiction")),
    ReductionMethod("quantifier_simp", "Universal/existential distribution, witness elimination and negation normalization",
                    ("simp_all [forall_and, exists_or]", "simp_all", "push_neg\n  simp_all", "aesop"),
                    ("∀", "∃", "Exists", "Forall"), "Lean core; push_neg/aesop require supporting imports"),
    ReductionMethod("equality_congruence", "Congruence closure, substitution and equality transitivity",
                    ("subst_vars\n  rfl", "grind", "simp_all", "congr 1 <;> assumption"), ("=", "Eq", "rw", "subst")),
    ReductionMethod("ac_normalize", "Associative/commutative canonicalization",
                    ("ac_rfl", "simp_all [and_assoc, and_comm, and_left_comm, or_assoc, or_comm, or_left_comm]"),
                    ("+", "*", "∧", "∨", "++")),
    ReductionMethod("arithmetic_linear", "Linear integer/natural arithmetic, intervals and contradictions",
                    ("omega", "simp_all <;> omega", "linarith"),
                    ("Nat", "Int", "≤", "≥", "<", ">", "+", "-"), "Lean core omega; linarith requires Mathlib"),
    ReductionMethod("arithmetic_polynomial", "Polynomial identities, nonlinear consequences and numerical evaluation",
                    ("ring", "ring_nf", "nlinarith", "norm_num", "positivity"),
                    ("*", "^", "ℝ", "ℚ", "Real", "Rat"), "Mathlib"),
    ReductionMethod("rational_normalize", "Rational expressions with denominator side conditions",
                    ("field_simp <;> ring", "norm_num", "norm_cast", "push_cast\n  ring"),
                    ("/", "⁻¹", "Rat", "ℚ"), "Mathlib; Lean must prove nonzero side conditions"),
    ReductionMethod("bitvector_decide", "Bit-vector/Boolean identities using certificate-producing decision procedures",
                    ("bv_decide", "decide", "simp_all"), ("BitVec", "UInt", "Bool", "&&", "|||", "&&&"),
                    "Std.Tactic.BVDecide for bv_decide", "bv_decide uses native certificate checking; extended trust"),
    ReductionMethod("set_extensionality", "Set equality/subset, membership, union/intersection and complements",
                    ("ext <;> simp_all", "ext <;> simp_all <;> tauto", "simp_all", "aesop"),
                    ("Set", "∩", "∪", "∈", "⊆", "ᶜ"), "Mathlib Set/ext/tauto"),
    ReductionMethod("function_extensionality", "Function equality and pointwise beta/eta simplification",
                    ("funext x\n  simp_all", "funext x\n  rfl", "simp_all", "rfl"), ("fun ", "Function", "funext")),
    ReductionMethod("datatype_reduce", "Constructor injectivity/disjointness and discriminant simplification",
                    ("simp_all", "injection ‹_ = _›", "grind", "cases ‹False›"),
                    ("List", "Option", "some", "none", "Nat.succ", "constructor", "cases")),
    ReductionMethod("structural_reduce", "Witness/constructor packing, unused local facts and proof slicing", ()),
    ReductionMethod("simp_set_reduce", "Delete unused simplifier lemmas one at a time and as a group", (), ("simp", "rw")),
    ReductionMethod("branch_invariant", "Common branch normalization and bounded induction/branch closers", (),
                    ("case ", "induction ", "cases ")),
    ReductionMethod("egraph_minimize", "Bounded propositional congruence closure, distributive factoring and cost extraction", (),
                    ("∧", "∨", "¬", "↔", "→", "Prop")),
    ReductionMethod("proof_slice", "Compiler-guided coarse-to-fine deletion of layout blocks and sibling chunks", ()),
    ReductionMethod("kernel_reduce", "Definitional beta/delta/iota/zeta reduction and checked decidability",
                    ("rfl", "dsimp\n  rfl", "decide", "decide +kernel", "decide_cbv"),
                    environment="Lean core; decide_cbv is version-dependent"),
    ReductionMethod("grind_control", "Bounded library-independent congruence and local-context saturation",
                    ("grind only", "grind [*]", "grind -split", "simp_all\n  grind"),
                    environment="Lean core grind; options are version-dependent"),
    ReductionMethod("simp_control", "Minimal explicit simplifier sets and binder-aware repeated rewriting",
                    ("simp only", "simp_all only", "simpa only", "simp_all +decide")),
    ReductionMethod("additive_normalize", "Abelian-group normalization, including cancellations",
                    ("abel", "abel_nf\n  assumption", "simp_all <;> abel"),
                    ("+", "-", "Add", "Int", "ℤ"), "Mathlib abel"),
    ReductionMethod("noncommutative_normalize", "Noncommutative polynomial and group word normalization",
                    ("noncomm_ring", "group", "simp_all <;> noncomm_ring"),
                    ("*", "⁻¹", "Group", "Ring"), "Mathlib noncomm_ring/group"),
    ReductionMethod("order_normalize", "Order duality, lattice identities and bound propagation",
                    ("order", "bound", "simp_all [min_def, max_def] <;> split_ifs <;> omega"),
                    ("≤", "<", "min", "max", "⊓", "⊔"), "Mathlib; individual tactics require imports"),
    ReductionMethod("cast_transport", "Remove coercion detours and transfer arithmetic to normalized types",
                    ("norm_cast", "push_cast\n  ring", "zify at *\n  omega", "qify at *\n  linarith"),
                    ("↑", "Nat", "Int", "ℚ", "ℤ"), "Mathlib norm_cast/zify/qify"),
    ReductionMethod("finite_context", "Finite case analysis and extensionality of bounded indices",
                    ("decide", "simp_all", "aesop"), ("Fin", "Bool", "Fintype"), "Lean core; aesop optional"),
    ReductionMethod("logical_transport", "Reduce contradiction, contraposition and biconditional proof scaffolding",
                    ("contrapose!\n  aesop", "by_contra h\n  simp_all", "constructor <;> aesop"),
                    ("¬", "→", "↔", "False"), "Mathlib contrapose!/aesop"),
    ReductionMethod("rewrite_transport", "Collapse rewrite/finisher sequences and transport exact terms", (),
                    ("rw", "simp", "exact", "apply")),
    ReductionMethod("local_alias_reduce", "Inline terminal local aliases without dropping dependent premises", (),
                    ("have", "let", "exact")),
    ReductionMethod("symmetry_reduce", "Cancel adjacent symmetry scaffolding and reverse-proof wrappers", (),
                    ("symm", "Eq.symm", "Iff.symm")),
    ReductionMethod("application_reduce", "Fuse a unary apply/exact proof into one checked application", (),
                    ("apply", "exact")),
    ReductionMethod("eta_reduce", "Eliminate an introduced argument immediately passed to a function", (),
                    ("intro", "exact")),
    ReductionMethod("solver_argument_reduce", "Balanced nested lemma-list and certificate-support minimization", (),
                    ("simp", "rw", "grind", "linarith")),
)
LOGIC_STRATEGIES = tuple(method.strategy for method in METHODS)
_BY_NAME = {method.strategy: method for method in METHODS}


def reduction_catalog() -> list[dict[str, Any]]:
    return [asdict(method) for method in METHODS]


def applicable_strategies(source: str) -> list[str]:
    return [m.strategy for m in METHODS if not m.features or any(f in source for f in m.features)]


def analysis_summary(goal: str) -> dict[str, Any]:
    """Keep exponential normal forms out of the bounded LLM prompt."""
    report = analyze_formula(goal)
    if not report.get("supported"):
        return report
    forms = {}
    for form in ("dnf", "cnf"):
        row = report[form]
        forms[form] = {key: row[key] for key in ("cost", "optimal_two_level", "equivalent_on_context", "vacuous")}
        forms[form]["lean_chars"] = len(row["lean"])
        # Never present truncated syntax as a complete equivalent formula.
        forms[form]["lean"] = row["lean"] if len(row["lean"]) <= 512 else None
    return {"schema": report["schema"], "supported": True, "semantics": report["semantics"],
            "variables": report["variables"], "normal_forms": forms,
            "bdd_nodes": len(report["bdd"]["nodes"]),
            "independent_variables": report["bdd"]["independent_variables"],
            # These describe satisfying assignments of the goal, NOT facts
            # available in the proof context. Using them as assumptions would
            # be circular reasoning (even though Lean would reject the draft).
            "goal_consequences_not_hypotheses": {
                "forced": report["invariants"]["forced"],
                "relations": report["invariants"]["relations"][:8],
                "vacuous": report["invariants"]["vacuous"],
            },
            "redundant_conjunct_count": len(report["invariants"]["redundant_conjuncts"]),
            "authority": "search_hint_requires_Lean"}


def _case_proof(formula: str, *, max_atoms: int = 6) -> str | None:
    try:
        names = variables(parse_formula(formula))
    except ValueError:
        return None
    if len(names) > max_atoms:
        return None
    commands = [f"by_cases {name}" for name in names]
    return "classical\n" + " <;> ".join([*commands, "simp_all"])


def equivalence_proof(left: str, right: str, *, assumptions: str = "True") -> str:
    """Generate a Lean proof *obligation*, never a trusted Python certificate."""
    from .logic_ir import Formula
    a, b, context = parse_formula(left), parse_formula(right), parse_formula(assumptions)
    obligation = Formula("imp", (context, Formula("iff", (a, b))))
    proof = _case_proof(render_formula(obligation))
    if proof is None:
        raise ValueError("equivalence proof exceeds case-split budget")
    return proof


def structural_observations(body: str) -> dict[str, Any]:
    lines = body.splitlines()
    unused = []
    repeated: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        # Only single-line local definitions. Layout/control, comments, terms
        # and binders require elaboration; they cannot justify text deletion.
        match = re.fullmatch(r"(?:have|let)\s+([A-Za-z_][A-Za-z0-9_']*)\s*(?::[^:=]+)?\s*:=\s*(.+)", stripped)
        if match and not any(x in match[2] for x in ("by", "--", "/-", '"', ";")):
            tail = "\n".join(lines[index + 1:])
            indent = len(line) - len(line.lstrip())
            next_line = next((s for s in lines[index + 1:] if s.strip()), "")
            continuation = next_line and len(next_line) - len(next_line.lstrip()) > indent
            if not continuation and not re.search(r"(?<![\w'])" + re.escape(match[1]) + r"(?![\w'])", tail):
                unused.append(index)
        if stripped.startswith(("simp", "dsimp", "rw ")):
            repeated.setdefault(stripped, []).append(index)
    return {"unused_local_lines": unused[:32],
            "repeated_normalizers": [{"tactic": t, "lines": ns[:16]} for t, ns in repeated.items() if len(ns) > 1][:16],
            "authority": "syntactic_hints_require_Lean"}


def reduction_variants(body: str, *, strategy: str, goal: str = "", cap: int = 16) -> list[tuple[str, str, tuple[str, ...]]]:
    """Generate bounded theorem-body drafts; all must be compiler checked."""
    if strategy not in _BY_NAME or cap <= 0:
        return []
    budget = min(64, int(cap))
    rows: list[tuple[str, str, tuple[str, ...]]] = []
    seen = {body.strip()}

    def push(kind: str, text: str, *ops: str) -> None:
        clean = text.strip("\n")
        if clean.strip() and clean.strip() not in seen and len(rows) < budget:
            seen.add(clean.strip())
            rows.append((kind, clean, (strategy, *ops)))

    if strategy == "proof_slice":
        from .proof_slicing import deletion_variants
        return deletion_variants(body, cap=budget)
    if strategy == "solver_argument_reduce":
        from .tactic_arguments import argument_variants
        return argument_variants(body, cap=budget)
    if strategy in {"application_reduce", "eta_reduce"}:
        # Whole lines and single identifiers only; dependent type/scope checks
        # are left to Lean. No rewriting inside terms, comments or quotations.
        if any(s in body for s in ('--', '/-', '-/', '"', '`', '$')):
            return rows
        name = r"[^\W\d][\w'.]*"
        pattern = (r"(?m)^([ ]*)apply (" + name + r")[ ]*\n\1exact (" + name + r")[ ]*$"
                   if strategy == "application_reduce" else
                   r"(?m)^([ ]*)intro (" + name + r")[ ]*\n\1exact (" + name + r") \2[ ]*$")
        for match in re.finditer(pattern, body):
            if strategy == "eta_reduce" and match[2] == match[3]:
                continue
            replacement = (f"exact {match[2]} {match[3]}" if strategy == "application_reduce"
                           else f"exact {match[3]}")
            push(strategy, body[:match.start()] + match[1] + replacement + body[match.end():])
        return rows
    if strategy == "local_alias_reduce":
        # Small terminal patterns only. No substitution across dependent
        # binders, arbitrary terms, comments, or nested proof blocks.
        pattern = r"(?m)^([ ]*)(?:have|let) ([\w']+)(?:\s*:\s*[^\n:=]+)?\s*:=\s*([\w'.]+)\s*\n\1exact \2[ ]*$"
        for match in re.finditer(pattern, body):
            if match[3] not in {"by", "sorry", "admit"}:
                push("terminal_alias", body[:match.start()] + match[1] + "exact " + match[3] + body[match.end():])
        return rows
    if strategy == "symmetry_reduce":
        for match in re.finditer(r"(?m)^([ ]*)symm[ ]*\n\1symm[ ]*\n", body):
            push("double_symmetry", body[:match.start()] + body[match.end():])
        for match in re.finditer(r"(?m)^([ ]*)symm[ ]*\n\1exact (?:Eq|Iff)\.symm ([\w']+)[ ]*$", body):
            push("symmetry_transport", body[:match.start()] + match[1] + "exact " + match[2] + body[match.end():])
        return rows
    if strategy == "egraph_minimize":
        from .equality_saturation import saturate_formula
        try:
            result = saturate_formula(parse_formula(goal), iterations=3, max_nodes=256, max_matches=4000)
            if result.get("supported"):
                reduced = result["lean"]
                if reduced == "True":
                    proof = _case_proof(goal)
                    if proof:
                        push("egraph_tautology", proof, "egraph")
                elif len(reduced) < len(goal):
                    proof = equivalence_proof(goal, reduced)
                    nested = "\n".join("  " + line for line in proof.splitlines())
                    push("egraph_cut", f"have : ({goal}) ↔ ({reduced}) := by\n{nested}\napply this.mpr\nsimp_all", "egraph")
        except ValueError:
            pass
        return rows
    if strategy == "rewrite_transport":
        # These are hypotheses about tactic behavior, NOT unconditional edits.
        for match in re.finditer(r"(?m)^(\s*)rw (\[[^\[\]\n]+\])\s*\n\1(?:rfl|assumption)\s*$", body):
            push("rw_finisher", body[:match.start()] + match[1] + "simpa only " + match[2] + body[match.end():], "rewrite_finisher")
        for match in re.finditer(r"(?m)^(\s*)simp(?: only)? (\[[^\[\]\n]+\]) at ([\w']+)\s*\n\1exact \3\s*$", body):
            push("simpa_using", body[:match.start()] + f"{match[1]}simpa {match[2]} using {match[3]}" + body[match.end():], "simpa_using")
        for match in re.finditer(r"(?m)^(\s*)exact ([\w'.]+)\s*$", body):
            if not match[2].startswith(("Eq.", "False.")):
                push("exact_to_assumption", body[:match.start()] + match[1] + "assumption" + body[match.end():])
        return rows

    if strategy == "boolean_minimize":
        report = analyze_formula(goal)
        if report.get("supported"):
            proof = _case_proof(goal)
            if proof:
                # The variables eliminated by a reduced BDD need no split if
                # simp can expose the independence; keep the full proof too.
                support = sorted({n["variable"] for n in report["bdd"]["nodes"]})
                if support and len(support) < len(report["variables"]):
                    push("shannon_support", "classical\n" + " <;> ".join([*(f"by_cases {n}" for n in support), "simp_all"]))
                push("truth_table_split", proof, "shannon")
                for form in ("dnf", "cnf"):
                    reduced = report[form]["lean"]
                    if len(reduced) >= len(goal) or reduced == goal:
                        continue
                    try:
                        certificate = equivalence_proof(goal, reduced)
                    except ValueError:
                        continue  # The combined obligation may exceed the AST budget.
                    nested = "\n".join("  " + line for line in certificate.splitlines())
                    push("minimized_" + form,
                         f"have : ({goal}) ↔ ({reduced}) := by\n{nested}\napply this.mpr\nsimp_all", "quine_mccluskey", form)
        return rows

    for index, text in enumerate(_BY_NAME[strategy].tactics):
        push(f"{strategy}_{index}", text.replace("\n  ", "\n"))

    if strategy in {"structural_reduce", "invariant_reduce"}:
        from . import folds
        transforms = (folds.fold_ctor_pair_exacts, folds.fold_use_exact, folds.fold_trim_intro_names,
                      folds.fold_unused_intros, folds.fold_drop_unfold_before_split)
        for fn in transforms:
            push(fn.__name__, fn(body), fn.__name__)
        lines = body.splitlines()
        for index in structural_observations(body)["unused_local_lines"]:
            push("unused_local", "\n".join(lines[:index] + lines[index + 1:]), "dead_binding")
    if strategy == "simp_set_reduce":
        matches = list(re.finditer(r"\b(?:simp_all|simp|simpa|rw)(?: only)?\s*\[([^\[\]\n]*)\]", body))
        # Repeated identical lemma lists often dominate proof length. Explore
        # shared deletions before individual sites; every batch is recompiled.
        for content in dict.fromkeys(match[1] for match in matches):
            shared = [m for m in matches if m[1] == content]
            if len(shared) < 2 or any(c in content for c in "(){}⟨⟩\";"):
                continue
            items = content.split(",")
            for i in range(min(16, len(items))):
                replacement = ",".join(items[:i] + items[i + 1:])
                edited = body
                for m in reversed(shared):
                    edited = edited[:m.start(1)] + replacement + edited[m.end(1):]
                push("shared_simp_lemma", edited, "shared_simp_lemma_delete")
        for match in matches:
            items = match[1].split(",")
            # Commas inside parentheses/terms are not lemma separators.
            if any(c in match[1] for c in "(){}⟨⟩\";"):
                continue
            for i in range(min(16, len(items))):
                content = ",".join(items[:i] + items[i + 1:])
                push("remove_simp_lemma", body[:match.start(1)] + content + body[match.end(1):], "simp_lemma_delete")
            push("empty_simp_set", body[:match.start(1)] + body[match.end(1):], "simp_set_empty")
            if len(rows) >= budget:
                break
    if strategy == "branch_invariant":
        from . import folds, tactics
        for fn in (folds.fold_hoist_repeated_simp, folds.fold_redundant_inner_simp):
            push(fn.__name__, fn(body), fn.__name__)
        spans = sorted(tactics.case_spans(body), key=lambda s: (-(s.end - s.header_end), s.start))[:16]
        groups = []
        for span in spans:
            original = body[span.header_end:span.end]
            lines = [line.strip() for line in original.splitlines() if line.strip()]
            prefixes = [""]
            # Preserve the definitions/introductions that make a closer
            # applicable. Never retain only half a layout-controlled branch.
            prefix = []
            for line in lines[:3]:
                if not re.match(r"^(?:simp(?:_all)?|dsimp|unfold|intro|intros|subst|subst_vars)\b", line):
                    break
                if any(c in line for c in ("--", "/-", "=>", ";")):
                    break
                prefix.append(line)
                prefixes.insert(0, "\n".join(prefix) + "\n")
            groups.append([(span, pre + closer, closer, bool(pre)) for pre in prefixes
                           for closer in ("grind", "simp_all", "assumption", "omega")])
        for index in range(max(map(len, groups), default=0)):
            for group in groups:
                if index < len(group):
                    span, text, closer, kept_prefix = group[index]
                    push("branch_prefix_closer" if kept_prefix else "branch_closer",
                         tactics.replace_case_body(body, span, text), span.label, closer)
                    if len(rows) >= budget:
                        return rows
    return rows


def reduction_sweep(body: str, *, goal: str = "", source: str = "", requested: Sequence[str] = (),
                    cap: int = 24, offset: int = 0) -> list[tuple[str, str, tuple[str, ...]]]:
    """Round-robin methods; rotating start prevents fixed-budget starvation."""
    if cap <= 0:
        return []
    names = applicable_strategies(source or (goal + "\n" + body))
    if names:
        start = offset % len(names)
        names = names[start:] + names[:start]
    preferred = list(dict.fromkeys(n for n in requested if n in _BY_NAME))
    names = preferred + [n for n in names if n not in preferred]
    groups = [reduction_variants(body, strategy=n, goal=goal, cap=cap) for n in names]
    rows, seen = [], {body.strip()}
    for index in range(max(map(len, groups), default=0)):
        for group in groups:
            if index < len(group):
                kind, text, ops = group[index]
                if text.strip() not in seen:
                    seen.add(text.strip())
                    rows.append((kind, text, ops))
                    if len(rows) >= max(0, min(64, cap)):
                        return rows
    return rows
