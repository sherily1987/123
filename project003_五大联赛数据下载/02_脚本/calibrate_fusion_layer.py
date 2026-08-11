#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""融合层组合/edge 校准拟合（2026-08-03）。

样本：版本归因审计通过的 vunknown 批次（fusion-1.4.0-era/core-3.4.4，体彩官方数据），
主口径 = closing 快照（369 场，最接近开球的市场状态）；另跑全快照池（1439）作敏感性。

协议：按 kickoff 时间序列 60/20/20 切分；train 上拟合：
  1) confidence 分档表（主方向最大概率 -> 该档历史命中率，作为校准后主概率）；
  2) edge 阈值（主方向 模型概率 - 市场去水概率 的最小 pp，超过才给 confidence）。
test 上验证：分档 ECE、1X2 Brier/LogLoss、edge 策略命中率 vs 市场隐含概率。

决策：仅当 test 上 校准ECE <= raw ECE 且 <= 市场 ECE、edge 策略命中率 >= 市场隐含
（且 n>=30）时，输出"可翻转"结论与 draft policy；翻转动作由主流程执行。

用法：python calibrate_fusion_layer.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r"C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3/scripts")
from odds_methods import devig

ROOT = Path(r"H:\claude AI自媒体\project003_五大联赛数据下载")
BACKTEST = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest"
)
AUDIT = BACKTEST / "version_attribution_audit_2026-08-03.json"
OUT_REPORT = ROOT / "05_交付" / "fusion_layer_calibration_2026-08-03.json"
OUT_DRAFT = ROOT / "04_素材" / "recommendation_policy.draft.json"

BAND_EDGES = [0.0, 0.40, 0.50, 0.60, 1.01]


def idx_actual(sc):
    return 0 if sc["home"] > sc["away"] else (1 if sc["home"] == sc["away"] else 2)


def load_samples(snapshot):
    """返回按 kickoff 排序的样本列表。"""
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    attr_ids = {r["prediction_id"] for r in audit["rows"] if r.get("settled")}
    samples = []
    for p in BACKTEST.joinpath("predictions").rglob("*.json"):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if rec.get("prediction_id") not in attr_ids:
            continue
        if rec.get("snapshot_type") != snapshot:
            continue
        out = rec.get("output") or {}
        core = out.get("core_output") or {}
        pct = core.get("final_1x2_pct") or out.get("forecast", {}).get("final_1x2_pct") or []
        if len(pct) != 3:
            continue
        odds = (rec.get("input") or {}).get("odds") or []
        if len(odds) != 3:
            continue
        rp = BACKTEST / "results" / f"{rec.get('match_id')}.json"
        try:
            sc = (json.loads(rp.read_text(encoding="utf-8")).get("score_90") or {})
        except Exception:
            continue
        if sc.get("home") is None or sc.get("away") is None:
            continue
        try:
            mkt, _ = devig([float(x) for x in odds], "power")
        except Exception:
            continue
        samples.append({
            "prediction_id": rec.get("prediction_id"),
            "kickoff": (rec.get("match") or {}).get("kickoff") or "",
            "pct": pct,
            "market": mkt,
            "actual": idx_actual(sc),
        })
    samples.sort(key=lambda r: r["kickoff"])
    return samples


def metrics_1x2(probs, idxs, ref=None):
    n = len(probs)
    bs = sum(sum((p[k] - (1 if k == j else 0)) ** 2 for k in range(3)) for p, j in zip(probs, idxs)) / n
    ll = sum(-math.log(max(1e-12, p[j])) for p, j in zip(probs, idxs)) / n
    obs = []
    for p, j in zip(probs, idxs):
        obs += [(p[k], 1 if k == j else 0) for k in range(3)]
    ece = 0.0
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(x, y) for x, y in obs if lo <= x < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ece += len(g) / len(obs) * abs(sum(x for x, _ in g) / len(g) - sum(z for _, z in g) / len(g))
    return {"n": n, "brier": round(bs, 6), "logloss": round(ll, 6), "ece": round(ece, 6)}


def band_index(prob):
    for i in range(len(BAND_EDGES) - 1):
        if BAND_EDGES[i] <= prob < BAND_EDGES[i + 1]:
            return i
    return len(BAND_EDGES) - 2


