#!/usr/bin/env python3
"""check_output.py — 批量预测输出核对：市场去水 vs 模型 1X2 vs 可靠性旗标。

用途：今日推荐/单场批量建模后，识别模型输出失真的场次（model_first λ 拟合
被推到极端的场次），按纪律降级为市场基线。2026-08-07 实战收编（10 场中
4 场失真：003/006/007 有 EXTREME_LAMBDA_ASYMMETRY 旗标、009 无旗标但
模型输出均匀分布偏离市场 24.7pp——全部降级）。

用法：
  python check_output.py --input input.json --model model_output.json
  # 默认读当前目录的 input.json + model_output.json

输出：
  1) 逐场对比表：编号/比赛/体彩HAD/市场去水%/模型1X2%/模式/严重旗标
  2) 背离检测：argmax 方向不一致 或 任一档偏差>15pp 的场次标 ⚠️，方向一致标 ✅

数字全部由脚本产生（power devig 与引擎同法）。
"""
from __future__ import annotations

import argparse
import json
import io
from pathlib import Path


def devig(odds):
    """比例去水（与 fusion_backtest.py 同法），返回 0-1 概率列表。"""
    q = [1.0 / x for x in odds]
    s = sum(q)
    return [x / s for x in q]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="input.json", help="批量输入 JSON（含 matches[]）")
    ap.add_argument("--model", default="model_output.json", help="fusion_predict 输出（含 results[]）")
    a = ap.parse_args()

    with io.open(a.input, encoding="utf-8-sig") as f:
        inp = json.load(f)
    with io.open(a.model, encoding="utf-8-sig") as f:
        out = json.load(f)

    rows = []
    for r in out.get("results", []):
        match_str = str(r.get("match", ""))
        im = next((m for m in inp.get("matches", [])
                   if m.get("home") in match_str and m.get("away") in match_str), None)
        num = (im or {}).get("sporttery_meta", {}).get("match_num", "?")
        odds = (im or {}).get("odds")
        mkt_pct = None
        if odds and len(odds) == 3:
            mkt_pct = [round(x * 100, 1) for x in devig([float(x) for x in odds])]
        fc = r.get("forecast") or {}
        fd = r.get("fusion_decision") or {}
        flags = [f for f in (r.get("reliability_flags") or []) if f.startswith("EXTREME")]
        rows.append({
            "num": num, "match": match_str, "odds": odds, "mkt_pct": mkt_pct,
            "model_pct": fc.get("final_1x2_pct"), "mode": r.get("mode"),
            "primary": fd.get("primary_outcome"), "top_gap_pp": fd.get("top_gap_pp"),
            "severe_flags": flags,
        })

    print("=" * 100)
    print(f"{'编号':<9}{'比赛':<22}{'体彩HAD':<18}{'市场去水%':<24}{'模型1X2%':<24}{'模式':<12}{'严重旗标'}")
    print("=" * 100)
    for r in rows:
        odds_s = "/".join(str(x) for x in r["odds"]) if r["odds"] else "None"
        mkt_s = json.dumps(r["mkt_pct"], ensure_ascii=False) if r["mkt_pct"] else "None"
        mdl_s = json.dumps(r["model_pct"], ensure_ascii=False)
        flag_s = ";".join(f.split(":")[0] for f in r["severe_flags"]) if r["severe_flags"] else "-"
        print(f"{r['num']:<9}{r['match'][:20]:<22}{odds_s:<18}{mkt_s:<24}{mdl_s:<24}{r['mode']:<12}{flag_s}")

    print("\n=== 模型 vs 市场背离检测（argmax 方向不一致 或 偏差>15pp）===")
    for r in rows:
        if not r["mkt_pct"]:
            print(f"  {r['num']} {r['match'][:20]}: 无市场概率（model_first 分支），以模型为主但需看旗标")
            continue
        mkt_argmax = max(range(3), key=lambda i: r["mkt_pct"][i])
        mdl_argmax = max(range(3), key=lambda i: r["model_pct"][i])
        mkt_name = ["H", "D", "A"][mkt_argmax]
        mdl_name = ["H", "D", "A"][mdl_argmax]
        max_diff = max(abs(x - y) for x, y in zip(r["mkt_pct"], r["model_pct"]))
        if mkt_argmax != mdl_argmax or max_diff > 15:
            print(f"  ⚠️ {r['num']} {r['match'][:20]}: 市场{mkt_name}({r['mkt_pct'][mkt_argmax]}%) vs 模型{mdl_name}({r['model_pct'][mdl_argmax]}%) max_diff={max_diff:.1f}pp")
        else:
            print(f"  ✅ {r['num']} {r['match'][:20]}: 方向一致 {mkt_name}({r['mkt_pct'][mkt_argmax]}%) max_diff={max_diff:.1f}pp")


if __name__ == "__main__":
    main()
