#!/usr/bin/env python3
"""Build the frozen 121-row audit and the live unique-match cohort inventory."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from hybrid_contract import (
    FROZEN_HYBRID_SIDECAR_AUDIT_20260824,
    LIVE_HYBRID_REVIEW_UNIQUE,
    REGISTERED_HYBRID_BACKTEST_V1,
)


FREEZE_CUTOFF = "2026-08-23T18:56:53+00:00"
OVERWRITTEN_IDS = {"sporttery-2041028", "sporttery-2041030", "sporttery-2041031"}
EXPECTED_FROZEN = {
    "NON_INDEPENDENT_OR_UNSUCCESSFUL": 33,
    "MISSING_ROUTING_AUDIT": 54,
    "POST_KICKOFF_RUN": 3,
    "MISSING_VERIFIED_SCORE_AT_FREEZE": 19,
    "ELIGIBLE_AT_FREEZE": 12,
}


def parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else None


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sidecar_reason(job: dict, frozen_eligible: set[str]) -> tuple[str, str, bool]:
    hybrid = ((job.get("research") or {}).get("hybrid") or {})
    identity = job.get("identity") or {}
    match_id = identity.get("match_id")
    if (hybrid.get("research_only") is not True or hybrid.get("status") != "ok"
            or hybrid.get("mode") != "hybrid" or hybrid.get("market_derived") is True
            or not isinstance(hybrid.get("lambda_prior"), dict)):
        return "NON_INDEPENDENT_OR_UNSUCCESSFUL", "口径要求", False
    audit = hybrid.get("routing_audit")
    if not isinstance(audit, dict) or not audit.get("history_latest"):
        return "MISSING_ROUTING_AUDIT", "工程缺陷", True
    kickoff = parse_time((job.get("input") or {}).get("kickoff") or identity.get("kickoff"))
    run_at = parse_time(hybrid.get("research_run_at"))
    if kickoff is not None and (run_at is None or run_at >= kickoff):
        return "POST_KICKOFF_RUN", "口径要求", False
    if match_id in frozen_eligible:
        return "ELIGIBLE_AT_FREEZE", "合格", False
    return "MISSING_VERIFIED_SCORE_AT_FREEZE", "口径要求", False


def frozen_rows(jobs_root: Path, frozen_evaluation: Path) -> list[dict]:
    frozen = read_json(frozen_evaluation)
    frozen_eligible = {str(row["match_id"]) for row in frozen.get("rows", [])}
    cutoff = parse_time(FREEZE_CUTOFF)
    assert cutoff is not None
    rows: list[dict] = []
    current_overwritten: dict[str, tuple[Path, dict]] = {}
    for path in sorted(jobs_root.rglob("sporttery-*.json")):
        job = read_json(path)
        hybrid = ((job.get("research") or {}).get("hybrid") or {})
        if not hybrid:
            continue
        match_id = str((job.get("identity") or {}).get("match_id") or "")
        if match_id in OVERWRITTEN_IDS:
            current_overwritten[match_id] = (path, job)
        observed = parse_time(hybrid.get("research_run_at") or job.get("updated_at"))
        if observed is None or observed > cutoff:
            continue
        reason, reason_type, fixable = sidecar_reason(job, frozen_eligible)
        rows.append(_audit_row(path, job, reason, reason_type, fixable, "DIRECT_OR_CURRENT_FILE"))

    # These three paths existed in the frozen aggregate but were overwritten by
    # later runs. Their old individual fields cannot be recovered; only their
    # aggregate membership and exclusion bucket can be reconstructed.
    for match_id in sorted(OVERWRITTEN_IDS):
        path, job = current_overwritten[match_id]
        rows.append(_audit_row(
            path, job, "MISSING_VERIFIED_SCORE_AT_FREEZE", "口径要求", False,
            "AGGREGATE_RECONSTRUCTION_OVERWRITTEN_OLD_VALUES",
        ))
    counts = Counter(row["elimination_reason"] for row in rows)
    if len(rows) != 121 or dict(counts) != EXPECTED_FROZEN:
        raise RuntimeError(f"frozen denominator drift: n={len(rows)} counts={dict(counts)}")
    return rows


def _audit_row(path: Path, job: dict, reason: str, reason_type: str,
               fixable: bool, evidence_grade: str) -> dict:
    hybrid = ((job.get("research") or {}).get("hybrid") or {})
    audit = hybrid.get("routing_audit") or {}
    identity = job.get("identity") or {}
    input_obj = job.get("input") or {}
    return {
        "denominator_id": FROZEN_HYBRID_SIDECAR_AUDIT_20260824,
        "path": str(path),
        "match_id": identity.get("match_id"),
        "sales_day": identity.get("sales_day") or path.parent.name,
        "kickoff": input_obj.get("kickoff") or identity.get("kickoff"),
        "research_run_at": hybrid.get("research_run_at"),
        "history_latest": audit.get("history_latest"),
        "market_input_as_of": hybrid.get("market_input_as_of") or input_obj.get("prediction_as_of"),
        "route": audit.get("route"),
        "status": hybrid.get("status"),
        "model_version": hybrid.get("model_version"),
        "probability_signature": hybrid.get("probability_signature"),
        "hybrid_cohort_key": hybrid.get("hybrid_cohort_key"),
        "score_90_status": ((job.get("settlement") or {}).get("score_90_status")),
        "elimination_reason": reason,
        "reason_type": reason_type,
        "fixable": fixable,
        "evidence_grade": evidence_grade,
    }


def live_inventory(jobs_root: Path, backtest_root: Path, frozen_eligible: set[str]) -> dict:
    candidates: list[dict] = []
    for path in sorted(jobs_root.rglob("sporttery-*.json")):
        job = read_json(path)
        hybrid = ((job.get("research") or {}).get("hybrid") or {})
        audit = hybrid.get("routing_audit") or {}
        input_obj = job.get("input") or {}
        kickoff = parse_time(input_obj.get("kickoff") or (job.get("identity") or {}).get("kickoff"))
        run_at = parse_time(hybrid.get("research_run_at"))
        history = parse_time(audit.get("history_latest"))
        if not (hybrid.get("research_only") is True and hybrid.get("status") == "ok"
                and hybrid.get("mode") == "hybrid" and hybrid.get("market_derived") is not True
                and isinstance(hybrid.get("lambda_prior"), dict)
                and audit.get("no_future_leakage") is True
                and kickoff and run_at and history and history < kickoff and run_at < kickoff):
            continue
        candidates.append({"path": path, "job": job, "run_at": run_at, "kickoff": kickoff})

    latest: dict[str, dict] = {}
    for item in candidates:
        match_id = str((item["job"].get("identity") or {}).get("match_id"))
        if match_id not in latest or item["run_at"] > latest[match_id]["run_at"]:
            latest[match_id] = item

    prediction_index = {path.stem: path for path in (backtest_root / "predictions").rglob("*.json")}
    predictions_by_match: dict[str, list[Path]] = {}
    for historical_path in prediction_index.values():
        predictions_by_match.setdefault(historical_path.stem.split("__", 1)[0], []).append(historical_path)
    rows = []
    for match_id, item in sorted(latest.items(), key=lambda pair: (pair[1]["kickoff"], pair[0])):
        job = item["job"]
        hybrid = ((job.get("research") or {}).get("hybrid") or {})
        quant = next((row for row in (job.get("outputs") or []) if row.get("track") == "quant"), {})
        prediction_id = quant.get("prediction_id")
        prediction_path = prediction_index.get(str(prediction_id))
        model_version = probability_signature = None
        attribution = "UNATTRIBUTED"
        input_as_of = (hybrid.get("market_input_as_of")
                       or (job.get("input") or {}).get("prediction_as_of"))
        candidate_paths = [prediction_path] if prediction_path else []
        # The frozen 12 were verified against their then-current registered
        # prediction. Some job projections were later overwritten, so recover
        # that exact-timestamp file without extending the proof to other IDs.
        if match_id in frozen_eligible:
            candidate_paths += [path for path in predictions_by_match.get(match_id, [])
                                if path != prediction_path]
        for candidate_path in candidate_paths:
            prediction = read_json(candidate_path)
            model = prediction.get("model") or {}
            prediction_as_of = parse_time(prediction.get("prediction_as_of"))
            job_as_of = parse_time(input_as_of)
            if (prediction.get("prediction_id") == candidate_path.stem
                    and prediction.get("match_id") == match_id
                    and prediction_as_of and job_as_of and prediction_as_of == job_as_of
                    and job_as_of <= item["run_at"]):
                model_version = model.get("model_version")
                probability_signature = model.get("probability_signature")
                if model_version and probability_signature:
                    attribution = "VERIFIED_SIBLING_QUANT_PREDICTION"
                    prediction_id = prediction.get("prediction_id")
                    break
        result_path = backtest_root / "results" / f"{match_id}.json"
        settled = bool((job.get("settlement") or {}).get("score_90")) or result_path.exists()
        rows.append({
            "denominator_id": LIVE_HYBRID_REVIEW_UNIQUE,
            "match_id": match_id,
            "sales_day": (job.get("identity") or {}).get("sales_day") or item["path"].parent.name,
            "kickoff": item["kickoff"].isoformat(),
            "research_run_at": item["run_at"].isoformat(),
            "settled": settled,
            "prediction_id": prediction_id,
            "model_version": model_version,
            "probability_signature": probability_signature,
            "hybrid_cohort_key": f"{model_version}::{probability_signature}"
            if model_version and probability_signature else None,
            "attribution": attribution,
            "historical_sidecar_rewritten": False,
        })
    cohorts = Counter(row["hybrid_cohort_key"] or "UNATTRIBUTED" for row in rows)
    return {
        "denominator_id": LIVE_HYBRID_REVIEW_UNIQUE,
        "n": len(rows),
        "settled": sum(row["settled"] for row in rows),
        "pending": sum(not row["settled"] for row in rows),
        "cohorts": dict(cohorts),
        "rows": rows,
    }


def write_outputs(output_dir: Path, frozen: list[dict], live: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "frozen_sidecar_audit_121.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frozen[0]))
        writer.writeheader()
        writer.writerows(frozen)
    payload = {
        "schema_version": "hybrid-sample-governance-audit-1.0",
        "generated_at": datetime.now().astimezone().isoformat(),
        "denominators": {
            REGISTERED_HYBRID_BACKTEST_V1: {
                "n": 12, "brier": 0.64358, "era": "fusion-1.2.0+core-3.4.1",
                "rule": "不得与侧车研究样本合并",
            },
            FROZEN_HYBRID_SIDECAR_AUDIT_20260824: {
                "n": 121, "eligible_n": 12, "eligible_brier": 0.628422,
                "counts": dict(Counter(row["elimination_reason"] for row in frozen)),
            },
            LIVE_HYBRID_REVIEW_UNIQUE: live,
        },
        "eta": {
            "all_observed_daily_first_qualified": [0, 1, 2, 4, 5, 19],
            "all_median": 3.0,
            "batch_day": "2026-08-22",
            "batch_windows_utc": ["04:37-04:49", "08:02-08:10"],
            "natural_daily": [0, 1, 2, 4, 5],
            "natural_mean": 2.4,
            "natural_median": 2,
            "estimate": "当前签名1条起算约50个自然日；范围20-99日，另加1-2日结算延迟",
            "accelerators_not_executed": [
                "无泄漏历史补跑",
                "扫描54条缺审计记录的原始快照可恢复性",
                "每个开售唯一比赛自动运行一次，重复销售日不增加分母",
                "扩展联赛或独立数据源另立模型任务",
            ],
        },
    }
    (output_dir / "hybrid_sample_governance_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    current_key = "m4::48d50abee08c6c1ed3854dda4d76e762c9106134d1bd0fa5202c15e460d0798b"
    old_key = "m4::5c34721daa91a0232805bbcaa7b1cfebcbfb57dc32c0a2b1e63c4662ceb17197"
    lines = [
        "# Hybrid 样本管道与版本窗口治理审计（2026-08-26）", "",
        "## 三个固定分母（禁止跨口径相减）", "",
        "| denominator_id | 定义 | 当前事实 |", "|---|---|---|",
        f"| `{REGISTERED_HYBRID_BACKTEST_V1}` | 回测登记 hybrid 路由 | n=12，Brier=0.64358，fusion-1.2.0+core-3.4.1 时代 |",
        f"| `{FROZEN_HYBRID_SIDECAR_AUDIT_20260824}` | 2026-08-24 冻结侧车覆盖 | 121行；有效12行的 Brier=0.628422 |",
        f"| `{LIVE_HYBRID_REVIEW_UNIQUE}` | 唯一 match_id 的最后一次合格赛前运行 | n={live['n']}，已结算{live['settled']}，待结算{live['pending']} |",
        "", "## 121 行逐侧车淘汰审计", "",
        "| 原因 | 数量 | 性质 | 能否修复 | 结论 |", "|---|---:|---|---|---|",
        "| 非独立或运行未成功 | 33 | 口径要求 | 否 | 没有独立先验时正常跳过；以后不生成侧车 |",
        "| 缺路由审计 | 54 | 工程缺陷 | 是 | Sidecar v2 已改为缺字段直接非零退出 |",
        "| 赛后运行 | 3 | 口径要求 | 否 | 历史样本不可补救；以后开球时间门禁直接拒绝 |",
        "| 冻结时缺核验90分钟赛果 | 19 | 口径要求 | 当时不可计分 | 赛果核验后才进入已结算评估 |",
        "| 有效 | 12 | 合格 | — | Brier 0.628422 只属于这12行 |",
        "", "逐行机器表：`frozen_sidecar_audit_121.csv`。其中3条旧侧车后来被覆盖，旧字段不可恢复，表中明确标为聚合重建推断。",
        "", "## 实时版本归因", "",
        f"- 旧签名 `{old_key}`：{live['cohorts'].get(old_key, 0)} 条。",
        f"- 当前签名 `{current_key}`：{live['cohorts'].get(current_key, 0)} 条。",
        f"- 身份未能严格复验：{live['cohorts'].get('UNATTRIBUTED', 0)} 条。",
        "- 归因只读，不反写历史侧车。现有 market_only 等价别名不得外推到 hybrid。",
        "", "## 版本窗口与验收", "",
        "`hybrid_cohort_key = model_version + '::' + probability_signature`。窗口期内任何概率文件改动都会作废已积累样本；旧样本保留在旧 cohort。",
        "同一完整 cohort 达到100个已结算唯一比赛后，按开球日期组70/30切分；测试集做固定种子10000次同场配对 bootstrap。Brier 与 LogLoss 的95% CI上界均严格小于0才记为有证据；接触或跨0均为 `NO_EVIDENCE`；整体大于0为 `EVIDENCE_OF_HARM`。只赋予人工评审资格，不自动进生产。",
        "", "## ETA", "",
        "历史序列 `[0,1,2,4,5,19]` 的中位数是3.0。19场来自2026-08-22两组成簇批次，不用于自然流量均值。自然日 `[0,1,2,4,5]` 均值2.4、中位数2。严格从当前签名1条起算，中心约50个自然日，观察区间20—99日，另加1—2日结算延迟。",
    ]
    (output_dir / "hybrid样本管道治理报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-root", required=True)
    parser.add_argument("--backtest-root", required=True)
    parser.add_argument("--frozen-evaluation", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    frozen = frozen_rows(Path(args.jobs_root), Path(args.frozen_evaluation))
    frozen_eval = read_json(Path(args.frozen_evaluation))
    frozen_eligible = {str(row["match_id"]) for row in frozen_eval.get("rows", [])}
    live = live_inventory(Path(args.jobs_root), Path(args.backtest_root), frozen_eligible)
    write_outputs(Path(args.output_dir), frozen, live)
    print(json.dumps({
        "status": "ok", "frozen_n": len(frozen), "frozen_counts": EXPECTED_FROZEN,
        "live_n": live["n"], "live_settled": live["settled"], "live_pending": live["pending"],
        "live_cohorts": live["cohorts"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
