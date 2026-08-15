#!/usr/bin/env python3
"""重放旧版本样本，判定它与当前概率代码是否**数值等价**。

为什么需要这个脚本
------------------
`probability_signature` 是概率文件的**字节哈希**。只要 `production_router.py` 之类的
文件动了一个字节，签名就变，`audit_version_consistency.py` 就会要求 bump `model_version`，
于是样本累积清零——这正是 `40_模型/模型版本管理_打破current死锁.md` 声称要打破的死锁，
只是范围从「全部源文件」缩小到了「概率文件名单」，机制本身没变。

2026-08-15 实测踩到一次：m1→m2 的 bump 由影子路由与签名拆分触发，生产 market_only
路由的概率**一位没变**，却让 34 场在途样本落进一个不会再增长的队列。

本脚本提供字节哈希给不出的那个答案：**概率到底变没变**。做法是取旧样本登记时保存的
`input`，用当前代码重跑，与登记的 `output.final_1x2_pct` 逐场比对。

判定与用法
----------
- `equivalent`：全部场次概率完全一致 → 该旧版本的样本可以在 manifest 里登记为
  `model_version_aliases`，并入当前 cohort，不必从零累积；
- `changed`：存在差异 → 旧样本不得并入，必须重新累积（与 1466 场 legacy 同样处理）。

**等价判定只覆盖被重放的路由与市场**。只跑了 market_only 就只能对 market_only 下结论，
不能外推到 hybrid 或其他衍生市场；报告里的 `replayed_modes` 就是这个边界。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from fusion_backtest import load_jsonl, resolve_path
from runtime import resolve_python
from runtime_paths import backtest_store

HERE = Path(__file__).resolve().parent
PY = resolve_python()
COMPARE_FIELDS = ("final_1x2_pct", "model_1x2_pct")


def replay_one(record: dict) -> dict:
    """重跑单条记录的 input，返回比对结果。"""
    match_id = record.get("match_id")
    recorded = record.get("output") or {}
    payload = record.get("input")
    if not payload:
        return {"match_id": match_id, "status": "no_input"}

    with tempfile.TemporaryDirectory() as tmp:
        in_path = Path(tmp) / "input.json"
        out_path = Path(tmp) / "output.json"
        in_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([PY, str(HERE / "fusion_predict.py"), str(in_path),
                               "--output", str(out_path)],
                              text=True, capture_output=True)
        if proc.returncode != 0 or not out_path.exists():
            return {"match_id": match_id, "status": "replay_failed",
                    "detail": (proc.stderr or proc.stdout or "").strip()[:300]}
        fresh = json.loads(out_path.read_text(encoding="utf-8"))

    core = fresh.get("core_output") or fresh
    diffs = {}
    for field in COMPARE_FIELDS:
        before, after = recorded.get(field), core.get(field)
        if before is None and after is None:
            continue
        if before != after:
            diffs[field] = {"recorded": before, "replayed": after}
    return {
        "match_id": match_id,
        "status": "differs" if diffs else "identical",
        "mode": record.get("mode") or payload.get("mode"),
        "diffs": diffs,
    }


def build_report(root: Path, model_version: str, limit: int = 0) -> dict:
    records = []
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str((rec.get("model") or {}).get("model_version") or "") == model_version:
            records.append(rec)
    if limit:
        records = records[:limit]

    results = [replay_one(rec) for rec in records]
    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    modes = sorted({str(r.get("mode")) for r in results if r.get("mode")})

    identical = counts.get("identical", 0)
    verdict = ("equivalent" if identical == len(results) and results
               else "changed" if counts.get("differs") else "inconclusive")
    return {
        "schema_version": "fusion-probability-replay-1.0",
        "replayed_model_version": model_version,
        "replayed_n": len(results),
        "replayed_modes": modes,
        "counts": counts,
        "verdict": verdict,
        "verdict_note": {
            "equivalent": "全部重放场次概率一致；可在 manifest 登记 model_version_aliases 并入当前 cohort。",
            "changed": "存在概率差异；旧样本不得并入当前 cohort，必须重新累积。",
            "inconclusive": "没有可重放的样本或重放失败，无法判定。",
        }[verdict],
        "scope_warning": "等价结论仅覆盖 replayed_modes 列出的路由，不可外推到其他路由或衍生市场。",
        "results": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="重放旧版本样本判定概率等价性")
    ap.add_argument("--store", default=str(backtest_store()))
    ap.add_argument("--model-version", required=True, help="要重放的旧 model_version，如 m1")
    ap.add_argument("--limit", type=int, default=0, help="只重放前 N 条（0=全部）")
    ap.add_argument("--output", help="写出 JSON 报告")
    a = ap.parse_args()

    report = build_report(Path(a.store), a.model_version, a.limit)
    print(f"重放 {report['replayed_model_version']}：{report['replayed_n']} 场"
          f"（路由 {','.join(report['replayed_modes']) or '?'}）")
    for status, n in sorted(report["counts"].items()):
        print(f"  {status}: {n}")
    print(f"判定：{report['verdict']} — {report['verdict_note']}")
    print(report["scope_warning"])
    for item in report["results"]:
        if item["status"] == "differs":
            print(f"  差异 {item['match_id']}: {json.dumps(item['diffs'], ensure_ascii=False)}")
        elif item["status"] not in ("identical",):
            print(f"  {item['status']} {item['match_id']}: {item.get('detail', '')}")

    if a.output:
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["verdict"] != "inconclusive" else 1


if __name__ == "__main__":
    raise SystemExit(main())
