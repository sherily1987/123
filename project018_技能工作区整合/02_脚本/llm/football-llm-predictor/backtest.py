#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 轨道证据驱动预测 回测 (支持多日累计)
=========================================
用法:
  python backtest.py                    # 自动扫描 data/ 下所有已有赛果的日期, 累计统计
  python backtest.py --date 2026-08-05  # 只回测指定日期(详细)
  python backtest.py --date 2026-08-05 --verbose  # 单日详细(含每场明细)

评估: 方向命中(单选/双选) + 比分偏好命中 + 与官方赔率方向对比
输出: 每日命中率 + 多日累计命中率
"""
import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import predict as fp

# 方向 -> one-hot 向量索引 (Brier Score 用)
DIR_INDEX = {"主胜": 0, "平局": 1, "客胜": 2}


def votes_to_prob(vote_dist_str):
    """从 '主胜:3.0 | 平局:1.5 | 客胜:0.5' 格式的投票分布解析概率向量。"""
    probs = [1/3, 1/3, 1/3]
    if not vote_dist_str:
        return probs
    total = 0.0
    raw = {}
    for part in vote_dist_str.split("|"):
        m = re.match(r"\s*(主胜|平局|客胜)\s*:\s*([\d.]+)", part.strip())
        if m:
            raw[m.group(1)] = float(m.group(2))
            total += float(m.group(2))
    if total > 0 and raw:
        probs = [raw.get("主胜", 0)/total, raw.get("平局", 0)/total, raw.get("客胜", 0)/total]
    return probs


def brier_score(prob_vec, actual_dir):
    """多类 Brier Score: sum((p_i - y_i)^2), 越小越好。随机=0.667, 完美=0。"""
    y = [0, 0, 0]
    if actual_dir in DIR_INDEX:
        y[DIR_INDEX[actual_dir]] = 1
    return sum((p - yi) ** 2 for p, yi in zip(prob_vec, y))


def parse_report(path):
    """解析证据版预测报告 -> {场次idx: {direction, votes, strength, score_pref, individual}}"""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    matches = {}
    blocks = re.split(r"(?=⚽ 第\d+/\d+场)", text)
    for blk in blocks:
        if "综合方向" not in blk:
            continue
        m = re.search(r"⚽ 第(\d+)/\d+场 \[([^\]]*)\] (.+?) VS (.+?) \|", blk, re.M)
        if not m:
            continue
        idx = int(m.group(1))
        d = re.search(r"综合方向: (.+?)  \((\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)票, 强度(\d+)%\)", blk)
        sp = re.search(r"比分偏好: (.+)", blk)
        votes = re.search(r"投票分布: (.+)", blk)
        matches[idx] = {
            "num": m.group(2), "home": m.group(3).strip(), "away": m.group(4).strip(),
            "direction": d.group(1) if d else "",
            "votes": d.group(2) if d else "", "total": d.group(3) if d else "",
            "strength": d.group(4) if d else "",
            "score_pref": sp.group(1).strip() if sp else "",
            "vote_dist": votes.group(1).strip() if votes else "",
            "individual": [],
        }
        for line in blk.splitlines():
            im = re.match(r"\s+\[(.+?)\s*\] (.+?)( 比分:.+?)? — (.+)", line)
            if im and "失败" not in line and "综合方向" not in line:
                matches[idx]["individual"].append({
                    "model": im.group(1).strip(), "dir": im.group(2).strip(),
                    "reasoning": im.group(4).strip()})
    return matches


def result_of(r):
    h, a = r["score_90"].split("-")
    h, a = int(h), int(a)
    return h, a, ("主胜" if h > a else "平局" if h == a else "客胜")


def evaluate_date(date_str, verbose=False):
    """回测单个日期, 返回 (rows, summary)。"""
    report = f"data/predictions_{date_str}.txt"
    results_f = f"data/results_{date_str}.json"
    raw_f = f"data/raw_{date_str}.json"
    if not (os.path.exists(report) and os.path.exists(results_f)):
        return None, None

    preds = parse_report(report)
    with open(results_f, encoding="utf-8") as f:
        results = {r["match_id"]: r for r in json.load(f)["results"]}
    raw = {}
    if os.path.exists(raw_f):
        with open(raw_f, encoding="utf-8") as f:
            # match_id 类型归一化：raw 里可能是 int、results 里是 str，统一用 str 作 key
            raw = {str(m["match_id"]): m for m in json.load(f)["matches"]}

    rows = []
    for idx in sorted(preds):
        p = preds[idx]
        r = next((v for v in results.values() if v["match_num"] == p["num"]), None)
        if not r:
            continue
        h, a, actual = result_of(r)
        pred_dir = p["direction"]

        dir_hit = pred_dir == actual
        alt_hits = []
        for ind in p["individual"]:
            dd = ind["dir"]
            mm = re.match(r"(.+?)(?: \(备选:(.+?)\))?$", dd)
            if mm:
                if mm.group(1) == actual:
                    alt_hits.append(f"{ind['model']}单选命中")
                elif mm.group(2) == actual:
                    alt_hits.append(f"{ind['model']}双选命中")

        sp = p["score_pref"]
        # 比分命中按竞彩兑奖规则: 预测选项 == 实际比分映射到的兑奖选项
        # (预测"胜其他" vs 实际 6-0 -> 命中; 预测"2-1" vs 实际 2-1 -> 命中)
        actual_crs = fp.map_score_to_crs(h, a)
        score_hit = sp == actual_crs

        rawm = raw.get(r["match_id"], {})
        mo = rawm.get("model_odds") or []
        if len(mo) >= 3:
            official_dir = "主胜" if mo[0] == min(mo) else "客胜" if mo[2] == min(mo) else "平局"
        else:
            official_dir = "?"

        rows.append((p, r, h, a, actual, dir_hit, score_hit, official_dir, alt_hits))

        if verbose:
            print(f"\n⚽ [{p['num']}] {p['home']} vs {p['away']}")
            print(f"   预测: {pred_dir} ({p['votes']}/{p['total']}票, 强度{p['strength']}%) | 比分偏好 {sp}")
            print(f"   实际: {h}-{a} → {actual}")
            print(f"   方向: {'✅ 命中' if dir_hit else '❌ 未中'} | 比分: {'✅ 命中' if score_hit else '❌ 未中'} | 官方赔率方向: {official_dir} ({'✅' if official_dir == actual else '❌'})")
            if alt_hits:
                print(f"   💡 双选覆盖: {', '.join(alt_hits)}")

    n = len(rows)
    if n == 0:
        return rows, None
    dir_hits = sum(1 for r in rows if r[5])
    dir_hits_with_alt = sum(1 for r in rows if r[5] or r[8])
    score_hits = sum(1 for r in rows if r[6])
    official_hits = sum(1 for r in rows if r[7] == r[4])

    # Brier Score (基于综合方向投票分布的隐含概率)
    brier_list = []
    for (p, r, h, a, actual, dh, sh, od, ah) in rows:
        prob_vec = votes_to_prob(p.get("vote_dist", ""))
        brier_list.append(brier_score(prob_vec, actual))
    avg_brier = sum(brier_list) / n if n else None

    # 各模型独立命中率 (单选)
    model_stats = {}
    for (p, r, h, a, actual, dh, sh, od, ah) in rows:
        for ind in p["individual"]:
            mm = re.match(r"(.+?)(?: \(备选:(.+?)\))?$", ind["dir"])
            if not mm:
                continue
            model = ind["model"].strip()
            if model not in model_stats:
                model_stats[model] = {"total": 0, "hit": 0, "alt": 0, "home_pred": 0}
            model_stats[model]["total"] += 1
            if mm.group(1) == actual:
                model_stats[model]["hit"] += 1
            elif mm.group(2) == actual:
                model_stats[model]["alt"] += 1
            if mm.group(1) == "主胜":
                model_stats[model]["home_pred"] += 1

    summary = {
        "date": date_str, "n": n,
        "dir_hits": dir_hits, "dir_with_alt": dir_hits_with_alt,
        "score_hits": score_hits, "official_hits": official_hits,
        "avg_brier": avg_brier, "model_stats": model_stats,
    }
    return rows, summary


def main():
    ap = argparse.ArgumentParser(description="LLM证据驱动预测回测(多日累计)")
    ap.add_argument("--date", help="回测指定日期 YYYY-MM-DD (默认自动扫描全部)")
    ap.add_argument("--verbose", action="store_true", help="单日详细输出")
    args = ap.parse_args()

    if args.date:
        # 单日模式
        rows, s = evaluate_date(args.date, verbose=args.verbose)
        if s is None:
            print(f"❌ {args.date}: 缺预测文件或赛果文件(data/predictions_{args.date}.txt / results_{args.date}.json)")
            return
        print("=" * 78)
        print(f"🔁 回测报告 · {args.date} ({s['n']} 场)")
        print("=" * 78)
        if not args.verbose:
            for p, r, h, a, actual, dh, sh, od, ah in rows:
                print(f"  [{p['num']}] {p['home']} vs {p['away']}: 预测{p['direction']} → 实际{actual} "
                      f"{'✅' if dh else '❌'}" + (f" 💡双选: {', '.join(ah)}" if ah else ""))
        print("\n📊 汇总:")
        print(f"   方向命中(单选): {s['dir_hits']}/{s['n']} = {s['dir_hits']/s['n']*100:.0f}%")
        print(f"   方向命中(含双选): {s['dir_with_alt']}/{s['n']} = {s['dir_with_alt']/s['n']*100:.0f}%")
        print(f"   比分偏好命中: {s['score_hits']}/{s['n']} = {s['score_hits']/s['n']*100:.0f}%")
        print(f"   官方赔率方向: {s['official_hits']}/{s['n']} = {s['official_hits']/s['n']*100:.0f}%")
        if s["avg_brier"] is not None:
            print(f"   Brier Score(越低越好, 随机0.667): {s['avg_brier']:.3f}")
        if s.get("model_stats"):
            print("\n   🤖 各模型独立命中率:")
            for model, st in sorted(s["model_stats"].items(),
                                    key=lambda x: -x[1]["hit"]/max(1, x[1]["total"])):
                pct = st["hit"]/st["total"]*100 if st["total"] else 0
                home_pct = st["home_pred"]/st["total"]*100 if st["total"] else 0
                short = model.split("/")[-1][:20]
                print(f"     {short:<20} {st['hit']}/{st['total']} ({pct:.0f}%) "
                      f"+双选{st['alt']} | 主胜预测占比{home_pct:.0f}%")
        return

    # 多日累计模式: 扫描所有 predictions_*.txt + results_*.json
    reports = sorted(glob.glob("data/predictions_*.txt"))
    dates = []
    for rp in reports:
        base = os.path.basename(rp).replace("predictions_", "").replace(".txt", "")
        if re.match(r"^\d{4}-\d{2}-\d{2}$", base) and os.path.exists(f"data/results_{base}.json"):
            dates.append(base)
    if not dates:
        print("❌ 未找到任何可回测的日期(需要 data/predictions_<date>.txt + data/results_<date>.json)")
        return

    print("=" * 90)
    print("🔁 LLM 证据驱动预测 · 多日累计回测")
    print("=" * 90)
    print(f"{'日期':<12} {'场次':>4} {'方向单选':>14} {'含双选':>14} {'比分':>8} {'Brier':>8} {'官方赔率':>14}")
    print("-" * 90)

    agg = {"n": 0, "dir": 0, "alt": 0, "score": 0, "official": 0}
    brier_sum = 0.0
    cum_model = {}
    for d in dates:
        _, s = evaluate_date(d)
        if s is None:
            continue
        agg["n"] += s["n"]
        agg["dir"] += s["dir_hits"]
        agg["alt"] += s["dir_with_alt"]
        agg["score"] += s["score_hits"]
        agg["official"] += s["official_hits"]
        if s["avg_brier"] is not None:
            brier_sum += s["avg_brier"] * s["n"]
        for model, st in (s.get("model_stats") or {}).items():
            c = cum_model.setdefault(model, {"total": 0, "hit": 0, "alt": 0, "home_pred": 0})
            for k in c:
                c[k] += st.get(k, 0)
        dir_txt = f"{s['dir_hits']}/{s['n']} ({s['dir_hits']/s['n']*100:.0f}%)"
        alt_txt = f"{s['dir_with_alt']}/{s['n']} ({s['dir_with_alt']/s['n']*100:.0f}%)"
        score_txt = f"{s['score_hits']}/{s['n']}"
        brier_txt = f"{s['avg_brier']:.3f}" if s["avg_brier"] is not None else "—"
        off_txt = f"{s['official_hits']}/{s['n']} ({s['official_hits']/s['n']*100:.0f}%)"
        print(f"{d:<12} {s['n']:>4} {dir_txt:>14} {alt_txt:>14} {score_txt:>8} {brier_txt:>8} {off_txt:>14}")

    print("-" * 90)
    n = agg["n"]
    if n:
        dir_txt = f"{agg['dir']}/{n} ({agg['dir']/n*100:.0f}%)"
        alt_txt = f"{agg['alt']}/{n} ({agg['alt']/n*100:.0f}%)"
        score_txt = f"{agg['score']}/{n}"
        brier_txt = f"{brier_sum/n:.3f}" if brier_sum else "—"
        off_txt = f"{agg['official']}/{n} ({agg['official']/n*100:.0f}%)"
        print(f"{'累计':<12} {n:>4} {dir_txt:>14} {alt_txt:>14} {score_txt:>8} {brier_txt:>8} {off_txt:>14}")

    if cum_model:
        print("\n🤖 各模型累计独立命中率(单选):")
        for model, st in sorted(cum_model.items(), key=lambda x: -x[1]["hit"]/max(1, x[1]["total"])):
            pct = st["hit"]/st["total"]*100 if st["total"] else 0
            home_pct = st["home_pred"]/st["total"]*100 if st["total"] else 0
            short = model.split("/")[-1][:22]
            print(f"  {short:<22} {st['hit']}/{st['total']} ({pct:.0f}%) +双选{st['alt']} | 主胜预测占比{home_pct:.0f}%")

    print("=" * 90)
    print("说明: 方向单选=综合方向直接命中; 含双选=单选命中或任一模型双选覆盖; 官方赔率=市场方向命中")
    print("     Brier: 综合方向投票隐含概率的多类Brier, 越低越好, 三选一随机基线≈0.667")
    print("     样本越多越可信, 单日 5-10 场只是噪声, 建议积累 2-3 周再看趋势")


if __name__ == "__main__":
    main()
