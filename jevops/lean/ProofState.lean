import Lean

/- Observation only: this exports a bounded projection of elaborator states, not
   a replay checkpoint, a kernel certificate, or a declaration admission API. -/
open Lean Elab

namespace JevOpsProofState

def jn (n : Nat) : Json := toJson (toString n)
def ja (xs : List Json) : Json := .arr xs.toArray

partial def nameJson (n : Name) (depth : Nat := 0) : Except String Json := do
  if depth > 64 then throw "name depth budget"
  match n with
  | .anonymous => return .arr #[]
  | .str p s =>
    if s.utf8ByteSize > 65536 then throw "name byte budget"
    return .arr ((← (← nameJson p (depth + 1)).getArr?).push (ja [toJson "s", toJson s]))
  | .num p i => return .arr ((← (← nameJson p (depth + 1)).getArr?).push (ja [toJson "n", jn i]))

def binder : BinderInfo → String
  | .default => "explicit" | .implicit => "implicit"
  | .strictImplicit => "strictImplicit" | .instImplicit => "instance"

def localKind : LocalDeclKind → String
  | .default => "default" | .implDetail => "implDetail" | .auxDecl => "auxDecl"

def mvarKind : MetavarKind → String
  | .natural => "natural" | .synthetic => "synthetic" | .syntheticOpaque => "syntheticOpaque"

structure Encoder where
  exprs : Array Json := #[]
  levels : Array Json := #[]
  exprMemo : ExprStructMap Nat := {}
  levelMemo : Std.HashMap Level Nat := {}
  pending : Array MVarId := #[]
  seen : Std.HashSet MVarId := {}
  pendingLevels : Array LMVarId := #[]
  seenLevels : Std.HashSet LMVarId := {}

abbrev M := StateT Encoder (Except String)

def room (limit : Nat) : M Unit := do
  let s ← get
  if s.exprs.size + s.levels.size >= limit then throw "graph node budget"

def queue (id : MVarId) : M Unit := do
  unless (← get).seen.contains id do
    if (← get).pending.size >= 256 then throw "metavariable budget"
    modify fun s => { s with pending := s.pending.push id, seen := s.seen.insert id }

partial def level (u : Level) (limit : Nat) (depth : Nat := 0) : M Nat := do
  if depth >= 128 then throw "level depth budget"
  if let some i := (← get).levelMemo.get? u then return i
  room limit
  let next := fun u => level u limit (depth + 1)
  let row ← match u with
    | .zero => pure (ja [toJson "zero"])
    | .param n => do pure <| ja [toJson "param", ← nameJson n]
    | .succ a => do pure <| ja [toJson "succ", jn (← next a)]
    | .max a b => do pure <| ja [toJson "max", jn (← next a), jn (← next b)]
    | .imax a b => do pure <| ja [toJson "imax", jn (← next a), jn (← next b)]
    | .mvar id => do
      unless (← get).seenLevels.contains id do
        if (← get).pendingLevels.size >= 256 then throw "universe metavariable budget"
        modify fun s => { s with pendingLevels := s.pendingLevels.push id, seenLevels := s.seenLevels.insert id }
      pure <| ja [toJson "mvar", ← nameJson id.name]
  room limit
  let i := (← get).levels.size
  modify fun s => { s with levels := s.levels.push row, levelMemo := s.levelMemo.insert u i }
  return i

def metadata (m : MData) : Except String Json := do
  if m.entries.length > 256 then throw "metadata budget"
  return ja (← m.entries.mapM fun (n, v) => do
    let j ← match v with
      | .ofString s => pure (ja [toJson "string", toJson s])
      | .ofBool b => pure (ja [toJson "bool", toJson b])
      | .ofName n => do pure <| ja [toJson "name", ← nameJson n]
      | .ofNat n => pure (ja [toJson "nat", jn n])
      | .ofInt n => pure (ja [toJson "int", toJson (toString n)])
      | .ofSyntax _ => throw "syntax-valued metadata unsupported"
    return ja [← nameJson n, j])

