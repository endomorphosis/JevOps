import Lean

/- Composed with the existing Arena prefix parser and ProofState library.
   The prefix is never concatenated to editable source. No namespace guessing,
   shifted offsets, target imports, candidate admission or cost claims. -/
open Lean Elab

/- Reuse the whole-proof verifier's exact private-import audit. The richer
   environment is audit-only; neither elaboration nor replay sees private names.
   Real axioms and missing/mismatched declarations remain failures. -/
def auditLocalProof (env : Environment) (proof : Expr) : IO (Array Name) := do
  if !env.header.isModule then return ← JevOpsProofState.coreProofAxioms env proof
  let imports ← importModules env.header.imports {} (trustLevel := 0)
  let (_, state) ← IO.ofExcept (((proof.getUsedConstants.forM JevOpsArena.auditConstant).run
    (env, imports)).run {})
  return state.axioms

/- One bounded backward application, followed by fresh-context term replay.
   Every generated subgoal must close by assumption. No after-state proof is
   used; failed attempts cannot leave assignments for the next invocation. -/
def discoverApplication (state : Command.State) (input environment : String)
    (limit eventsLimit eventId : Nat) (candidate : String) : IO Json := do
  if candidate.utf8ByteSize > 4096 then throw (IO.userError "candidate byte budget")
  let (trace, nodes) ← JevOpsProofState.traceStateData state input environment limit eventsLimit true
  let some (ctx, t) := nodes[eventId]? | throw (IO.userError "event outside trace")
  let events ← IO.ofExcept ((← IO.ofExcept (trace.getObjVal? "events")).getArr?)
  let some anchor := events[eventId]? | throw (IO.userError "missing event anchor")
  unless t.goalsBefore.length == 1 && t.goalsAfter.isEmpty do
    throw (IO.userError "single closing goal required")
  let baseline ← JevOpsProofState.replayClosed ctx t t.stx auditLocalProof
  let stx ← IO.ofExcept (Parser.runParserCategory ctx.env `tactic candidate)
  let (proposed, extracted) ← JevOpsProofState.replayClosedResult ctx t stx auditLocalProof true
  let mkReplay := fun text outcome => Json.mkObj [
    ("schema", toJson "jevops-closed-tactic-replay/v1"),
    ("environment", toJson environment), ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash), ("event", anchor), ("candidate", toJson text),
    ("baseline", baseline), ("proposed", outcome), ("proof_admitted", toJson false),
    ("snapshot_decoded", toJson false), ("whole_source_checked", toJson false)]
  let roundtrip ← match extracted with
    | none => pure Json.null
    | some text => do
      let termStx ← IO.ofExcept (Parser.runParserCategory ctx.env `tactic text)
      pure (mkReplay text (← JevOpsProofState.replayClosed ctx t termStx auditLocalProof))
  return Json.mkObj [("schema", toJson "jevops-local-application/v1"),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("search", mkReplay candidate proposed), ("extracted_candidate", toJson extracted),
    ("roundtrip", roundtrip)]

/- Proposal search only: every successful path is subsequently executed again by
   discoverApplication, kernel/audit checked, printed, and independently replayed.
   The IO counter is deliberately outside saved elaborator state: backtracking
   cannot refund work. Sibling goals are part of the same AND search, so failure
   of a later sibling backtracks earlier choices (including metavariables). -/
structure LocalSearchStats where
  attempts : Nat := 0
  depthCutoffs : Nat := 0
  exhausted : Bool := false
  trace : Array Json := #[]
  retrievals : Array Json := #[]
  retrievalExhausted : Bool := false
  dischargeChecks : Array Json := #[]
  dischargeChecksExhausted : Bool := false
  cycleChecks : Array Json := #[]
  cycleChecksExhausted : Bool := false

/- Only exact, meta-free propositions are eligible. In particular, repeating a
   data goal such as Nat under Nat.succ is NOT a proof-search cycle. Keys stay
   native and branch-local; neither pretty text nor a digest establishes equality.
   Raw metas (even assigned ones) deliberately abstain in this first guard. -/
structure LocalCycleKey where
  type : Expr
  declarations : Array LocalDecl
  instances : LocalInstances
  slots : Nat
  auxiliaryNames : Array (Option Name)

def sameCycleDecl (a b : LocalDecl) : Bool :=
  match a, b with
  | .cdecl i f n t bi k, .cdecl j g m u bj l =>
    i == j && f == g && n == m && t.equal u && bi == bj && k == l
  | .ldecl i f n t v nd k, .ldecl j g m u w ne l =>
    i == j && f == g && n == m && t.equal u && v.equal w && nd == ne && k == l
  | _, _ => false

def sameCycleKey (a b : LocalCycleKey) : Bool :=
  a.type.equal b.type && a.slots == b.slots && a.auxiliaryNames == b.auxiliaryNames &&
    a.declarations.size == b.declarations.size &&
    (a.declarations.zip b.declarations).all (fun (x, y) => sameCycleDecl x y) &&
    a.instances.size == b.instances.size &&
    (a.instances.zip b.instances).all (fun (x, y) =>
      x.className == y.className && x.fvar.equal y.fvar)

