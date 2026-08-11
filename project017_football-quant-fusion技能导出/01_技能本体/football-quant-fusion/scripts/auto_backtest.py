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
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
FUSION_CLI = HERE / "fusion_cli.py"
DUAL_TRACK = HERE / "backtest_dual_track.py"
DEFAULT_STORE = Path(
    r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/backtest"
)


def run(cmd, timeout=900):
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return {"ok": proc.returncode == 0, "rc": proc.returncode,
                "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": "TIMEOUT", "stdout": "", "stderr": f"timeout>{timeout}s"}


def discover_record_dirs(workspace):
    """扫描 <workspace>/project*/04_素材/待回测记录/*/ 中含 index.json 的日期目录。"""
    found = []
    for proj in sorted(Path(workspace).glob("project*")):
        if not proj.is_dir():
            continue
        base = proj / "04_素材" / "待回测记录"
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            if d.is_dir() and (d / "index.json").exists():
                found.append(d)
    return found


def main():
    ap = argparse.ArgumentParser(description="自动回测所有已预测比赛")
    ap.add_argument("--workspace", default=r"H:\claude AI自媒体", help="扫描各项目待回测目录的工作区根")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--output-dir", default=None, help="合并报告输出目录（默认 <cwd>/05_交付/auto_backtest）")
    ap.add_argument("--skip-settle", action="store_true", help="跳过共享库赛果回填")
    ap.add_argument("--skip-store-backtest", action="store_true", help="跳过共享库量化回测")
    a = ap.parse_args()

    now = datetime.datetime.now().astimezone()
    out_dir = Path(a.output_dir) if a.output_dir else Path.cwd() / "05_交付" / "auto_backtest"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%d")
    report = {
        "schema": "auto-backtest-1.0",
        "ran_at": now.isoformat(),
        "workspace": a.workspace,
        "store": a.store,
        "settle": None,
        "store_backtest": None,
        "dual_track_dates": [],
        "summary": {},
    }

    # 1) 共享库赛果回填
    if not a.skip_settle:
        r = run([sys.executable, str(FUSION_CLI), "settle", "--store", a.store])
        try:
            report["settle"] = json.loads(r["stdout"])
        except Exception:
            report["settle"] = {"error": (r["stderr"] or r["stdout"])[:400], "ok": r["ok"]}
        print(f"[settle] ok={r['ok']} -> {str(report['settle'])[:200]}")

    # 2) 共享库量化回测
    if not a.skip_store_backtest:
        out_sb = out_dir / f"store_backtest_{stamp}.json"
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
    for d in dirs:
        date = d.name
        proj = d.parents[2]
        out_json = proj / "05_交付" / f"backtest_dual_track_{date}.json"
        out_md = proj / "05_交付" / f"backtest_dual_track_{date}.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        r = run([sys.executable, str(DUAL_TRACK), "--records-dir", str(d),
                 "--output", str(out_json), "--report", str(out_md)])
        entry = {"date": date, "dir": str(d), "ok": r["ok"], "output": str(out_json)}
        try:
            j = json.loads(out_json.read_text(encoding="utf-8"))
            entry["summary"] = j.get("summary", {})
        except Exception:
            entry["summary"] = {"error": (r["stderr"] or r["stdout"])[:300]}
        report["dual_track_dates"].append(entry)
        print(f"[dual-track {date}] ok={r['ok']} {str(entry['summary'])[:160]}")

    # 4) 合并报告
    dates = report["dual_track_dates"]
    settled = sum((d.get("summary", {}).get("settled") or 0) for d in dates)
    q_hit = sum((d.get("summary", {}).get("quant_1x2", {}).get("hit") or 0) for d in dates)
    q_n = sum((d.get("summary", {}).get("quant_1x2", {}).get("n") or 0) for d in dates)
    llm_hit = sum((d.get("summary", {}).get("llm_double", {}).get("hit") or 0) for d in dates)
    llm_n = sum((d.get("summary", {}).get("llm_double", {}).get("n") or 0) for d in dates)
    report["summary"] = {
        "record_dirs_found": len(dirs),
        "settled_total": settled,
        "quant_1x2_total": {"n": q_n, "hit": q_hit, "hit_rate_pct": round(100 * q_hit / q_n, 2) if q_n else None},
        "llm_double_total": {"n": llm_n, "hit": llm_hit, "hit_rate_pct": round(100 * llm_hit / llm_n, 2) if llm_n else None},
        "caveat": "样本少时命中率不具结论性；SKILL 纪律：>=100 场评估、>=200 场做结论。",
    }
    out_json = out_dir / f"auto_backtest_report_{stamp}.json"
    out_md = out_dir / f"auto_backtest_report_{stamp}.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 自动回测报告（{stamp}）",
        "",
        f"- 运行时间：{report['ran_at']}",
        f"- 工作区：{a.workspace}",
        f"- 共享库 settle：{json.dumps(report['settle'], ensure_ascii=False)[:200] if report['settle'] else '跳过'}",
        f"- 共享库量化回测：{'成功' if (report.get('store_backtest') or {}).get('ok') else '失败/跳过'}",
        "",
        "## 双轨（待回测记录）汇总",
        "",
        f"- 已结算：{report['summary']['settled_total']} 场",
        f"- 量化 1X2：{report['summary']['quant_1x2_total']['hit']}/{report['summary']['quant_1x2_total']['n']}"
        f"（{report['summary']['quant_1x2_total']['hit_rate_pct']}%）",
        f"- LLM 双选：{report['summary']['llm_double_total']['hit']}/{report['summary']['llm_double_total']['n']}"
        f"（{report['summary']['llm_double_total']['hit_rate_pct']}%）",
        "",
        "## 各日期明细",
        "",
        "| 日期 | 已结算 | 量化1X2 | LLM双选 | 报告 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for d in dates:
        s = d.get("summary", {})
        q = s.get("quant_1x2", {})
        l = s.get("llm_double", {})
        lines.append(
            f"| {d['date']} | {s.get('settled','-')} | "
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
    print(f"\n合并报告：{out_md}")
    print(f"JSON：{out_json}")


if __name__ == "__main__":
    main()
