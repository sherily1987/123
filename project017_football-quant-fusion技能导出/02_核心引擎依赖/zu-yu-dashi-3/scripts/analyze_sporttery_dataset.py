#!/usr/bin/env python3
import argparse,json,math
from collections import Counter,defaultdict
BIG5={'英超','西甲','意甲','德甲','法甲'}
NAT=('世界杯','亚洲杯','非洲杯','欧洲杯','美洲杯','世预赛','女亚洲杯')
CLUB_CUPS=('杯','欧冠','欧罗巴','欧协联','解放者杯','亚冠')
HB=[(-1,1.39,'≤1.39'),(1.4,1.59,'1.40–1.59'),(1.6,1.89,'1.60–1.89'),(1.9,2.19,'1.90–2.19'),(2.2,2.59,'2.20–2.59'),(2.6,3.19,'2.60–3.19'),(3.2,999,'≥3.20')]
DB=[(-1,3,'≤3.00'),(3.01,3.39,'3.01–3.39'),(3.4,3.79,'3.40–3.79'),(3.8,4.19,'3.80–4.19'),(4.2,4.99,'4.20–4.99'),(5,999,'≥5.00')]
# [中文功能] 计算列表均值（空列表返回None）
def mean(a):return sum(a)/len(a) if a else None
# [中文功能] 计算对数损失（单样本）
def ll(p,y):return -math.log(max(1e-15,p[y]))
# [中文功能] 计算Brier分数（单样本）
def brier(p,y):return sum((p[i]-(i==y))**2 for i in range(3))
# [中文功能] 按赔率区间分桶统计结果分布
def binstats(rows,bins,idx):
 out=[]
 for lo,hi,name in bins:
  z=[r for r in rows if lo<=r['odds_had'][idx]<=hi];c=Counter(r['result_1x2'] for r in z);n=len(z)
  out.append({'band':name,'n':n,'H':round(c['H']/n,4) if n else None,'D':round(c['D']/n,4) if n else None,'A':round(c['A']/n,4) if n else None,'implied':round(mean([r['p_had'][idx] for r in z]),4) if n else None})
 return out
