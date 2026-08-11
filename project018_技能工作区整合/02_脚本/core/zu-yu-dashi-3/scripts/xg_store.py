#!/usr/bin/env python3
"""多平台xG标准化、去重与聚合。JSONL长期库。"""
import argparse,csv,json,hashlib,statistics
from datetime import datetime,timezone
from pathlib import Path
DEFAULT='C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/zu-yu-dashi-3/xg/xg_records.jsonl'
# [中文功能] 标准化队名（去空格非字母数字）
def norm(s):return ''.join(c.lower() for c in str(s).strip() if c.isalnum())
# [中文功能] 生成比赛去重键
def key(r):return '|'.join([str(r['date'])[:10],norm(r['home']),norm(r['away']),str(r.get('competition',''))])
# [中文功能] 生成记录稳定哈希ID
def rid(r):return hashlib.sha256((key(r)+'|'+r['source']).encode()).hexdigest()[:20]
# [中文功能] 读取jsonl记录
def read(p):
 p=Path(p);return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []
# [中文功能] xG库子命令：add/aggregate
def main():
 ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='cmd',required=True)
 a=sub.add_parser('add');a.add_argument('--file',required=True);a.add_argument('--store',default=DEFAULT)
 g=sub.add_parser('aggregate');g.add_argument('--store',default=DEFAULT);g.add_argument('--output',required=True)
 x=ap.parse_args()
 if x.cmd=='add':
  raw=json.load(open(x.file,encoding='utf-8'));items=raw.get('records',raw) if isinstance(raw,dict) else raw;old=read(x.store);byid={z['record_id']:z for z in old};added=updated=0
  for r in items:
   for f in ('date','home','away','xg_home','xg_away','source'):
    if r.get(f) is None:raise SystemExit('missing '+f)
   z={'date':str(r['date'])[:10],'competition':r.get('competition',''),'home':r['home'],'away':r['away'],'xg_home':float(r['xg_home']),'xg_away':float(r['xg_away']),'source':r['source'],'source_type':r.get('source_type','manual'),'status':r.get('status','VALID'),'url':r.get('url'),'observed_at':r.get('observed_at') or datetime.now(timezone.utc).isoformat(),'provider_model':r.get('provider_model',r['source']),'notes':r.get('notes',[])};z['match_key']=key(z);z['record_id']=rid(z)
   if z['record_id'] in byid:updated+=1
   else:added+=1
   byid[z['record_id']]=z
  p=Path(x.store);p.parent.mkdir(parents=True,exist_ok=True);p.write_text('\n'.join(json.dumps(z,ensure_ascii=False,sort_keys=True) for z in byid.values())+'\n',encoding='utf-8');print(json.dumps({'added':added,'updated':updated,'total':len(byid),'store':str(p)},ensure_ascii=False))
 else:
  rows=read(x.store);groups={}
  for r in rows:groups.setdefault(r['match_key'],[]).append(r)
  out=[]
  for k,z in groups.items():
   # 同平台只保留最新；跨平台取中位数，保留离散度
   latest={}
   for r in z:
    if r['source'] not in latest or r['observed_at']>latest[r['source']]['observed_at']:latest[r['source']]=r
   v=list(latest.values());hs=[r['xg_home'] for r in v];aws=[r['xg_away'] for r in v]
   out.append({'match_key':k,'date':v[0]['date'],'home':v[0]['home'],'away':v[0]['away'],'providers':sorted(latest),'provider_count':len(v),'xg_home_median':statistics.median(hs),'xg_away_median':statistics.median(aws),'xg_home_range':[min(hs),max(hs)],'xg_away_range':[min(aws),max(aws)],'records':v})
  Path(x.output).parent.mkdir(parents=True,exist_ok=True);Path(x.output).write_text(json.dumps({'matches':out},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'matches':len(out),'output':x.output},ensure_ascii=False))
if __name__=='__main__':main()