abbrev LocalCycleHistory := Std.HashMap MVarId (List (Nat × LocalCycleKey))

def inspectCycleGoal (goal : MVarId) :
    Tactic.TacticM (Option LocalCycleKey × String × Nat × Nat) := do
  let saved ← Tactic.saveState
  let mut result := (none, "error", 0, 0)
  try
    result ← goal.withContext do
      let lctx ← getLCtx
      let instances ← Meta.getLocalInstances
      -- Persistent-array size is O(1); LocalContext.size itself scans entries.
      let slots := lctx.decls.size
      if slots > 64 || instances.size > 64 then
        return (none, "context_limit", 0, min slots 65)
      let declarations := lctx.foldl (fun ds d => ds.push d) (#[] : Array LocalDecl)
      let type ← goal.getType
      let mut pending := [type] ++ instances.toList.map (·.fvar)
      for d in declarations do
        pending := d.type :: pending
        if let some value := d.value? (allowNondep := true) then pending := value :: pending
      let count := declarations.size
      let mut nodes := 0
      while !pending.isEmpty do
        if nodes == 2048 then return (none, "node_limit", nodes, count)
        let e := pending.head!
        pending := pending.tail!
        nodes := nodes + 1
        if e.hasMVar then return (none, "metavariables", nodes, count)
        match e with
        | .app f a => pending := f :: a :: pending
        | .forallE _ t b _ | .lam _ t b _ => pending := t :: b :: pending
        | .letE _ t v b _ => pending := t :: v :: b :: pending
        | .mdata _ b | .proj _ _ b => pending := b :: pending
        | _ => pure ()
      -- No unification or normalization of the key. isProp is observational and
      -- all its state is restored below, including on exceptions.
      if !(← Meta.isProp type) then return (none, "not_prop", nodes, count)
      let auxiliaryNames := declarations.map (fun d => lctx.auxDeclToFullName.get? d.fvarId)
      return (some { type, declarations, instances, slots, auxiliaryNames }, "eligible", nodes, count)
  catch _ => pure ()
  saved.restore (restoreInfo := true)
  return result

/- Bounded substitution only: no unification, reduction, delayed-assignment
   synthesis, or fresh metavariables. Charge both expression and universe visits
   before inspecting them. Repeated references are charged again; expansion is
   bounded even for shared DAGs or malformed cyclic assignments. -/
structure CycleResolveStats where
  exprNodes : Nat := 0
  levelNodes : Nat := 0
  termDereferences : Nat := 0
  levelDereferences : Nat := 0
  kind : String := "eligible"
  location : Option String := none

def cycleVisit (stats : IO.Ref CycleResolveStats) (depth : Nat) (level : Bool) :
    Tactic.TacticM Bool := do
  let s ← stats.get
  if s.exprNodes + s.levelNodes >= 2048 then
    stats.modify fun s => { s with kind := "node_limit" }
    return false
  if depth >= 128 then
    stats.modify fun s => { s with kind := "depth_limit" }
    return false
  stats.modify fun s => if level then { s with levelNodes := s.levelNodes + 1 }
    else { s with exprNodes := s.exprNodes + 1 }
  return true

partial def resolveCycleLevel (u : Level) (depth : Nat) (stats : IO.Ref CycleResolveStats) :
    OptionT Tactic.TacticM Level := do
  unless ← cycleVisit stats depth true do failure
  match u with
  | .mvar id =>
    let some value ← getLevelMVarAssignment? id | do
      stats.modify fun s => { s with kind := "unresolved_level" }
      failure
    stats.modify fun s => { s with levelDereferences := s.levelDereferences + 1 }
    resolveCycleLevel value (depth + 1) stats
  | .succ v => return .succ (← resolveCycleLevel v (depth + 1) stats)
  | .max v w => return .max (← resolveCycleLevel v (depth + 1) stats) (← resolveCycleLevel w (depth + 1) stats)
  | .imax v w => return .imax (← resolveCycleLevel v (depth + 1) stats) (← resolveCycleLevel w (depth + 1) stats)
  | _ => return u

partial def resolveCycleExpr (e : Expr) (depth : Nat) (stats : IO.Ref CycleResolveStats) :
    OptionT Tactic.TacticM Expr := do
  unless ← cycleVisit stats depth false do failure
  match e with
  | .mvar id =>
    let some value ← getExprMVarAssignment? id | do
      let delayed ← getDelayedMVarAssignment? id
      stats.modify fun s => { s with kind := if delayed.isSome then "delayed_assignment" else "unresolved_term" }
      failure
    stats.modify fun s => { s with termDereferences := s.termDereferences + 1 }
    resolveCycleExpr value (depth + 1) stats
  | .sort u => return .sort (← resolveCycleLevel u (depth + 1) stats)
  | .const name levels => return .const name (← levels.mapM (fun u => resolveCycleLevel u (depth + 1) stats))
  | .app f a => return .app (← resolveCycleExpr f (depth + 1) stats) (← resolveCycleExpr a (depth + 1) stats)
  | .lam n t b bi => return .lam n (← resolveCycleExpr t (depth + 1) stats) (← resolveCycleExpr b (depth + 1) stats) bi
  | .forallE n t b bi => return .forallE n (← resolveCycleExpr t (depth + 1) stats) (← resolveCycleExpr b (depth + 1) stats) bi
  | .letE n t v b nd =>
    let t ← resolveCycleExpr t (depth + 1) stats
    let v ← resolveCycleExpr v (depth + 1) stats
    let b ← resolveCycleExpr b (depth + 1) stats
    return .letE n t v b nd
  | .mdata data b => return .mdata data (← resolveCycleExpr b (depth + 1) stats)
  | .proj n i b => return .proj n i (← resolveCycleExpr b (depth + 1) stats)
  | _ => return e

def inspectAssignedCycleGoal (goal : MVarId) :
    Tactic.TacticM (Option LocalCycleKey × CycleResolveStats × Nat) := do
  let saved ← Tactic.saveState
  let stats ← IO.mkRef ({} : CycleResolveStats)
  let mut key := none
  let mut count := 0
  try
    (key, count) ← goal.withContext do
      let lctx ← getLCtx
      let instances ← Meta.getLocalInstances
      let slots := lctx.decls.size
      if slots > 64 || instances.size > 64 then
        stats.modify fun s => { s with kind := "context_limit" }
        return (none, min slots 65)
      let declarations := lctx.foldl (fun ds d => ds.push d) (#[] : Array LocalDecl)
      let resolve := fun location e => do
        stats.modify fun s => { s with location := some location }
        resolveCycleExpr e 0 stats
      let result ← (do
        let type ← resolve "goal" (← goal.getType)
        let declarations ← declarations.mapM fun d => do
          let t ← resolve "local_type" d.type
          match d with
          | .cdecl i f n _ bi k => pure (.cdecl i f n t bi k)
          | .ldecl i f n _ v nd k => return .ldecl i f n t (← resolve "local_value" v) nd k
        let instances ← instances.mapM fun i => do
          pure { i with fvar := (← resolve "instance" i.fvar) }
        -- Defense in depth: no partially substituted key can become eligible.
        if type.hasMVar || declarations.any (fun d => d.type.hasMVar ||
            (d.value? (allowNondep := true)).any Expr.hasMVar) || instances.any (·.fvar.hasMVar) then
          stats.modify fun s => { s with kind := "error" }
          failure
        stats.modify fun s => { s with location := some "prop_check" }
        unless ← Meta.isProp type do
          stats.modify fun s => { s with kind := "not_prop", location := none }
          failure
        stats.modify fun s => { s with location := none }
        let auxiliaryNames := declarations.map (fun d => lctx.auxDeclToFullName.get? d.fvarId)
        pure ({ type, declarations, instances, slots, auxiliaryNames } : LocalCycleKey)
        : OptionT Tactic.TacticM LocalCycleKey).run
      return (result, declarations.size)
  catch _ => stats.modify fun s => { s with kind := "error" }
  saved.restore (restoreInfo := true)
  return (key, ← stats.get, count)

structure LocalRetrieval where
  pool : Json
  order : Array String
  byHead : Std.HashMap String (Array String)
  maxQueries : Nat
  topK : Nat

structure LocalSearchStep where
  action : String
  goalIndex : Nat := 0

def LocalSearchStep.json (s : LocalSearchStep) : Json :=
  Json.mkObj [("action", toJson s.action), ("goal_index", toJson s.goalIndex)]

def LocalSearchStep.script (s : LocalSearchStep) : String :=
  -- `focus` can leave assigned sibling metavariables in the goal list. Prune
  -- them before rotation, exactly as the search does before indexing goals.
  (if s.goalIndex == 0 then "" else
    "(all_goals skip); (rotate_left " ++ toString s.goalIndex ++ "); ") ++
  "(focus (" ++ s.action ++ "))"

/- Inspect only a bounded current-goal spine, including assigned head metavars.
   No normalization, local proof-value mining or library-wide environment scan. -/
def localGoalHead (expr : Expr) : MetaM (Option String) := do
  let mut e := expr
  for _ in [:256] do
    match e with
    | .app f _ => e := f
    | .mdata _ body => e := body
    | .mvar id =>
      if let some value ← getExprMVarAssignment? id then e := value else return none
    | .const n _ =>
      return if n.toString.utf8ByteSize <= 1024 then some n.toString else none
    | _ => return none
  return none

/- Observe a goal's universe without committing any inference/unification
   performed by type inference or reduction. `Sort u` with unresolved u is not
   evidence of either Prop or data. Raw heads remain diagnostic hints only. -/
def inspectDischargeGoal (goal : MVarId) : Tactic.TacticM (String × Option String) := do
  let saved ← Tactic.saveState
  let mut kind := "error"
  let mut head := none
  try
    let result ← goal.withContext do
      let type ← goal.getType
      let head ← localGoalHead type
      let sort ← Meta.whnfD (← Meta.inferType type)
      let kind ← match sort with
        | .sort u => do
          let u ← instantiateLevelMVars u
          pure (if u.isAlwaysZero then "prop" else if u.isNeverZero then "data" else "unknown")
        | _ => pure "unknown"
      pure (kind, head)
    kind := result.1
    head := result.2
  catch _ => pure ()
  saved.restore (restoreInfo := true)
  return (kind, head)

def subgoalNames (retrieval : LocalRetrieval) (head : Option String) : Array String := Id.run do
  let matched := (head.bind (retrieval.byHead[·]?)).getD #[]
  let fallback := retrieval.order.filter (!matched.contains ·)
  let reserve := if !fallback.isEmpty && retrieval.topK > 1 then 1 else 0
  let selected := matched.extract 0 (retrieval.topK - reserve)
  return selected ++ fallback.extract 0 (retrieval.topK - selected.size)

def readLocalRetrieval (request : Json) (initial : Array String) : IO (Option LocalRetrieval) := do
  let .ok pool := request.getObjVal? "subgoal_pool" | return none
  let rows ← IO.ofExcept pool.getArr?
  let maxQueries ← IO.ofExcept (request.getObjValAs? Nat "max_retrievals")
  let topK ← IO.ofExcept (request.getObjValAs? Nat "retrieval_top_k")
  unless rows.size > 0 && rows.size <= 64 && maxQueries > 0 && maxQueries <= 256 &&
      topK > 0 && topK <= 8 do throw (IO.userError "subgoal retrieval bounds")
  let mut names : Array String := #[]
  let mut heads : Std.HashMap String (Option String) := {}
  for row in rows do
    let name ← IO.ofExcept (row.getObjValAs? String "name")
    unless !name.isEmpty && name.utf8ByteSize <= 256 && !names.contains name &&
        (name.splitOn ".").all (fun p => !p.isEmpty &&
          p.toList.all (fun c => c.isAlphanum || c == '_' || c == '\'')) do
      throw (IO.userError "invalid retrieval premise")
    let raw ← IO.ofExcept (row.getObjVal? "head")
    let head ← if raw == Json.null then pure none else some <$> IO.ofExcept raw.getStr?
    if let some h := head then
      unless !h.isEmpty && h.utf8ByteSize <= 1024 do throw (IO.userError "head byte budget")
    names := names.push name
    heads := heads.insert name head
  unless initial.all names.contains && names == names.qsort (· < ·) do
    throw (IO.userError "noncanonical or incomplete retrieval pool")
  let order := initial ++ names.filter (!initial.contains ·)
  let mut byHead : Std.HashMap String (Array String) := {}
  for name in order do
    if let some (some head) := heads[name]? then
      byHead := byHead.insert head ((byHead[head]?).getD #[] |>.push name)
  return some { pool, order, byHead, maxQueries, topK }

partial def localSearch (actions : Array String) (steps depthLimit : Nat)
    (stats : IO.Ref LocalSearchStats) (frontier : List (MVarId × Nat))
    (retrieval? : Option LocalRetrieval := none) (dischargeWindow : Nat := 0)
    (dischargeFilter : String := "none") (maxChecks : Nat := 256)
    (cycleGuard : String := "none") (maxCycleChecks : Nat := 256)
    (cycleKey : String := "raw-v1")
    (history : LocalCycleHistory := {}) :
    Tactic.TacticM (Option (List LocalSearchStep)) := do
  if cycleGuard != "none" && (← stats.get).cycleChecksExhausted then return none
  let frontier ← if dischargeWindow > 0 then
    frontier.filterM (fun p => return !(← p.1.isAssigned)) else pure frontier
  -- Try bounded local-hypothesis discharge before generative applications.
  -- Each speculative attempt is charged; all elaborator state is restored if
  -- any downstream sibling fails. A unifying assumption is NOT an irreversible
  -- commitment to its metavariable assignments.
  if dischargeWindow > 0 then
    for index in [:min dischargeWindow frontier.length] do
      if cycleGuard != "none" && (← stats.get).cycleChecksExhausted then return none
      let (goal, depth) := frontier[index]!
      if depth >= depthLimit then continue
      if (← stats.get).attempts >= steps then
        stats.modify fun s => { s with exhausted := true }
        return none
      let mut checkId : Option Nat := none
      if dischargeFilter != "none" then
        let s ← stats.get
        if s.dischargeChecks.size >= maxChecks then
          stats.modify fun s => { s with dischargeChecksExhausted := true }
          return none
        -- Reserve the independent observation unit BEFORE inspecting Lean state.
        let id := s.dischargeChecks.size
        stats.modify fun s => { s with dischargeChecks := s.dischargeChecks.push Json.null }
        let (kind, head) ← inspectDischargeGoal goal
        let attempt := dischargeFilter == "observe-all-v1" || kind == "prop"
        let check := Json.mkObj [("id", toJson id), ("at_step", toJson s.attempts),
          ("depth", toJson depth), ("goal_index", toJson index), ("head", toJson head),
          ("kind", toJson kind), ("decision", toJson (if attempt then "attempt" else "skip"))]
        stats.modify fun s => { s with dischargeChecks := s.dischargeChecks.set! id check }
        if !attempt then continue
        checkId := some id
      stats.modify fun s => { s with attempts := s.attempts + 1 }
      let saved ← Tactic.saveState
      let mut closed := false
      try
        Tactic.setGoals [goal]
        Tactic.evalTactic (← ofExcept (Parser.runParserCategory (← getEnv) `tactic "assumption"))
        Term.synthesizeSyntheticMVarsNoPostponing
        closed := (← Tactic.getUnsolvedGoals).isEmpty && !(← Core.getMessageLog).hasErrors
      catch _ => pure ()
      let row := [
        ("action", toJson "assumption"), ("depth", toJson depth), ("applied", toJson closed),
        ("retrieval_id", Json.null), ("phase", toJson "discharge"), ("goal_index", toJson index)]
      stats.modify fun s => { s with trace := s.trace.push (Json.mkObj
        (if dischargeFilter == "none" then row else row ++ [("check_id", toJson checkId)])) }
      if closed then
        let remaining := (frontier.rotateLeft index).drop 1
        if let some path ← localSearch actions steps depthLimit stats remaining retrieval? dischargeWindow dischargeFilter maxChecks cycleGuard maxCycleChecks cycleKey history then
          return some ({ action := "assumption", goalIndex := index } :: path)
      saved.restore (restoreInfo := true)
  match frontier with
  | [] => return some []
  | (goal, depth) :: rest =>
    if ← goal.isAssigned then return ← localSearch actions steps depthLimit stats rest retrieval? dischargeWindow dischargeFilter maxChecks cycleGuard maxCycleChecks cycleKey history
    if depth >= depthLimit then
      stats.modify fun s => { s with depthCutoffs := s.depthCutoffs + 1 }
      return none
    let mut ancestors : List (Nat × LocalCycleKey) := []
    if cycleGuard != "none" then
      let s ← stats.get
      if s.cycleChecks.size >= maxCycleChecks then
        stats.modify fun s => { s with cycleChecksExhausted := true }
        return none
      let id := s.cycleChecks.size
      stats.modify fun s => { s with cycleChecks := s.cycleChecks.push Json.null }
      let (key?, kind, nodes, declarations, details) ← if cycleKey == "assigned-v1" then do
          let (key, s, count) ← inspectAssignedCycleGoal goal
          pure (key, s.kind, s.exprNodes + s.levelNodes, count, [
            ("expr_nodes", toJson s.exprNodes), ("level_nodes", toJson s.levelNodes),
            ("term_dereferences", toJson s.termDereferences),
            ("level_dereferences", toJson s.levelDereferences), ("blocked_in", toJson s.location)])
        else do
          let (key, kind, nodes, count) ← inspectCycleGoal goal
          pure (key, kind, nodes, count, [])
      let mut repeatOf : Option Nat := none
      if let some key := key? then
        ancestors := (history[goal]?).getD []
        repeatOf := (ancestors.find? (fun (_, old) => sameCycleKey key old)).map (·.1)
        ancestors := (id, key) :: ancestors
      let prune := repeatOf.isSome && cycleGuard == "prune-v1"
      stats.modify fun s => { s with cycleChecks := s.cycleChecks.set! id (Json.mkObj ([
        ("id", toJson id), ("at_step", toJson s.attempts), ("depth", toJson depth),
        ("kind", toJson kind), ("nodes", toJson nodes), ("declarations", toJson declarations),
        ("repeat_of", toJson repeatOf), ("decision", toJson (if prune then "prune" else "continue"))] ++ details)) }
      if prune then return none
    let mut choices := actions
    let mut retrievalId : Option Nat := none
    if let some retrieval := retrieval? then
      if (← stats.get).attempts >= steps then
        stats.modify fun s => { s with exhausted := true }
        return none
      if depth > 0 then
        let used := (← stats.get).retrievals.size
        if used >= retrieval.maxQueries then
          stats.modify fun s => { s with retrievalExhausted := true }
          return none
        let head ← localGoalHead (← goal.getType)
        let selected := subgoalNames retrieval head
        retrievalId := some used
        stats.modify fun s => { s with retrievals := s.retrievals.push (Json.mkObj [
          ("id", toJson used), ("depth", toJson depth), ("head", toJson head),
          ("selected", toJson selected)]) }
        choices := #["assumption"] ++ selected.map ("apply _root_." ++ ·) ++ #["intro", "constructor"]
    for action in choices do
      if cycleGuard != "none" && (← stats.get).cycleChecksExhausted then return none
      if dischargeWindow > 0 && action == "assumption" then continue
      if (← stats.get).attempts >= steps then
        stats.modify fun s => { s with exhausted := true }
        return none
      stats.modify fun s => { s with attempts := s.attempts + 1 }
      let saved ← Tactic.saveState
      let mut children : Option (List MVarId) := none
      try
        Tactic.setGoals [goal]
        let actionStx ← ofExcept (Parser.runParserCategory (← getEnv) `tactic action)
        Tactic.evalTactic actionStx
        Term.synthesizeSyntheticMVarsNoPostponing
        unless (← Core.getMessageLog).hasErrors do
          children := some (← Tactic.getUnsolvedGoals)
      catch _ => pure ()
      let row := [("action", toJson action), ("depth", toJson depth),
        ("applied", toJson children.isSome)]
      let row := if dischargeWindow > 0 then row ++
        [("phase", toJson "expand"), ("goal_index", toJson (0 : Nat))] else row
      let row := if dischargeFilter == "none" then row else row ++ [("check_id", Json.null)]
      stats.modify fun s => { s with trace := s.trace.push (Json.mkObj
        (if retrieval?.isSome then row ++ [("retrieval_id", toJson retrievalId)] else row)) }
      if let some subgoals := children then
        -- Only children inherit this goal's ancestors. Independent siblings
        -- keep their own histories, also when discharge rotates the frontier.
        let nextHistory := if cycleGuard == "none" then history else
          subgoals.foldl (fun h g => h.insert g ancestors) history
        if let some path ← localSearch actions steps depthLimit stats
            (subgoals.map (fun g => (g, depth + 1)) ++ rest) retrieval? dischargeWindow dischargeFilter maxChecks cycleGuard maxCycleChecks cycleKey nextHistory then
          return some ({ action } :: path)
      saved.restore (restoreInfo := true)
    return none

def discoverSearch (state : Command.State) (input environment : String)
    (limit eventsLimit eventId steps depth : Nat) (premises : Array String)
    (retrieval? : Option LocalRetrieval := none) (dischargeWindow : Nat := 0)
    (dischargeFilter : String := "none") (maxChecks : Nat := 256)
    (cycleGuard : String := "none") (maxCycleChecks : Nat := 256)
    (cycleKey : String := "raw-v1") : IO Json := do
  unless steps > 0 && steps <= 256 && depth > 0 && depth <= 8 &&
      premises.size > 0 && premises.size <= 8 do
    throw (IO.userError "search bounds")
  unless dischargeWindow <= 16 && (dischargeWindow == 0 || retrieval?.isSome) do
    throw (IO.userError "discharge window bounds")
  unless dischargeFilter == "none" ||
      (dischargeWindow > 0 && maxChecks > 0 && maxChecks <= 256 &&
        (dischargeFilter == "observe-all-v1" || dischargeFilter == "propositions-v1")) do
    throw (IO.userError "discharge filter bounds")
  unless cycleGuard == "none" || ((cycleGuard == "observe-v1" || cycleGuard == "prune-v1") &&
      maxCycleChecks > 0 && maxCycleChecks <= 256) do
    throw (IO.userError "cycle guard bounds")
  unless cycleKey == "raw-v1" || (cycleKey == "assigned-v1" && cycleGuard != "none") do
    throw (IO.userError "cycle key mode")
  -- Python checks plain declaration names as well; enforce this at the driver
  -- boundary too. No user tactic fragments or hidden all-library search.
  for name in premises do
    unless name.utf8ByteSize <= 256 && !name.isEmpty &&
        (name.splitOn ".").all (fun p => !p.isEmpty &&
          p.toList.all (fun c => c.isAlphanum || c == '_' || c == '\'')) do
      throw (IO.userError "plain premise name required")
  let (_, nodes) ← JevOpsProofState.traceStateData state input environment limit eventsLimit true
  let some (ctx, t) := nodes[eventId]? | throw (IO.userError "event outside trace")
  unless t.goalsBefore.length == 1 && t.goalsAfter.isEmpty do
    throw (IO.userError "single closing goal required")
  let stats ← IO.mkRef ({} : LocalSearchStats)
  let actions := #["assumption"] ++ premises.map ("apply _root_." ++ ·) ++ #["intro", "constructor"]
  let path ← ctx.runMetaM {} do
    setMCtx t.mctxBefore
    let found ← IO.mkRef (none : Option (List LocalSearchStep))
    let _ ← Term.TermElabM.run' do
      Tactic.run t.goalsBefore.head! do
        withReader (fun c => { c with recover := false }) do
          found.set (← localSearch actions steps depth stats (t.goalsBefore.map (·, 0)) retrieval? dischargeWindow dischargeFilter maxChecks cycleGuard maxCycleChecks cycleKey)
    found.get
  let script := path.map fun xs => "solve | " ++ String.intercalate "; "
    (xs.map LocalSearchStep.script)
  -- A bounded successful path can still exceed the text budget: abstain, don't
  -- truncate a proof. Search success alone is never authoritative evidence.
  let script := script.filter (fun s => s.utf8ByteSize <= 4096)
  let application ← match script with
    | none => pure Json.null
    | some script => discoverApplication state input environment limit eventsLimit eventId script
  let stats ← stats.get
  let fields := [
    ("schema", toJson (if cycleKey == "assigned-v1" then "jevops-local-search/v6" else
      if cycleGuard != "none" then "jevops-local-search/v5" else
      if dischargeFilter != "none" then "jevops-local-search/v4" else
      if dischargeWindow > 0 then "jevops-local-search/v3" else
      if retrieval?.isSome then "jevops-local-search/v2" else "jevops-local-search/v1")),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("premises", toJson premises), ("max_steps", toJson steps), ("max_depth", toJson depth),
    ("attempted_steps", toJson stats.attempts), ("depth_cutoffs", toJson stats.depthCutoffs),
    ("step_exhausted", toJson stats.exhausted), ("trace", .arr stats.trace),
    ("path", if dischargeWindow > 0 then (path.map (fun xs => toJson (xs.map LocalSearchStep.json))).getD Json.null
      else toJson (path.map (fun xs => xs.map (·.action)))),
    ("script", toJson script), ("application", application)]
  let fields := if dischargeWindow > 0 then fields ++ [("discharge_window", toJson dischargeWindow)] else fields
  let fields := if cycleKey == "raw-v1" then fields else fields ++ [("cycle_key", toJson cycleKey)]
  let fields := if cycleGuard == "none" then fields else fields ++ [
    ("cycle_guard", toJson cycleGuard), ("max_cycle_checks", toJson maxCycleChecks),
    ("cycle_checks", .arr stats.cycleChecks), ("cycle_checks_exhausted", toJson stats.cycleChecksExhausted)]
  let fields := if dischargeFilter == "none" then fields else fields ++ [
    ("discharge_filter", toJson dischargeFilter), ("max_discharge_checks", toJson maxChecks),
    ("discharge_checks", .arr stats.dischargeChecks),
    ("discharge_checks_exhausted", toJson stats.dischargeChecksExhausted)]
  return Json.mkObj (fields ++ match retrieval? with
    | none => []
    | some r => [("subgoal_pool", r.pool), ("max_retrievals", toJson r.maxQueries),
        ("retrieval_top_k", toJson r.topK), ("retrievals", .arr stats.retrievals),
        ("retrieval_exhausted", toJson stats.retrievalExhausted)])

/- Diagnostic-only built-in profiler: source and proof environment are unchanged.
   Inclusive intervals nest; consumers must NOT sum parent and child costs.
   No source offsets are inferred from pretty-printed tactic hints. -/
structure TacticProfile where
  rows : Array Json := #[]
  visited : Nat := 0

def profileCounter (x : Float) : IO Nat := do
  if x.isNaN || x.isInf || x < 0 || x >= 9007199254740992 then
    throw (IO.userError "invalid profiler counter")
  let n := x.toUInt64.toNat
  unless n.toFloat == x do throw (IO.userError "nonintegral profiler counter")
  return n

partial def visitProfile (msg : MessageData) (parent : Option Nat)
    (nodeLimit eventLimit : Nat) (depth : Nat := 0)
    (ctx : Option MessageDataContext := none) (nctx : Option NamingContext := none)
    : StateT TacticProfile IO Unit := do
  if depth >= 256 || (← get).visited >= nodeLimit then
    throw (IO.userError "profile traversal budget; no partial inventory")
  modify fun s => { s with visited := s.visited + 1 }
  let visit := fun m p => visitProfile m p nodeLimit eventLimit (depth + 1) ctx nctx
  match msg with
  | .withContext c m => visitProfile m parent nodeLimit eventLimit (depth + 1) (some c) nctx
  | .withNamingContext c m => visitProfile m parent nodeLimit eventLimit (depth + 1) ctx (some c)
  | .nest _ m | .group m | .tagged _ m | .ofWidget _ m => visit m parent
  | .compose a b => visit a parent *> visit b parent
  | .trace data hint children =>
    let mut owner := parent
    if data.cls == `Elab.step && data.tag.startsWith "Lean.Parser.Tactic." then
      if (← get).rows.size >= eventLimit then
        throw (IO.userError "profile event budget; no partial inventory")
      let start ← profileCounter data.startTime
      let stop ← profileCounter data.stopTime
      if stop < start then throw (IO.userError "reversed profiler interval")
      let id := (← get).rows.size
      let hint : MessageData := match ctx with | some c => .withContext c hint | none => hint
      let hint : MessageData := match nctx with | some c => .withNamingContext c hint | none => hint
      let text ← hint.toString
      let row := Json.mkObj [("id", toJson id), ("parent", toJson parent),
        ("syntax_kind", toJson data.tag), ("hint", toJson (text.take 512)),
        ("hint_truncated", toJson (decide (text.length > 512))),
        ("start_raw", toJson start), ("stop_raw", toJson stop),
        ("inclusive_raw", toJson (stop - start))]
      modify fun s => { s with rows := s.rows.push row }
      owner := some id
    for child in children do visit child owner
  | _ => pure ()

def tacticProfileReport (state : Command.State) (environment : String)
    (raw threshold nodeLimit eventLimit : Nat) : IO Json := do
  let (_, result) ← (do
    for m in state.messages.reportedPlusUnreported.toArray do
      visitProfile m.data none nodeLimit eventLimit).run ({} : TacticProfile)
  return Json.mkObj [("schema", toJson "jevops-tactic-heartbeat-profile/v1"),
    ("environment", toJson environment), ("lean_version", toJson Lean.versionString),
    ("lean_githash", toJson Lean.githash), ("instrumented", toJson true),
    ("measurement", toJson "lean-trace-profiler-raw-heartbeats/v1"),
    ("projection", toJson "builtin-tactic-traces/v1"),
    ("threshold_raw", toJson threshold), ("command_raw", toJson raw),
    ("nodes_visited", toJson result.visited), ("events", .arr result.rows),
    ("proof_admitted", toJson false), ("score_eligible", toJson false)]

unsafe def main : IO UInt32 := do
  let stdin ← IO.getStdin
  let mut bytes := ByteArray.empty
  repeat
    let chunk ← stdin.read 65536
    if chunk.isEmpty then break
    bytes := bytes ++ chunk
    if bytes.size > 33554432 then throw (IO.userError "request byte budget")
  let some text := String.fromUTF8? bytes | throw (IO.userError "UTF-8 required")
  let request ← IO.ofExcept (Json.parse text)
  let field := fun key => IO.ofExcept (request.getObjValAs? String key)
  let nat := fun key => IO.ofExcept (request.getObjValAs? Nat key)
  let mode ← field "mode"
  let projection ← field "projection"
  unless projection == "closing-source-spans/v1" do throw (IO.userError "unsupported project projection")
  let environment ← field "environment"
  let limit ← nat "node_budget"
  let events ← nat "event_budget"
  JevOpsProofState.settings environment limit events
  let heartbeats ← nat "max_heartbeats"
  if heartbeats == 0 || heartbeats > 10000000 then throw (IO.userError "heartbeat budget")
  let before ← field "prefix"
  let source ← field "source"
  let target := (← field "target").toName
  if before.utf8ByteSize > 8388608 || source.utf8ByteSize > 262144 then
    throw (IO.userError "source byte budget")
  initSearchPath (← findSysroot)
  enableInitializersExecution
  let initial ← JevOpsArena.prefixState before heartbeats
  if initial.messages.hasErrors then throw (IO.userError "prefix errors")
  if initial.env.contains target then throw (IO.userError "target already available")
  -- Discard any prefix diagnostics/trees; preserve its actual scopes/environment.
  let initial := { initial with messages := {}, infoState := { enabled := true } }
  let threshold ← if mode == "profile" then nat "threshold_raw" else pure 0
  if threshold > 1000000 then throw (IO.userError "profiler threshold budget")
  let initial := if mode == "profile" then
      { initial with scopes := initial.scopes.map fun s => { s with opts :=
        (s.opts.setBool `trace.profiler true |>.setBool `trace.profiler.useHeartbeats true
          |>.setNat `trace.profiler.threshold threshold) } }
    else initial
  let (state, raw) ← JevOpsArena.branch initial source target heartbeats
  if state.messages.hasErrors then throw (IO.userError "reference elaboration errors")
  unless state.env.contains target do throw (IO.userError "reference target missing")
  let report ← if mode == "profile" then
      tacticProfileReport state environment raw threshold limit events
    else if mode == "capture" then
      JevOpsProofState.traceState state source environment limit events true
    else if mode == "replay" then
      JevOpsProofState.replayState state source environment limit events
        (← nat "event_id") (← field "candidate") true auditLocalProof
    else if mode == "application" then
      discoverApplication state source environment limit events
        (← nat "event_id") (← field "candidate")
    else if mode == "search" then
      let premises ← IO.ofExcept (request.getObjValAs? (Array String) "premises")
      let dischargeWindow ← match request.getObjVal? "discharge_window" with
        | .error _ => pure 0
        | .ok value => IO.ofExcept value.getNat?
      let dischargeFilter ← match request.getObjVal? "discharge_filter" with
        | .error _ => pure "none"
        | .ok value => IO.ofExcept value.getStr?
      let maxChecks ← if dischargeFilter == "none" then pure 256 else nat "max_discharge_checks"
      let cycleGuard ← match request.getObjVal? "cycle_guard" with
        | .error _ => pure "none"
        | .ok value => IO.ofExcept value.getStr?
      let maxCycleChecks ← if cycleGuard == "none" then pure 256 else nat "max_cycle_checks"
      let cycleKey ← match request.getObjVal? "cycle_key" with
        | .error _ => pure "raw-v1"
        | .ok value => IO.ofExcept value.getStr?
      discoverSearch state source environment limit events (← nat "event_id")
        (← nat "max_steps") (← nat "max_depth") premises (← readLocalRetrieval request premises)
        dischargeWindow dischargeFilter maxChecks cycleGuard maxCycleChecks cycleKey
    else throw (IO.userError "unsupported local mode")
  IO.println ("JEVOPS_ARENA_LOCAL:" ++ (Json.mkObj [
    ("schema", toJson "jevops-arena-local-stage/v1"),
    ("request_sha256", toJson (← field "request_sha256")), ("target", toJson target.toString),
    ("lean_version", toJson Lean.versionString), ("lean_githash", toJson Lean.githash),
    ("report", report)]).compress)
  return 0
