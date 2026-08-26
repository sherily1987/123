from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import probability_replay_check as replay_check
import signature_drift_governance as governance
import release_governance


OLD_SIG = "b" * 64
CURRENT = {"model_version": "m4", "probability_signature": "a" * 64}
FIELDS = replay_check.COMPARE_FIELDS


def record(match_id: str, *, route: str = "market_only", input_ok: bool = True) -> dict:
    """Minimal registered prediction record with an immutable registered route."""
    payload = {
        "match_id": match_id,
        "home": "Home",
        "away": "Away",
        "competition": "League",
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
        "match": {"home": "Home", "away": "Away", "competition": "League",
                  "kickoff": "2026-09-01T12:00:00Z"},
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
        ("m4", ("string", f'"{OLD_SIG}"'), "market_only"),
        ("m4", ("string", f'"{OLD_SIG}"'), "hybrid"),
    }


@pytest.mark.parametrize("signature", ["", "b" * 12, "z" * 64])
def test_invalid_or_truncated_signature_makes_the_whole_group_unreplayable(monkeypatch, signature):
    rows = [record("m-1"), record("m-2")]
    for row in rows:
        row["model"]["probability_signature"] = signature
    monkeypatch.setattr(governance, "replay_one", lambda row: identical_result(row))

    report = governance.evaluate_group(rows, current_identity=CURRENT)

    assert report["status"] == "UNREPLAYABLE"
    assert {item["status"] for item in report["results"]} == {"UNREPLAYABLE"}
    assert report["alias_eligible"] is False


