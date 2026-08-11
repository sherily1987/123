#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国体彩移动端官方链路采集器。
赛程列表取 matchId，再逐场低频取 HAD/HHAD/CRS/TTG/HAFU。
"""
import argparse, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone

BASE = "https://webapi.sporttery.cn/gateway"
LIST_API = BASE + "/uniform/fb/getMatchDataPageListV1.qry"
FIXED_API = BASE + "/uniform/football/getFixedBonusV1.qry"
UA = {"User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36",
      "Referer":"https://m.sporttery.cn/mjc/zqsj/?tab=concern", "Accept":"application/json,text/plain,*/*"}

# [中文功能] 请求体彩官方接口并解析JSON
def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if str(data.get("errorCode", "0")) != "0":
        raise RuntimeError(f"API error {data.get('errorCode')}: {data.get('errorMessage')}")
    return data

# [中文功能] 安全转float（失败返回None）
def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

# [中文功能] 取盘口历史最后一行
def latest(rows):
    return rows[-1] if rows else {}

# [中文功能] 拼装盘口更新时间戳
def stamp(row):
    if not row: return None
    return " ".join(x for x in [row.get("updateDate"), row.get("updateTime")] if x) or None

# [中文功能] 解析比分玩法CRS赔率
def parse_crs(row):
    out = {}
    for k, v in row.items():
        if len(k) == 6 and k[0] == "s" and k[3] == "s" and not k.endswith("f"):
            try: out[f"{int(k[1:3])}-{int(k[4:6])}"] = float(v)
            except (ValueError, TypeError): pass
    labels = {"s-1sh":"胜其他", "s-1sd":"平其他", "s-1sa":"负其他"}
    for k, label in labels.items():
        if num(row.get(k)) is not None: out[label] = num(row[k])
    return out or None

# [中文功能] 解析总进球TTG 8档赔率
def parse_ttg(row):
    out = {}
    for i in range(8):
        v = num(row.get(f"s{i}"))
        if v is not None: out[str(i) if i < 7 else "7+"] = v
    return out or None

# [中文功能] 解析半全场HAFU九宫格赔率
def parse_hafu(row):
    out = {k:num(row.get(k)) for k in ["hh","hd","ha","dh","dd","da","ah","ad","aa"]}
    out = {k:v for k,v in out.items() if v is not None}
    return out or None

# [中文功能] 展平官方按天分组的场次列表
def parse_list(data):
    out=[]
    for day in data.get("value",{}).get("matchInfoList",[]):
        for m in day.get("subMatchList",[]): out.append(m)
    return out

# [中文功能] 从赛程列表提取赛果（半场/全场比分）
def parse_results(data, date=None):
    """从赛程列表提取赛果。sectionsNo1=半场，sectionsNo999=全场。"""
    out=[]
    for m in parse_list(data):
        if date and m.get("businessDate")!=date and m.get("matchDate")!=date: continue
        ft=(m.get("sectionsNo999") or "").strip(); ht=(m.get("sectionsNo1") or "").strip()
        out.append({"match_id":m.get("matchId"),"match_num":m.get("matchNumStr"),
          "business_date":m.get("businessDate"),"kickoff_local":f"{m.get('matchDate')} {m.get('matchTime')}",
          "league":m.get("leagueAbbName"),"home":m.get("homeTeamAbbName"),"away":m.get("awayTeamAbbName"),
          "status_name":m.get("matchStatusName"),
          "finished":m.get("matchStatusName")=="已完成" and bool(ft),
          "score_ht":ht.replace(":","-") or None,"score_90":ft.replace(":","-") or None})
    return out

# [中文功能] 把原始采集转成模型输入JSON
def to_input(items, fetched_at):
    matches=[]
    for x in items:
        if not x.get("odds_eligible") or not x.get("model_odds"): continue
        d={"home":x["home"],"away":x["away"],"competition":x["league"],"stage":x["league"],
           "kickoff":x["kickoff_iso"],"mode":"market_only","odds":x["model_odds"],"context_confirmed":True,
           "field_meta":{
               "odds":{"reliability":100,"freshness":100,"source":"中国体彩网移动端官方固定奖金接口","observed_at":x.get("had_updated_at") or fetched_at},
               "hhad":{"reliability":100,"freshness":100,"source":"中国体彩网移动端官方固定奖金接口","observed_at":x.get("hhad_updated_at") or fetched_at},
               "ttg":{"reliability":100,"freshness":100,"source":"中国体彩网移动端官方固定奖金接口","observed_at":x.get("ttg_updated_at") or fetched_at},
               "hafu":{"reliability":100,"freshness":100,"source":"中国体彩网移动端官方固定奖金接口","observed_at":x.get("hafu_updated_at") or fetched_at},
               "crs":{"reliability":100,"freshness":100,"source":"中国体彩网移动端官方固定奖金接口","observed_at":x.get("crs_updated_at") or fetched_at}
           },
           "assumptions":[],"sporttery_meta":{"match_id":x["match_id"],"match_num":x["match_num"]}}
        if x.get("model_hhad"):
            # Sporttery HHAD is a three-way pool, not an Asian two-way line.
            d["hhad"] = x["model_hhad"]
            d["assumptions"].append("已提供体彩HHAD三态；未映射为亚洲盘ah_line")
        else:
            d["field_meta"].pop("hhad", None)
        if x.get("ttg") and all(k in x["ttg"] for k in ["0","1","2","3","4","5","6","7+"]):
            d["ttg"]={"odds":[x["ttg"][k] for k in ["0","1","2","3","4","5","6","7+"]]}
        else:
            d["field_meta"].pop("ttg", None)
            d["assumptions"].append("无完整TTG，比分/O-U/BTTS由现有市场反解")
        HK=["hh","hd","ha","dh","dd","da","ah","ad","aa"]
        if x.get("hafu") and all(k in x["hafu"] for k in HK):
            d["hafu"]={"odds":[x["hafu"][k] for k in HK]}
        else:
            d["field_meta"].pop("hafu", None)
        if x.get("team_ids"):
            d["sporttery_meta"].update(x["team_ids"])
        matches.append(d)
    return {"matches":matches}

# [中文功能] 采集入口：按日期/单场拉取全盘口
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",required=True)
    ap.add_argument("--date",help="business_date或开球日期，YYYY-MM-DD")
    ap.add_argument("--match-num",help="竞彩编号，如 周六001")
    ap.add_argument("--match-id",type=int,help="直接采集单场matchId")
    ap.add_argument("--emit-input")
    ap.add_argument("--delay",type=float,default=1.5,help="逐场请求间隔秒，默认1.5")
    ap.add_argument("--method",choices=["concern","result","all"],default="concern")
    ap.add_argument("--results",action="store_true",help="只采赛果(sectionsNo999)，不逐场拉赔率")
    a=ap.parse_args()
    fetched_at=datetime.now(timezone.utc).isoformat()
    if a.results:
        q={"method":"result"}
        if a.date: q["matchDate"]=a.date
        url=LIST_API+"?"+urllib.parse.urlencode(q)
        rows=parse_results(fetch(url),a.date)
        if a.match_num: rows=[r for r in rows if r["match_num"]==a.match_num]
        if a.match_id: rows=[r for r in rows if r["match_id"]==a.match_id]
        out={"schema_version":"1.0","collector_version":"mobile-results-3.5.0",
             "source":"中国体彩网移动端官方赛果","source_url":url,"fetched_at":fetched_at,
             "count":len(rows),"finished_count":sum(1 for r in rows if r["finished"]),"results":rows,
             "notes":["score_90取sectionsNo999(全场90分钟)。","未完成场次score_90为null，不得臆补。"]}
        with open(a.output,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
        print(json.dumps({"status":"ok","count":len(rows),"finished":out["finished_count"],"output":a.output},ensure_ascii=False))
        return
    if a.match_id:
        seeds=[{"matchId":a.match_id,"matchNumStr":a.match_num}]
        list_url=None
    else:
        q={"method":a.method}
        if a.date: q["matchDate"]=a.date
        list_url=LIST_API+"?"+urllib.parse.urlencode(q)
        seeds=parse_list(fetch(list_url))
        if a.date: seeds=[m for m in seeds if m.get("businessDate")==a.date or m.get("matchDate")==a.date]
        if a.match_num: seeds=[m for m in seeds if (m.get("matchNumStr") or str(m.get("matchNum")))==a.match_num]
    items=[]
    for i,m in enumerate(seeds):
        if i: time.sleep(max(0,a.delay))
        mid=m.get("matchId")
        fixed_url=FIXED_API+"?"+urllib.parse.urlencode({"clientCode":3001,"matchId":mid})
        value=fetch(fixed_url).get("value",{})
        oh=value.get("oddsHistory") or {}
        had=latest(oh.get("hadList",[])); hhad=latest(oh.get("hhadList",[])); crs=latest(oh.get("crsList",[])); ttg=latest(oh.get("ttgList",[])); hafu=latest(oh.get("hafuList",[]))
        odds=[num(had.get(k)) for k in ["h","d","a"]]
        if any(v is None for v in odds): odds=None
        hh=[num(hhad.get(k)) for k in ["h","d","a"]]; line=num(hhad.get("goalLine"))
        kickoff_date=m.get("matchDate"); kickoff_time=(m.get("matchTime") or "00:00")[:5]
        status=str(m.get("matchStatus") or "")
        items.append({"match_id":mid,"match_num":m.get("matchNumStr") or m.get("matchNum"),"business_date":m.get("businessDate"),
          "kickoff_local":f"{kickoff_date or ''} {kickoff_time}","kickoff_iso":f"{kickoff_date}T{kickoff_time}:00+08:00" if kickoff_date else None,
          "timezone":"Asia/Shanghai","league":m.get("leagueAbbName") or oh.get("leagueAbbName"),
          "home":m.get("homeTeamAbbName") or oh.get("homeTeamAbbName"),"away":m.get("awayTeamAbbName") or oh.get("awayTeamAbbName"),
          "status":status,"status_name":m.get("matchStatusName"),"model_odds":odds,
          "model_hhad":{"line":line,"odds":hh} if line is not None and all(v is not None for v in hh) else None,
          "crs":parse_crs(crs),"ttg":parse_ttg(ttg),"hafu":parse_hafu(hafu),
          "team_ids":{"home_team_id":oh.get("homeTeamId") or m.get("homeTeamId"),
                      "away_team_id":oh.get("awayTeamId") or m.get("awayTeamId"),
                      "league_id":oh.get("leagueId") or m.get("leagueId"),
                      "home_full":oh.get("homeTeamAllName") or m.get("homeTeamAllName"),
                      "away_full":oh.get("awayTeamAllName") or m.get("awayTeamAllName")},
          "single_pools":{x.get("poolCode"):x.get("single") for x in (oh.get("singleList") or [])},
          "had_updated_at":stamp(had),"hhad_updated_at":stamp(hhad),"crs_updated_at":stamp(crs),"ttg_updated_at":stamp(ttg),"hafu_updated_at":stamp(hafu),
          "odds_eligible":odds is not None and status in ["2","3","Selling",""],"fixed_bonus_url":fixed_url,
          "odds_history":oh,"match_result_list":value.get("matchResultList"),"sections_no999":value.get("sectionsNo999")})
    out={"schema_version":"3.0","collector_version":"mobile-3.5.0","source":"中国体彩网移动端官方链路",
         "source_url":list_url,"fetched_at":fetched_at,"count":len(items),"matches":items,
         "notes":["唯一链路：移动端 getConditionsV1 + getMatchDataPageListV1 + 逐场 getFixedBonusV1。","CRS只作相对排序，不直接归一化。","禁止调用任何已废弃PC/计算器接口。"]}
    with open(a.output,"w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=2)
    res={"status":"ok","count":len(items),"output":a.output}
    if a.emit_input:
        inp=to_input(items,fetched_at)
        with open(a.emit_input,"w",encoding="utf-8") as f: json.dump(inp,f,ensure_ascii=False,indent=2)
        res.update({"model_input":a.emit_input,"input_count":len(inp["matches"])})
    print(json.dumps(res,ensure_ascii=False))
if __name__=="__main__": main()
