#!/usr/bin/env python3
"""sales_day_collect — 体彩采集器（REBUILT 2026-08-02，双口径）。

新规则（默认）：--kickoff-date YYYY-MM-DD —— 按开球日期分组采集：
同一天开球的所有场次为一组；今天开售、明天开球的场次归入明天那一组，
不按销售日采集所有在售场次。
旧口径（兼容）：--sales-day YYYY-MM-DD —— 按竞彩销售日编号筛选（周六001…跨午夜）。
两种模式都按官方 matchId 去重，并逐场通过核心采集器 fetch_sporttery_full.py
拉取 HAD/HHAD/CRS/TTG/HAFU。
"""
import argparse
import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORE = Path('H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3/scripts/fetch_sporttery_full.py')

UA = {'User-Agent': 'Mozilla/5.0 (Linux; Android 14)',
      'Referer': 'https://m.sporttery.cn/mjc/zqsj/?tab=concern'}
LIST = 'https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry'
LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']


# [中文功能] 拉取某日体彩官方场次列表
def list_matches(method, query_date):
    url = LIST + '?' + urllib.parse.urlencode({'method': method, 'matchDate': query_date})
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.load(response)
    rows = []
    for day in data.get('value', {}).get('matchInfoList', []):
        rows.extend(day.get('subMatchList', []))
    return url, rows


# [中文功能] 调用核心采集器拉取单场全盘口
def run_core(query_date, method, output, delay, match_id=None, match_num=None):
    if match_id is not None:
        cmd = [sys.executable, str(CORE), '--match-id', str(match_id),
               '--match-num', str(match_num or ''), '--output', str(output),
               '--delay', str(delay)]
    else:
        cmd = [sys.executable, str(CORE), '--date', query_date, '--method', method,
               '--output', str(output), '--delay', str(delay)]
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(output.read_text(encoding='utf-8'))


# [中文功能] 按开球日期分组：双查 all+concern，仅保留开球日期==目标日的场次
def collect_by_kickoff_date(target):
    collected = {}
    source_urls = []
    for method in ('all', 'concern'):
        url, rows = list_matches(method, target.isoformat())
        source_urls.append(url)
        for row in rows:
            mid = row.get('matchId')
            if '已完成' in str(row.get('matchStatusName') or ''):
                continue  # 结果接口返回的已完赛场次不可预测，跳过
            if mid is not None and (row.get('matchDate') or '')[:10] == target.isoformat():
                collected[str(mid)] = row
    return collected, source_urls


# [中文功能] 按竞彩销售日采集（旧口径）：跨午夜双查，按销售日编号筛选
def collect_by_sales_day(start, label):
    collected = {}
    source_urls = []
    for idx, day in enumerate([start, start + timedelta(days=1)]):
        qdate = day.isoformat()
        method = 'all' if idx == 0 else 'concern'
        url, rows = list_matches(method, qdate)
        source_urls.append(url)
        for row in rows:
            num = str(row.get('matchNumStr') or '')
            if '已完成' in str(row.get('matchStatusName') or ''):
                continue
            if not num.startswith(label):
                continue
            mid = row.get('matchId')
            if mid is not None:
                collected[str(mid)] = row
    return collected, source_urls


