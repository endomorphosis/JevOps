import Lean

/- Read-only inspection of a separately compiled theorem. No new declaration
   or axiom is added to the target environment. Counts do not unfold constants
   or measure kernel checking time. ExprStructEq avoids hash-only identity. -/
open Lean

namespace JevOpsMetrics

structure Size where
  tree : Nat := 1
  height : Nat := 1
  deriving Inhabited

structure Walk where
  memo : ExprStructMap Size := {}
  kinds : Std.HashMap String Nat := {}
  edges : Nat := 0

def children : Expr → Array Expr
  | .app f a => #[f, a]
  | .lam _ t b _ | .forallE _ t b _ => #[t, b]
  | .letE _ t v b _ => #[t, v, b]
  | .mdata _ e | .proj _ _ e => #[e]
  | _ => #[]

def kind : Expr → String
  | .bvar _ => "bvar"
  | .fvar _ => "fvar"
  | .mvar _ => "mvar"
  | .sort _ => "sort"
  | .const _ _ => "const"
  | .app _ _ => "app"
  | .lam _ _ _ _ => "lambda"
  | .forallE _ _ _ _ => "forall"
  | .letE _ _ _ _ _ => "let"
  | .lit _ => "literal"
  | .mdata _ _ => "metadata"
  | .proj _ _ _ => "projection"

def treeCap : Nat := 100000000

partial def visit (e : Expr) (limit depth : Nat) : StateT Walk (Except String) Size := do
  if depth > 512 then throw "expression depth budget"
  if let some size := (← get).memo.get? ⟨e⟩ then return size
  if (← get).memo.size >= limit then throw "expression node budget"
  let mut size : Size := {}
  let cs := children e
  for child in cs do
    let next ← visit child limit (depth + 1)
    size := { tree := min treeCap (size.tree + next.tree), height := max size.height (next.height + 1) }
  if size.height > 512 then throw "expression depth budget"
  if (← get).memo.size >= limit then throw "expression node budget"
  modify fun st => {
    memo := st.memo.insert ⟨e⟩ size
    edges := st.edges + cs.size
    kinds := st.kinds.insert (kind e) (st.kinds.getD (kind e) 0 + 1)
  }
  return size

def measure (e : Expr) (limit : Nat) : Except String Json := do
  let (size, st) ← (visit e limit 0).run {}
  return Json.mkObj [
    ("unique_structural_nodes", toJson st.memo.size),
    ("dag_edges", toJson st.edges),
    ("tree_nodes", if size.tree < treeCap then toJson size.tree else Json.null),
    ("tree_nodes_lower_bound", toJson size.tree),
    ("tree_count_saturated", toJson (decide (size.tree >= treeCap))),
    ("height", toJson size.height),
    ("kinds", Json.mkObj (st.kinds.toList.map fun (k, n) => (k, toJson n))),
    ("closed", toJson (!e.hasFVar && !e.hasMVar && !e.hasLooseBVars))]

def inspect (name : Name) (limit : Nat) : CoreM Json := do
  let .thmInfo info ← getConstInfo name | throwError "only theorem declarations are supported"
  let proof ← match measure info.value limit with
    | .ok x => pure x
    | .error e => throwError "{e}"
  let type ← match measure info.type limit with
    | .ok x => pure x
    | .error e => throwError "{e}"
  let axioms ← collectAxioms name
  return Json.mkObj [("schema", toJson "jevops-expr-metrics/v1"), ("declaration", toJson name.toString),
    ("proof", proof), ("type", type), ("axioms", toJson (axioms.map Name.toString)),
    ("constant_bodies_unfolded", toJson false), ("independent_kernel_verifier_used", toJson false)]

end JevOpsMetrics

def main (args : List String) : IO UInt32 := do
  let [directory, moduleName, declaration, budget] := args
    | throw (IO.userError "expected module directory, module name, theorem name, node budget")
  let some limit := budget.toNat? | throw (IO.userError "invalid node budget")
  if limit == 0 || limit > 100000 then throw (IO.userError "invalid node budget")
  initSearchPath (← findSysroot) [System.FilePath.mk directory]
  let env ← importModules #[{ module := moduleName.toName }] {}
  let report ← (JevOpsMetrics.inspect declaration.toName limit).toIO'
    { fileName := "ExprMetrics", fileMap := default, maxRecDepth := 1024 } { env := env }
  IO.println ("JEVOPS_EXPR_METRICS:" ++ report.compress)
  return 0
