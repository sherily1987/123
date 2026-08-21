import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import hybrid_shadow as hs
import intl_kelly_index as iki
import job_ticket as jt

PINNACLE = {
    "key": "pinnacle",
    "title": "Pinnacle",
    "markets": [{
        "key": "h2h",
        "outcomes": [
            {"name": "Espanyol", "price": 2.12},
            {"name": "Draw", "price": 3.31},
            {"name": "Levante", "price": 3.86},
        ],
    }],
}
SOFT_HOME = {
    "key": "williamhill",
    "title": "William Hill",
    "markets": [{
        "key": "h2h",
        "outcomes": [
            {"name": "Espanyol", "price": 1.70},
            {"name": "Draw", "price": 3.80},
            {"name": "Levante", "price": 5.00},
        ],
    }],
}
LAY = {
    "key": "betfair_ex_eu",
    "title": "Betfair",
    "markets": [{
        "key": "h2h_lay",
        "outcomes": [
            {"name": "Espanyol", "price": 2.18},
            {"name": "Draw", "price": 3.45},
            {"name": "Levante", "price": 4.20},
        ],
    }],
}


def _row(books):
    return {
        "match_id": "sporttery-2040907",
        "intl_match": "Espanyol vs Levante",
        "bookmakers": books,
    }


def test_pinnacle_beats_softer_books():
    cons = iki.consensus_from_bookmakers(
        [SOFT_HOME, PINNACLE, LAY], ["Espanyol", "西班牙人"], ["Levante", "莱万特"])
    assert cons["source"] == "pinnacle"
    assert cons["n_books"] == 1
    assert cons["probs"] == iki.proportional_devig([2.12, 3.31, 3.86])


def test_mean_used_when_pinnacle_missing():
    cons = iki.consensus_from_bookmakers(
        [SOFT_HOME], ["Espanyol"], ["Levante"])
    assert cons["source"] == "equal_weight_mean"
    assert cons["n_books"] == 1


def test_lay_market_is_ignored():
    cons = iki.consensus_from_bookmakers([LAY], ["Espanyol"], ["Levante"])
    assert cons.get("error") == "no_complete_h2h"


def test_shape_gap_picks_softest_sporttery_direction():
    # 体彩把主胜开松：相对 Pinnacle 共识，主胜 G 应明显高于另外两个
    sporttery = [2.40, 3.20, 2.90]
    intl = iki.proportional_devig([2.12, 3.31, 3.86])
    shape = iki.chinese_kelly_index(sporttery, intl)
    assert shape["softest_direction"] == "主胜"
    assert shape["gap_max_minus_mid"] > 0.05
    assert shape["index"]["主胜"] == sporttery[0] * intl[0]


def test_audit_is_unfitted_research_and_has_no_stake():
    payload = iki.audit_from_intl_row(
        [2.05, 3.20, 3.55], _row([PINNACLE]),
        home="西班牙人", away="莱万特", match_id="sporttery-2040907")
    assert payload["research_only"] is True
    assert payload["calibration"] == "UNFITTED"
    assert payload["status"] == "ok"
    assert payload["intl_source"] == "pinnacle"
    assert payload["ledger_entry"]["backtested"] is False
    assert payload["ledger_entry"]["calibration"] == "UNFITTED"
    iki.assert_no_stake_fields(payload)
    # 体彩与 Pinnacle 形状接近时，三个 G 都在返还率附近且 < 1
    assert all(g < 1.0 for g in payload["index"].values())


def test_missing_intl_skips():
    skipped = iki.intl_kelly_for_match(
        {"home": "A", "away": "B", "odds": [2.0, 3.2, 3.8], "match_id": 1},
        store=None)
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "intl_odds_unavailable"
    iki.assert_no_stake_fields(skipped)


def test_load_latest_row_prefers_last_batch(tmp_path):
    store = tmp_path / "intl_production.jsonl"
    first = {"matches": [_row([SOFT_HOME])]}
    second = {"matches": [_row([PINNACLE])]}
    store.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    row = iki.load_latest_intl_row(store, "sporttery-2040907")
    assert row["bookmakers"][0]["key"] == "pinnacle"


def test_job_ticket_splits_sidecar_and_keeps_hybrid():
    ident = {"match_id": 2040907, "sales_day": "2026-08-16", "home": "西班牙人", "away": "莱万特"}
    job = jt.assemble_job(
        identity=ident,
        research={
            "final_1x2_pct": [40.0, 30.0, 30.0],
            "mode": "hybrid",
            "intl_kelly": {
                "calibration": "UNFITTED",
                "status": "ok",
                "index": {"主胜": 0.93, "平局": 0.91, "客胜": 0.88},
            },
        },
    )
    assert jt.validate_job(job) == []
    assert job["research"]["hybrid"]["final_1x2_pct"][0] == 40.0
    assert "intl_kelly" not in job["research"]["hybrid"]
    assert job["research"]["intl_kelly"]["research_only"] is True
    assert job["research"]["intl_kelly"]["calibration"] == "UNFITTED"


def test_job_ticket_rejects_stake_and_valid_calibration():
    ident = {"match_id": 2040907, "sales_day": "2026-08-16"}
    job = jt.assemble_job(
        identity=ident,
        research={"intl_kelly": {"calibration": "VALID", "kelly_fraction": 0.1}},
    )
    errors = jt.validate_job(job)
    assert any("UNFITTED" in e for e in errors)
    assert any("stake" in e for e in errors)


def test_hybrid_shadow_attaches_sidecar_without_touching_predict_input(tmp_path, monkeypatch):
    store = tmp_path / "intl_production.jsonl"
    store.write_text(json.dumps({"matches": [_row([PINNACLE])]}) + "\n", encoding="utf-8")
    monkeypatch.setattr(hs, "intl_store", lambda: store)
    match = {
        "home": "西班牙人",
        "away": "莱万特",
        "odds": [2.40, 3.20, 2.90],
        "match_id": 2040907,
        "mode": "market_only",
    }
    before = json.dumps(match, sort_keys=True)
    blob = hs._research_blob(match, {"final_1x2_pct": [41.0, 30.0, 29.0], "mode": "hybrid"})
    assert json.dumps(match, sort_keys=True) == before
    assert match["mode"] == "market_only"
    assert blob["final_1x2_pct"][0] == 41.0
    kelly = blob["intl_kelly"]
    assert kelly["status"] == "ok"
    assert kelly["softest_direction"] == "主胜"
    assert kelly["calibration"] == "UNFITTED"
    iki.assert_no_stake_fields(blob)
