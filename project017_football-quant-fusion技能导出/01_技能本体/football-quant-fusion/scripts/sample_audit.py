#!/usr/bin/env python3
"""Audit eligible denominators for registered fusion forecasts."""
import argparse,json
from pathlib import Path

# [中文功能] 按行读取registry.jsonl注册记录
def load(p):
 return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()] if Path(p).exists() else []

# [中文功能] 旧容器路径 /var/minis/... 自动映射到本机 shared 目录，避免注册路径失效
def resolve_path(p_str, root):
 p=Path(p_str)
 if p.exists():return p
 if p_str.startswith('/var/minis/shared/'):
  return root.parents[1]/p_str[len('/var/minis/shared/'):]
 return p

# [中文功能] 按快照统计样本数、去重与可结算市场
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--store',default='H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/backtest');ap.add_argument('--snapshot');ap.add_argument('--league');ap.add_argument('--output',required=True);a=ap.parse_args();root=Path(a.store)
 seen={}; total=0; dup=0; settled=0; eligible={k:0 for k in ['1x2','hhad','ou25','btts','score','hafu','clv']}; exclusions={}
 for e in load(root/'registry.jsonl'):
  p=resolve_path(e.get('path',''),root)
  if not p.exists():continue
  r=json.loads(p.read_text(encoding='utf-8'))
  if a.snapshot and r.get('snapshot_type')!=a.snapshot:continue
  if a.league and a.league not in str((r.get('match') or {}).get('competition','')):continue
  key=(r.get('match_id'),r.get('snapshot_type'))
  if key in seen:dup+=1;continue
  seen[key]=r;total+=1
  rp=root/'results'/(r.get('match_id')+'.json')
  if not rp.exists():exclusions['no_result']=exclusions.get('no_result',0)+1;continue
  rs=json.loads(rp.read_text(encoding='utf-8')); score=rs.get('score_90')
  if not isinstance(score,dict) or score.get('home') is None:exclusions['invalid_or_pending_result']=exclusions.get('invalid_or_pending_result',0)+1;continue
  settled+=1; o=r.get('output',{}); c=o.get('core_output',o); f=o.get('forecast') or c.get('forecast') or {}
  if len(c.get('final_1x2_pct') or c.get('final_1x2') or [])==3:eligible['1x2']+=1
  if (f.get('sporttery_hhad_3way') or c.get('sporttery_hhad_3way')):eligible['hhad']+=1
  if (f.get('ou_2_5') or c.get('ou_2_5')):eligible['ou25']+=1
  if (f.get('btts') or c.get('btts')):eligible['btts']+=1
  if (f.get('score_matrix') or c.get('score_matrix')):eligible['score']+=1
  if (f.get('hafu_model') or c.get('hafu_model')):eligible['hafu']+=1
  if (o.get('clv') or c.get('clv')):eligible['clv']+=1
 report={'schema_version':'sample-audit-1.0','snapshot':a.snapshot,'league':a.league,'registered_unique':total,'deduped_duplicates':dup,'settled':settled,'eligible_by_market':eligible,'exclusions':exclusions,'calibration_gate':{'min_recalibration':100,'threshold_review':200,'ready_for_recalibration':settled>=100,'ready_for_threshold_review':settled>=200}}
 Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
