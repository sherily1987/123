#!/usr/bin/env python3
"""重拟合 recommendation_policy.json 的 primary_probability band 表（P0-1）与 edge 门槛（P0-2）。

口径（与 fusion_backtest.py 一致）：
- 样本 = registry.jsonl 中每条有赛果的预测记录（同 match_id+snapshot 去重保留最新）
- 主方向 = argmax(final_1x2_pct)；max_prob = 主方向概率/100
- edge_pp = final_1x2_pct[primary] - market_prob_pct[primary]（百分点点）
- 命中 = 赛果 1X2 == primary
输出：
1) 按 max_prob 分箱的实际命中率（细分高概率段，替代原 0.6+ 合并 band）
2) 不同 edge_min_pp 门槛下的样本/命中率/对市场隐含的提升
只打印，不写文件；确认后由主流程写入 policy。
"""
from __future__ import annotations
import json
import math
from pathlib import Path

STORE = Path("C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/backtest")


def load_jsonl(path: Path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def find(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
        if isinstance(d, dict):
            d = d.get(k) or {}
    return default


def actual_1x2(h, a):
    return 0 if h > a else (1 if h == a else 2)


def main():
    rows = []
    seen = {}
    dropped = 0
    for e in load_jsonl(STORE / "registry.jsonl"):
        p = Path(e.get("path", ""))
        if not p.exists():
            continue
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rp = STORE / "results" / (e.get("match_id", "") + ".json")
        if not rp.exists():
            continue
        try:
            rs = json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            continue
        s90 = rs.get("score_90")
        if not isinstance(s90, dict) or s90.get("home") is None:
            continue
        out = rec.get("output") or {}
        core = out.get("core_output") or out
        fc = out.get("forecast") or core.get("forecast") or {}
        probs_pct = find(out, "final_1x2_pct", "final_1x2") or find(core, "final_1x2_pct") or fc.get("final_1x2_pct")
        mkt_pct = find(out, "market_prob_pct") or fc.get("market_prob_pct") or core.get("market_prob_pct")
        if not isinstance(probs_pct, list) or len(probs_pct) != 3:
            continue
        h, a = int(s90["home"]), int(s90["away"])
        idx = actual_1x2(h, a)
        primary = max(range(3), key=lambda i: probs_pct[i])
        max_prob = probs_pct[primary] / 100.0
        edge_pp = None
        if isinstance(mkt_pct, list) and len(mkt_pct) == 3:
            edge_pp = probs_pct[primary] - mkt_pct[primary]
        key = (e.get("match_id"), rec.get("snapshot_type") or "?")
        cur = seen.get(key)
        if cur is not None and (e.get("created_at") or "") <= (cur[1] or ""):
            dropped += 1
            continue
        seen[key] = (len(rows), e.get("created_at"))
        rows.append({
            "max_prob": max_prob, "hit": int(primary == idx),
            "edge_pp": edge_pp, "snapshot": rec.get("snapshot_type") or "?",
            "version": str((rec.get("model") or {}).get("version") or "?"),
            "match_id": e.get("match_id"),
        })

    print(f"有效样本: {len(rows)}（去重丢弃 {dropped}）\n")

    # ---- 1) max_prob 分箱：细分高概率段 ----
    bins = [
        (0.00, 0.35), (0.35, 0.40), (0.40, 0.45), (0.45, 0.50),
        (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
        (0.70, 0.80), (0.80, 1.01),
    ]
    print("=== 主方向概率分箱（实际命中率）===")
    print(f"{'band':<14}{'n':>6}{'avg_prob':>10}{'actual':>10}{'偏差pp':>8}")
    bin_stats = []
    for lo, hi in bins:
        g = [r for r in rows if lo <= r["max_prob"] < hi]
        if not g:
            continue
        n = len(g)
        ap = sum(r["max_prob"] for r in g) / n
        aa = sum(r["hit"] for r in g) / n
        bin_stats.append({"lo": lo, "hi": hi, "n": n, "avg_prob": ap, "actual": aa})
        print(f"[{lo:.2f},{hi:.2f}){n:>6}{ap*100:>9.1f}%{aa*100:>9.1f}%{(aa-ap)*100:>+8.1f}")

    # ---- 2) 候选 band 表（样本>=30 的段独立校准，不足的合并）----
    print("\n=== 候选 band 表（n>=30 独立；否则并入相邻）===")
    cand = []
    i = 0
    while i < len(bin_stats):
        b = bin_stats[i]
        if b["n"] >= 30:
            cand.append({"lo": b["lo"], "hi": b["hi"], "n": b["n"], "prob": round(b["actual"], 4)})
            i += 1
        else:
            # 合并到下一段
            j = i
            tot_n = 0
            wsum = 0.0
            while j < len(bin_stats) and tot_n < 30:
                tot_n += bin_stats[j]["n"]
                wsum += bin_stats[j]["n"] * bin_stats[j]["actual"]
                j += 1
            if tot_n > 0:
                cand.append({"lo": bin_stats[i]["lo"], "hi": bin_stats[j-1]["hi"],
                             "n": tot_n, "prob": round(wsum / tot_n, 4)})
            i = j
    for c in cand:
        print(f"  [{c['lo']:.2f},{c['hi']:.2f}) n={c['n']} prob={c['prob']}")

    # ---- 3) edge_min_pp 门槛扫描 ----
    print("\n=== edge_min_pp 门槛扫描（有 edge 的样本）===")
    print(f"{'edge>=':<8}{'n':>6}{'命中率':>9}{'市场隐含':>10}{'提升pp':>8}")
    for thr in [0, 2, 5, 8, 10]:
        g = [r for r in rows if r["edge_pp"] is not None and r["edge_pp"] >= thr]
        if not g:
            continue
        n = len(g)
        hit = sum(r["hit"] for r in g) / n
        # 市场隐含概率 = 主方向市场概率均值（近似）
        mkt_avg = sum(r["max_prob"] - (r["edge_pp"] or 0) / 100 for r in g) / n
        print(f">={thr:>3}pp{n:>6}{hit*100:>8.1f}%{mkt_avg*100:>9.1f}%{(hit-mkt_avg)*100:>+8.1f}")

    # ---- 4) 快照/版本分布（确认样本构成）----
    from collections import Counter
    print("\n=== 样本构成 ===")
    print("快照:", dict(Counter(r["snapshot"] for r in rows)))
    ver = Counter()
    for r in rows:
        v = r["version"]
        if "1.4" in v or "1.3" in v:
            ver["fusion-1.3/1.4"] += 1
        elif "1.2" in v:
            ver["fusion-1.2"] += 1
        else:
            ver[v or "?"] += 1
    print("版本:", dict(ver))


if __name__ == "__main__":
    main()
