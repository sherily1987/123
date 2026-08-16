#!/usr/bin/env python3
"""全联赛汇总回测（采纳配置）。

配置来自前几轮实验的结论，不再在此调参：
  - 协议：滚动重拟合，step=30 天，half_life=500（半衰期跨联赛不稳定，保留默认）
  - 代理 xG：统一 w=0.4（逐联赛选参已实测为负收益）
  - 冷启动收缩：关闭（实测净收益 0.0009，噪声量级）

## 两条不可违反的口径纪律

1. **模型必须与基线算在同一子集上**。模型覆盖全部场次、基线只覆盖有赔率的场次，
   直接相减是错的（供应商赔率非随机缺失，2021-2022 整体没有）。
   本脚本一律读 `model_on_baseline_subset`。
2. **两种市场基线不得合并**。`provider_market` 是开赛前最后一条报价取中位数；
   `closing_market` 是收盘均价，是市场最强形态、更难被击败。分组汇总。

全程离线，不发 API 请求。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


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
training = _load("train_five_leagues", HERE / "train_five_leagues.py")
blend = _load("tune_xg_blend", HERE / "tune_xg_blend.py")

STEP_DAYS, HALF_LIFE, XG_WEIGHT = 30, 500.0, 0.4

# 联赛清单由 04_素材/标准化 自动发现，不再硬编码——规模到 40+ 个联赛后手工维护不现实。
# 规则：
#   <slug>_events_provider_market.jsonl  -> apifootball 源，基线 provider_market
#   fd_<code>_events.jsonl               -> football-data.co.uk 源，基线 closing_market
#   xG 是否启用以 league_xg_plan.json 为准（文件存在与否不可作依据）
CONTINENTAL = ("uefa_champions_league", "uefa_europa_league", "europe_uefa_conference_league")


def discover(project: Path, catalogs: list[Path]) -> list[tuple]:
    """返回 (显示名, league_id, 事件文件, xg文件或None, 基线字段)。

    xG 是否启用**以 league_xg_plan.json 为准**，不能只看 xg 文件是否存在——
    早先手工试验留下的陈旧文件会绕过覆盖率门槛（实测乌超因此用了只覆盖 35%
    场次的 xG，评估集从 221 场缩到 120 场，差距被放大到 +0.0673）。
    计划文件缺失时才退回按文件存在判断。
    """
    norm = project / "04_素材" / "标准化"
    plan_path = project / "05_交付" / "league_xg_plan.json"
    plan = {}
    if plan_path.exists():
        plan = {k: v.get("basis") for k, v in
                json.loads(plan_path.read_text(encoding="utf-8"))["leagues"].items()}

    def xg_for(slug: str):
        if plan and not plan.get(slug):
            return None
        f = norm / f"{slug}_xg.jsonl"
        return f.name if f.exists() else None

    ids = {}
    for cat in catalogs:
        if cat.exists():
            for lg in json.loads(cat.read_text(encoding="utf-8"))["leagues"]:
                ids[lg["slug"]] = (lg["id"], lg.get("kind", "domestic_league"))
    out = []
    for ev in sorted(norm.glob("*_events_provider_market.jsonl")):
        slug = ev.name.replace("_events_provider_market.jsonl", "")
        if slug in CONTINENTAL:
            continue          # 洲际赛事不做独立训练，见跨联赛校准报告
        lid, kind = ids.get(slug, (None, "domestic_league"))
        if kind != "domestic_league":
            continue
        out.append((slug, lid, ev.name, xg_for(slug), "provider_market"))
    for ev in sorted(norm.glob("fd_*_events.jsonl")):
        slug = ev.name.replace("_events.jsonl", "")
        out.append((slug, slug.split("_")[1].upper(), ev.name, xg_for(slug), "closing_market"))
    return out


def backtest_league(project: Path, league_id, events_file: str, xg_file: str | None, baseline: str) -> dict:
    src = project / "04_素材" / "标准化" / events_file
    raw = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    _, test_from = training.time_cutoffs(raw)
    goals = strength.load_matches(src, league_id=league_id, require_odds=False)

    if xg_file:
        xg_matches = strength.load_matches(src, league_id=league_id, require_odds=False,
                                           xg_input=project / "04_素材" / "标准化" / xg_file)
        blend.BASELINE = (baseline, baseline)
        blend.STEP_DAYS, blend.HALF_LIFE = STEP_DAYS, HALF_LIFE
        rep = blend.walk_forward_blend(goals, xg_matches, test_from, None, [XG_WEIGHT])[XG_WEIGHT]
        config = f"滚动+xG w={XG_WEIGHT}"
    else:
        rep = strength.walk_forward_validate(goals, test_from, step_days=STEP_DAYS, half_life=HALF_LIFE,
                                             baseline_key=baseline, baseline_label=baseline)
        config = "滚动（无 xG 数据）"

    sub = rep.get("model_on_baseline_subset") or {}
    mkt = rep.get(baseline) or {}
    model_subset = sub.get("brier_mean")
    n_subset = sub.get("n")
    if not isinstance(model_subset, float):
        # 无市场基线联赛（api-sports.io 源无赛前赔率）：没有 baseline 子集，
        # 用全测试集指标代替，market 保持 None
        model_subset = (rep.get("model") or {}).get("brier_mean")
        n_subset = rep.get("n")
    return {
        "config": config, "baseline": baseline, "test_from": test_from,
        "n_all": rep.get("n"), "skip": rep.get("skip"),
        "model_all": (rep.get("model") or {}).get("brier_mean"),
        "n_subset": n_subset, "model_subset": model_subset,
        "market": mkt.get("brier_mean"),
        "frequency": (rep.get("frequency_baseline") or {}).get("brier_mean"),
        "accuracy_pct": (rep.get("model") or {}).get("accuracy_pct"),
        "log_loss": (rep.get("model") or {}).get("log_loss"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--min-test", type=int, default=60, help="测试集少于该场次的联赛只记录不参与汇总")
    ap.add_argument("--only", nargs="*", help="只回测这些 slug（如 fd_d2 fd_usa apisports_netherlands_eerste_divisie）")
    a = ap.parse_args()

    catalogs = sorted((HERE).glob("*catalog*.json")) + sorted(HERE.glob("all_leagues_batch*.json"))
    leagues = discover(a.project, catalogs)
    if a.only:
        allow = set(a.only)
        leagues = [row for row in leagues if row[0] in allow]
    print(f"自动发现 {len(leagues)} 个可回测联赛\n")

    results = {}
    for name, lid, ev, xg, baseline in leagues:
        try:
            r = backtest_league(a.project, lid, ev, xg, baseline)
        except Exception as exc:
            print(f"{name:<40}跳过：{type(exc).__name__} {str(exc)[:60]}", flush=True)
            continue
        if not isinstance(r.get("model_subset"), float):
            print(f"{name:<40}跳过：模型子集不可用", flush=True)
            continue
        r["no_market"] = not isinstance(r.get("market"), float)
        r["thin"] = r["n_subset"] < a.min_test
        results[name] = r
        if r["no_market"]:
            gap_freq = (r["model_subset"] - r["frequency"]) if isinstance(r.get("frequency"), float) else None
            flag = "  ⚠样本薄" if r["thin"] else ""
            gtxt = f"  差(频率) {gap_freq:+.4f}" if gap_freq is not None else ""
            print(f"{name:<40}n={r['n_subset']:<5}模型 {r['model_subset']:.4f}  "
                  f"无市场基线（频率 {r['frequency']:.4f}{gtxt}）{flag}", flush=True)
            continue
        flag = "  ⚠样本薄" if r["thin"] else ""
        print(f"{name:<40}n={r['n_subset']:<5}模型 {r['model_subset']:.4f}  "
              f"基线 {r['market']:.4f}  差 {r['model_subset'] - r['market']:+.4f}{flag}", flush=True)

    groups = {}
    for name, r in results.items():
        if r.get("thin") or r.get("no_market"):
            continue          # 样本过薄/无市场基线的联赛不进市场口径汇总（后者见下方 no_mkt 组）
        g = groups.setdefault(r["baseline"], {"n": 0, "model": 0.0, "market": 0.0, "freq": 0.0, "leagues": []})
        n = r["n_subset"]
        g["n"] += n
        g["model"] += n * r["model_subset"]
        g["market"] += n * r["market"]
        g["freq"] += n * r["frequency"]
        g["leagues"].append(name)
    summary = {k: {"leagues": v["leagues"], "n": v["n"],
                   "model": round(v["model"] / v["n"], 4), "market": round(v["market"] / v["n"], 4),
                   "frequency": round(v["freq"] / v["n"], 4),
                   "gap": round((v["model"] - v["market"]) / v["n"], 4)} for k, v in groups.items()}
    # 无市场基线联赛（api-sports.io 源，无赛前赔率）单独分组：只与频率基线对比，不混入市场口径
    no_mkt = {"n": 0, "model": 0.0, "freq": 0.0, "leagues": []}
    for name, r in results.items():
        if r.get("thin") or not r.get("no_market"):
            continue
        n = r["n_subset"]
        no_mkt["n"] += n
        no_mkt["model"] += n * r["model_subset"]
        no_mkt["freq"] += n * r["frequency"]
        no_mkt["leagues"].append(name)
    if no_mkt["leagues"]:
        summary["no_market"] = {"leagues": no_mkt["leagues"], "n": no_mkt["n"],
                                "model": round(no_mkt["model"] / no_mkt["n"], 4),
                                "market": None,
                                "frequency": round(no_mkt["freq"] / no_mkt["n"], 4),
                                "gap_vs_frequency": round((no_mkt["model"] - no_mkt["freq"]) / no_mkt["n"], 4)}

    payload = {"config": {"step_days": STEP_DAYS, "half_life": HALF_LIFE, "xg_weight": XG_WEIGHT,
                          "shrinkage": "off", "metric_basis": "model_on_baseline_subset"},
               "leagues": results, "summary_by_baseline": summary}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n== 分口径汇总（两种市场基线不可合并；no_market 无赛前赔率，只比频率基线）==")
    for k, v in summary.items():
        if k == "no_market":
            print(f"  无市场基线（{len(v['leagues'])} 个联赛，{v['n']} 场）"
                  f"  模型 {v['model']:.4f}  频率基线 {v['frequency']:.4f}  差 {v['gap_vs_frequency']:+.4f}")
            continue
        label = "赛前快照" if k == "provider_market" else "收盘线"
        print(f"  {label}（{len(v['leagues'])} 个联赛，{v['n']} 场）"
              f"  模型 {v['model']:.4f}  市场 {v['market']:.4f}  差 {v['gap']:+.4f}  频率基线 {v['frequency']:.4f}")
    print(f"\n报告：{a.report}")


if __name__ == "__main__":
    main()
