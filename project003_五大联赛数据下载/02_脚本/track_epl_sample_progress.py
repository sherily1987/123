#!/usr/bin/env python3
"""五大联赛回测样本积累进度跟踪（英超 200+ 复审触发器）。

统计逻辑复用引擎 sample_audit.py：--league X --snapshot closing，
返回已结算样本数，对照门槛：
- 100：重校准线
- 200：阈值复审线（英超目标）

用法:
  python track_epl_sample_progress.py
  python track_epl_sample_progress.py --output 05_交付/样本进度.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
SAMPLE_AUDIT = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\sample_audit.py"
)
LEAGUES = ["英超", "西甲", "意甲", "德甲", "法甲"]
GATE_RE = 100
GATE_REVIEW = 200
EPL_WEEKLY = 8  # 竞彩英超约 8 场/周（赛季中）
AH_TEST_TARGET = 1000  # 亚盘复审建议线：test ≥1000（对应可用样本约 3334，70/30 切分）
AH_CSV = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\datasets\big5_odds_full.csv"
)
BACKTEST_STORE = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest"
)


def run_audit(league):
    out = PROJ / "04_素材" / f"_progress_{league}.json"
    p = subprocess.run([sys.executable, str(SAMPLE_AUDIT), "--league", league,
                        "--snapshot", "closing", "--output", str(out)],
                       text=True, capture_output=True)
    if p.returncode != 0:
        return {"settled": 0, "eligible_1x2": 0,
                "error": (p.stderr or p.stdout)[-200:]}
    j = json.loads(p.stdout)
    return {"settled": j.get("settled", 0),
            "eligible_1x2": j.get("eligible_by_market", {}).get("1x2", 0)}


def ah_pool_stats():
    """研究库亚盘样本：Pinnacle 收盘亚盘行数（0.5 步长可用 / 全部 / 2026 赛季）。"""
    stats = {lg: {"ah_all": 0, "ah_half": 0, "ah_2026": 0} for lg in LEAGUES}
    if not AH_CSV.exists():
        return stats
    with io.open(AH_CSV, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            lg = row.get("league")
            if lg not in stats:
                continue
            line = row.get("ah_PinnacleClose_line")
            home = row.get("ah_PinnacleClose_home")
            away = row.get("ah_PinnacleClose_away")
            if line is None or str(line).strip() == "" or home is None or away is None:
                continue
            try:
                lv = float(line)
            except Exception:
                continue
            stats[lg]["ah_all"] += 1
            if abs(lv * 2 - round(lv * 2)) < 1e-9:
                stats[lg]["ah_half"] += 1
            if (row.get("season") or "").startswith("2025-26") or (row.get("match_date") or "").startswith("2025-"):
                stats[lg]["ah_2026"] += 1
    return stats


def fusion_version_stats():
    """融合层登记样本按版本归因统计（prediction_id 解析版本，赛果库判已结算）。

    口径：registry.jsonl 每条 = 一个 (match_id, snapshot_type) 样本（登记时已幂等去重）；
    版本从 prediction_id 的 vfusion-X-core-Y / vunknown 标记解析。
    """
    reg = BACKTEST_STORE / "registry.jsonl"
    res_dir = BACKTEST_STORE / "results"
    counts = {}
    seen = set()
    if not reg.exists():
        return {"by_version": {}, "note": "registry.jsonl 缺失"}
    for line in reg.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        pid = e.get("prediction_id") or ""
        mid = e.get("match_id")
        m = re.search(r"__([a-z0-9_\-]+)$", pid)
        snap = m.group(1) if m else "?"
        vm = re.search(r"vfusion-([0-9-]+)-core-([0-9-]+)", pid)
        if vm:
            ver = f"fusion-{vm.group(1).replace('-', '.')}/core-{vm.group(2).replace('-', '.')}"
        elif "vunknown" in pid:
            ver = "unknown"
        else:
            ver = "unparsed"
        key = (mid, snap)
        if key in seen:
            continue
        seen.add(key)
        c = counts.setdefault(ver, {"total": 0, "settled": 0, "prematch": 0, "prematch_settled": 0})
        c["total"] += 1
        if snap == "prematch":
            c["prematch"] += 1
        rp = res_dir / f"{mid}.json"
        if rp.exists():
            try:
                rs = json.loads(rp.read_text(encoding="utf-8"))
                sc = rs.get("score_90") or {}
                if sc.get("home") is not None and sc.get("away") is not None:
                    c["settled"] += 1
                    if snap == "prematch":
                        c["prematch_settled"] += 1
            except Exception:
                pass
    return {"by_version": counts}


def load_attribution():
    p = BACKTEST_STORE / "version_attribution_audit_2026-08-03.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output")
    a = ap.parse_args()
    rows = {lg: run_audit(lg) for lg in LEAGUES}
    ah = ah_pool_stats()
    fv = fusion_version_stats()
    att = load_attribution()

    print(f"{'联赛':<4} {'已结算':>6} {'1x2可用':>8} {'100线':>6} {'200线':>6}  状态")
    for lg in LEAGUES:
        s = rows[lg]["settled"]
        state = ("✔ 超200，可阈值复审" if s >= GATE_REVIEW
                 else "✔ 超100，可重校准" if s >= GATE_RE else "积累中")
        print(f"{lg:<4} {s:>6} {rows[lg]['eligible_1x2']:>8} {GATE_RE:>6} {GATE_REVIEW:>6}  {state}")

    print("\n亚盘研究库样本（Pinnacle 收盘，big5_odds_full.csv）：")
    print(f"{'联赛':<4} {'全部亚盘':>8} {'0.5步长可用':>10} {'2025-26':>8}  复审线(3334可用)")
    for lg in LEAGUES:
        ahx = ah[lg]
        need = max(0, int(AH_TEST_TARGET / 0.3) - ahx["ah_half"])
        print(f"{lg:<4} {ahx['ah_all']:>8} {ahx['ah_half']:>10} {ahx['ah_2026']:>8}  还差约 {need}")

    print("\n融合层版本样本（已结算，按 prediction_id 归因）：")
    for ver, c in sorted(fv["by_version"].items(), key=lambda kv: -kv[1]["settled"]):
        print(f"{ver:<28} 总数={c['total']:>5} 已结算={c['settled']:>5} prematch={c['prematch']:>4} "
              f"prematch已结算={c['prematch_settled']:>4}")
    v140 = fv["by_version"].get("fusion-1.4.0/core-3.4.4")
    if v140:
        s = v140["settled"]
        print(f"\n1.4.0 已结算 {s} 场：距 100 线还差 {max(0, GATE_RE - s)}，距 200 线还差 {max(0, GATE_REVIEW - s)}")
    else:
        print("\n1.4.0 版本尚无已结算样本（新赛季流水线登记 prematch 快照后开始积累）")

    if att:
        c = att.get("counts", {})
        print(f"\n版本归因审计（2026-08-03）：vunknown 批次 {c.get('vunknown_total')} 条全部 core 3.4.4、"
              f"1.4.0 代码就位后登记；已结算 {c.get('settled')} 条 -> 可归因 fusion-1.4.0-era/core-3.4.4")
        settled = c.get("settled", 0)
        print(f"归因后已结算 {settled} 场：距 100 线差 {max(0, GATE_RE - settled)}，"
              f"距 200 线差 {max(0, GATE_REVIEW - settled)}（已超 200，可启动阈值复审）"
              if settled >= GATE_REVIEW else
              f"归因后已结算 {settled} 场：距 100 线差 {max(0, GATE_RE - settled)}，"
              f"距 200 线差 {max(0, GATE_REVIEW - settled)}")

    epl = rows["英超"]["settled"]
    remain = max(0, GATE_REVIEW - epl)
    if epl < GATE_REVIEW:
        weeks = remain / EPL_WEEKLY
        note = (f"英超还差 {remain} 场（按赛季中约 {EPL_WEEKLY} 场/周估算，约 {weeks:.1f} 周；"
                f"当前为休赛期，新赛季 8 月中旬开赛后开始积累）")
    else:
        note = "英超已达 200+，可以启动时间序列切分校准复审"
    print("\n" + note)

    report = {
        "schema": "sample-progress-1.0", "snapshot": "closing",
        "gates": {"recalibration": GATE_RE, "threshold_review": GATE_REVIEW},
        "ah_review": {"note": "亚盘复审建议线 test≥1000（0.5 步长可用样本约 3334，70/30 切分）",
                      "target_half_step": int(AH_TEST_TARGET / 0.3)},
        "as_of": datetime.now(timezone.utc).isoformat(),
        "leagues": rows,
        "ah_pool": ah,
        "fusion_layer": {
            "note": "版本从 prediction_id 解析；已结算=results 库存在 score_90；100/200 为重校准/复审线",
            "gates": {"recalibration": GATE_RE, "threshold_review": GATE_REVIEW},
            "by_version": fv["by_version"],
            "version_1_4_0": v140,
            "attribution_audit": att,
        },
        "epl": {"settled": epl, "remaining_to_200": remain, "note": note},
    }
    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("已写入:", a.output)


if __name__ == "__main__":
    main()
