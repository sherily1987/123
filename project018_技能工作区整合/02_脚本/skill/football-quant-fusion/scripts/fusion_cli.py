#!/usr/bin/env python3
"""football-quant-fusion command router.

REBUILT 2026-08-02：原文件在文件系统同步事故中损坏，本文件基于
SKILL.md 1.5.0 命令表、会话中读取的 record_fusion 逻辑与已恢复脚本重建。
子命令依赖的脚本如缺失会返回明确错误，不静默吞错。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from runtime import resolve_python
from runtime_paths import core_copy_status, core_scripts_dir, data_root, odds_store, validate_cli_paths
from draw_watch_signal import build_draw_calibration_shadow, build_draw_research

# 统一解释器：当前为 3.14 等非 3.12 时，所有子进程改用内置 Python 3.12
PY = resolve_python()

HERE = Path(__file__).resolve().parent
FUSION_VERSION = "1.5.0"
STORE = data_root() / "backtest"

# 子命令 → 负责脚本（相对本目录；缺失时给出恢复提示）
MAP = {
    "collect": "sales_day_collect.py",
    "sales-day-collect": "sales_day_collect.py",
    "kickoff-date-collect": "sales_day_collect.py",
    "record": "fusion_record.py",
    "daily-pipeline": "fusion_daily_pipeline.py",
    "prematch-evidence": "prematch_evidence_collect.py",
    "bb-browser-evidence": "bb_browser_evidence_collect.py",
}

HELP = """\
Supported commands:
  collect | sales-day-collect | kickoff-date-collect
  record | daily-pipeline | preview | merge-preview | settle | backtest
  odds-add | odds-drift | odds-intl | odds-intl-capture | tournament
  football-data-enrich | market-ablation | collect-date | llm-evidence
  version-progress | derivative-diagnostics | half-time-enrichment | score-shadow-compare
  league-capability-matrix
  draw-watch-evaluate | draw-ttg-shadow-research
  half-time-collect | four-market-admission
  job | strategy-plan | independent-market-shadow
  hybrid-shadow | hybrid-evaluate | hybrid-admission
  late-info
  prematch-evidence
  bb-browser-evidence
