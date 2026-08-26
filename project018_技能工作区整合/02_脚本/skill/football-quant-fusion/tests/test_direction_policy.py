from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "direction_policy", SCRIPTS / "direction_policy.py"
)
direction_policy = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(direction_policy)


POLICY = {
    "schema_version": "direction-policy-1.0",
    "rule_version": "direction-policy-v1",
    "primary_only_min_gap_pp": 10.0,
    "cover_min_gap_pp": 2.0,
    "cover_max_gap_pp": 10.0,
    "alternative_min_probability": 0.28,
    "draw_tie_band_pp": 1.0,
    "unclear_max_gap_pp": 2.0,
}
IDENTITY = {"model_version": "m4", "probability_signature": "a" * 64}
AS_OF = "2026-08-27T10:00:00+00:00"


def build(probabilities, **kwargs):
    return direction_policy.build_direction_policy(
        probabilities,
        prediction_as_of=kwargs.pop("prediction_as_of", AS_OF),
        model_identity=kwargs.pop("model_identity", IDENTITY),
        policy=kwargs.pop("policy", POLICY),
        **kwargs,
    )


def test_clear_primary_is_single_direction():
    result = build([0.55, 0.25, 0.20])

    assert result["classification"] == "PRIMARY_ONLY"
    assert result["primary_direction"] == "H"
    assert result["alternative_direction"] is None
    assert result["probabilities"] == {"H": 0.55, "D": 0.25, "A": 0.20}
    assert result["trigger"]["primary_margin_pp"] == 30.0


def test_close_draw_is_selected_as_cover_within_tie_band():
    result = build([0.394, 0.298, 0.307])

    assert result["classification"] == "PRIMARY_WITH_COVER"
    assert result["primary_direction"] == "H"
    assert result["alternative_direction"] == "D"
    assert result["trigger"]["primary_margin_pp"] == 8.7
    assert result["trigger"]["primary_vs_alternative_pp"] == 9.6


def test_near_tie_abstains():
    result = build([0.34, 0.33, 0.33])

    assert result["classification"] == "UNCLEAR"
    assert result["primary_direction"] is None
    assert result["alternative_direction"] is None


def test_percentages_are_preserved_without_rescaling():
    result = build([39.4, 29.8, 30.7])

    assert result["classification"] == "PRIMARY_WITH_COVER"
    assert result["probabilities"] == {"H": 39.4, "D": 29.8, "A": 30.7}
    assert result["probability_unit"] == "percent"


def test_valid_policy_carries_auditable_identity_source_and_signature():
    result = build([0.44, 0.28, 0.28])

    assert result["status"] == "AVAILABLE"
    assert result["rule_version"] == "direction-policy-v1"
    assert result["model_version"] == "m4"
    assert result["probability_signature"] == "a" * 64
    assert result["prediction_as_of"] == AS_OF
    assert result["probability_source"] == "final_1x2_pct"
    assert len(result["decision_policy_signature"]) == 64


def test_policy_signature_changes_when_canonical_config_changes():
    first = build([0.44, 0.28, 0.28])
    changed = dict(POLICY, alternative_min_probability=0.29)
    second = build([0.44, 0.28, 0.28], policy=changed)

    assert first["decision_policy_signature"] != second["decision_policy_signature"]


def test_direction_implementation_is_governed_as_decision_policy_not_probability_code():
    manifest = json.loads(
        (SKILL_ROOT / "config" / "version_manifest.json").read_text(encoding="utf-8")
    )

    assert "scripts/direction_policy.py" in manifest["decision_policy_files"]
    assert "scripts/direction_policy.py" not in manifest["probability_files"]


def test_policy_signature_changes_when_governed_implementation_bytes_change(
        monkeypatch, tmp_path):
    governed_code = tmp_path / "direction_policy.py"
    governed_code.write_bytes(b"original direction behavior")
    monkeypatch.setattr(direction_policy, "POLICY_IMPLEMENTATION_FILE", governed_code)
    first = build([0.44, 0.28, 0.28])

    governed_code.write_bytes(b"changed direction behavior")
    second = build([0.44, 0.28, 0.28])

    assert first["decision_policy_signature"] != second["decision_policy_signature"]


def test_invalid_input_returns_unavailable_without_fabricating_direction():
    result = build([0.7, 0.2, 0.2])

    assert result["status"] == "UNAVAILABLE"
    assert result["classification"] == "UNAVAILABLE"
    assert result["primary_direction"] is None
    assert result["alternative_direction"] is None
    assert result["reason"] == "probabilities_must_sum_to_100"


def test_naive_prediction_time_returns_unavailable():
    result = build([0.55, 0.25, 0.20], prediction_as_of="2026-08-27T10:00:00")

    assert result["status"] == "UNAVAILABLE"
    assert result["primary_direction"] is None
    assert result["reason"] == "prediction_as_of_must_be_timezone_aware"
