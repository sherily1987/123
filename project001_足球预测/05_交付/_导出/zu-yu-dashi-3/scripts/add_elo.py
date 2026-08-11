#!/usr/bin/env python3
"""给回测数据集补上 ClubElo 评分（无前视偏差）

数据源：http://api.clubelo.com/YYYY-MM-DD  免费，返回该日期全部俱乐部 Elo 的 CSV

⚠️ 前视偏差防护（本脚本存在的核心理由）：
   绝不能用「今天的 Elo」去预测两年前的比赛——那份 Elo 已经把比赛结果吸收进去了，
   等于偷看答案。本脚本对每场比赛只取**开赛日之前**最近的一份快照。

用法：
    python add_elo.py <输入.json> <输出.json> <快照目录>

快照目录里应有若干 YYYY-MM-DD.csv，可用如下方式按周抓取：
    curl -o 2025-08-15.csv http://api.clubelo.com/2025-08-15
"""
import argparse
import bisect
import csv
import glob
import json
import os
import sys

# football-data 队名 → ClubElo 队名。仅列出两边写法不一致的。
NAME_MAP = {
    "Nott'm Forest": "Forest",
    "Bayern Munich": "Bayern",
    "Ein Frankfurt": "Frankfurt",
    "FC Koln": "Koeln",
    "M'gladbach": "Gladbach",
    "Werder Bremen": "Werder",
    "Ath Bilbao": "Bilbao",
    "Ath Madrid": "Atletico",
    "Espanol": "Espanyol",
    "Vallecano": "Rayo Vallecano",
    "St Etienne": "Saint-Etienne",
}


def load_snapshots(folder):
    """返回 (排序后的日期列表, {日期: {队名: Elo}})。"""
    snaps = {}
    for path in glob.glob(os.path.join(folder, '*.csv')):
        day = os.path.splitext(os.path.basename(path))[0]
        if len(day) != 10 or day.count('-') != 2:
            continue
        table = {}
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                club, elo = row.get('Club'), row.get('Elo')
                if club and elo:
                    try:
                        table[club] = float(elo)
                    except ValueError:
                        pass
        if table:
            snaps[day] = table
    return sorted(snaps), snaps


def parse_date(s):
    """football-data 的日期是 DD/MM/YYYY 或 DD/MM/YY，统一转 YYYY-MM-DD。"""
    s = (s or '').strip()
    if not s:
        return None
    if '-' in s and len(s) == 10:
        return s
    parts = s.split('/')
    if len(parts) != 3:
        return None
    d, m, y = parts
    if len(y) == 2:
        y = ('20' if int(y) < 70 else '19') + y
    return f'{y}-{int(m):02d}-{int(d):02d}'


def main():
    ap = argparse.ArgumentParser(description='为回测集补 ClubElo（防前视偏差）')
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('snapshots', help='存放 YYYY-MM-DD.csv 的目录')
    a = ap.parse_args()

    days, snaps = load_snapshots(a.snapshots)
    if not days:
        print('快照目录里没有可用的 CSV', file=sys.stderr)
        sys.exit(1)

    data = json.load(open(a.input, encoding='utf-8-sig'))
    matches = data['matches'] if isinstance(data, dict) else data

    stats = {'total': 0, 'with_elo': 0, 'no_date': 0, 'no_snapshot': 0}
    unmatched = {}
    out = []
    for m in matches:
        stats['total'] += 1
        day = parse_date(m.get('kickoff'))
        if not day:
            stats['no_date'] += 1
            out.append(m)
            continue

        # 关键：取严格早于开赛日的最近快照，杜绝前视偏差
        i = bisect.bisect_left(days, day) - 1
        if i < 0:
            stats['no_snapshot'] += 1
            out.append(m)
            continue
        snap_day = days[i]
        table = snaps[snap_day]

        eh = table.get(NAME_MAP.get(m['home'], m['home']))
        ea = table.get(NAME_MAP.get(m['away'], m['away']))
        if eh is None:
            unmatched[m['home']] = unmatched.get(m['home'], 0) + 1
        if ea is None:
            unmatched[m['away']] = unmatched.get(m['away'], 0) + 1

        if eh is not None and ea is not None:
            m = dict(m)
            m['elo_home'] = round(eh, 1)
            m['elo_away'] = round(ea, 1)
            m.setdefault('assumptions', []).append(f'Elo 取自 {snap_day} 快照（早于开赛日 {day}）')
            stats['with_elo'] += 1
        out.append(m)

    result = {'_meta': (data.get('_meta', {}) if isinstance(data, dict) else {}),
              'matches': out}
    result['_meta']['elo_source'] = 'clubelo.com 周快照，取开赛日之前最近一份'
    json.dump(result, open(a.output, 'w', encoding='utf-8'), ensure_ascii=False)

    print(f"✅ {stats['with_elo']} / {stats['total']} 场补上成对 Elo → {a.output}")
    if stats['no_date']:
        print(f"   {stats['no_date']} 场日期无法解析")
    if stats['no_snapshot']:
        print(f"   {stats['no_snapshot']} 场早于最早快照")
    if unmatched:
        top = sorted(unmatched.items(), key=lambda x: -x[1])[:12]
        print("   队名未匹配（次数）:", ", ".join(f"{k}×{v}" for k, v in top))


if __name__ == '__main__':
    main()
