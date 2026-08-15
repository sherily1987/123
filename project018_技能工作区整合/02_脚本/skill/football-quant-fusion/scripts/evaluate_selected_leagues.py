#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math
from pathlib import Path
from statistics import mean
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import core_scripts_dir  # noqa: E402
# 2026-08-16：原硬编码指向外部 football-quant-fusion-suite 的 zu-yu-dashi-3 物理拷贝
# （靠人工 cp 同步、历史上真的漂移过）。改走 core_scripts_dir()，默认仓库内唯一事实源。
sys.path.insert(0, str(core_scripts_dir()))
from odds_methods import devig
METHODS=('proportional','additive','power','shin'); SNAPS=('opening','t_minus_24h','t_minus_6h','closing')
# [中文功能] 把比分转成胜平负索引（主胜0/平1/客胜2）
def idx(s): return 0 if s[0]>s[1] else (1 if s[0]==s[1] else 2)
# [中文功能] 计算三元Brier分数（概率与结果的平方误差）
def brier(p,i): return sum((p[j]-(j==i))**2 for j in range(3))
# [中文功能] 计算期望校准误差ECE（分10桶统计）
def ece(obs):
 v=[(p[j],int(i==j)) for p,i in obs for j in range(3)]; z=0; bins=[]
 for b in range(10):
  lo,hi=b/10,(b+1)/10; g=[x for x in v if lo<=x[0]<(hi if b<9 else 1.000001)]
  if not g: continue
  ap=mean(x[0] for x in g); aa=mean(x[1] for x in g); z+=len(g)/len(v)*abs(ap-aa)
  bins.append({'bin':f'{lo:.1f}-{hi:.1f}','n':len(g),'avg_prob':round(ap,6),'actual_rate':round(aa,6)})
 return round(z,6),bins
# [中文功能] 汇总单联赛所有记录的校准与命中指标
def run(rows,m,s):
 obs=[]; bs=[]; ls=[]; hit=[]
 for r in rows:
  o=(r.get('snapshots') or {}).get(s) or {}; score=r.get('score_90'); odds=o.get('odds')
  if not score or not odds: continue
  try:p,_=devig(odds,m); i=idx(score)
  except Exception: continue
  obs.append((p,i)); bs.append(brier(p,i)); ls.append(-math.log(max(1e-15,p[i]))); hit.append(int(max(range(3),key=lambda j:p[j])==i))
 if not obs:return {'n':0}
 ec,bins=ece(obs); return {'n':len(obs),'brier':round(mean(bs),8),'logloss':round(mean(ls),8),'accuracy_pct':round(mean(hit)*100,3),'ece':ec,'calibration_bins':bins}
# [中文功能] 按联赛批量评估并输出总报告
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--dir',required=True);ap.add_argument('--output',required=True);a=ap.parse_args(); base=Path(a.dir)
 leagues=('意甲','西甲','法甲','欧冠','欧罗巴'); out={'schema_version':'selected-league-devig-eval-1.0','leagues':{},'methods':list(METHODS),'snapshots':list(SNAPS)}
 for league in leagues:
  rows=[json.loads(x) for x in (base/(league+'.jsonl')).read_text(encoding='utf-8').splitlines() if x.strip()]; out['leagues'][league]={'rows':len(rows),'results':{}}
  for s in SNAPS:
   out['leagues'][league]['results'][s]={}
   for m in METHODS:
    print(league,s,m,flush=True); out['leagues'][league]['results'][s][m]=run(rows,m,s)
  out['leagues'][league]['ranking_by_brier']={s:sorted([{'method':m,**v} for m,v in out['leagues'][league]['results'][s].items() if v['n']],key=lambda x:(x['brier'],x['logloss'])) for s in SNAPS}
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'status':'ok','output':a.output,'summary':{k:{s:v['ranking_by_brier'][s][:2] for s in SNAPS} for k,v in out['leagues'].items()}},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
