import ExprDAG

open Lean JevOpsDAG

def fixtureRoots : Array Expr := Id.run do
  let u := Level.param `u
  let v := Level.param `v
  let nat := Expr.const `Nat []
  let zero := Expr.lit (.natVal 0)
  let md : MData := { entries := [(`k, .ofString "λ\n\"\u0000"), (`k, .ofNat (2^128)),
    (`signed, .ofInt (-123)), (`flag, .ofBool true), (`name, .ofName (.num (.str .anonymous "x.y") 7))] }
  let mut out := #[Expr.sort (.max u v), Expr.sort (.imax u v), Expr.sort (.succ u),
    Expr.const `Eq [u, v, u], Expr.const (.str .anonymous "A.B") [], Expr.const `A.B [],
    Expr.const (.num `A 7) [], Expr.const (.str `A "7") [],
    Expr.letE `x nat zero (.bvar 0) false, Expr.letE `x nat zero (.bvar 0) true,
    Expr.proj `Prod 0 (.const `pair []), Expr.lit (.strVal "λ\n\"\u0000"),
    Expr.mdata md zero, Expr.mdata { entries := md.entries.reverse } zero]
  for bi in [BinderInfo.default, .implicit, .strictImplicit, .instImplicit] do
    out := out.push (.lam `x nat (.bvar 0) bi)
    out := out.push (.forallE `x nat (.bvar 0) bi)
  -- Identical bvar syntax denotes different binders at these two occurrences.
  out := out.push (.lam `p (.sort .zero) (.lam `h (.bvar 0) (.bvar 0) .default) .default)
  let mut shared := zero
  for _ in [:24] do
    shared := .app shared shared
  return out.push shared

def dagFixtureTest : IO Unit := do
  let exact ← IO.mkRef ({ data := "λabc".toUTF8 } : IO.FS.Stream.Buffer)
  unless (← readBounded (IO.FS.Stream.ofBuffer exact) 5) == "λabc" do
    throw (IO.userError "bounded UTF-8 read mismatch")
  let oversized ← IO.mkRef ({ data := "abcdefghijklmnop".toUTF8 } : IO.FS.Stream.Buffer)
  let rejected ← try
    let _ ← readBounded (IO.FS.Stream.ofBuffer oversized) 8
    pure false
  catch _ => pure true
  unless rejected && (← oversized.get).pos == 9 do
    throw (IO.userError "input budget must reject before consuming the stream")
  let malformed ← IO.mkRef ({ data := ByteArray.mk #[255] } : IO.FS.Stream.Buffer)
  let rejected ← try
    let _ ← readBounded (IO.FS.Stream.ofBuffer malformed) 8
    pure false
  catch _ => pure true
  unless rejected do throw (IO.userError "malformed UTF-8 accepted")
  let environment := String.ofList (List.replicate 64 'a')
  let wire ← match checkedEncode fixtureRoots environment 10000 with
    | .ok wire => pure wire
    | .error e => throw (IO.userError e)
  for bad in [Expr.fvar ⟨`x⟩, Expr.mvar ⟨`m⟩, Expr.sort (.mvar ⟨`u⟩), Expr.bvar 0,
              Expr.mdata { entries := [(`syntax, .ofSyntax .missing)] } (.lit (.natVal 0))] do
    match checkedEncode #[bad] environment 10000 with
    | .ok _ => throw (IO.userError "unsupported expression was accepted")
    | .error _ => pure ()
  match checkedEncode fixtureRoots environment 1 with
  | .ok _ => throw (IO.userError "node budget ignored")
  | .error _ => pure ()
  IO.println ("JEVOPS_DAG_FIXTURE:" ++ wire.compress)

#eval dagFixtureTest
