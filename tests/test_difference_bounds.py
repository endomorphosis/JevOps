from __future__ import annotations

from itertools import product
import shutil

import pytest

from jevops.difference_bounds import DifferenceBound as B, closure, reduce_bounds, verify_path, implication_obligation
from jevops.router_tuning import _lean_compiler


def test_transitive_redundancy_duplicate_removal_and_final_support():
    cs = [B(0,1,2), B(1,2,3), B(0,2,7), B(0,1,2), B(2,2,0)]
    result = reduce_bounds(cs, 3)
    assert result["kept_indices"] == [0,1]
    assert not result["lean_verified"] and not result["global_minimum"]
    for cert in result["certificates"]:
        assert set(cert["path"]) <= set(result["kept_indices"])
        assert verify_path(cs, cs[cert["removed_index"]], cert["path"])
    for xs in product(range(-4,5), repeat=3):
        truth = lambda c: xs[c.left] - xs[c.right] <= c.bound
        assert all(map(truth, cs)) == all(truth(cs[i]) for i in result["kept_indices"])


def test_negative_cycles_unknown_paths_and_invalid_witnesses():
    cs = [B(0,1,0), B(1,0,-1)]
    report = reduce_bounds(cs, 2)
    assert report["status"] == "inconsistent_context" and not report["reduced"]
    assert sum(cs[i].bound for i in report["negative_cycle"]) < 0
    assert closure([B(0,1,1)], 3)["paths"][1][2] is None
    assert not verify_path([B(0,1,2), B(1,2,3)], B(0,2,4), [0,1])
    assert not verify_path(cs, B(0,0,0), [1,0])
    assert not verify_path(cs, B(0,1,0), [True])
    with pytest.raises(ValueError): B(True,0,1)
    with pytest.raises(ValueError): closure([B(0,2,1)],2)
    with pytest.raises(ValueError): implication_obligation(cs, B(0,1,0), [9])


def test_difference_curriculum_carries_checked_support_and_train_split_is_fixed():
    from jevops.rewrite_distillation import difference_rows
    rows = difference_rows(123)
    assert rows[0] == difference_rows(456)[0]
    for row in rows:
        cs = [B(**c) for c in row["constraints"]]
        cert = row["certificate"]
        assert verify_path(cs, cs[cert["removed_index"]], cert["path"])
        assert row["strategies"] == ["arithmetic_linear"]
        assert "h2" not in row["source"]  # The removed bound is not assumed to prove itself.


@pytest.mark.skipif(shutil.which("lean") is None, reason="requires Lean")
def test_real_lean_checks_difference_paths_not_oracle_claims(tmp_path):
    cs = [B(0,1,2), B(1,2,3), B(0,2,7), B(0,1,2), B(2,2,0)]
    result = reduce_bounds(cs,3)
    source = "\n".join(implication_obligation(cs,cs[c["removed_index"]],c["path"],name=f"diff_{i}")
                         for i,c in enumerate(result["certificates"]))
    receipt = _lean_compiler(project_root=tmp_path,kernel_only=True)(source)
    assert receipt["theorem_ok"] and receipt["kernel_audit"]["accepted"],receipt
