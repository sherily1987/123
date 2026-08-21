# -*- coding: utf-8 -*-
"""补全回测（v3 干净版）：体彩赛果（match_num 精确）+ apifootball（联赛+时间约束）合并结算。

apifootball 只覆盖欧洲联赛；非欧洲联赛（日职/韩职/沙职/美职/英冠等）绝不按时间错配，
留在 missing 里由 api-sports 补（见补全脚本说明）。
"""
import json
import os
import re
import sqlite3
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, r'F:/HM足球比赛预测/project023_足球预测Web应用/02_脚本')
DB_PATH = r'F:/HM足球比赛预测/project023_足球预测Web应用/02_脚本/data/app.db'

LEAGUE_MAP = {
    '荷甲': 'eredivisie', '瑞超': 'allsvenskan', '挪超': 'eliteserien',
    '葡超': 'primeira liga', '西甲': 'la liga', '芬超': 'veikkausliiga',
    '德乙': '2. bundesliga', '英冠': 'championship',
}
AF_UNCOVERED = {'日职', '日乙', '韩职', '沙职', '美职', '英社区盾', '巴甲'}

# 1) apifootball 赛果（按联赛+UTC时间索引）
key = os.environ['APIFOOTBALL_COM_KEY']
data = json.loads(urllib.request.urlopen(urllib.request.Request(
    'https://apiv2.apifootball.com/?action=get_events&from=2026-08-15&to=2026-08-17&timezone=UTC&APIkey=' + key,
    headers={'User-Agent': 'Mozilla/5.0'}), timeout=60).read())
af = {}
for m in data:
    if m.get('match_status') != 'Finished':
        continue
    ln = (m.get('league_name') or '').lower()
    league_norm = next((k for k, v in LEAGUE_MAP.items() if v in ln), None)
    if not league_norm:
        continue
    sc = m.get('match_hometeam_ft_score') or m.get('match_hometeam_score')
    sca = m.get('match_awayteam_ft_score') or m.get('match_awayteam_score')
    if sc is None or sca is None:
        continue
    af.setdefault(league_norm, {})[f"{m.get('match_date')} {m.get('match_time')}"] = f"{sc}-{sca}"

# 2) 体彩赛果（match_num 精确）
tix = {}
for d in ('2026-08-15', '2026-08-16', '2026-08-17'):
    r = json.load(open(f'C:/Users/Administrator/football-llm-predictor/data/results_{d}.json', encoding='utf-8'))
    for mm in r.get('results', []):
        if mm.get('finished') and mm.get('score_90'):
            tix[mm['match_num']] = mm['score_90']

# 3) 读预测
c = sqlite3.connect(DB_PATH)
preds = c.execute("""
    SELECT p.sales_day, p.match_num, p.direction, p.single_pick, p.score, m.kickoff, m.league
    FROM predictions p LEFT JOIN matches m ON p.sales_day=m.sales_day AND p.match_num=m.match_num
""").fetchall()


def kick_utc(kick):
    if not kick:
        return None
    mm = re.search(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', str(kick))
    if not mm:
        return None
    dt = datetime.strptime(mm.group(1) + ' ' + mm.group(2), '%Y-%m-%d %H:%M')
    return (dt - timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')


def actual_dir(score):
    mm = re.search(r'(\d+)-(\d+)', str(score))
    if not mm:
        return None
    h, a = int(mm.group(1)), int(mm.group(2))
    return '主胜' if h > a else ('客胜' if h < a else '平局')


rows, missing = [], []
for sales_day, match_num, direction, single_pick, score, kickoff, league in preds:
    s90 = None
    src = None
    if match_num in tix:
        s90, src = tix[match_num], 'tix'
    elif league not in AF_UNCOVERED and league in af:
        k = kick_utc(kickoff)
        if k and k in af[league]:
            s90, src = af[league][k], 'apifootball'
    if not s90:
        missing.append((match_num, kickoff, league))
        continue
    ad = actual_dir(s90)
    hit_single = (direction == ad)
    sp_parts = (single_pick or '').replace(' ', '').split('/')
    rows.append({'sales_day': sales_day, 'match_num': match_num, 'match_id': None,
                 'score_90': s90, 'actual_direction': ad,
                 'hit_single': int(hit_single), 'hit_double': int(hit_single or ad in sp_parts),
                 'score_hit': int(score == s90), '_src': src})

import db
db.init()
for day in ('2026-08-15', '2026-08-17'):
    db.upsert_backtests(day, [{k: v for k, v in r.items() if not k.startswith('_')}
                              for r in rows if r['sales_day'] == day])

n = len(rows)
s = sum(r['hit_single'] for r in rows)
d = sum(r['hit_double'] for r in rows)
sc = sum(r['score_hit'] for r in rows)
print(f'\n=== 合并结算 {n} 场 ===')
print(f'方向单选 {s}/{n} = {s/n:.0%}  含双选 {d}/{n} = {d/n:.0%}  比分 {sc}/{n} = {sc/n:.0%}')
print(f'来源: 体彩 {sum(1 for r in rows if r["_src"]=="tix")} 场, apifootball {sum(1 for r in rows if r["_src"]=="apifootball")} 场')
print(f'未匹配 {len(missing)} 场:', sorted(missing, key=lambda x: x[2]))

by = defaultdict(list)
for r in rows:
    by[r['sales_day']].append(r)
for day, rs in sorted(by.items()):
    nn, ss, dd, cc = len(rs), sum(r['hit_single'] for r in rs), sum(r['hit_double'] for r in rs), sum(r['score_hit'] for r in rs)
    print(f'{day}: {nn} 场 → 单选 {ss}/{nn} ({ss/nn:.0%})  双选 {dd}/{nn}  比分 {cc}/{nn}')
