#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体彩赔率移动追踪库。

每次采集把各盘口快照按 (match_id, pool, update_time) 去重后追加到 JSONL，
长期累积即得开盘→终盘的赔率移动序列，用于 CLV / 盘口异动分析。

用法：
  python3 odds_movement.py add --source raw_sporttery.json
  python3 odds_movement.py show --match-id 2040673
  python3 odds_movement.py drift --date 2026-08-01
"""
import argparse, json
from pathlib import Path

DEFAULT = 'H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/odds/movement.jsonl'
POOLS = [('hadList', 'HAD'), ('hhadList', 'HHAD'), ('ttgList', 'TTG'),
         ('crsList', 'CRS'), ('hafuList', 'HAFU')]


# [中文功能] 按行读取赔率移动库jsonl
def read(p):
    p = Path(p)
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()] if p.exists() else []


# [中文功能] 比例去水得到公平概率
def devig(o):
    q = [1/float(x) for x in o]; s = sum(q)
    return [x/s for x in q], s-1


# [中文功能] 兼容两种采集器结构的盘口历史提取
def _history(m):
    """Support both collector raw and kleague history payload shapes."""
    if isinstance(m.get('odds_history'), dict) and m.get('odds_history'):
        return m.get('odds_history')
    hist = (m.get('historical_odds') or {}).get('odds_history')
    return hist if isinstance(hist, dict) else {}


# [中文功能] 从不同格式采集行提取比赛标识字段
def _match_fields(m):
    mid = m.get('match_id') if m.get('match_id') not in (None, '') else m.get('matchId')
    num = m.get('match_num') or m.get('matchNumStr') or m.get('matchNum')
    league = m.get('league') or m.get('leagueAbbName') or m.get('leagueAllName')
    home = m.get('home') or m.get('homeTeamAbbName') or m.get('homeTeamAllName')
    away = m.get('away') or m.get('awayTeamAbbName') or m.get('awayTeamAllName')
    kickoff = m.get('kickoff_iso') or m.get('kickoff')
    if not kickoff and m.get('matchDate'):
        mt = str(m.get('matchTime') or '00:00')[:5]
        kickoff = f"{m.get('matchDate')}T{mt}:00+08:00"
    business = m.get('business_date') or m.get('businessDate') or m.get('matchDate')
    tid = m.get('team_ids') or {}
    return {
        'official_source': '中国体彩网移动端官方固定奖金接口',
        'match_id': mid,
        'match_num': num,
        'business_date': business,
        'league': league,
        'home': home,
        'away': away,
        'kickoff': kickoff,
        'home_team_id': tid.get('home_team_id') or m.get('homeTeamId'),
        'away_team_id': tid.get('away_team_id') or m.get('awayTeamId'),
    }


# [中文功能] 从采集原始JSON抽取全部盘口快照
def collect(src):
    """从采集器原始 JSON / 韩职历史 JSON 抽出所有盘口快照。"""
    out = []
    for m in json.load(open(src, encoding='utf-8')).get('matches', []):
        oh = _history(m)
        base = _match_fields(m)
        for key, pool in POOLS:
            for row in oh.get(key) or []:
                ts = ' '.join(x for x in [row.get('updateDate'), row.get('updateTime')] if x)
                if not ts:
                    continue
                rec = dict(base)
                rec.update({
                    'pool': pool,
                    'observed_at': ts,
                    'source': '中国体彩网移动端官方固定奖金接口',
                    'updated_at': ts,
                    'odds': {k: v for k, v in row.items()
                             if k not in ('updateDate', 'updateTime') and v not in (None, '')},
                })
                out.append(rec)
    return out


# [中文功能] 赔率移动库子命令：add/show/drift
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('add');   a.add_argument('--source', required=True); a.add_argument('--store', default=DEFAULT)
    s = sub.add_parser('show');  s.add_argument('--match-id', type=int, required=True); s.add_argument('--store', default=DEFAULT)
    r = sub.add_parser('drift'); r.add_argument('--date'); r.add_argument('--store', default=DEFAULT)
    x = ap.parse_args()
    store = Path(x.store)

    if x.cmd == 'add':
        old = read(store)
        seen = {(z['match_id'], z['pool'], z['updated_at']) for z in old}
        new = [z for z in collect(x.source) if (z['match_id'], z['pool'], z['updated_at']) not in seen]
        store.parent.mkdir(parents=True, exist_ok=True)
        with store.open('a', encoding='utf-8') as f:
            for z in new: f.write(json.dumps(z, ensure_ascii=False, sort_keys=True)+'\n')
        print(json.dumps({'added': len(new), 'skipped_dup': len(collect(x.source))-len(new),
                          'total': len(old)+len(new), 'store': str(store)}, ensure_ascii=False))

    elif x.cmd == 'show':
        rows = [z for z in read(store) if z['match_id'] == x.match_id]
        rows.sort(key=lambda z: (z['pool'], z['updated_at']))
        for z in rows:
            print(f"{z['updated_at']}  {z['pool']:5s} {z['odds']}")
        print(json.dumps({'match_id': x.match_id, 'snapshots': len(rows)}, ensure_ascii=False))

    else:  # drift：只看 HAD，统计开盘→最新的变化
        rows = [z for z in read(store) if z['pool'] == 'HAD'
                and (not x.date or z['business_date'] == x.date)]
        by = {}
        for z in rows: by.setdefault(z['match_id'], []).append(z)
        out = []
        for mid, zs in by.items():
            if len(zs) < 2: continue
            zs.sort(key=lambda z: z['updated_at'])
            f, l = zs[0], zs[-1]
            try:
                o1 = [float(f['odds'][k]) for k in 'hda']; o2 = [float(l['odds'][k]) for k in 'hda']
            except (KeyError, ValueError): continue
            p1, _ = devig(o1); p2, _ = devig(o2)
            out.append({'match_id': mid, 'match': f"{f['home']} vs {f['away']}",
                        'snapshots': len(zs), 'open': o1, 'latest': o2,
                        'prob_shift_pp': [round((b-a)*100, 2) for a, b in zip(p1, p2)],
                        'from': f['updated_at'], 'to': l['updated_at']})
        out.sort(key=lambda z: -max(abs(v) for v in z['prob_shift_pp']))
        print(json.dumps({'tracked': len(by), 'with_movement': len(out), 'movements': out},
                         ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