partial def expr (e : Expr) (limit : Nat) (depth : Nat := 0) : M Nat := do
  if depth >= 128 then throw "expression depth budget"
  if let some i := (← get).exprMemo.get? ⟨e⟩ then return i
  room limit
  let next := fun e => expr e limit (depth + 1)
  let row ← match e with
    | .bvar i => pure (ja [toJson "bvar", jn i])
    | .fvar id => do pure <| ja [toJson "fvar", ← nameJson id.name]
    | .mvar id => do queue id; pure <| ja [toJson "mvar", ← nameJson id.name]
    | .sort u => do pure <| ja [toJson "sort", jn (← level u limit)]
    | .const n us => do
      if us.length > 256 then throw "universe arity budget"
      pure <| ja [toJson "const", ← nameJson n, ja (← us.mapM fun u => return jn (← level u limit))]
    | .app f a => do pure <| ja [toJson "app", jn (← next f), jn (← next a)]
    | .lam n t b bi => do pure <| ja [toJson "lam", ← nameJson n, toJson (binder bi), jn (← next t), jn (← next b)]
    | .forallE n t b bi => do pure <| ja [toJson "forall", ← nameJson n, toJson (binder bi), jn (← next t), jn (← next b)]
    | .letE n t v b nd => do pure <| ja [toJson "let", ← nameJson n, toJson nd, jn (← next t), jn (← next v), jn (← next b)]
    | .lit (.natVal n) => pure (ja [toJson "nat", jn n])
    | .lit (.strVal s) => pure (ja [toJson "string", toJson s])
    | .mdata m b => do pure <| ja [toJson "mdata", ← metadata m, jn (← next b)]
    | .proj n i b => do pure <| ja [toJson "proj", ← nameJson n, jn i, jn (← next b)]
  room limit
  let i := (← get).exprs.size
  modify fun s => { s with exprs := s.exprs.push row, exprMemo := s.exprMemo.insert ⟨e⟩ i }
  return i

def localDecl (d : LocalDecl) (limit : Nat) : M Json := do
  let (value, nondep) ← match d with
    | .cdecl .. => pure (Json.null, false)
    -- Lean treats nondependent `have` entries as typed opaque variables.
    -- Their hidden values may be stale/type-incorrect after reverting locals;
    -- exporting them as definitions invents operational dependencies.
    | .ldecl _ _ _ _ _ true _ => pure (Json.null, true)
    | .ldecl _ _ _ _ v false _ => do pure (jn (← expr v limit), false)
  return Json.mkObj [("id", ← nameJson d.fvarId.name), ("name", ← nameJson d.userName),
    ("index", jn d.index), ("type", jn (← expr d.type limit)), ("value", value),
    ("nondep", toJson nondep), ("binder", toJson (binder d.binderInfo)),
    ("kind", toJson (localKind d.kind))]

-- InfoTree can retain intermediate contexts whose assignments mention cleared
-- locals. Match the wire validator: reject the whole observation, never invent
-- missing declarations or silently omit an assignment/local definition.
def scopedRoot (e : Expr) (allowed : Std.HashSet FVarId) : M Unit := do
  if e.hasLooseBVars || !(collectFVars {} e).fvarIds.all allowed.contains then
    throw "unbound variable in local context"

