"""Summary arithmetic must not turn unknown usage into zero or award proof credit."""
import importlib.util
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "papers/completion/lean_refactor_arena/tools/report_frozen_schema_pilot.py"
spec = importlib.util.spec_from_file_location("frozen_schema_report", TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_unknown_usage_and_proof_outcome_remain_unknown():
    arm = {"strict_format_attempts": 0, "valid_attempts": 0, "shorter_valid_attempts": 0,
           "tokens_reserved": 100, "tokens_observed": None, "best_valid_tokens": None,
           "trials": [{"step": 0, "status": "GENERATION_OR_ACCOUNTING_FAILED", "all_pin_valid": None,
                       "generation": {"error_category": "http_error", "http_status": 400}}]}
    result = module.arm_summary(arm)
    assert result["tokens_observed"] is None and result["known_model_tokens"] == 0
    assert result["measured_generations"] == 0 and result["attempts_reserved"] == 1
    assert result["trials"][0]["all_pin_valid"] is None and result["valid_attempts"] == 0


def test_test_setup_errors_are_not_counted_as_passes(tmp_path):
    path = tmp_path / "tests.xml"
    path.write_text('<testsuites><testsuite><testcase/><testcase><error/></testcase>'
                    '<testcase><skipped/></testcase></testsuite></testsuites>')
    assert module.tests_summary(path) == {"tests": 3, "errors": 1, "failures": 0, "skipped": 1}
