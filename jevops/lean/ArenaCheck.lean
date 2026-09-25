import Lean

/- Trusted local instrumentation, never inserted into the candidate environment.
   Elaborate the reference and candidate independently from the same prefix.
   No target theorem is imported from one branch into the other. -/
open Lean Elab

namespace JevOpsArena

def options (opts : Options) (limit : Nat) : Options :=
  opts.setBool `Elab.async false |>.setBool `debug.skipKernelTC false
    |>.setBool `debug.byAsSorry false |>.setBool `debug.proofAsSorry false
    |> fun opts => maxHeartbeats.set opts limit

def protectedState (state : Command.State) (limit : Nat) : Command.State :=
  { state with scopes := state.scopes.map fun s => { s with opts := options s.opts limit } }

def diagnostics (messages : MessageLog) : IO Json := do
  let rows ← messages.reportedPlusUnreported.toArray.mapM fun m => do
    return Json.mkObj [("severity", toJson (toString m.severity)),
      ("message", toJson (toString ((← m.data.toString).take 4096))),
      ("fileName", toJson m.fileName),
      ("pos", Json.mkObj [("line", toJson m.pos.line), ("column", toJson m.pos.column)])]
  return .arr rows

/- Bounded parser observations, not proof evidence. Collect after BOTH measured
   branches so traversal cannot perturb either branch's heartbeat interval.
   Offsets refer to the original UTF-8 source (Lean normalizes CRLF internally).
   Never return a partial inventory when a traversal bound is reached. -/
def solverSourceOffsets (input : String) : Array Nat := Id.run do
  let bytes := input.toUTF8
  let mut offsets := #[0]
  let mut i := 0
  while i < bytes.size do
    i := i + (if bytes[i]! == 13 && bytes[i+1]? == some 10 then 2 else 1)
    offsets := offsets.push i
  return offsets

structure SolverSpans where
  rows : Array Json := #[]
  visited : Nat := 0

partial def visitSolverSyntax (stx : Syntax) (offsets : Array Nat) (depth : Nat := 0)
    : StateT SolverSpans (Except String) Unit := do
  if depth >= 256 || (← get).visited >= 100000 then throw "syntax traversal budget"
  modify fun s => { s with visited := s.visited + 1 }
  let args := stx.getArgs
  if let some first := args[0]? then
    if first.isAtom && ["simp", "simp_all", "dsimp", "simpa", "grind", "linarith", "nlinarith"].contains first.getAtomVal then
      if let (some start, some stop) := (stx.getPos?, stx.getTailPos?) then
        if let (some a, some b) := (offsets[start.byteIdx]?, offsets[stop.byteIdx]?) then
          if a < b then
            if (← get).rows.size >= 256 then throw "solver span budget"
            let row := Json.mkObj [("start_utf8", toJson a), ("end_utf8", toJson b),
              ("tactic", toJson first.getAtomVal), ("syntax_kind", toJson stx.getKind.toString)]
            modify fun s => { s with rows := s.rows.push row }
  for arg in args do visitSolverSyntax arg offsets (depth + 1)

