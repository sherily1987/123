#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日一体化流水线：回填赛果 → 采集新盘 → 登记快照 → 追加赔率移动库。

体彩每天 11:00 开售时刷新全部盘口赔率，故建议 11:05 后运行。

用法：
  python3 daily_pipeline.py                    # today + 明天
  python3 daily_pipeline.py --date 2026-08-02  # 指定单日
  python3 daily_pipeline.py --dry-run          # 只看不写
"""
import argparse, json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
STORE = 'H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest'
WORK = Path('H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/forward')
CST = timezone(timedelta(hours=8))


# [中文功能] 带重试地执行子进程命令
def run(args, retries=0, **kw):
    """retries>0 时对网络类失败重试，间隔递增。"""
    import time
    for i in range(retries + 1):
        r = subprocess.run([sys.executable] + [str(x) for x in args],
                           capture_output=True, text=True, **kw)
        if r.returncode == 0 or i == retries:
            return r
        time.sleep(3 * (i + 1))
    return r


# [中文功能] 核心版每日流水线（结算→采集→登记）
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', help='只处理该 business_date，默认今天+明天')
    ap.add_argument('--snapshot', default='T-7h')
    ap.add_argument('--store', default=STORE)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    today = datetime.now(CST)
    dates = [a.date] if a.date else [today.strftime('%Y-%m-%d'),
                                     (today + timedelta(days=1)).strftime('%Y-%m-%d')]
    report = {'ran_at': datetime.now(CST).isoformat(), 'dates': dates,
              'settle': None, 'collect': [], 'record': [], 'movement': []}

    # 1) 先回填已完赛的赛果（官方 matchId 优先匹配）
    r = run([HERE / 'settle_from_sporttery.py', '--store', a.store]
            + (['--dry-run'] if a.dry_run else []), retries=2)
    try:
        s = json.loads(r.stdout)
        report['settle'] = {'settled': s.get('settled'), 'pending': s.get('pending'),
                            'detail': [x for x in s.get('report', [])
                                       if x['status'] in ('settled', 'would_settle')]}
    except (ValueError, AttributeError):
        report['settle'] = {'error': (r.stderr or r.stdout)[:200]}

    # 2) 逐日采集全盘口 + 生成输入 + 追加赔率移动库
    for day in dates:
        d = WORK / day
        d.mkdir(parents=True, exist_ok=True)
        raw = d / f'sporttery_{a.snapshot}.json'
        batch = d / f'inputs_{a.snapshot}.json'
        r = run([HERE / 'fetch_sporttery_full.py', '--date', day,
                 '--output', raw, '--emit-input', batch], retries=2)
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            report['collect'].append({'date': day, 'error': (r.stderr or r.stdout)[:200]})
            continue
        report['collect'].append({'date': day, 'matches': info.get('count'),
                                  'with_odds': info.get('input_count')})

        m = run([HERE / 'odds_movement.py', 'add', '--source', raw])
        try:
            report['movement'].append({'date': day, **json.loads(m.stdout)})
        except ValueError:
            report['movement'].append({'date': day, 'error': (m.stderr or m.stdout)[:150]})

        if a.dry_run or not batch.exists():
            continue
        # 3) 采集前瞻：攻防均值、历史交锋、近期战绩、伤停、积分榜、球员、未来赛程
        preview = d / f'preview_{a.snapshot}.json'
        hybrid = d / f'hybrid_inputs_{a.snapshot}.json'
        pv = run([HERE / 'fetch_match_preview.py', '--from-collect', raw,
                  '--output', preview, '--terms', '10'], retries=2)
        if pv.returncode == 0:
            mg = run([HERE / 'merge_preview.py', '--input', batch, '--preview', preview,
                      '--output', hybrid], retries=0)
            source_input = hybrid if mg.returncode == 0 else batch
        else:
            source_input = batch
            report['collect'][-1]['preview_error'] = (pv.stderr or pv.stdout)[-180:]
        # 4) 逐场登记快照（record_prediction 自身拒绝已开赛场次）
        for mm in json.load(open(source_input, encoding='utf-8'))['matches']:
            num = mm['sporttery_meta']['match_num']
            ip, op = d / f'{num}_input.json', d / f'{num}_output.json'
            json.dump(mm, open(ip, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
            q = run([HERE / 'record_prediction.py', '--input', ip, '--output', op,
                     '--predict', '--snapshot', a.snapshot, '--store', a.store])
            try:
                st = json.loads(q.stdout).get('status')
            except ValueError:
                st = None
            ok = q.returncode == 0 and st == 'recorded'
            dup = st == 'skipped_duplicate_snapshot'
            report['record'].append({
                'match_num': num, 'match': f"{mm['home']} vs {mm['away']}",
                'ok': ok, 'status': st or 'error', 'duplicate': dup,
                'note': None if q.returncode == 0 else q.stderr.strip().splitlines()[-1][:80]})

    report['summary'] = {
        'settled': (report['settle'] or {}).get('settled', 0),
        'collected': sum(c.get('matches') or 0 for c in report['collect']),
        'recorded': sum(1 for x in report['record'] if x['ok']),
        'duplicate_snapshot': sum(1 for x in report['record'] if x.get('duplicate')),
        'skipped': sum(1 for x in report['record']
                       if not x['ok'] and not x.get('duplicate')),
        'odds_snapshots_added': sum(m.get('added') or 0 for m in report['movement']),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
