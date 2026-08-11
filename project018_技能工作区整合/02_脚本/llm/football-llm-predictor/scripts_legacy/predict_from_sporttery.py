#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
足彩比赛批量预测：体彩采集数据 -> 多LLM投票 -> 综合报告
========================================================
读取采集器输出的JSON(含官方赔率), 对每场比赛调用多个免费LLM独立预测,
聚合投票输出综合预测 + 官方赔率对照。

用法:
  python predict_from_sporttery.py --input data/raw_2026-08-05.json
  python predict_from_sporttery.py --input data/raw_2026-08-05.json --match-id 2040727
  python predict_from_sporttery.py --input data/raw_2026-08-05.json --max-matches 2 --models google/gemma-4-31b-it:free
"""

import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import football_predictor as fp


def match_to_prompt(m):
    """把一场比赛的采集数据(含官方赔率)拼成 LLM 的附加信息。"""
    lines = []
    if m.get("kickoff_local"):
        lines.append(f"开球时间:{m['kickoff_local']}")
    mo = m.get("model_odds") or []
    if len(mo) >= 3:
        lines.append(f"官方胜平负赔率: 主胜{mo[0]} / 平{mo[1]} / 客胜{mo[2]}")
    hh = m.get("model_hhad") or {}
    if hh.get("odds"):
        line = hh.get("line", 0)
        o = hh["odds"]
        sign = "+" if line > 0 else ""
        lines.append(f"官方让球({sign}{line:g})赔率: 主胜{o[0]} / 平{o[1]} / 客胜{o[2]}")
    crs = m.get("crs") or {}
    if crs:
        top = sorted(((k, v) for k, v in crs.items() if "-" in k),
                     key=lambda x: x[1])[:5]
        lines.append("官方比分赔率最低前五: " +
                     ", ".join(f"{k}:{v}" for k, v in top))
    ttg = m.get("ttg") or {}
    if ttg:
        best = min(ttg, key=lambda k: ttg[k])
        lines.append(f"官方总进球赔率(0-7+): " +
                     " ".join(f"{k}球:{v}" for k, v in
                              sorted(ttg.items(), key=lambda x: x[1])[:4]) +
                     f" (最低:{best}球)")
    hafu = m.get("hafu") or {}
    if hafu:
        names = {"hh": "胜胜", "hd": "胜平", "ha": "胜负", "dh": "平胜",
                 "dd": "平平", "da": "平负", "ah": "负胜", "ad": "负平",
                 "aa": "负负"}
        top_h = sorted(hafu.items(), key=lambda x: x[1])[:4]
        lines.append("官方半全场赔率最低前四: " +
                     ", ".join(f"{names.get(k,k)}:{v}" for k, v in top_h))
    return " | ".join(lines)


def predict_match(client, match, models, concurrency=4):
    """对单场比赛: 并行调用所有模型(并发限4, 降低免费档限流), 返回聚合结果。
    client 参数保留兼容; 实际按模型ID前缀路由到对应 provider。"""
    extra = match_to_prompt(match)
    prompt = fp.build_user_prompt(match["home"], match["away"],
                                  match.get("league", ""), extra)
    predictions = {}
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(fp.call_model,
                          fp.get_client(fp.provider_for(md)), md, prompt): md
                for md in models}
        for fut in as_completed(futs):
            md, p = fut.result()
            with lock:
                predictions[md] = p
            if "error" in p:
                print(f"     ✗ [{md}] 失败: {p['error'][:55]}")
            else:
                hr = p.get("half_result") or "-"
                print(f"     ✓ [{md.split('/')[-1].split(':')[0][:18]:<18}] "
                      f"-> {p['home_score']}-{p['away_score']} {p['result']} "
                      f"总:{p.get('total_goals','?')}球 半:{hr} "
                      f"置信:{p['confidence']*100:.0f}%")
    return fp.aggregate(predictions, models)


def print_match_result(match, agg):
    """打印单场综合预测 + 官方赔率对照 + 让球玩法分析。"""
    print(f"\n  📊 综合预测: {match['home']} {agg['top_score'][0]} - "
          f"{agg['top_score'][1]} {match['away']}  ({agg['top_result']}, "
          f"{agg['top_score_votes']}/{agg['valid_count']}票)")
    print(f"  🎯 平均置信度: {agg['avg_confidence']*100:.0f}%")
    dis = agg["disagreement"]
    tag = "低(一致)" if dis <= 0.35 else "中" if dis <= 0.6 else "高(分散)"
    print(f"  ⚖️ 分歧度: {dis:.0%} ({tag})")
    mo = match.get("model_odds") or []
    if len(mo) >= 3:
        print(f"  🏷️ 官方胜平负: {mo[0]}/{mo[1]}/{mo[2]} "
              f"-> 隐含概率 主{1/mo[0]*100:.0f}% 平{1/mo[1]*100:.0f}% 客{1/mo[2]*100:.0f}%")
    hh = match.get("model_hhad") or {}
    if hh.get("odds"):
        o = hh["odds"]
        print(f"  🏷️ 官方让球({hh.get('line',0):+g}): {o[0]}/{o[1]}/{o[2]}")
    # 让球玩法分析: 综合比分 -> 让球结果, 对照官方
    ha = fp.hhad_analysis(match, agg["top_score"])
    if ha:
        sign = "+" if ha["line"] > 0 else ""
        icon = "✅一致" if ha["agree"] else "⚠️分歧"
        print(f"  🎲 让球玩法: 预测比分→{ha['result']} | "
              f"官方让球({sign}{ha['line']:g})最低赔方向:{ha['official_dir']} "
              f"({min(ha['official_odds']):.2f}) | {icon}")
    # 总进球分析
    tg = agg.get("top_total_goals", "")
    if tg:
        ttg = match.get("ttg") or {}
        tg_odds = ttg.get(tg, "-")
        if ttg:
            best_tg = min(ttg, key=lambda k: ttg[k])
            icon = "✅一致" if best_tg == tg else "⚠️分歧"
            print(f"  🎯 总进球: 预测 {tg}球 (赔率{tg_odds}) | "
                  f"官方最低:{best_tg}球({ttg[best_tg]}) | {icon}")
    # 半全场分析
    hafu = agg.get("top_hafu", "")
    if hafu:
        # 从各模型(半场结果x全场结果)推导九宫格并投票
        hrs = Counter()
        for md, p in agg.get("individual", {}).items():
            if p.get("half_result"):
                hrs[fp.hafu_result(p["half_result"], p["result"])] += 1
        if hrs:
            top_hafu = hrs.most_common(1)[0][0]
            hafu_match = match.get("hafu") or {}
            if hafu_match:
                names = {"胜胜": "hh", "胜平": "hd", "胜负": "ha", "平胜": "dh",
                         "平平": "dd", "平负": "da", "负胜": "ah", "负平": "ad",
                         "负负": "aa"}
                fld = names[top_hafu]
                best_f = min(hafu_match, key=lambda k: hafu_match[k])
                icon = "✅一致" if best_f == fld else "⚠️分歧"
                print(f"  🏁 半全场: 预测 {top_hafu} "
                      f"(赔率{hafu_match.get(fld, '-')}) | "
                      f"官方最低:{names.get(best_f, best_f)}"
                      f"({hafu_match[best_f]}) | {icon}")


def main():
    ap = argparse.ArgumentParser(description="足彩批量多LLM预测")
    ap.add_argument("--input", required=True, help="采集器输出的JSON文件")
    ap.add_argument("--models", nargs="+", default=fp.DEFAULT_MODELS,
                    help="模型列表")
    ap.add_argument("--match-id", type=int, default=None, help="只预测指定matchId")
    ap.add_argument("--max-matches", type=int, default=0,
                    help="最多预测前N场(0=全部)")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    matches = data["matches"]
    if args.max_matches:
        matches = matches[:args.max_matches]
    if args.match_id:
        matches = [m for m in matches if m["match_id"] == args.match_id]
    if not matches:
        print("没有符合条件的比赛")
        return

    print(f"🎯 共 {len(matches)} 场比赛待预测, 每场 {len(args.models)} 个模型投票")
    client = fp.get_client()

    for i, m in enumerate(matches, 1):
        if i > 1:
            print(f"\n⏳ 场次冷却 8 秒(降低免费档限流)...")
            time.sleep(8)
        print(f"\n{'='*64}")
        print(f"⚽ 第{i}/{len(matches)}场 [{m.get('match_num','')}] "
              f"{m['home']} VS {m['away']} | {m.get('league','')} "
              f"| {m.get('kickoff_local','')}")
        print(f"{'='*64}")
        agg = predict_match(client, m, args.models)
        if "error" in agg:
            print(f"  [失败] {agg['error']}")
            continue
        print_match_result(m, agg)
        print(f"\n  🤖 各模型详情:")
        for md, p in agg["individual"].items():
            print(f"     [{md.split('/')[-1].split(':')[0][:20]:<20}] "
                  f"{p['home_score']}-{p['away_score']} ({p['result']}, "
                  f"置信{p['confidence']*100:.0f}%) — {p['reasoning'][:50]}")


if __name__ == "__main__":
    main()
