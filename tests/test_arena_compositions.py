"""Draft generation tests; only the native selector can verify a draft."""
import copy
import json
import os
from pathlib import Path
import sys

import pytest

from jevops import arena_compositions as compositions
from jevops import arena_lean as native
from jevops.arena_report_audit import audit_report
from jevops.arena import source_hash
from jevops.arena import Outcome, VerificationRequest
from jevops.lean import VersionPin

STATEMENT = "theorem compose_fixture (p : Prop) : p → p"


@pytest.mark.parametrize("tactic", ["intro", "intros"])
@pytest.mark.parametrize("names", ["h", "x h", "δ υπόθεση", "x' h'"])
def test_contract_one_adjacent_leaf_without_changing_statement(tactic, names):
    source = STATEMENT + f" := by\n  {tactic} {names}\n  exact {names.split()[-1]}\n"
    assert compositions.intro_exact_assumption(source, STATEMENT) == STATEMENT + " := by\n  repeat intro\n  assumption\n"


@pytest.mark.parametrize("body", [
    "intro h\n  exact h",  # different indentation
    "  intro h\n  exact other",  # not an introduced name
    "  intro h\n  exact id h",  # not a single identifier
    "  intro h\n  exact h\n  assumption",  # not a leaf
    "  intro h\n  exact h -- note", "  intro h\n  /- note -/\n  exact h",
    "  intro h\n\n  exact h", "  intros h h\n  exact h", "  intro _\n  exact _",
    "  intros (h : p)\n  exact h", "  intro h <;> simp\n  exact h",
    "  intro h\n\texact h", "  intro h\n  exact «h»",
])
def test_unsupported_or_nonleaf_shapes_abstain(body):
    assert compositions.intro_exact_assumption(STATEMENT + " := by\n" + body, STATEMENT) is None


def test_unrelated_branch_and_original_newline_are_preserved():
    source = STATEMENT + " := by\n  case left =>\n    intros x h\n    exact h\n  case right =>\n    exact other"
    result = compositions.intro_exact_assumption(source, STATEMENT)
    assert result == STATEMENT + " := by\n  case left =>\n    repeat intro\n    assumption\n  case right =>\n    exact other"
    assert compositions.intro_exact_assumption(STATEMENT + " := fun h => h", STATEMENT) is None
    assert compositions.intro_exact_assumption(source, "theorem different : True") is None


@pytest.mark.parametrize("ending", ["", "\n"])
def test_intro_simp_leaf_replacement_keeps_statement_and_newline(ending):
    source = STATEMENT + " := by\n  intro\n  simp_all" + ending
    assert compositions.intro_simp_grind(source, STATEMENT) == STATEMENT + " := by\n  grind" + ending


def test_first_and_all_leaf_replacements_are_distinct_frozen_ablations():
    first = "    intro\n    simp_all\n"
    second = "    intro\n    simp_all"
    source = STATEMENT + " := by\n  case left =>\n" + first + "  case right =>\n" + second
    assert compositions.intro_simp_grind(source, STATEMENT) == source.replace(first, "    grind\n", 1)
    assert compositions.intro_simp_grind(source, STATEMENT, replace_all=True) == (
        STATEMENT + " := by\n  case left =>\n    grind\n  case right =>\n    grind")


@pytest.mark.parametrize("body", [
    "  intro h\n  simp_all", "  intros\n  simp_all", "  intro\n    simp_all",
    "  intro\n\n  simp_all", "  intro\n  simp_all [foo]", "  intro\n  simp_all at *",
    "  intro\n  simp_all\n  exact h", "  intro\n  simp_all\n    exact h",
    "  intro\n  simp_all -- note", "  intro\n  simp_all\n  /- note -/",
    "\tintro\n\tsimp_all", "  intro\r\n  simp_all\r\n", "  intro; simp_all",
    '  have x := "intro\\nsimp_all"', "  intro\n  simp_all\n  exact `x",
])
def test_unsupported_intro_simp_shapes_abstain(body):
    assert compositions.intro_simp_grind(STATEMENT + " := by\n" + body, STATEMENT) is None


def test_intro_simp_term_proofs_and_invalid_policies_abstain():
    assert compositions.intro_simp_grind(STATEMENT + " := fun h => h", STATEMENT) is None
    assert compositions.intro_simp_grind(STATEMENT + " := by\n  intro\n  simp_all", "theorem other : True") is None
    for policy in (1, None, "all"):
        with pytest.raises(ValueError):
            compositions.intro_simp_grind(STATEMENT + " := by\n  intro\n  simp_all", STATEMENT, replace_all=policy)


