#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多版本预测统一回测
==================
对比 data/ 下所有 predictions_*.txt (v1/v2/v3/evidence) 对同一赛果的命中率。
兼容两种格式:
  - 旧格式: "📊 综合预测: 里莫 1 - 1 桑托斯  (客胜, 2/5票)" (比分+赛果)
  - 新格式: "📊 综合方向: 客胜  (3.5/8.0票, 强度44%)" (方向+比分偏好)
"""
import glob
import json
import os
import re

RESULTS = "data/results_2026-08-05.json"


def result_map():
    with open(RESULTS, encoding="utf-8") as f:
        data = json.load(f)
    out = {}
    for r in data["results"]:
        h, a = r["score_90"].split("-")
        h, a = int(h), int(a)
        out[r["match_num"]] = {
            "home": r["home"], "away": r["away"], "score": f"{h}-{a}",
            "result": "主胜" if h > a else "平局" if h == a else "客胜",
            "score_ht": r["score_ht"],
        }
    return out


def parse_old_format(text):
    """旧格式: 综合预测行 -> {match_num: {direction, votes, total}}"""
    out = {}
    blocks = re.split(r"(?=⚽ 第\d+/\d+场)", text)
    for blk in blocks:
        m = re.search(r"⚽ 第(\d+)/\d+场 \[([^\]]*)\]", blk)
        if not m:
            continue
        num = m.group(2)
        cm = re.search(r"综合预测: .+?\((.+?), (\d+)/(\d+)票\)", blk)
        if not cm:
            continue
        direction = cm.group(1)
        out[num] = {"direction": direction, "votes": cm.group(2),
                    "total": cm.group(3)}
    return out


def parse_new_format(text):
    """新格式(证据版): 综合方向行 -> {match_num: {direction, votes, total}}"""
    out = {}
    blocks = re.split(r"(?=⚽ 第\d+/\d+场)", text)
    for blk in blocks:
        m = re.search(r"⚽ 第(\d+)/\d+场 \[([^\]]*)\]", blk)
        if not m:
            continue
        num = m.group(2)
        cm = re.search(r"综合方向: (.+?)  \((\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)票", blk)
        if not cm:
            continue
        out[num] = {"direction": cm.group(1), "votes": cm.group(2),
                    "total": cm.group(3)}
    return out


def main():
    results = result_map()
    # 明确指定版本文件
    files = [
        ("v1", "data/predictions_2026-08-05.txt"),
        ("v2", "data/predictions_2026-08-05_v2.txt"),
        ("v3", "data/predictions_2026-08-05_v3.txt"),
        ("证据版", "data/predictions_evidence_2026-08-05.txt"),
    ]
    print("=" * 90)
    print("🔁 多版本预测统一回测 · 2026-08-05 五场")
    print("=" * 90)

    summary = {}
    for tag, path in files:
        if not os.path.exists(path):
            print(f"⚠️ 跳过 {tag}: {path} 不存在")
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        if "综合方向" in text:
            preds = parse_new_format(text)
        else:
            preds = parse_old_format(text)
        summary[tag] = {"hit": 0, "n": 0, "detail": {}}
        for num, res in results.items():
            p = preds.get(num)
            if not p:
                summary[tag]["detail"][num] = "无预测"
                continue
            hit = p["direction"] == res["result"]
            summary[tag]["n"] += 1
            if hit:
                summary[tag]["hit"] += 1
            summary[tag]["detail"][num] = (
                f"{'✅' if hit else '❌'} {p['direction']}({p['votes']}/{p['total']}票)"
                f" vs 实际{res['result']}")

    # 打印每场明细
    tags = list(summary.keys())
    for num, res in results.items():
        cells = []
        for tag in tags:
            d = summary[tag]["detail"].get(num, "无")
            cells.append(f"{d:>22}")
        print(f"[{num}] {res['home']} vs {res['away']} 实际 {res['score']}({res['result']})")
        for tag, d in zip(tags, cells):
            print(f"    {tag:>6}: {d}")
        print()

    # 汇总
    print("=" * 90)
    print("📊 方向命中率汇总:")
    for tag in tags:
        s = summary[tag]
        rate = s["hit"] / s["n"] * 100 if s["n"] else 0
        print(f"   {tag:>10}: {s['hit']}/{s['n']} = {rate:.0f}%")
    print("=" * 90)


if __name__ == "__main__":
    main()
