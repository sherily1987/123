#!/usr/bin/env python3
"""足预大师3.3回测：支持登记库或离线历史JSON。"""
import argparse,json,math
from pathlib import Path
from backtest_lib import *
# [中文功能] 小数转百分数（None保持None）
def pct(x):return None if x is None else round(x*100,2)
# [中文功能] 计算均值（空序列返回None）
def mean(xs):return None if not xs else sum(xs)/len(xs)
# [中文功能] 按概率分桶统计并计算ECE
def bins(records,key='pred',n=10):
 out=[];ece=0
 for b in range(n):
  lo,hi=b/n,(b+1)/n;z=[r for r in records if lo<=r[key]<(hi if b<n-1 else hi+1e-12)]
  if not z:continue
  ap=mean([r[key] for r in z]);ar=mean([r['actual'] for r in z]);e=abs(ap-ar);ece+=len(z)/max(1,len(records))*e;out.append({'bin':f'{lo:.1f}-{hi:.1f}','n':len(z),'avg_prob':round(ap,4),'actual_rate':round(ar,4),'abs_error':round(e,4)})
 return out,round(ece,5)
# [中文功能] 把一条登记记录转成回测评分行
def score_row(pr,rs):
 o=pr['output']; probs=o.get('final_1x2') or [x/100 for x in (o.get('final_1x2_pct') or o.get('adjusted_1x2_pct'))];h=rs['score_90']['home'];a=rs['score_90']['away'];idx=actual_1x2(h,a);actual=f'{h}-{a}';tops=[x['score'] for x in o.get('top_scores',[])];sm=o.get('score_matrix') or {};sp=sm.get(actual)
 row={'prediction_id':pr.get('prediction_id'),'match_id':pr.get('match_id'),'actual_score':actual,'actual_idx':idx,'probs':probs,'pick_correct':probs.index(max(probs))==idx,'brier_sum':brier(probs,idx),'log_loss':logloss(probs,idx),'top1':actual in tops[:1],'top3':actual in tops[:3],'top5':actual in tops[:5],'score_log_loss':None if sp is None else -math.log(max(1e-12,sp)),'mode':o.get('mode'),'version':o.get('engine_version')}
 market=o.get('market_prob_pct');
 if market:row['market_brier_sum']=brier([x/100 for x in market],idx);row['market_log_loss']=logloss([x/100 for x in market],idx)
 ou=o.get('ou_2_5');bt=o.get('btts');adv=o.get('advancement')
 if ou:row['ou25_brier']=binary_brier(ou['over_pct']/100,1 if h+a>2.5 else 0)
 if bt:row['btts_brier']=binary_brier(bt['yes_pct']/100,1 if h>0 and a>0 else 0)
 if adv and rs.get('advanced'):row['advance_brier']=binary_brier(adv['home_advance_pct']/100,1 if rs['advanced']=='home' else 0)
 return row
# [中文功能] 从回测库加载注册记录与赛果
def load_store(root,snapshot=None):
 # 同一 (match_id, snapshot_type) 只能贡献一个样本；重复登记保留 created_at 最新的一条。
 # 规范依据 SKILL.md：「同一比赛多快照不能当成多个独立样本」。
 root=Path(root);keep={};dropped=[]
 # [中文功能] 旧容器路径 /var/minis/... 自动映射到本机 shared 目录，避免注册路径失效
 def _resolve(p_str):
  p=Path(p_str)
  if p.exists():return p
  if p_str.startswith('/var/minis/shared/'):
   return root.parents[1]/p_str[len('/var/minis/shared/'):]
  return p
 for e in load_jsonl(root/'registry.jsonl'):
  p=_resolve(e['path']);rp=root/'results'/(e['match_id']+'.json')
  if not p.exists() or not rp.exists():continue
  pr=json.load(open(p,encoding='utf-8'));rs=json.load(open(rp,encoding='utf-8'))
  if snapshot and pr.get('snapshot_type')!=snapshot:continue
  k=(pr.get('match_id'),pr.get('snapshot_type'));cur=keep.get(k)
  if cur is None or pr.get('created_at','')>cur[0].get('created_at',''):
   if cur is not None:dropped.append({'match_id':k[0],'snapshot_type':k[1],'superseded_prediction_id':cur[0].get('prediction_id')})
   keep[k]=(pr,rs)
  else:
   dropped.append({'match_id':k[0],'snapshot_type':k[1],'superseded_prediction_id':pr.get('prediction_id')})
 return [score_row(pr,rs) for pr,rs in keep.values()],dropped
# [中文功能] 加载离线历史JSON并即时预测
def load_offline(path):
 raw=json.load(open(path,encoding='utf-8-sig'));items=raw.get('matches',raw) if isinstance(raw,dict) else raw;rows=[]
 for i,x in enumerate(items):
  inp=dict(x);act=inp.pop('actual');from predict import predict;o=predict(inp);pr={'prediction_id':f'offline-{i}','match_id':f'offline-{i}','output':o};rs={'score_90':{'home':int(act[0]),'away':int(act[1])},'advanced':x.get('actual_advanced')};rows.append(score_row(pr,rs))
 return rows
# [中文功能] 回测主入口（在线登记库或离线文件）
def main():
 ap=argparse.ArgumentParser();ap.add_argument('input',nargs='?',help='离线历史JSON');ap.add_argument('--store',default='H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest');ap.add_argument('--snapshot');ap.add_argument('--output');a=ap.parse_args()
 if a.input:rows,dropped=load_offline(a.input),[]
 else:rows,dropped=load_store(a.store,a.snapshot)
 # [中文功能] 取某字段所有有效值的均值
 def av(k):return mean([r[k] for r in rows if r.get(k) is not None])
 cal=[]
 for r in rows:
  for i,p in enumerate(r['probs']):cal.append({'pred':p,'actual':1 if r['actual_idx']==i else 0})
 cb,ece=bins(cal);n=len(rows);freq=[mean([1 if r['actual_idx']==i else 0 for r in rows]) for i in range(3)] if rows else [None]*3
 base=None if not rows else mean([brier(freq,r['actual_idx']) for r in rows])
 met={'schema_version':'2.0','generated_at':now(),'sample_size':n,'deduped_duplicates':len(dropped),'deduped_detail':dropped,'warning':'样本<200时结论不可靠。' if n<200 else None,'one_x_two':{'accuracy_pct':pct(av('pick_correct')),'brier_sum':av('brier_sum'),'brier_mean':None if av('brier_sum') is None else av('brier_sum')/3,'log_loss':av('log_loss'),'ece':ece,'calibration_bins':cb},'baselines':{'frequency_probs':freq,'frequency_brier_sum':base,'market_brier_sum':av('market_brier_sum'),'market_log_loss':av('market_log_loss')},'score':{'top1_accuracy_pct':pct(av('top1')),'top3_accuracy_pct':pct(av('top3')),'top5_accuracy_pct':pct(av('top5')),'log_loss':av('score_log_loss')},'ou_2_5':{'brier':av('ou25_brier')},'btts':{'brier':av('btts_brier')},'advancement':{'brier':av('advance_brier')},'records':rows}
 out=Path(a.output) if a.output else Path(a.store)/'metrics'/'latest.json';atomic_json(out,met);print(json.dumps(met,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
