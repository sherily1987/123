from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probability_replay_check as replay_check
import signature_drift_governance as governance


OLD_SIG = "b" * 64
CURRENT = {"model_version": "m4", "probability_signature": "a" * 64}
FIELDS = replay_check.COMPARE_FIELDS


def record(match_id: str, *, route: str = "market_only", input_ok: bool = True) -> dict:
    """Minimal registered prediction record with an immutable registered route."""
    payload = {
        "match_id": match_id,
        "home": "Home",
        "away": "Away",
        "kickoff": "2026-09-01T12:00:00Z",
        "prediction_as_of": "2026-09-01T10:00:00Z",
        "mode": route,
    } if input_ok else None
    return {
        "match_id": match_id,
        "kickoff": "2026-09-01T12:00:00Z",
        "prediction_as_of": "2026-09-01T10:00:00Z",
        "mode": route,
        "input": payload,
        "output": {},
        "model": {"model_version": "m4", "probability_signature": OLD_SIG},
    }


def identical_result(row: dict) -> dict:
    return {
        "match_id": row["match_id"],
        "status": "identical",
        "route": row["mode"],
        "prediction_as_of": row["prediction_as_of"],
        "input_sha256": "1" * 64,
        "diffs": {},
        "time_audit": {"usable": True, "reason": None},
    }


def test_drift_group_is_unreplayable_when_one_member_lacks_input(monkeypatch):
    rows = [record("m-1"), record("m-2", input_ok=False)]
    monkeypatch.setattr(governance, "replay_one", lambda row: identical_result(row))

    report = governance.evaluate_group(rows, current_identity=CURRENT)

    assert report["status"] == "UNREPLAYABLE"
    assert report["alias_eligible"] is False


def test_route_is_part_of_group_identity():
    groups = governance.group_records([
        record("m-1", route="market_only"),
        record("m-2", route="hybrid"),
    ])

    assert set(groups) == {
        ("m4", OLD_SIG, "market_only"),
        ("m4", OLD_SIG, "hybrid"),
    }


def test_equivalent_group_stays_pending_review_and_never_alias_eligible(monkeypatch):
    rows = [record("m-1"), record("m-2")]
    monkeypatch.setattr(governance, "replay_one", lambda row: identical_result(row))

    report = governance.evaluate_group(rows, current_identity=CURRENT)

    assert report["status"] == "PENDING_REVIEW"
    assert report["alias_eligible"] is False
    assert report["old_identity"] == {"model_version": "m4", "probability_signature": OLD_SIG}
    assert report["route"] == "market_only"


def test_any_replay_difference_requires_a_version_bump(monkeypatch):
    row = record("m-1")
    changed = identical_result(row)
    changed["status"] = "differs"
    changed["diffs"] = {"score_matrix": {"recorded": [[1]], "replayed": [[2]]}}
    monkeypatch.setattr(governance, "replay_one", lambda _row: changed)

    report = governance.evaluate_group([row], current_identity=CURRENT)

    assert report["status"] == "CHANGED_REQUIRES_VERSION_BUMP"
    assert report["alias_eligible"] is False


@pytest.mark.parametrize("field", FIELDS)
def test_replay_compares_every_required_output_field(monkeypatch, field):
    row = record("m-1")
    recorded = {name: {"value": 1.0} for name in FIELDS}
    replayed = {name: {"value": 1.0} for name in FIELDS}
    replayed[field] = {"value": 2.0}
    row["output"] = recorded
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: replayed)

    result = replay_check.replay_one(row)

    assert result["status"] == "differs"
    assert set(result["diffs"]) == {field}


def test_replay_rejects_missing_required_output_field(monkeypatch):
    row = record("m-1")
    row["output"] = {name: 0.1 for name in FIELDS}
    replayed = dict(row["output"])
    replayed.pop("btts")
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: replayed)

    result = replay_check.replay_one(row)

    assert result["status"] == "differs"
    assert "btts" in result["diffs"]


def test_replay_accepts_floats_only_within_fixed_tolerance(monkeypatch):
    row = record("m-1")
    row["output"] = {name: 1.0 for name in FIELDS}
    replayed = {name: 1.0 + 5e-11 for name in FIELDS}
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: replayed)

    result = replay_check.replay_one(row)

    assert result["status"] == "identical"
    assert result["diffs"] == {}


def test_replay_rejects_evidence_collected_after_prediction_as_of(monkeypatch):
    row = record("m-1")
    row["input"]["field_meta"] = {
        "injury": {"observed_at": "2026-09-01T10:01:00Z"},
    }
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    result = replay_check.replay_one(row)

    assert result["status"] == "UNREPLAYABLE"
    assert result["time_audit"]["reason"] == "evidence_after_prediction_as_of"


def test_replay_rejects_registered_team_identity_that_disagrees_with_input(monkeypatch):
    row = record("m-1")
    row["match"] = {"home": "Different Home", "away": "Away", "competition": "League",
                    "kickoff": "2026-09-01T12:00:00Z"}
    row["input"]["competition"] = "League"
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    result = replay_check.replay_one(row)

    assert result["status"] == "UNREPLAYABLE"
    assert result["time_audit"]["reason"] == "home_team_mismatch"


def test_attestation_write_is_read_only_and_hashes_its_canonical_content(monkeypatch, tmp_path):
    row = record("m-1")
    monkeypatch.setattr(governance, "load_registered_records", lambda _root: [row])
    monkeypatch.setattr(governance, "replay_one", lambda item: identical_result(item))

    reports = governance.build_drift_attestations(tmp_path, CURRENT)

    assert len(reports) == 1
    report = reports[0]
    attestation = Path(report["attestation_path"])
    persisted = json.loads(attestation.read_text(encoding="utf-8"))
    expected = hashlib.sha256(
        governance.canonical_json(report["report_hash_input"]).encode("utf-8")
    ).hexdigest()
    assert report["status"] == "PENDING_REVIEW"
    assert report["report_sha256"] == expected
    assert persisted["report_sha256"] == expected
    assert not (tmp_path / "registry.jsonl").exists()
