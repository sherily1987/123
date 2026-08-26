from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import version_progress  # noqa: E402


CURRENT_SIG = "a" * 64
ALIAS_SIG = "b" * 64
DRIFT_SIG = "c" * 64


def _policy(classification, primary, alternative=None):
    return {
        "status": "AVAILABLE",
        "classification": classification,
        "primary_direction": primary,
        "alternative_direction": alternative,
        "prediction_as_of": "2026-09-01T10:00:00+00:00",
    }


def _record(match_id, model_version, signature, route, direction_status, policy):
    return {
        "prediction_id": f"{match_id}__2026-09-01T10:00:00Z__prematch",
        "match_id": match_id,
        "snapshot_type": "prematch",
        "created_at": "2026-09-01T10:00:00+00:00",
        "prediction_as_of": "2026-09-01T10:00:00+00:00",
        "match": {"kickoff": "2026-09-01T12:00:00+00:00"},
        "model": {"model_version": model_version, "probability_signature": signature},
        "input": {"mode": route},
        "direction_policy_status": direction_status,
        **({"direction_policy": policy} if policy is not None else {}),
    }


def _store(root: Path, records):
    (root / "predictions").mkdir(parents=True)
    (root / "results").mkdir()
    registry = []
    for record, result_direction in records:
        path = root / "predictions" / f"{record['match_id']}.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        registry.append({
            "prediction_id": record["prediction_id"], "match_id": record["match_id"],
            "created_at": record["created_at"], "path": str(path),
        })
        if result_direction is not None:
            score = {"H": (2, 0), "D": (1, 1), "A": (0, 2)}[result_direction]
            result = {
                "status": "finished", "settlement_scope": "90min",
                "score_90": {"home": score[0], "away": score[1]},
                "source": {"name": "official"},
            }
            (root / "results" / f"{record['match_id']}.json").write_text(
                json.dumps(result), encoding="utf-8")
    (root / "registry.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in registry), encoding="utf-8")
    (root / "results_registry.jsonl").write_text(
        "".join(json.dumps({"match_id": record["match_id"]}) + "\n"
                for record, result in records if result is not None), encoding="utf-8")


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_governance_report_combines_lock_alias_drift_and_direction_metrics(
        tmp_path, monkeypatch):
    current = _record("raw", "m4", CURRENT_SIG, "market_only", "REGISTERED",
                      _policy("PRIMARY_ONLY", "H"))
    aliased = _record("alias", "m3", ALIAS_SIG, "market_only", "REGISTERED",
                      _policy("PRIMARY_WITH_COVER", "H", "D"))
    drift = _record("drift", "m4", DRIFT_SIG, "hybrid", "NOT_REGISTERED", None)
    _store(tmp_path, [(current, "H"), (aliased, "D"), (drift, "A")])
    lock_path = tmp_path / "release_lock.json"
    lock_path.write_text(json.dumps({
        "model_version": "m4", "probability_signature": CURRENT_SIG,
        "locked_at": "2026-08-26T00:00:00+00:00",
    }), encoding="utf-8")
    recommendation_path = tmp_path / "recommendation_policy.json"
    recommendation_path.write_text(json.dumps({
        "production_recommendations_enabled": False,
    }), encoding="utf-8")
    alias_path = tmp_path / "probability_aliases.json"
    alias_path.write_text("[]", encoding="utf-8")
    attestation_path = tmp_path / "alias-attestation.json"
    attestation_path.write_text(json.dumps({
        "compare_fields": ["final_1x2_pct", "score_matrix"],
    }), encoding="utf-8")
    before = {path.name: _digest(path) for path in (
        lock_path, recommendation_path, alias_path, tmp_path / "registry.jsonl")}

    alias = {
        "status": "EQUIVALENT_ALIAS", "model_version": "m3",
        "probability_signature": ALIAS_SIG, "route": "market_only",
        "alias_to_model_version": "m4", "alias_to_probability_signature": CURRENT_SIG,
        "attestation_path": str(attestation_path),
        "attestation_sha256": _digest(attestation_path),
    }
    monkeypatch.setattr(version_progress, "build_identity", lambda: {
        "model_version": "m4", "probability_signature": CURRENT_SIG,
    })
    monkeypatch.setattr(version_progress, "load_version_aliases", lambda _version: [alias])
    monkeypatch.setattr(version_progress, "data_root", lambda: tmp_path)

    report = version_progress.build_direction_governance_report(
        tmp_path,
        release_lock_path=lock_path,
        recommendation_policy_path=recommendation_path,
    )

    assert report["current_identity"] == {
        "model_version": "m4", "probability_signature": CURRENT_SIG,
    }
    assert report["release_lock"]["status"] == "MATCH"
    assert report["sample_identity"] == {
        "raw_current_n": 1, "approved_alias_n": 1, "current_settled_n": 2,
        "current_pending_n": 0,
    }
    assert report["drift_group_status_counts"] == {"UNREPLAYED": 1}
    assert report["approved_aliases"] == [{
        "model_version": "m3",
        "probability_signature": ALIAS_SIG,
        "route": "market_only",
        "alias_to_model_version": "m4",
        "alias_to_probability_signature": CURRENT_SIG,
        "attestation_path": str(attestation_path),
        "attestation_sha256": _digest(attestation_path),
        "compare_fields": ["final_1x2_pct", "score_matrix"],
        "record_count": 1,
        "settled_count": 1,
    }]
    metrics = report["direction_policy_metrics"]
    assert metrics["registration_status_counts"] == {
        "NOT_REGISTERED": 1, "REGISTERED": 2,
    }
    assert metrics["primary_hit"] == {"hits": 1, "n": 2, "rate": 0.5}
    assert metrics["alternative_hit"] == {"hits": 1, "n": 1, "rate": 1.0}
    assert metrics["direction_policy_hit"] == {"hits": 2, "n": 2, "rate": 1.0}
    assert report["version_admission"]["status"] == "HOLD"
    assert report["version_admission"]["uses_direction_coverage"] is False
    assert report["read_only"] == {
        "aliases_written": False,
        "release_lock_written": False,
        "weights_changed": False,
        "gates_changed": False,
    }
    after = {path.name: _digest(path) for path in (
        lock_path, recommendation_path, alias_path, tmp_path / "registry.jsonl")}
    assert after == before


def test_direction_governance_entrypoint_has_no_output_or_mutation_flags():
    with pytest.raises(SystemExit) as exc:
        version_progress.direction_governance_main(["--output", "forbidden.json"])

    assert exc.value.code == 2
