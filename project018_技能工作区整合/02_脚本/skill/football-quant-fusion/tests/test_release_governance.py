from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("release_governance", SCRIPTS / "release_governance.py")
governance = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(governance)


OLD_SIG = "a" * 64
CURRENT_SIG = "b" * 64


def _identity(signature=CURRENT_SIG):
    return {"model_version": "m4", "probability_signature": signature}


def _attestation(*, fields=None, verdict="equivalent"):
    return {
        "replayed_model_version": "m4",
        "current_identity": _identity(),
        "replayed_probability_signatures": [OLD_SIG],
        "compare_fields": fields if fields is not None else list(governance.REQUIRED_REPLAY_FIELDS),
        "replayed_modes": ["market_only"],
        "counts": {"identical": 2},
        "verdict": verdict,
    }


def _schema_2_attestation(**overrides):
    report = _attestation()
    report.update({
        "schema_version": "fusion-probability-replay-2.0",
        "records_total": 2,
        "records_selected": 2,
        "is_complete_replay": True,
    })
    report.update(overrides)
    return report


def _validate(report):
    return governance.validate_replay_attestation(
        report,
        previous_lock=_identity(OLD_SIG),
        current_identity=_identity(),
    )


def _group_attestation(*, tolerance=1e-10, old_signature=OLD_SIG):
    registered_identity = {
        "match_id": "match-1", "home": "Home", "away": "Away",
        "competition": "League", "kickoff": "2026-09-01T12:00:00Z",
        "prediction_as_of": "2026-09-01T10:00:00Z",
        "model_version": "m4", "probability_signature": old_signature,
        "route": "market_only",
    }
    input_identity = {
        "match_id": "match-1", "home": "Home", "away": "Away",
        "competition": "League", "kickoff": "2026-09-01T12:00:00Z",
        "prediction_as_of": "2026-09-01T10:00:00Z", "route": "market_only",
    }
    result = {
        "match_id": "match-1", "status": "identical", "route": "market_only",
        "prediction_as_of": "2026-09-01T10:00:00Z",
        "input_sha256": "c" * 64, "diffs": {},
        "registered_identity": registered_identity, "input_identity": input_identity,
        "time_audit": {
            "usable": True, "reason": None,
            "registered_prediction_as_of": "2026-09-01T10:00:00Z",
            "input_prediction_as_of": "2026-09-01T10:00:00Z",
            "registered_kickoff": "2026-09-01T12:00:00Z",
            "input_kickoff": "2026-09-01T12:00:00Z",
            "prediction_before_kickoff": True,
            "evidence_after_prediction_as_of": False,
        },
    }
    core = {
        "schema_version": "signature-drift-attestation-1.0",
        "old_identity": {"model_version": "m4", "probability_signature": old_signature},
        "route": "market_only", "current_identity": _identity(),
        "compare_fields": list(governance.REQUIRED_REPLAY_FIELDS),
        "float_tolerance": tolerance, "record_count": 1, "results": [result],
        "status": "PENDING_REVIEW", "alias_eligible": False,
    }
    report = dict(core, report_hash_input=core)
    report["report_sha256"] = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def _validate_group(report):
    return governance.validate_grouped_alias_attestation(
        report, current_identity=_identity())


def _rehash_group(report):
    core = {key: value for key, value in report.items() if key not in {
        "generated_at", "report_sha256", "report_hash_input", "attestation_path",
    }}
    report["report_hash_input"] = core
    report["report_sha256"] = hashlib.sha256(
        json.dumps(core, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def test_grouped_alias_attestation_accepts_complete_identity_and_time_proof():
    validated = _validate_group(_group_attestation())

    assert validated["route"] == "market_only"
    assert validated["probability_signature"] == OLD_SIG


@pytest.mark.parametrize("tolerance", [True, "1e-10", None, 0, 1e-9])
def test_grouped_alias_attestation_requires_exact_float_tolerance(tolerance):
    with pytest.raises(governance.ReleaseGovernanceError, match="容差"):
        _validate_group(_group_attestation(tolerance=tolerance))


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("registered_identity", "home", None),
        ("registered_identity", "probability_signature", "d" * 64),
        ("input_identity", "match_id", "different-match"),
        ("input_identity", "route", "hybrid"),
        ("registered_identity", "prediction_as_of", "2026-09-01T10:00:00"),
        ("input_identity", "kickoff", "2026-09-01T09:00:00Z"),
    ],
)
def test_grouped_alias_attestation_rechecks_immutable_record_and_input_identity(
    section, field, value
):
    report = deepcopy(_group_attestation())
    report["results"][0][section][field] = value
    _rehash_group(report)

    with pytest.raises(governance.ReleaseGovernanceError, match="身份|签名|路由|时间|赛前"):
        _validate_group(report)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("registered_prediction_as_of", "2026-09-01T09:59:00Z"),
        ("input_kickoff", "2026-09-01T13:00:00Z"),
        ("prediction_before_kickoff", False),
        ("evidence_after_prediction_as_of", True),
    ],
)
def test_grouped_alias_attestation_recomputes_time_audit_instead_of_trusting_usable(
    field, value
):
    report = deepcopy(_group_attestation())
    report["results"][0]["time_audit"][field] = value
    _rehash_group(report)

    with pytest.raises(governance.ReleaseGovernanceError, match="时间审计"):
        _validate_group(report)