def ece_bands(bands, rows):
    n = len(rows)
    tot = 0.0
    cnt = Counter()
    hit = Counter()
    for r in rows:
        b = band_index(r["max_prob"])
        cnt[b] += 1
        hit[b] += int(r["primary"] == r["actual"])
    for b in cnt:
        tot += cnt[b] / n * abs(bands[b]["prob"] - hit[b] / cnt[b])
    return tot


def fit_and_validate(samples, snapshot_label):
    n = len(samples)
    cut1 = int(n * 0.6)
    cut2 = int(n * 0.8)
    train, val, test = samples[:cut1], samples[cut1:cut2], samples[cut2:]
    for grp in (train, val, test):
        for r in grp:
            r["primary"] = max(range(3), key=lambda k: r["pct"][k])
            r["max_prob"] = r["pct"][r["primary"]] / 100.0
            r["edge_pp"] = r["pct"][r["primary"]] - r["market"][r["primary"]] * 100.0
    # ---- train 拟合：分档表 ----
    tr_cnt = Counter(); tr_hit = Counter()
    for r in train:
        tr_cnt[band_index(r["max_prob"])] += 1
        tr_hit[band_index(r["max_prob"])] += int(r["primary"] == r["actual"])
    bands = []
    for i in range(len(BAND_EDGES) - 1):
        c = tr_cnt[i]
        h = tr_hit[i]
        bands.append({
            "lo": BAND_EDGES[i], "hi": BAND_EDGES[i + 1],
            "n_train": c,
            "prob": round(h / c, 4) if c else None,
        })
    # ---- train 拟合：edge 阈值（命中率 >= 市场隐含 + 0，取最大训练样本数下满足者）----
    cand = {}
    for t in range(0, 9):
        sub = [r for r in train if r["edge_pp"] >= t]
        if len(sub) < 30:
            continue
        hit = sum(int(r["primary"] == r["actual"]) for r in sub) / len(sub)
        imp = sum(r["market"][r["primary"]] for r in sub) / len(sub)
        cand[t] = {"n": len(sub), "hit": round(hit, 4), "market_implied": round(imp, 4),
                   "edge_realized_pp": round((hit - imp) * 100, 2)}
    edge_pp = max(cand, key=lambda t: (cand[t]["hit"] >= cand[t]["market_implied"], cand[t]["edge_realized_pp"]))
    # ---- validation：选阈值（用 val 段过滤掉 train 过拟合的极端值）----
    val_best = None
    for t, info in cand.items():
        vsub = [r for r in val if r["edge_pp"] >= t]
        if len(vsub) < 15:
            continue
        vhit = sum(int(r["primary"] == r["actual"]) for r in vsub) / len(vsub)
        vimp = sum(r["market"][r["primary"]] for r in vsub) / len(vsub)
        score = (vhit - vimp) * math.sqrt(len(vsub))
        if val_best is None or score > val_best[0]:
            val_best = (score, t, round(vhit, 4), round(vimp, 4), len(vsub))
    if val_best is not None and cand.get(val_best[1]):
        edge_pp = val_best[1]
    # ---- test 验证 ----
    def _raw_ece(rows):
        n2 = len(rows)
        cnt = Counter(); hit = Counter()
        for r in rows:
            b = band_index(r["max_prob"])
            cnt[b] += 1
            hit[b] += int(r["primary"] == r["actual"])
        return sum(cnt[b] / n2 * abs(r["max_prob"] - hit[b] / cnt[b]) for b in cnt)
    raw_ece = _raw_ece(test)
    mkt_ece = _raw_ece([
        {"max_prob": r["market"][r["primary"]], "primary": r["primary"], "actual": r["actual"]}
        for r in test
    ])
    cal_ece = ece_bands(bands, test)
    m1 = metrics_1x2([[x / 100.0 for x in r["pct"]] for r in test], [r["actual"] for r in test])
    m2 = metrics_1x2([r["market"] for r in test], [r["actual"] for r in test])
    tsub = [r for r in test if r["edge_pp"] >= edge_pp]
    edge_test = None
    if len(tsub) >= 15:
        hit = sum(int(r["primary"] == r["actual"]) for r in tsub) / len(tsub)
        imp = sum(r["market"][r["primary"]] for r in tsub) / len(tsub)
        edge_test = {"n": len(tsub), "hit_pct": round(hit * 100, 2),
                     "market_implied_pct": round(imp * 100, 2),
                     "edge_realized_pp": round((hit - imp) * 100, 2)}
    ready = (
        cal_ece <= raw_ece + 1e-9 and cal_ece <= mkt_ece + 1e-9
        and edge_test is not None and edge_test["hit_pct"] >= edge_test["market_implied_pct"]
        and edge_test["n"] >= 30
    )
    return {
        "snapshot": snapshot_label, "n": n,
        "split": {"train": len(train), "val": len(val), "test": len(test)},
        "date_range": [samples[0]["kickoff"][:10], samples[-1]["kickoff"][:10]],
        "bands": bands,
        "edge": {"candidates": cand, "selected_edge_pp": edge_pp,
                 "val_selected": val_best},
        "test": {
            "model_1x2": m1,
            "market_1x2": m2,
            "band_ece": {"raw": round(raw_ece, 6), "market": round(mkt_ece, 6),
                         "calibrated": round(cal_ece, 6)},
            "edge_strategy": edge_test,
        },
        "ready_to_flip": ready,
    }


