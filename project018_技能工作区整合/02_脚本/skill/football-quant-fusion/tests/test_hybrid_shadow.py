import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hybrid_shadow as hs
import job_ticket as jt


def test_job_research_hybrid_is_sidecar_not_output_track():
    ident = {"match_id": 2040884, "sales_day": "2026-08-16", "home": "塞维利亚", "away": "巴列卡诺"}
    job = jt.assemble_job(
        identity=ident,
        quant={"track": "quant", "final_1x2_pct": [41.2, 30.9, 28.0], "action": "skip", "status": "MARKET_BASELINE"},
        research={"final_1x2_pct": [40.0, 30.0, 30.0], "mode": "hybrid", "skip_reason": None},
    )
    assert jt.validate_job(job) == []
    assert {o["track"] for o in job["outputs"]} == {"quant"}
    assert job["research"]["hybrid"]["research_only"] is True
    assert job["research"]["hybrid"]["final_1x2_pct"][0] == 40.0


def test_odds_movement_is_a_separate_research_sidecar():
    job = jt.assemble_job(
        identity={"match_id": 2040884, "sales_day": "2026-08-16"},
        research={
            "final_1x2_pct": [40.0, 30.0, 30.0], "mode": "hybrid",
            "odds_movement": {"status": "VALID", "prob_shift_pp": [1.0, 0.0, -1.0]},
        },
    )

    assert job["research"]["odds_movement"]["research_only"] is True
    assert "odds_movement" not in job["research"]["hybrid"]


def test_research_hybrid_must_be_research_only():
    job = {
        "schema": jt.SCHEMA,
        "identity": {"match_id": "sporttery-1"},
        "outputs": [],
        "research": {"hybrid": {"research_only": False, "final_1x2_pct": [40, 30, 30]}},
    }
    assert any("research_only" in e for e in jt.validate_job(job))


def test_scope_and_fusion_input():
    assert hs.in_scope({"competition": "西甲"}) is None
    assert hs.in_scope({"league": "瑞超"}) is None
    assert hs.in_scope({"league": "沙职"}) is None
    assert hs.in_scope({"league": "英冠"}) is None
    assert hs.in_scope({"league": "欧冠"}) is None
    assert hs.in_scope({"league": "欧联"}) is None
    assert hs.in_scope({"league": "欧协联"}) is None
    assert hs.in_scope({"league": "解放者杯"}) is None
    assert hs.in_scope({"league": "亚冠精英"}) is None
    assert hs.in_scope({"league": "欧超杯"}) is None
    assert hs.in_scope({"league": "世界杯"}) is None
    assert hs.in_scope({"league": "俱乐部友谊"}).startswith("league_not_in_scope")
    raw = {
        "match_id": 2040884, "match_num": "周六024",
        "home": "塞维利亚", "away": "巴列卡诺", "league": "西甲",
        "kickoff_iso": "2026-08-16T03:30:00+08:00",
        "model_odds": [2.2, 2.84, 3.1],
    }
    inp = hs.to_fusion_input(raw)
    assert inp["mode"] == "market_only"
    assert inp["sporttery_meta"]["match_id"] == 2040884
    assert inp["odds"] == [2.2, 2.84, 3.1]


def test_score_day_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(hs, "jobs_root", lambda: tmp_path)
    monkeypatch.setattr(hs, "backtest_store", lambda: tmp_path / "backtest")
    (tmp_path / "backtest" / "results").mkdir(parents=True)
    assert hs.score_day("2026-08-16")["n"] == 0


def test_weight_sweep_is_research_only_and_does_not_mutate_primary_route(monkeypatch):
    routed = {"mode": "hybrid", "market_weight": 0.6, "lambda_prior": {"lambda_home": 1.2}}
    seen = []

    def fake_predict(_core, _version, payload):
        seen.append(payload["market_weight"])
        return {
            "fusion_status": "ok", "mode": "hybrid",
            "forecast": {
                "final_1x2_pct": [payload["market_weight"] * 100, 20, 80 - payload["market_weight"] * 100],
                "model_1x2_pct": [30, 30, 40], "market_prob_pct": [40, 25, 35],
            },
        }

    monkeypatch.setattr(hs, "predict_one", fake_predict)
    sweep = hs.weight_sweep(None, {}, routed, routed["lambda_prior"], weights=(0.4, 0.7))

    assert seen == [0.4, 0.7]
    assert routed["market_weight"] == 0.6
    assert [item["market_weight"] for item in sweep] == [0.4, 0.7]
    assert all(item["research_only"] is True for item in sweep)
