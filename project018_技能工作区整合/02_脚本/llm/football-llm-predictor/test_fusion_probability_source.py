# -*- coding: utf-8 -*-
"""轨道A概率来源加载器测试（2026-08-16）。

关键断言：取不到就返回 None（调用方必须 skip），绝不回退到投票比例；
market_only 记录必须被标成 market_derived。
"""
import json

import fusion_probability_source as fps


def _write_store(tmp_path, records):
    store = tmp_path / "backtest"
    (store / "predictions").mkdir(parents=True)
    lines = []
    for rec in records:
        path = store / "predictions" / f"{rec['prediction_id'].replace(':', '-')}.json"
        path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        lines.append(json.dumps({"match_id": rec["match_id"], "created_at": rec["created_at"],
                                 "path": str(path)}, ensure_ascii=False))
    (store / "registry.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return store


def _record(match_id, created_at, pct, mode="market_only", applied=True):
    return {
        "prediction_id": f"{match_id}__{created_at}",
        "match_id": match_id,
        "created_at": created_at,
        "snapshot_type": "prematch",
        "mode": mode,
        "model": {"model_version": "m2"},
        "output": {
            "final_1x2_pct": pct,
            "market_dependency_pct": 100 if mode == "market_only" else 40,
            "calibration": {"applied": applied, "league_basis": "测试基准"},
        },
    }


def test_returns_none_when_quant_track_has_not_registered_the_match(tmp_path):
    store = _write_store(tmp_path, [_record("sporttery-1", "2026-08-16T00:00:00Z", [40, 30, 30])])
    assert fps.load_fusion_probabilities(999, store=store) is None


def test_loads_probabilities_and_marks_market_derived(tmp_path):
    store = _write_store(tmp_path, [_record("sporttery-2040898", "2026-08-16T00:00:00Z",
                                            [36.3, 30.1, 33.6])])
    got = fps.load_fusion_probabilities(2040898, store=store)
    assert got["probabilities"] == {"主胜": 0.363, "平局": 0.301, "客胜": 0.336}
    also = fps.load_fusion_probabilities("sporttery-2040898", store=store)
    assert also["probabilities"] == got["probabilities"]
    assert got["source"] == "fusion-m2-final_1x2_pct"
    assert got["calibration_status"] == "VALID"
    assert got["market_derived"] is True


def test_non_market_only_mode_is_not_market_derived(tmp_path):
    store = _write_store(tmp_path, [_record("sporttery-3", "2026-08-16T00:00:00Z",
                                            [40, 30, 30], mode="hybrid")])
    assert fps.load_fusion_probabilities(3, store=store)["market_derived"] is False


def test_uncalibrated_record_reports_unfitted(tmp_path):
    store = _write_store(tmp_path, [_record("sporttery-4", "2026-08-16T00:00:00Z",
                                            [40, 30, 30], applied=False)])
    assert fps.load_fusion_probabilities(4, store=store)["calibration_status"] == "UNFITTED"


def test_latest_snapshot_wins(tmp_path):
    store = _write_store(tmp_path, [
        _record("sporttery-5", "2026-08-16T00:00:00Z", [40, 30, 30]),
        _record("sporttery-5", "2026-08-16T06:00:00Z", [50, 25, 25]),
    ])
    got = fps.load_fusion_probabilities(5, store=store)
    assert got["probabilities"]["主胜"] == 0.5


def test_malformed_probability_vector_is_rejected(tmp_path):
    bad = _record("sporttery-6", "2026-08-16T00:00:00Z", [40, 30])
    store = _write_store(tmp_path, [bad])
    assert fps.load_fusion_probabilities(6, store=store) is None
