from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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
