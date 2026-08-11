# -*- coding: utf-8 -*-
"""LLM 轨评测：拉体彩赛果 + 对照预测报告/四玩法。"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RUN_DIR = Path(__file__).resolve().parent

ROOT = Path(r"C:/Users/Administrator/football-llm-predictor")
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT))
import football_predictor as fp
import llm_prompt_rules as lpr
import predict as pr

UA = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://m.sporttery.cn/",
    "Accept": "application/json",
}
CTX = ssl.create_default_context()


def colon_to_dash(s):
    if s is None:
        return None
    s = str(s).strip().replace("：", ":").replace(":", "-")
    return s if re.fullmatch(r"\d+-\d+", s) else None


def fetch_results(day: str) -> list[dict]:
    url = (
        "https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry"
        f"?method=result&matchDate={day}&clientCode=3001"
    )
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    value = data.get("value") or {}
    pages = value.get("matchInfoList") or []
    rows = []
    for grp in pages:
        for m in grp.get("subMatchList") or []:
            s90 = colon_to_dash(m.get("sectionsNo999"))
            sht = colon_to_dash(m.get("sectionsNo1"))
            finished = bool(s90) and str(m.get("matchStatusName") or "") in (
                "已完成",
                "完场",
                "已结束",
            )
            if s90 and m.get("matchStatus") in ("11", 11, "2", 2):
                finished = True
            rows.append(
                {
                    "match_id": m.get("matchId"),
                    "match_num": m.get("matchNumStr") or str(m.get("matchNum") or ""),
                    "league": m.get("leagueAbbName"),
                    "home": m.get("homeTeamAbbName"),
                    "away": m.get("awayTeamAbbName"),
                    "kickoff_local": f"{m.get('matchDate','')} {m.get('matchTime','')}".strip(),
                    "status_name": m.get("matchStatusName"),
                    "finished": finished,
                    "score_ht": sht,
                    "score_90": s90 if finished else None,
                }
            )
    return rows


def save_results(day: str, rows: list[dict]) -> Path:
    payload = {
        "schema_version": "1.0",
        "source": "中国体彩网移动端官方赛果",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "finished_count": sum(1 for r in rows if r.get("finished") and r.get("score_90")),
        "results": rows,
        "notes": ["score_90=sectionsNo999 90分钟", "LLM eval auto"],
    }
    path = DATA / f"results_{day}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_results(day: str) -> list[dict]:
    p = DATA / f"results_{day}.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("results") or []


def result_1x2(score_90: str) -> str:
    h, a = map(int, score_90.split("-"))
    if h > a:
        return "主胜"
    if h < a:
        return "客胜"
    return "平局"


def ou25(score_90: str) -> str:
    h, a = map(int, score_90.split("-"))
    return "大2.5" if h + a > 2 else "小2.5"


def hafu_label(ht: str | None, ft: str) -> str | None:
    if not ht or not re.fullmatch(r"\d+-\d+", ht):
        return None
    def side(s):
        h, a = map(int, s.split("-"))
        return "胜" if h > a else ("负" if h < a else "平")
    return side(ht) + side(ft)


def parse_predictions_txt(path: Path) -> list[dict]:
    """Parse predictions_*.txt evidence-track style."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"\n(?=【|## |\d+\. |场次|周[一二三四五六日]\d+)", text)
    # fallback: use report md table if txt hard
    preds = []
    # try structured lines from report style in txt
    for m in re.finditer(
        r"(周[一二三四五六日]\d{3})\s+(.+?)\s+vs\s+(.+?)\s*\n.*?方向[:：]\s*(\S+).*?强度[:：]?\s*(\d+)%?.*?比分偏好[:：]\s*(\S+)",
        text,
        re.S,
    ):
        preds.append(
            {
                "match_num": m.group(1),
                "home": m.group(2).strip(),
                "away": m.group(3).strip(),
                "direction": m.group(4).replace("**", ""),
                "strength": int(m.group(5)),
                "score_pref": m.group(6),
                "alt": None,
            }
        )
    if preds:
        return preds
    # from export report md
    return []


def parse_report_md(path: Path) -> list[dict]:
    if not path.exists():
        return []
    t = path.read_text(encoding="utf-8")
    preds = []
    # table rows: | 周二001 | 里莫 vs 桑托斯 | **客胜** (3.5/8.0票) | 44% | 1-2 | ...
    for line in t.splitlines():
        if not line.strip().startswith("|"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5:
            continue
        if not re.match(r"周[一二三四五六日]\d{3}", cols[0]):
            continue
        num = cols[0]
        m = re.match(r"(.+?)\s+vs\s+(.+)", cols[1])
        if not m:
            continue
        dm = re.search(r"(主胜|平局|客胜)", cols[2])
        sm = re.search(r"(\d+)%", cols[3])
        score = cols[4].replace("**", "").strip()
        # alt from dual mentions later
        preds.append(
            {
                "match_num": num,
                "home": m.group(1).strip(),
                "away": m.group(2).strip(),
                "direction": dm.group(1) if dm else "",
                "strength": int(sm.group(1)) if sm else None,
                "score_pref": score if re.match(r"\d+-\d+|胜其他|平其他|负其他", score) else score,
                "alt": None,
            }
        )
    # try fill alt from detail sections
    for p in preds:
        # look for 备选 near match
        pat = rf"{re.escape(p['match_num'])}[\s\S]{{0,1200}}?备选[:：]?\s*(主胜|平局|客胜)"
        mm = re.search(pat, t)
        if mm:
            p["alt"] = mm.group(1)
        # also individual 备选 majority
    return preds


def match_pred_result(pred, results):
    by_num = {r.get("match_num"): r for r in results if r.get("match_num")}
    r = by_num.get(pred["match_num"])
    if r and r.get("finished") and r.get("score_90"):
        return r
    # fuzzy home/away
    for r in results:
        if not r.get("finished") or not r.get("score_90"):
            continue
        if pred["home"] in (r.get("home") or "") or (r.get("home") or "") in pred["home"]:
            if pred["away"] in (r.get("away") or "") or (r.get("away") or "") in pred["away"]:
                return r
    return None


def eval_batch(day: str, preds: list[dict], results: list[dict]) -> dict:
    rows = []
    for p in preds:
        r = match_pred_result(p, results)
        if not r:
            continue
        actual = result_1x2(r["score_90"])
        dir_hit = p["direction"] == actual
        # dual: direction or alt
        dual_hit = dir_hit or (p.get("alt") == actual)
        # also if strength < 60 and we only have single, still single
        h, a = map(int, r["score_90"].split("-"))
        crs = lpr.map_score_to_crs(h, a)
        score_hit = p.get("score_pref") == crs
        off = None
        rows.append(
            {
                "match_num": p["match_num"],
                "home": p["home"],
                "away": p["away"],
                "pred_dir": p["direction"],
                "alt": p.get("alt"),
                "strength": p.get("strength"),
                "score_pref": p.get("score_pref"),
                "actual": actual,
                "score_90": r["score_90"],
                "score_ht": r.get("score_ht"),
                "crs": crs,
                "dir_hit": dir_hit,
                "dual_hit": dual_hit,
                "score_hit": score_hit,
                "ou_actual": ou25(r["score_90"]),
                "hafu_actual": hafu_label(r.get("score_ht"), r["score_90"]),
            }
        )
    n = len(rows)
    if not n:
        return {"day": day, "n": 0, "rows": []}
    return {
        "day": day,
        "n": n,
        "dir_hits": sum(1 for x in rows if x["dir_hit"]),
        "dual_hits": sum(1 for x in rows if x["dual_hit"]),
        "score_hits": sum(1 for x in rows if x["score_hit"]),
        "rows": rows,
        "score_pref_dist": Counter(p.get("score_pref") for p in preds),
        "dir_dist": Counter(p.get("direction") for p in preds),
    }


def eval_four_market(path: Path, results: list[dict]) -> dict:
    if not path.exists():
        return {"n": 0}
    data = json.loads(path.read_text(encoding="utf-8"))
    # list of match preds
    items = data if isinstance(data, list) else data.get("matches") or data.get("results") or []
    rows = []
    for it in items:
        if not isinstance(it, dict) or it.get("error"):
            continue
        home = it.get("home") or (it.get("match") or {}).get("home")
        away = it.get("away") or (it.get("match") or {}).get("away")
        # find result
        r = None
        for rr in results:
            if not rr.get("score_90"):
                continue
            if home and (home in (rr.get("home") or "") or (rr.get("home") or "") in str(home)):
                if away and (away in (rr.get("away") or "") or (rr.get("away") or "") in str(away)):
                    r = rr
                    break
        if not r:
            # try match_num
            mn = it.get("match_num") or it.get("num")
            for rr in results:
                if rr.get("match_num") == mn and rr.get("score_90"):
                    r = rr
                    break
        if not r:
            continue
        actual = result_1x2(r["score_90"])
        # direction fields
        d = it.get("direction") or it.get("top_result") or it.get("result")
        if d in ("H", "home"):
            d = "主胜"
        if d in ("A", "away"):
            d = "客胜"
        if d in ("D", "draw"):
            d = "平局"
        score = it.get("score_pref") or it.get("top_score") or it.get("score")
        if not score and it.get("home_score") is not None:
            score = f"{it.get('home_score')}-{it.get('away_score')}"
        ou = it.get("ou25") or it.get("top_ou25")
        hafu = it.get("hafu") or it.get("top_hafu")
        h, a = map(int, r["score_90"].split("-"))
        crs = lpr.map_score_to_crs(h, a)
        rows.append(
            {
                "home": home,
                "away": away,
                "pred_dir": d,
                "actual": actual,
                "dir_hit": d == actual,
                "score_pref": score,
                "score_hit": score == crs,
                "ou": ou,
                "ou_hit": ou == ou25(r["score_90"]) if ou else None,
                "hafu": hafu,
                "hafu_act": hafu_label(r.get("score_ht"), r["score_90"]),
                "hafu_hit": (hafu == hafu_label(r.get("score_ht"), r["score_90"])) if hafu else None,
                "score_90": r["score_90"],
            }
        )
    n = len(rows)
    if not n:
        return {"n": 0, "rows": []}
    return {
        "n": n,
        "dir_hits": sum(1 for x in rows if x["dir_hit"]),
        "score_hits": sum(1 for x in rows if x["score_hit"]),
        "ou_hits": sum(1 for x in rows if x.get("ou_hit")),
        "ou_n": sum(1 for x in rows if x.get("ou_hit") is not None),
        "hafu_hits": sum(1 for x in rows if x.get("hafu_hit")),
        "hafu_n": sum(1 for x in rows if x.get("hafu_hit") is not None),
        "rows": rows,
        "score_dist": Counter(x.get("score_pref") for x in rows),
        "ou_dist": Counter(x.get("ou") for x in rows),
    }


def pct(a, b):
    return f"{a}/{b} = {a/b*100:.0f}%" if b else "n/a"


def main():
    # restore 08-05 if needed
    r05_path = DATA / "results_2026-08-05.json"
    if r05_path.exists():
        d = json.loads(r05_path.read_text(encoding="utf-8"))
        if d.get("finished_count", 0) < 5:
            # keep restored content from earlier write - re-check
            pass

    days = ["2026-08-05", "2026-08-07", "2026-08-08"]
    all_stats = []
    print("=" * 72)
    print("LLM 轨评测（竞彩 90 分钟口径）")
    print("=" * 72)

    for day in days:
        # fetch fresh for 07/08; keep 05 file if good
        if day == "2026-08-05":
            rows = load_results(day)
            if sum(1 for r in rows if r.get("score_90")) < 5:
                try:
                    rows = fetch_results(day)
                    # merge with known if empty scores
                    save_results(day, rows)
                except Exception as e:
                    print(day, "fetch fail", e)
            # ensure dash format
            for r in rows:
                if r.get("score_90"):
                    r["score_90"] = colon_to_dash(r["score_90"]) or r["score_90"]
                if r.get("score_ht"):
                    r["score_ht"] = colon_to_dash(r["score_ht"]) or r["score_ht"]
        else:
            try:
                rows = fetch_results(day)
                save_results(day, rows)
            except Exception as e:
                print(day, "fetch fail", e)
                rows = load_results(day)

        fin = [r for r in rows if r.get("finished") and r.get("score_90")]
        print(f"\n## {day} 赛果 finished={len(fin)}/{len(rows)}")

        preds = parse_report_md(DATA / f"预测报告_{day}.md")
        if not preds:
            preds = parse_predictions_txt(DATA / f"predictions_{day}.txt")
        # 08 report filename says 08 but header 07 - still parse
        if day == "2026-08-08" and not preds:
            preds = parse_report_md(DATA / "预测报告_2026-08-08.md")

        st = eval_batch(day, preds, fin)
        all_stats.append(st)
        print(f"  可评测 {st['n']} 场 | 预测文件 {len(preds)} 条")
        if st["n"]:
            print(f"  方向单选: {pct(st['dir_hits'], st['n'])}")
            print(f"  方向含双选: {pct(st['dual_hits'], st['n'])}")
            print(f"  比分偏好: {pct(st['score_hits'], st['n'])}")
            print(f"  比分偏好分布(预测侧): {st['score_pref_dist'].most_common(5)}")
            print("  逐场:")
            for x in st["rows"]:
                mark = "✔" if x["dir_hit"] else "✘"
                sm = "✔" if x["score_hit"] else "✘"
                print(
                    f"   {x['match_num']} {x['home']}vs{x['away']}: "
                    f"预测{x['pred_dir']}/{x['score_pref']} → 实际{x['actual']} {x['score_90']} "
                    f"方向{mark} 比分{sm}"
                )

    # aggregate evidence track
    n = sum(s["n"] for s in all_stats)
    dh = sum(s.get("dir_hits", 0) for s in all_stats)
    du = sum(s.get("dual_hits", 0) for s in all_stats)
    sh = sum(s.get("score_hits", 0) for s in all_stats)
    print("\n" + "=" * 72)
    print("## 证据轨累计（有赛果可评）")
    print(f"场次 {n} | 方向单选 {pct(dh,n)} | 含双选 {pct(du,n)} | 比分 {pct(sh,n)}")

    # market baseline from same results: majority favorite from report not available;
    # use dual-track historical notes

    # four market batch
    print("\n## 四玩法轨（2026-08-08 批次 llm_predictions.json）")
    # collect all results 08+09
    res_all = []
    for day in ["2026-08-08", "2026-08-09", "2026-08-07"]:
        res_all.extend(load_results(day) if day != "2026-08-08" else fetch_results(day) if False else load_results(day))
    # reload 08
    res_all = []
    for day in ["2026-08-07", "2026-08-08", "2026-08-09"]:
        res_all.extend(load_results(day))
    fm = eval_four_market(
        RUN_DIR / "llm_predictions.json",
        [r for r in res_all if r.get("score_90")],
    )
    print(f"  可评测 {fm.get('n',0)}")
    if fm.get("n"):
        print(f"  1X2: {pct(fm['dir_hits'], fm['n'])}")
        print(f"  比分: {pct(fm['score_hits'], fm['n'])}")
        print(f"  大小球: {pct(fm['ou_hits'], fm['ou_n'])}")
        print(f"  半全场: {pct(fm['hafu_hits'], fm['hafu_n'])}")
        print(f"  比分分布: {fm['score_dist'].most_common(5)}")
        print(f"  OU分布: {fm['ou_dist'].most_common(5)}")
        for x in fm["rows"][:15]:
            print(
                f"   {x['home']}vs{x['away']}: {x['pred_dir']}/{x['score_pref']}/{x.get('ou')} "
                f"→ {x['actual']} {x['score_90']} dir{'✔' if x['dir_hit'] else '✘'}"
            )

    # dual track published backtests
    print("\n## 既有双轨回测包（交付目录）")
    for name in ["backtest_dual_track_20260805.json", "backtest_dual_track_20260806.json"]:
        p = Path(r"H:/claude AI自媒体/project014_football-quant-fusion/05_交付") / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        print(name, json.dumps({k: d.get(k) for k in d if k in ("n","settled","llm","quant","summary") or k.endswith("rate")}, ensure_ascii=False)[:400])
        # print top keys
        print("  keys", list(d.keys())[:20])
        if "llm" in d:
            print("  llm", d["llm"])
        if "summary" in d:
            print("  summary", d["summary"])

    # structural quality on latest preds without results
    print("\n## 结构质量（8/8 证据轨预测，不依赖赛果）")
    preds08 = parse_report_md(DATA / "预测报告_2026-08-08.md")
    if preds08:
        sc = Counter(p["score_pref"] for p in preds08)
        di = Counter(p["direction"] for p in preds08)
        strong = sum(1 for p in preds08 if (p.get("strength") or 0) >= 80)
        print(f"  场次 {len(preds08)} | 方向 {di} | 比分Top {sc.most_common(3)}")
        print(f"  强度≥80%: {strong}/{len(preds08)} = {strong/len(preds08)*100:.0f}%（易贴市场热门）")
        collapse = sc.get("2-1", 0) + sc.get("1-2", 0)
        print(f"  2-1/1-2 合计: {collapse}/{len(preds08)} = {collapse/len(preds08)*100:.0f}%（模式坍缩指标）")

    # write report
    out = RUN_DIR / "LLM轨评测_20260809.md"
    lines = [
        f"# LLM 轨评测报告",
        f"",
        f"> 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 口径: 竞彩90分钟+CRS | 样本外结论门槛: ≥100场评估 / ≥200场下结论",
        f"",
        f"## 1. 命中率（有赛果）",
        f"",
        f"| 日期 | 场次 | 方向单选 | 含双选 | 比分 |",
        f"|---|---:|---:|---:|---:|",
    ]
    for s in all_stats:
        if not s["n"]:
            lines.append(f"| {s['day']} | 0 | - | - | - |")
            continue
        lines.append(
            f"| {s['day']} | {s['n']} | {pct(s['dir_hits'],s['n'])} | {pct(s['dual_hits'],s['n'])} | {pct(s['score_hits'],s['n'])} |"
        )
    lines += [
        f"| **累计** | **{n}** | **{pct(dh,n)}** | **{pct(du,n)}** | **{pct(sh,n)}** |",
        f"",
        f"## 2. 既有双轨包",
        f"- 20260805: LLM双选 1/4 (25%), 单选 0/4; 量化1X2 0/4",
        f"- 20260806: LLM双选 2/4 (50%), 单选 1/4; 量化1X2 1/4",
        f"",
        f"## 3. 结构问题（准确率之前先看）",
        f"- 8/8 证据轨 13 场: 比分高度集中 2-1/1-2；高强度（≥80%）占比高，与市场同向标注「与官方一致」几乎全覆盖 → **更像盘口复读器**",
        f"- 8/8 四玩法轨 28 场（预测时）: 2-1×23、大2.5×28、半全场胜胜×23 → **四玩法模板坍缩**（提示词优化已上，待下批验证）",
        f"",
        f"## 4. 结论边界",
        f"- 当前可结算 LLM 样本约 **{n} 场（证据轨）+ 双轨包 8 场**，远低于 100 场评估线",
        f"- **不能**宣称 LLM 轨优于市场或优于量化轨",
        f"- 现阶段定位: 证据结构化 + 多模型定性投票的**研究轨**；投注决策仍以量化门控/不出胆纪律为准",
        f"",
        f"## 5. 改进优先级（评测导向）",
        f"1. 赛后自动回填 results_*.json + 跑 backtest.py（已修 CRS 映射）",
        f"2. 用优化后 prompt 重跑并对照坍缩指标（2-1 占比、OU 一边倒）",
        f"3. 强制双选规则在 strength<60% 时写入报告 alt 字段，便于含双选统计",
        f"4. get_lineups 进证据后，单独切片「有首发 vs 无首发」命中率",
        f"",
    ]
    # detail tables
    lines.append("## 6. 逐场明细（证据轨）\n")
    for s in all_stats:
        if not s.get("rows"):
            continue
        lines.append(f"### {s['day']}\n")
        lines.append("| 场次 | 对阵 | 预测 | 比分偏好 | 实际 | 比分 | 方向 | 比分 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for x in s["rows"]:
            lines.append(
                f"| {x['match_num']} | {x['home']} vs {x['away']} | {x['pred_dir']} | {x['score_pref']} | "
                f"{x['actual']} | {x['score_90']} | {'✔' if x['dir_hit'] else '✘'} | {'✔' if x['score_hit'] else '✘'} |"
            )
        lines.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    # also copy to project014
    dest = Path(r"H:/claude AI自媒体/project014_football-quant-fusion/05_交付/LLM轨评测_20260809.md")
    try:
        dest.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass
    print("\n报告:", out)
    print("DONE")


if __name__ == "__main__":
    main()
