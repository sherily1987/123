#!/usr/bin/env python3
"""Validate fusion combo references without settling them."""
import argparse,json
from pathlib import Path
from recommendation_policy import validate_combo_ids
from runtime_paths import backtest_store

# [中文功能] 按行读取registry.jsonl注册记录
def load(p):
 return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()] if Path(p).exists() else []

# [中文功能] 校验组合腿ID的有效性并输出结果
def main():
 # 2026-08-16：--store 默认值原指向外部套件（物理拷贝、比仓库内旧），改走仓库内唯一事实源
 ap=argparse.ArgumentParser();ap.add_argument('--store',default=str(backtest_store()));ap.add_argument('--legs',required=True,help='JSON file: {combos:[{combo_id,legs:[]},...]}');ap.add_argument('--output',required=True);a=ap.parse_args();root=Path(a.store);data=json.loads(Path(a.legs).read_text(encoding='utf-8')); pred=[];covers=[]
 for e in load(root/'registry.jsonl'):
  p=Path(e.get('path',''))
  if not p.exists():continue
  r=json.loads(p.read_text(encoding='utf-8')); pred.append(r.get('prediction_id'))
 report=[]
 for combo in data.get('combos',[]):
  v=validate_combo_ids(combo,pred,covers);report.append({**combo,**v,'status':'valid' if v['valid'] else 'invalid_combo_reference'})
 out={'schema_version':'fusion-combo-validation-1.0','registered_prediction_ids':len([x for x in pred if x]),'combos':report};Path(a.output).parent.mkdir(parents=True,exist_ok=True);Path(a.output).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
