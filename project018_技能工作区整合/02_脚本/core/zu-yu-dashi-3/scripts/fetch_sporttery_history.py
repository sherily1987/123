#!/usr/bin/env python3
"""体彩历史赛果+赛前赔率：五大联赛及正式杯赛，排除友谊赛；保守并发、断点续采。"""
import argparse, concurrent.futures, json, os, random, time, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
BASE="https://webapi.sporttery.cn/gateway"
COND=BASE+"/uniform/fb/getConditionsV1.qry?method=result"
LIST=BASE+"/uniform/fb/getMatchDataPageListV1.qry"
FIXED=BASE+"/uniform/football/getFixedBonusV1.qry"
HEAD={"User-Agent":"Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36","Referer":"https://m.sporttery.cn/mjc/zqsj/?tab=result","Accept":"application/json,text/plain,*/*"}
BIG5={"英超","西甲","意甲","德甲","法甲"}; CUP_WORDS=("杯","欧冠","欧罗巴","欧协联","解放者杯","亚冠"); EXCLUDE=("国际赛","友谊","俱乐部赛")
STOP_CODES={403,429,567}
# [中文功能] 原子写JSON文件
def atomic(path,data):
 tmp=path+".tmp"
 with open(tmp,"w",encoding="utf-8") as f:json.dump(data,f,ensure_ascii=False,indent=2)
 os.replace(tmp,path)
# [中文功能] 带重试的HTTP GET
def get(url,retries=2):
 for n in range(retries+1):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers=HEAD),timeout=30) as r:return json.load(r)
  except urllib.error.HTTPError as e:
   if e.code in STOP_CODES: raise RuntimeError(f"STOP_HTTP_{e.code}")
   if n==retries:raise
  except Exception:
   if n==retries:raise
  time.sleep((2**n)+random.uniform(.2,.8))
# [中文功能] 联赛过滤：只保留五大联赛与杯赛
def keep(s):
 s=s or "";return s in BIG5 or (any(w in s for w in CUP_WORDS) and not any(w in s for w in EXCLUDE))
# [中文功能] 生成日期序列
def days(a,b):
 while a<=b:yield a;a+=timedelta(days=1)
# [中文功能] 展平场次列表
def flatten(j):return [m for g in j.get("value",{}).get("matchInfoList",[]) for m in g.get("subMatchList",[])]
# [中文功能] 取某时间前最近一次快照
def latest_before(rows,k):
 good=[]
 for r in rows or []:
  try:t=datetime.fromisoformat(r.get("updateDate","")+"T"+r.get("updateTime","00:00:00")+"+08:00")
  except ValueError:continue
  if not k or t<k:good.append((t,r))
 return max(good,key=lambda x:x[0])[1] if good else None
# [中文功能] 提取三项赔率
def odds(r,ks):
 if not r:return None
 try:return [float(r[k]) for k in ks]
 except (KeyError,TypeError,ValueError):return None
# [中文功能] 抓取单场固定奖金历史
def fixed(m):
 time.sleep(random.uniform(.25,.75));mid=m["matchId"];u=FIXED+"?"+urllib.parse.urlencode({"clientCode":3001,"matchId":mid})
 v=get(u)["value"];oh=v.get("oddsHistory") or {}
 try:k=datetime.fromisoformat(m["matchDate"]+"T"+(m.get("matchTime") or "00:00")[:5]+":00+08:00")
 except Exception:k=None
 names={"had":"hadList","hhad":"hhadList","crs":"crsList","ttg":"ttgList","hafu":"hafuList"};snap={x:latest_before(oh.get(y,[]),k) for x,y in names.items()}
 return {**m,"kickoff_iso":k.isoformat() if k else None,"closing_pre_match":snap,"closing_had":odds(snap["had"],["h","d","a"]),"hhad_line":snap["hhad"].get("goalLine") if snap["hhad"] else None,"closing_hhad":odds(snap["hhad"],["h","d","a"]),"odds_history":oh,"fixed_bonus_url":u,"match_result_list":v.get("matchResultList"),"sections_no999":v.get("sectionsNo999")}
# [中文功能] 下载指定区间历史数据
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--output",required=True);ap.add_argument("--start");ap.add_argument("--end");ap.add_argument("--workers",type=int,default=3);ap.add_argument("--list-delay",type=float,default=.35);a=ap.parse_args()
 c=get(COND)["value"];lo=date.fromisoformat(c["startDate"]);hi=date.fromisoformat(c["endDate"]);start=max(lo,date.fromisoformat(a.start)) if a.start else lo;end=min(hi,date.fromisoformat(a.end)) if a.end else hi
 old={};meta={}
 if os.path.exists(a.output):
  try:
   prev=json.load(open(a.output,encoding="utf-8"));old={str(x["matchId"]):x for x in prev.get("matches",[]) if "fixed_error" not in x};meta=prev
  except Exception:pass
 found={}
 for i,d in enumerate(days(start,end)):
  if i:time.sleep(max(0,a.list_delay))
  u=LIST+"?"+urllib.parse.urlencode({"method":"result","matchDate":d.isoformat()})
  for m in flatten(get(u)):
   if keep(m.get("leagueAbbName") or m.get("leagueAllName")):found[str(m["matchId"])]=m
 pending=[m for k,m in found.items() if k not in old];print(json.dumps({"phase":"list_done","selected":len(found),"cached":len(old),"pending":len(pending),"range":[str(start),str(end)]},ensure_ascii=False),flush=True)
 errors=[]
 # [中文功能] 并发任务包装
 def task(m):
  try:return fixed(m)
  except Exception as e:return {**m,"fixed_error":str(e)}
 with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(a.workers,3))) as ex:
  for n,row in enumerate(ex.map(task,pending),1):
   if "fixed_error" in row:errors.append(row)
   else:old[str(row["matchId"])]=row
   if n%20==0:
    meta.update({"schema_version":"1.1","source":"中国体彩网移动端官方赛果与固定奖金接口","fetched_at":datetime.now(timezone.utc).isoformat(),"available_range":{"start":str(lo),"end":str(hi)},"requested_range":{"start":str(start),"end":str(end)},"count":len(old),"matches":list(old.values()),"errors":errors});atomic(a.output,meta);print(json.dumps({"saved":len(old),"errors":len(errors)},ensure_ascii=False),flush=True)
   if any(str(x.get("fixed_error","")).startswith("STOP_HTTP_") for x in errors):break
 meta.update({"schema_version":"1.1","source":"中国体彩网移动端官方赛果与固定奖金接口","fetched_at":datetime.now(timezone.utc).isoformat(),"available_range":{"start":str(lo),"end":str(hi)},"requested_range":{"start":str(start),"end":str(end)},"filter":{"leagues":sorted(BIG5),"cups":"正式杯赛关键词","excluded":list(EXCLUDE)},"count":len(old),"matches":list(old.values()),"errors":errors,"notes":["closing_pre_match仅选开球前最后快照","90分钟/加时/点球须隔离","禁止赛后信息泄漏"]});atomic(a.output,meta)
 print(json.dumps({"status":"ok" if not errors else "partial","count":len(old),"errors":len(errors),"output":a.output},ensure_ascii=False))
if __name__=="__main__":main()