def test_intro_simp_limits_and_duplicate_paths():
    source = STATEMENT + " := by\n" + "\n" * 256 + "  intro\n  simp_all"
    assert compositions.intro_simp_grind(source, STATEMENT) is None
    source = STATEMENT + " := by\n" + " " * 32768 + "intro\n  simp_all"
    assert compositions.intro_simp_grind(source, STATEMENT) is None
    record = dict(name="compose_fixture", statement=STATEMENT, src=STATEMENT + " := by\n  intro\n  simp_all")
    batch = compositions.draft_batch(record, [["intro_simp_grind_first"], ["intro_simp_grind_all"]])
    assert [a["status"] for a in batch["attempts"]] == ["DRAFT", "DUPLICATE"]
    assert not batch["proof_verified"] and batch["native_processes"] == 0


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("bullet", ["", ". ", "· "])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("ending", ["", "\n"])
def test_constructive_subset_block_preserves_discharge_and_layout(side, bullet, inline, ending):
    indent = "    " if bullet else "  "
    discharge = indent + "apply ih ; assumption" if inline else indent + "apply ih\n" + indent + "assumption"
    source = STATEMENT + " := by\n  " + bullet + "apply List.Subset.trans\n" + discharge + "\n" + indent + "intro\n" + indent + "simp_all" + ending
    expected = STATEMENT + " := by\n  " + bullet + f"apply List.subset_append_of_subset_{side}\n" + discharge + ending
    assert compositions.subset_trans_append(source, STATEMENT, side=side) == expected


@pytest.mark.parametrize("replacement", ["apply ih h", "apply Foo.ih", "apply (ih)", "exact ih", "apply _",
                                       "apply ih <;> assumption", "apply ih; assumption; skip", "apply `ih"])
def test_subset_matcher_does_not_guess_argument_or_expression_boundaries(replacement):
    source = STATEMENT + " := by\n  apply List.Subset.trans\n  " + replacement + "\n  assumption\n  intro\n  simp_all"
    assert compositions.subset_trans_append(source, STATEMENT, side="left") is None


@pytest.mark.parametrize("damage", ["indent", "intro_name", "blank", "comment", "nonterminal", "nonterminal_child", "simp_args", "tab", "oversize"])
def test_subset_unsupported_layout_abstains(damage):
    source = STATEMENT + " := by\n  . apply List.Subset.trans\n    apply ih\n    assumption\n    intro\n    simp_all"
    if damage == "indent": source = source.replace("    assumption", "   assumption")
    elif damage == "intro_name": source = source.replace("intro", "intro x")
    elif damage == "blank": source = source.replace("    intro", "\n    intro")
    elif damage == "comment": source += " -- not a rewrite target"
    elif damage == "nonterminal": source += "\n    exact ih"
    elif damage == "nonterminal_child": source += "\n      exact ih"
    elif damage == "simp_args": source += " [List.Subset]"
    elif damage == "tab": source = source.replace("    ", "\t")
    else: source += "\n" * 256
    assert compositions.subset_trans_append(source, STATEMENT, side="right") is None


def test_subset_direction_is_allowlisted_and_term_proofs_abstain():
    source = STATEMENT + " := fun h => h"
    assert compositions.subset_trans_append(source, STATEMENT, side="left") is None
    for side in (None, True, "middle", "left; sorry", []):
        with pytest.raises(ValueError): compositions.subset_trans_append(source, STATEMENT, side=side)


def test_subset_composition_changes_each_matching_block_once():
    leaf = "  . apply List.Subset.trans\n    apply h'\n    assumption\n    intro\n    simp_all\n"
    source = STATEMENT + " := by\n" + leaf + leaf
    record = dict(name="compose_fixture", statement=STATEMENT, src=source)
    batch = compositions.draft_batch(record, [["subset_trans_append_left", "subset_trans_append_right"]])
    draft = batch["drafts"][0]["source"]
    assert draft.count("subset_append_of_subset_left") == draft.count("subset_append_of_subset_right") == 1
    assert "List.Subset.trans" not in draft and draft.count("apply h'") == 2
    assert batch["attempts"][0]["steps"][0]["after_sha256"] == batch["attempts"][0]["steps"][1]["before_sha256"]
    assert not batch["proof_verified"] and batch["native_processes"] == 0


