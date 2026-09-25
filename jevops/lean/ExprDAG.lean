import Lean

/- Bounded, structural expression storage, not a proof rewrite. V1 preserves
   scalar metadata in entry order and rejects Syntax-valued metadata. It never
   serializes free/metavariables, unfolds constants, or infers source text. -/
open Lean

namespace JevOpsDAG

def schema := "jevops-lean-expr-dag/v1"
def metadataPolicy := "ordered-scalars-v1-reject-syntax"
def maxDepth := 256
def maxBytes := 16777216
def ja (xs : List Json) : Json := .arr xs.toArray
def jn (n : Nat) : Json := toJson (toString n)

def settings (environment : String) (limit : Nat) : Except String Unit := do
  unless environment.length == 64 && environment.toList.all (fun c =>
      ('0' ≤ c && c ≤ '9') || ('a' ≤ c && c ≤ 'f')) do
    throw "environment fingerprint required"
  if limit == 0 || limit > 100000 then throw "invalid node budget"

def natOf (j : Json) : Except String Nat := do
  let s ← j.getStr?
  if s.length > 4096 then throw "integer payload budget"
  let some n := s.toNat? | throw "decimal natural expected"
  unless toString n == s do throw "noncanonical natural"
  return n

def strOf (j : Json) : Except String String := do
  let s ← j.getStr?
  if s.utf8ByteSize > 1048576 then throw "string payload budget"
  return s

partial def nameParts (n : Name) (depth : Nat := 0) : Except String (List Json) := do
  if depth > 64 then throw "name depth budget"
  match n with
  | .anonymous => do pure <| []
  | .str p s => do pure <| (← nameParts p (depth + 1)) ++ [ja [toJson "s", toJson s]]
  | .num p i => do pure <| (← nameParts p (depth + 1)) ++ [ja [toJson "n", jn i]]

def nameJson (n : Name) : Except String Json := return ja (← nameParts n)

def nameOf (j : Json) : Except String Name := do
  let parts ← j.getArr?
  if parts.size > 64 then throw "name depth budget"
  let mut n := Name.anonymous
  for p in parts do
    match (← p.getArr?).toList with
    | [.str "s", s] => n := .str n (← strOf s)
    | [.str "n", i] => n := .num n (← natOf i)
    | _ => throw "invalid name component"
  return n

def dataJson (v : DataValue) : Except String Json := do
  match v with
  | .ofString s => do pure <| ja [toJson "string", toJson s]
  | .ofBool b => do pure <| ja [toJson "bool", toJson b]
  | .ofName n => do pure <| ja [toJson "name", ← nameJson n]
  | .ofNat n => do pure <| ja [toJson "nat", jn n]
  | .ofInt n => do pure <| ja [toJson "int", toJson (toString n)]
  | .ofSyntax _ => throw "syntax-valued metadata unsupported"

def dataOf (j : Json) : Except String DataValue := do
  match (← j.getArr?).toList with
  | [.str "string", s] => do pure <| .ofString (← strOf s)
  | [.str "bool", b] => do pure <| .ofBool (← b.getBool?)
  | [.str "name", n] => do pure <| .ofName (← nameOf n)
  | [.str "nat", n] => do pure <| .ofNat (← natOf n)
  | [.str "int", j] =>
    let s ← j.getStr?
    if s.length > 4096 then throw "integer payload budget"
    let some n := s.toInt? | throw "decimal integer expected"
    unless toString n == s do throw "noncanonical integer"
    return .ofInt n
  | _ => throw "unsupported metadata value"

def metadataJson (m : MData) : Except String Json := do
  if m.entries.length > 256 then throw "metadata entry budget"
  return ja (← m.entries.mapM fun (n, v) => do pure <| ja [← nameJson n, ← dataJson v])

def metadataOf (j : Json) : Except String MData := do
  let rows ← j.getArr?
  if rows.size > 256 then throw "metadata entry budget"
  let entries ← rows.toList.mapM fun row => do
    match (← row.getArr?).toList with
    | [n, v] => do pure <| (← nameOf n, ← dataOf v)
    | _ => throw "invalid metadata entry"
  return { entries := entries }

