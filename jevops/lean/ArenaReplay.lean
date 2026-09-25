import Lean

/- Assembled with the existing JevOpsDAG and JevOpsArena libraries by
   arena_replay.py. The checker never elaborates candidate source, imports a
   candidate .olean or executes candidate initializers. Exported data is not
   evidence of its correspondence to the submitted source or measured cost. -/
open Lean Elab

namespace JevOpsArenaReplay

def outcome (status reason : String) : Json :=
  Json.mkObj [("status", toJson status), ("reason", toJson reason)]

def field (j : Json) (key : String) : IO String :=
  IO.ofExcept (j.getObjValAs? String key)

def coldMethod := "fresh-process-single-command-raw-heartbeats/v1"

unsafe def produce (j : Json) (target : Name) (environment : String) (limit nodes : Nat)
    (measure : Bool := false) : IO Json := do
  -- Keep the effectful field read inside the branch: an inline monadic bind
  -- in a Boolean operand would also run for ordinary, non-measurement replay.
  if measure then
    unless (← field j "measurement") == coldMethod do
      return outcome "ERROR" "measurement_method_mismatch"
  let before ← JevOpsArena.prefixState (← field j "prefix") limit
  if before.messages.hasErrors then return outcome "UNAVAILABLE" "prefix_errors"
  if before.env.contains target then return outcome "ERROR" "target_already_available"
  -- Exactly ONE branch in this producer. Parsing/prefix construction precede
  -- the branch counter; export and checking follow it. No reference warm-up.
  let (changed, raw) ← JevOpsArena.branch before (← field j "candidate") target limit
  if changed.messages.hasErrors then return outcome "REJECTED" "candidate_errors"
  let some (.thmInfo info) := changed.env.find? target
    | return outcome "REJECTED" "candidate_target_missing"
  match JevOpsDAG.checkedEncode #[info.value, info.type] environment nodes with
  | .error reason => return outcome "UNSUPPORTED" reason
  | .ok wire =>
    let names ← IO.ofExcept (info.levelParams.mapM JevOpsDAG.nameJson)
    let fields := [("status", toJson "EXPORTED"), ("reason", toJson ""),
      ("export", Json.mkObj [("target", toJson target.toString),
        ("level_parameters", JevOpsDAG.ja names), ("dag", wire)])]
    -- Still producer-reported, not authenticated against hostile metaprograms.
    return Json.mkObj (fields ++ if measure then
      [("measurement", toJson coldMethod), ("raw_heartbeats", toJson raw)] else [])

unsafe def checkData (j : Json) (target : Name) (environment : String) (limit nodes : Nat) : IO Json := do
  -- Only the trusted challenge/reference is elaborated in this process.
  let before ← JevOpsArena.prefixState (← field j "prefix") limit
  if before.messages.hasErrors then return outcome "UNAVAILABLE" "prefix_errors"
  if before.env.contains target then return outcome "ERROR" "target_already_available"
  let (reference, _) ← JevOpsArena.branch before (← field j "reference") target limit
  if reference.messages.hasErrors then return outcome "ERROR" "reference_errors"
  let some (.thmInfo expected) := reference.env.find? target
    | return outcome "ERROR" "reference_target_missing"
  let allowed ← IO.ofExcept (j.getObjValAs? (Array String) "allowed_axioms")
  let originalAxioms ← JevOpsArena.axioms reference target
  unless originalAxioms.all allowed.contains do return outcome "ERROR" "reference_axiom_policy"
  let artifact ← IO.ofExcept (j.getObjVal? "export")
  unless (← field artifact "target") == target.toString do return outcome "REJECTED" "export_target_mismatch"
  let params ← IO.ofExcept do
    let rows ← (← artifact.getObjVal? "level_parameters").getArr?
    if rows.size > 256 then throw "universe parameter budget"
    rows.toList.mapM JevOpsDAG.nameOf
  let wire ← IO.ofExcept (artifact.getObjVal? "dag")
  let roots ← IO.ofExcept (JevOpsDAG.decode wire environment nodes)
  unless roots.size == 2 do return outcome "REJECTED" "two_roots_required"
  unless (← IO.ofExcept (JevOpsDAG.checkedEncode roots environment nodes)) == wire do
    return outcome "REJECTED" "noncanonical_export"
  unless params == expected.levelParams && Expr.equal roots[1]! expected.type do
    return outcome "REJECTED" "challenge_type_or_universes_mismatch"
  -- V1 accepts no new auxiliary declarations. Constants must be available in
  -- the original target-free prefix, not the reference branch or producer.
  for root in roots do
    for name in root.getUsedConstants do
      unless before.env.contains name do return outcome "UNSUPPORTED" "new_or_missing_constant"
  let decl := Declaration.thmDecl {
    name := target, levelParams := params, type := expected.type, value := roots[0]! }
  try
    -- addDecl kernel-checks, without compiling or evaluating the proof. Any
    -- exception (including its recovery path) returns a non-success outcome.
    let (_, checked) ← Core.CoreM.toIO (addDecl decl)
      { fileName := "ArenaProofData", fileMap := default, maxRecDepth := 2048,
        options := JevOpsArena.options {} limit } { env := before.env }
    if checked.messages.hasErrors then return outcome "REJECTED" "kernel_messages"
    let found ← JevOpsArena.axioms { before with env := checked.env } target
    unless found.all (fun a => allowed.contains a && originalAxioms.contains a) do
      return outcome "REJECTED" "axiom_expansion"
    return Json.mkObj [("status", toJson "PROOF_DATA_CHECKED"), ("reason", toJson ""),
      ("axioms", toJson found), ("reference_axioms", toJson originalAxioms)]
  catch _ => return outcome "REJECTED" "kernel_rejected"

end JevOpsArenaReplay

unsafe def main : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution -- only trusted prefix/imports in checker mode
  let input ← JevOpsDAG.readBounded (← IO.getStdin)
  let j ← IO.ofExcept (Json.parse input)
  let mode ← JevOpsArenaReplay.field j "mode"
  let request ← JevOpsArenaReplay.field j "request_id"
  let environment ← JevOpsArenaReplay.field j "environment"
  let target ← JevOpsArenaReplay.field j "target"
  let limit ← IO.ofExcept (j.getObjValAs? Nat "max_heartbeats")
  let nodes ← IO.ofExcept (j.getObjValAs? Nat "node_budget")
  if limit == 0 || limit > 10000000 then throw (IO.userError "bounded heartbeat limit required")
  let report ← if mode == "produce" then
      JevOpsArenaReplay.produce j target.toName environment limit nodes
    else if mode == "measure" then
      JevOpsArenaReplay.produce j target.toName environment limit nodes true
    else if mode == "check" then
      JevOpsArenaReplay.checkData j target.toName environment limit nodes
    else throw (IO.userError "unknown replay mode")
  IO.println <| "JEVOPS_ARENA_REPLAY:" ++ (Json.mkObj [
    ("schema", toJson "jevops-arena-term-replay-stage/v1"), ("mode", toJson mode),
    ("request_id", toJson request), ("environment", toJson environment),
    ("target", toJson target), ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash), ("report", report)]).compress
  return 0
