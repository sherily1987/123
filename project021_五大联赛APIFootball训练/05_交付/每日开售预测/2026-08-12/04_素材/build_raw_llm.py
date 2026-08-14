# -*- coding: utf-8 -*-
"""构造 football-llm-predictor 的 raw_2026-08-12.json：7 场已开售场次，采集器 schema。"""
import json, io, glob, os
from datetime import datetime

SRC = 'F:/HM足球比赛预测/project022_20260812开售预测/04_素材'
OUT = 'C:/Users/Administrator/football-llm-predictor/data/raw_2026-08-12.json'

def load(p):
    return json.loads(io.open(p, encoding='utf-8-sig').read())

sale = load(SRC + '/on_sale_20260812.json')
info = {}
for m in sale:
    if m.get('match_id') and m.get('date') and m.get('time'):
        info[str(m['match_id'])] = {
            'match_num': m['num'],
            'kickoff_local': f"{m['date']} {m['time']}",
            'kickoff_iso': f"{m['date']}T{m['time']}:00+08:00",
        }

# 按销售列表顺序收集单场采集文件（保证证据序号 = 列表序）
matches = []
for m in sale:
    mid = str(m.get('match_id'))
    if mid not in info:
        continue
    path = os.path.join(SRC, f'm_{mid}.json')
    if not os.path.exists(path):
        print(f'!! 缺单场文件 {path}'); continue
    d = load(path)
    for mm in d.get('matches', []):
        if str(mm.get('match_id')) != mid:
            continue
        if not (mm.get('model_odds') and mm.get('odds_eligible')):
            print(f"!! {mid} {mm.get('home')}vs{mm.get('away')} 无HAD/未开售，跳过")
            continue
        rec = dict(mm)
        rec['match_num'] = info[mid]['match_num']
        rec['business_date'] = '2026-08-12'
        rec['kickoff_local'] = info[mid]['kickoff_local']
        rec['kickoff_iso'] = info[mid]['kickoff_iso']
        matches.append(rec)
        print(f"{rec['match_num']} {rec['league']} {rec['home']} vs {rec['away']} | {rec['kickoff_iso']} | had={rec['model_odds']}")

raw = {
    'schema_version': '3.0',
    'collector_version': 'mobile-3.5.0',
    'source': '中国体彩网移动端官方链路',
    'source_url': None,
    'fetched_at': datetime.now().astimezone().isoformat(),
    'count': len(matches),
    'matches': matches,
    'notes': ['2026-08-12 开售日采集；含已开售未开球 7 场（HAD 可用）'],
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with io.open(OUT, 'w', encoding='utf-8') as f:
    json.dump(raw, f, ensure_ascii=False, indent=2)
print(f'\n写入 {OUT}，共 {len(matches)} 场')
