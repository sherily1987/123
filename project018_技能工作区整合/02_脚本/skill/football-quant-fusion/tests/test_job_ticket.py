import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import job_ticket as jt


def test_quant_summary_keeps_four_market_model_outputs_with_dependency_label():
    """Catches job compression dropping score/TTG/HAFU model distributions."""
    out = {
        "mode": "market_only",
        "market_dependency_pct": 100,
        "forecast": {
            "final_1x2_pct": [20.0, 30.0, 50.0],
            "top_scores": [{"score": "0-1", "prob_pct": 12.0}],
            "ou_2_5": {"over_pct": 45.0, "under_pct": 55.0},
        },
        "core_output": {
            "ttg_score_consistency": {
                "model_prob_pct": [8.0, 20.0, 26.0, 22.0, 13.0, 6.0, 3.0, 2.0]
            },
            "hafu_model": {
                "prob_pct": [10.0, 5.0, 2.0, 8.0, 15.0, 19.0, 1.0, 5.0, 35.0],
                "calibration_status": "UNFITTED",
            },
            "derived_market_status": {"top_scores": "FITTED"},
        },
    }

    summary = jt.quant_from_fusion_output(out)

    assert summary["market_forecasts"]["CRS"]["top_scores"][0]["score"] == "0-1"
    assert summary["market_forecasts"]["HAD"]["model_prob_pct"] == [20.0, 30.0, 50.0]
    assert summary["market_forecasts"]["HAD"]["calibration_status"] == "UNFITTED"
    assert summary["market_forecasts"]["TTG"]["model_prob_pct"][2] == 26.0
    assert summary["market_forecasts"]["HAFU"]["model_prob_pct"][8] == 35.0
    assert summary["market_forecasts"]["HAFU"]["calibration_status"] == "UNFITTED"
    assert summary["market_forecasts"]["TTG"]["probability_source"] == "market_conditioned_model"
    assert summary["market_forecasts"]["TTG"]["independent_from_same_pool"] is False


def test_quant_summary_marks_missing_derivative_calibration_explicitly_unfitted():
    summary = jt.quant_from_fusion_output({"forecast": {}, "core_output": {}})
    assert {name: summary["market_forecasts"][name]["calibration_status"]
            for name in ("CRS", "TTG", "HAFU")} == {
                "CRS": "UNFITTED", "TTG": "UNFITTED", "HAFU": "UNFITTED",
            }


def test_normalize_match_id_accepts_int_str_and_prefixed():
    assert jt.normalize_match_id(2040898) == "sporttery-2040898"
    assert jt.normalize_match_id("2040898") == "sporttery-2040898"
    assert jt.normalize_match_id("sporttery-2040898") == "sporttery-2040898"
    assert jt.normalize_match_id(None) is None
    assert jt.normalize_match_id("") is None


def test_stamp_identity_writes_root_fields_from_sporttery_meta():
    payload = {"fusion_status": "ok"}
    data = {
        "home": "阿森纳",
        "away": "曼城",
        "sporttery_meta": {"match_id": 2040898, "match_num": "周日011"},
    }
    jt.stamp_identity(payload, data)
    assert payload["match_id"] == "sporttery-2040898"
    assert payload["match_num"] == "周日011"


def test_assemble_keeps_tracks_separate_and_rejects_vote_as_probability():
    ident = {
        "match_id": "sporttery-2040898",
        "match_num": "周日011",
        "sales_day": "2026-08-16",
        "home": "阿森纳",
        "away": "曼城",
        "kickoff": "2026-08-16T22:00:00+08:00",
    }
    job = jt.assemble_job(
        identity=ident,
        input_obj={"odds": [2.37, 3.17, 2.55], "mode": "market_only"},
        quant={
            "track": "quant",
            "final_1x2_pct": [36.3, 30.1, 33.6],
            "primary_outcome": "H",
            "status": "MARKET_BASELINE",
            "action": "skip",
            "mode": "market_only",
            "market_dependency_pct": 100,
        },
        llm={
            "dir": "平局",
            "alt": "主胜",
            "strength": 57.1,
            "ev_action": "skip",
            "ev_reason": "evidence_gap",
            "evidence_gap": True,
        },
    )
    assert jt.validate_job(job) == []
    tracks = {row["track"]: row for row in job["outputs"]}
    assert tracks["quant"]["final_1x2_pct"][0] == 36.3
    assert tracks["llm"]["direction"] == "D"
    assert tracks["llm"]["strength"]["type"] == "vote_share"
    assert abs(tracks["llm"]["strength"]["value"] - 0.571) < 1e-6
    assert "final_1x2_pct" not in tracks["llm"] or tracks["llm"].get("final_1x2_pct") is None

    bad = json.loads(json.dumps(job))
    bad["outputs"].append({"track": "llm", "final_1x2_pct": [50, 25, 25], "strength": 0.5})
    assert any("final_1x2_pct" in e or "vote_share" in e for e in jt.validate_job(bad))


def test_skip_action_cannot_carry_evs():
    ident = {"match_id": 2040001, "sales_day": "2026-08-16"}
    job = jt.assemble_job(
        identity=ident,
        llm={"dir": "主胜", "strength": 80, "ev_action": "skip", "evs": {"主胜": 0.2}},
    )
    llm = next(row for row in job["outputs"] if row["track"] == "llm")
    assert not llm.get("evs")
    sneaked = json.loads(json.dumps(job))
    sneaked["outputs"][0]["evs"] = {"主胜": 0.2}
    sneaked["outputs"][0]["action"] = "skip"
    assert any("evs" in e for e in jt.validate_job(sneaked))


def test_llm_preregister_schema_becomes_vote_share_skip():
    row = {
        "match_id": "sporttery-2040898",
        "direction": {"pick": "双选 平局/主胜（D/H）", "single_preference": "平局（D）"},
        "score_picks": ["1-1", "0-1"],
        "risk_gate": {"action": "skip", "reason": "证据存在缺口，风险过高", "strength": 0.571},
    }
    ident = {"match_id": "sporttery-2040898", "sales_day": "2026-08-16"}
    job = jt.assemble_job(identity=ident, llm=row)
    assert jt.validate_job(job) == []
    llm = job["outputs"][0]
    assert llm["direction"] == "D"
    assert llm["action"] == "skip"
    assert llm["strength"] == {"type": "vote_share", "value": 0.571}
    assert llm["evidence_gap"] is True


def test_upsert_merges_tracks_on_same_match_id(tmp_path):
    ident = {"match_id": 7, "sales_day": "2026-08-16", "home": "A", "away": "B"}
    p1 = jt.upsert_job(
        tmp_path,
        ident,
        quant={"track": "quant", "final_1x2_pct": [40, 30, 30], "action": "skip", "status": "MARKET_BASELINE"},
    )
    p2 = jt.upsert_job(
        tmp_path,
        ident,
        llm={"dir": "客胜", "strength": 0.6, "ev_action": "skip", "evidence_gap": False},
    )
    assert p1 == p2
    job = json.loads(p2.read_text(encoding="utf-8"))
    assert {row["track"] for row in job["outputs"]} == {"quant", "llm"}
    loaded = jt.load_job(tmp_path, "sporttery-7", "2026-08-16")
    assert loaded["identity"]["match_id"] == "sporttery-7"