def binderJson : BinderInfo → Json
  | .default => toJson "explicit"
  | .implicit => toJson "implicit"
  | .strictImplicit => toJson "strictImplicit"
  | .instImplicit => toJson "instance"

def binderOf (j : Json) : Except String BinderInfo := do
  match ← j.getStr? with
  | "explicit" => do pure <| .default
  | "implicit" => do pure <| .implicit
  | "strictImplicit" => do pure <| .strictImplicit
  | "instance" => do pure <| .instImplicit
  | _ => throw "invalid binder annotation"

structure Encoder where
  expressions : Array Json := #[]
  levels : Array Json := #[]
  exprMemo : ExprStructMap Nat := {}
  levelMemo : Std.HashMap Level Nat := {}

abbrev EncodeM := StateT Encoder (Except String)

def room (limit : Nat) : EncodeM Unit := do
  let st ← get
  if st.expressions.size + st.levels.size >= limit then throw "node budget"

partial def putLevel (u : Level) (limit depth : Nat) : EncodeM Nat := do
  if depth > maxDepth then throw "level depth budget"
  if let some i := (← get).levelMemo.get? u then return i
  room limit
  let row ← match u with
    | .zero => pure <| ja [toJson "zero"]
    | .succ a => do pure <| ja [toJson "succ", jn (← putLevel a limit (depth + 1))]
    | .max a b => do pure <| ja [toJson "max", jn (← putLevel a limit (depth + 1)), jn (← putLevel b limit (depth + 1))]
    | .imax a b => do pure <| ja [toJson "imax", jn (← putLevel a limit (depth + 1)), jn (← putLevel b limit (depth + 1))]
    | .param n => do pure <| ja [toJson "param", ← nameJson n]
    | .mvar _ => throw "universe metavariable unsupported"
  room limit
  let i := (← get).levels.size
  modify fun s => { s with levels := s.levels.push row, levelMemo := s.levelMemo.insert u i }
  return i

partial def putExpr (e : Expr) (limit depth : Nat) : EncodeM Nat := do
  if depth > maxDepth then throw "expression depth budget"
  if let some i := (← get).exprMemo.get? ⟨e⟩ then return i
  room limit
  let next := fun a => putExpr a limit (depth + 1)
  let row ← match e with
    | .bvar i => do pure <| ja [toJson "bvar", jn i]
    | .sort u => do pure <| ja [toJson "sort", jn (← putLevel u limit 0)]
    | .const n us => do pure <| ja [toJson "const", ← nameJson n, ja (← us.mapM fun u => do pure <| jn (← putLevel u limit 0))]
    | .app f a => do pure <| ja [toJson "app", jn (← next f), jn (← next a)]
    | .lam n t b bi => do pure <| ja [toJson "lam", ← nameJson n, binderJson bi, jn (← next t), jn (← next b)]
    | .forallE n t b bi => do pure <| ja [toJson "forall", ← nameJson n, binderJson bi, jn (← next t), jn (← next b)]
    | .letE n t v b nd => do pure <| ja [toJson "let", ← nameJson n, toJson nd, jn (← next t), jn (← next v), jn (← next b)]
    | .lit (.natVal n) => do pure <| ja [toJson "nat", jn n]
    | .lit (.strVal s) => do pure <| ja [toJson "string", toJson s]
    | .mdata m b => do pure <| ja [toJson "mdata", ← metadataJson m, jn (← next b)]
    | .proj n i b => do pure <| ja [toJson "proj", ← nameJson n, jn i, jn (← next b)]
    | .fvar _ | .mvar _ => throw "free/metavariable unsupported"
  room limit
  let i := (← get).expressions.size
  modify fun s => { s with expressions := s.expressions.push row, exprMemo := s.exprMemo.insert ⟨e⟩ i }
  return i

def encode (roots : Array Expr) (environment : String) (limit : Nat) : Except String Json := do
  settings environment limit
  if roots.isEmpty || roots.size > 64 then throw "root budget"
  for e in roots do
    if e.hasFVar || e.hasMVar || e.hasLooseBVars then throw "closed expression required"
  let (ids, s) ← (roots.mapM fun e => putExpr e limit 0).run {}
  return Json.mkObj [("schema", toJson schema), ("environment", toJson environment),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("metadata_policy", toJson metadataPolicy), ("levels", .arr s.levels),
    ("expressions", .arr s.expressions), ("roots", .arr (ids.map jn))]

