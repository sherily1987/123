#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体彩官方前瞻数据采集器（独立于赔率的强度锚）。

数据源：m.sporttery.cn/zqlszl/bssj/?mid= 页面调用的官方接口，全部走 webapi.sporttery.cn。
    getMatchFeatureV1      近N场场均进球/失球、胜率切片   ← 主要用途
    getResultHistoryV1     历史交锋（含半场比分）
    getMatchResultV1       双方近N场逐场比分
    getInjurySuspensionV1  伤停名单
    getMatchTablesV1       积分榜

核心产出 `strength`：由 goalAvg/lossGoalAvg 交叉组合出的 lambda_home/lambda_away，
可作为 hybrid 模式下独立于赔率的强度锚。

⚠️ 这些统计未做对手强度调整，且是市场早已知晓的公开信息，
   不保证加入后更准（见 pitfalls 2.2 的 ClubElo 教训），必须回测验证。

用法：
  python3 fetch_match_preview.py --match-id 2040674 --output prev.json
  python3 fetch_match_preview.py --from-collect raw_sporttery.json --output prev.json
"""
import argparse, json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://webapi.sporttery.cn/gateway/uniform/football/"
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer": "https://m.sporttery.cn/zqlszl/bssj/", "Accept": "application/json,text/plain,*/*"}


# [中文功能] 带重试地请求体彩官方前瞻接口
def fetch(q, retries=2):
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(BASE + q, headers=UA), timeout=25) as r:
                d = json.load(r)
            if str(d.get("errorCode", "0")) != "0":
                return None
            return d.get("value")
        except Exception:
            if i == retries: return None
            time.sleep(2 * (i + 1))
    return None


# [中文功能] 安全转float（失败返回默认值）
def fnum(x, dv=None):
    try: return float(x)
    except (TypeError, ValueError): return dv


# [中文功能] 由近N场攻防均值交叉生成λ锚
def build_strength(feat):
    """由近N场攻防均值交叉出 λ 锚。

    主队λ = (主队场均进球 + 客队场均失球) / 2
    客队λ = (客队场均进球 + 主队场均失球) / 2
    这样同时用到进攻端与对手防守端，比单看进球稳。
    """
    if not feat: return None
    g, l = feat.get("goalAvg") or {}, feat.get("lossGoalAvg") or {}
    hg, ag = fnum(g.get("homeGoalAvgCnt")), fnum(g.get("awayGoalAvgCnt"))
    hl, al = fnum(l.get("homeLossGoalAvgCnt")), fnum(l.get("awayLossGoalAvgCnt"))
    if None in (hg, ag, hl, al): return None
    n = g.get("totalLegCnt") or 0
    return {
        "lambda_home": round((hg + al) / 2, 3),
        "lambda_away": round((ag + hl) / 2, 3),
        "sample_legs": n,
        "raw": {"home_goal_avg": hg, "away_goal_avg": ag,
                "home_loss_avg": hl, "away_loss_avg": al},
        "status": "VALID" if n >= 8 else "LOW_SAMPLE",
        "note": "近%s场统计，未做对手强度调整；属公开信息，与市场高度重叠" % n,
    }


# [中文功能] 采集单场特征、交锋、近期、伤停、积分、赛程
def collect(mid, terms=10, hist=5):
    feat = fetch(f"getMatchFeatureV1.qry?termLimits={terms}&sportteryMatchId={mid}"); time.sleep(.8)
    hh = fetch(f"getResultHistoryV1.qry?sportteryMatchId={mid}&termLimits={hist}&tournamentFlag=0&homeAwayFlag=0"); time.sleep(.8)
    recent = fetch(f"getMatchResultV1.qry?sportteryMatchId={mid}&termLimits={terms}&tournamentFlag=0&homeAwayFlag=0"); time.sleep(.8)
    inj = fetch(f"getInjurySuspensionV1.qry?sportteryMatchId={mid}"); time.sleep(.8)
    tables = fetch(f"getMatchTablesV1.qry?sportteryMatchId={mid}"); time.sleep(.8)
    players = fetch(f"getMatchPlayerV1.qry?sportteryMatchId={mid}&termLimits=3"); time.sleep(.8)
    future = fetch(f"getFutureMatchesV1.qry?sportteryMatchId={mid}&termLimits=4"); time.sleep(.8)
    head = fetch(f"getMatchHeadV1.qry?source=m&sportteryMatchId={mid}")

    # [中文功能] 提取主/客队一方的近期赛程
    def side_matches(side):
        s = (recent or {}).get(side) or {}
        out = []
        for m in (s.get("matchList") or []):
            out.append({"date": m.get("matchDateTime") or m.get("matchDate"),
                        "home": m.get("homeTeamShortName"), "away": m.get("awayTeamShortName"),
                        "score_90": m.get("fullCourtGoal"), "score_ht": m.get("halfTimeGoal"),
                        "league_id": m.get("gmLeagueId"),
                        "home_team_id": m.get("homeTeamId"), "away_team_id": m.get("awayTeamId")})
        return out

    h2h = []
    for m in ((hh or {}).get("matchList") or []):
        h2h.append({"date": m.get("matchDateTime") or m.get("matchDate"),
                    "home": m.get("homeTeamShortName"), "away": m.get("awayTeamShortName"),
                    "score_90": m.get("fullCourtGoal"), "score_ht": m.get("halfTimeGoal"),
                    "result": m.get("homeMatchResult"), "league_id": m.get("gmLeagueId"),
                    "home_team_id": m.get("homeTeamId"), "away_team_id": m.get("awayTeamId")})

    # [中文功能] 按位置与出场率折算攻防门三档缺阵冲击
    def injuries(side):
        """按位置与出场率折算攻/防/门将三档缺阵冲击。

        引擎字段范围 0~0.5。单人上限按位置设定，再乘出场率（首发权重更高），
        多人累加后截断。这是唯一真正独立于赔率的信息源。
        """
        s = (inj or {}).get(side) or {}
        lst = s.get("injuriesAndSuspensionsList") or []
        # [UNFITTED] 单人满额冲击：前锋主要削攻，后卫削防，门将单列
        CAP = {"Forward": (.10, .00), "Midfielder": (.06, .03),
               "Defender": (.01, .09), "Goalkeeper": (.00, .00)}
        atk = dfs = gk = 0.0
        detail = []
        for p in lst:
            pos = p.get("playerPositionCode") or ""
            ap = float(p.get("appearanceCnt") or 0)
            st = float(p.get("startedMatchCnt") or 0)
            # 出场率：首发算满，替补算半，10场为满额基准
            w = min(1.0, (st + (ap - st) * .5) / 10.0)
            a, d = CAP.get(pos, (.05, .04))
            if pos == "Goalkeeper":
                gk += .10 * w
            atk += a * w; dfs += d * w
            detail.append({"name": p.get("personName"), "pos": p.get("playerPositionDesc"),
                           "apps": int(ap), "starts": int(st),
                           "type": "伤" if p.get("injuryFlag") else ("停" if p.get("suspensionFlag") else "?"),
                           "weight": round(w, 2)})
        cl = lambda x: round(min(0.5, max(0.0, x)), 4)
        # An explicit home/away response with an empty list is observable but
        # does not prove that no absences exist; some providers return empty
        # payloads when coverage is missing. Keep it out of usable evidence.
        response_present = isinstance(inj, dict) and any(side in inj for side in ("home", "away"))
        status = "VALID" if lst else "EMPTY_UNCONFIRMED" if response_present else "UNAVAILABLE"
        return {"team": s.get("teamShortName"), "team_id": s.get("teamId"),
                "count": len(lst),
                "status": status,
                "confirmed_no_absence": False,
                "attack_absence": cl(atk), "defense_absence": cl(dfs), "gk_absence": cl(gk),
                "players": detail, "list": lst}

    return {
        "match_id": mid,
        "home": (feat or {}).get("homeTeamShortName") or (head or {}).get("homeTeamShortName"),
        "away": (feat or {}).get("awayTeamShortName") or (head or {}).get("awayTeamShortName"),
        "kickoff": (head or {}).get("matchDateTime"),
        "team_ids": {"home": (feat or {}).get("homeTeamId"), "away": (feat or {}).get("awayTeamId")},
        "strength": build_strength(feat),
        "feature": {k: (feat or {}).get(k) for k in
                    ["goalAvg", "lossGoalAvg", "last", "eachHomeAway", "sameHomeAway", "eachSameHomeAway"]},
        "h2h": h2h,
        "h2h_statistics": (hh or {}).get("statistics"),
        "recent_home": side_matches("home"),
        "recent_away": side_matches("away"),
        "injuries": {"home": injuries("home"), "away": injuries("away")},
        "tables": (tables or {}).get("tables") or [],
        "players": {"home": (players or {}).get("home") or {}, "away": (players or {}).get("away") or {}},
        "future": {"home": (future or {}).get("home") or {}, "away": (future or {}).get("away") or {}},
        "available": bool(feat),
    }


# [中文功能] 按matchId或采集文件批量生成前瞻JSON
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--match-id", type=int)
    ap.add_argument("--from-collect", help="fetch_sporttery_full 的原始JSON，批量取其中所有 match_id")
    ap.add_argument("--output", required=True)
    ap.add_argument("--terms", type=int, default=10, help="近N场，最大30")
    ap.add_argument("--hist", type=int, default=5, help="历史交锋N场")
    ap.add_argument("--delay", type=float, default=1.2)
    a = ap.parse_args()

    if a.match_id:
        mids = [a.match_id]
    elif a.from_collect:
        src = json.load(open(a.from_collect, encoding="utf-8"))
        mids = [m["match_id"] for m in src.get("matches", []) if m.get("match_id")]
    else:
        raise SystemExit("需要 --match-id 或 --from-collect")

    items = []
    for i, mid in enumerate(mids):
        if i: time.sleep(a.delay)
        items.append(collect(mid, a.terms, a.hist))

    out = {"schema_version": "1.0", "collector_version": "preview-3.4.1",
           "source": "中国体彩网移动端官方前瞻接口",
           "source_page": "https://m.sporttery.cn/zqlszl/bssj/?mid=",
           "fetched_at": datetime.now(timezone.utc).isoformat(),
           "terms": a.terms, "count": len(items),
           "available_count": sum(1 for x in items if x["available"]),
           "matches": items,
           "notes": ["strength 由 goalAvg/lossGoalAvg 交叉得出，可作 hybrid 强度锚。",
                     "统计未做对手强度调整，且与市场信息高度重叠，必须回测验证后再信任。",
                     "sample_legs<8 标 LOW_SAMPLE。"]}
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    with open(a.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"status": "ok", "count": len(items),
                      "available": out["available_count"], "output": a.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