# [中文功能] 采集主流程（新规则 kickoff-date / 旧口径 sales-day）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sales-day', help='[旧口径] sales-day start date YYYY-MM-DD')
    ap.add_argument('--kickoff-date', help='[新规则] 按开球日期采集：同一天开球的所有场次为一组 YYYY-MM-DD')
    ap.add_argument('--sales-label', help='e.g. 周六; defaults to weekday of sales-day')
    ap.add_argument('--output', required=True)
    ap.add_argument('--emit-input')
    ap.add_argument('--delay', type=float, default=1.5)
    args = ap.parse_args()

    if args.kickoff_date:
        mode = 'kickoff-date'
        target = date.fromisoformat(args.kickoff_date)
        label = None
        collected, source_urls = collect_by_kickoff_date(target)
        if not collected:
            raise SystemExit(f'no matches with kickoff date {args.kickoff_date}')
        group_key = args.kickoff_date
    elif args.sales_day:
        mode = 'sales-day'
        start = date.fromisoformat(args.sales_day)
        label = args.sales_label or LABELS[start.weekday()]
        collected, source_urls = collect_by_sales_day(start, label)
        if not collected:
            raise SystemExit(f'no {label} matches found for sales day {args.sales_day}')
        group_key = args.sales_day
    else:
        raise SystemExit('需要 --kickoff-date（新规则）或 --sales-day（旧口径）之一')

    with tempfile.TemporaryDirectory(prefix=f'fusion-{mode}-') as td:
        raw_parts = []
        errors = []
        for pos, row in enumerate(collected.values()):
            qdate = (row.get('matchDate') or group_key)[:10]
            out = Path(td) / f'{pos}.json'
            try:
                raw_parts.append(run_core(qdate, 'all', out, args.delay,
                                          match_id=row.get('matchId'), match_num=row.get('matchNumStr')))
            except Exception as exc:
                errors.append({'match_id': row.get('matchId'),
                               'match_num': row.get('matchNumStr'),
                               'error': str(exc)[:200]})
        matches = []
        for part in raw_parts:
            for match in part.get('matches', []):
                mid = str(match.get('match_id'))
                if mid not in collected:
                    continue
                source = collected[mid]
                match['business_date'] = source.get('businessDate') or source.get('matchDate')
                match['kickoff_local'] = f"{source.get('matchDate') or ''} {(source.get('matchTime') or '00:00')[:5]}".strip()
                if source.get('matchDate'):
                    match['kickoff_iso'] = f"{source['matchDate']}T{(source.get('matchTime') or '00:00')[:5]}:00+08:00"
                match['timezone'] = 'Asia/Shanghai'
                match['match_num'] = source.get('matchNumStr') or match.get('match_num')
                match['home'] = source.get('homeTeamAbbName') or match.get('home')
                match['away'] = source.get('awayTeamAbbName') or match.get('away')
                match['league'] = source.get('leagueAbbName') or match.get('league')
                match['status_name'] = source.get('matchStatusName') or match.get('status_name')
                matches.append(match)
        by_id = {str(m.get('match_id')): m for m in matches}
        matches = list(by_id.values())
        if mode == 'kickoff-date':
            matches.sort(key=lambda m: (str(m.get('kickoff_local') or ''), str(m.get('match_num', ''))))
        else:
            matches.sort(key=lambda m: int(str(m.get('match_num', '')).replace(label, ''))
                         if str(m.get('match_num', '')).replace(label, '').isdigit() else 999)
        fetched_at = max((p.get('fetched_at', '') for p in raw_parts), default='')
        if mode == 'kickoff-date':
            output = {
                'schema_version': 'fusion-kickoff-date-1.0',
                'collector_version': 'football-quant-fusion-kickoff-date-1.0',
                'source': '中国体彩网移动端官方链路',
                'source_urls': source_urls,
                'kickoff_date': args.kickoff_date,
                'group_rule': '同一天开球的所有场次为一组；今天开售、明天开球的场次归入明天那一组。',
                'fetched_at': fetched_at,
                'count': len(matches),
                'error_count': len(errors),
                'errors': errors,
                'matches': matches,
                'notes': ['新规则：按开球日期分组采集，不按销售日采集在售场次。',
                          '官方列表 all+concern 双查该开球日期，按 matchId 去重，'
                          '仅保留开球日期==目标日的场次。',
                          '注意 fusion 采集可能漏场次，需与 soccer-lottery concern 快照'
                          '按 match_id 合并（见 pitfalls 3.1）。']}
        else:
            output = {
                'schema_version': 'fusion-sales-day-1.0',
                'collector_version': 'football-quant-fusion-sales-day-1.0',
                'source': '中国体彩网移动端官方链路',
                'source_urls': source_urls,
                'sales_day': args.sales_day,
                'sales_label': label,
                'calendar_query_dates': [(date.fromisoformat(args.sales_day) + timedelta(days=i)).isoformat()
                                         for i in (0, 1)],
                'fetched_at': fetched_at,
                'count': len(matches),
                'error_count': len(errors),
                'errors': errors,
                'matches': matches,
                'notes': ['[旧口径] 按竞彩销售日编号筛选；跨午夜场次保留实际kickoff日期。',
                          '按官方match_id去重，不把周日场次混入周六销售日。',
                          '注意 fusion 采集可能漏场次，需与 soccer-lottery concern 快照'
                          '按 match_id 合并（见 pitfalls 3.1）。']}
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        result = {'status': 'ok', 'mode': mode, 'errors': len(errors),
                  ('kickoff_date' if mode == 'kickoff-date' else 'sales_day'): group_key,
                  'count': len(matches), 'output': args.output}
        if args.emit_input:
            spec = {'matches': []}
            keys = ['hh', 'hd', 'ha', 'dh', 'dd', 'da', 'ah', 'ad', 'aa']
            for m in matches:
                if not m.get('odds_eligible') or not m.get('model_odds'):
                    continue
                d = {'home': m['home'], 'away': m['away'], 'competition': m['league'],
                     'stage': m['league'], 'kickoff': m['kickoff_iso'], 'mode': 'market_only',
                     'odds': m['model_odds'], 'context_confirmed': True,
                     'field_meta': {
                         'odds': {'reliability': 100, 'freshness': 100,
                                  'source': '中国体彩网移动端官方固定奖金接口',
                                  'observed_at': m.get('had_updated_at') or fetched_at},
                         'hhad': {'reliability': 100, 'freshness': 100,
                                  'source': '中国体彩网移动端官方固定奖金接口',
                                  'observed_at': m.get('hhad_updated_at') or fetched_at},
                         'ttg': {'reliability': 100, 'freshness': 100,
                                 'source': '中国体彩网移动端官方固定奖金接口',
                                 'observed_at': m.get('ttg_updated_at') or fetched_at},
                         'hafu': {'reliability': 100, 'freshness': 100,
                                  'source': '中国体彩网移动端官方固定奖金接口',
                                  'observed_at': m.get('hafu_updated_at') or fetched_at},
                         'crs': {'reliability': 100, 'freshness': 100,
                                 'source': '中国体彩网移动端官方固定奖金接口',
                                 'observed_at': m.get('crs_updated_at') or fetched_at},
                     },
                     'assumptions': [],
                     'sporttery_meta': {'match_id': m['match_id'], 'match_num': m['match_num']}}
                if m.get('model_hhad'):
                    d['hhad'] = m['model_hhad']
                    d['assumptions'].append('已提供体彩HHAD三态；未自动映射为亚洲盘ah_line')
                else:
                    d['field_meta'].pop('hhad', None)
                if m.get('ttg') and all(k in m['ttg'] for k in ['0', '1', '2', '3', '4', '5', '6', '7+']):
                    d['ttg'] = {'odds': [m['ttg'][k] for k in ['0', '1', '2', '3', '4', '5', '6', '7+']]}
                else:
                    d['field_meta'].pop('ttg', None)
                    d['assumptions'].append('无完整TTG，比分/O-U/BTTS由现有市场反解')
                if m.get('hafu') and all(k in m['hafu'] for k in keys):
                    d['hafu'] = {'odds': [m['hafu'][k] for k in keys]}
                else:
                    d['field_meta'].pop('hafu', None)
                if m.get('team_ids'):
                    d['sporttery_meta'].update(m['team_ids'])
                if m.get('crs'):
                    d['crs'] = m.get('crs')
                spec['matches'].append(d)
            Path(args.emit_input).parent.mkdir(parents=True, exist_ok=True)
            Path(args.emit_input).write_text(json.dumps(spec, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            result['model_input'] = args.emit_input
            result['input_count'] = len(spec['matches'])
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