def ref (j : Json) (bound : Nat) : Except String Nat := do
  let n ← natOf j
  if n >= bound then throw "forward or out-of-range reference"
  return n

def getRef {α : Type} (xs : Array α) (j : Json) : Except String α := do
  let i ← ref j xs.size
  match xs[i]? with
  | some x => do pure <| x
  | none => throw "reference missing"

def height (refs : List Json) (depths : Array Nat) : Except String Nat := do
  let h := 1 + (← refs.mapM (getRef depths)).foldl max 0
  if h > maxDepth then throw "DAG depth budget"
  return h

def decode (wire : Json) (environment : String) (limit : Nat) : Except String (Array Expr) := do
  settings environment limit
  if wire.compress.utf8ByteSize > maxBytes then throw "wire byte budget"
  let keys := (← wire.getObj?).toList.map Prod.fst
  unless keys.length == 8 && ["schema", "environment", "lean_version", "lean_githash",
      "metadata_policy", "levels", "expressions", "roots"].all keys.contains do throw "wire fields"
  for (key, expected) in [("schema", schema), ("environment", environment),
       ("lean_version", Lean.versionString), ("lean_githash", Lean.githash), ("metadata_policy", metadataPolicy)] do
    unless (← wire.getObjValAs? String key) == expected do throw s!"{key} mismatch"
  let ls ← (← wire.getObjVal? "levels").getArr?
  let es ← (← wire.getObjVal? "expressions").getArr?
  if es.size + ls.size > limit then throw "node budget"
  let mut levels : Array Level := #[]
  let mut depths : Array Nat := #[]
  for row in ls do
    let (u, refs) ← match (← row.getArr?).toList with
      | [.str "zero"] => pure (Level.zero, [])
      | [.str "succ", a] => do pure <| (Level.succ (← getRef levels a), [a])
      | [.str "max", a, b] => do pure <| (Level.max (← getRef levels a) (← getRef levels b), [a, b])
      | [.str "imax", a, b] => do pure <| (Level.imax (← getRef levels a) (← getRef levels b), [a, b])
      | [.str "param", n] => do pure <| (Level.param (← nameOf n), [])
      | _ => throw "invalid level constructor"
    depths := depths.push (← height refs depths)
    levels := levels.push u
  let mut exprs : Array Expr := #[]
  depths := #[]
  for row in es do
    let (e, refs) ← match (← row.getArr?).toList with
      | [.str "bvar", j] => do
        let n ← natOf j
        if n >= 65536 then throw "bound variable index budget"
        pure (Expr.bvar n, [])
      | [.str "sort", u] => do pure <| (Expr.sort (← getRef levels u), [])
      | [.str "const", n, us] => do
        let us ← us.getArr?
        if us.size > 256 then throw "constant universe arity budget"
        pure (Expr.const (← nameOf n) (← us.toList.mapM (getRef levels)), [])
      | [.str "app", f, a] => do pure <| (Expr.app (← getRef exprs f) (← getRef exprs a), [f, a])
      | [.str "lam", n, bi, t, b] => do pure <| (Expr.lam (← nameOf n) (← getRef exprs t) (← getRef exprs b) (← binderOf bi), [t, b])
      | [.str "forall", n, bi, t, b] => do pure <| (Expr.forallE (← nameOf n) (← getRef exprs t) (← getRef exprs b) (← binderOf bi), [t, b])
      | [.str "let", n, nd, t, v, b] => do pure <| (Expr.letE (← nameOf n) (← getRef exprs t) (← getRef exprs v) (← getRef exprs b) (← nd.getBool?), [t, v, b])
      | [.str "nat", n] => do pure <| (Expr.lit (.natVal (← natOf n)), [])
      | [.str "string", s] => do pure <| (Expr.lit (.strVal (← strOf s)), [])
      | [.str "mdata", m, b] => do pure <| (Expr.mdata (← metadataOf m) (← getRef exprs b), [b])
      | [.str "proj", n, i, b] => do pure <| (Expr.proj (← nameOf n) (← natOf i) (← getRef exprs b), [b])
      | _ => throw "invalid expression constructor"
    depths := depths.push (← height refs depths)
    exprs := exprs.push e
  let ids ← (← wire.getObjVal? "roots").getArr?
  if ids.isEmpty || ids.size > 64 then throw "root budget"
  let roots ← ids.mapM (getRef exprs)
  for e in roots do
    if e.hasFVar || e.hasMVar || e.hasLooseBVars then throw "closed expression required"
  return roots

