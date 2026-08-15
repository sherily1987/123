#!/usr/bin/env python3
"""诊断「模型在哪里输给市场」——为将来开 m3 提供靶子，本身不改任何概率文件。

全局结论已知：474 场配对 bootstrap 的 `模型-市场 Brier delta = +0.0082`，
95%CI [-0.0035, +0.0210] 跨 0——模型与市场统计上没有差别，点估计略差。
全局一个数说明不了该改什么，本脚本按四个维度拆开看：

  1. 按联赛：哪些联赛系统性拖后腿
  2. 按模型最大概率分箱：过度自信还是不够自信
  3. 按市场依赖度：market_only 与有独立信息的样本表现差多少
  4. 按快照时点：越接近开球是否越准

配对比较全部用**同场**样本（同一场既有模型概率又有市场概率），避免样本构成差异冒充效果差异。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

from fusion_backtest import (attach_clv, dedupe_snapshot_rows, load_jsonl,  # noqa: E402
                             resolve_path, score_record, select_primary_rows)
from runtime_paths import backtest_store  # noqa: E402


def brier(probs, actual_idx):
    return sum((p - (1.0 if i == actual_idx else 0.0)) ** 2 for i, p in enumerate(probs))


def paired_rows(root: Path):
    raw = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        row, _ = score_record(record, root)
        if row is not None:
            # score_record 不带市场依赖度，这里从原记录补上（按市场依赖度分组要用）
            row["market_dependency_pct"] = (record.get("output") or {}).get("market_dependency_pct")
            row["fusion_mode"] = record.get("mode")
            raw.append(row)
    rows, _ = dedupe_snapshot_rows(raw)
    rows = attach_clv(rows)
    rows = select_primary_rows(rows, "latest_before_kickoff")
    # 只保留同场既有模型概率又有市场概率的样本
    return [r for r in rows if r.get("market_probs") and r.get("actual_idx") is not None]


def summarize(bucket, bootstrap=2000, seed=20260816, min_n_for_ci=30):
    """同场配对比较；样本 >= min_n_for_ci 时给配对 bootstrap 的 95%CI。

    只报点估计会把「模型更差」说成定论——全局 delta 的 CI 就是跨 0 的。
    分组同样必须带不确定性，否则按 delta 排序的名次全是噪声。
    """
    n = len(bucket)
    if not n:
        return None
    diffs = [brier(r["probs"], r["actual_idx"]) - brier(r["market_probs"], r["actual_idx"])
             for r in bucket]
    model = sum(brier(r["probs"], r["actual_idx"]) for r in bucket) / n
    market = sum(brier(r["market_probs"], r["actual_idx"]) for r in bucket) / n
    stat = {"n": n, "model_brier": round(model, 4), "market_brier": round(market, 4),
            "delta": round(model - market, 4)}
    if n >= min_n_for_ci:
        rng = random.Random(seed)
        means = []
        for _ in range(bootstrap):
            means.append(sum(rng.choice(diffs) for _ in range(n)) / n)
        means.sort()
        lo = means[int(0.025 * bootstrap)]
        hi = means[int(0.975 * bootstrap) - 1]
        stat["delta_95ci"] = [round(lo, 4), round(hi, 4)]
        stat["excludes_zero"] = lo > 0 or hi < 0
    return stat


def group(rows, keyfunc):
    buckets = defaultdict(list)
    for row in rows:
        key = keyfunc(row)
        if key is not None:
            buckets[key].append(row)
    out = {}
    for key, bucket in buckets.items():
        stat = summarize(bucket)
        if stat:
            out[str(key)] = stat
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["delta"]))


def prob_band(row):
    top = max(row["probs"])
    edges = [0.0, 0.4, 0.5, 0.6, 0.7, 1.01]
    for i in range(len(edges) - 1):
        if edges[i] <= top < edges[i + 1]:
            return f"{edges[i]:.2f}-{edges[i+1]:.2f}"
    return None


def market_dependency_band(row):
    dep = row.get("market_dependency_pct")
    if dep is None:
        return "unknown"
    dep = float(dep)
    if dep >= 100:
        return "100 (market_only)"
    if dep >= 80:
        return "80-99"
    return "<80"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=str(backtest_store()))
    ap.add_argument("--output")
    a = ap.parse_args()

    rows = paired_rows(Path(a.store))
    report = {
        "schema_version": "fusion-precision-diagnosis-1.0",
        "paired_n": len(rows),
        "overall": summarize(rows),
        "by_league": group(rows, lambda r: r.get("league")),
        "by_model_top_prob_band": group(rows, prob_band),
        "by_market_dependency": group(rows, market_dependency_band),
        "by_snapshot": group(rows, lambda r: r.get("snapshot_type")),
        "note": "delta = 模型Brier - 市场Brier，正数表示模型更差。分组样本量小时不得据此下结论。",
    }

    # 关键分解：把「模型真正偏离市场」的样本单独摘出来。
    # 若剩下的样本 delta ≈ 0，说明全局劣势全部由这一小撮产生，靶子就是独立信息通路。
    low_dep = [r for r in rows if (r.get("market_dependency_pct") or 0) < 80]
    rest = [r for r in rows if (r.get("market_dependency_pct") or 0) >= 80]
    low_dep_band = [r for r in rows if prob_band(r) == "0.00-0.40"]
    report["decomposition"] = {
        "low_market_dependency(<80)": summarize(low_dep),
        "rest(>=80)": summarize(rest),
        "top_prob_band_0.00-0.40_all": summarize(low_dep_band),
        "top_prob_band_0.00-0.40_excluding_low_dependency": summarize(
            [r for r in low_dep_band if (r.get("market_dependency_pct") or 0) >= 80]),
        "note": "低依赖样本的联赛/快照分布见 low_market_dependency_profile；"
                "它们同时也是低概率分箱的主要来源，所以那一箱的劣势不是分箱本身的问题。",
    }
    profile = defaultdict(lambda: defaultdict(int))
    for row in low_dep:
        profile["league"][str(row.get("league"))] += 1
        profile["snapshot"][str(row.get("snapshot_type"))] += 1
        profile["prob_band"][str(prob_band(row))] += 1
    report["low_market_dependency_profile"] = {k: dict(v) for k, v in profile.items()}

    print(f"配对样本 {report['paired_n']} 场；总体 {report['overall']}")
    for section in ("by_league", "by_model_top_prob_band", "by_market_dependency", "by_snapshot"):
        print(f"\n== {section}（delta 由大到小，正数=模型更差）")
        for key, stat in report[section].items():
            ci = stat.get("delta_95ci")
            if ci is None:
                tail = "  ← n<30，不给CI，不得下结论"
            else:
                tail = f"  95%CI [{ci[0]:+.4f}, {ci[1]:+.4f}]"
                tail += "  ★显著" if stat.get("excludes_zero") else "  (跨0)"
            print(f"  {key:<24} n={stat['n']:<5} 模型={stat['model_brier']:.4f} "
                  f"市场={stat['market_brier']:.4f} delta={stat['delta']:+.4f}{tail}")

    print("\n== 关键分解")
    for key, stat in report["decomposition"].items():
        if isinstance(stat, dict) and "delta" in stat:
            ci = stat.get("delta_95ci")
            ci_text = f" 95%CI [{ci[0]:+.4f}, {ci[1]:+.4f}]" if ci else " (n<30)"
            print(f"  {key:<48} n={stat['n']:<5} delta={stat['delta']:+.4f}{ci_text}")

    if a.output:
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
