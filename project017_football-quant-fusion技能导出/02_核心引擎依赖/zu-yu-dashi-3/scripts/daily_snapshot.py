#!/usr/bin/env python3
"""采集体彩→生成输入→逐场预测并登记不可覆盖快照。"""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
# [中文功能] 生成某日全部场次的快照数据集
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--date',required=True);ap.add_argument('--snapshot',default='T-6h');ap.add_argument('--store',default='F:\HM足球比赛预测\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest');ap.add_argument('--work',default='F:\HM足球比赛预测\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/forward');a=ap.parse_args();here=Path(__file__).parent;day=Path(a.work)/a.date;day.mkdir(parents=True,exist_ok=True);raw=day/f'sporttery_{a.snapshot}.json';batch=day/f'inputs_{a.snapshot}.json'
 subprocess.run([sys.executable,str(here/'fetch_sporttery_full.py'),'--date',a.date,'--output',str(raw),'--emit-input',str(batch)],check=True,stdout=subprocess.DEVNULL);data=json.load(open(batch,encoding='utf-8'));records=[]
 for i,m in enumerate(data['matches']):
  inp=day/f"{m['sporttery_meta']['match_num']}_{a.snapshot}_input.json";out=day/f"{m['sporttery_meta']['match_num']}_{a.snapshot}_output.json";inp.write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8')
  r=subprocess.run([sys.executable,str(here/'record_prediction.py'),'--input',str(inp),'--output',str(out),'--predict','--snapshot',a.snapshot,'--store',a.store],capture_output=True,text=True)
  records.append({'match_num':m['sporttery_meta']['match_num'],'ok':r.returncode==0,'stdout':r.stdout,'stderr':r.stderr})
 summary={'date':a.date,'snapshot':a.snapshot,'count':len(records),'records':records};(day/f'register_{a.snapshot}.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
