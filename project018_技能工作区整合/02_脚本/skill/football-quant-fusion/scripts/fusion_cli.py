#!/usr/bin/env python3
"""football-quant-fusion command router.

REBUILT 2026-08-02：原文件在文件系统同步事故中损坏，本文件基于
SKILL.md 1.4.0 命令表、会话中读取的 record_fusion 逻辑与已恢复脚本重建。
子命令依赖的脚本如缺失会返回明确错误，不静默吞错。
"""
import json
import subprocess
import sys
from pathlib import Path

from runtime import resolve_python
from runtime_paths import core_scripts_dir, data_root

# 统一解释器：当前为 3.14 等非 3.12 时，所有子进程改用内置 Python 3.12
PY = resolve_python()

HERE = Path(__file__).resolve().parent
FUSION_VERSION = "1.4.0"
STORE = data_root() / "backtest"

# 子命令 → 负责脚本（相对本目录；缺失时给出恢复提示）
MAP = {
    "collect": "sales_day_collect.py",
    "sales-day-collect": "sales_day_collect.py",
    "kickoff-date-collect": "sales_day_collect.py",
    "record": "fusion_record.py",
    "daily-pipeline": "fusion_daily_pipeline.py",
}

HELP = """\
Supported commands:
  collect | sales-day-collect | kickoff-date-collect
  record | daily-pipeline | preview | merge-preview | settle | backtest
  odds-add | odds-drift | odds-intl | tournament
  football-data-enrich | market-ablation | collect-date
"""


# [中文功能] 从命令行参数中提取指定flag的值
def option_value(rest, flag):
    if flag not in rest:
        return None
    j = rest.index(flag)
    if j + 1 < len(rest) and not rest[j + 1].startswith('-'):
        return rest[j + 1]
    return None


# [中文功能] 以子进程运行脚本并转发其输出
def run_script(script, rest):
    p = HERE / script
    if not p.exists():
        raise SystemExit(f'脚本缺失（事故损坏待恢复）：{p}\n可用 zu-yu-dashi-3 对应脚本替代或联系重建。')
    proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