def _pair_body(parent="", bullet=". ", inline=True, ending="\n"):
    indent = "  " + ("  " if parent else "")
    leaves = []
    for name in ("ih1", "ih2"):
        discharge = (f"apply {name} ; assumption\n" if inline else f"apply {name}\n{indent}  assumption\n")
        leaves.append(f"{indent}{bullet}apply List.Subset.trans\n{indent}  {discharge}"
                      f"{indent}  intro\n{indent}  simp_all\n")
    return ("  " + parent + "apply List.Subset.app\n" + "".join(leaves)).rstrip("\n") + ending


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("parent", ["", ". ", "· "])
@pytest.mark.parametrize("bullet", [". ", "· "])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("ending", ["", "\n"])
def test_shared_target_precedes_split_and_preserves_both_discharges(side, parent, bullet, inline, ending):
    source = STATEMENT + " := by\n" + _pair_body(parent, bullet, inline, ending)
    result = compositions.subset_pair_target(source, STATEMENT, side=side)
    indent = "  " + ("  " if parent else "")
    expected = source.replace("  " + parent + "apply List.Subset.app\n",
        "  " + parent + f"apply List.subset_append_of_subset_{side}\n" + indent + "apply List.Subset.app\n", 1)
    expected = expected.replace("List.Subset.trans", "List.subset_append_of_subset_left", 1)
    expected = expected.replace("List.Subset.trans", "List.subset_append_of_subset_right", 1)
    expected = expected.replace(indent + "  intro\n", "").replace(indent + "  simp_all\n", "")
    if not ending:
        expected = expected.removesuffix(indent + "  simp_all").removesuffix("\n")
    assert result == expected
    assert compositions.reference_tokens(source, STATEMENT) - compositions.reference_tokens(result, STATEMENT) == 2


@pytest.mark.parametrize("damage", ["parent_argument", "parent_combinator", "first_leaf", "second_leaf",
    "hyp_argument", "hyp_qualified", "hyp_wildcard", "discharge", "intro_name", "simp_arguments",
    "blank", "indent", "nonterminal", "third_child", "missing_second", "tab", "cr", "comment", "quote", "lines", "bytes"])
def test_shared_target_unsupported_or_partial_shapes_abstain(damage):
    body = _pair_body()
    if damage == "parent_argument": body = body.replace("List.Subset.app", "List.Subset.app h")
    elif damage == "parent_combinator": body = body.replace("List.Subset.app", "List.Subset.app <;> skip")
    elif damage == "first_leaf": body = body.replace("List.Subset.trans", "List.Subset.refl", 1)
    elif damage == "second_leaf": body = body.rsplit("List.Subset.trans", 1)[0] + body.rsplit("List.Subset.trans", 1)[1]
    elif damage == "hyp_argument": body = body.replace("apply ih1", "apply ih1 h")
    elif damage == "hyp_qualified": body = body.replace("apply ih1", "apply Foo.ih1")
    elif damage == "hyp_wildcard": body = body.replace("apply ih2", "apply _")
    elif damage == "discharge": body = body.replace("assumption", "skip", 1)
    elif damage == "intro_name": body = body.replace("intro\n", "intro x\n", 1)
    elif damage == "simp_arguments": body = body.replace("simp_all", "simp_all [h]", 1)
    elif damage == "blank": body = body.replace("  . apply List.Subset.trans", "\n  . apply List.Subset.trans", 1)
    elif damage == "indent": body = body.replace("    apply ih2", "   apply ih2")
    elif damage == "nonterminal": body += "  assumption\n"
    elif damage == "third_child": body += "  . assumption\n"
    elif damage == "missing_second": body = body.rsplit("  . apply List.Subset.trans", 1)[0]
    elif damage == "tab": body = body.replace("    ", "\t")
    elif damage == "cr": body = body.replace("\n", "\r\n")
    elif damage == "comment": body += "-- comment\n"
    elif damage == "quote": body += '  have s := "x"\n'
    elif damage == "lines": body += "\n" * 256
    else: body += " " * 32768
    assert compositions.subset_pair_target(STATEMENT + " := by\n" + body, STATEMENT, side="right") is None


def test_shared_target_direction_and_statement_boundary():
    source = STATEMENT + " := by\n" + _pair_body()
    assert compositions.subset_pair_target(source, "theorem other : True", side="right") is None
    assert compositions.subset_pair_target(STATEMENT + " := fun h => h", STATEMENT, side="left") is None
    for side in (None, True, [], "right; sorry"):
        with pytest.raises(ValueError): compositions.subset_pair_target(source, STATEMENT, side=side)


def test_shared_target_edits_only_first_supported_pair_and_preserves_other_cases():
    body = "".join("  " + line for line in _pair_body().splitlines(keepends=True))
    source = STATEMENT + " := by\n  case first =>\n" + body + "  case second =>\n" + body
    result = compositions.subset_pair_target(source, STATEMENT, side="right")
    assert result is not None
    assert result.split("  case second =>\n", 1)[1] == body
    assert result.count("List.Subset.trans") == 2


