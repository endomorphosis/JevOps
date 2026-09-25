import Lean

/- Diagnostic tail joined to the trusted ArenaCheck library by the local test
   runner. It describes environments; it does NOT issue verification receipts. -/
open Lean Elab

private def infoKind : Option ConstantInfo → String
  | none => "missing"
  | some (.thmInfo _) => "theorem"
  | some (.axiomInfo _) => "axiom"
  | some _ => "other"

private def inspectTarget (state : Command.State) (target : Name) : IO Json := do
  let env := state.env
  let matchingNames := env.checked.get.constants.map₂.toList.filterMap fun (name, info) =>
    if name.toString.endsWith target.getString! then
      some (Json.mkObj [("name", toJson name.toString), ("kind", toJson (infoKind (some info)))])
    else none
  return Json.mkObj [
    ("is_module", toJson env.header.isModule),
    ("is_exporting", toJson env.isExporting),
    ("scope_namespace", toJson state.scopes.head!.currNamespace.toString),
    ("scope_public", toJson state.scopes.head!.isPublic),
    ("visible_kind", toJson (infoKind (env.find? target))),
    ("private_kind", toJson (infoKind ((env.setExporting false).find? target))),
    ("checked_kind", toJson (infoKind (env.checked.get.find? target))),
    ("matching_local_constants", toJson matchingNames),
    ("messages", ← JevOpsArena.diagnostics state.messages)]

unsafe def main : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let input ← (← IO.getStdin).readToEnd
  let json ← IO.ofExcept (Json.parse input)
  let field := fun key => IO.ofExcept ((json.getObjVal? key).bind Json.getStr?)
  let target := (← field "target").toName
  let initial ← JevOpsArena.prefixState (← field "prefix") 2000000
  let (original, _) ← JevOpsArena.branch initial (← field "reference") target 2000000
  IO.println ("JEVOPS_TARGET_DIAGNOSTIC:" ++ (Json.mkObj [
    ("initial", ← inspectTarget initial target),
    ("original", ← inspectTarget original target)]).compress)
  return 0
