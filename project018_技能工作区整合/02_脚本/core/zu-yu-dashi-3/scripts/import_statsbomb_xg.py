#!/usr/bin/env python3
"""StatsBomb Open Data事件JSON→标准xG记录JSON。"""
import argparse,json
from pathlib import Path
# [中文功能] 从StatsBomb仓库导入xG事件数据
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repo',required=True,help='statsbomb open-data目录');ap.add_argument('--output',required=True);ap.add_argument('--max',type=int);a=ap.parse_args();root=Path(a.repo);matches=[]
 for p in (root/'data'/'matches').glob('*/*.json'):
  for m in json.load(open(p,encoding='utf-8')):
   matches.append(m)
 if a.max:matches=matches[:a.max]
 rec=[]
 for m in matches:
  mid=m['match_id'];ep=root/'data'/'events'/f'{mid}.json'
  if not ep.exists():continue
  x={m['home_team']['home_team_name']:0.0,m['away_team']['away_team_name']:0.0}
  for e in json.load(open(ep,encoding='utf-8')):
   if e.get('type',{}).get('name')=='Shot':x[e['team']['name']]=x.get(e['team']['name'],0)+float(e.get('shot',{}).get('statsbomb_xg',0))
  rec.append({'date':m['match_date'],'competition':m['competition']['competition_name'],'home':m['home_team']['home_team_name'],'away':m['away_team']['away_team_name'],'xg_home':round(x[m['home_team']['home_team_name']],4),'xg_away':round(x[m['away_team']['away_team_name']],4),'source':'StatsBomb Open Data','source_type':'open_event_data','provider_model':'StatsBomb','status':'VALID','url':'https://github.com/statsbomb/open-data','notes':[f'match_id={mid}']})
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps({'records':rec},ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'records':len(rec),'output':a.output},ensure_ascii=False))
if __name__=='__main__':main()
