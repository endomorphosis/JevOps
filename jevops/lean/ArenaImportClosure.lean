import Lean

/- Assembled with ArenaCheck's trusted prefix reader. This is a host-side
   dependency inventory, never a proof-verification or compression receipt. -/
open Lean Elab

unsafe def main : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let json ← IO.ofExcept (Json.parse (← (← IO.getStdin).readToEnd))
  let inputPrefix ← IO.ofExcept (json.getObjValAs? String "prefix")
  let target ← IO.ofExcept (json.getObjValAs? String "target")
  let request ← IO.ofExcept (json.getObjValAs? String "request_sha256")
  let initial ← JevOpsArena.prefixState inputPrefix 2000000
  if initial.messages.hasErrors then
    throw (IO.userError "import discovery prefix failed")
  if (initial.env.checked.get.find? target.toName).isSome then
    throw (IO.userError "discovery target already imported")
  -- The verifier needs private imported proof bodies for its separate axiom
  -- audit. Inventory that closure as well, without changing the prefix state.
  let audit ← importModules initial.env.header.imports {} (trustLevel := 0)
  let mut seen : NameSet := {}
  let mut modules : Array Json := #[]
  for name in initial.env.header.moduleNames ++ audit.header.moduleNames do
    if seen.contains name then continue
    if modules.size >= 4096 then throw (IO.userError "module inventory bound")
    seen := seen.insert name
    let path ← findOLean name
    unless ← path.pathExists do throw (IO.userError "missing imported artifact")
    modules := modules.push (Json.mkObj [
      ("name", toJson name.toString), ("olean", toJson path.toString)])
  IO.println ("JEVOPS_IMPORT_CLOSURE:" ++ (Json.mkObj [
    ("schema", toJson "jevops-native-import-closure/v1"),
    ("request_sha256", toJson request),
    ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash),
    ("modules", toJson modules)]).compress)
  return 0
