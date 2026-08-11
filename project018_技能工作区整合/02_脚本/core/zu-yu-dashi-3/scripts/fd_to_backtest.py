#!/usr/bin/env python3
"""football-data.co.uk CSV → backtest.py 输入格式

数据源：https://www.football-data.co.uk/  （免费公开，明确供投注系统开发与分析使用）
下载 URL 格式：https://www.football-data.co.uk/mmz4281/{赛季}/{联赛}.csv
  赛季：2526 = 2025/26 ｜ 联赛：E0 英超 D1 德甲 SP1 西甲 I1 意甲 F1 法甲

用法：
    python fd_to_backtest.py <输出.json> <csv1> [csv2 ...]

赔率优先级：Pinnacle(PS*) > 多家平均(Avg*) > Bet365(B365*)
Pinnacle 抽水最低、定价最锐，是校准回测的首选基准。
"""
import argparse
import csv
import json
import sys

# football-data 的 Div 代码 → 引擎的赛事名（用于 LEAGUE_GOAL_TOTALS 查表）
DIV_TO_COMPETITION = {
    'E0': '英超', 'E1': '英冠',
    'D1': '德甲', 'D2': '德乙',
    'SP1': '西甲', 'SP2': '西乙',
    'I1': '意甲', 'I2': '意乙',
    'F1': '法甲', 'F2': '法乙',
}

# 赔率列的优先顺序：(主, 平, 客, 来源标签)
ODDS_COLUMNS = [
    ('PSH', 'PSD', 'PSA', 'Pinnacle'),
    ('AvgH', 'AvgD', 'AvgA', '多家平均'),
    ('B365H', 'B365D', 'B365A', 'Bet365'),
]


# [中文功能] 按优先级取一组完整赔率，缺失则降级下一来源
def pick_odds(row):
    """按优先级取一组完整赔率。任一项缺失或非法则降级到下一来源。"""
    for h, d, a, tag in ODDS_COLUMNS:
        try:
            o = [float(row[h]), float(row[d]), float(row[a])]
        except (KeyError, ValueError, TypeError):
            continue
        if all(x > 1 for x in o):
            return o, tag
    return None, None


# [中文功能] 把football-data CSV转换为回测JSON
def convert(paths):
    matches, stats = [], {'total': 0, 'skipped': 0, 'by_source': {}}
    for p in paths:
        with open(p, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                if not row.get('HomeTeam') or not row.get('AwayTeam'):
                    continue          # 文件尾部常有空行
                stats['total'] += 1
                try:
                    actual = [int(row['FTHG']), int(row['FTAG'])]
                except (KeyError, ValueError, TypeError):
                    stats['skipped'] += 1
                    continue          # 未完赛或比分缺失
                odds, tag = pick_odds(row)
                if odds is None:
                    stats['skipped'] += 1
                    continue
                div = row.get('Div', '')
                comp = DIV_TO_COMPETITION.get(div, div)
                stats['by_source'][tag] = stats['by_source'].get(tag, 0) + 1
                matches.append({
                    'home': row['HomeTeam'],
                    'away': row['AwayTeam'],
                    'stage': comp,
                    'competition': comp,
                    'kickoff': row.get('Date', ''),
                    'odds': odds,
                    'actual': actual,
                    'assumptions': [f'赔率来源 {tag}'],
                })
    return matches, stats


# [中文功能] CLI入口：CSV列表转回测数据集
def main():
    ap = argparse.ArgumentParser(description='football-data CSV → 回测 JSON')
    ap.add_argument('output', help='输出 JSON 路径')
    ap.add_argument('csvs', nargs='+', help='一个或多个 football-data CSV')
    a = ap.parse_args()

    matches, stats = convert(a.csvs)
    if not matches:
        print('没有可用比赛，检查 CSV 是否正确。', file=sys.stderr)
        sys.exit(1)

    out = {
        '_meta': {
            'source': 'football-data.co.uk',
            'license': '免费公开，供投注系统开发与分析使用',
            'files': a.csvs,
            'odds_priority': 'Pinnacle > 多家平均 > Bet365',
        },
        'matches': matches,
    }
    with open(a.output, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False)

    print(f"✅ {len(matches)} 场写入 {a.output}")
    print(f"   跳过 {stats['skipped']} 场（无比分或无完整赔率）")
    for k, v in sorted(stats['by_source'].items(), key=lambda x: -x[1]):
        print(f"   赔率来源 {k}: {v} 场")


if __name__ == '__main__':
    main()
