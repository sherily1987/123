#!/usr/bin/env python3
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
from backtest_lib import *

# [中文功能] 解析ISO时间字符串
def parse_dt(s): return datetime.fromisoformat(s.replace('Z','+00:00'))
# [中文功能] 把核心预测登记进回测库
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',required=True);ap.add_argument('--output',required=True);ap.add_argument('--store',default='H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest');ap.add_argument('--snapshot',default='unspecified');ap.add_argument('--allow-past',action='store_true');ap.add_argument('--predict',action='store_true',help='先跑predict.py生成--output再登记');ap.add_argument('--replace-snapshot',action='store_true',help='允许同一(match_id,snapshot)重复登记；重复条目在回测中只算一个样本');a=ap.parse_args()
 inp=json.load(open(a.input,encoding='utf-8'))
 if a.predict:
  from predict import predict as run
  res=run(inp);Path(a.output).parent.mkdir(parents=True,exist_ok=True);atomic_json(a.output,res)
 out=json.load(open(a.output,encoding='utf-8'))
 if 'matches' in inp or out.get('status')=='batch':sys.exit('record one match per invocation')
 ko=inp.get('kickoff');
 if not ko:sys.exit('kickoff required')
 kd=parse_dt(ko)
 if kd.tzinfo is None:sys.exit('kickoff timezone required')
 if kd.astimezone(timezone.utc)<=datetime.now(timezone.utc) and not a.allow_past:sys.exit('kickoff already passed; refuse retrospective prediction')
 comp=slug(inp.get('competition',inp.get('stage','match')));season=slug(inp.get('season','na'));ds=kd.strftime('%Y%m%dT%H%MZ')
 mid=f"{comp}_{season}_{ds}_{slug(inp['home'])}__{slug(inp['away'])}"
 version=str(out.get('engine_version','unknown'));vslug=slug(version)
 created=datetime.now(timezone.utc);pid=f"{mid}__v{vslug}__{created.strftime('%Y%m%dT%H%M%SZ')}__{slug(a.snapshot)}"
 # 同一比赛同一快照只允许一条：否则回测会把它当成两个独立样本重复计权。
 if not a.replace_snapshot:
  snap=slug(a.snapshot)
  for e in load_jsonl(Path(a.store)/'registry.jsonl'):
   if e.get('match_id')!=mid:continue
   ep=Path(e['path'])
   if not ep.exists():continue
   if json.load(open(ep,encoding='utf-8')).get('snapshot_type')==a.snapshot:
    print(json.dumps({'status':'skipped_duplicate_snapshot','match_id':mid,'snapshot_type':a.snapshot,'existing_prediction_id':e.get('prediction_id'),'note':'同一比赛同一快照已登记；如确需覆盖用 --replace-snapshot'},ensure_ascii=False));sys.exit(0)
 engine=Path(__file__).with_name('predict.py').read_bytes();rec={'schema_version':'1.1','prediction_id':pid,'match_id':mid,'created_at':created.isoformat(),'snapshot_type':a.snapshot,'model':{'name':'zu-yu-dashi-3','version':version,'engine_sha256':sha(engine)},'match':{'competition':inp.get('competition'),'season':inp.get('season'),'stage':inp.get('stage'),'kickoff':ko,'home':inp['home'],'away':inp['away']},'input':inp,'output':out,'hashes':{'input_sha256':sha(inp),'output_sha256':sha(out)}}
 p=Path(a.store)/'predictions'/created.strftime('%Y/%m')/(pid+'.json')
 if p.exists():sys.exit('prediction exists; no overwrite')
 atomic_json(p,rec);reg=Path(a.store)/'registry.jsonl';prev=load_jsonl(reg);prevhash=prev[-1].get('entry_hash','') if prev else '';entry={'prediction_id':pid,'match_id':mid,'path':str(p),'record_hash':sha(rec),'previous_hash':prevhash,'created_at':rec['created_at']};entry['entry_hash']=sha(prevhash+entry['record_hash']);append_jsonl(reg,entry)
 print(json.dumps({'status':'recorded','prediction_id':pid,'match_id':mid,'path':str(p)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