"""


def assert_release_lock_clean() -> None:
    """Fail closed when probability files drift from the release lock."""
    audit = HERE / "audit_version_consistency.py"
    proc = subprocess.run([PY, str(audit)], text=True, capture_output=True)
    if proc.returncode:
        detail = (proc.stdout or proc.stderr or "版本审计失败").strip()
        raise SystemExit(f"发布锁审计未通过，禁止生产登记：{detail}")


# [中文功能] 从命令行参数中提取指定flag的值
def option_value(rest, flag):
    if flag not in rest:
        return None
    j = rest.index(flag)
    if j + 1 < len(rest) and not rest[j + 1].startswith('-'):
        return rest[j + 1]
    return None


def attach_draw_research(wrapped, input_payload):
    """Append the draw-observation label after the frozen probability engine.

    This deliberately runs in the command-router layer: no probability value,
    calibration, registration gate, or probability signature is modified.
    """
    if not isinstance(wrapped, dict) or not isinstance(input_payload, dict):
        return wrapped
    if isinstance(wrapped.get("results"), list) and isinstance(input_payload.get("matches"), list):
        result = dict(wrapped)
        result["results"] = [
            attach_draw_research(item, payload)
            for item, payload in zip(wrapped["results"], input_payload["matches"])
        ]
        return result
    if wrapped.get("fusion_status") != "ok" or not isinstance(wrapped.get("forecast"), dict):
        return wrapped
    result = dict(wrapped)
    forecast = dict(wrapped["forecast"])
    forecast["draw_research"] = build_draw_research(
        forecast.get("final_1x2_pct"), input_payload.get("ttg"),
    )
    forecast["draw_calibration_shadow"] = build_draw_calibration_shadow(
        forecast.get("final_1x2_pct"), input_payload.get("ttg"),
    )
    result["forecast"] = forecast
    return result


# [中文功能] 以子进程运行脚本并实时转发其输出（不再 capture 吞掉进度）
def run_script(script, rest):
    p = HERE / script
    if not p.exists():
        raise SystemExit(f'脚本缺失（事故损坏待恢复）：{p}\n可用 zu-yu-dashi-3 对应脚本替代或联系重建。')
    proc = subprocess.Popen([PY, str(p), *rest], text=True, encoding="utf-8", errors="replace",
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


# [中文功能] 运行仓库外的显式脚本入口；用于独立部署的 LLM 证据链。
def run_external_script(path, rest):
    p = Path(path).resolve()
    if not p.is_file():
        raise SystemExit(f"外部脚本缺失：{p}")
    proc = subprocess.Popen(
        [PY, str(p), *rest], text=True, encoding="utf-8", errors="replace",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def run_llm_evidence(rest):
    """委托生产 LLM 工程采集近期战绩、CRS/TTG/HAFU 与临场阵容证据。

    2026-08-16：LLM 工程已从 C:\\Users\\Administrator\\football-llm-predictor 迁入仓库，
    默认值随之改为仓库内路径；`FOOTBALL_LLM_ROOT` 仍可覆盖（例如临时指回 C 盘对比）。
    """
    root = Path(os.environ.get("FOOTBALL_LLM_ROOT")
                or (HERE.parents[2] / "llm" / "football-llm-predictor"))
    script = root / "mcp_evidence.py"
    if not script.is_file():
        raise SystemExit(
            f"LLM 证据链不可用：未找到 {script}。"
            "请设置 FOOTBALL_LLM_ROOT 指向真实生产目录；不得静默回退到仓库副本。"
        )
    return run_external_script(script, rest)


# [中文功能] 可选项：把采集结果写入赔率移动库
def maybe_odds_add(odds_source):
    if not odds_source:
        return None
    try:
        proc = subprocess.run(
            [PY, str(HERE / 'fusion_cli.py'), 'odds-add', '--source', odds_source,
             '--store', str(odds_store())],
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
    input_payload = json.loads(Path(input_path).read_text(encoding="utf-8-sig"))
    wrapped = attach_draw_research(wrapped, input_payload)
    fusion_output.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    # 2026-08-12 修复：保留 build_identity，否则 fusion_record 登记时
    # engine_bundle/prediction_code/config 三个哈希全部落 'unknown'，
    # 导致同版本样本永远无法归入 current cohort（P1-1 根因）。
    core["build_identity"] = wrapped.get("build_identity")
    if wrapped.get("match_id"):
        core["match_id"] = wrapped["match_id"]
    if wrapped.get("match_num"):
        core["match_num"] = wrapped["match_num"]
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
    # All routed commands share the same write-path guard.  This prevents a
    # caller from silently bypassing the repository fact source with an
    # explicit legacy ``--store`` or ``--odds-store`` override.
    validate_cli_paths(rest)
    copy_status = core_copy_status()
    if copy_status["status"] == "MISMATCH":
        raise SystemExit(
            "核心引擎仓库副本与外部物理副本不一致；请先同步并重新审计："
            + ",".join(copy_status["mismatches"])
        )
    if cmd == "record" and any(arg in ("-h", "--help") for arg in rest):
        print("Usage: fusion_cli.py record --input MATCH.json --output MODEL.json "
              "[--snapshot prematch] [--store DIR] [--odds-source ODDS.json]")
        return
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
    if cmd == "job":
        run_script("job_ticket.py", rest)
        return
    if cmd == "record":
        assert_release_lock_clean()
    if cmd == "strategy-plan":
        # 四市场逐池审计 + 2/3 串结构 + 每日预算总账；所有生产与资金门禁失败关闭。
        run_script("daily_strategy_planner.py", rest)
        return
    if cmd == "independent-market-shadow":
        # 不读取本场赔率生成概率；赔率只用于逐池市场基线和纸面EV比较。
        run_script("independent_lambda_market_shadow.py", rest)
        return
    if cmd == "hybrid-shadow":
        # 影子 hybrid：不登记、不开 m4。用法：
        #   fusion_cli.py hybrid-shadow --input raw.json --sales-day YYYY-MM-DD
        #   fusion_cli.py hybrid-shadow --score --sales-day YYYY-MM-DD
        run_script("hybrid_shadow.py", rest)
        return
    if cmd == "hybrid-evaluate":
        # 只读评测同场 independent hybrid 相对市场的 OOS 指标；不登记、不改 m3。
        run_script("hybrid_evaluation.py", rest)
        return
    if cmd == "hybrid-admission":
        # 只读上线资格判定；任何结果均不得切换生产概率或推荐开关。
        run_script("hybrid_admission.py", rest)
        return
    if cmd == "late-info":
        # 动态赛前伤停/首发，只写研究库。
        #   fusion_cli.py late-info --from-collect raw.json
        #   fusion_cli.py late-info --from-collect raw.json --watch
        run_script("collect_late_info.py", rest)
        return
    if cmd == "version-progress":
        # 发布窗口期盯样本累积：当前 model_version 已结算/在途场次与门槛距离。
        # 用法：fusion_cli.py version-progress [--store DIR] [--json] [--output FILE]
        run_script("version_progress.py", rest)
        return
    if cmd == "league-capability-matrix":
        # 联赛能力矩阵只做样本/证据/赛果门禁，不改变概率或版本。
        run_script("league_capability_matrix.py", rest)
        return
    if cmd == "half-time-enrichment":
        # 离线核验半场比分，只写 research evidence，绝不反写 90 分钟正式赛果。
        run_script("half_time_enrichment.py", rest)
        return
    if cmd == "half-time-collect":
        # 仅抓取并归档 provider 半场原始响应，后续仍须三重匹配才可作为研究证据。
        run_script("collect_half_time_apifootball.py", rest)
        return
    if cmd == "derivative-diagnostics":
        # 大小球/半全场独立分母评测；HAFU 必须同时有已核验半场证据与非 UNFITTED 概率。
        run_script("derivative_diagnostics.py", rest)
        return
    if cmd == "draw-watch-evaluate":
        # 平局 watch/focus 只读结算；样本不足时永远 hold，不触碰生产概率。
        run_script("draw_watch_evaluation.py", rest)
        return
    if cmd == "draw-ttg-shadow-research":
        # TTG 条件平局概率候选的严格时序回测；仅报告 hold/review，不改变生产概率。
        run_script("draw_ttg_shadow_research.py", rest)
        return
    if cmd == "score-shadow-compare":
        # 仅比较已验证的 Big5 比分参数候选；不触碰 m3 与生产比分矩阵。
        run_script("score_shadow_compare.py", rest)
        return
    if cmd == "four-market-admission":
        # 四类输出分别准入；只输出 hold/review，不自动改任何生产参数。
        run_script("four_market_admission.py", rest)
        return
    if cmd == "llm-evidence":
        run_llm_evidence(rest)
        return
    if cmd == "prematch-evidence":
        # 赛前事实自动采集：只写 evidence sidecar，不改写已登记预测。
        run_script("prematch_evidence_collect.py", rest)
        return
    if cmd == "bb-browser-evidence":
        # BB-browser/FotMob 补充证据：research-only，要求显式 URL 映射。
        run_script("bb_browser_evidence_collect.py", rest)
        return
    if cmd == "odds-intl":
        # 国际盘对照（可选，The Odds API）：仅 CLV/edge 研究，不参与概率建模。
        # 用法：fusion_cli.py odds-intl --match-file raw.json --out intl_snapshot.json [--dry-run]
        run_script("odds_api_adapter.py", rest)
        return
    if cmd == "odds-intl-capture":
        # 只在 T-24h/T-6h/T-75m 窗口采集国际盘研究快照；不改变生产概率。
        run_script("intl_snapshot_capture.py", rest)
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
        p = HERE / "fusion_settle.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        proc = subprocess.Popen([PY, str(p), *rest], text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
        raise SystemExit(proc.returncode)
    if cmd == "backtest":
        # fusion 全参数回测：委托融合回测脚本（缺失时回退 zu-yu-dashi-3 回测并说明）
        fb = HERE / "fusion_backtest.py"
        if fb.exists():
            p = fb
        else:
            p = core_scripts_dir() / "backtest.py"
            print('提示：fusion_backtest.py 缺失（事故损坏），回退核心引擎回测', file=sys.stderr)
        proc = subprocess.Popen([PY, str(p), *rest], text=True, encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
        raise SystemExit(proc.returncode)
    if cmd in ("odds-add", "odds-drift"):
        p = core_scripts_dir() / "odds_movement.py"
        if not p.exists():
            raise SystemExit(f'依赖脚本缺失：{p}')
        sub_cmd = 'add' if cmd == 'odds-add' else 'drift'
        proc = subprocess.Popen([PY, str(p), sub_cmd, *rest], text=True, encoding="utf-8",
                                errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
        proc.wait()
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