def test_shared_target_composition_lineage_and_duplicate_nomination():
    source = STATEMENT + " := by\n" + _pair_body()
    record = dict(name="compose_fixture", statement=STATEMENT, src=source)
    batch = compositions.draft_batch(record, [["subset_pair_target_right"], ["subset_pair_target_right"]])
    assert [a["status"] for a in batch["attempts"]] == ["DRAFT", "DUPLICATE"]
    step = batch["attempts"][0]["steps"][0]
    assert step["before_sha256"] == source_hash(source)
    assert step["after_sha256"] == source_hash(batch["drafts"][0]["source"])
    assert step["before_tokens"] - step["after_tokens"] == 2
    assert not batch["proof_verified"] and not batch["training_enabled"] and batch["native_processes"] == 0
    assert compositions.draft_batch(record, [["subset_pair_target_right", "subset_pair_target_right"]])["drafts"] == []


def _lifted_pair_body(parent="", bullet=". ", inline=True, ending="\n"):
    indent = "  " + ("  " if parent else "")
    leaves = []
    for name, side in (("ih1", "left"), ("ih2", "right")):
        discharge = (f"apply {name} ; assumption\n" if inline else f"apply {name}\n{indent}  assumption\n")
        leaves.append(f"{indent}{bullet}apply List.subset_append_of_subset_{side}\n{indent}  {discharge}")
    return ("  " + parent + "apply List.Subset.app\n" + "".join(leaves)).rstrip("\n") + ending


@pytest.mark.parametrize("split_disjunction", [False, True])
@pytest.mark.parametrize("parent", ["", ". ", "· "])
@pytest.mark.parametrize("bullet", [". ", "· "])
@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("ending", ["", "\n"])
def test_pair_simp_preserves_parent_bullet_statement_and_ending(split_disjunction, parent, bullet, inline, ending):
    source = STATEMENT + " := by\n" + _lifted_pair_body(parent, bullet, inline, ending)
    lemmas = "List.Subset, or_imp" if split_disjunction else "List.Subset"
    expected = STATEMENT + " := by\n  " + parent + f"simp_all [{lemmas}]" + ending
    assert compositions.subset_pair_simp(source, STATEMENT, split_disjunction=split_disjunction) == expected


@pytest.mark.parametrize("damage", ["parent_argument", "first_side", "second_side", "hyp_argument",
    "hyp_qualified", "hyp_wildcard", "discharge", "blank", "indent", "nonterminal", "third_child",
    "missing_second", "tab", "cr", "comment", "quote", "lines", "bytes"])
def test_pair_simp_abstains_on_unsupported_shapes(damage):
    body = _lifted_pair_body()
    if damage == "parent_argument": body = body.replace("List.Subset.app", "List.Subset.app h")
    elif damage == "first_side": body = body.replace("subset_left", "subset_right")
    elif damage == "second_side": body = body.replace("subset_right", "subset_left")
    elif damage == "hyp_argument": body = body.replace("apply ih1", "apply ih1 h")
    elif damage == "hyp_qualified": body = body.replace("apply ih1", "apply Foo.ih1")
    elif damage == "hyp_wildcard": body = body.replace("apply ih2", "apply _")
    elif damage == "discharge": body = body.replace("assumption", "assumption; skip", 1)
    elif damage == "blank": body = body.replace("  . apply", "\n  . apply", 1)
    elif damage == "indent": body = body.replace("    apply ih2", "   apply ih2")
    elif damage == "nonterminal": body += "  assumption\n"
    elif damage == "third_child": body += "  . assumption\n"
    elif damage == "missing_second": body = body.split("  . apply List.subset_append_of_subset_right", 1)[0]
    elif damage == "tab": body = body.replace("    ", "\t")
    elif damage == "cr": body = body.replace("\n", "\r\n")
    elif damage == "comment": body += "-- comment\n"
    elif damage == "quote": body += '  have s := "x"\n'
    elif damage == "lines": body += "\n" * 256
    else: body += " " * 32768
    source = STATEMENT + " := by\n" + body
    for replace_all in (False, True):
        assert compositions.subset_pair_simp(source, STATEMENT, replace_all=replace_all) is None


def test_pair_simp_policies_and_statement_boundary():
    source = STATEMENT + " := by\n" + _lifted_pair_body()
    assert compositions.subset_pair_simp(source, "theorem other : True") is None
    assert compositions.subset_pair_simp(STATEMENT + " := fun h => h", STATEMENT) is None
    for invalid in (None, 1, "all", []):
        with pytest.raises(ValueError): compositions.subset_pair_simp(source, STATEMENT, replace_all=invalid)
        with pytest.raises(ValueError): compositions.subset_pair_simp(source, STATEMENT, split_disjunction=invalid)