# [中文功能] 泊松分布大球（超2.5球）概率
def poisson_over(lam):return 1-math.exp(-lam)*(1+lam+lam*lam/2)
# [中文功能] 分析体彩历史数据集的校准指标
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--json',required=True);ap.add_argument('--md',required=True);a=ap.parse_args()
 rows=[json.loads(x) for x in open(a.input,encoding='utf-8') if x.strip()]
 ys={'H':0,'D':1,'A':2}; bs=[brier(r['p_had'],ys[r['result_1x2']]) for r in rows];ls=[ll(r['p_had'],ys[r['result_1x2']]) for r in rows]
 # multiclass confidence ECE
 bins=[];ece=0
 for lo in [i/10 for i in range(10)]:
  z=[]
  for r in rows:
   conf=max(r['p_had']);pred=r['p_had'].index(conf);y=ys[r['result_1x2']]
   if lo <= conf < (lo + .1) or (lo == .9 and .9 <= conf <= 1):z.append((conf,pred==y))
  if z:
   cf=mean([x[0] for x in z]);ac=mean([x[1] for x in z]);ece+=len(z)/len(rows)*abs(cf-ac);bins.append({'range':f'{lo:.1f}-{lo+.1:.1f}','n':len(z),'confidence':round(cf,4),'accuracy':round(ac,4),'gap_pp':round((ac-cf)*100,2)})
 freq=Counter(r['result_1x2'] for r in rows);fp=[freq[x]/len(rows) for x in 'HDA'];fbs=[brier(fp,ys[r['result_1x2']]) for r in rows];fls=[ll(fp,ys[r['result_1x2']]) for r in rows]
 club=[r for r in rows if any(w in r['league'] for w in CLUB_CUPS) and r['league'] not in BIG5 and not any(w in r['league'] for w in NAT)]
 nat=[r for r in rows if any(w in r['league'] for w in NAT)]
 # TTG direct market and expectation-poisson tests
 tz=[r for r in rows if r.get('ttg')]
 actual=[r['over25'] for r in tz];direct=[sum(r['ttg']['probs'][3:]) for r in tz];pois=[poisson_over(r['ttg']['implied_goal_total']) for r in tz]
 # [中文功能] 计算二分类Brier/LogLoss等指标
 def binary(p,y):return {'brier':mean([(x-int(t))**2 for x,t in zip(p,y)]),'logloss':mean([-(int(t)*math.log(max(x,1e-15))+(1-int(t))*math.log(max(1-x,1e-15))) for x,t in zip(p,y)]),'mean_pred':mean(p),'actual':mean(y)}
 # total goal MAE and bias of TTG expectation
 gt=[r['ttg']['implied_goal_total'] for r in tz];act=[r['total_goals'] for r in tz]
 out={'sample':len(rows),'range':[rows[0]['date'],rows[-1]['date']], 'market_1x2':{'brier_sum':mean(bs),'brier_mean':mean(bs)/3,'logloss':mean(ls),'ece':ece,'bins':bins,'base_frequency':fp,'base_brier_sum':mean(fbs),'base_logloss':mean(fls)},'club_cups':{'n':len(club),'leagues':Counter(r['league'] for r in club),'home_odds_bands':binstats(club,HB,0),'draw_odds_bands':binstats(club,DB,1)},'national':{'n':len(nat),'leagues':Counter(r['league'] for r in nat)},'ttg':{'n':len(tz),'direct_over25':binary(direct,actual),'poisson_from_expectation':binary(pois,actual),'goal_total_mae':mean([abs(x-y) for x,y in zip(gt,act)]),'goal_total_bias':mean([x-y for x,y in zip(gt,act)]),'mean_implied_total':mean(gt),'actual_mean_total':mean(act)}}
 # round recursively for json
 # [中文功能] 把输出中的非JSON类型转为可序列化结构
 def clean(x):
  if isinstance(x,float):return round(x,6)
  if isinstance(x,Counter):return dict(x)
  if isinstance(x,dict):return {k:clean(v) for k,v in x.items()}
  if isinstance(x,list):return [clean(v) for v in x]
  return x
 out=clean(out);json.dump(out,open(a.json,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
 m=out['market_1x2'];t=out['ttg'];lines=[f'# 体彩历史数据审计\n\n样本：{out["sample"]}场（{out["range"][0]} 至 {out["range"][1]}）',f'\n## 1. 市场基线\n\n- Brier Sum：{m["brier_sum"]:.4f}（Mean {m["brier_mean"]:.4f}）\n- LogLoss：{m["logloss"]:.4f}\n- ECE：{m["ece"]:.4f}\n- 基础频率 Brier Sum：{m["base_brier_sum"]:.4f}\n- 基础频率 LogLoss：{m["base_logloss"]:.4f}',f'\n## 2. 俱乐部杯赛赔率参照\n\n有效杯赛：{out["club_cups"]["n"]}场。国家队赛事另列：{out["national"]["n"]}场。\n\n### 主胜赔率分档\n\n|档位|n|主胜|平|客胜|平均去水隐含|\n|---|---:|---:|---:|---:|---:|']
 for z in out['club_cups']['home_odds_bands']:lines.append(f'|{z["band"]}|{z["n"]}|{z["H"]}|{z["D"]}|{z["A"]}|{z["implied"]}|')
 lines+=['\n### 平局赔率分档\n\n|档位|n|主胜|平|客胜|平均去水平概率|\n|---|---:|---:|---:|---:|---:|']
 for z in out['club_cups']['draw_odds_bands']:lines.append(f'|{z["band"]}|{z["n"]}|{z["H"]}|{z["D"]}|{z["A"]}|{z["implied"]}|')
 lines.append(f'\n## 3. TTG验证\n\n- 样本：{t["n"]}场\n- TTG直接去水大2.5：Brier {t["direct_over25"]["brier"]:.4f}，LogLoss {t["direct_over25"]["logloss"]:.4f}，预测均值 {t["direct_over25"]["mean_pred"]:.3f}，实际 {t["direct_over25"]["actual"]:.3f}\n- TTG期望总进球→Poisson：Brier {t["poisson_from_expectation"]["brier"]:.4f}，LogLoss {t["poisson_from_expectation"]["logloss"]:.4f}\n- 隐含总进球均值 {t["mean_implied_total"]:.3f}，实际 {t["actual_mean_total"]:.3f}，偏差 {t["goal_total_bias"]:.3f}，MAE {t["goal_total_mae"]:.3f}\n\n> 这是回顾性校准审计，不是投注建议。')
 open(a.md,'w',encoding='utf-8').write('\n'.join(lines));print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
