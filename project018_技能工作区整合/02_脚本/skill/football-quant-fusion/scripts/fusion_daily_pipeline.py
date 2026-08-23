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
from runtime_paths import (
    assert_writable_target,
    backtest_store,
    core_scripts_dir,
    forward_work_dir,
    odds_store,
)
from evidence_merge import merge_browser_audit

# 统一解释器：当前为非 3.12 时，子进程改用内置 Python 3.12
PY = resolve_python()

HERE = Path(__file__).resolve().parent
# 曾经硬编码指向 .codex\...\football-quant-fusion-suite\...（一份需要手动同步的外部
# 物理拷贝，本轮会话已实测发现它比仓库内版本落后过）。改用 runtime_paths 里已有的
# core_scripts_dir()：读 FUSION_CORE_DIR 环境变量（当前实际配置的就是仓库内路径），
# 没设置时回退到仓库内路径——不再有第二处需要手动保持一致的路径来源。
CORE_DIR = core_scripts_dir()
STORE = backtest_store()
ODDS_STORE = odds_store()
WORK = forward_work_dir()
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


def run_hybrid_shadow(batch: Path, sales_day: str, day_dir: Path, snapshot: str) -> dict:
    """Run research-only hybrid from the exact market batch just collected.

    The quant record and hybrid sidecar therefore share an identical Sporttery
    snapshot.  A failed research pass must not block the production-safe
    market-only registration performed immediately before it.
    """
    output = day_dir / f"hybrid_{snapshot}.json"
    result = run([
        HERE / "hybrid_shadow.py", "--input", batch,
        "--sales-day", sales_day, "--output", output,
    ])
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    if result.returncode != 0:
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    return {
        "status": "ok",
        "n": payload.get("n", 0),
        "ok": payload.get("ok", 0),
        "skipped": payload.get("skipped", 0),
        "output": str(output),
    }


def run_half_time_research(store: Path) -> dict:
    """Capture and verify half-time labels as research evidence after settlement."""
    research = store.parent / "research"
    fixture_dir = research / "half-time-fixtures" / "apifootball"
    fixtures = fixture_dir / "fixtures.json"
    evidence = research / "half-time-evidence" / "apifootball_verified_latest.json"
    capture = run([
        HERE / "collect_half_time_apifootball.py", "--store", store,
        "--output-dir", fixture_dir, "--fixtures-output", fixtures,
    ])
    try:
        captured = json.loads(capture.stdout)
    except ValueError:
        return {"status": "error", "stage": "capture",
                "error": (capture.stderr or capture.stdout)[-300:]}
    if capture.returncode != 0 or captured.get("status") != "ok":
        return {"status": "error", "stage": "capture",
                "error": (capture.stderr or capture.stdout)[-300:]}
    fixtures = Path(captured.get("fixtures") or fixtures)
    if not fixtures.is_file():
        return {"status": "error", "stage": "capture", "error": "fixtures_output_missing"}
    aliases = HERE.parent / "config" / "intl_odds_sources.json"
    enriched = run([
        HERE / "half_time_enrichment.py", "--fixtures", fixtures,
        "--store", store, "--aliases", aliases, "--output", evidence,
    ])
    try:
        result = json.loads(enriched.stdout)
    except ValueError:
        return {"status": "error", "stage": "enrichment",
                "error": (enriched.stderr or enriched.stdout)[-300:]}
    if enriched.returncode != 0 or result.get("status") != "ok":
        return {"status": "error", "stage": "enrichment",
                "error": (enriched.stderr or enriched.stdout)[-300:]}
    return {"status": "ok", "provider_rows": captured.get("provider_rows", 0),
            "rows": result.get("rows", 0), "verified": result.get("verified", 0)}


def run_derivative_research(store: Path) -> dict:
    """Refresh O/U and HAFU diagnostics after settlement without changing production outputs."""
    research = store.parent / "research"
    evidence = research / "half-time-evidence" / "apifootball_verified_latest.json"
    output = research / "derivative-diagnostics" / "latest.json"
    result = run([
        HERE / "derivative_diagnostics.py", "--store", store,
        "--half-time-evidence", evidence, "--output", output,
    ])
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    if result.returncode != 0 or payload.get("status") != "ok":
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    return {"status": "ok", "output": str(output), "metrics": payload.get("metrics")}


def run_draw_watch_research(store: Path) -> dict:
    """Refresh settled draw-watch/shadow evidence without touching m4 outputs."""
    output = store.parent / "research" / "draw-watch" / "latest.json"
    result = run([HERE / "draw_watch_evaluation.py", "--store", store, "--output", output])
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    if result.returncode != 0:
        return {"status": "error", "error": (result.stderr or result.stdout)[-300:], "output": str(output)}
    return {"status": "ok", "output": str(output), "admission": payload.get("admission"),
            "shadow_probability_paired": payload.get("shadow_probability_paired")}


