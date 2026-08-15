#!/usr/bin/env python3
"""One-shot daily pipeline for football-quant-fusion.

Ported from zu-yu-dashi-3's daily_pipeline.py (settle -> collect -> record ->
odds-movement) but rewired to fusion's own collector (sales_day_collect.py).
默认按开球日期分组采集（--kickoff-date，同日开球为一组）；旧口径可用
--sales-day。登记走 fusion_cli.py record（完整融合 payload，含门控/审计）。

Why this exists: zu-yu-dashi-3's daily_pipeline is a strong, already-battle
-tested orchestration pattern (see its SKILL.md changelog and pitfalls.md),
but it registers straight into zu-yu-dashi-3's own store via
record_prediction.py --predict, which calls core.predict() directly and
bypasses every fusion-layer gate (recommendation_policy, ledger audit,
UNFITTED_FUSION tagging, sales-day de-duplication). Running it does not
produce a fusion registration. This script closes that gap without
duplicating math: it shells out to fusion's own sales_day_collect.py and
fusion_cli.py record, which internally delegates back to fusion_predict.py
-> core.predict().

Usage:
  python3 fusion_daily_pipeline.py --kickoff-date 2026-08-03
  python3 fusion_daily_pipeline.py --sales-day 2026-08-02 --dry-run
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime import resolve_python
from runtime_paths import core_scripts_dir

# 统一解释器：当前为非 3.12 时，子进程改用内置 Python 3.12
PY = resolve_python()

HERE = Path(__file__).resolve().parent
# 曾经硬编码指向 .codex\...\football-quant-fusion-suite\...（一份需要手动同步的外部
# 物理拷贝，本轮会话已实测发现它比仓库内版本落后过）。改用 runtime_paths 里已有的
# core_scripts_dir()：读 FUSION_CORE_DIR 环境变量（当前实际配置的就是仓库内路径），
# 没设置时回退到仓库内路径——不再有第二处需要手动保持一致的路径来源。
CORE_DIR = core_scripts_dir()
# ⚠️ STORE/ODDS_STORE/WORK 仍指向外部物理拷贝（下方三行），刻意未在本轮改动：
# 实测该外部副本的 production_movement.jsonl（926KB，8-12 09:00 写入）比仓库内那份
# （753KB，8-11 10:00）更新更大，说明两边数据已经分裂。贸然切换会让流水线"丢失"
# 这几天写入外部副本的数据。这是独立的数据一致性问题，需要先合并两份历史数据、
# 确认权威来源，再统一路径——不能顺手在这次改动里一起做。
STORE = 'C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/backtest'
ODDS_STORE = 'C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/odds/production_movement.jsonl'
WORK = Path('C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/forward')
CST = timezone(timedelta(hours=8))


# [中文功能] 带重试地执行子进程命令（实时转发输出，同时保留 stdout 供调用方解析）
def run(cmd, retries=0):
    import time
    for i in range(retries + 1):
        proc = subprocess.Popen([PY] + [str(x) for x in cmd],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        chunks = []
        for line in proc.stdout:
            chunks.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
        r = type("Completed", (), {})()
        r.stdout = "".join(chunks)
        r.stderr = ""
        r.returncode = proc.returncode
        if proc.returncode == 0 or i == retries:
            return r
        time.sleep(3 * (i + 1))
    return r


# [中文功能] 每日流水线：结算→采集→登记→赔率移动
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kickoff-date', help='[新规则] 按开球日期采集：同日开球为一组 YYYY-MM-DD')
    ap.add_argument('--sales-day', help='YYYY-MM-DD; defaults to today (Asia/Shanghai)')
    ap.add_argument('--snapshot', default='T-7h')
    ap.add_argument('--store', default=STORE)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--apifootball-fallback', action='store_true',
                    help='体彩官方赛果缺失时显式启用 APIFootball 欧冠补全')
    a = ap.parse_args()

    today = datetime.now(CST)
    sales_day = a.kickoff_date or a.sales_day or today.strftime('%Y-%m-%d')
    report = {'ran_at': datetime.now(CST).isoformat(), 'sales_day': sales_day,
              'settle': None, 'collect': None, 'record': [], 'movement': None,
              'intl_odds': None}

    # 1) Settle already-finished matches first (official matchId preferred).
    r = run([HERE / 'fusion_settle.py', '--store', a.store]
            + (['--dry-run'] if a.dry_run else [])
            + (['--apifootball-fallback'] if a.apifootball_fallback else []), retries=2)
    try:
        s = json.loads(r.stdout)
        official = s.get('official') or {}
        provider = s.get('apifootball_fallback') or {}
        detail = [x for x in official.get('report', [])
                  if x.get('status') in ('settled', 'would_settle')]
        detail.extend(x for x in provider.get('report', [])
                      if x.get('status') in ('settled', 'would_settle'))
        report['settle'] = {'settled': s.get('settled'),
                            'pending': official.get('pending'),
                            'apifootball_fallback': provider or None,
                            'detail': detail}
    except (ValueError, AttributeError):
        report['settle'] = {'error': (r.stderr or r.stdout)[:200]}

    # 2) Collect the full cross-midnight sales day via fusion's own collector.
    d = WORK / sales_day
    d.mkdir(parents=True, exist_ok=True)
    raw = d / f'sporttery_{a.snapshot}.json'
    batch = d / f'inputs_{a.snapshot}.json'
    collect_args = ([HERE / 'sales_day_collect.py', '--kickoff-date', sales_day]
                    if a.kickoff_date else [HERE / 'sales_day_collect.py', '--sales-day', sales_day])
    r = run(collect_args + [
             '--output', raw, '--emit-input', batch], retries=2)
    try:
        # sales_day_collect.py prints pretty-printed (indent=2) JSON, unlike
        # zu-yu-dashi-3's single-line collector output, so the whole stdout
        # must be parsed rather than just its last line.
        info = json.loads(r.stdout)
        report['collect'] = {'count': info.get('count'), 'with_odds': info.get('input_count')}
    except ValueError:
        report['collect'] = {'error': (r.stderr or r.stdout)[:300]}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # 3) Append odds movement snapshot (best-effort; fusion_cli does this too,
    #    duplicated here so the pipeline is a single source of truth even if
    #    the caller does not run `collect` separately).
    m = run([CORE_DIR / 'odds_movement.py', 'add', '--source', raw, '--store', ODDS_STORE])
    try:
        report['movement'] = json.loads(m.stdout)
    except ValueError:
        report['movement'] = {'error': (m.stderr or m.stdout)[:150]}

    # 3.5) 国际盘对照（可选，The Odds API）：设置了 ODDS_API_KEY 才抓取；
    #      失败只记录、不阻断主链路。结果存 odds/intl_production.jsonl。
    if os.environ.get('ODDS_API_KEY'):
        intl_out = WORK / sales_day / f'intl_{a.snapshot}.json'
        ir = run([HERE / 'odds_api_adapter.py', '--match-file', raw,
                  '--out', intl_out,
                  '--store', str(Path(ODDS_STORE).parent)])
        try:
            report['intl_odds'] = json.loads(ir.stdout)
        except ValueError:
            report['intl_odds'] = {'status': 'error',
                                   'error': (ir.stderr or ir.stdout)[:200]}
    else:
        report['intl_odds'] = {'status': 'skipped',
                               'reason': 'ODDS_API_KEY 未设置，国际盘对照默认不启用'}

    if a.dry_run or not batch.exists():
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # 4) Register each match through the FULL fusion path (fusion_cli record
    #    -> fusion_predict -> core.predict), not the bare core registration.
    matches = json.load(open(batch, encoding='utf-8')).get('matches', [])
    for mm in matches:
        num = (mm.get('sporttery_meta') or {}).get('match_num', 'unknown')
        ip = d / f'{num}_input.json'
        op = d / f'{num}_output.json'
        json.dump(mm, open(ip, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
        q = run([HERE / 'fusion_cli.py', 'record', '--input', str(ip), '--output', str(op),
                 '--snapshot', a.snapshot, '--store', a.store])
        try:
            payload = json.loads(q.stdout)
            st = payload.get('status')
        except ValueError:
            st = None
        ok = q.returncode == 0 and st == 'recorded'
        dup = st == 'skipped_duplicate_snapshot'
        report['record'].append({
            'match_num': num, 'match': f"{mm.get('home')} vs {mm.get('away')}",
            'ok': ok, 'status': st or 'error', 'duplicate': dup,
            'note': None if ok or dup else (q.stderr or q.stdout).strip().splitlines()[-1][:120]
                    if (q.stderr or q.stdout) else None})

    report['summary'] = {
        'settled': (report['settle'] or {}).get('settled', 0),
        'collected': (report['collect'] or {}).get('count', 0),
        'recorded': sum(1 for x in report['record'] if x['ok']),
        'duplicate_snapshot': sum(1 for x in report['record'] if x.get('duplicate')),
        'skipped_or_blocked': sum(1 for x in report['record'] if not x['ok'] and not x.get('duplicate')),
        'odds_snapshots_added': (report['movement'] or {}).get('added', 0),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
