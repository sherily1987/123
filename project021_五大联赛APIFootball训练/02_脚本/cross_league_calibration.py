#!/usr/bin/env python3
"""跨联赛标尺校准：用欧战结果检验并校正各国内联赛强度评分的可比性。

## 为什么需要

`fit_model` 把每个联赛的 α 重归一化到均值 0。于是英超中游队和比甲中游队的 α 都≈0，
但两者实力显然不同——**联赛之间的整体强度差在国内比赛里根本不可辨识**。
欧战是唯一让两个联赛的球队直接交手的样本，因此是估计这个偏移的唯一数据来源。

## 模型

给每个联赛一个标量强度偏移 s_L（Σs=0 为归一化约束）：

    λ_主 = exp(adv + (α_主 + s_主联赛) + (β_客 − s_客联赛))
    λ_客 = exp(      (α_客 + s_客联赛) + (β_主 − s_主联赛))

β 越大表示失球越多，故强联赛的球队 β 要**减**去 s。
α/β 取自各国内联赛已拟合模型并固定不动，只拟合 adv 与 s_L。

## 对照

- **naive**：只拟合欧战主场优势 adv，全部 s=0（即直接把各联赛评分当同一把尺子）
- **calibrated**：同时拟合 adv 与 s_L

两者都拟合 adv，这样改善才能干净地归因到"联赛偏移"，而不是主场优势校准。

时间切分：cutoff 之前的欧战比赛拟合偏移，之后的用于评估；国内模型也只用 cutoff 之前的
比赛拟合，避免任何未来信息。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

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

# 参与校准的国内联赛由 catalog + 标准化目录**自动发现**，不再手工维护——
# 规模到 40+ 个联赛后手工清单必然遗漏。每多一个欧战常客联赛，可用样本与偏移精度都提高。
HERE = Path(__file__).resolve().parent

# 三项俱乐部洲际赛事都是偏移的估计样本。欧协联参赛队多来自中小联赛，
# 对本方法的样本增益最大（欧冠/欧联以强队为主，覆盖不到弱旅）。
UEFA = ["uefa_champions_league", "uefa_europa_league", "europe_uefa_conference_league"]
HALF_LIFE = 500.0
# 欧战场次低于此数的联赛不单独给自由参数，合用一个共享偏移。
# 实测波黑只有 2 场、拉脱维亚/立陶宛各 4 场，用它们各估一个参数得到的是任意值，
# 且 Σs=0 的约束会让这些噪声参数污染其余联赛的偏移。
MIN_UEFA_MATCHES = 40
POOLED = "_pooled_small"


def discover_domestic(project: Path) -> list[dict]:
    """从 catalog 读 league_id，与标准化目录里实际存在的文件取交集。"""
    ids = {}
    for cat in sorted(HERE.glob("*.json")):
        try:
            data = json.loads(cat.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for lg in (data.get("leagues") or []):
            if lg.get("kind", "domestic_league") == "domestic_league" and lg.get("note") != "women":
                ids[lg["slug"]] = lg["id"]
    # 五大联赛的 slug 未必出现在任何 catalog 里（最早是硬编码跑的），显式补上
    ids.update({"premier_league": 152, "la_liga": 302, "serie_a": 207,
                "bundesliga": 175, "ligue_1": 168})
    norm = project / "04_素材" / "标准化"
    return [{"id": lid, "slug": s} for s, lid in sorted(ids.items())
            if (norm / f"{s}_events_provider_market.jsonl").exists()]


def build_rating_table(project: Path, cutoff_day: int, shrinkage_k: float = 0.0) -> dict:
    """逐联赛拟合（只用 cutoff 之前的比赛），汇成 team_id -> (联赛, α, β)。

    ## 关于低样本球队与收缩（结论：默认不开，理由见下）

    `fit_model` 把 α 归一化到均值 0。低样本球队（升降级附加赛对手，实测苏超 22 队中
    8 队加权样本量 <10，Arbroath 2.08 场 α=-4.611；葡超 Torreense 1.99 场 α=-7.312）
    会把 α 均值拖低，使**正常球队的 α 被整体抬高**，联赛偏移再用大负数补偿。

    联赛内部这个平移会抵消（两队同联赛、同样平移）；跨联赛不抵消。

    ⚠️ **但收缩修不了它**：`apply_shrinkage` 为保持联赛整体进球水平做了再居中，
    **均值恒定不变**；而问题恰恰是"离群值把均值拖偏"，收缩只压缩离散度、不动均值，
    设计上就无能为力。内部验证集实测也选 k=0（0.5837，随 k 单调劣化到 0.5897）。

    真正的修法应是**用样本量加权的均值做归一化**，让 1~2 场的球队不参与定中心。
    但 α 与 β 的居中约定会与 (α+s)/(β−s) 的模型形式相互作用——对 α 整体平移 c 时，
    主队侧被 s 吸收、客队侧却反号，故不是无害的重参数化。改动影响面大，尚未验证。

    保留本参数是为了可复现地记录这一判断，默认 auto 会选出 k=0。
    单场跨联赛预测对 k 敏感（实测某场客胜概率在 60.6%~68.3% 间移动）而合计 Brier 几乎不变，
    因此**单场概率必须带上这一区间作为模型选择不确定性**。
    """
    table, per_league = {}, {}
    for lg in discover_domestic(project):
        src = project / "04_素材" / "标准化" / f"{lg['slug']}_events_provider_market.jsonl"
        if not src.exists():   # 自动发现已保证存在，此处兜底防止竞态
            continue
        matches = [m for m in strength.load_matches(src, league_id=lg["id"], require_odds=False)
                   if m["day"] < cutoff_day]
        if len(matches) < 200:
            continue
        model = strength.fit_model(matches, half_life=HALF_LIFE)
        if shrinkage_k:
            model = strength.apply_shrinkage(model, shrinkage_k)
        idx = strength.team_index(model)
        per_league[lg["slug"]] = {"n_matches": len(matches), "teams": len(model["teams"]),
                                 "home_adv": model["home_adv"]}
        for team, i in idx.items():
            if team in model["teams"]:
                table[team] = (lg["slug"], model["alpha"][i], model["beta"][i])
    return table, per_league


def load_uefa(project: Path, table: dict) -> list[dict]:
    rows = []
    for comp in UEFA:
        src = project / "04_素材" / "标准化" / f"{comp}_events_provider_market.jsonl"
        if not src.exists():
            continue
        for m in strength.load_matches(src, require_odds=False):
            if m["home"] in table and m["away"] in table:
                rows.append({**m, "comp": comp})
    return sorted(rows, key=lambda r: r["day"])


def league_groups(rows, table, min_matches: int = MIN_UEFA_MATCHES):
    """欧战场次不足的联赛归入共享组，返回 (联赛->组名, 组名列表, 逐联赛场次)。"""
    counts: dict[str, int] = {}
    for r in rows:
        for side in ("home", "away"):
            counts[table[r[side]][0]] = counts.get(table[r[side]][0], 0) + 1
    mapping = {lg: (lg if c >= min_matches else POOLED) for lg, c in counts.items()}
    groups = sorted(set(mapping.values()))
    return mapping, groups, counts


def fit_offsets(rows, table, leagues, calibrate: bool, mapping: dict | None = None):
    """拟合 adv（与可选的 s_L）。Σs=0 通过参数化为「前 n-1 个自由、最后一个取负和」实现。

    ``mapping`` 把联赛映射到参数组：样本不足的联赛共用一个偏移，
    避免用几场比赛去估一个自由参数。
    """
    mapping = mapping or {lg: lg for lg in leagues}
    li = {lg: i for i, lg in enumerate(leagues)}
    n = len(leagues)
    ah = np.array([table[r["home"]][1] for r in rows])
    bh = np.array([table[r["home"]][2] for r in rows])
    aa = np.array([table[r["away"]][1] for r in rows])
    ba = np.array([table[r["away"]][2] for r in rows])
    lh_idx = np.array([li[mapping[table[r["home"]][0]]] for r in rows])
    la_idx = np.array([li[mapping[table[r["away"]][0]]] for r in rows])
    gh = np.array([r["gh"] for r in rows], dtype=float)
    ga = np.array([r["ga"] for r in rows], dtype=float)

    def expand(p):
        adv = p[0]
        if not calibrate:
            return adv, np.zeros(n)
        free = p[1:]
        s = np.concatenate([free, [-free.sum()]])   # Σs = 0
        return adv, s

    def lam(p):
        adv, s = expand(p)
        sh, sa = s[lh_idx], s[la_idx]
        return np.exp(adv + (ah + sh) + (ba - sa)), np.exp((aa + sa) + (bh - sh))

    def neg_ll(p):
        lam_h, lam_a = lam(p)
        lam_h = np.maximum(lam_h, 1e-9); lam_a = np.maximum(lam_a, 1e-9)
        ll = gh * np.log(lam_h) - lam_h + ga * np.log(lam_a) - lam_a
        lt, _, _ = strength.tau_terms(lam_h, lam_a, gh, ga, strength.RHO)
        return float(-(ll.sum() + lt.sum()))

    p0 = np.zeros(1 + (n - 1 if calibrate else 0))
    p0[0] = 0.2
    res = minimize(neg_ll, p0, method="L-BFGS-B", options={"maxiter": 500})
    adv, s = expand(res.x)
    group_offsets = {lg: float(s[i]) for lg, i in li.items()}
    # 展开回逐联赛视图：共享组的成员都取该组的偏移
    offsets = {lg: group_offsets[grp] for lg, grp in mapping.items() if grp in group_offsets}
    offsets.update(group_offsets)
    return {"home_adv": float(adv), "offsets": offsets, "group_offsets": group_offsets,
            "converged": bool(res.success), "n_fit": len(rows)}


def evaluate(rows, table, params):
    out = []
    for r in rows:
        lh_league, ah, bh = table[r["home"]]
        la_league, aa, ba = table[r["away"]]
        sh = params["offsets"].get(lh_league, 0.0)
        sa = params["offsets"].get(la_league, 0.0)
        lam_h = math.exp(params["home_adv"] + (ah + sh) + (ba - sa))
        lam_a = math.exp((aa + sa) + (bh - sh))
        probs = strength.dc_one(strength.dc_matrix(lam_h, lam_a, strength.RHO))
        row = {"league": r["comp"], "day": r["day"], "model": probs,
               "actual_idx": 0 if r["gh"] > r["ga"] else (1 if r["gh"] == r["ga"] else 2)}
        if r.get("provider_market"):
            row["provider_market"] = r["provider_market"]
        out.append(row)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--fit-fraction", type=float, default=0.7)
    ap.add_argument("--shrinkage", default="auto",
                    help="低样本收缩强度 k；auto 表示在内部验证集上选（不看测试集）")
    ap.add_argument("--shrinkage-grid", type=float, nargs="*", default=[0.0, 2.0, 5.0, 10.0, 20.0])
    a = ap.parse_args()

    # 先用全窗口找出可用欧战比赛，再据此定 cutoff，最后按 cutoff 重拟合国内模型
    table_all, _ = build_rating_table(a.project, 10 ** 9)
    all_rows = load_uefa(a.project, table_all)
    if len(all_rows) < 200:
        raise SystemExit(f"可用欧战样本不足（{len(all_rows)} 场）")
    cutoff_day = all_rows[int(len(all_rows) * a.fit_fraction)]["day"]

    # k 在**内部验证集**上选：把 fit 窗口再切 70/30，绝不看测试集
    shrink_sweep = []
    if a.shrinkage == "auto":
        pre = [r for r in all_rows if r["day"] < cutoff_day]
        inner_cut = pre[int(len(pre) * 0.7)]["day"]
        for k in a.shrinkage_grid:
            tbl = build_rating_table(a.project, inner_cut, k)[0]
            rws = load_uefa(a.project, tbl)
            inner_fit = [r for r in rws if r["day"] < inner_cut]
            inner_val = [r for r in rws if inner_cut <= r["day"] < cutoff_day]
            if len(inner_fit) < 100 or len(inner_val) < 50:
                continue
            mp, grps, _ = league_groups(inner_fit, tbl)
            prm = fit_offsets(inner_fit, tbl, grps, calibrate=True, mapping=mp)
            scored = evaluate(inner_val, tbl, prm)
            bs = sum(sum((r["model"][i] - (1 if i == r["actual_idx"] else 0)) ** 2
                         for i in range(3)) for r in scored) / len(scored)
            shrink_sweep.append({"k": k, "n": len(scored), "brier": round(bs, 6)})
        if not shrink_sweep:
            raise SystemExit("内部验证样本不足，无法自动选 k；请显式传 --shrinkage")
        shrinkage_k = min(shrink_sweep, key=lambda x: x["brier"])["k"]
    else:
        shrinkage_k = float(a.shrinkage)

    table, per_league = build_rating_table(a.project, cutoff_day, shrinkage_k)
    rows = load_uefa(a.project, table)
    fit_rows = [r for r in rows if r["day"] < cutoff_day]
    test_rows = [r for r in rows if r["day"] >= cutoff_day]
    mapping, groups, uefa_counts = league_groups(fit_rows, table)
    pooled = sorted(lg for lg, g in mapping.items() if g == POOLED)
    leagues = groups

    naive = fit_offsets(fit_rows, table, leagues, calibrate=False, mapping=mapping)
    calib = fit_offsets(fit_rows, table, leagues, calibrate=True, mapping=mapping)

    result = {"cutoff": str(date.fromordinal(cutoff_day)), "leagues": leagues,
              "uefa_match_counts": dict(sorted(uefa_counts.items(), key=lambda x: -x[1])),
              "pooled_small_leagues": pooled, "min_uefa_matches": MIN_UEFA_MATCHES,
              "shrinkage_k": shrinkage_k, "shrinkage_selection": shrink_sweep,
              "domestic_fit": per_league, "n_fit": len(fit_rows), "n_test": len(test_rows),
              "naive": naive, "calibrated": calib, "test": {}}
    for label, params in (("naive", naive), ("calibrated", calib)):
        scored = evaluate(test_rows, table, params)
        rep = strength.build_report(scored, [{"gh": r["gh"], "ga": r["ga"], "day": r["day"]} for r in rows],
                                    cutoff_day, 0, "provider_market")
        result["test"][label] = {"n": rep["n"], "model": rep["model"],
                                 "provider_market": rep.get("provider_market"),
                                 "frequency_baseline": rep.get("frequency_baseline")}

    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"切分 {result['cutoff']}  拟合 {len(fit_rows)} 场  评估 {len(test_rows)} 场")
    if shrink_sweep:
        print("内部验证集选收缩 k： " + "  ".join(f"k={s['k']:g}:{s['brier']:.4f}" for s in shrink_sweep))
    print(f"采用 k={shrinkage_k:g}\n")
    print("联赛强度偏移 s_L（正=该联赛整体更强，Σs=0）:")
    for lg, v in sorted(calib["offsets"].items(), key=lambda x: -x[1]):
        print(f"  {lg:<28}{v:+.4f}")
    print(f"\n欧战主场优势 naive {naive['home_adv']:.4f}  calibrated {calib['home_adv']:.4f}\n")
    hdr = f"{'方案':<14}{'n':>5}{'Brier':>9}{'logloss':>10}{'准确率%':>9}"
    print(hdr); print("-" * len(hdr))
    for label in ("naive", "calibrated"):
        m = result["test"][label]["model"]
        print(f"{label:<14}{m['n']:>5}{m['brier_mean']:>9.4f}{m['log_loss']:>10.4f}{m['accuracy_pct']:>9.1f}")
    mk = result["test"]["naive"].get("provider_market") or {}
    fb = result["test"]["naive"].get("frequency_baseline") or {}
    if mk.get("brier_mean"):
        print(f"{'市场基线':<14}{mk['n']:>5}{mk['brier_mean']:>9.4f}{mk['log_loss']:>10.4f}{mk['accuracy_pct']:>9.1f}")
    if fb.get("brier_mean"):
        print(f"{'频率基线':<14}{fb['n']:>5}{fb['brier_mean']:>9.4f}{fb['log_loss']:>10.4f}")
    print(f"\n报告：{a.report}")


if __name__ == "__main__":
    main()
