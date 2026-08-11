#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vunknown 批次版本归因审计（2026-08-03）。

背景：8/2 体彩官方历史回填的 1445 条预测因 fusion_record 读取不存在的 engine_version
字段而全部落成 vunknown，无法版本归因。审计依据：
  1) 每条输出 core_engine_version == 3.4.4（与生产核心一致）；
  2) 登记时间在 8/2 22:16（北京时间，fusion 1.4.0 代码就位）之后；
  3) 数据来源为中国体彩官方（oddsHistory / getFixedBonusV1）盘口快照 + 官方赛果。

产出：backtest/version_attribution_audit_2026-08-03.json（sidecar，不改 registry）。
口径：已结算 = results/<match_id>.json 存在 score_90。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BACKTEST = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\shared\football-quant-fusion\backtest"
)
PRED_DIR = BACKTEST / "predictions"
RES_DIR = BACKTEST / "results"
OUT = BACKTEST / "version_attribution_audit_2026-08-03.json"

CORE_OK = "3.4.4"
ROLLOUT_BJ = datetime(2026, 8, 2, 22, 16, tzinfo=ZoneInfo("Asia/Shanghai"))


def created_bj(name: str):
    m = re.search(r"(\d{8})T(\d{6})Z", name)
    if not m:
        return None
    dt_utc = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
    return dt_utc.replace(tzinfo=timezone.utc).astimezone()


def main():
    rows = []
    n_core_ok = n_status_ok = n_after_rollout = n_settled = 0
    by_snapshot = Counter()
    for p in sorted(PRED_DIR.rglob("*.json")):
        if "vunknown" not in p.name:
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        out = r.get("output") or {}
        mid = r.get("match_id")
        core = str(out.get("core_engine_version") or "")
        status = str(out.get("fusion_status") or "")
        cb = created_bj(p.name)
        after = cb is not None and cb >= ROLLOUT_BJ
        settled = False
        rp = RES_DIR / f"{mid}.json"
        if rp.exists():
            try:
                sc = (json.loads(rp.read_text(encoding="utf-8")).get("score_90") or {})
                settled = sc.get("home") is not None and sc.get("away") is not None
            except Exception:
                pass
        n_core_ok += core == CORE_OK
        n_status_ok += status == "ok"
        n_after_rollout += 1 if after else 0
        n_settled += 1 if settled else 0
        by_snapshot[r.get("snapshot_type") or "?"] += 1 if settled else 0
        rows.append({
            "prediction_id": r.get("prediction_id"),
            "match_id": mid,
            "snapshot": r.get("snapshot_type"),
            "core_engine_version": core,
            "fusion_status": status,
            "created_bj": cb.strftime("%Y-%m-%d %H:%M") if cb else None,
            "after_1_4_0_rollout": after,
            "settled": settled,
        })
    audit = {
        "schema": "version-attribution-audit-1.0",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "basis": [
            f"输出字段 core_engine_version=={CORE_OK}",
            f"登记时间 >= {ROLLOUT_BJ:%Y-%m-%d %H:%M} 北京时间（fusion 1.4.0 代码就位）",
            "数据来源为中国体彩官方盘口快照+官方赛果",
            "注：回溯登记（--allow-past），属回填/仿真样本，非实时赛前预登记",
        ],
        "conclusion": ("attributed" if n_core_ok == len(rows) and n_after_rollout == len(rows) else "partial"),
        "counts": {
            "vunknown_total": len(rows),
            "core_3_4_4": n_core_ok,
            "fusion_status_ok": n_status_ok,
            "after_1_4_0_rollout": n_after_rollout,
            "settled": n_settled,
            "settled_by_snapshot": dict(by_snapshot),
        },
        "attributed_version": "fusion-1.4.0-era/core-3.4.4",
        "rows": rows,
    }
    OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit["counts"], ensure_ascii=False, indent=2))
    print("结论:", audit["conclusion"], "| 输出:", OUT)


if __name__ == "__main__":
    main()
