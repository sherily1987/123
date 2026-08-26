from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

direction_policy = importlib.import_module("direction_policy")
fusion_predict = importlib.import_module("fusion_predict")


def _times(*, snapshot_offset_hours: int = 0) -> tuple[str, str]:
    kickoff = datetime.now(timezone.utc) + timedelta(days=3)
    prediction_as_of = kickoff - timedelta(hours=12 - snapshot_offset_hours)
    return kickoff.isoformat(), prediction_as_of.isoformat()


def _input(kickoff: str, prediction_as_of: str, *, match_id: str = "direction-test") -> dict:
    return {
        "home": "Home",
        "away": "Away",
        "competition": "Test League",
        "stage": "Test",
        "kickoff": kickoff,
        "prediction_as_of": prediction_as_of,
        "mode": "market_only",
        "route": "market_only",
        "sporttery_meta": {"match_id": match_id},
    }


def _valid_output(prediction_as_of: str, probabilities: list[float] | None = None) -> dict:
    probabilities = probabilities or [55.0, 25.0, 20.0]
    identity = fusion_predict._core.build_identity()
    release_identity = json.loads(
        (SKILL_ROOT / "config" / "release_lock.json").read_text(encoding="utf-8-sig")
    )
    identity.update({
        "model_version": release_identity["model_version"],
        "probability_signature": release_identity["probability_signature"],
    })
    policy = direction_policy.build_direction_policy(
        probabilities,
        prediction_as_of=prediction_as_of,
        model_identity=identity,
        policy=direction_policy.load_policy(),
    )
    return {
        "fusion_status": "ok",
        "research_only": False,
        "build_identity": identity,
        "core_engine_version": identity["core_version"],
        "final_1x2_pct": probabilities,
        "direction_policy": policy,
    }


def _write_payloads(root: Path, inp: dict, out: dict) -> tuple[Path, Path]:
    input_path = root / "input.json"
    output_path = root / "output.json"
    input_path.write_text(json.dumps(inp), encoding="utf-8")
    output_path.write_text(json.dumps(out), encoding="utf-8")
    return input_path, output_path


def _run_record(root: Path, inp: dict, out: dict, *, snapshot: str = "prematch",
                replace_snapshot: bool = False,
                allow_past: bool = False) -> subprocess.CompletedProcess[str]:
    input_path, output_path = _write_payloads(root, inp, out)
    command = [
        sys.executable,
        str(SCRIPTS / "fusion_record.py"),
        "--input", str(input_path),
        "--output", str(output_path),
        "--store", str(root / "store"),
        "--snapshot", snapshot,
    ]
    if replace_snapshot:
        command.append("--replace-snapshot")
    if allow_past:
        command.append("--allow-past")
    return subprocess.run(command, text=True, capture_output=True)


