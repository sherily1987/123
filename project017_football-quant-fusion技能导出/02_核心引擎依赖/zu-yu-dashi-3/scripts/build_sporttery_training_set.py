#!/usr/bin/env python3
"""把体彩历史采集结果清洗成建模/回测数据集。
输入：fetch_sporttery_history.py 的 JSON
输出：干净的 JSONL + 汇总报告；只保留有赛前HAD与90分钟比分的比赛。
"""
import argparse, json, re
from collections import Counter

NAT = ("世界杯", "亚洲杯", "非洲杯", "欧洲杯", "美洲杯", "世预赛", "女亚洲杯")
SCORE = re.compile(r"^(\d+):(\d+)$")


# [中文功能] 赔率去水，返回归一化概率与庄家边际
def devig(odds):
    """去水：返回归一化概率与庄家边际。"""
    if not odds or any(not o or o <= 1 for o in odds):
        return None, None
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv], s - 1


# [中文功能] 优先提取常规时间比分字段
def score90(m):
    """优先使用常规时间比分字段，格式 'h:a'。"""
    for k in ("sectionsNo999", "sections_no999", "sectionsNo1"):
        v = m.get(k) or ""
        mm = SCORE.match(str(v).strip())
        if mm:
            return int(mm.group(1)), int(mm.group(2))
    return None


# [中文功能] 取比赛临近收盘的盘口快照
def snapshot(m, key):
    return (m.get("closing_pre_match") or {}).get(key)


# [中文功能] 由TTG赔率转8档总进球概率
def ttg_probs(row):
    if not row:
        return None, None
    o = []
    for i in range(8):
        try:
            o.append(float(row[f"s{i}"]))
        except (KeyError, TypeError, ValueError):
            return None, None
    p, margin = devig(o)
    if not p:
        return None, None
    exp = sum(p[i] * (i if i < 7 else 7.5) for i in range(8))
    return {"probs": p, "margin": margin, "implied_goal_total": exp}, o


# [中文功能] 取CRS赔率最低的Top比分
def crs_top(row, n=5):
    if not row:
        return None
    out = {}
    for k, v in row.items():
        if len(k) == 6 and k[0] == "s" and k[3] == "s" and not k.endswith("f"):
            try:
                out[f"{int(k[1:3])}-{int(k[4:6])}"] = float(v)
            except (TypeError, ValueError):
                pass
    if not out:
        return None
    return [s for s, _ in sorted(out.items(), key=lambda kv: kv[1])[:n]]


# [中文功能] 把采集数据加工成训练集
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--drop-national", action="store_true", help="剔除国家队赛事，只留俱乐部")
    a = ap.parse_args()

    src = json.load(open(a.input, encoding="utf-8"))
    rows, dropped = [], Counter()

    for m in src.get("matches", []):
        league = m.get("leagueAbbName") or m.get("leagueAllName") or ""
        if a.drop_national and any(w in league for w in NAT):
            dropped["national_team"] += 1
            continue
        if str(m.get("matchStatus")) not in ("11", "10"):
            dropped["not_finished"] += 1
            continue
        sc = score90(m)
        if not sc:
            dropped["no_score"] += 1
            continue
        had = m.get("closing_had")
        p_had, margin = devig(had)
        if not p_had:
            dropped["no_pre_had"] += 1
            continue

        hh = m.get("closing_hhad")
        p_hh, hh_margin = devig(hh) if hh else (None, None)
        ttg, ttg_odds = ttg_probs(snapshot(m, "ttg"))
        h, aw = sc
        rows.append({
            "match_id": m.get("matchId"),
            "match_num": m.get("matchNumStr"),
            "date": m.get("matchDate"),
            "kickoff": m.get("kickoff_iso"),
            "league": league,
            "league_id": m.get("leagueId"),
            "home": m.get("homeTeamAllName") or m.get("homeTeamAbbName"),
            "away": m.get("awayTeamAllName") or m.get("awayTeamAbbName"),
            "home_id": m.get("homeTeamId"),
            "away_id": m.get("awayTeamId"),
            "odds_had": had,
            "p_had": [round(x, 6) for x in p_had],
            "had_margin": round(margin, 6),
            "hhad_line": m.get("hhad_line"),
            "odds_hhad": hh,
            "p_hhad": [round(x, 6) for x in p_hh] if p_hh else None,
            "ttg": ttg,
            "odds_ttg": ttg_odds,
            "crs_market_top5": crs_top(snapshot(m, "crs")),
            "score_90": [h, aw],
            "result_1x2": "H" if h > aw else ("D" if h == aw else "A"),
            "total_goals": h + aw,
            "over25": (h + aw) > 2.5,
            "btts": h > 0 and aw > 0,
            "supremacy": h - aw,
        })

    rows.sort(key=lambda r: (r["date"] or "", r["match_id"]))
    with open(a.output, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n = len(rows)
    res = Counter(r["result_1x2"] for r in rows)
    lg = Counter(r["league"] for r in rows)
    rep = {
        "source": a.input,
        "clean_rows": n,
        "dropped": dict(dropped),
        "date_range": [rows[0]["date"], rows[-1]["date"]] if rows else None,
        "leagues": lg.most_common(),
        "result_freq": {k: round(res[k] / n, 4) for k in "HDA"} if n else None,
        "avg_had_margin": round(sum(r["had_margin"] for r in rows) / n, 4) if n else None,
        "with_hhad": sum(1 for r in rows if r["p_hhad"]),
        "with_ttg": sum(1 for r in rows if r["ttg"]),
        "with_crs": sum(1 for r in rows if r["crs_market_top5"]),
        "over25_rate": round(sum(r["over25"] for r in rows) / n, 4) if n else None,
        "btts_rate": round(sum(r["btts"] for r in rows) / n, 4) if n else None,
        "avg_goals": round(sum(r["total_goals"] for r in rows) / n, 4) if n else None,
    }
    json.dump(rep, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