def test_pair_simp_first_all_use_original_nonoverlapping_matches():
    body = "".join("  " + line for line in _lifted_pair_body().splitlines(keepends=True))
    source = STATEMENT + " := by\n  case first =>\n" + body + "  case second =>\n" + body
    first = compositions.subset_pair_simp(source, STATEMENT)
    all_pairs = compositions.subset_pair_simp(source, STATEMENT, replace_all=True)
    assert first == source.replace(body, "    simp_all [List.Subset]\n", 1)
    assert all_pairs == source.replace(body, "    simp_all [List.Subset]\n")
    record = dict(name="compose_fixture", statement=STATEMENT, src=source)
    paths = [["subset_pair_simp_first"], ["subset_pair_simp_all"],
             ["subset_pair_simp_split_first"], ["subset_pair_simp_split_all"]]
    batch = compositions.draft_batch(record, paths)
    assert len({d["source"] for d in batch["drafts"]}) == 4
    assert batch["drafts"][0]["source"] == first and batch["drafts"][1]["source"] == all_pairs
    assert not batch["proof_verified"] and not batch["training_enabled"] and batch["native_processes"] == 0
    record["src"] = STATEMENT + " := by\n" + _lifted_pair_body()
    single = compositions.draft_batch(record, paths)
    assert [a["status"] for a in single["attempts"]] == ["DRAFT", "DUPLICATE", "DRAFT", "DUPLICATE"]
    assert compositions.draft_batch(record, [["subset_pair_simp_first", "subset_pair_simp_first"]])["drafts"] == []


@pytest.fixture
def record():
    rows = [json.loads(line) for line in native.CORPUS.read_text().splitlines() if line.strip()]
    return next(row for row in rows if row["name"] == "CallElimCorrect.extractedOldExprInVars")


def _triple_body(*, bullet='', inline=True, ending='\n'):
    indent = '  ' + ('  ' if bullet else '')
    def leaf(side, name):
        discharge = f'apply {name} ; assumption' if inline else f'apply {name}\n{indent}  assumption'
        return f'{indent}. apply List.subset_append_of_subset_{side}\n{indent}  {discharge}\n'
    return ('  ' + bullet + 'apply List.Subset.app\n' + leaf('left', 'a')
            + indent + 'apply List.subset_append_of_subset_right\n'
            + indent + 'apply List.Subset.app\n' + leaf('left', 'b') + leaf('right', 'c')).rstrip('\n') + ending


@pytest.mark.parametrize('strategy,script', [
    ('simp', 'simp_all only [List.Subset, List.mem_append, or_imp, forall_and]'),
    ('grind', 'grind only [List.Subset, List.mem_append]'),
    ('simp_grind', 'simp_all only [List.Subset, List.mem_append]\n{indent}grind only []'),
    ('simp_normalized', 'simp_all only [List.Subset, List.mem_append, or_imp, forall_and, '
                        'true_implies, true_or, or_true, implies_true, and_self]'),
    ('simp_normalized_compact', 'simp_all only [List.Subset, List.mem_append, or_imp, '
                                'true_implies, true_or, or_true, implies_true, and_self]'),
    ('term', 'exact List.Subset.app\n'
             '{indent}  (List.subset_append_of_subset_left _ (a ‹_›))\n'
             '{indent}  (List.subset_append_of_subset_right _ (List.Subset.app\n'
             '{indent}    (List.subset_append_of_subset_left _ (b ‹_›))\n'
             '{indent}    (List.subset_append_of_subset_right _ (c ‹_›))))'),
    ('term_leaves', 'apply List.Subset.app\n'
                    '{indent}. exact List.subset_append_of_subset_left _ (a ‹_›)\n'
                    '{indent}apply List.subset_append_of_subset_right\n'
                    '{indent}apply List.Subset.app\n'
                    '{indent}. exact List.subset_append_of_subset_left _ (b ‹_›)\n'
                    '{indent}. exact List.subset_append_of_subset_right _ (c ‹_›)'),
    ('left_nested', 'apply List.Subset.app\n'
                    '{indent}. apply List.subset_append_of_subset_left\n'
                    '{indent}  apply List.Subset.app\n'
                    '{indent}  . apply List.subset_append_of_subset_left\n'
                    '{indent}    apply a ; assumption\n'
                    '{indent}  . apply List.subset_append_of_subset_right\n'
                    '{indent}    apply b ; assumption\n'
                    '{indent}apply List.subset_append_of_subset_right\n'
                    '{indent}apply c ; assumption'),
])
@pytest.mark.parametrize('bullet', ['', '. ', '· '])
@pytest.mark.parametrize('inline,ending', [(True, ''), (False, '\n')])
def test_triple_reconstruction_exact_layout_and_endings(strategy, script, bullet, inline, ending):
    source = STATEMENT + ' := by\n' + _triple_body(bullet=bullet, inline=inline, ending=ending)
    result = compositions.subset_triple_reconstruct(source, STATEMENT, strategy=strategy)
    indent = '  ' + ('  ' if bullet else '')
    if strategy == 'left_nested' and not inline:
        for name, padding in [('a', '    '), ('b', '    '), ('c', '')]:
            script = script.replace(f'apply {name} ; assumption', f'apply {name}\n{{indent}}{padding}assumption')
    assert result == STATEMENT + ' := by\n  ' + bullet + script.format(indent=indent) + ending
    assert compositions.subset_triple_reconstruct(result, STATEMENT, strategy=strategy) is None


