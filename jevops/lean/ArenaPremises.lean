import Lean

/- Assembled with JevOpsArena's prefix reader. Only trusted project prefixes
   are elaborated; no candidate or reference proof is sent to this process. -/
open Lean Elab

namespace JevOpsPremises

def auditInfo (env imports : Environment) (name : Name) : Except String ConstantInfo := do
  match env.checked.get.find? name with
  | some (.axiomInfo a) =>
    if env.checked.get.const2ModIdx.contains name then
      let some richer := imports.checked.get.find? name | throw "audit_missing"
      unless richer.type == a.type && richer.levelParams == a.levelParams do
        throw "audit_mismatch"
      return richer
    else return .axiomInfo a
  | some info => return info
  | none =>
    let some info := imports.checked.get.find? name | throw "audit_missing"
    return info

def closure (env imports : Environment) (root : Name) (budget : Nat)
    : Except String (Array String × Array String) := do
  let mut todo := #[root]
  let mut seen : NameSet := {}
  let mut names : Array String := #[]
  let mut axioms : Array String := #[]
  while !todo.isEmpty do
    let name := todo.back!
    todo := todo.pop
    if seen.contains name then continue
    if names.size >= budget then throw "dependency_budget"
    seen := seen.insert name
    names := names.push name.toString
    let info ← auditInfo env imports name
    let mut expressions := #[info.type]
    match info with
    | .axiomInfo _ => axioms := axioms.push name.toString
    | .thmInfo t => expressions := expressions.push t.value
    | .defnInfo d => expressions := expressions.push d.value
    | .opaqueInfo o => expressions := expressions.push o.value
    | .inductInfo i => todo := todo ++ i.ctors.toArray
    | _ => pure ()
    for expression in expressions do
      for dependency in expression.getUsedConstants do
        unless seen.contains dependency do todo := todo.push dependency
    -- The name budget also bounds the traversal frontier, not just the result.
    if todo.size > budget * 16 then throw "dependency_budget"
  return (names.qsort (· < ·), axioms.qsort (· < ·))

def excluded (name status : String) : Json :=
  Json.mkObj [("name", toJson name), ("status", toJson status)]

def headSignature (expr : Expr) : Option Json := Id.run do
  let mut e := expr
  let mut arity := 0
  for _ in [:257] do
    match e with
    | .app f _ => e := f; arity := arity + 1
    | .mdata _ body => e := body
    | _ =>
      if let .const n _ := e then
        if n.toString.utf8ByteSize > 1024 then return none
      let (kind, name) := match e with
        | .const n _ => ("const", toJson n.toString)
        | .bvar _ => ("bound", Json.null)
        | .sort _ => ("sort", Json.null)
        | _ => ("other", Json.null)
      return some (Json.mkObj [("kind", toJson kind), ("name", name), ("arity", toJson arity)])
  return none

def typeSignature (name : String) (type : Expr) : Option Json := Id.run do
  let mut e := type
  let mut kinds : Array String := #[]
  let mut heads : Array Json := #[]
  for _ in [:129] do
    match e with
    | .mdata _ body => e := body
    | .forallE _ domain body binder =>
      if kinds.size == 64 then return none
      let some head := headSignature domain | return none
      kinds := kinds.push (match binder with
        | .default => "explicit" | .implicit => "implicit"
        | .strictImplicit => "strict_implicit" | .instImplicit => "instance")
      heads := heads.push head
      e := body
    | _ =>
      let some head := headSignature e | return none
      let signature := Json.mkObj [("schema", toJson "jevops-premise-signature/v1"),
        ("name", toJson name), ("binder_kinds", toJson kinds),
        ("binder_heads", toJson heads), ("conclusion", head)]
      if signature.compress.utf8ByteSize > 15000 then return none
      return some signature
  return none

unsafe def exportNames (before : String) (target : Name) (names : Array String)
    (limit budget : Nat) (signatures : Bool := false) : IO Json := do
  let initial ← JevOpsArena.prefixState before limit
  if initial.messages.hasErrors then
    return Json.mkObj [("status", toJson "UNAVAILABLE"), ("reason", toJson "prefix_errors")]
  if initial.env.contains target then
    return Json.mkObj [("status", toJson "ERROR"), ("reason", toJson "target_already_available")]
  -- Rich private import data is used ONLY to audit dependencies, never to
  -- enlarge the visible environment or to pretty-print inaccessible constants.
  let imports ← if initial.env.header.isModule then
    importModules initial.env.header.imports {} (trustLevel := 0)
    else pure initial.env
  let rows ← names.mapM fun text => do
    let name := text.toName
    if isPrivateName name then return excluded text "PRIVATE"
    let some info := initial.env.find? name | return excluded text "MISSING"
    if info.type.hasMVar || info.type.hasFVar then return excluded text "OPEN_TYPE"
    match closure initial.env imports name budget with
    | .error reason => return excluded text reason
    | .ok (dependencies, axioms) =>
      let opts := (JevOpsArena.options {} limit).setBool `pp.fullNames true
      let typeText := (← PrettyPrinter.ppExprLegacy initial.env {} {} opts info.type).pretty
      if typeText.utf8ByteSize > 16384 then return excluded text "TYPE_BUDGET"
      let fields := [("name", toJson text), ("status", toJson "AVAILABLE"),
        ("type_text", toJson typeText), ("dependencies", toJson dependencies),
        ("axioms", toJson axioms)]
      return Json.mkObj (if signatures then fields ++ [("signature", toJson (typeSignature text info.type))] else fields)
  return Json.mkObj [("status", toJson "EXPORTED"), ("entries", toJson rows)]

end JevOpsPremises

unsafe def main : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let input ← (← IO.getStdin).readToEnd
  let j ← IO.ofExcept (Json.parse input)
  let field := fun key => IO.ofExcept (j.getObjValAs? String key)
  let target ← field "target"
  let schema ← field "schema"
  unless schema == "jevops-native-premises-stage/v1" || schema == "jevops-native-premises-stage/v2" do
    throw (IO.userError "unsupported inventory schema")
  let names ← IO.ofExcept (j.getObjValAs? (Array String) "names")
  let budget ← IO.ofExcept (j.getObjValAs? Nat "dependency_budget")
  let limit ← IO.ofExcept (j.getObjValAs? Nat "max_heartbeats")
  unless 0 < names.size && names.size <= 64 && 0 < budget && budget <= 4096 && 0 < limit do
    throw (IO.userError "inventory bounds")
  let report ← JevOpsPremises.exportNames (← field "prefix") target.toName names limit budget
    (schema == "jevops-native-premises-stage/v2")
  IO.println ("JEVOPS_PREMISES:" ++ (Json.mkObj [
    ("schema", toJson schema),
    ("request_sha256", toJson (← field "request_sha256")), ("target", toJson target),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("report", report)]).compress)
  return 0
