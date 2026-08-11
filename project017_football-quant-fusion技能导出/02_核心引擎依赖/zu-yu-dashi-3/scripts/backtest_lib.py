#!/usr/bin/env python3
import hashlib,json,math,re
from datetime import datetime,timezone
from pathlib import Path

# [中文功能] 返回当前UTC时间ISO字符串
def now(): return datetime.now(timezone.utc).isoformat()
# [中文功能] 生成排序键的规范JSON字符串
def canonical(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
# [中文功能] 计算内容SHA256哈希
def sha(x): return hashlib.sha256((x if isinstance(x,bytes) else canonical(x).encode())).hexdigest()
# [中文功能] 把文本转成可读ASCII短标识（附稳定哈希）
def slug(s):
 s=str(s or '')
 base=re.sub(r'[^a-z0-9]+','-',s.lower()).strip('-')[:48]
 # 中文/非拉丁文本会被旧实现清空或碰撞；保留可读ASCII并附稳定短哈希。
 has_non_ascii=any(ord(c)>127 for c in s)
 digest=hashlib.sha256(s.encode('utf-8')).hexdigest()[:10]
 if not base:return 'u-'+digest
 return f'{base}-{digest}' if has_non_ascii else base
# [中文功能] 原子写JSON文件
def atomic_json(path,data):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
# [中文功能] 追加一行JSON到jsonl文件
def append_jsonl(path,data):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('a',encoding='utf-8') as f:f.write(canonical(data)+'\n')
# [中文功能] 读取jsonl文件为对象列表
def load_jsonl(path):
 p=Path(path)
 if not p.exists():return []
 return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
# [中文功能] 计算单样本Brier分数
def brier(probs,idx): return sum((p-(1 if i==idx else 0))**2 for i,p in enumerate(probs))
# [中文功能] 计算单样本对数损失
def logloss(probs,idx): return -math.log(max(1e-12,min(1-1e-12,probs[idx])))
# [中文功能] 计算二分类Brier分数
def binary_brier(p,y): return (p-y)**2
# [中文功能] 由主客比分得到胜平负实际结果索引
def actual_1x2(h,a): return 0 if h>a else (1 if h==a else 2)
# [中文功能] 按亚洲盘线结算主队输赢/走盘状态
def ah_state(h,a,line):
 q=round(float(line)*4)/4
 # [中文功能] 符号函数：正/负/零判胜负
 def r(x):
  z=h-a+x
  return 1 if z>1e-9 else (-1 if z< -1e-9 else 0)
 if abs(q*2-round(q*2))<1e-8:return {1:'full_win',0:'push',-1:'full_loss'}[r(q)]
 import math
 rs=sorted([r(math.floor(q*2)/2),r(math.ceil(q*2)/2)])
 return {(-1,-1):'full_loss',(-1,0):'half_loss',(0,0):'push',(0,1):'half_win',(1,1):'full_win'}[tuple(rs)]
