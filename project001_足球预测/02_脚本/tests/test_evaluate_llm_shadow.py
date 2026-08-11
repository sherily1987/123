import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from evaluate_llm_shadow import evaluate_payload


MODEL_POOL = [
    "zhipu/glm-4-flash",
    "qwen/qwen-flash",
    "deepseek/deepseek-chat",
    "moonshot/kimi-k2.6",
]


def record(**overrides):
    value = {
        "match_id": "m-1",
        "cohort_key": "pool-v1",
        "model_id": "zhipu/glm-4-flash",
        "prediction_identity": {"snapshot": "s-1", "route": "shadow_llm"},
        "prediction": {"direction": "H", "json_valid": True},
        "result": {
            "status": "finished",
            "settlement_scope": "90min",
            "source_provenance_class": "official_formal",
            "score_90": {"home": 1, "away": 0},
        },
    }
    value.update(overrides)
    return value


def test_under_30_reports_only_guarded_quality_metrics_and_no_winner():
    report = evaluate_payload({"records": [record()]})
    cohort = report["cohorts"]["pool-v1"]

    assert report["status"] == "collecting"
    assert report["production_quant_route"] == "MARKET_BASELINE/market_only"
    assert report["formal_banker_count"] == 0
    assert cohort["included_records"] == 1
    assert cohort["stage"] == "under_30_quality_only"
    assert cohort["metrics"]["json_failure_rate"] == 0.0
    assert cohort["metrics"]["evidence_rejection_rate"] == 0.0
    assert cohort["winner_conclusion"] is None
    assert cohort["model_weight_adjustment"] is None
    assert cohort["production_weight_change_conclusion"] is None


def test_only_formal_or_complete_user_confirmed_90min_results_are_included():
    accepted_user = record(
        match_id="m-2",
        model_id="qwen/qwen-flash",
        result={
            "status": "finished",
            "settlement_scope": "90min",
            "source_provenance_class": "user_confirmed_official",
            "verified_by": "user_confirmed_official_sporttery_result",
            "verification_note": "用户确认体彩官方90分钟赛果",
            "evidence_reference": "official-ticket-2",
            "score_90": {"home": 0, "away": 0},
        },
    )
    rejected_extra_time = record(
        match_id="m-3",
        result={
            "status": "finished after extra time",
            "settlement_scope": "90min",
            "source_provenance_class": "official_formal",
            "score_90": {"home": 1, "away": 1},
        },
    )
    report = evaluate_payload({"records": [record(), accepted_user, rejected_extra_time]})
    cohort = report["cohorts"]["pool-v1"]

    assert cohort["included_records"] == 2
    assert cohort["excluded_records"] == 1
    assert cohort["exclusions"][0]["reason"] == "non_ordinary_90min_status"
    assert cohort["identities"]["qwen/qwen-flash"]["included"] == 1


def test_missing_fields_are_null_and_cli_reads_explicit_input_only(tmp_path):
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps({"records": [record(prediction={})]}), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" / "evaluate_llm_shadow.py"), str(input_path), str(output_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(output_path.read_text(encoding="utf-8"))
    cohort = report["cohorts"]["pool-v1"]

    assert completed.stdout == ""
    assert cohort["metrics"]["model_disagreement_rate"] is None
    assert cohort["metrics"]["collapse_rate"] is None
    assert cohort["identities"]["zhipu/glm-4-flash"]["prediction_identity"] == {"snapshot": "s-1", "route": "shadow_llm"}
    assert not (tmp_path / "history").exists()


def test_rejects_input_without_records_list():
    with pytest.raises(ValueError, match="records"):
        evaluate_payload({})
