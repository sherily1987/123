# -*- coding: utf-8 -*-
"""构造 2026-08-12 销售日 input.json（7 场已开售，含全盘口）"""
import json, io, glob, os
from datetime import datetime, timezone

BASE = 'F:/HM足球比赛预测/project022_20260812开售预测/04_素材'
OUT = BASE + '/input.json'

def load(p):
    return json.loads(io.open(p, encoding='utf-8-sig').read())

# 编号 -> kickoff（北京时间，来源 on_sale_20260812.json）
sale = load(BASE + '/on_sale_20260812.json')
kickoff_map = {}
num_map = {}
for m in sale:
    num = m['num']  # 周三001
    date = m['date']; tm = m['time']
    if date and tm and m['match_id']:
        # 2026-08-13 03:00 -> ISO with +08:00
        dt = datetime.strptime(f'{date} {tm}', '%Y-%m-%d %H:%M')
        kickoff_map[str(m['match_id'])] = f'{date}T{tm}:00+08:00'
        num_map[str(m['match_id'])] = num

now_iso = datetime.now(timezone.utc).isoformat()
matches = []
for p in sorted(glob.glob(BASE + '/m_20408*.json')):
    d = load(p)
    for m in d.get('matches', []):
        if not (m.get('model_odds') and m.get('odds_eligible')):
            continue
        mid = str(m['match_id'])
        kick = kickoff_map.get(mid)
        if kick is None:
            print(f'!! {mid} 无kickoff，跳过'); continue
        # 过滤已开球
        kt = datetime.fromisoformat(kick)
        if kt < datetime.now().astimezone():
            print(f'!! {mid} {m["home"]}vs{m["away"]} 已开球({kick})，跳过'); continue
        # field_meta：各池 observed_at 用采集的 *_updated_at
        fm = {}
        for pool, key in [('odds', 'had_updated_at'), ('hhad', 'hhad_updated_at'),
                          ('ttg', 'ttg_updated_at'), ('hafu', 'hafu_updated_at'),
                          ('crs', 'crs_updated_at')]:
            upd = m.get(key)
            fm[pool] = {
                'reliability': 100, 'freshness': 100,
                'source': '中国体彩网移动端官方固定奖金接口',
                'collected_at': now_iso,
                'source_updated_at': upd,
                'prediction_as_of': now_iso,
                'observed_at': upd,
            }
        ttg = m.get('ttg') or {}
        hafu = m.get('hafu') or {}
        rec = {
            'home': m['home'], 'away': m['away'],
            'competition': m.get('league'), 'stage': m.get('league'),
            'kickoff': kick,
            'mode': 'market_only',
            'odds': m['model_odds'],
            'context_confirmed': True,
            'prediction_as_of': now_iso,
            'collected_at': now_iso,
            'field_meta': fm,
            'assumptions': ['已提供体彩HHAD三态；未自动映射为亚洲盘ah_line'],
            'sporttery_meta': {
                'match_id': m['match_id'],
                'match_num': num_map.get(mid, ''),
                'home_team_id': (m.get('team_ids') or {}).get('home_team_id'),
                'away_team_id': (m.get('team_ids') or {}).get('away_team_id'),
                'league_id': (m.get('team_ids') or {}).get('league_id'),
                'home_full': (m.get('team_ids') or {}).get('home_full'),
                'away_full': (m.get('team_ids') or {}).get('away_full'),
            },
            'hhad': m.get('model_hhad'),
            'ttg': {'odds': [ttg.get(str(i)) for i in range(7)] + [ttg.get('7+')]},
            'hafu': {'odds': [hafu.get(k) for k in ['hh','hd','ha','dh','dd','da','ah','ad','aa']]},
            'crs': m.get('crs'),
        }
        matches.append(rec)
        print(f"{mid} {rec['competition']} {rec['home']} vs {rec['away']} kickoff={kick} had={rec['odds']}")

with io.open(OUT, 'w', encoding='utf-8') as f:
    json.dump({'matches': matches}, f, ensure_ascii=False, indent=2)
print(f'\n写入 {OUT}，共 {len(matches)} 场')
