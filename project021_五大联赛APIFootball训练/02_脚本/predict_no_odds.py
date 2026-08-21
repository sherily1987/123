#!/usr/bin/env python3
"""无赔率场次预测 + 可用性判据。

赔率基线**从不参与预测**，只用于评价。DC 团队强度是 model_first 路径，
只吃赛果与代理 xG。所以"没有赔率"不妨碍出预测——妨碍的是**判断这次预测可不可信**。

本脚本把此前散落在报告里的判据固化下来，输出预测的同时给出
`可用 / 降级 / 拒绝` 的结论与理由。

## 两套评分构造不可混用（这是踩过的坑）

- **同联赛对阵**：复刻回测协议——该联赛模型（half_life=500，若该联赛启用 xG 则
  按 w=0.4 混合），**不加收缩、不加偏移**。
- **跨联赛对阵**：复刻校准协议——纯进球模型 + 收缩 k + 联赛偏移，**不混 xG**。
  偏移是在这套构造上拟合的；用别的构造去套偏移会得到错误结果
  （实测某场客胜概率因此从 68% 虚高到 89%）。

## 可用性判据

1. **联赛档位**（由 full_backtest.json 的模型-市场差距实时计算，不硬编码）：
     A <0.010   B <0.018   C <0.030   D 其余或测试样本 <120
2. **跨联赛对阵降一档**——单标量偏移在两队都不是本联赛平均水平时会失真。
3. **顶级对决直接拒绝**：跨联赛且两队 α 都在各自联赛前 15% 或后 15%。
     实测欧超杯 PSG vs 维拉，模型主胜 34.8% 而市场 57.5%，差 22.7pp。
4. **低样本球队拒绝**：任一方 weighted_n < 10（升降级附加赛对手那类，评分不可信）。
5. 输出一律标 `market_dependency: UNAVAILABLE`，不得让下游误以为经过市场校准。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
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


calib = _load("cross_league_calibration", HERE / "cross_league_calibration.py")
strength = calib.strength

HALF_LIFE, XG_WEIGHT = 500.0, 0.4
# ⚠️ 2026-08-19 步骤4 实测：英超 half_life=120 的 tunning 结论（无 xG 口径）在带 xG 的
# 生产口径下无收益（full_backtest 实测 0.6214 vs 0.6202），保持默认 500，不覆盖。
LEAGUE_HALF_LIFE: dict[str, float] = {}
TIER_BOUNDS = ((0.010, "A"), (0.018, "B"), (0.030, "C"))
# 频率基线分档（比市场基线弱得多，阈值必须更严）：大幅跑赢才 A，打平/略差一律 D
FREQ_TIER_BOUNDS = ((-0.050, "A"), (-0.020, "B"), (0.0, "C"))
MIN_TEST_N = 120
MIN_WEIGHTED_N = 10.0
EXTREME_PCT = 0.15


def league_tiers(project: Path) -> dict:
    """由回测结果实时计算档位，避免与报告脱节。

    无市场基线（market=None，api-sports.io 源）的联赛改用频率基线分档，
    tier 加 F- 前缀（如 F-A），表示"基于频率基线，未经市场对比"。
    """
    path = project / "05_交付" / "full_backtest.json"
    if not path.exists():
        return {}
    out = {}
    for slug, v in json.loads(path.read_text(encoding="utf-8"))["leagues"].items():
        if not isinstance(v.get("model_subset"), float):
            continue
        if isinstance(v.get("market"), float):
            gap = v["model_subset"] - v["market"]
            basis = "market"
        elif isinstance(v.get("frequency"), float):
            gap = v["model_subset"] - v["frequency"]
            basis = "frequency"
        else:
            continue
        tier = "D"
        if v["n_subset"] >= MIN_TEST_N:
            if basis == "market":
                for bound, label in TIER_BOUNDS:
                    if gap < bound:
                        tier = label
                        break
            else:
                # 频率基线不看主客、极易跑赢，必须用更严阈值：大幅跑赢才 A，
                # 打平或略差（gap>=0）一律 D（与市场口径的 A/B/C 不可比）
                for bound, label in FREQ_TIER_BOUNDS:
                    if gap < bound:
                        tier = label
                        break
        if basis == "frequency":
            tier = f"F-{tier}"
        out[slug] = {"tier": tier, "gap": round(gap, 4), "n": v["n_subset"], "tier_basis": basis}
    return out


# 有完赛事件但没有 provider_market 文件的联赛（日职 api-sports：有 xG、收盘另挂）。
# 不得把收盘文件改名为 *_events_provider_market.jsonl。
EXTRA_EVENT_LEAGUES = (
    {"id": 98, "slug": "apisports_japan_j1_league"},
)


def event_path(project: Path, slug: str) -> Path:
    norm = project / "04_素材" / "标准化"
    market = norm / f"{slug}_events_provider_market.jsonl"
    if market.exists():
        return market
    events = norm / f"{slug}_events.jsonl"
    if events.exists():
        return events
    raise FileNotFoundError(f"no event file for {slug}")


def domestic_leagues(project: Path) -> list[dict]:
    seen = {lg["slug"]: lg for lg in calib.discover_domestic(project)}
    for lg in EXTRA_EVENT_LEAGUES:
        if lg["slug"] not in seen:
            try:
                event_path(project, lg["slug"])
            except FileNotFoundError:
                continue
            seen[lg["slug"]] = lg
    return list(seen.values())


def index_teams(project: Path) -> dict:
    """显示名 -> [(联赛 slug, league_id, 主键)]，重名会返回多个候选。"""
    out: dict[str, list] = {}
    for lg in domestic_leagues(project):
        src = event_path(project, lg["slug"])
        for m in strength.load_matches(src, league_id=lg["id"], require_odds=False):
            for side in ("home", "away"):
                out.setdefault(m[f"{side}_name"], [])
                entry = (lg["slug"], lg["id"], m[side])
                if entry not in out[m[f"{side}_name"]]:
                    out[m[f"{side}_name"]].append(entry)
    return out


def resolve(index: dict, query: str):
    exact = index.get(query)
    if exact:
        return exact
    hits = [(k, v) for k, v in index.items() if query.lower() in k.lower()]
    if not hits:
        return []
    hits.sort(key=lambda x: len(x[0]))
    return hits[0][1]


def fit_league(project: Path, slug: str, league_id, use_xg: bool, shrinkage_k: float):
    src = event_path(project, slug)
    hl = LEAGUE_HALF_LIFE.get(slug, HALF_LIFE)
    goals = strength.load_matches(src, league_id=league_id, require_odds=False)
    model = strength.fit_model(goals, half_life=hl)
    if shrinkage_k:
        model = strength.apply_shrinkage(model, shrinkage_k)
        return model
    if use_xg:
        xg_path = project / "04_素材" / "标准化" / f"{slug}_xg.jsonl"
        if xg_path.exists():
            xg_matches = strength.load_matches(src, league_id=league_id, require_odds=False,
                                               xg_input=xg_path)
            if len(xg_matches) >= 200:
                model = strength.blend_models(model, strength.fit_model(
                    xg_matches, half_life=hl, target="xg"), XG_WEIGHT)
    return model


def xg_enabled(project: Path, slug: str) -> bool:
    path = project / "05_交付" / "league_xg_plan.json"
    if not path.exists():
        return (project / "04_素材" / "标准化" / f"{slug}_xg.jsonl").exists()
    plan = json.loads(path.read_text(encoding="utf-8"))["leagues"]
    return bool((plan.get(slug) or {}).get("basis"))


SCORE_LAMBDA3 = 0.05
SCORE_TEMPERATURE = 1.30


def bp_score_matrix(lam_h, lam_a, lam3=SCORE_LAMBDA3, size=11):
    """无赔率比分：用已有 λ（可含代理 xG）摊双变量泊松，再温度缩放。"""
    ph = [math.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(size)]
    pa = [math.exp(-lam_a) * lam_a ** j / math.factorial(j) for j in range(size)]
    s_ph, s_pa = sum(ph), sum(pa)
    ph = [x / s_ph for x in ph]
    pa = [x / s_pa for x in pa]
    denom = max(lam_h * lam_a, 1e-12)
    raw = []
    for i, x in enumerate(ph):
        row = []
        for j, y in enumerate(pa):
            acc = 0.0
            for k in range(min(i, j) + 1):
                acc += math.comb(i, k) * math.comb(j, k) * math.factorial(k) * (lam3 / denom) ** k
            row.append(x * y * math.exp(-lam3) * acc)
        raw.append(row)
    tot = sum(sum(r) for r in raw) or 1.0
    m = [[v / tot for v in r] for r in raw]
    inv = 1.0 / SCORE_TEMPERATURE
    scaled = [[max(v, 0.0) ** inv for v in r] for r in m]
    st = sum(sum(r) for r in scaled) or 1.0
    return [[v / st for v in r] for r in scaled]


def dc_matrix(lam_h, lam_a, rho, size=11):
    ph = [math.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(size)]
    pa = [math.exp(-lam_a) * lam_a ** j / math.factorial(j) for j in range(size)]
    m = [[ph[i] * pa[j] for j in range(size)] for i in range(size)]
    m[0][0] *= 1 + lam_h * lam_a * rho
    m[1][0] *= 1 - lam_a * rho
    m[0][1] *= 1 - lam_h * rho
    m[1][1] *= 1 + rho
    total = sum(sum(r) for r in m)
    return [[x / total for x in r] for r in m]


def summarize(lam_h, lam_a, rho):
    m = dc_matrix(lam_h, lam_a, rho)
    scores = bp_score_matrix(lam_h, lam_a)
    n = len(m)
    home = sum(m[i][j] for i in range(n) for j in range(n) if i > j)
    draw = sum(m[i][i] for i in range(n))
    return {
        "lambda": [round(lam_h, 4), round(lam_a, 4)],
        "probs_1x2": [round(home, 4), round(draw, 4), round(1 - home - draw, 4)],
        "over25": round(sum(m[i][j] for i in range(n) for j in range(n) if i + j >= 3), 4),
        "btts": round(sum(m[i][j] for i in range(1, n) for j in range(1, n)), 4),
        "top_scores": [{"score": f"{i}-{j}", "p": round(p, 4)}
                       for p, i, j in sorted(((scores[i][j], i, j) for i in range(6) for j in range(6)),
                                             reverse=True)[:5]],
        "score_model": {
            "family": "bivariate_poisson",
            "lambda3": SCORE_LAMBDA3,
            "temperature": SCORE_TEMPERATURE,
            "lambda_source": "team_strength_optional_proxy_xg",
            "note": "1X2 仍用 DC 矩阵；比分格子用 BP+T。生产 market_only 比分未改。",
        },
    }


def percentile(model, key) -> float:
    idx = strength.team_index(model)[key]
    alphas = sorted(model["alpha"])
    return alphas.index(model["alpha"][idx]) / max(len(alphas) - 1, 1)


_TIER_RANK = {"A": 0, "F-A": 1, "B": 2, "F-B": 3, "C": 4, "F-C": 5, "D": 6, "F-D": 7}
_TIER_DOWN = {"A": "B", "B": "C", "C": "D", "D": "D"}


def verdict(tiers, home_lg, away_lg, cross, extremes, low_n):
    reasons = []
    t_home = (tiers.get(home_lg) or {}).get("tier", "D")
    t_away = (tiers.get(away_lg) or {}).get("tier", "D")
    tier = t_home if _TIER_RANK[t_home] <= _TIER_RANK[t_away] else t_away
    reasons.append(f"联赛档位取较差者：{home_lg}={t_home}, {away_lg}={t_away} -> {tier}")
    if cross:
        pfx = "F-" if tier.startswith("F-") else ""
        tier = pfx + _TIER_DOWN[tier[2:] if pfx else tier]
        reasons.append("跨联赛对阵，降一档（单标量偏移在两队非本联赛平均水平时失真）")
    if low_n:
        return "拒绝", reasons + [f"低样本球队：{low_n}（weighted_n<{MIN_WEIGHTED_N:g}，评分不可信）"]
    if cross and extremes:
        return "拒绝", reasons + [
            f"跨联赛且双方都是各自联赛的极端档（{extremes}）；"
            "实测欧超杯 PSG vs 维拉此情形下模型与市场差 22.7pp"]
    if tier == "D":
        return "拒绝", reasons + ["档位 D：无市场兜底时不建议单独使用"]
    if tier == "F-D":
        return "拒绝", reasons + ["档位 F-D：无市场基线且未跑赢频率基线，不建议使用"]
    if tier == "C":
        return "降级", reasons + ["档位 C：只看方向，不要采用具体数值"]
    if tier == "F-C":
        return "降级", reasons + ["档位 F-C：只看方向，不要采用具体数值（且无市场基线，置信度更低）"]
    if tier.startswith("F-"):
        reasons.append("⚠️ 联赛无赛前赔率基线，分档基于频率基线对比，未经过市场验证，置信度低于市场对比联赛")
    return "可用", reasons


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--away", required=True)
    ap.add_argument("--neutral", action="store_true", help="中立场（欧超杯、决赛等），主场优势置零")
    ap.add_argument("--calibration", type=Path, help="跨联赛偏移报告，默认取 05_交付/cross_league_calibration_all.json")
    ap.add_argument("--output", type=Path)
    a = ap.parse_args()

    tiers = league_tiers(a.project)
    index = index_teams(a.project)
    hs, aws = resolve(index, a.home), resolve(index, a.away)
    for label, hits, q in (("主队", hs, a.home), ("客队", aws, a.away)):
        if not hits:
            raise SystemExit(f"{label} 未在任何联赛模型中找到：{q}")
        if len(hits) > 1:
            raise SystemExit(f"{label} 名称有歧义，命中多支球队：{q} -> {hits}；请改用主键（如 id:80）")
    (h_slug, h_id, h_key), (a_slug, a_id, a_key) = hs[0], aws[0]
    cross = h_slug != a_slug

    if cross:
        cal_path = a.calibration or a.project / "05_交付" / "cross_league_calibration_all.json"
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        k = float(cal.get("shrinkage_k") or 0.0)
        offsets = cal["calibrated"]["offsets"]
        adv = 0.0 if a.neutral else float(cal["calibrated"]["home_adv"])
        mh = fit_league(a.project, h_slug, h_id, use_xg=False, shrinkage_k=k)
        ma = fit_league(a.project, a_slug, a_id, use_xg=False, shrinkage_k=k)
        ih, ia = strength.team_index(mh)[h_key], strength.team_index(ma)[a_key]
        sh, sa = offsets.get(h_slug, 0.0), offsets.get(a_slug, 0.0)
        lam_h = math.exp(adv + (mh["alpha"][ih] + sh) + (ma["beta"][ia] - sa))
        lam_a = math.exp((ma["alpha"][ia] + sa) + (mh["beta"][ih] - sh))
        ph, pa_ = percentile(mh, h_key), percentile(ma, a_key)
        extremes = (f"{a.home} {ph:.0%} / {a.away} {pa_:.0%}"
                    if (ph > 1 - EXTREME_PCT and pa_ > 1 - EXTREME_PCT)
                    or (ph < EXTREME_PCT and pa_ < EXTREME_PCT) else None)
        wn = {a.home: mh["weighted_n"][ih], a.away: ma["weighted_n"][ia]}
        basis = {"mode": "cross_league", "shrinkage_k": k, "offsets": {h_slug: sh, a_slug: sa},
                 "home_adv": adv, "xg": False,
                 "note": "复刻校准协议：纯进球模型+收缩+偏移，不混 xG"}
    else:
        model = fit_league(a.project, h_slug, h_id, use_xg=xg_enabled(a.project, h_slug), shrinkage_k=0.0)
        idx = strength.team_index(model)
        ih, ia = idx[h_key], idx[a_key]
        adv = 0.0 if a.neutral else model["home_adv"]
        lam_h = math.exp(adv + model["alpha"][ih] + model["beta"][ia])
        lam_a = math.exp(model["alpha"][ia] + model["beta"][ih])
        extremes = None
        wn = {a.home: model["weighted_n"][ih], a.away: model["weighted_n"][ia]}
        basis = {"mode": "same_league", "league": h_slug, "xg": xg_enabled(a.project, h_slug),
                 "xg_weight": XG_WEIGHT, "home_adv": adv,
                 "note": "复刻回测协议：half_life=500，启用 xG 时按 w=0.4 混合，不加收缩"}

    low_n = [t for t, v in wn.items() if v < MIN_WEIGHTED_N]
    call, reasons = verdict(tiers, h_slug, a_slug, cross, extremes, low_n)
    result = {
        "home": a.home, "away": a.away, "neutral": a.neutral,
        "home_league": h_slug, "away_league": a_slug, "cross_league": cross,
        "verdict": call, "reasons": reasons,
        "league_tiers": {h_slug: tiers.get(h_slug), a_slug: tiers.get(a_slug)},
        "weighted_n": {k: round(v, 2) for k, v in wn.items()},
        "basis": basis, "market_dependency": "UNAVAILABLE",
        "prediction": summarize(lam_h, lam_a, strength.RHO),
    }
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    p = result["prediction"]
    mark = {"可用": "OK", "降级": "!!", "拒绝": "XX"}[call]
    print(f"[{mark}] {call}   {a.home}({h_slug}) vs {a.away}({a_slug})"
          f"{'  中立场' if a.neutral else ''}{'  跨联赛' if cross else ''}")
    for r in reasons:
        print(f"     - {r}")
    print(f"  λ {p['lambda'][0]:.2f} : {p['lambda'][1]:.2f}   总进球 {sum(p['lambda']):.2f}")
    print(f"  胜 {p['probs_1x2'][0]*100:.1f}%  平 {p['probs_1x2'][1]*100:.1f}%  负 {p['probs_1x2'][2]*100:.1f}%")
    print(f"  大2.5 {p['over25']*100:.1f}%   双方进球 {p['btts']*100:.1f}%")
    print("  比分 " + "  ".join(f"{s['score']} {s['p']*100:.1f}%" for s in p["top_scores"]))
    print(f"  市场依赖：UNAVAILABLE（本预测未经任何市场校准）")


if __name__ == "__main__":
    main()
