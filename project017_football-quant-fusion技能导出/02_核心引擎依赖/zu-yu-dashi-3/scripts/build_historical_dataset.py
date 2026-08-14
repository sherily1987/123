#!/usr/bin/env python3
"""下载football-data近年CSV并转换为足预大师离线回测集。"""
import argparse,subprocess,sys,json
from pathlib import Path
SEASONS=['2425','2526']; LEAGUES=['E0','D1','SP1','I1','F1']
# [中文功能] 从football-data构建历史数据集
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='F:\HM足球比赛预测\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/historical');ap.add_argument('--seasons',nargs='*',default=SEASONS);ap.add_argument('--leagues',nargs='*',default=LEAGUES);a=ap.parse_args();root=Path(a.root);csvdir=root/'csv';csvdir.mkdir(parents=True,exist_ok=True);files=[];failed=[]
 for s in a.seasons:
  for lg in a.leagues:
   p=csvdir/f'{s}_{lg}.csv';u=f'https://www.football-data.co.uk/mmz4281/{s}/{lg}.csv'
   r=subprocess.run(['curl','-fL','--retry','2','--max-time','60','-o',str(p),u])
   if r.returncode==0 and p.stat().st_size>1000:files.append(str(p))
   else:failed.append(u);p.unlink(missing_ok=True)
 out=root/'history.json';conv=Path(__file__).with_name('fd_to_backtest.py');r=subprocess.run([sys.executable,str(conv),str(out),*files],capture_output=True,text=True)
 if r.returncode:sys.stderr.write(r.stderr);sys.exit(r.returncode)
 meta={'status':'ok','seasons':a.seasons,'leagues':a.leagues,'csv_count':len(files),'failed':failed,'dataset':str(out),'converter_output':r.stdout};(root/'build_meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