# [中文功能] 每日流水线：结算→采集→登记→赔率移动
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--kickoff-date', help='[新规则] 按开球日期采集：同日开球为一组 YYYY-MM-DD')
    ap.add_argument('--sales-day', help='YYYY-MM-DD; defaults to today (Asia/Shanghai)')
    # Generic ``prematch`` is truthful at any pre-kickoff collection time.
    # A precise T-minus label may only be supplied explicitly by a scheduler
    # that actually ran at that measured offset.
    ap.add_argument('--snapshot', default='prematch')
    ap.add_argument('--store', type=Path, default=STORE)
    ap.add_argument('--odds-store', type=Path, default=ODDS_STORE)
    ap.add_argument('--work-dir', type=Path, default=WORK)
    ap.add_argument('--allow-legacy-write', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--bb-browser-url-map', type=Path,
                    help='可选：BB-browser/FotMob URL映射JSON；仅追加research-only证据')
    ap.add_argument('--bb-browser-discover', action='store_true',
                    help='可选：按比赛身份发现官方/补充来源候选，写browser_tasks.json')
    ap.add_argument('--apifootball-fallback', action='store_true',
                    help='体彩官方赛果缺失时显式启用 APIFootball 欧冠补全')
    a = ap.parse_args()
    try:
        a.store = assert_writable_target(a.store, a.allow_legacy_write)
        a.odds_store = assert_writable_target(a.odds_store, a.allow_legacy_write)
        a.work_dir = assert_writable_target(a.work_dir, a.allow_legacy_write)
    except ValueError as exc:
        ap.error(str(exc))

    today = datetime.now(CST)
    sales_day = a.kickoff_date or a.sales_day or today.strftime('%Y-%m-%d')
    report = {'ran_at': datetime.now(CST).isoformat(), 'sales_day': sales_day,
              'settle': None, 'collect': None, 'record': [], 'movement': None,
              'intl_odds': None, 'hybrid_shadow': None, 'half_time_research': None,
              'derivative_research': None, 'draw_watch_research': None}

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

    # 1.5) New 90-minute settlements need independently verified half-time
    # labels before HAFU can ever be evaluated.  This is research-only and a
    # provider failure must not block the production collection/registration.
    if not a.dry_run and int((report['settle'] or {}).get('settled') or 0) > 0:
        report['half_time_research'] = run_half_time_research(a.store)
        report['derivative_research'] = run_derivative_research(a.store)
        report['draw_watch_research'] = run_draw_watch_research(a.store)
    else:
        report['half_time_research'] = {'status': 'skipped', 'reason': 'no_new_settlement_or_dry_run'}
        report['derivative_research'] = {'status': 'skipped', 'reason': 'no_new_settlement_or_dry_run'}
        report['draw_watch_research'] = {'status': 'skipped', 'reason': 'no_new_settlement_or_dry_run'}

    # 2) Collect the full cross-midnight sales day via fusion's own collector.
    d = a.work_dir / sales_day
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
    if not batch.exists():
        report['input_gate'] = {'status': 'skipped', 'reason': 'collector did not emit formal input batch'}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    try:
        matches = json.load(open(batch, encoding='utf-8')).get('matches', [])
    except (OSError, ValueError, AttributeError) as exc:
        report['input_gate'] = {'status': 'error', 'reason': f'formal input batch unreadable: {exc}'}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if not matches:
        # 待开售 / 缺完整 HAD 的原始行不是可登记预测，也不值得消耗国际盘额度。
        report['input_gate'] = {'status': 'skipped', 'reason': 'no formal Sporttery inputs (unopened or incomplete odds)'}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    # 3.4) Automatic pre-match evidence pass.  This writes immutable sidecars
    # and attaches only the audited evidence fields to the in-memory input;
    # the official odds and registered prediction identity remain unchanged.
    evidence_dir = d / "evidence_snapshots"
    er = run([HERE / 'prematch_evidence_collect.py', '--input', batch,
              '--output-dir', evidence_dir])
    try:
        report['prematch_evidence'] = json.loads(er.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError, AttributeError):
        report['prematch_evidence'] = {'status': 'error', 'error': (er.stderr or er.stdout)[-300:]}
    for mm in matches:
        mid = str(mm.get('match_id') or (mm.get('sporttery_meta') or {}).get('match_id') or '')
        sidecar = evidence_dir / (mid if mid.startswith('sporttery-') else f'sporttery-{mid}')
        if not sidecar.exists():
            continue
        try:
            evidence = json.loads(sidecar.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        audit = evidence.get('evidence_audit') or {}
        chain = {name: (audit.get('entries') or {}).get(name) for name in audit.get('critical_fields') or []}
        mm['evidence_chain'] = {k: v for k, v in chain.items() if v}
        mm['evidence_snapshot_ref'] = str(sidecar)
    if a.bb_browser_url_map or a.bb_browser_discover:
        browser_dir = evidence_dir / 'bb-browser'
        browser_args = [HERE / 'bb_browser_evidence_collect.py', '--input', batch,
                         '--output-dir', browser_dir]
        if a.bb_browser_url_map:
            browser_args += ['--url-map', a.bb_browser_url_map]
        if a.bb_browser_discover:
            browser_args += ['--discover']
        br = run(browser_args)
        try:
            report['bb_browser_evidence'] = json.loads(br.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError, AttributeError):
            report['bb_browser_evidence'] = {'status': 'error', 'error': (br.stderr or br.stdout)[-300:]}
        for mm in matches:
            mid = str(mm.get('match_id') or (mm.get('sporttery_meta') or {}).get('match_id') or '')
            browser_sidecar = browser_dir / f"{mid if mid.startswith('sporttery-') else f'sporttery-{mid}'}.json"
            if browser_sidecar.exists():
                mm['browser_evidence_ref'] = str(browser_sidecar)
                try:
                    browser_snapshot = json.loads(browser_sidecar.read_text(encoding='utf-8-sig'))
                    merged_chain, merge_audit = merge_browser_audit(
                        mm.get('evidence_chain') or {},
                        browser_snapshot.get('evidence_audit') or {},
                    )
                    mm['evidence_chain'] = merged_chain
                    mm['browser_evidence_merge_audit'] = merge_audit
                except (OSError, ValueError, TypeError) as exc:
                    mm['browser_evidence_merge_audit'] = {
                        'status': 'ERROR', 'reason': str(exc)[:300]
                    }
    if a.dry_run:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    # 3) Append odds movement snapshot (best-effort; fusion_cli does this too,
    #    duplicated here so the pipeline is a single source of truth even if
    #    the caller does not run `collect` separately).
    m = run([CORE_DIR / 'odds_movement.py', 'add', '--source', raw, '--store', a.odds_store])
    try:
        report['movement'] = json.loads(m.stdout)
    except ValueError:
        report['movement'] = {'error': (m.stderr or m.stdout)[:150]}

    # 3.5) 国际盘对照（可选，The Odds API）：设置了 ODDS_API_KEY 才抓取；
    #      失败只记录、不阻断主链路。结果存 odds/intl_production.jsonl。
    if os.environ.get('ODDS_API_KEY'):
        intl_out = a.work_dir / sales_day / f'intl_{a.snapshot}.json'
        ir = run([HERE / 'odds_api_adapter.py', '--match-file', raw,
                  '--out', intl_out,
                  '--store', str(a.odds_store.parent)])
        try:
            report['intl_odds'] = json.loads(ir.stdout)
        except ValueError:
            report['intl_odds'] = {'status': 'error',
                                   'error': (ir.stderr or ir.stdout)[:200]}
    else:
        report['intl_odds'] = {'status': 'skipped',
                               'reason': 'ODDS_API_KEY 未设置，国际盘对照默认不启用'}

    # 3.6) 盘后伤停 + T-75 首发：只写研究库，不并入下面的正式登记 input。
    if a.dry_run:
        report['late_info'] = {'status': 'skipped', 'reason': 'dry-run'}
    else:
        li = run([HERE / 'collect_late_info.py', '--from-collect', raw,
                  '--snapshot', a.snapshot, '--work-dir', d])
        try:
            report['late_info'] = json.loads(li.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError, AttributeError):
            report['late_info'] = {'status': 'error',
                                   'error': (li.stderr or li.stdout)[-200:]}

    # 4) Register each match through the FULL fusion path (fusion_cli record
    #    -> fusion_predict -> core.predict), not the bare core registration.
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

    # 4.5) The research-only route must consume exactly this collection batch.
    # It writes only research.hybrid sidecars and never changes the production
    # probability or its registry entry.
    report['hybrid_shadow'] = run_hybrid_shadow(batch, sales_day, d, a.snapshot)

    report['summary'] = {
        'settled': (report['settle'] or {}).get('settled', 0),
        'collected': (report['collect'] or {}).get('count', 0),
        'recorded': sum(1 for x in report['record'] if x['ok']),
        'duplicate_snapshot': sum(1 for x in report['record'] if x.get('duplicate')),
        'skipped_or_blocked': sum(1 for x in report['record'] if not x['ok'] and not x.get('duplicate')),
        'odds_snapshots_added': (report['movement'] or {}).get('added', 0),
        'hybrid_shadow_ok': (report['hybrid_shadow'] or {}).get('ok', 0),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