def test_grouped_numeric_signature_makes_every_member_unreplayable_without_replay(monkeypatch):
    numeric_signature = int("1" * 64)
    rows = [record("m-1"), record("m-2")]
    for row in rows:
        row["model"]["probability_signature"] = numeric_signature
    monkeypatch.setattr(governance, "replay_one", lambda _row: pytest.fail("must not replay"))

    groups = governance.group_records(rows)
    report = governance.evaluate_group(next(iter(groups.values())), current_identity=CURRENT)

    assert set(groups) == {
        ("m4", ("integer", str(numeric_signature)), "market_only"),
    }
    assert report["status"] == "UNREPLAYABLE"
    assert [item["status"] for item in report["results"]] == ["UNREPLAYABLE", "UNREPLAYABLE"]
    assert {item["time_audit"]["reason"] for item in report["results"]} == {
        "probability_signature_invalid"
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


@pytest.mark.parametrize(
    ("field", "input_value"),
    [
        ("match_id", None),
        ("home", None),
        ("away", None),
        ("competition", None),
        ("kickoff", None),
        ("prediction_as_of", "2026-09-01T10:00:00"),
    ],
)
def test_replay_requires_complete_timezone_aware_registered_and_input_identity(
        monkeypatch, field, input_value):
    row = record("m-1")
    if field == "prediction_as_of":
        row["input"][field] = input_value
    else:
        row["input"].pop(field, None) if input_value is None else row["input"].__setitem__(field, input_value)
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    result = replay_check.replay_one(row)

    assert result["status"] == "UNREPLAYABLE"
    assert result["time_audit"]["usable"] is False


def test_replay_requires_registered_prediction_time_to_equal_stored_input(monkeypatch):
    row = record("m-1")
    row["input"]["prediction_as_of"] = "2026-09-01T09:59:00Z"
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    result = replay_check.replay_one(row)

    assert result["status"] == "UNREPLAYABLE"
    assert result["time_audit"]["reason"] == "prediction_as_of_mismatch"


def test_legacy_build_report_still_validates_as_a_complete_equivalent_attestation(monkeypatch, tmp_path):
    row = record("m-1")
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_text(json.dumps(row), encoding="utf-8")
    (tmp_path / "registry.jsonl").write_text(json.dumps({"path": str(prediction_path)}) + "\n",
                                                encoding="utf-8")
    monkeypatch.setattr(replay_check, "build_identity", lambda: CURRENT)
    monkeypatch.setattr(replay_check, "replay_one", lambda item: identical_result(item))

    report = replay_check.build_report(tmp_path, "m4")
    validated = release_governance.validate_replay_attestation(
        report,
        previous_lock={"model_version": "m4", "probability_signature": OLD_SIG},
        current_identity=CURRENT,
    )

    assert report["verdict"] == "equivalent"
    assert report["replayed_probability_signatures"] == [OLD_SIG]
    assert report["replayed_modes"] == ["market_only"]
    assert validated["replay_verdict"] == "equivalent"


def test_legacy_build_report_fails_closed_for_invalid_record_signature(monkeypatch, tmp_path):
    row = record("m-1")
    row["model"]["probability_signature"] = "b" * 12
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_text(json.dumps(row), encoding="utf-8")
    (tmp_path / "registry.jsonl").write_text(json.dumps({"path": str(prediction_path)}) + "\n",
                                                encoding="utf-8")
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    report = replay_check.build_report(tmp_path, "m4")

    assert report["verdict"] == "inconclusive"
    assert report["counts"] == {"UNREPLAYABLE": 1}
    assert report["results"][0]["time_audit"]["reason"] == "probability_signature_invalid"


def test_numeric_json_signature_is_invalid_even_when_its_decimal_text_has_64_digits(monkeypatch, tmp_path):
    row = record("m-1")
    row["model"]["probability_signature"] = int("1" * 64)
    prediction_path = tmp_path / "prediction.json"
    prediction_path.write_text(json.dumps(row), encoding="utf-8")
    (tmp_path / "registry.jsonl").write_text(json.dumps({"path": str(prediction_path)}) + "\n",
                                                encoding="utf-8")
    monkeypatch.setattr(replay_check, "_run_replay", lambda _payload: pytest.fail("must not replay"))

    report = replay_check.build_report(tmp_path, "m4")

    assert report["results"][0]["status"] == "UNREPLAYABLE"
    assert report["results"][0]["time_audit"]["reason"] == "probability_signature_invalid"


def test_limited_legacy_report_does_not_claim_coverage_for_unreplayed_signature(monkeypatch, tmp_path):
    second_sig = "c" * 64
    first, second = record("m-1"), record("m-2", route="hybrid")
    second["model"]["probability_signature"] = second_sig
    paths = []
    for index, row in enumerate((first, second)):
        path = tmp_path / f"prediction-{index}.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        paths.append({"path": str(path)})
    (tmp_path / "registry.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in paths), encoding="utf-8")
    monkeypatch.setattr(replay_check, "build_identity", lambda: CURRENT)
    monkeypatch.setattr(replay_check, "replay_one", lambda item: identical_result(item))

    report = replay_check.build_report(tmp_path, "m4", limit=1)

    assert report["replayed_probability_signatures"] == [OLD_SIG]
    assert report["replayed_modes"] == ["market_only"]
    with pytest.raises(release_governance.ReleaseGovernanceError, match="不完整|未覆盖"):
        release_governance.validate_replay_attestation(
            report,
            previous_lock={"model_version": "m4", "probability_signature": second_sig},
            current_identity=CURRENT,
        )


def test_limited_report_with_same_signature_and_route_is_explicitly_partial_and_rejected(
        monkeypatch, tmp_path):
    first, second = record("m-1"), record("m-2")
    entries = []
    for index, row in enumerate((first, second)):
        path = tmp_path / f"prediction-{index}.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        entries.append({"path": str(path)})
    (tmp_path / "registry.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    monkeypatch.setattr(replay_check, "build_identity", lambda: CURRENT)
    monkeypatch.setattr(replay_check, "replay_one", lambda item: identical_result(item))

    report = replay_check.build_report(tmp_path, "m4", limit=1)

    assert report["records_total"] == 2
    assert report["records_selected"] == 1
    assert report["is_complete_replay"] is False
    assert report["verdict"] == "partial"
    with pytest.raises(release_governance.ReleaseGovernanceError, match="不完整"):
        release_governance.validate_replay_attestation(
            report,
            previous_lock={"model_version": "m4", "probability_signature": OLD_SIG},
            current_identity=CURRENT,
        )


def test_complete_multi_record_report_remains_valid_for_release_governance(monkeypatch, tmp_path):
    first, second = record("m-1"), record("m-2")
    entries = []
    for index, row in enumerate((first, second)):
        path = tmp_path / f"prediction-{index}.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        entries.append({"path": str(path)})
    (tmp_path / "registry.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    monkeypatch.setattr(replay_check, "build_identity", lambda: CURRENT)
    monkeypatch.setattr(replay_check, "replay_one", lambda item: identical_result(item))

    report = replay_check.build_report(tmp_path, "m4")
    validated = release_governance.validate_replay_attestation(
        report,
        previous_lock={"model_version": "m4", "probability_signature": OLD_SIG},
        current_identity=CURRENT,
    )

    assert report["is_complete_replay"] is True
    assert report["verdict"] == "equivalent"
    assert validated["replay_verdict"] == "equivalent"


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


def test_mixed_raw_signature_types_write_distinct_safe_attestations_without_invalid_replay(
        monkeypatch, tmp_path):
    valid_signature = "1" * 64
    raw_signatures = [
        valid_signature,
        int(valid_signature),
        {"raw": "bad/signature:object"},
        ["bad/signature:list"],
        "bad/signature:stream",
    ]
    rows = []
    for index, signature in enumerate(raw_signatures):
        for member in range(2):
            row = record(f"m-{index}-{member}")
            row["model"]["probability_signature"] = signature
            rows.append(row)
    replayed = []

    def replay_valid_signature_only(item):
        signature = item["model"]["probability_signature"]
        if type(signature) is not str or signature != valid_signature:
            pytest.fail("invalid signature groups must not call replay")
        replayed.append(item["match_id"])
        return identical_result(item)

    monkeypatch.setattr(governance, "load_registered_records", lambda _root: rows)
    monkeypatch.setattr(governance, "replay_one", replay_valid_signature_only)

    reports = governance.build_drift_attestations(tmp_path, CURRENT)

    assert len(reports) == len(raw_signatures)
    assert replayed == ["m-0-0", "m-0-1"]
    assert sum(report["status"] == "PENDING_REVIEW" for report in reports) == 1
    assert sum(report["status"] == "UNREPLAYABLE" for report in reports) == 4
    assert all(report["record_count"] == 2 for report in reports)
    assert all(
        [result["status"] for result in report["results"]] ==
        (["identical"] * 2 if report["status"] == "PENDING_REVIEW"
         else ["UNREPLAYABLE"] * 2)
        for report in reports
    )

    paths = [Path(report["attestation_path"]) for report in reports]
    assert len({path.name for path in paths}) == len(raw_signatures)
    assert len({path.parent for path in paths}) == 1
    assert all(re.fullmatch(r"signature-drift-[0-9a-f]{64}\.json", path.name)
               for path in paths)
    assert all(path.is_file() for path in paths)

    persisted_raw_signatures = [
        json.loads(path.read_text(encoding="utf-8"))["old_identity"]["probability_signature"]
        for path in paths
    ]
    for original in raw_signatures:
        assert any(type(persisted) is type(original) and persisted == original
                   for persisted in persisted_raw_signatures)


def test_corrupt_signature_path_characters_cannot_escape_attestation_directory(
        monkeypatch, tmp_path):
    row = record("m-unsafe")
    row["model"]["probability_signature"] = "bad/signature:stream"
    monkeypatch.setattr(governance, "load_registered_records", lambda _root: [row])
    monkeypatch.setattr(governance, "replay_one", lambda _row: pytest.fail("must not replay"))

    report = governance.build_drift_attestations(tmp_path, CURRENT)[0]

    path = Path(report["attestation_path"])
    expected_dir = tmp_path / "signature-drift-attestations" / path.parent.name
    assert path.parent == expected_dir
    assert re.fullmatch(r"signature-drift-[0-9a-f]{64}\.json", path.name)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["old_identity"] == {
        "model_version": "m4",
        "probability_signature": "bad/signature:stream",
    }