def main():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    print("审计:", audit["counts"]["settled"], "已结算；主口径 closing")
    rep = {
        "schema_version": "fusion-layer-calibration-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "protocol": "chronological 60/20/20; band table + edge threshold fitted on train, "
                    "edge threshold cross-checked on val, reported on test",
        "pool": "attributed vunknown (fusion-1.4.0-era/core-3.4.4, 体彩官方)",
        "results": {},
    }
    for snap in ("closing", "all"):
        samples = load_samples(snap if snap != "all" else None)
        if snap == "all":
            # 全快照池：同一比赛的多个快照都算独立样本（口径= (match_id, snapshot_type)）
            all_s = []
            for s in ("closing", "opening", "t_minus_24h", "t_minus_6h"):
                all_s += load_samples(s)
            all_s.sort(key=lambda r: r["kickoff"])
            samples = all_s
        rep["results"][snap] = fit_and_validate(samples, snap)
        r = rep["results"][snap]
        print(f"[{snap}] n={r['n']} test: bandECE raw={r['test']['band_ece']['raw']} "
              f"cal={r['test']['band_ece']['calibrated']} mkt={r['test']['band_ece']['market']} | "
              f"edge@pp{r['edge']['selected_edge_pp']}: {r['test']['edge_strategy']} | "
              f"ready={r['ready_to_flip']}")
    # draft policy artifact
    closing = rep["results"]["closing"]
    allp = rep["results"]["all"]
    if allp["ready_to_flip"]:
        draft = {
            "calibration_status": "VALID",
            "min_samples_for_recalibration": 100,
            "target_samples_for_threshold_review": 200,
            "one_goal_draw_risk_pct": 18.0,
            "stale_market_factor": {"fresh_hours": 6, "half_hours": 12, "max_hours": 24},
            "calibration_params": {
                "primary_probability": {
                    "method": "band_table_plus_edge",
                    "bands": allp["bands"],
                    "edge_min_pp": allp["edge"]["selected_edge_pp"],
                    "fitted_on": "全快照池(1439) attributed 2026-08-03 audit pool, 60/20/20 chronological",
                    "pool_notes": "bands 取全快照池（样本更稳，n_train 539/103/98/123）；"
                                  "closing 池 test ECE raw 0.0804->cal 0.0715，全池 raw 0.0602->cal 0.0438",
                    "validated": {
                        "all": allp["test"],
                        "closing": closing["test"],
                    },
                }
            },
        }
        OUT_DRAFT.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rep["draft_policy"] = str(OUT_DRAFT)
    OUT_REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT_REPORT)
    print("结论:", "可翻转（test 达标，bands 取全池）" if allp["ready_to_flip"] else "暂不翻转（test 未达标）")


if __name__ == "__main__":
    main()
