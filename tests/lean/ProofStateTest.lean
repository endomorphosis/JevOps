import ProofState

open Lean JevOpsProofState

/- Synthetic native contexts test representation/dependencies, not proof truth. -/
def stateFixture : Except String Json := do
  let u : LMVarId := ⟨`u⟩
  let v : LMVarId := ⟨`v⟩
  let g : MVarId := ⟨`g⟩
  let h : MVarId := ⟨`h⟩
  let d : MetavarDecl := {
    lctx := {}, type := .sort (.mvar u), depth := 0
    localInstances := #[], kind := .natural, index := 0 }
  let mctx : MetavarContext := {}
  let mctx := { mctx with
    decls := (mctx.decls.insert g d).insert h { d with index := 1 }
    lAssignment := mctx.lAssignment.insert u (.mvar v) }
  let mctx := (mctx.addLevelMVarDecl u).addLevelMVarDecl v
  let wire ← capture mctx [g, h] 4096
  let delayed := { mctx with dAssignment := mctx.dAssignment.insert g { fvars := #[], mvarIdPending := h } }
  match capture delayed [g] 4096 with
  | .ok _ => throw "delayed assignment was silently lost"
  | .error e => unless e == "delayed metavariable assignment unsupported" do throw e
  match capture mctx [⟨`missing⟩] 4096 with
  | .ok _ => throw "missing metavariable declaration was accepted"
  | .error _ => pure ()
  let badDecl := { d with type := .mdata { entries := [(`key, .ofSyntax .missing)] } (.sort .zero) }
  let bad := { mctx with decls := mctx.decls.insert g badDecl }
  match capture bad [g] 4096 with
  | .ok _ => throw "syntax metadata was silently lost"
  | .error _ => pure ()
  let unbound := { mctx with decls := mctx.decls.insert g { d with type := .fvar ⟨`cleared⟩ } }
  match capture unbound [g] 4096 with
  | .ok _ => throw "undeclared free variable was accepted"
  | .error e => unless e == "unbound variable in local context" do throw e
  let unboundValue := { mctx with eAssignment := mctx.eAssignment.insert g (.fvar ⟨`cleared⟩) }
  match capture unboundValue [g] 4096 with
  | .ok _ => throw "unbound assignment was accepted"
  | .error e => unless e == "unbound variable in local context" do throw e
  -- Lean's opaque have may retain a stale value after reverting a dependency.
  -- It is a typed variable, unlike a transparent let with the same stale value.
  let hvar : FVarId := ⟨`opaqueHave⟩
  let lctx := ({} : LocalContext).mkLetDecl hvar `h (.sort .zero) (.fvar ⟨`cleared⟩) true
  let haveCtx := { mctx with decls := mctx.decls.insert g { d with lctx } }
  let haveWire ← capture haveCtx [g] 4096
  let rows ← (← haveWire.getObjVal? "metavariables").getArr?
  let locals ← (← rows[0]!.getObjVal? "locals").getArr?
  unless (← locals[0]!.getObjVal? "value") == Json.null do throw "opaque value exposed"
  unless (← locals[0]!.getObjValAs? Bool "nondep") do throw "opaque marker lost"
  let badLet := ({} : LocalContext).mkLetDecl hvar `h (.sort .zero) (.fvar ⟨`cleared⟩) false
  match capture { haveCtx with decls := haveCtx.decls.insert g { d with lctx := badLet } } [g] 4096 with
  | .ok _ => throw "transparent unbound let was accepted"
  | .error e => unless e == "unbound variable in local context" do throw e
  return wire

#eval do
  let wire ← IO.ofExcept stateFixture
  IO.println ("JEVOPS_STATE_FIXTURE:" ++ wire.compress)

/- The wire-budget gate must remove the entire state, not truncate its locals.
   A following small event remains captured, independent of the first event. -/
#eval show IO Unit from do
  let base := [("id", jn 7), ("parent", jn 3)]
  let fields := [("status", toJson "captured"),
    ("before", toJson (String.ofList (List.replicate 100000 'x'))), ("after", Json.null)]
  let large ← IO.ofExcept (boundedEvent base fields 256)
  unless large == Json.mkObj (base ++ [("status", toJson "unsupported"),
    ("reason", toJson "event observation byte budget")]) do
    throw (IO.userError "oversized event was not wholly unsupported")
  let small := [("status", toJson "captured"), ("before", Json.null), ("after", Json.null)]
  let kept ← IO.ofExcept (boundedEvent base small 256)
  unless kept == Json.mkObj (base ++ small) do throw (IO.userError "small event lost")
  match boundedEvent base small 0 with
  | .ok _ => throw (IO.userError "zero budget accepted")
  | .error _ => pure ()