def capture (mctx : MetavarContext) (goals : List MVarId) (limit : Nat) : Except String Json := do
  if goals.length > 64 then throw "goal budget"
  let ((decls, udecls), st) ← (do
    for id in goals do queue id
    let mut decls := #[]
    let mut i := 0
    while i < (← get).pending.size do
      let id := (← get).pending[i]!
      let some d := mctx.findDecl? id | throw "missing metavariable declaration"
      if (mctx.getDelayedMVarAssignmentCore? id).isSome then
        throw "delayed metavariable assignment unsupported"
      let (locals, allowed) ← d.lctx.foldlM (init := (#[], ({} : Std.HashSet FVarId))) fun (acc, allowed) d => do
        if acc.size >= 256 then throw "local declaration budget"
        let wire ← localDecl d limit
        scopedRoot d.type allowed
        if let some v := d.value? then scopedRoot v allowed
        return (acc.push wire, allowed.insert d.fvarId)
      if d.localInstances.size > 256 then throw "local instance budget"
      let insts ← d.localInstances.mapM fun inst => do
        let root ← expr inst.fvar limit
        scopedRoot inst.fvar allowed
        return ja [← nameJson inst.className, jn root]
      let assigned ← match mctx.getExprAssignmentCore? id with
        | none => pure Json.null
        | some e => do
          let root ← expr e limit
          scopedRoot e allowed
          pure (jn root)
      let typ ← expr d.type limit
      scopedRoot d.type allowed
      decls := decls.push (Json.mkObj [("id", ← nameJson id.name), ("name", ← nameJson d.userName),
        ("type", jn typ), ("locals", .arr locals), ("instances", .arr insts),
        ("assignment", assigned), ("kind", toJson (mvarKind d.kind)),
        ("depth", jn d.depth), ("index", jn d.index), ("scope_args", jn d.numScopeArgs)])
      i := i + 1
    let mut udecls := #[]
    i := 0
    while i < (← get).pendingLevels.size do
      let id := (← get).pendingLevels[i]!
      let some depth := mctx.findLevelDepth? id | throw "missing universe metavariable declaration"
      let assigned ← match mctx.lAssignment.find? id with
        | none => pure Json.null
        | some u => do pure <| jn (← level u limit)
      udecls := udecls.push (Json.mkObj [("id", ← nameJson id.name), ("depth", jn depth),
        ("assignment", assigned)])
      i := i + 1
    pure (decls, udecls) : M _) |>.run {}
  return Json.mkObj [("schema", toJson "jevops-open-proof-state/v2"),
    ("goals", ja (← goals.mapM fun g => nameJson g.name)),
    ("expressions", .arr st.exprs), ("levels", .arr st.levels),
    ("metavariables", .arr decls), ("universe_metavariables", .arr udecls),
    ("depth", jn mctx.depth), ("level_assign_depth", jn mctx.levelAssignDepth)]

structure Trace where
  events : Array Json := #[]
  nodes : Array (ContextInfo × TacticInfo) := #[]
  spans : Std.HashSet (Nat × Nat) := {}
  visited : Nat := 0
  bytes : Nat := 0

-- Lean normalizes CRLF before parsing. Export offsets in the caller's original
-- UTF-8 source, including both bytes of each CRLF, not in the normalized copy.
def sourceOffsets (input : String) : Array Nat := Id.run do
  let bytes := input.toUTF8
  let mut offsets := #[0]
  let mut i := 0
  while i < bytes.size do
    i := i + (if bytes[i]! == 13 && bytes[i+1]? == some 10 then 2 else 1)
    offsets := offsets.push i
  return offsets

-- Reserve equal wire space per possible event. An oversized observation is
-- wholly unsupported, never a clipped local context or a partial proof state.
-- Later small events retain their identities and cannot be starved of space by
-- an earlier large observation. Keep the independent whole-trace bound below.
def boundedEvent (base fields : List (String × Json)) (eventsLimit : Nat) : Except String Json := do
  if eventsLimit == 0 || eventsLimit > 256 then throw "invalid event budget"
  let limit := 16000000 / eventsLimit
  let event := Json.mkObj (base ++ fields)
  if event.compress.utf8ByteSize <= limit then return event
  let unsupported := Json.mkObj (base ++ [("status", toJson "unsupported"),
    ("reason", toJson "event observation byte budget")])
  if unsupported.compress.utf8ByteSize > limit then throw "event metadata byte budget"
  return unsupported

partial def visit (tree : InfoTree) (ctx? : Option ContextInfo) (parent : Option Nat)
    (limit eventsLimit : Nat) (offsets : Array Nat) (depth : Nat := 0)
    (closingSpans : Bool := false) : StateT Trace (Except String) Unit := do
  if depth >= 256 || (← get).visited >= 100000 then throw "InfoTree traversal budget"
  modify fun s => { s with visited := s.visited + 1 }
  match tree with
  | .context ctx child => visit child (ctx.mergeIntoOuter? ctx?) parent limit eventsLimit offsets (depth + 1) closingSpans
  | .hole _ => throw "unresolved InfoTree hole"
  | .node info children =>
    let mut childParent := parent
    if let .ofTacticInfo t := info then
      let some ctx := ctx? | throw "missing elaborator context"
      let start := t.stx.getPos?.bind (fun p => offsets[p.byteIdx]?)
      let stop := t.stx.getTailPos?.bind (fun p => offsets[p.byteIdx]?)
      let span := (start.getD 0, stop.getD 0)
      let selected := !closingSpans || (t.goalsBefore.length == 1 && t.goalsAfter.isEmpty &&
        start.isSome && stop.isSome && span.1 < span.2 && !(← get).spans.contains span)
      if selected then
        let id := (← get).events.size
        if id >= eventsLimit then throw "event budget"
        let base := [("id", jn id), ("parent", parent.map jn |>.getD Json.null),
          ("declaration", ← nameJson (ctx.parentDecl?.getD .anonymous)),
          ("namespace", ← nameJson ctx.currNamespace),
          ("syntax_kind", ← nameJson t.stx.getKind),
          ("start", start.map jn |>.getD Json.null), ("end", stop.map jn |>.getD Json.null)]
        let pair := do
          let before ← capture t.mctxBefore t.goalsBefore limit
          let after ← capture t.mctxAfter t.goalsAfter limit
          pure (before, after)
        let fields := match pair with
          | .ok (before, after) => [("status", toJson "captured"), ("before", before), ("after", after)]
          | .error reason => [("status", toJson "unsupported"), ("reason", toJson reason)]
        let event ← boundedEvent base fields eventsLimit
        let bytes := (← get).bytes + event.compress.utf8ByteSize
        if bytes > 16000000 then throw "trace byte budget"
        modify fun s => { s with
          events := s.events.push event
          nodes := s.nodes.push (ctx, t)
          spans := s.spans.insert span
          bytes := bytes }
        childParent := some id
    for child in children do visit child ctx? childParent limit eventsLimit offsets (depth + 1) closingSpans

def readSource : IO String := do
  let stdin ← IO.getStdin
  let mut bytes := ByteArray.empty
  repeat
    let chunk ← stdin.read (USize.ofNat (min 65536 (1048577 - bytes.size)))
    if chunk.isEmpty then break
    bytes := bytes ++ chunk
    if bytes.size > 1048576 then throw (IO.userError "source byte budget")
  let some source := String.fromUTF8? bytes | throw (IO.userError "source must be UTF-8")
  return source

def settings (environment : String) (limit eventsLimit : Nat) : IO Unit := do
  if environment.length != 64 || !environment.toList.all (fun c =>
      ('0' ≤ c && c ≤ '9') || ('a' ≤ c && c ≤ 'f')) then throw (IO.userError "environment fingerprint required")
  if limit == 0 || limit > 20000 || eventsLimit == 0 || eventsLimit > 256 then
    throw (IO.userError "invalid capture budget")

unsafe def elaborateSource (input : String) : IO Frontend.State := do
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let ictx := Parser.mkInputContext input "JevOpsProofStateInput.lean"
  let (header, ps, messages) ← Parser.parseHeader ictx
  let opts := ({} : Options).setBool `Elab.async false
  let (env, messages) ← processHeader header opts messages ictx
  let commandState := { Command.mkState env messages opts with infoState.enabled := true }
  IO.processCommands ictx ps commandState

def traceStateData (state : Command.State) (input environment : String) (limit eventsLimit : Nat)
    (closingSpans : Bool := false) : IO (Json × Array (ContextInfo × TacticInfo)) := do
  let offsets := sourceOffsets input
  let (_, trace) ← IO.ofExcept ((do
    for tree in state.infoState.trees do visit tree none none limit eventsLimit offsets 0 closingSpans
    : StateT Trace (Except String) Unit).run {})
  return (Json.mkObj [("schema", toJson "jevops-proof-state-trace/v1"),
    ("environment", toJson environment), ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash), ("elaboration_errors", toJson state.messages.hasErrors),
    ("events", .arr trace.events), ("proof_admitted", toJson false), ("replayable", toJson false)], trace.nodes)

def traceState (state : Command.State) (input environment : String) (limit eventsLimit : Nat)
    (closingSpans : Bool := false) : IO Json := do
  return (← traceStateData state input environment limit eventsLimit closingSpans).1

def traceOf (result : Frontend.State) (input environment : String) (limit eventsLimit : Nat) : IO Json :=
  traceState result.commandState input environment limit eventsLimit

unsafe def run (environment : String) (limit eventsLimit : Nat) : IO Json := do
  settings environment limit eventsLimit
  let input ← readSource
  traceOf (← elaborateSource input) input environment limit eventsLimit

/- Replay uses regenerated native context, NOT a decoder for capture's JSON.
   Only closed local telescopes receive a kernel-checked closing result. -/
partial def tacticNodes (tree : InfoTree) (ctx? : Option ContextInfo := none) :
    Array (ContextInfo × TacticInfo) := Id.run do
  match tree with
  | .context ctx child => return tacticNodes child (ctx.mergeIntoOuter? ctx?)
  | .node info children =>
    let mut out := #[]
    if let .ofTacticInfo t := info then
      if let some ctx := ctx? then out := out.push (ctx, t)
    for child in children do out := out ++ tacticNodes child ctx?
    return out
  | .hole _ => return #[]

def closed (e : Expr) : Bool := !e.hasFVar && !e.hasMVar && !e.hasLooseBVars

abbrev ProofAudit := Environment → Expr → IO (Array Name)

def coreProofAxioms (env : Environment) (proof : Expr) : IO (Array Name) := do
  let (names, _) ← Core.CoreM.toIO (do
    let mut found := #[]
    for c in proof.getUsedConstants do
      for a in ← collectAxioms c do
        unless found.contains a do found := found.push a
    return found) { fileName := "JevOpsLocalAudit", fileMap := default } { env }
  return names

def replayClosedResult (ctx : ContextInfo) (t : TacticInfo) (stx : Syntax)
    (audit : ProofAudit := coreProofAxioms) (materialize : Bool := false) : IO (Json × Option String) := do
  try
    ctx.runMetaM {} do
      setMCtx t.mctxBefore
      if t.goalsBefore.isEmpty || t.goalsBefore.length > 16 then
        throwError "replay requires 1..16 visible goals"
      let env ← getEnv
      let expected ← t.goalsBefore.mapM fun goal => goal.withContext do
        if ← goal.isAssigned then throwError "before goal already assigned"
        let d ← goal.getDecl
        let typ ← instantiateMVars (← Meta.mkForallFVars d.lctx.getFVars d.type
          (usedLetOnly := false) (generalizeNondepLet := true))
        unless closed typ do throwError "open local telescope unsupported"
        match Kernel.check env {} typ with
        | .error _ => throwError "invalid before telescope"
        | .ok _ => pure ()
        return typ
      let goals ← Term.TermElabM.run' do
        Tactic.run t.goalsBefore.head! do
          Tactic.setGoals t.goalsBefore
          withReader (fun c => { c with recover := false }) (Tactic.evalTactic stx)
          Term.synthesizeSyntheticMVarsNoPostponing
      if (← Core.getMessageLog).hasErrors then throwError "replay logged elaboration errors"
      if !goals.isEmpty then
        return (Json.mkObj [("status", toJson "open_goals"), ("closed_goals_checked", jn 0),
          ("remaining_goals", jn goals.length), ("axioms", ja [])], none)
      let mut axioms : Array Name := #[]
      let mut candidate : Option String := none
      for (goal, typ) in t.goalsBefore.zip expected do
        let (found, text) ← goal.withContext do
          let d ← goal.getDecl
          let value ← instantiateMVars (mkMVar goal)
          let proof ← instantiateMVars (← Meta.mkLambdaFVars d.lctx.getFVars value
            (usedLetOnly := false) (generalizeNondepLet := true))
          unless closed proof do throwError "unassigned or unbound replay proof"
          let inferred ← match Kernel.check env {} proof with
            | .ok inferred => pure inferred
            | .error _ => throwError "replayed proof failed kernel check"
          unless Kernel.isDefEqGuarded env {} inferred typ do throwError "replay changed goal type"
          -- Audit the same ORIGINAL environment used by the kernel, never a
          -- tactic's replacement environment. The injected project audit may
          -- inspect private import bodies but cannot expose them to the tactic.
          let found ← audit env proof
          let text ← if materialize && t.goalsBefore.length == 1 then do
              -- Delaboration is a proposal, not a proof serialization. The caller
              -- must replay the printed term from the ORIGINAL before-context.
              let fmt ← withOptions (fun o => (o.setBool `pp.fullNames true).setBool `pp.proofs true)
                (PrettyPrinter.ppExpr value)
              let text := "exact " ++ fmt.pretty 4096
              if text.utf8ByteSize > 4096 then throwError "materialized candidate byte budget"
              pure (some text)
            else pure none
          return (found, text)
        candidate := text
        for a in found do
          unless axioms.contains a do axioms := axioms.push a
      unless axioms.all (fun a => [``propext, ``Classical.choice, ``Quot.sound].contains a) do
        throwError "replay uses forbidden axioms: {axioms.map Name.toString}"
      return (Json.mkObj [("status", toJson "closed_kernel_checked"),
        ("closed_goals_checked", jn expected.length), ("remaining_goals", jn 0),
        ("axioms", toJson (axioms.map Name.toString))], candidate)
  catch e =>
    return (Json.mkObj [("status", toJson "rejected"), ("closed_goals_checked", jn 0),
      ("remaining_goals", Json.null), ("axioms", ja []),
      ("reason", toJson (String.ofList ((toString e).toList.take 1024)))], none)

def replayClosed (ctx : ContextInfo) (t : TacticInfo) (stx : Syntax)
    (audit : ProofAudit := coreProofAxioms) : IO Json := do
  return (← replayClosedResult ctx t stx audit).1

def replayState (state : Command.State) (input environment : String)
    (limit eventsLimit eventId : Nat) (candidate : String) (closingSpans : Bool := false)
    (audit : ProofAudit := coreProofAxioms) : IO Json := do
  settings environment limit eventsLimit
  if candidate.utf8ByteSize > 4096 then throw (IO.userError "candidate byte budget")
  -- Validate traversal bounds before collecting native references.
  let (trace, nodes) ← traceStateData state input environment limit eventsLimit closingSpans
  if state.messages.hasErrors then throw (IO.userError "original source has elaboration errors")
  let some (ctx, t) := nodes[eventId]? | throw (IO.userError "event outside trace")
  let events ← IO.ofExcept ((← IO.ofExcept (trace.getObjVal? "events")).getArr?)
  let some anchor := events[eventId]? | throw (IO.userError "missing event anchor")
  let baseline ← replayClosed ctx t t.stx audit
  let stx ← IO.ofExcept (Parser.runParserCategory ctx.env `tactic candidate)
  let proposed ← replayClosed ctx t stx audit
  return Json.mkObj [("schema", toJson "jevops-closed-tactic-replay/v1"),
    ("environment", toJson environment), ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash), ("event", anchor), ("candidate", toJson candidate),
    ("baseline", baseline), ("proposed", proposed), ("proof_admitted", toJson false),
    ("snapshot_decoded", toJson false), ("whole_source_checked", toJson false)]

unsafe def runReplay (environment : String) (limit eventsLimit eventId : Nat) (candidate : String) : IO Json := do
  settings environment limit eventsLimit
  let input ← readSource
  replayState (← elaborateSource input).commandState input environment limit eventsLimit eventId candidate

end JevOpsProofState

unsafe def main (args : List String) : IO UInt32 := do
  match args with
  | ["replay", environment, nodes, events, eventId, candidate] =>
    let some nodes := nodes.toNat? | throw (IO.userError "invalid node budget")
    let some events := events.toNat? | throw (IO.userError "invalid event budget")
    let some eventId := eventId.toNat? | throw (IO.userError "invalid event ID")
    IO.println ("JEVOPS_TACTIC_REPLAY:" ++ (← JevOpsProofState.runReplay environment nodes events eventId candidate).compress)
    return 0
  | [environment, nodes, events] =>
    let some nodes := nodes.toNat? | throw (IO.userError "invalid node budget")
    let some events := events.toNat? | throw (IO.userError "invalid event budget")
    IO.println ("JEVOPS_PROOF_STATE:" ++ (← JevOpsProofState.run environment nodes events).compress)
    return 0
  | _ => throw (IO.userError "expected ENV NODE_BUDGET EVENT_BUDGET; source on stdin")
