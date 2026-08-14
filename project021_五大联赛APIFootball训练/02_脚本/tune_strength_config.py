#!/usr/bin/env python3
"""五大联赛团队强度配置调参：半衰期扫描 + 固定拟合 vs 滚动重拟合。

纪律：**所有配置在验证集上选，测试集只报最终结果**，不得用测试集挑参数。
全程离线，不发任何 API 请求。

用法：
  python tune_strength_config.py --project <project021路径> --report <输出json>
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

HALF_LIVES = [120, 180, 250, 365, 500, 750, 1100]
STEP_DAYS = 30
BASELINE = ("provider_market", "provider_market")
DEFAULT_HALF_LIFE = 500.0


def evaluate(matches, mode, half_life, from_day, to_day):
    """按模式跑一次验证；fixed=一次拟合，walk_forward=按月重拟合。"""
    if mode == "fixed":
        model = strength.fit_model([m for m in matches if m["day"] < from_day], half_life=half_life)
        return strength.validate(matches, model, from_day, to_day=to_day,
                                 baseline_key=BASELINE[0], baseline_label=BASELINE[1])
    return strength.walk_forward_validate(matches, from_day, to_day=to_day, step_days=STEP_DAYS,
                                          half_life=half_life,
                                          baseline_key=BASELINE[0], baseline_label=BASELINE[1])


def brier(report):
    model = (report or {}).get("model") or {}
    return model.get("brier_mean")


def run_league(project: Path, league: dict) -> dict:
    src = project / "04_素材" / "标准化" / f"{league['slug']}_events_provider_market.jsonl"
    raw_rows = [json.loads(line) for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
    first, second = training.time_cutoffs(raw_rows)
    matches = strength.load_matches(src, league_id=league["id"], require_odds=False)

    sweep = []
    for mode in ("fixed", "walk_forward"):
        for hl in HALF_LIVES:
            rep = evaluate(matches, mode, float(hl), first, second)
            sweep.append({"mode": mode, "half_life": hl, "n": rep.get("n"), "skip": rep.get("skip"),
                          "brier": brier(rep), "log_loss": (rep.get("model") or {}).get("log_loss")})

    scored = [s for s in sweep if isinstance(s["brier"], float)]
    best = min(scored, key=lambda s: s["brier"]) if scored else None
    current = next((s for s in sweep if s["mode"] == "fixed" and s["half_life"] == DEFAULT_HALF_LIFE), None)

    # 测试集：只跑「现状默认」与「验证集选出的最优」两组，不再挑参
    test = {"current": evaluate(matches, "fixed", DEFAULT_HALF_LIFE, second, None)}
    if best:
        test["selected"] = evaluate(matches, best["mode"], float(best["half_life"]), second, None)
    return {"league": league, "cutoffs": {"validation_from": first, "test_from": second},
            "validation_sweep": sweep, "validation_current": current, "validation_best": best,
            "test": {k: {"n": v.get("n"), "skip": v.get("skip"),
                         "model": v.get("model"), BASELINE[1]: v.get(BASELINE[1]),
                         "frequency_baseline": v.get("frequency_baseline")}
                     for k, v in test.items()}}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()

    results = []
    for lg in LEAGUES:
        res = run_league(a.project, lg)
        results.append(res)
        b, c = res["validation_best"], res["validation_current"]
        print(f"{lg['slug']:<16} 验证最优 {b['mode']:<13}hl={b['half_life']:<5} B={b['brier']:.4f}"
              f"   （现状 fixed hl=500 B={c['brier']:.4f}）", flush=True)

    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps({"half_lives": HALF_LIVES, "step_days": STEP_DAYS,
                                    "discipline": "配置在验证集上选，测试集只报结果",
                                    "leagues": results}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 测试集：现状 vs 验证集选出的配置 ==")
    hdr = f"{'league':<16}{'配置':<26}{'n':>5}{'skip':>6}{'model':>9}{'market':>9}{'freq':>9}"
    print(hdr); print("-" * len(hdr))
    for res in results:
        b = res["validation_best"]
        for key, label in (("current", "fixed hl=500（现状）"),
                           ("selected", f"{b['mode']} hl={b['half_life']}")):
            t = res["test"].get(key) or {}
            m = (t.get("model") or {}).get("brier_mean")
            mk = (t.get(BASELINE[1]) or {}).get("brier_mean")
            fb = (t.get("frequency_baseline") or {}).get("brier_mean")
            f = lambda x: f"{x:>9.4f}" if isinstance(x, float) else f"{'--':>9}"
            print(f"{res['league']['slug']:<16}{label:<26}{t.get('n') or 0:>5}{t.get('skip') or 0:>6}{f(m)}{f(mk)}{f(fb)}")
    print(f"\n报告：{a.report}")


if __name__ == "__main__":
    main()