@pytest.mark.parametrize('damage', ['first_side', 'shared_side', 'last_side', 'extra_argument',
    'wrong_discharge', 'same_indent_followup', 'deeper_followup', 'missing_leaf', 'blank',
    'comment', 'tab', 'crlf', 'too_many_lines', 'too_many_bytes'])
def test_triple_reconstruction_abstains_without_guessing_scope(damage):
    body = _triple_body()
    if damage == 'first_side': body = body.replace('subset_left', 'subset_right', 1)
    elif damage == 'shared_side': body = body.replace('  apply List.subset_append_of_subset_right', '  apply List.subset_append_of_subset_left', 1)
    elif damage == 'last_side': body = body.replace('. apply List.subset_append_of_subset_right', '. apply List.subset_append_of_subset_left')
    elif damage == 'extra_argument': body = body.replace('apply a ;', 'apply a h ;')
    elif damage == 'wrong_discharge': body = body.replace('apply b ; assumption', 'apply b ; exact h')
    elif damage == 'same_indent_followup': body += '  exact leftover\n'
    elif damage == 'deeper_followup': body += '    exact leftover\n'
    elif damage == 'missing_leaf': body = body.split('  . apply List.subset_append_of_subset_right')[0]
    elif damage == 'blank': body = body.replace('    apply b', '\n    apply b')
    elif damage == 'comment': body += '-- note\n'
    elif damage == 'tab': body = body.replace('    ', '\t')
    elif damage == 'crlf': body = body.replace('\n', '\r\n')
    elif damage == 'too_many_lines': body += '\n' * 256
    elif damage == 'too_many_bytes': body += ' ' * 32768
    for strategy in ('simp', 'grind', 'simp_grind', 'simp_normalized', 'simp_normalized_compact', 'term', 'term_leaves', 'left_nested'):
        assert compositions.subset_triple_reconstruct(STATEMENT + ' := by\n' + body, STATEMENT, strategy=strategy) is None


@pytest.mark.parametrize('strategy', ['term', 'term_leaves'])
def test_triple_terms_capture_names_and_preserve_unmatched_regions(strategy, monkeypatch):
    monkeypatch.setattr(native, 'run_native', lambda *a, **k: pytest.fail('nomination must not invoke Lean'))
    body = _triple_body().replace('apply a ;', "apply hyp_a' ;").replace('apply b ;', 'apply β ;')
    nested = ''.join('  ' + line for line in body.splitlines(keepends=True))
    prefix = STATEMENT + ' := by\n  case first =>\n    cases Hnorm\n'
    suffix = '  case untouched =>\n' + nested
    source = prefix + nested + suffix
    result = compositions.subset_triple_reconstruct(source, STATEMENT, strategy=strategy)
    assert result.startswith(prefix) and result.endswith(suffix)
    assert "(hyp_a' ‹_›)" in result and '(β ‹_›)' in result and '(c ‹_›)' in result
    assert 'grind' not in result and 'simp' not in result
    assert 0 < compositions.reference_tokens(result, STATEMENT) - compositions.reference_tokens(source, STATEMENT) <= 16


@pytest.mark.parametrize('strategy', ['term', 'term_leaves', 'left_nested'])
@pytest.mark.parametrize('name', ['_', 'a.h', 'a h', '(a)', '‹a›', 'a; exact h'])
def test_triple_terms_do_not_splice_expressions_as_leaf_names(strategy, name):
    source = STATEMENT + ' := by\n' + _triple_body().replace('apply a ;', f'apply {name} ;')
    assert compositions.subset_triple_reconstruct(source, STATEMENT, strategy=strategy) is None


@pytest.mark.parametrize('growth,accepted', [(16, True), (17, False)])
def test_triple_term_growth_ceiling_is_enforced(growth, accepted, monkeypatch):
    source = STATEMENT + ' := by\n' + _triple_body()
    monkeypatch.setattr(compositions, 'reference_tokens', lambda value, statement: 100 if value == source else 100 + growth)
    for strategy in ('term', 'term_leaves'):
        result = compositions.subset_triple_reconstruct(source, STATEMENT, strategy=strategy)
        assert (result is not None) == accepted


