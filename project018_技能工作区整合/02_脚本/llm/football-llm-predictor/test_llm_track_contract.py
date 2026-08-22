import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("llm_track_contract.py")
SPEC = importlib.util.spec_from_file_location("llm_track_contract", MODULE_PATH)
contract = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(contract)


def test_k3_single_model_record_is_research_only_and_normalizes_match_id():
    record = {
        "match_id": "2040999",
        "models_used": ["moonshot/kimi-k3"],
        "single_model": True,
        "research_only": True,
        "action": "observe",
        "reason": "single_model_no_consensus",
        "prediction_as_of": "2026-08-22T12:00:00+08:00",
    }

    result = contract.validate_prediction_record(record)

    assert result["valid"] is True
    assert result["match_id"] == "sporttery-2040999"
    assert result["model_id"] == "moonshot/kimi-k3"
    assert result["reason_codes"] == []


def test_single_model_record_cannot_claim_consensus_or_bet():
    record = {
        "match_id": "sporttery-2040999",
        "models_used": ["moonshot/kimi-k3"],
        "single_model": True,
        "research_only": False,
        "action": "bet",
        "reason": "",
        "prediction_as_of": "2026-08-22T12:00:00+08:00",
    }

    result = contract.validate_prediction_record(record)

    assert result["valid"] is False
    assert "SINGLE_MODEL_NOT_RESEARCH_ONLY" in result["reason_codes"]
    assert "SINGLE_MODEL_ACTION_NOT_OBSERVE" in result["reason_codes"]


def test_evidence_manifest_preserves_unavailable_sections_without_t75_state():
    raw_match = {
        "match_id": "sporttery-2040999",
        "kickoff": "2026-08-22T20:00:00+08:00",
        "crs": [],
        "ttg": [],
        "hafu": [],
    }
    evidence = {
        "recent_form": {"home": [{"result": "W"}], "away": []},
        "injuries_status": "UNAVAILABLE",
        "lineups_status": "UNAVAILABLE",
        "collected_at": "2026-08-22T18:45:00+08:00",
    }

    manifest = contract.build_evidence_manifest(raw_match, evidence)

    assert manifest["match_id"] == "sporttery-2040999"
    assert manifest["sections"]["recent_form"]["status"] == "PARTIAL"
    assert manifest["sections"]["crs"]["status"] == "UNAVAILABLE"
    assert manifest["sections"]["ttg"]["status"] == "UNAVAILABLE"
    assert manifest["sections"]["hafu"]["status"] == "UNAVAILABLE"
    assert manifest["sections"]["lineups"]["status"] == "UNAVAILABLE"
    assert manifest["collection_mode"] == "single_pass"
    assert manifest["collection_status"] == "PARTIAL"
    assert manifest["gap_sections"] == ["recent_form", "crs", "ttg", "hafu", "injuries", "lineups"]
    assert "t75_refresh" not in manifest
