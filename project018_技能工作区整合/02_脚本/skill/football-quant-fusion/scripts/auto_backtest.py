#!/usr/bin/env python3
"""自动回测所有已预测比赛（手动关键词：回测已经预测的比赛 / 自动计划任务）。

覆盖两条数据源：
1. 共享库（fusion_record 登记的预测，`shared/football-quant-fusion/backtest/`）：
   - 先 settle 回填官方赛果（幂等）；
   - 再跑 fusion_backtest 统计共享库量化记录。
2. 各项目 `04_素材/待回测记录/<date>/`（双轨登记，含 index.json + index_llm.json）：
   - 逐日期跑 `backtest_dual_track.py`，量化 1X2/比分 vs LLM 双选/单选/比分；
   - 每日期 JSON/MD 写到所属项目的 `05_交付/`。

最后输出合并报告（汇总 settle / 共享库 / 各日期双轨命中率）。

用法:
  python auto_backtest.py --workspace "H:\\claude AI自媒体" --output-dir <项目>/05_交付/auto_backtest
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from runtime_paths import data_root, workspace_root

SKILL = HERE.parent
FUSION_CLI = HERE / "fusion_cli.py"
DUAL_TRACK = HERE / "backtest_dual_track.py"
DEFAULT_STORE = data_root() / "backtest"


def run(cmd, timeout=900):
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {"ok": proc.returncode == 0, "rc": proc.returncode,
                "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": "TIMEOUT", "stdout": "", "stderr": f"timeout>{timeout}s"}


def discover_record_dirs(workspace):
    """发现工作区内包含双轨索引的 ``待回测记录/<date>`` 目录。

    兼容既有 ``project*/04_素材/待回测记录`` 与销售日目录直接存放
    ``待回测记录`` 的结构，避免后者被自动回测静默跳过。
    """
    root = Path(workspace)
    found = []
    seen = set()
    for base in root.rglob("待回测记录"):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or not (d / "index.json").exists():
                continue
            key = str(d.resolve())
            if key not in seen:
                found.append(d)
                seen.add(key)
    return sorted(found)


def project_root_for_record_dir(records_dir):
    """返回双轨报告的所属项目目录，兼容两种待回测目录布局。"""
    material_dir = records_dir.parent.parent
    if material_dir.name == "04_素材":
        return material_dir.parent
    return material_dir


def create_archive_paths(output_dir, timestamp):
    """Reserve a non-overwrite archive run and return its fixed latest entry."""
    output_dir = Path(output_dir)
    run_dir = output_dir / "archive" / timestamp
    if run_dir.exists():
        raise FileExistsError(f"archive run already exists: {run_dir}")
    return {"run_dir": run_dir, "latest_dir": output_dir / "latest"}


def publish_latest(run_dir, latest_dir):
    """Refresh the stable latest entry from an immutable completed archive run."""
    latest_dir = Path(latest_dir)
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(run_dir, latest_dir)


def dual_track_archive_paths(run_dir, records_dir):
    """Give each discovered records directory a collision-free report name."""
    records_dir = Path(records_dir)
    token = hashlib.sha256(str(records_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    stem = f"backtest_dual_track_{records_dir.name}_{token}"
    base = Path(run_dir) / "dual_track"
    return {"json": base / f"{stem}.json", "markdown": base / f"{stem}.md"}


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _parse_time(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None


def select_primary_records(candidates):
    """Select one latest pre-kickoff prediction per match for primary evaluation."""
    eligible, dropped = [], []
    for candidate in candidates:
        predicted = _parse_time(candidate.get("prediction_as_of"))
        kickoff = _parse_time(candidate.get("kickoff"))
        if predicted is None:
            dropped.append({**candidate, "reason": "missing_prediction_as_of"})
        elif kickoff is None:
            dropped.append({**candidate, "reason": "missing_kickoff"})
        elif predicted >= kickoff:
            dropped.append({**candidate, "reason": "post_kickoff_prediction"})
        else:
            eligible.append(candidate)
    selected = []
    for match_id in sorted({c["match_id"] for c in eligible}):
        group = [c for c in eligible if c["match_id"] == match_id]
        winner = max(group, key=lambda c: _parse_time(c["prediction_as_of"]))
        selected.append(winner)
        dropped.extend({**c, "reason": "superseded_by_newer_prediction"} for c in group if c is not winner)
    return selected, dropped


def build_provenance(record_dirs, results_dir, match_ids):
    """Hash every consumed index, executable script, and match result artifact."""
    indexes = {}
    for records_dir in record_dirs:
        for name in ("index.json", "index_llm.json"):
            path = Path(records_dir) / name
            if path.exists():
                indexes[str(path)] = sha256_file(path)
    result_hashes = {}
    for match_id in sorted(set(match_ids)):
        path = Path(results_dir) / f"{match_id}.json"
        if path.exists():
            result_hashes[match_id] = sha256_file(path)
    return {"input_indexes": indexes,
            "scripts": {"auto_backtest.py": sha256_file(Path(__file__)),
                        "backtest_dual_track.py": sha256_file(DUAL_TRACK)},
            "result_hashes": result_hashes}


def aggregate_dual_track_summaries(summaries):
    """Aggregate formal scoring only; cross-validation remains a separately visible count."""
    official_settled = sum((s.get("settlement_provenance", {}).get("official_formal") or 0) for s in summaries)
    cross_validation = sum((s.get("settlement_provenance", {}).get("cross_validation") or 0) for s in summaries)
    q_hit = sum((s.get("quant_1x2", {}).get("hit") or 0) for s in summaries)
    q_n = sum((s.get("quant_1x2", {}).get("n") or 0) for s in summaries)
    llm_hit = sum((s.get("llm_double", {}).get("hit") or 0) for s in summaries)
    llm_n = sum((s.get("llm_double", {}).get("n") or 0) for s in summaries)
    return {
        "official_settled_total": official_settled,
        "cross_validation_total": cross_validation,
        "quant_1x2_total": {"n": q_n, "hit": q_hit, "hit_rate_pct": round(100 * q_hit / q_n, 2) if q_n else None},
        "llm_double_total": {"n": llm_n, "hit": llm_hit, "hit_rate_pct": round(100 * llm_hit / llm_n, 2) if llm_n else None},
    }


def main():
    ap = argparse.ArgumentParser(description="自动回测所有已预测比赛")
    ap.add_argument("--workspace", default=str(workspace_root()), help="扫描各项目待回测目录的工作区根")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--output-dir", default=None, help="合并报告输出目录（默认 <cwd>/05_交付/auto_backtest）")
    ap.add_argument("--settle", action="store_true", help="Explicitly permit shared-store result settlement (default: never settle).")
    ap.add_argument("--apifootball-fallback", action="store_true",
                    help="When --settle is enabled, use APIFootball for unresolved UCL results.")
    ap.add_argument("--skip-settle", action="store_true", help="Deprecated compatibility flag; settle is already off by default.")
    ap.add_argument("--skip-store-backtest", action="store_true", help="跳过共享库量化回测")
    a = ap.parse_args()

    now = datetime.datetime.now().astimezone()
    out_dir = Path(a.output_dir) if a.output_dir else Path.cwd() / "05_交付" / "auto_backtest"
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    archive = create_archive_paths(out_dir, timestamp)
    run_dir = archive["run_dir"]
    run_dir.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "auto-backtest-1.1",
        "ran_at": now.isoformat(),
        "run_id": timestamp,
        "archive_dir": str(run_dir),
        "latest_entry": str(archive["latest_dir"]),
        "workspace": a.workspace,
        "store": a.store,
        "settle": None,
        "store_backtest": None,
        "dual_track_dates": [],
        "summary": {},
    }

    # 1) 共享库赛果回填
    if a.settle and not a.skip_settle:
        settle_cmd = [sys.executable, str(FUSION_CLI), "settle", "--store", a.store]
        if a.apifootball_fallback:
            settle_cmd.append("--apifootball-fallback")
        r = run(settle_cmd)
        try:
            report["settle"] = json.loads(r["stdout"])
        except Exception:
            report["settle"] = {"error": (r["stderr"] or r["stdout"])[:400], "ok": r["ok"]}
        print(f"[settle] ok={r['ok']} -> {str(report['settle'])[:200]}")
    else:
        report["settle"] = {"status": "not_requested"}

    # 2) 共享库量化回测
    if not a.skip_store_backtest:
        out_sb = run_dir / "store_backtest.json"
        r = run([sys.executable, str(FUSION_CLI), "backtest", "--store", a.store, "--output", str(out_sb)])
        report["store_backtest"] = {
            "ok": r["ok"],
            "rc": r["rc"],
            "output": str(out_sb),
            "tail": (r["stdout"] or r["stderr"])[-1500:],
        }
        print(f"[store_backtest] ok={r['ok']}")

    # 3) 各项目待回测目录双轨回测
    dirs = discover_record_dirs(a.workspace)
    candidates = []
    for d in dirs:
        index = json.loads((d / "index.json").read_text(encoding="utf-8"))
        for record in index.get("records", []):
            candidates.append({
                "match_id": record.get("match_id"),
                "prediction_as_of": record.get("prediction_as_of"),
                "kickoff": record.get("kickoff") or (record.get("match") or {}).get("kickoff"),
                "dir": str(d),
            })
    primary, dropped_primary = select_primary_records([c for c in candidates if c["match_id"]])
    selected_by_dir = {}
    for row in primary:
        selected_by_dir.setdefault(row["dir"], []).append(row["match_id"])
    report["primary_selection"] = {"selected": primary, "dropped": dropped_primary}
    for d in dirs:
        selected_ids = selected_by_dir.get(str(d), [])
        if not selected_ids:
            continue
        date = d.name
        dual_paths = dual_track_archive_paths(run_dir, d)
        out_json = dual_paths["json"]
        out_md = dual_paths["markdown"]
        out_json.parent.mkdir(parents=True, exist_ok=True)
        r = run([sys.executable, str(DUAL_TRACK), "--records-dir", str(d),
                 "--output", str(out_json), "--report", str(out_md),
                 *sum((["--match-id", mid] for mid in selected_ids), [])])
        entry = {"date": date, "dir": str(d), "match_ids": selected_ids, "ok": r["ok"], "output": str(out_json)}
        try:
            j = json.loads(out_json.read_text(encoding="utf-8"))
            entry["summary"] = j.get("summary", {})
        except Exception:
            entry["summary"] = {"error": (r["stderr"] or r["stdout"])[:300]}
        report["dual_track_dates"].append(entry)
        print(f"[dual-track {date}] ok={r['ok']} {str(entry['summary'])[:160]}")

    # 4) 合并报告
    dates = report["dual_track_dates"]
    dual_summary = aggregate_dual_track_summaries([d.get("summary", {}) for d in dates])
    report["summary"] = {
        "record_dirs_found": len(dirs),
        **dual_summary,
        "caveat": "样本少时命中率不具结论性；SKILL 纪律：>=100 场评估、>=200 场做结论。",
    }
    report["provenance"] = build_provenance(dirs, Path(a.store) / "results", [row["match_id"] for row in primary])
    out_json = run_dir / "auto_backtest_report.json"
    out_md = run_dir / "auto_backtest_report.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 自动回测报告（{timestamp}）",
        "",
        f"- 运行时间：{report['ran_at']}",
        f"- 工作区：{a.workspace}",
        f"- 共享库 settle：{json.dumps(report['settle'], ensure_ascii=False)[:200] if report['settle'] else '跳过'}",
        f"- 共享库量化回测：{'成功' if (report.get('store_backtest') or {}).get('ok') else '失败/跳过'}",
        "",
        "## 双轨（待回测记录）汇总",
        "",
        f"- 正式结算：{report['summary']['official_settled_total']} 场（仅计入正式分母）",
        f"- 交叉验证（不计正式分母）：{report['summary']['cross_validation_total']} 场",
        f"- 量化 1X2：{report['summary']['quant_1x2_total']['hit']}/{report['summary']['quant_1x2_total']['n']}"
        f"（{report['summary']['quant_1x2_total']['hit_rate_pct']}%）",
        f"- LLM 双选：{report['summary']['llm_double_total']['hit']}/{report['summary']['llm_double_total']['n']}"
        f"（{report['summary']['llm_double_total']['hit_rate_pct']}%）",
        "",
        "## 各日期明细",
        "",
        "| 日期 | 正式结算 | 交叉验证 | 量化1X2 | LLM双选 | 报告 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in dates:
        s = d.get("summary", {})
        q = s.get("quant_1x2", {})
        l = s.get("llm_double", {})
        lines.append(
            f"| {d['date']} | {s.get('settlement_provenance', {}).get('official_formal','-')} | "
            f"{s.get('settlement_provenance', {}).get('cross_validation','-')} | "
            f"{q.get('hit','-')}/{q.get('n','-')}（{q.get('hit_rate_pct','-')}%） | "
            f"{l.get('hit','-')}/{l.get('n','-')}（{l.get('hit_rate_pct','-')}%） | {d['output']} |"
        )
    lines.append("")
    lines.append("## 结论边界")
    lines.append("")
    lines.append(report["summary"]["caveat"])
    lines.append("")
    lines.append("完整数据见同目录 JSON；共享库量化回测明细见 store_backtest_*.json。")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    metadata_path = run_dir / "run_metadata.json"
    metadata_path.write_text(json.dumps({
        "schema": "auto-backtest-run-metadata-1.0",
        "run_id": timestamp,
        "ran_at": report["ran_at"],
        "argv": sys.argv,
        "workspace": a.workspace,
        "store": a.store,
        "archive_dir": str(run_dir),
        "latest_entry": str(archive["latest_dir"]),
        "provenance": report["provenance"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    publish_latest(run_dir, archive["latest_dir"])
    print(f"\n合并报告：{out_md}")
    print(f"JSON：{out_json}")
    print(f"归档：{run_dir}")
    print(f"固定入口：{archive['latest_dir']}")


if __name__ == "__main__":
    main()