def test_triple_reconstruction_fixed_statement_and_strategy():
    for bad in (True, None, 'simp_all', '__import__'):
        with pytest.raises(ValueError):
            compositions.subset_triple_reconstruct(STATEMENT + ' := by\n' + _triple_body(), STATEMENT, strategy=bad)
    assert compositions.subset_triple_reconstruct(STATEMENT + ' := fun h => h', STATEMENT, strategy='simp') is None
    assert compositions.subset_triple_reconstruct(STATEMENT + ' := by\n' + _triple_body(), 'theorem other : True', strategy='simp') is None


def test_triple_strata_reconstruction_preserves_other_branches_and_budget(record):
    from jevops.arena import reference_tokens
    from jevops.arena_trial import Candidate
    archive = Path(__file__).resolve().parents[1] / 'papers/completion/lean_refactor_arena/evidence/subset-triple-strata-2026-09-25/incumbent.json'
    raw = json.loads(archive.read_text())
    seed = Candidate(raw['label'], raw['source'], raw['provenance'])
    paths = [['subset_triple_' + s] for s in ('simp', 'grind', 'simp_grind')]
    batch = compositions.draft_batch(record, paths, seed=seed)
    assert reference_tokens(seed.source, record['statement']) == 169
    assert len(batch['drafts']) == 3
    for draft in batch['drafts']:
        assert set(draft) == {'name', 'source', 'label', 'provenance'}
        assert draft['source'].split('  case ite ', 1)[0] == seed.source.split('  case ite ', 1)[0]
        assert draft['source'].split('  case eq ', 1)[1] == seed.source.split('  case eq ', 1)[1]
        assert reference_tokens(draft['source'], record['statement']) < 169
    assert not batch['proof_verified'] and batch['native_processes'] == 0
    assert not compositions.draft_batch(record, paths, seed=seed, cap=0)['drafts']
    assert len(compositions.draft_batch(record, paths, seed=seed, cap=1)['drafts']) == 1
    assert compositions.draft_batch(record, [paths[0], paths[0]], seed=seed)['attempts'][1]['status'] == 'DUPLICATE'


PATHS = [["drop_rename_i"], ["intro_exact_assumption"], ["drop_rename_i", "intro_exact_assumption"]]


def test_benchmark_drafts_are_distinct_unverified_ablations(record, monkeypatch):
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("drafts cannot run Lean"))
    before = copy.deepcopy(record)
    batch = compositions.draft_batch(record, PATHS, cap=3)
    assert record == before
    assert batch["reference_tokens"] == 222
    assert [a["tokens"] for a in batch["attempts"]] == [213, 220, 211]
    assert len({d["source"] for d in batch["drafts"]}) == 3
    assert all(set(d) == {"name", "label", "source", "provenance"} for d in batch["drafts"])
    assert all(d["source"].startswith(record["statement"]) for d in batch["drafts"])
    steps = batch["attempts"][-1]["steps"]
    assert steps[0]["before_sha256"] == source_hash(record["src"])
    assert steps[0]["after_sha256"] == steps[1]["before_sha256"] == source_hash(batch["drafts"][0]["source"])
    assert steps[1]["after_sha256"] == source_hash(batch["drafts"][-1]["source"])
    assert not batch["proof_verified"] and not batch["training_enabled"] and not batch["promoted"]
    assert batch["native_processes"] == 0 and batch["official_score"] is None


def test_cap_deduplication_and_abstention_are_explicit(record):
    assert compositions.draft_batch(record, PATHS, cap=0)["attempts"] == []
    assert len(compositions.draft_batch(record, PATHS, cap=1)["drafts"]) == 1
    batch = compositions.draft_batch(record, [PATHS[0], PATHS[0], ["proof_slice_unused_have"]])
    assert [a["status"] for a in batch["attempts"]] == ["DRAFT", "DUPLICATE", "ABSTAINED"]
    assert len(batch["drafts"]) == 1
    # A non-applicable final step cannot silently return a shorter partial path.
    assert compositions.draft_batch(record, [["drop_rename_i", "proof_slice_unused_have"]])["drafts"] == []


@pytest.mark.parametrize("paths", [[], "drop_rename_i", [[]], [["__import__"]], [["drop_rename_i"] * 4], PATHS * 3])
def test_unknown_or_unbounded_rule_paths_rejected(record, paths):
    with pytest.raises(ValueError):
        compositions.draft_batch(record, paths)


@pytest.mark.parametrize("cap", [True, -1, 9, 1.5])
def test_bad_caps_rejected(record, cap):
    with pytest.raises(ValueError):
        compositions.draft_batch(record, PATHS, cap=cap)