# [中文功能] 可选项：把采集结果写入赔率移动库
def maybe_odds_add(odds_source):
    if not odds_source:
        return None
    try:
        proc = subprocess.run(
            [PY, str(HERE / 'fusion_cli.py'), 'odds-add', '--source', odds_source],
            text=True, capture_output=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except Exception as exc:
        return {'status': 'error', 'note': str(exc)}
    return None


# [中文功能] 融合登记主流程（预测→包裹→注册回测库）
def record_fusion(rest):
    input_path = option_value(rest, "--input")
    output_path = option_value(rest, "--output")
    odds_source = option_value(rest, "--odds-source")
    if not input_path or not output_path:
        raise SystemExit("record requires --input and --output")
    odds_report = maybe_odds_add(odds_source) if odds_source else None
    fusion_output = Path(output_path)
    proc = subprocess.run(
        [PY, str(HERE / "fusion_predict.py"), input_path, "--output", str(fusion_output)],
        text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout)
    wrapped = json.loads(fusion_output.read_text(encoding="utf-8"))
    if wrapped.get("fusion_status") != "ok":
        raise SystemExit("fusion prediction blocked; refuse registration")
    # 保留完整 fusion payload，同时保持 core 兼容概率字段在顶层
    core = dict(wrapped.get("core_output") or {})
    core["engine_version"] = f"fusion-{FUSION_VERSION}+core-{wrapped.get('core_engine_version', 'unknown')}"
    core["core_engine_version"] = wrapped.get("core_engine_version")
    core["fusion_schema_version"] = wrapped.get("fusion_schema_version")
    core["version_manifest"] = wrapped.get("version_manifest")
    core["fusion_status"] = wrapped.get("fusion_status")
    core["fusion_decision"] = wrapped.get("fusion_decision")
    core["adjustment_ledger_audit"] = wrapped.get("adjustment_ledger_audit")
    core["goal_rate"] = wrapped.get("goal_rate") or (wrapped.get("forecast") or {}).get("goal_rate")
    core["source_evidence"] = wrapped.get("source_evidence")
    core["field_meta"] = wrapped.get("field_meta")
    core["data_quality"] = wrapped.get("data_quality")
    core["market_dependency_pct"] = wrapped.get("market_dependency_pct", core.get("market_dependency_pct"))
    core["reliability_flags"] = wrapped.get("reliability_flags", core.get("reliability_flags"))
    core["forecast"] = wrapped.get("forecast")
    core["market_freshness"] = wrapped.get("market_freshness") or (wrapped.get("core_output") or {}).get("market_freshness")
    core["recommendation_gate"] = wrapped.get("recommendation_gate") or (wrapped.get("core_output") or {}).get("recommendation_gate")
    core["data_usage_audit"] = wrapped.get("data_usage_audit") or (wrapped.get("core_output") or {}).get("data_usage_audit")
    core["fusion_full_output"] = wrapped
    if odds_report is not None:
        core["odds_movement_capture"] = odds_report
    core_path = fusion_output.with_suffix(fusion_output.suffix + ".registry-core.json")
    core_path.write_text(json.dumps(core, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    delegated = list(rest)
    if "--predict" in delegated:
        delegated.remove("--predict")
    if "--odds-source" in delegated:
        j = delegated.index("--odds-source")
        del delegated[j:j + 2 if j + 1 < len(delegated) and not delegated[j + 1].startswith("-") else j + 1]
    i = delegated.index("--output")
    delegated[i + 1] = str(core_path)
    if "--store" not in delegated:
        delegated += ["--store", str(STORE)]
    proc = subprocess.run([PY, str(HERE / "fusion_record.py"), *delegated], text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout)
    record = json.loads(proc.stdout)
    record["odds_movement_capture"] = odds_report
    print(json.dumps(record, ensure_ascii=False, indent=2))


# [中文功能] CLI子命令路由入口
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    if sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        print(HELP)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd in ("collect", "sales-day-collect", "kickoff-date-collect"):
        script = MAP[cmd]
        p = HERE / script
        if not p.exists():
            raise SystemExit(f'脚本缺失：{p}')
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            raise SystemExit(proc.returncode)
        # collect 输出 JSON；若有 --emit-input 且后续想登记，可继续 record
        return
    if cmd == "record":
        record_fusion(rest)
        return
    if cmd == "daily-pipeline":
        run_script("fusion_daily_pipeline.py", rest)
        return
    if cmd == "odds-intl":
        # 国际盘对照（可选，The Odds API）：仅 CLV/edge 研究，不参与概率建模。
        # 用法：fusion_cli.py odds-intl --match-file raw.json --out intl_snapshot.json [--dry-run]
        run_script("odds_api_adapter.py", rest)
        return
    if cmd == "tournament":
        # 赛事级 Monte Carlo（新版欧冠 36 队赛制，2026-08-04 收编自 project005）
        # 用法：fusion_cli.py tournament --iterations 100000 --seed YYYYMMDD \
        #   [--teams teams.json --strength strength.json --output out.json]
        run_script("ucl_tournament_mc.py", rest)
        return
    if cmd in ("preview",):
        # 委托 zu-yu-dashi-3 官方前瞻采集
        p = core_scripts_dir() / "fetch_match_preview.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    if cmd in ("merge-preview",):
        p = core_scripts_dir() / "merge_preview.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    if cmd == "settle":
        p = core_scripts_dir() / "settle_from_sporttery.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    if cmd == "backtest":
        # fusion 全参数回测：委托融合回测脚本（缺失时回退 zu-yu-dashi-3 回测并说明）
        fb = HERE / "fusion_backtest.py"
        if fb.exists():
            proc = subprocess.run([PY, str(fb), *rest], text=True, capture_output=True)
            sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
            raise SystemExit(proc.returncode)
        p = core_scripts_dir() / "backtest.py"
        print('提示：fusion_backtest.py 缺失（事故损坏），回退核心引擎回测', file=sys.stderr)
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    if cmd in ("odds-add", "odds-drift"):
        p = core_scripts_dir() / "odds_movement.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        sub_cmd = 'add' if cmd == 'odds-add' else 'drift'
        proc = subprocess.run([PY, str(p), sub_cmd, *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    if cmd in ("football-data-enrich", "market-ablation", "collect-date"):
        script = {"football-data-enrich": "football_data_enrich.py",
                  "market-ablation": "market_ablation.py",
                  "collect-date": "sales_day_collect.py"}[cmd]
        p = HERE / script
        if not p.exists():
            raise SystemExit(f'脚本缺失（事故损坏待恢复）：{p}\n'
                             f'{cmd} 功能暂不可用（脚本损坏待恢复）。'
                             + (' football-data-enrich 可先用 zu-yu-dashi-3 官方前瞻替代。' if cmd == 'football-data-enrich' else ''))
        proc = subprocess.run([PY, str(p), *rest], text=True, capture_output=True)
        sys.stdout.write(proc.stdout); sys.stderr.write(proc.stderr)
        raise SystemExit(proc.returncode)
    print(f'未知子命令：{cmd}', file=sys.stderr)
    raise SystemExit(1)


if __name__ == '__main__':
    main()
