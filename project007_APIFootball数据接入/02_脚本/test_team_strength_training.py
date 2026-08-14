from __future__ import annotations
import importlib.util, json, subprocess, sys
from pathlib import Path
import pytest

MODULE=Path(__file__).parents[2] / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "team_strength.py"
SPEC=importlib.util.spec_from_file_location("strength",MODULE); strength=importlib.util.module_from_spec(SPEC); assert SPEC and SPEC.loader; SPEC.loader.exec_module(strength)

def test_results_only_league_filter_loads_finished_rows(tmp_path):
    p=tmp_path/'rows.jsonl'; p.write_text(json.dumps({"league_id":152,"actual":[2,1],"home":"A","away":"B","kickoff":"2025-01-01"})+'\n'+json.dumps({"league_id":1,"actual":[1,0],"home":"C","away":"D","kickoff":"2025-01-02"})+'\n',encoding='utf-8')
    rows=strength.load_matches(p,league_id=152,require_odds=False)
    assert len(rows)==1 and rows[0]['gh']==2 and rows[0]['league']=='152'


def test_cli_exposes_results_only_and_league_filter():
    result = subprocess.run(
        [sys.executable, str(MODULE), "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--results-only" in result.stdout
    assert "--league-id" in result.stdout


def test_results_only_validation_marks_market_as_unavailable(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {
        "teams": ["A", "B"],
        "home_adv": 0.0,
        "alpha": [0.0, 0.0],
        "beta": [0.0, 0.0],
    }
    report = strength.validate(
        [
            {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "152", "odds": []},
            {"home": "B", "away": "A", "gh": 0, "ga": 1, "day": 2, "league": "152", "odds": []},
        ],
        model,
        from_day=2,
    )
    assert report["model"]["n"] == 1
    assert report["market"] == {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"}


def test_results_only_validation_honors_exclusive_to_day(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    rows = [
        {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "152", "odds": []},
        {"home": "B", "away": "A", "gh": 0, "ga": 1, "day": 2, "league": "152", "odds": []},
        {"home": "A", "away": "B", "gh": 1, "ga": 1, "day": 3, "league": "152", "odds": []},
    ]

    report = strength.validate(rows, model, from_day=2, to_day=3)

    assert report["n"] == 1


def test_validate_reports_named_provider_market_baseline(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    matches = [
        {"home": "A", "away": "B", "gh": 0, "ga": 0, "day": 1, "league": "152", "odds": []},
        {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 2, "league": "152", "odds": [], "provider_market": [0.5, 0.3, 0.2]},
    ]

    report = strength.validate(matches, model, from_day=2, baseline_key="provider_market", baseline_label="provider_market")

    assert report["provider_market"]["n"] == 1
    assert "market" not in report


# --- 球队身份主键（供应商跨赛季改名） ---

def _event(mid, home_id, home, away_id, away, day, goals=(1, 0)):
    return {"match_id": mid, "league_id": 152, "actual": list(goals), "kickoff": day,
            "home_id": home_id, "home": home, "away_id": away_id, "away": away}


def test_team_key_prefers_provider_id_and_falls_back_to_name():
    assert strength.team_key({"home_id": 80, "home": "Man City"}, "home") == "id:80"
    assert strength.team_key({"home": "Man City"}, "home") == "Man City"


def test_load_matches_merges_renamed_team_into_one_identity(tmp_path):
    """同一 team_id 换了显示名，必须仍是同一支球队。"""
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        _event(1, 80, "Manchester City", 102, "Manchester United", "2024-08-10"),
        _event(2, 80, "Man City", 102, "Manchester Utd", "2025-08-10"),
    ]) + "\n", encoding="utf-8")

    rows = strength.load_matches(p, require_odds=False)

    assert {r["home"] for r in rows} == {"id:80"}
    assert {r["away"] for r in rows} == {"id:102"}
    assert rows[0]["home_name"] == "Manchester City" and rows[1]["home_name"] == "Man City"


def test_fit_model_exposes_aliases_and_predict_accepts_any_historical_name(tmp_path):
    p = tmp_path / "rows.jsonl"
    events = []
    for i, day in enumerate(["2024-08-10", "2024-09-10", "2024-10-10", "2024-11-10"]):
        events.append(_event(i * 2 + 1, 80, "Manchester City", 102, "Manchester United", day, (2, 1)))
        events.append(_event(i * 2 + 2, 102, "Manchester United", 80, "Manchester City", day, (1, 1)))
    events.append(_event(99, 80, "Man City", 102, "Manchester Utd", "2025-08-10", (3, 0)))
    p.write_text("\n".join(json.dumps(r) for r in events) + "\n", encoding="utf-8")

    model = strength.fit_model(strength.load_matches(p, require_odds=False))

    assert model["teams"] == ["id:102", "id:80"]
    assert model["team_names"] == ["Manchester Utd", "Man City"]  # 取最近一次写法
    # 新旧队名、主键三种写法都应命中同一支球队
    for home, away in [("Man City", "Manchester Utd"),
                       ("Manchester City", "Manchester United"),
                       ("id:80", "id:102")]:
        res = strength.predict_match(model, home, away)
        assert res["status"] == "VALID", (home, away)
        assert res["home"] == "Man City"


def test_build_team_identity_drops_alias_for_true_duplicate_names():
    """同名不同 id 是真重名（实测塞浦路斯有两支 Omonia）。
    不得静默合并成一支，也不得中断整条管线——丢弃该别名并记录即可。"""
    matches = [
        {"home": "id:1", "away": "id:2", "home_name": "Omonia", "away_name": "B", "day": 1},
        {"home": "id:3", "away": "id:2", "home_name": "Omonia", "away_name": "B", "day": 2},
    ]

    names, aliases, ambiguous = strength.build_team_identity(matches)

    assert ambiguous == {"Omonia": ["id:1", "id:3"]}
    assert "Omonia" not in aliases          # 按名字无从分辨，不建别名
    assert aliases["B"] == "id:2"           # 其余名字不受影响
    assert set(names) == {"id:1", "id:2", "id:3"}   # 三支球队仍各自独立


def test_ambiguous_name_does_not_resolve_in_predict(monkeypatch, tmp_path):
    """重名球队不能被 predict_match 按名字命中，否则会指向错误的队。"""
    p = tmp_path / "rows.jsonl"
    rows = []
    for i, d in enumerate(["2024-08-10", "2024-09-10", "2024-10-10", "2024-11-10"]):
        rows.append(_event(i * 2 + 1, 1, "Omonia", 2, "Other", d, (2, 1)))
        rows.append(_event(i * 2 + 2, 3, "Omonia", 2, "Other", d, (1, 1)))
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    model = strength.fit_model(strength.load_matches(p, require_odds=False))

    assert "Omonia" in model["ambiguous_names"]
    assert strength.predict_match(model, "Omonia", "Other")["status"] == "UNFITTED_TEAM"
    assert strength.predict_match(model, "id:1", "id:2")["status"] == "VALID"


def test_validate_does_not_skip_renamed_team(monkeypatch, tmp_path):
    """回归保护：改名发生在测试期时，整队曾被判 UNFITTED_TEAM 全部跳过。"""
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    p = tmp_path / "rows.jsonl"
    events = [_event(i, 80, "Manchester City", 102, "Manchester United", d, (2, 1))
              for i, d in enumerate(["2024-08-10", "2024-09-10", "2024-10-10"])]
    events.append(_event(9, 80, "Man City", 102, "Manchester Utd", "2025-08-10", (1, 0)))
    p.write_text("\n".join(json.dumps(r) for r in events) + "\n", encoding="utf-8")
    matches = strength.load_matches(p, require_odds=False)
    model = strength.fit_model([m for m in matches if m["day"] < strength.parse_day("2025-01-01")])

    report = strength.validate(matches, model, from_day=strength.parse_day("2025-01-01"))

    assert report["skip"] == 0 and report["model"]["n"] == 1


def test_team_index_tolerates_model_without_aliases():
    """旧模型文件没有 team_aliases，仍按主键查找。"""
    assert strength.team_index({"teams": ["A", "B"]}) == {"A": 0, "B": 1}


# --- 冷启动：低样本收缩与未见球队兜底 ---

def _toy_model():
    return {"teams": ["A", "B", "C"], "home_adv": 0.2,
            "alpha": [0.6, -0.6, 0.0], "beta": [0.3, -0.1, -0.2],
            "weighted_n": [2.0, 200.0, 50.0]}


def test_apply_shrinkage_is_identity_when_k_is_zero():
    model = _toy_model()
    assert strength.apply_shrinkage(model, 0)["alpha"] == model["alpha"]


def test_apply_shrinkage_pulls_low_sample_team_toward_mean():
    model = _toy_model()
    out = strength.apply_shrinkage(model, 10)
    mean_a = sum(model["alpha"]) / 3

    # 1) 均值守恒：收缩只压缩队际差距，不改联赛整体进球水平
    assert abs(sum(out["alpha"]) / 3 - mean_a) < 1e-9
    assert abs(sum(out["beta"]) / 3 - sum(model["beta"]) / 3) < 1e-9
    # 2) 离散度必须变小
    assert max(out["alpha"]) - min(out["alpha"]) < max(model["alpha"]) - min(model["alpha"])
    # 3) 低样本队（A，2 场）被拉得比高样本队（B，200 场）更狠
    pull = lambda i: abs(out["alpha"][i] - mean_a) / abs(model["alpha"][i] - mean_a)
    assert pull(0) < pull(1)


def test_estimate_newcomer_prior_recovers_weak_newcomer():
    """升班马进球少、失球多，先验应为 α<0、β>0。"""
    matches = []
    day = 0
    for i in range(200):  # 老队之间：2-2，联赛均值每队 2 球
        day += 3
        matches.append({"home": "old1", "away": "old2", "gh": 2, "ga": 2, "day": day})
    for i in range(80):  # 一年后出现的新队：进 1 失 3
        day += 3
        matches.append({"home": "old1", "away": "newbie", "gh": 3, "ga": 1, "day": day})
    prior = strength.estimate_newcomer_prior(matches)
    assert prior["alpha_offset"] < 0 and prior["beta_offset"] > 0
    assert prior["n_teams"] == 1


def test_attach_fallback_uses_league_mean_without_prior():
    model = strength.attach_fallback(_toy_model())
    assert model["fallback"]["basis"] == "league_mean"
    assert abs(model["fallback"]["alpha"] - 0.0) < 1e-9


def test_attach_fallback_applies_newcomer_offset():
    prior = {"alpha_offset": -0.3, "beta_offset": 0.4}
    model = strength.attach_fallback(_toy_model(), prior)
    assert model["fallback"]["basis"] == "newcomer_prior"
    assert model["fallback"]["alpha"] < 0 and model["fallback"]["beta"] > sum(_toy_model()["beta"]) / 3


def test_score_rows_uses_fallback_instead_of_skipping(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = strength.attach_fallback(_toy_model())
    subset = [{"home": "A", "away": "从未见过", "gh": 1, "ga": 0, "day": 5, "league": "152", "odds": []}]

    skipped, n_skipped = strength.score_rows(subset, model)
    scored, n_scored = strength.score_rows(subset, model, use_fallback=True)

    assert (len(skipped), n_skipped) == (0, 1)
    assert (len(scored), n_scored) == (1, 0)
    assert scored[0]["fallback_used"] is True


# --- xG 目标与混合 ---

def test_rho_is_zero_for_xg_target():
    """tau_terms 靠整数相等做 DC 修正，小数 xG 永远匹配不上会静默失效。
    必须显式取 0，而不是依赖它碰巧不生效。"""
    assert strength.rho_for("xg") == 0.0
    assert strength.rho_for("goals") == strength.RHO


def test_fit_model_records_zero_rho_when_target_is_xg(tmp_path):
    p = tmp_path / "rows.jsonl"
    events = []
    for i, d in enumerate(["2024-08-10", "2024-09-10", "2024-10-10", "2024-11-10"]):
        events.append(_event(i * 2 + 1, 1, "A", 2, "B", d, (2, 1)))
        events.append(_event(i * 2 + 2, 2, "B", 1, "A", d, (1, 1)))
    p.write_text("\n".join(json.dumps(r) for r in events) + "\n", encoding="utf-8")
    xg = tmp_path / "xg.jsonl"
    xg.write_text("\n".join(json.dumps({"match_id": e["match_id"], "xg": [1.4, 0.9]}) for e in events) + "\n",
                  encoding="utf-8")

    matches = strength.load_matches(p, require_odds=False, xg_input=xg)
    model = strength.fit_model(matches, target="xg")

    assert model["rho"] == 0.0 and model["target"] == "xg"
    assert matches[0]["gh"] == 1.4  # 进球被 xG 顶替


def test_load_matches_skips_rows_without_xg_instead_of_filling_zero(tmp_path):
    p = tmp_path / "rows.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        _event(1, 1, "A", 2, "B", "2024-08-10"),
        _event(2, 1, "A", 2, "B", "2024-09-10"),
    ]) + "\n", encoding="utf-8")
    xg = tmp_path / "xg.jsonl"
    xg.write_text(json.dumps({"match_id": 1, "xg": [1.2, 0.8]}) + "\n", encoding="utf-8")

    rows = strength.load_matches(p, require_odds=False, xg_input=xg)

    assert len(rows) == 1 and rows[0]["gh"] == 1.2
    assert strength.LAST_LOAD_STATS["xg_missing"] == 1


def _model(teams, names, alpha, beta, adv=0.2):
    return {"teams": teams, "team_names": names, "team_aliases": dict(zip(names, teams)),
            "home_adv": adv, "alpha": alpha, "beta": beta, "weighted_n": [10.0] * len(teams),
            "rho": strength.RHO}


def test_blend_models_mixes_on_team_intersection():
    goals = _model(["id:1", "id:2", "id:3"], ["A", "B", "C"], [1.0, 0.0, -1.0], [0.2, 0.0, -0.2])
    xg = _model(["id:1", "id:2"], ["A", "B"], [0.0, 1.0], [0.0, 0.4], adv=0.4)

    out = strength.blend_models(goals, xg, 0.25)

    assert out["teams"] == ["id:1", "id:2"]
    assert out["dropped_teams"] == ["id:3"]
    assert out["alpha"] == [pytest.approx(0.75), pytest.approx(0.25)]
    assert out["home_adv"] == pytest.approx(0.25)
    assert out["rho"] == strength.RHO      # 混合模型输出离散比分，DC 修正仍适用
    assert out["blend_weight"] == 0.25


def test_blend_weight_zero_reproduces_goal_model():
    goals = _model(["id:1", "id:2"], ["A", "B"], [1.0, -1.0], [0.2, -0.2])
    xg = _model(["id:1", "id:2"], ["A", "B"], [0.0, 0.0], [0.0, 0.0])
    assert strength.blend_models(goals, xg, 0.0)["alpha"] == [1.0, -1.0]


def test_blend_rejects_weight_out_of_range():
    m = _model(["id:1"], ["A"], [0.0], [0.0])
    with pytest.raises(ValueError):
        strength.blend_models(m, m, 1.5)


def test_report_gives_model_metrics_on_the_baseline_subset(monkeypatch):
    """模型覆盖全部场次、基线只覆盖有赔率的子集，两者直接相减是错的。
    实测供应商赔率非随机缺失（2021-2022 完全没有），必须同子集比较。"""
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.6, 0.2, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    matches = [
        {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "1", "odds": []},  # 频率基线用
        # 有赔率的一场：模型猜对；无赔率的一场：模型猜错 —— 两个子集必然不同
        {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 2, "league": "1", "odds": [],
         "provider_market": [0.6, 0.2, 0.2]},
        {"home": "A", "away": "B", "gh": 0, "ga": 1, "day": 2, "league": "1", "odds": []},
    ]

    rep = strength.validate(matches, model, from_day=2,
                            baseline_key="provider_market", baseline_label="provider_market")

    assert rep["model"]["n"] == 2
    assert rep["model_on_baseline_subset"]["n"] == 1
    assert rep["model_on_baseline_subset"]["brier_mean"] < rep["model"]["brier_mean"]
    assert rep["provider_market"]["n"] == 1


def test_model_on_baseline_subset_is_unavailable_without_odds(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    rows = [{"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "1", "odds": []},
            {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 2, "league": "1", "odds": []}]
    rep = strength.validate(rows, model, from_day=2)
    assert rep["model_on_baseline_subset"]["status"] == "UNAVAILABLE"


def test_report_survives_when_no_matches_precede_from_day(monkeypatch):
    """从样本第一天就开始验证时，频率基线无从算起——旧版在此除零崩溃。"""
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    rep = strength.validate([{"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "1", "odds": []}],
                            model, from_day=1)
    assert rep["frequency_baseline"]["probs"] == [0.3333, 0.3333, 0.3333]