def _records(root: Path) -> list[dict]:
    entries = [
        json.loads(line)
        for line in (root / "store" / "registry.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return [json.loads(Path(entry["path"]).read_text(encoding="utf-8")) for entry in entries]


def _direction_policies(value) -> list[dict]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "direction_policy" and isinstance(child, dict):
                found.append(child)
            found.extend(_direction_policies(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_direction_policies(child))
    return found


def test_new_formal_prediction_attaches_policy_without_changing_probabilities(monkeypatch):
    _, prediction_as_of = _times()
    identity = fusion_predict._core.build_identity()
    probabilities = [39.4, 29.8, 30.8]
    core_output = {"final_1x2_pct": list(probabilities)}
    bare = {
        "fusion_status": "ok",
        "research_only": False,
        "build_identity": identity,
        "forecast": {"final_1x2_pct": list(probabilities)},
        "core_output": core_output,
    }
    monkeypatch.setattr(fusion_predict, "_core_predict_one", lambda *_args: copy.deepcopy(bare))

    result = fusion_predict.predict_one(object(), "test", {"prediction_as_of": prediction_as_of})

    assert result["forecast"]["final_1x2_pct"] == probabilities
    assert result["core_output"]["final_1x2_pct"] == probabilities
    assert result["direction_policy"]["rule_version"] == "direction-policy-v1"
    assert result["direction_policy"]["activation_timestamp"] == "2026-08-26T11:16:27+08:00"
    assert result["direction_policy"]["probabilities"] == {
        "H": 39.4, "D": 29.8, "A": 30.8,
    }
    assert result["core_output"]["direction_policy"] == result["direction_policy"]


@pytest.mark.parametrize("research_only,fusion_status", [(True, "ok"), (False, "blocked")])
def test_nonformal_prediction_does_not_attach_policy(monkeypatch, research_only, fusion_status):
    _, prediction_as_of = _times()
    bare = {
        "fusion_status": fusion_status,
        "research_only": research_only,
        "build_identity": fusion_predict._core.build_identity(),
        "forecast": {"final_1x2_pct": [55.0, 25.0, 20.0]},
        "core_output": {"final_1x2_pct": [55.0, 25.0, 20.0]},
    }
    monkeypatch.setattr(fusion_predict, "_core_predict_one", lambda *_args: copy.deepcopy(bare))

    result = fusion_predict.predict_one(object(), "test", {"prediction_as_of": prediction_as_of})

    assert "direction_policy" not in result
    assert "direction_policy" not in result["core_output"]


def test_policy_generation_failure_keeps_probability_output_and_clears_directions(monkeypatch):
    _, prediction_as_of = _times()
    probabilities = [55.0, 25.0, 20.0]
    bare = {
        "fusion_status": "ok",
        "research_only": False,
        "build_identity": fusion_predict._core.build_identity(),
        "forecast": {"final_1x2_pct": list(probabilities)},
        "core_output": {"final_1x2_pct": list(probabilities)},
    }
    monkeypatch.setattr(fusion_predict, "_core_predict_one", lambda *_args: copy.deepcopy(bare))
    monkeypatch.setattr(
        fusion_predict, "_load_direction_policy_module",
        lambda: (_ for _ in ()).throw(ValueError("policy missing")),
    )

    result = fusion_predict.predict_one(object(), "test", {"prediction_as_of": prediction_as_of})

    assert result["forecast"]["final_1x2_pct"] == probabilities
    unavailable = result["direction_policy"]
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["classification"] == "UNAVAILABLE"
    assert unavailable["primary_direction"] is None
    assert unavailable["alternative_direction"] is None
    assert unavailable["reason"] == "validation_error"
    assert unavailable["validation_error"] == "direction_policy_import_failed:ValueError"


def test_direction_module_import_failure_never_blocks_base_probability(monkeypatch, tmp_path):
    _, prediction_as_of = _times()
    probabilities = [55.0, 25.0, 20.0]
    bare = {
        "fusion_status": "ok",
        "research_only": False,
        "build_identity": fusion_predict._core.build_identity(),
        "forecast": {"final_1x2_pct": list(probabilities)},
        "core_output": {"final_1x2_pct": list(probabilities)},
    }
    monkeypatch.setattr(fusion_predict, "_core_predict_one", lambda *_args: copy.deepcopy(bare))
    monkeypatch.setattr(fusion_predict, "_DIRECTION_POLICY_FILE", tmp_path / "missing.py")

    result = fusion_predict.predict_one(object(), "test", {"prediction_as_of": prediction_as_of})

    assert result["forecast"]["final_1x2_pct"] == probabilities
    assert result["direction_policy"]["status"] == "UNAVAILABLE"
    assert result["direction_policy"]["primary_direction"] is None
    assert result["direction_policy"]["alternative_direction"] is None
    assert result["direction_policy"]["validation_error"].startswith(
        "direction_policy_import_failed:"
    )


def test_prematch_record_contains_validated_direction_policy(tmp_path):
    kickoff, prediction_as_of = _times()
    inp = _input(kickoff, prediction_as_of)
    out = _valid_output(prediction_as_of)

    result = _run_record(tmp_path, inp, out)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    assert recorded["direction_policy_status"] == "REGISTERED"
    assert recorded["direction_policy"] == out["direction_policy"]
    assert recorded["direction_policy"]["rule_version"] == "direction-policy-v1"


def test_policy_config_has_aware_task4_activation_timestamp():
    policy = json.loads(
        (SKILL_ROOT / "config" / "direction_policy.json").read_text(encoding="utf-8-sig")
    )

    activation = datetime.fromisoformat(policy["activation_timestamp"])

    assert policy["activation_timestamp"] == "2026-08-26T11:16:27+08:00"
    assert activation.tzinfo is not None
    assert activation.utcoffset() is not None


def test_legacy_output_before_policy_activation_is_not_backfilled(tmp_path):
    kickoff = "2026-08-27T20:00:00+08:00"
    prediction_as_of = "2026-08-26T11:16:26+08:00"
    inp = _input(kickoff, prediction_as_of)
    out = _valid_output(prediction_as_of)
    del out["direction_policy"]

    result = _run_record(tmp_path, inp, out, allow_past=True)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    assert recorded["direction_policy_status"] == "NOT_REGISTERED"
    assert "direction_policy" not in recorded


@pytest.mark.parametrize("prediction_as_of", [
    "2026-08-26T11:16:27+08:00",
    "2026-08-26T11:16:28+08:00",
])
def test_current_output_missing_policy_is_unavailable_not_legacy(tmp_path, prediction_as_of):
    kickoff = "2026-08-27T20:00:00+08:00"
    inp = _input(kickoff, prediction_as_of, match_id=f"missing-{prediction_as_of[-8:]}")
    out = _valid_output(prediction_as_of)
    del out["direction_policy"]

    result = _run_record(tmp_path, inp, out, allow_past=True)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    assert recorded["direction_policy_status"] == "UNAVAILABLE"
    assert recorded["direction_policy"]["status"] == "UNAVAILABLE"
    assert recorded["direction_policy"]["reason"] == "validation_error"
    assert recorded["direction_policy"]["validation_error"] == "direction_policy_missing_after_activation"
    assert recorded["direction_policy"]["primary_direction"] is None
    assert recorded["direction_policy"]["alternative_direction"] is None
    assert recorded["output"]["direction_policy"] == recorded["direction_policy"]


@pytest.mark.parametrize(
    "mutation,expected_error",
    [
        (lambda policy, out, inp: policy["probabilities"].update(H=54.0), "probabilities_mismatch"),
        (lambda policy, out, inp: policy.update(model_version="m999"), "model_identity_mismatch"),
        (lambda policy, out, inp: policy.update(prediction_as_of=(
            datetime.fromisoformat(inp["prediction_as_of"]) + timedelta(seconds=1)
        ).isoformat()), "prediction_as_of_mismatch"),
        (lambda policy, out, inp: policy.update(schema_version="direction-policy-0.0"), "schema_version_mismatch"),
        (lambda policy, out, inp: policy.update(unregistered_extension=True), "schema_fields_mismatch"),
        (lambda policy, out, inp: policy.update(non_finite_extension=float("nan")), "schema_fields_mismatch"),
        (lambda policy, out, inp: policy.update(rule_version="direction-policy-v0"), "rule_version_mismatch"),
        (lambda policy, out, inp: policy.update(decision_policy_signature="0" * 64), "decision_policy_signature_mismatch"),
        (lambda policy, out, inp: policy["decision_policy_signature_components"].update(
            implementation_sha256="0" * 64
        ), "decision_policy_signature_components_mismatch"),
        (lambda policy, out, inp: policy.update(classification="PRIMARY_WITH_COVER"), "classification_mismatch"),
        (lambda policy, out, inp: policy.update(primary_direction="A"), "primary_direction_mismatch"),
    ],
)
def test_invalid_policy_records_probability_snapshot_as_unavailable(
        tmp_path, mutation, expected_error):
    kickoff, prediction_as_of = _times()
    inp = _input(kickoff, prediction_as_of)
    out = _valid_output(prediction_as_of)
    mutation(out["direction_policy"], out, inp)

    result = _run_record(tmp_path, inp, out)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    assert recorded["output"]["final_1x2_pct"] == [55.0, 25.0, 20.0]
    assert recorded["direction_policy_status"] == "UNAVAILABLE"
    unavailable = recorded["direction_policy"]
    assert unavailable["status"] == "UNAVAILABLE"
    assert unavailable["classification"] == "UNAVAILABLE"
    assert unavailable["primary_direction"] is None
    assert unavailable["alternative_direction"] is None
    assert unavailable["reason"] == "validation_error"
    assert unavailable["validation_error"] == expected_error


def test_invalid_policy_is_sanitized_from_every_persisted_nested_copy(tmp_path):
    kickoff, prediction_as_of = _times()
    inp = _input(kickoff, prediction_as_of, match_id="nested-policy-sanitize")
    out = _valid_output(prediction_as_of)
    valid = copy.deepcopy(out["direction_policy"])
    tampered = copy.deepcopy(valid)
    tampered["primary_direction"] = "A"
    out["direction_policy"] = tampered
    out["core_output"] = {"final_1x2_pct": [55.0, 25.0, 20.0],
                          "direction_policy": copy.deepcopy(tampered)}
    out["fusion_full_output"] = {
        "direction_policy": copy.deepcopy(valid),
        "core_output": {"direction_policy": copy.deepcopy(tampered)},
        "results": [{"direction_policy": copy.deepcopy(tampered)}],
    }

    result = _run_record(tmp_path, inp, out)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    policies = _direction_policies(recorded)
    assert len(policies) >= 6
    assert {policy["validation_error"] for policy in policies} == {"primary_direction_mismatch"}
    assert len({policy["rejected_direction_policy_sha256"] for policy in policies}) == 1
    for policy in policies:
        assert policy["status"] == "UNAVAILABLE"
        assert policy["classification"] == "UNAVAILABLE"
        assert policy["primary_direction"] is None
        assert policy["alternative_direction"] is None
    rejection_hash = recorded["direction_policy"]["rejected_direction_policy_sha256"]
    assert len(rejection_hash) == 64
    int(rejection_hash, 16)
    assert recorded["hashes"]["output_raw_sha256"] == hashlib.sha256(
        (tmp_path / "output.json").read_bytes()
    ).hexdigest()
    assert recorded["hashes"]["persisted_output_sha256"] != recorded["hashes"]["output_sha256"]


def test_policy_time_must_be_aware_and_strictly_prematch_without_blocking_probability(tmp_path):
    kickoff, prediction_as_of = _times()
    inp = _input(kickoff, prediction_as_of)
    out = _valid_output(prediction_as_of)
    out["direction_policy"]["prediction_as_of"] = datetime.fromisoformat(kickoff).replace(
        tzinfo=None
    ).isoformat()

    result = _run_record(tmp_path, inp, out)

    assert result.returncode == 0, result.stderr or result.stdout
    recorded = _records(tmp_path)[0]
    assert recorded["direction_policy_status"] == "UNAVAILABLE"
    assert recorded["direction_policy"]["validation_error"] == "prediction_as_of_not_aware_prematch"


def test_distinct_snapshots_keep_independent_immutable_policies_and_duplicates_skip(tmp_path):
    kickoff, first_as_of = _times(snapshot_offset_hours=0)
    _, second_as_of = _times(snapshot_offset_hours=2)
    inp = _input(kickoff, first_as_of, match_id="snapshot-direction-test")
    first = _valid_output(first_as_of, [55.0, 25.0, 20.0])

    first_result = _run_record(tmp_path, inp, first, snapshot="prematch")
    duplicate = _run_record(tmp_path, inp, first, snapshot="prematch")
    inp["prediction_as_of"] = second_as_of
    second = _valid_output(second_as_of, [39.4, 29.8, 30.8])
    second_result = _run_record(tmp_path, inp, second, snapshot="T-10h")

    assert first_result.returncode == 0, first_result.stderr or first_result.stdout
    assert duplicate.returncode == 0, duplicate.stderr or duplicate.stdout
    assert json.loads(duplicate.stdout)["status"] == "skipped_duplicate_snapshot"
    assert second_result.returncode == 0, second_result.stderr or second_result.stdout
    recorded = _records(tmp_path)
    assert len(recorded) == 2
    assert recorded[0]["direction_policy"]["probabilities"] == {
        "H": 55.0, "D": 25.0, "A": 20.0,
    }
    assert recorded[1]["direction_policy"]["probabilities"] == {
        "H": 39.4, "D": 29.8, "A": 30.8,
    }
    assert recorded[0]["direction_policy"]["prediction_as_of"] == first_as_of
    assert recorded[1]["direction_policy"]["prediction_as_of"] == second_as_of


def test_replace_prematch_still_cannot_overwrite_direction_snapshot(tmp_path):
    kickoff, prediction_as_of = _times()
    inp = _input(kickoff, prediction_as_of)
    out = _valid_output(prediction_as_of)

    result = _run_record(tmp_path, inp, out, replace_snapshot=True)

    assert result.returncode != 0
    assert "prematch snapshots are immutable" in result.stderr