def test_grouped_alias_attestation_rejects_same_identity_alias():
    with pytest.raises(governance.ReleaseGovernanceError, match="相同身份"):
        _validate_group(_group_attestation(old_signature=CURRENT_SIG))


def test_same_version_signature_transition_requires_complete_equivalent_attestation(tmp_path):
    lock_path = tmp_path / "release_lock.json"
    lock_path.write_text(json.dumps(_identity(OLD_SIG)), encoding="utf-8")
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps(_attestation(fields=["final_1x2_pct"])), encoding="utf-8")

    with pytest.raises(governance.ReleaseGovernanceError, match="比较字段"):
        governance.transition_release_lock(lock_path, _identity(), report_path)


def test_same_version_signature_transition_writes_audited_lock(tmp_path):
    lock_path = tmp_path / "release_lock.json"
    lock_path.write_text(json.dumps(_identity(OLD_SIG)), encoding="utf-8")
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps(_attestation()), encoding="utf-8")

    locked = governance.transition_release_lock(lock_path, _identity(), report_path)

    assert locked["model_version"] == "m4"
    assert locked["probability_signature"] == CURRENT_SIG
    assert locked["replay_attestation"]["previous_probability_signature"] == OLD_SIG
    assert locked["replay_attestation"]["replayed_modes"] == ["market_only"]
    assert json.loads(lock_path.read_text(encoding="utf-8"))["probability_signature"] == CURRENT_SIG


def test_schema_2_complete_full_replay_remains_valid():
    assert _validate(_schema_2_attestation())["replay_verdict"] == "equivalent"


def test_historical_schema_1_complete_replay_remains_valid_without_new_fields():
    report = _attestation()
    report["schema_version"] = "fusion-probability-replay-1.0"

    assert _validate(report)["replay_verdict"] == "equivalent"


@pytest.mark.parametrize("missing_field", [
    "records_total", "records_selected", "is_complete_replay",
])
def test_schema_2_rejects_missing_completeness_field(missing_field):
    report = _schema_2_attestation()
    report.pop(missing_field)

    with pytest.raises(governance.ReleaseGovernanceError, match="不完整"):
        _validate(report)


@pytest.mark.parametrize("field,value", [
    ("records_total", -1),
    ("records_selected", -1),
    ("records_total", True),
    ("records_selected", False),
    ("records_total", 2.0),
    ("records_selected", "2"),
])
def test_schema_2_rejects_tampered_non_negative_integer_counts(field, value):
    with pytest.raises(governance.ReleaseGovernanceError, match="不完整"):
        _validate(_schema_2_attestation(**{field: value}))


def test_schema_2_rejects_unequal_total_and_selected_counts():
    with pytest.raises(governance.ReleaseGovernanceError, match="不完整"):
        _validate(_schema_2_attestation(records_total=2, records_selected=1))


@pytest.mark.parametrize("completion", [False, None, 1, "true"])
def test_schema_2_requires_literal_true_complete_replay(completion):
    with pytest.raises(governance.ReleaseGovernanceError, match="不完整"):
        _validate(_schema_2_attestation(is_complete_replay=completion))


@pytest.mark.parametrize("verdict", ["partial", "limited", "incomplete"])
def test_schema_2_explicitly_rejects_incomplete_verdicts(verdict):
    with pytest.raises(governance.ReleaseGovernanceError, match="不完整"):
        _validate(_schema_2_attestation(verdict=verdict))


def test_same_version_signature_transition_rejects_any_probability_difference(tmp_path):
    lock_path = tmp_path / "release_lock.json"
    lock_path.write_text(json.dumps(_identity(OLD_SIG)), encoding="utf-8")
    report_path = tmp_path / "replay.json"
    report_path.write_text(json.dumps(_attestation(verdict="changed")), encoding="utf-8")

    with pytest.raises(governance.ReleaseGovernanceError, match="数值不等价"):
        governance.transition_release_lock(lock_path, _identity(), report_path)


def test_direct_formal_registration_rejects_output_identity_not_in_release_lock(tmp_path):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    sys.path.insert(0, str(scripts))
    from fusion_predict_core import build_identity

    identity = dict(build_identity(), model_version="m3", probability_signature="c" * 64)
    source = tmp_path / "input.json"
    output = tmp_path / "output.json"
    source.write_text(json.dumps({
        "home": "Home", "away": "Away", "stage": "test",
        "kickoff": "2099-01-01T12:00:00+08:00",
        "prediction_as_of": "2098-12-31T12:00:00+08:00",
        "sporttery_meta": {"match_id": "release-gate-test"},
    }), encoding="utf-8")
    output.write_text(json.dumps({"fusion_status": "ok", "build_identity": identity}), encoding="utf-8")

    completed = subprocess.run([
        sys.executable, str(scripts / "fusion_record.py"), "--input", str(source),
        "--output", str(output), "--store", str(tmp_path / "store"), "--snapshot", "prematch",
    ], text=True, capture_output=True)

    assert completed.returncode != 0
    assert "发布锁" in (completed.stderr or completed.stdout)
    assert not (tmp_path / "store" / "registry.jsonl").exists()
