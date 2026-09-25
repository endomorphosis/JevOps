"""Reporting fixtures; never native or model measurements."""
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

TOOL = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/audit_repair_lab.py"
spec = importlib.util.spec_from_file_location("repair_audit", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def interrupted(tmp_path):
    run, src = tmp_path / "run", tmp_path / "source"
    run.mkdir()
    src.mkdir()
    code = src / "sample.py"
    code.write_text("pass\n")
    (run / "plan.json").write_text(json.dumps({"plan_id": "fixture", "implementation": {"sample.py": module.digest(code)}}))
    with sqlite3.connect(run / "calls.sqlite") as db:
        db.execute("CREATE TABLE calls (id TEXT,kind TEXT,tokens INTEGER,native INTEGER,result TEXT)")
        db.execute("INSERT INTO calls VALUES ('control-1','native',0,1,?)", (json.dumps({"outcome": "VERIFIED"}),))
        db.execute("INSERT INTO calls VALUES ('control-2','native',0,1,NULL)")
    return run, src


def test_missing_receipt_stays_unknown_and_artifacts_untouched(interrupted):
    run, src = interrupted
    before = {p: module.digest(p) for p in run.iterdir()}
    result = module.audit(run, src)
    assert result["completion_recorded"] is None and not result["completion_report_present"]
    assert result["native_requests_reserved"] == 2 and result["model_calls_reserved"] == 0
    assert result["unfinished_reservations"] == 1 and result["calls"][1]["recorded_outcome"] is None
    assert not result["implementation_drift_at_audit"] and not result["recovered_receipts"]
    assert result["official_score"] is None and not result["comparison_established"]
    assert before == {p: module.digest(p) for p in run.iterdir()}


def test_reports_drift_without_recovering_or_rescoring(interrupted):
    run, src = interrupted
    (src / "sample.py").write_text("changed = True\n")
    result = module.audit(run, src)
    assert [x["path"] for x in result["implementation_drift_at_audit"]] == ["sample.py"]
    assert result["unfinished_reservations"] == 1 and result["completion_recorded"] is None


def test_output_is_exclusive(interrupted, tmp_path):
    run, src = interrupted
    output = tmp_path / "audit.json"
    args = ["--run-directory", str(run), "--source", str(src), "--output", str(output)]
    assert module.main(args) == 0
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        module.main(args)
    assert output.read_bytes() == original