def test_cli_writes_importable_drafts_and_never_overwrites(record, tmp_path, monkeypatch, capsys):
    output = tmp_path / "drafts"
    monkeypatch.setattr(sys, "argv", ["arena_compositions", "--problem", record["name"], "--path", "drop_rename_i",
        "--path", "intro_exact_assumption", "--path", "drop_rename_i,intro_exact_assumption", "--output-dir", str(output)])
    assert compositions.main() == 0
    assert json.loads(capsys.readouterr().out)["count"] == 3
    manifest = (output / "manifest.json").read_bytes()
    assert all((output / f"composition-{i}.json").is_file() for i in range(3))
    with pytest.raises(SystemExit) as exc:
        compositions.main()
    assert exc.value.code == 2 and (output / "manifest.json").read_bytes() == manifest


@pytest.mark.no_seal(reason="fresh native proof checks; external toolchain inputs")
@pytest.mark.parametrize("body,expected", [("intros; assumption", Outcome.REJECTED),
                                          ("repeat intro; assumption", Outcome.REJECTED),
                                          ("generated", Outcome.VERIFIED)])
def test_native_hidden_binders_need_unfolding(tmp_path, body, expected):
    if os.environ.get("JEVOPS_ARENA_NATIVE_TESTS") != "1":
        pytest.skip("explicit native opt-in; no toolchain downloads")
    tag = "v4.26.0"
    lean = native.pinned_lean(Path(os.environ.get("ELAN_HOME", str(Path.home() / ".elan"))), tag)
    pin = VersionPin(tag, "local-hidden-binder-regression")
    statement = "theorem hidden_binders (xs : List Nat) : HiddenSubset xs xs"
    source = statement + " := by\n  intro x hx\n  exact hx"
    record = {"name": "hidden_binders", "statement": statement, "src": source,
              "version_info": [{tag: pin.git_commit}]}
    prefix = "def HiddenSubset (xs ys : List Nat) : Prop := ∀ x, x ∈ xs → x ∈ ys\n"
    binding = native.ProjectBinding(pin, lean, tmp_path, prefix, project_backed=False)
    verifier = native.NativeLeanVerifier({pin: binding}, max_processes=1, timeout=60)
    context = verifier.context(record)
    candidate = (compositions.intro_exact_assumption(source, statement) if body == "generated"
                 else statement + " := by " + body)
    assert candidate is not None
    receipt = verifier(VerificationRequest(context, candidate, pin))
    assert receipt.outcome == expected, receipt


def test_saved_pilot_retains_invalid_shorter_arms_as_rejections(monkeypatch):
    """Historical bookkeeping only; this does not rerun or admit the proof."""
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("historical report inspection"))
    path = (Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence"
            / "native-composition-pilot-2026-09-23")
    report = json.loads((path / "report.json").read_text())
    audit = audit_report(json.loads((path / "protocol.json").read_text()), report)
    assert audit["status"] == "CONSISTENT", audit
    assert audit["proof_verified"] is False and audit["fresh_native_processes"] == 0
    assert report["selected_for_confirmation"] == "composition-0"
    rows = report["screen_analysis"]["rows"]
    assert rows["composition-0"]["tokens"] == 213 and rows["composition-0"]["admissible"]
    assert rows["composition-2"]["tokens"] == 211 and not rows["composition-2"]["admissible"]
    assert sum(s["status"] == "REJECTED" for s in report["screen"]["samples"]) == 8
    assert report["native_processes"] == 24 and report["training_enabled"] is report["promoted"] is False


def test_saved_repair_cannot_trade_more_heartbeats_for_fewer_tokens(monkeypatch):
    """Historical bookkeeping, not fresh native verification or admission."""
    monkeypatch.setattr(native, "run_native", lambda *a, **k: pytest.fail("historical report inspection"))
    path = (Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/evidence"
            / "native-composition-repair-2026-09-23")
    report = json.loads((path / "report.json").read_text())
    audit = audit_report(json.loads((path / "protocol.json").read_text()), report)
    assert audit["status"] == "CONSISTENT", audit
    assert report["status"] == "NO_IMPROVEMENT" and report["recommended"] is None
    assert report["retained_incumbent"] == "composition-0" and report["retained_incumbent_verified"]
    rows = report["screen_analysis"]["rows"]
    incumbent, candidate = rows["composition-0"], rows["composition-2"]
    assert candidate["admissible"] and candidate["tokens"] == 211 < incumbent["tokens"] == 213
    assert all(min(a) > max(b) for a, b in zip(candidate["raw_heartbeats_by_stratum"],
                                             incumbent["raw_heartbeats_by_stratum"]))
    assert report["screen_analysis"]["frontier"] == ["composition-0", "composition-2"]
    assert report["confirmation"] is None and report["native_processes"] == 12
    assert report["training_enabled"] is report["promoted"] is False
