#!/usr/bin/env python3
"""代理 xG 混合权重扫描。

协议：滚动重拟合（step=30 天、half_life=500），每个时间片分别拟合"进球版"与
"xG 版"两套强度，再按权重 w 混合。**每片只拟合一次，六个 w 复用**。

w=0 与 w=1 都走 blend_models，因此球队集合完全一致，Brier 可直接比较；
另外单独跑一次"纯进球模型（不取交集）"作为生产基线参照。

纪律：w 在验证集上选，测试集只报结果。全程离线。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


strength = _load("team_strength", ROOT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "team_strength.py")
training = _load("train_five_leagues", Path(__file__).resolve().parent / "train_five_leagues.py")

LEAGUES = [
    {"id": 152, "slug": "premier_league", "name": "Premier League"},
    {"id": 302, "slug": "la_liga", "name": "La Liga"},
    {"id": 207, "slug": "serie_a", "name": "Serie A"},
    {"id": 175, "slug": "bundesliga", "name": "Bundesliga"},
    {"id": 168, "slug": "ligue_1", "name": "Ligue 1"},
]

WEIGHTS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
STEP_DAYS, HALF_LIFE, MIN_TRAIN = 30, 500.0, 200
BASELINE = ("provider_market", "provider_market")


def walk_forward_blend(goal_matches, xg_matches, from_day, to_day, weights):
    """一次遍历同时产出所有权重的评分行。"""
    window = [m for m in goal_matches if m["day"] >= from_day and (to_day is None or m["day"] < to_day)]
    if not window:
        return {}
    rows = {w: [] for w in weights}
    skips = {w: 0 for w in weights}
    end_day = max(m["day"] for m in window) + 1
    point = from_day
    while point < end_day:
        nxt = point + STEP_DAYS
        chunk = [m for m in window if point <= m["day"] < nxt]
        if chunk:
            train_g = [m for m in goal_matches if m["day"] < point]
            train_x = [m for m in xg_matches if m["day"] < point]
            if len(train_g) < MIN_TRAIN or len(train_x) < MIN_TRAIN:
                for w in weights:
                    skips[w] += len(chunk)
            else:
                # 两套模型与 w 无关，每片只拟合一次
                model_g = strength.fit_model(train_g, half_life=HALF_LIFE)
                model_x = strength.fit_model(train_x, half_life=HALF_LIFE, target="xg")
                for w in weights:
                    blended = strength.blend_models(model_g, model_x, w)
                    r, s = strength.score_rows(chunk, blended, *BASELINE)
                    rows[w].extend(r)
                    skips[w] += s
        point = nxt
    return {w: strength.build_report(rows[w], goal_matches, from_day, skips[w], BASELINE[1],
                                     extra={"blend_weight": w}) for w in weights}


def pure_goal_baseline(goal_matches, from_day, to_day):
    return strength.walk_forward_validate(goal_matches, from_day, to_day=to_day, step_days=STEP_DAYS,
                                          half_life=HALF_LIFE, baseline_key=BASELINE[0],
                                          baseline_label=BASELINE[1], min_train=MIN_TRAIN)


def summarize(rep):
    m = (rep or {}).get("model") or {}
    return {"n": rep.get("n"), "skip": rep.get("skip"), "brier": m.get("brier_mean"),
            "log_loss": m.get("log_loss"), "accuracy_pct": m.get("accuracy_pct"),
            "market": ((rep or {}).get(BASELINE[1]) or {}).get("brier_mean"),
            "frequency": ((rep or {}).get("frequency_baseline") or {}).get("brier_mean")}


def run_league(project: Path, league: dict) -> dict:
    src = project / "04_素材" / "标准化" / f"{league['slug']}_events_provider_market.jsonl"
    xg_path = project / "04_素材" / "标准化" / f"{league['slug']}_xg.jsonl"
    raw = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    first, second = training.time_cutoffs(raw)

    goal_matches = strength.load_matches(src, league_id=league["id"], require_odds=False)
    xg_matches = strength.load_matches(src, league_id=league["id"], require_odds=False, xg_input=xg_path)
    coverage = dict(strength.LAST_LOAD_STATS)

    val = walk_forward_blend(goal_matches, xg_matches, first, second, WEIGHTS)
    sweep = [{"w": w, **summarize(r)} for w, r in sorted(val.items())]
    scored = [s for s in sweep if isinstance(s["brier"], float)]
    best = min(scored, key=lambda s: s["brier"]) if scored else None

    test = walk_forward_blend(goal_matches, xg_matches, second, None, sorted({0.0, best["w"]} if best else {0.0}))
    return {"league": league, "cutoffs": {"validation_from": first, "test_from": second},
            "xg_coverage": coverage, "validation_sweep": sweep, "validation_best": best,
            "test": {str(w): summarize(r) for w, r in test.items()},
            "test_pure_goal_baseline": summarize(pure_goal_baseline(goal_matches, second, None))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()

    results = []
    for lg in LEAGUES:
        res = run_league(a.project, lg)
        results.append(res)
        b = res["validation_best"]
        w0 = next(s for s in res["validation_sweep"] if s["w"] == 0.0)
        cov = res["xg_coverage"]
        print(f"{lg['slug']:<16} xg缺失 {cov.get('xg_missing'):>4} 场  验证最优 w={b['w']:.1f} "
              f"B={b['brier']:.4f}（w=0 {w0['brier']:.4f}）", flush=True)

    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps({"weights": WEIGHTS, "step_days": STEP_DAYS, "half_life": HALF_LIFE,
                                    "protocol": "walk_forward，每片拟合进球版与xG版各一次后按w混合",
                                    "discipline": "w 在验证集上选，测试集只报结果",
                                    "leagues": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 测试集 ==")
    hdr = f"{'league':<16}{'配置':<22}{'n':>5}{'skip':>6}{'model':>9}{'market':>9}{'freq':>9}"
    print(hdr); print("-" * len(hdr))
    for res in results:
        b = res["validation_best"]
        rows = [("0.0", "w=0（纯进球混合口径）")]
        if b and b["w"] != 0.0:
            rows.append((f"{b['w']}", f"w={b['w']:.1f}（验证选出）"))
        for key, label in rows:
            t = res["test"].get(key) or {}
            f = lambda x: f"{x:>9.4f}" if isinstance(x, float) else f"{'--':>9}"
            print(f"{res['league']['slug']:<16}{label:<22}{t.get('n') or 0:>5}{t.get('skip') or 0:>6}"
                  f"{f(t.get('brier'))}{f(t.get('market'))}{f(t.get('frequency'))}")
        p = res["test_pure_goal_baseline"]
        f = lambda x: f"{x:>9.4f}" if isinstance(x, float) else f"{'--':>9}"
        print(f"{'':<16}{'纯进球（不取交集）':<22}{p.get('n') or 0:>5}{p.get('skip') or 0:>6}"
              f"{f(p.get('brier'))}{f(p.get('market'))}{f(p.get('frequency'))}")
    print(f"\n报告：{a.report}")


if __name__ == "__main__":
    main()