def checkedEncode (roots : Array Expr) (environment : String) (limit : Nat) : Except String Json := do
  let wire ← encode roots environment limit
  let restored ← decode wire environment limit
  unless roots.size == restored.size && (roots.zip restored).all (fun (a, b) => Expr.equal a b) do
    throw "structural round trip mismatch"
  unless (← encode restored environment limit) == wire do throw "wire round trip mismatch"
  return wire

def exportTheorem (name : Name) (environment : String) (limit : Nat) : CoreM Json := do
  let .thmInfo info ← getConstInfo name | throwError "only theorem declarations supported"
  let wire ← match checkedEncode #[info.value, info.type] environment limit with
    | .ok wire => pure wire
    | .error err => throwError "{err}"
  let roots ← match decode wire environment limit with
    | .ok roots => pure roots
    | .error err => throwError "{err}"
  let env ← getEnv
  let inferred ← match Kernel.check env {} roots[0]! with
    | .ok t => pure t
    | .error _ => throwError "decoded proof failed kernel check"
  unless Kernel.isDefEqGuarded env {} inferred roots[1]! do throwError "decoded theorem type mismatch"
  let axioms ← collectAxioms name
  return Json.mkObj [("schema", toJson "jevops-lean-expr-export/v1"), ("declaration", toJson name.toString),
    ("level_parameters", ja (← info.levelParams.mapM fun n => match nameJson n with
      | .ok j => pure j | .error s => throwError "{s}")),
    ("dag", wire), ("exact_roundtrip", toJson true), ("kernel_typechecked", toJson true),
    ("axioms", toJson (axioms.map Name.toString)), ("proof_admitted", toJson false),
    ("independent_kernel_verifier_used", toJson false)]

def readBounded (stream : IO.FS.Stream) (limit : Nat := maxBytes) : IO String := do
  let mut input := ByteArray.empty
  repeat
    let chunk ← stream.read (USize.ofNat (min 65536 (limit + 1 - input.size)))
    if chunk.isEmpty then break
    input := input ++ chunk
    if input.size > limit then throw (IO.userError "wire byte budget")
  match String.fromUTF8? input with
  | some s => return s
  | none => throw (IO.userError "wire must be UTF-8")

end JevOpsDAG

def main (args : List String) : IO UInt32 := do
  match args with
  | ["export", directory, moduleName, declaration, environment, budget] =>
    let some limit := budget.toNat? | throw (IO.userError "invalid budget")
    match JevOpsDAG.settings environment limit with
    | .error e => throw (IO.userError e)
    | .ok _ => pure ()
    initSearchPath (← findSysroot) [System.FilePath.mk directory]
    let env ← importModules #[{ module := moduleName.toName }] {}
    let (report, _) ← (JevOpsDAG.exportTheorem declaration.toName environment limit).toIO
      { fileName := "ExprDAG", fileMap := default, maxRecDepth := 2048 } { env := env }
    IO.println ("JEVOPS_EXPR_DAG:" ++ report.compress)
    return 0
  | ["roundtrip", environment, budget] =>
    let some limit := budget.toNat? | throw (IO.userError "invalid budget")
    match JevOpsDAG.settings environment limit with
    | .error e => throw (IO.userError e)
    | .ok _ => pure ()
    let input ← JevOpsDAG.readBounded (← IO.getStdin)
    let result := do
      let wire ← Json.parse input
      let roots ← JevOpsDAG.decode wire environment limit
      let output ← JevOpsDAG.checkedEncode roots environment limit
      unless output == wire do throw "noncanonical or unreachable DAG nodes"
      return output
    match result with
    | .ok wire => IO.println ("JEVOPS_EXPR_DAG:" ++ wire.compress); return 0
    | .error err => throw (IO.userError err)
  | _ => throw (IO.userError "expected export DIR MODULE DECL ENV BUDGET or roundtrip ENV BUDGET")
