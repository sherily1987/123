# -*- coding: utf-8 -*-
"""api-sports 补赛果（v2 自动匹配）：英文队名精确匹配 → 结算入库。"""
import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta

KEY = os.environ['API_FOOTBALL_KEY']
DB = r'F:/HM足球比赛预测/project023_足球预测Web应用/02_脚本/data/app.db'

# 体彩场次 → (UTC时间, 主队英文, 客队英文) 硬映射（来自 48 场预测清单 + api-sports 已知命名）
TARGETS = [
    ('周六001', '2026-08-15 09:00', 'Kashima Antlers', 'Nagoya Grampus'),
    ('周六002', '2026-08-15 09:00', 'Blaublitz Akita', 'Toyama'),
    ('周六003', '2026-08-15 10:00', 'Urawa Reds', 'Sanfrecce Hiroshima'),
    ('周六004', '2026-08-15 10:00', 'Vissel Kobe', 'FC Tokyo'),
    ('周六005', '2026-08-15 10:30', 'FC Seoul', 'Daejeon Citizen'),
    ('周六006', '2026-08-15 10:30', 'Gwangju FC', 'Pohang Steelers'),
    ('周六007', '2026-08-15 11:00', 'Hertha Berlin', 'Heidenheim'),
    ('周六008', '2026-08-15 11:30', 'Bolton', 'Preston'),
    ('周六010', '2026-08-15 14:00', 'Norwich City', 'West Brom'),
    ('周六026', '2026-08-15 19:30', 'Fluminense', 'Palmeiras'),
    ('周六027', '2026-08-16 01:30', 'Real Salt Lake', 'Minnesota United'),
    ('周日001', '2026-08-16 10:00', 'Tokushima Vortis', 'Sagan Tosu'),
    ('周日003', '2026-08-16 10:30', 'Bucheon', 'Jeonbuk'),
    ('周日004', '2026-08-16 10:30', 'Incheon United', 'Gimcheon'),
    ('周日011', '2026-08-16 14:00', 'Arsenal', 'Man City'),
    ('周日017', '2026-08-16 15:00', 'Burnley', 'West Ham'),
]

def fetch(d):
    req = urllib.request.Request(f'https://v3.football.api-sports.io/fixtures?date={d}',
                                 headers={'x-apisports-key': KEY})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

by_time = {}
for d in ('2026-08-15', '2026-08-16', '2026-08-17'):
    for f in (fetch(d).get('response') or []):
        mm = re.match(r'(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})', f.get('fixture', {}).get('date', ''))
        if not mm:
            continue
        t = f'{mm.group(1)} {mm.group(2)}'
        teams = f.get('teams', {})
        home, away = (teams.get('home') or {}).get('name', ''), (teams.get('away') or {}).get('name', '')
        sc = (f.get('score') or {}).get('fulltime') or {}
        if sc.get('home') is None or sc.get('away') is None:
            continue
        by_time.setdefault(t, []).append({'home': home, 'away': away,
                                          'score': f"{sc['home']}-{sc['away']}"})

def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

matches = []
for num, utc, h_en, a_en in TARGETS:
    found = None
    for off in (timedelta(minutes=-5), timedelta(0), timedelta(minutes=5)):
        base = datetime.strptime(utc, '%Y-%m-%d %H:%M')
        for x in by_time.get((base + off).strftime('%Y-%m-%d %H:%M'), []):
            if norm(h_en) in norm(x['home']) and norm(a_en) in norm(x['away']):
                found = x
                break
        if found:
            break
    if found:
        print(f'{num}: {h_en} vs {a_en} → {found["score"]} ✅')
        matches.append((num, found['score']))
    else:
        print(f'{num}: {h_en} vs {a_en} → 未找到 ❌')

# 结算入库
c = sqlite3.connect(DB)
preds = {r[0]: r for r in c.execute("SELECT match_num, sales_day, direction, single_pick, score FROM predictions").fetchall()}
import db
db.init()
rows = []
for num, s90 in matches:
    p = preds.get(num)
    if not p:
        continue
    _, sales_day, direction, sp, score = p
    h, a = s90.split('-')
    ad = '主胜' if int(h) > int(a) else ('客胜' if int(h) < int(a) else '平局')
    hit_single = direction == ad
    sp_parts = (sp or '').replace(' ', '').split('/')
    rows.append({'sales_day': sales_day, 'match_num': num, 'match_id': None,
                 'score_90': s90, 'actual_direction': ad,
                 'hit_single': int(hit_single), 'hit_double': int(hit_single or ad in sp_parts),
                 'score_hit': int(score == s90)})
    print(f'  结算 {num}: 实际{s90} {ad} | 预测[{direction}|{sp}|比分{score}] 单选{"✅" if hit_single else "❌"}')
for day in ('2026-08-15', '2026-08-16', '2026-08-17'):
    db.upsert_backtests(day, [r for r in rows if r['sales_day'] == day])
print(f'\napi-sports 补结算 {len(rows)} 场')