def solverSyntax (initial : Command.State) (source : String) : IO Json := do
  let ictx := Parser.mkInputContext source "ArenaCandidate.lean"
  let scope := initial.scopes.head!
  let (cmd, _, messages) := Parser.parseCommand ictx
    { env := initial.env, options := scope.opts, currNamespace := scope.currNamespace,
      openDecls := scope.openDecls } {} {}
  let base := [("schema", toJson "jevops-lean-solver-spans/v1"),
    ("source_utf8_bytes", toJson source.utf8ByteSize)]
  let result := if messages.hasErrors then .error "source parse error"
    else (visitSolverSyntax cmd (solverSourceOffsets source)).run {}
  match result with
  | .error reason => return Json.mkObj (base ++ [("status", toJson "UNSUPPORTED"),
      ("reason", toJson reason), ("spans", toJson (#[] : Array Json))])
  | .ok (_, spans) => return Json.mkObj (base ++ [("status", toJson "CAPTURED"),
      ("nodes_visited", toJson spans.visited), ("spans", .arr spans.rows)])

/- Skip EOF elaboration so a prefix may end inside a namespace/section. Parse
   every real command normally; do not infer scope from text or truncate premises. -/
partial def prefixCommands (limit : Nat) : Frontend.FrontendM Unit := do
  Frontend.updateCmdPos
  let state ← Frontend.getCommandState
  -- Header and earlier command errors must survive Lean's per-command reset.
  -- Never elaborate a recovered prefix as if the complete source had passed.
  if state.messages.hasErrors then return
  let scope := state.scopes.head!
  let ictx ← Frontend.getInputContext
  let (cmd, ps, messages) := Parser.parseCommand ictx
    { env := state.env, options := scope.opts, currNamespace := scope.currNamespace,
      openDecls := scope.openDecls } (← Frontend.getParserState) state.messages
  Frontend.setParserState ps
  Frontend.setMessages messages
  if messages.hasErrors then return
  unless Parser.isTerminalCommand cmd do
    -- Keep the accumulated log outside elabCommandTopLevel, which clears it.
    -- Starting with an empty command log also avoids duplicate diagnostics on
    -- older frontends that retain incoming messages.
    Frontend.setCommandState (protectedState { state with messages := {} } limit)
    Frontend.elabCommandAtFrontend cmd
    Frontend.setMessages (messages ++ (← Frontend.getCommandState).messages)
    prefixCommands limit

unsafe def prefixState (input : String) (limit : Nat) : IO Command.State := do
  let ictx := Parser.mkInputContext input "ArenaPrefix.lean"
  let (header, ps, messages) ← Parser.parseHeader ictx
  let opts := options {} limit
  let (env, messages) ← processHeader header opts messages ictx (trustLevel := 0)
  let (_, state) ← (prefixCommands limit).run { inputCtx := ictx }
    |>.run { commandState := Command.mkState env messages opts, parserState := ps, cmdPos := ps.pos }
  return state.commandState

def branch (initial : Command.State) (source : String) (target : Name) (limit : Nat)
    : IO (Command.State × Nat) := do
  let ictx := Parser.mkInputContext source "ArenaCandidate.lean"
  let initial := protectedState { initial with messages := {} } limit
  let scope := initial.scopes.head!
  let (cmd, ps, messages) := Parser.parseCommand ictx
    { env := initial.env, options := scope.opts, currNamespace := scope.currNamespace,
      openDecls := scope.openDecls } {} {}
  if messages.hasErrors then return ({ initial with messages }, 0)
  if Parser.isTerminalCommand cmd then throw (IO.userError "missing declaration")
  let start ← IO.getNumHeartbeats
  let (_, state) ← (Frontend.elabCommandAtFrontend cmd).run { inputCtx := ictx }
    |>.run { commandState := { initial with messages := {} }, parserState := ps, cmdPos := 0 }
  -- async elaboration is disabled; accessing the theorem also forces its value.
  if let some (.thmInfo info) := state.commandState.env.find? target then
    let _ := info.value.hasMVar
    pure ()
  let finish ← IO.getNumHeartbeats
  let final := { state.commandState with messages := messages ++ state.commandState.messages }
  let scope := final.scopes.head!
  let (next, _, messages) := Parser.parseCommand ictx
    { env := final.env, options := scope.opts, currNamespace := scope.currNamespace,
      openDecls := scope.openDecls } ps final.messages
  unless Parser.isTerminalCommand next do throw (IO.userError "additional candidate command")
  return ({ final with messages }, finish - start)

/- Module exports can hide theorem bodies behind axiom-shaped constants. Load
   private import data ONLY for the audit, never into the elaboration branches.
   Traverse the actually checked local proof; replace an imported axiom-shaped
   view only with an exactly matching declaration from the pinned import data.
   A real axiom, including one hidden in a private proof, remains an axiom. -/
structure AuditState where
  visited : NameSet := {}
  axioms : Array Name := #[]

abbrev AuditM := ReaderT (Environment × Environment) (StateT AuditState (Except String))

partial def auditConstant (name : Name) : AuditM Unit := do
  if (← get).visited.contains name then return
  modify fun s => { s with visited := s.visited.insert name }
  let (checked, imports) ← read
  let current := checked.checked.get.find? name
  let imported := imports.checked.get.find? name
  let info ← match current with
    | some (.axiomInfo a) =>
      if checked.checked.get.const2ModIdx.contains name then
        match imported with
        | some richer =>
          if richer.type != a.type || richer.levelParams != a.levelParams then
            throw s!"private audit declaration mismatch: {name}"
          pure richer
        | none => throw s!"private audit declaration missing: {name}"
      else pure (.axiomInfo a)
    | some info => pure info
    | none => match imported with
      | some info => pure info
      | none => throw s!"audit dependency missing: {name}"
  let visit (expr : Expr) : AuditM Unit := expr.getUsedConstants.forM auditConstant
  match info with
  | .axiomInfo a =>
    modify fun s => { s with axioms := s.axioms.push name }
    visit a.type
  | .defnInfo d => visit d.type *> visit d.value
  | .thmInfo t => visit t.type *> visit t.value
  | .opaqueInfo o => visit o.type *> visit o.value
  | .quotInfo _ => pure ()
  | .ctorInfo c => visit c.type
  | .recInfo r => visit r.type
  | .inductInfo i => visit i.type *> i.ctors.forM auditConstant

def axioms (state : Command.State) (target : Name) : IO (Array String) := do
  if !state.env.header.isModule then
    let (names, _) ← Core.CoreM.toIO (collectAxioms target)
      { fileName := "ArenaAudit", fileMap := default } { env := state.env }
    return names.map Name.toString
  let imports ← importModules state.env.header.imports {} (trustLevel := 0)
  let (_, result) ← IO.ofExcept (((auditConstant target).run (state.env, imports)).run {})
  return result.axioms.map Name.toString

unsafe def check (before reference candidate : String) (target : Name) (limit : Nat)
    (candidateFirst : Bool := false) : IO Json := do
  let initial ← prefixState before limit
  if initial.messages.hasErrors then
    return Json.mkObj [("outcome", toJson "UNAVAILABLE"), ("reason", toJson "prefix_errors"),
      ("diagnostics", ← diagnostics initial.messages)]
  if initial.env.contains target then
    return Json.mkObj [("outcome", toJson "ERROR"), ("reason", toJson "target_already_available")]
  -- Both branches use the untouched prefix. Order is explicit for controlled
  -- measurements; neither branch gets the other's theorem as an assumption.
  let ((original, originalRaw), (changed, raw)) ← if candidateFirst then do
    let changed ← branch initial candidate target limit
    let original ← branch initial reference target limit
    pure (original, changed)
  else do
    let original ← branch initial reference target limit
    let changed ← branch initial candidate target limit
    pure (original, changed)
  if original.messages.hasErrors then
    return Json.mkObj [("outcome", toJson "ERROR"), ("reason", toJson "reference_errors"),
      ("diagnostics", ← diagnostics original.messages)]
  let some (.thmInfo originalInfo) := original.env.find? target
    | return Json.mkObj [("outcome", toJson "ERROR"), ("reason", toJson "reference_target_missing")]
  if changed.messages.hasErrors then
    return Json.mkObj [("outcome", toJson "REJECTED"), ("reason", toJson "candidate_errors"),
      ("diagnostics", ← diagnostics changed.messages)]
  let some (.thmInfo info) := changed.env.find? target
    | return Json.mkObj [("outcome", toJson "REJECTED"), ("reason", toJson "candidate_target_missing")]
  -- Structural equality is deliberately stricter than definitional equality.
  let same := originalInfo.levelParams == info.levelParams && originalInfo.type == info.type
  let closed := !info.type.hasMVar && !info.value.hasMVar && !info.value.hasFVar
  return Json.mkObj [("outcome", toJson (if same && closed then "VERIFIED" else "REJECTED")),
    ("reason", toJson (if same && closed then "" else "type_or_closedness_mismatch")),
    ("target_absent_before", toJson true), ("type_preserved", toJson same),
    ("reference_axioms", toJson (← axioms original target)),
    ("axioms", toJson (← axioms changed target)),
    ("raw_heartbeats", toJson raw), ("reference_raw_heartbeats", toJson originalRaw),
    ("heartbeats", toJson (raw / 1000)), ("reference_heartbeats", toJson (originalRaw / 1000)),
    ("diagnostics", ← diagnostics changed.messages),
    ("solver_spans", ← solverSyntax initial candidate)]

end JevOpsArena

unsafe def main : IO UInt32 := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let input ← (← IO.getStdin).readToEnd
  let json ← IO.ofExcept (Json.parse input)
  let field := fun key => IO.ofExcept ((json.getObjVal? key).bind Json.getStr?)
  let request ← field "request_id"
  let target ← field "target"
  let limit ← IO.ofExcept ((json.getObjVal? "max_heartbeats").bind Json.getNat?)
  let candidateFirst := ((json.getObjVal? "candidate_first").bind Json.getBool?).toOption.getD false
  if limit == 0 then throw (IO.userError "finite heartbeat limit required")
  let report ← JevOpsArena.check (← field "prefix") (← field "reference")
    (← field "candidate") target.toName limit candidateFirst
  let result := Json.mkObj [("schema", toJson "jevops-native-arena/v1"),
    ("request_id", toJson request), ("target", toJson target),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("branch_order", toJson (if candidateFirst then "candidate-first" else "reference-first")),
    ("measurement", toJson "command-elaboration-internal-heartbeats-div-1000/v1"),
    ("report", report)]
  IO.println ("JEVOPS_ARENA:" ++ result.compress)
  return 0
