#!/usr/bin/env python3
import argparse,json
from pathlib import Path
from backtest_lib import *
# [中文功能] 把'主-客'比分字符串转成整数元组
def score(s):
 x=s.split('-');
 if len(x)!=2 or any(not z.isdigit() for z in x):raise ValueError('score must H-A nonnegative integers')
 return {'home':int(x[0]),'away':int(x[1])}
# [中文功能] 为单场登记写入赛果
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--match-id',required=True);ap.add_argument('--score-90',required=True);ap.add_argument('--score-ht');ap.add_argument('--score-et');ap.add_argument('--penalty-winner',choices=['home','away']);ap.add_argument('--advanced',choices=['home','away']);ap.add_argument('--source',required=True);ap.add_argument('--source-url');ap.add_argument('--store',default='H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest');a=ap.parse_args()
 s90=score(a.score_90);sht=score(a.score_ht) if a.score_ht else None;set_=score(a.score_et) if a.score_et else None
 if a.penalty_winner and not set_:raise SystemExit('penalties require score-et')
 rec={'schema_version':'1.1','match_id':a.match_id,'status':'finished','score_ht':sht,'score_90':s90,'score_et':set_,'penalty_winner':a.penalty_winner,'advanced':a.advanced,'settlement_scope':'90min','source':{'name':a.source,'url':a.source_url,'observed_at':now()},'revision':1}
 p=Path(a.store)/'results'/(a.match_id+'.json')
 if p.exists():raise SystemExit('result exists; no silent overwrite')
 atomic_json(p,rec);append_jsonl(Path(a.store)/'results_registry.jsonl',{'match_id':a.match_id,'path':str(p),'hash':sha(rec),'created_at':now()});print(json.dumps({'status':'settled','path':str(p)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
