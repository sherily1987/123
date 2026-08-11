#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from statistics import mean
import sys
sys.path.insert(0,'H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts')
from odds_methods import devig
METHODS=('proportional','additive','power','shin'); SNAPS=('opening','t_minus_24h','t_minus_6h','closing')
LEAGUES=('意甲','西甲','法甲','欧冠','欧罗巴')
# [中文功能] 把比分转成胜平负索引（主胜0/平1/客胜2）
def idx(s): return 0 if s[0]>s[1] else (1 if s[0]==s[1] else 2)
# [中文功能] 计算指定快照的Brier/LogLoss/命中统计
def score(rows,m,s):
 bs=[];ls=[];hit=[]
 for r in rows:
  o=(r.get('snapshots') or {}).get(s) or {}; y=r.get('score_90'); odds=o.get('odds')
  if not y or not odds: continue
  try:p,_=devig(odds,m); i=idx(y)
  except Exception: continue
  bs.append(sum((p[j]-(j==i))**2 for j in range(3))); ls.append(-math.log(max(1e-15,p[i]))); hit.append(int(max(range(3),key=lambda j:p[j])==i))
 return {'n':len(bs),'brier':round(mean(bs),8) if bs else None,'logloss':round(mean(ls),8) if ls else None,'accuracy_pct':round(mean(hit)*100,3) if hit else None}
# [中文功能] 按时间顺序切分训练/验证/测试三段样本
def evaluate_split(rows):
 n=len(rows); a=max(1,int(n*.6)); b=max(a+1,int(n*.8)); return rows[:a],rows[a:b],rows[b:]
# [中文功能] 对选定联赛跑留出样本（OOS）回测并输出报告
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--dir',required=True); ap.add_argument('--output',required=True); ap.add_argument('--leagues',nargs='*',default=list(LEAGUES)); ap.add_argument('--snapshots',nargs='*',default=list(SNAPS)); args=ap.parse_args(); base=Path(args.dir); out={'schema_version':'selected-league-oos-1.0','split':'chronological 60% train / 20% validation / 20% test','selection':'select method by train Brier separately for league and snapshot; validation/test are untouched','leagues':{}}
 for league in args.leagues:
  rows=[json.loads(x) for x in (base/(league+'.jsonl')).read_text(encoding='utf-8').splitlines() if x.strip()]
  rows=[r for r in rows if r.get('score_90') is not None]; rows.sort(key=lambda r:r.get('kickoff') or '')
  train,val,test=evaluate_split(rows); item={'n':len(rows),'split_n':{'train':len(train),'validation':len(val),'test':len(test)},'date_ranges':{k: ([v[0].get('kickoff','')[:10], v[-1].get('kickoff','')[:10]] if v else None) for k,v in [('train',train),('validation',val),('test',test)]},'snapshots':{}}
  for s in args.snapshots:
   train_scores={m:score(train,m,s) for m in METHODS}; best=min(METHODS,key=lambda m:(train_scores[m]['brier'] is None,train_scores[m]['brier'] if train_scores[m]['brier'] is not None else 9))
   item['snapshots'][s]={'train':train_scores,'selected_by_train':best,'validation':{m:score(val,m,s) for m in METHODS},'test':{m:score(test,m,s) for m in METHODS},'selected_test':score(test,best,s),'default_test':score(test,'proportional',s)}
  out['leagues'][league]=item
 Path(args.output).parent.mkdir(parents=True,exist_ok=True); Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 summary={}
 for lg,x in out['leagues'].items():
  summary[lg]={s:{'train_selected':v['selected_by_train'],'test_selected':v['selected_test'],'test_default':v['default_test']} for s,v in x['snapshots'].items()}
 print(json.dumps({'status':'ok','output':args.output,'summary':summary},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
