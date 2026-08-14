#!/usr/bin/env python3
"""冷启动实验：低样本收缩强度 k × 未见球队兜底策略。

协议固定为滚动重拟合（step=30 天、half_life=500），只改冷启动相关开关，
以隔离本次改动的效果。配置在验证集上选，测试集只报结果。全程离线。

用法：
  python tune_cold_start.py --project <project021路径> --report <输出json>
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

SHRINKAGE = [0, 2, 5, 10, 20, 40]
FALLBACKS = [("off", False, False), ("league_mean", True, False), ("newcomer", True, True)]
STEP_DAYS, HALF_LIFE = 30, 500.0
BASELINE = ("provider_market", "provider_market")


def run(matches, from_day, to_day, k, use_fallback, newcomer):
    return strength.walk_forward_validate(
        matches, from_day, to_day=to_day, step_days=STEP_DAYS, half_life=HALF_LIFE,
        baseline_key=BASELINE[0], baseline_label=BASELINE[1],
        shrinkage_k=float(k), use_fallback=use_fallback, newcomer_prior=newcomer)


def summarize(rep):
    m = (rep or {}).get("model") or {}
    return {"n": rep.get("n"), "skip": rep.get("skip"), "fallback_rows": rep.get("fallback_rows"),
            "brier": m.get("brier_mean"), "log_loss": m.get("log_loss"), "accuracy_pct": m.get("accuracy_pct"),
            "market": ((rep or {}).get(BASELINE[1]) or {}).get("brier_mean"),
            "frequency": ((rep or {}).get("frequency_baseline") or {}).get("brier_mean")}


def run_league(project: Path, league: dict) -> dict:
    src = project / "04_素材" / "标准化" / f"{league['slug']}_events_provider_market.jsonl"
    raw = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    first, second = training.time_cutoffs(raw)
    matches = strength.load_matches(src, league_id=league["id"], require_odds=False)

    prior = strength.estimate_newcomer_prior([m for m in matches if m["day"] < second])
    sweep = []
    for label, use_fb, newcomer in FALLBACKS:
        for k in SHRINKAGE:
            s = summarize(run(matches, first, second, k, use_fb, newcomer))
            sweep.append({"fallback": label, "k": k, **s})

    scored = [s for s in sweep if isinstance(s["brier"], float)]
    # 覆盖面不同则 Brier 不可直接比：先在「都能预测」的口径下选，再看覆盖面收益
    best = min(scored, key=lambda s: s["brier"]) if scored else None
    current = next(s for s in sweep if s["fallback"] == "off" and s["k"] == 0)

    test = {"current": summarize(run(matches, second, None, 0, False, False))}
    if best:
        use_fb = best["fallback"] != "off"
        test["selected"] = summarize(run(matches, second, None, best["k"], use_fb, best["fallback"] == "newcomer"))
    return {"league": league, "cutoffs": {"validation_from": first, "test_from": second},
            "newcomer_prior": prior, "validation_sweep": sweep,
            "validation_current": current, "validation_best": best, "test": test}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()

    results = []
    for lg in LEAGUES:
        res = run_league(a.project, lg)
        results.append(res)
        b, c, p = res["validation_best"], res["validation_current"], res["newcomer_prior"]
        pr = f"α{p['alpha_offset']:+.3f} β{p['beta_offset']:+.3f} (n={p['n_matches']})" if p else "无样本"
        print(f"{lg['slug']:<16} 升班马先验 {pr:<34} 验证最优 k={b['k']:<3}fallback={b['fallback']:<12}"
              f"B={b['brier']:.4f}（现状 {c['brier']:.4f}）", flush=True)

    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps({"shrinkage": SHRINKAGE, "fallbacks": [f[0] for f in FALLBACKS],
                                    "step_days": STEP_DAYS, "half_life": HALF_LIFE,
                                    "protocol": "walk_forward，仅改冷启动开关",
                                    "leagues": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 测试集 ==")
    hdr = f"{'league':<16}{'配置':<24}{'n':>5}{'skip':>6}{'兜底':>6}{'model':>9}{'market':>9}{'freq':>9}"
    print(hdr); print("-" * len(hdr))
    for res in results:
        b = res["validation_best"]
        for key, label in (("current", "k=0 无兜底（现状）"), ("selected", f"k={b['k']} {b['fallback']}")):
            t = res["test"].get(key) or {}
            f = lambda x: f"{x:>9.4f}" if isinstance(x, float) else f"{'--':>9}"
            print(f"{res['league']['slug']:<16}{label:<24}{t.get('n') or 0:>5}{t.get('skip') or 0:>6}"
                  f"{t.get('fallback_rows') or 0:>6}{f(t.get('brier'))}{f(t.get('market'))}{f(t.get('frequency'))}")
    print(f"\n报告：{a.report}")


if __name__ == "__main__":
    main()
