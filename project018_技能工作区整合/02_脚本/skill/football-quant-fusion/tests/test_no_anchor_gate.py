"""无锚不得写成生产 1X2。"""
import os
import sys
from pathlib import Path

os.environ.setdefault(
    "FUSION_CORE_DIR",
    r"F:/HM足球比赛预测/project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(
    0,
    r"F:/HM足球比赛预测/project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts",
)

import fusion_predict_core as F
import predict as P


def test_no_odds_no_lambda_cannot_emit_374():
    out = P.predict({
        "home": "A", "away": "B", "stage": "Test",
        "kickoff": "2026-08-16T03:00:00+08:00", "context_confirmed": True,
    })
    assert out["status"] in ("incomplete", "no_independent_anchor", "invalid")
    assert out.get("final_1x2_pct") != [37.4, 25.3, 37.4]


def test_stale_favorite_does_not_flatten_to_374():
    """43 场里尤文那种：有盘、无独立锚、时间戳已老，不得摊成 37.4/37.4。"""
    core, version = F.load_core()
    wrapped = F.predict_one(core, version, {
        "home": "尤文图斯", "away": "克雷莫纳", "competition": "意甲", "stage": "意甲",
        "kickoff": "2026-01-13T03:45:00+08:00",
        "mode": "market_only",
        "odds": [1.14, 5.8, 12.5],
        "field_meta": {"odds": {"observed_at": "2026-01-12T11:37:16+08:00", "freshness": 15}},
    })
    assert wrapped["fusion_status"] == "blocked"
    assert wrapped["core_output"]["status"] in (
        "market_anchor_unusable", "no_independent_anchor",
    )
    assert (wrapped.get("forecast") or {}).get("final_1x2_pct") != [37.4, 25.3, 37.4]


def test_empty_pairs_fallback_is_not_production_1x2():
    lh, la, tags = P.build_lambdas({}, 2.45, None, False, False, "model_first")
    assert "NO_ANCHOR_FALLBACK" in tags
    assert abs(lh - la) < 1e-9
    out = P.predict({
        "home": "A", "away": "B", "stage": "Test",
        "kickoff": "2026-08-16T03:00:00+08:00",
        "mode": "model_first",
        "lambda_home": 1.4, "lambda_away": 1.1,
        "field_meta": {},
    })
    assert "NO_ANCHOR_FALLBACK" not in (out.get("xg_tags") or [])


def test_explicit_lambda_still_model_first():
    out = P.predict({
        "home": "A", "away": "B", "stage": "Test",
        "kickoff": "2026-08-16T03:00:00+08:00",
        "mode": "model_first", "lambda_home": 1.4, "lambda_away": 1.1,
        "field_meta": {},
    })
    assert out["status"] == "ok"
    assert out["mode"] == "model_first"
    assert out["market_dependency_pct"] == 0
    assert "NO_ANCHOR_FALLBACK" not in (out.get("xg_tags") or [])
