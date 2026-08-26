#!/usr/bin/env python3
"""按 model_version 统计样本累积进度，回答「距离解禁推荐还差多少场」。

背景：`fusion_backtest.py` 的 `calibration_gate.current_version_n` 只数**已结算**样本，
且必须跑完整回测才能看到。发布窗口期真正要盯的是两个数：
  1. 当前 model_version 已结算多少场（门禁分子，与回测口径一致）；
  2. 还有多少场已登记但未结算（在途样本，决定何时能达标）。

第 2 个数原先没有任何入口，只能手写脚本查——这正是本脚本存在的理由。

口径对齐说明：主快照选择复用 `select_primary_rows`，默认 `latest_before_kickoff`，
与回测默认值相同；结算判定同样查 results_registry.jsonl 的 match_id 并排除 cancelled。

但本脚本的 `settled` 是回测 `n` 的**上界**，两者不保证相等：回测的 `score_record()`
还会丢弃「已结算但无法评分」的记录（缺 `final_1x2_pct`、90分钟比分未验证等），
本脚本只问「登记了没有、结算了没有」。2026-08-16 实测两边都是 474，当前没有这类记录，
但不能假定永远相等——**门禁分子以回测的 `calibration_gate` 为准**，本脚本用于看
回测给不出的那个数：**在途未结算样本**。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fusion_backtest import (load_jsonl, load_version_aliases, resolve_path,
                             select_primary_rows)
from fusion_predict_core import build_identity
from probability_aliases import matches as alias_matches
from runtime_paths import assert_writable_target, backtest_store, data_root
from direction_settlement import (is_verified_official_90min_result,
                                  settle_direction_policy,
                                  summarize_direction_policy_metrics)

MIN_RECALIBRATION = 100
THRESHOLD_REVIEW = 200
CONFIG_ROOT = Path(__file__).resolve().parent.parent / "config"
DEFAULT_RELEASE_LOCK_PATH = CONFIG_ROOT / "release_lock.json"
DEFAULT_RECOMMENDATION_POLICY_PATH = CONFIG_ROOT / "recommendation_policy.json"
_DRIFT_STATUSES = {
    "PENDING_REVIEW",
    "UNREPLAYABLE",
    "CHANGED_REQUIRES_VERSION_BUMP",
}


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def load_drift_group_statuses(root: Path, current_identity: dict) -> dict[tuple[str, str, str], str]:
    """Load self-consistent Task 2 group states for read-only decomposition."""
    statuses: dict[tuple[str, str, str], tuple[str, str]] = {}
    proof_root = Path(root) / "signature-drift-attestations"
    if not proof_root.exists():
        return {}
    target = (str(current_identity.get("model_version") or ""),
              str(current_identity.get("probability_signature") or ""))
    for path in proof_root.rglob("signature-drift-*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(report, dict):
                continue
            hash_input = report.get("report_hash_input")
            expected_hash_input = {key: value for key, value in report.items() if key not in {
                "generated_at", "report_sha256", "report_hash_input", "attestation_path",
            }}
            if hash_input != expected_hash_input:
                continue
            digest = hashlib.sha256(_canonical_json(hash_input).encode("utf-8")).hexdigest()
            if report.get("report_sha256") != digest:
                continue
            old = report.get("old_identity") or {}
            current = report.get("current_identity") or {}
            route = report.get("route")
            status = report.get("status")
            if ((str(current.get("model_version") or ""),
                 str(current.get("probability_signature") or "")) != target
                    or not isinstance(route, str) or not route
                    or status not in _DRIFT_STATUSES):
                continue
            key = (str(old.get("model_version") or ""),
                   str(old.get("probability_signature") or ""), route)
            if not key[0] or not key[1]:
                continue
            generated_at = str(report.get("generated_at") or "")
            if key not in statuses or generated_at > statuses[key][0]:
                statuses[key] = (generated_at, status)
        except (OSError, ValueError, TypeError):
            continue
    return {key: value[1] for key, value in statuses.items()}


def settled_status(root: Path) -> dict:
    """match_id -> 结算状态；cancelled 不计入分母。"""
    status = {}
    for row in load_jsonl(root / "results_registry.jsonl"):
        mid = row.get("match_id")
        if mid:
            status[mid] = str(row.get("status") or "settled")
    return status


def registered_route(record: dict) -> str | None:
    """Read the immutable registered route; never derive it from current code."""
    values = []
    for container in (record, record.get("model") or {}, record.get("input") or {}):
        if isinstance(container, dict):
            value = container.get("route") or container.get("mode")
            if value not in (None, ""):
                if not isinstance(value, str):
                    return None
                values.append(value.strip())
    if not values or not values[0] or any(value != values[0] for value in values):
        return None
    return values[0]


def _signature_group_value(value) -> str:
    """Keep valid string signatures exact; isolate corrupt JSON types."""
    if isinstance(value, str):
        return value
    try:
        encoded = _canonical_json(value)
    except (TypeError, ValueError):
        encoded = repr(value)
    return f"(invalid-{type(value).__name__}:{encoded})"


def load_prediction_rows(root: Path) -> tuple[list[dict], int]:
    """读取全部登记预测（含未结算），返回 (rows, 读取失败数)。"""
    rows = []
    unreadable = 0
    for entry in load_jsonl(root / "registry.jsonl"):
        path = resolve_path(entry.get("path", ""), root)
        if not path.exists():
            unreadable += 1
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            unreadable += 1
            continue
        model = rec.get("model") or {}
        rows.append({
            "match_id": rec.get("match_id"),
            "prediction_id": rec.get("prediction_id") or entry.get("prediction_id"),
            "snapshot_type": rec.get("snapshot_type") or "unspecified",
            "created_at": rec.get("created_at") or entry.get("created_at") or "",
            "prediction_as_of": rec.get("prediction_as_of") or "",
            "kickoff": rec.get("kickoff") or (rec.get("match") or {}).get("kickoff") or "",
            "model_version": str(model.get("model_version") or "unattributable"),
            "probability_signature": model.get("probability_signature"),
            "route": registered_route(rec),
            "direction_policy_status": rec.get("direction_policy_status") or "NOT_REGISTERED",
            "direction_policy": rec.get("direction_policy"),
        })
    return rows, unreadable


def build_report(root: Path, snapshot_policy: str = "latest_before_kickoff") -> dict:
    identity = build_identity()
    cur_mv = str(identity.get("model_version") or "unknown")
    cur_sig = str(identity.get("probability_signature") or "")

    rows, unreadable = load_prediction_rows(root)
    # Audit the production/main registry separately.  Never silently merge it
    # into the backtest denominator: this section only exposes an unfinished
    # handoff between the two stores.
    main_root = data_root()
    main_rows, main_unreadable = load_prediction_rows(main_root) if main_root != root else ([], 0)
    backtest_prediction_ids = {str(row.get("prediction_id")) for row in rows if row.get("prediction_id")}
    primary = select_primary_rows(rows, snapshot_policy)
    status = settled_status(root)
    # 经重放验证等价的旧版本按 current 计（与 fusion_backtest.version_cohort 同一口径）
    aliases = [a for a in load_version_aliases(cur_mv)
               if str(a.get("alias_to_model_version")) == cur_mv
               and str(a.get("alias_to_probability_signature")) == cur_sig]
    alias_keys = {(str(a.get("model_version") or ""),
                   str(a.get("probability_signature") or ""),
                   str(a.get("route") or "")) for a in aliases}
    alias_versions = sorted({mv for mv, _, _ in alias_keys})
    drift_statuses = load_drift_group_statuses(root, identity)
    # 按当前 model_version 审计主库全量记录；签名另行分布，避免把漂移样本隐藏。
    main_current = [row for row in main_rows if row["model_version"] == cur_mv]
    main_signature_counts = {}
    for row in main_current:
        sig = _signature_group_value(row["probability_signature"])
        if not sig:
            sig = "(none)"
        main_signature_counts[sig[:12]] = main_signature_counts.get(sig[:12], 0) + 1
    main_not_in_backtest = [row for row in main_current
                            if str(row.get("prediction_id")) not in backtest_prediction_ids]

    by_version: dict[str, dict] = {}
    signature_drift = []
    signature_drift_groups: dict[tuple[str, str, str], int] = {}
    current_settled = 0
    current_pending = 0
    raw_current_n = 0
    approved_alias_n = 0
    for row in primary:
        bucket = by_version.setdefault(row["model_version"], {
            "settled": 0, "pending": 0, "cancelled": 0, "signatures": {},
        })
        sig = _signature_group_value(row["probability_signature"])
        if not sig:
            sig = "(none)"
        bucket["signatures"][sig[:12]] = bucket["signatures"].get(sig[:12], 0) + 1
        is_raw_current = (row["model_version"] == cur_mv
                          and row["probability_signature"] == cur_sig)
        matching_alias = (None if is_raw_current else
                          next((alias for alias in aliases if alias_matches(row, alias)), None))
        is_approved_alias = matching_alias is not None
        counts_as_current = is_raw_current or is_approved_alias
        state = status.get(row["match_id"])
        if state is None:
            bucket["pending"] += 1
            current_pending += counts_as_current
        elif state == "cancelled":
            bucket["cancelled"] += 1
        else:
            bucket["settled"] += 1
            current_settled += counts_as_current
            raw_current_n += int(is_raw_current)
            approved_alias_n += int(is_approved_alias)
        # 同版本但概率签名不同 = 改了概率文件却没 bump 版本，这些样本会被静默排除出 current
        if (row["model_version"] == cur_mv and cur_sig
                and row["probability_signature"] != cur_sig
                and (row["model_version"], row["probability_signature"],
                     row["route"] or "") not in alias_keys):
            signature_drift.append({
                "prediction_id": row["prediction_id"],
                "match_id": row["match_id"],
                "signature": sig[:12] or "(none)",
            })
            key = (row["model_version"],
                   _signature_group_value(row["probability_signature"]),
                   row["route"] or "")
            signature_drift_groups[key] = signature_drift_groups.get(key, 0) + 1

    settled = current_settled
    pending = current_pending
    # 只统计本次精确签名产生、且确实替代过同场旧快照的记录；不要把全库历史
    # 多快照数量（superseded_snapshot_count）误显示为本次发布重建数量。
    exact_current_primary = [
        row for row in primary
        if row["model_version"] == cur_mv and row["probability_signature"] == cur_sig
    ]
    reissued_current_snapshot_count = sum(
        any(str(candidate.get("prediction_id") or "") != str(row.get("prediction_id") or "")
            for candidate in rows if candidate.get("match_id") == row.get("match_id"))
        for row in exact_current_primary
    )
    drift_groups = [
        {"model_version": model_version, "probability_signature": signature,
         "route": route or None, "record_count": record_count,
         "status": drift_statuses.get((model_version, signature, route), "UNREPLAYED")}
        for (model_version, signature, route), record_count in sorted(signature_drift_groups.items())
    ]
    return {
        "schema_version": "fusion-version-progress-1.0",
        "store": str(root),
        "snapshot_policy": snapshot_policy,
        "current_model_version": cur_mv,
        "current_probability_signature": cur_sig[:12],
        "counted_as_current_aliases": alias_versions,
        "raw_current_n": raw_current_n,
        "approved_alias_n": approved_alias_n,
        "current": {
            "settled": settled,
            "pending": pending,
            "projected_after_pending": settled + pending,
            "to_recalibration": max(0, MIN_RECALIBRATION - settled),
            "to_threshold_review": max(0, THRESHOLD_REVIEW - settled),
            "ready_for_recalibration": settled >= MIN_RECALIBRATION,
            "ready_for_threshold_review": settled >= THRESHOLD_REVIEW,
        },
        "by_model_version": {k: v for k, v in sorted(by_version.items())},
        "signature_drift": signature_drift,
        "signature_drift_groups": drift_groups,
        "drift_groups": drift_groups,
        "unreplayable_groups": [group for group in drift_groups
                                if group["status"] == "UNREPLAYABLE"],
        "changed_groups": [group for group in drift_groups
                           if group["status"] == "CHANGED_REQUIRES_VERSION_BUMP"],
        "pending_review_groups": [group for group in drift_groups
                                  if group["status"] == "PENDING_REVIEW"],
        "superseded_snapshot_count": max(0, len(rows) - len(primary)),
        "reissued_current_snapshot_count": reissued_current_snapshot_count,
        "unreadable_records": unreadable,
        "main_registry_audit": {
            "store": str(main_root),
            "current_rows": len(main_current),
            "current_signature": cur_sig[:12],
            "signature_counts": main_signature_counts,
            "current_not_in_backtest": len(main_not_in_backtest),
            "unreadable_records": main_unreadable,
            "note": "仅审计主库与回测库接续差异，不自动并入 current cohort",
        },
        "note": "样本量只是复审触发点，不是统计证明；达标不等于可以解禁生产推荐。",
    }


def _read_json_object(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _release_lock_report(identity: dict, path: Path) -> dict:
    lock = _read_json_object(path)
    if not Path(path).is_file():
        status = "MISSING"
    elif not lock:
        status = "INVALID"
    elif (lock.get("model_version") == identity.get("model_version")
          and lock.get("probability_signature") == identity.get("probability_signature")):
        status = "MATCH"
    else:
        status = "DRIFT"
    return {
        "status": status,
        "path": str(path),
        "locked_model_version": lock.get("model_version"),
        "locked_probability_signature": lock.get("probability_signature"),
        "locked_at": lock.get("locked_at"),
    }


def _load_result(root: Path, match_id: str) -> dict | None:
    path = Path(root) / "results" / f"{match_id}.json"
    value = _read_json_object(path)
    return value or None


def _attested_compare_fields(alias: dict) -> list[str]:
    direct = alias.get("compare_fields")
    if isinstance(direct, list) and all(isinstance(field, str) and field for field in direct):
        return list(direct)
    path_value = alias.get("attestation_path")
    expected_hash = alias.get("attestation_sha256")
    if not isinstance(path_value, str) or not isinstance(expected_hash, str):
        return []
    path = Path(path_value)
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        return []
    proof = _read_json_object(path)
    fields = proof.get("compare_fields")
    if not isinstance(fields, list) or not all(
            isinstance(field, str) and field for field in fields):
        return []
    return list(fields)


def _alias_summaries(
    rows: list[dict], aliases: list[dict], verified_official_ids: set[str],
) -> list[dict]:
    summaries = []
    for alias in aliases:
        matching = [row for row in rows if alias_matches(row, alias)]
        summaries.append({
            "model_version": alias.get("model_version"),
            "probability_signature": alias.get("probability_signature"),
            "route": alias.get("route"),
            "alias_to_model_version": alias.get("alias_to_model_version"),
            "alias_to_probability_signature": alias.get("alias_to_probability_signature"),
            "attestation_path": alias.get("attestation_path"),
            "attestation_sha256": alias.get("attestation_sha256"),
            "compare_fields": _attested_compare_fields(alias),
            "record_count": len(matching),
            "verified_official_settled_count": sum(
                str(row.get("match_id")) in verified_official_ids for row in matching),
        })
    return summaries


def build_direction_governance_report(
    root: Path,
    snapshot_policy: str = "latest_before_kickoff",
    *,
    release_lock_path: Path = DEFAULT_RELEASE_LOCK_PATH,
    recommendation_policy_path: Path = DEFAULT_RECOMMENDATION_POLICY_PATH,
) -> dict:
    """Build the combined read-only identity and direction-governance view."""
    root = Path(root)
    progress = build_report(root, snapshot_policy)
    identity = build_identity()
    rows, _ = load_prediction_rows(root)
    primary = select_primary_rows(rows, snapshot_policy)
    registry_settled_ids = {
        str(row.get("match_id")) for row in load_jsonl(root / "results_registry.jsonl")
        if row.get("match_id") and str(row.get("status") or "settled") != "cancelled"
    }
    results_by_match = {
        str(row.get("match_id") or ""): _load_result(root, str(row.get("match_id") or ""))
        for row in primary
    }
    verified_official_ids = {
        match_id for match_id, result in results_by_match.items()
        if (match_id in registry_settled_ids
            and is_verified_official_90min_result(result))
    }
    direction_rows = []
    for row in primary:
        item = dict(row)
        result = results_by_match.get(str(row.get("match_id") or ""))
        item["direction_settlement"] = settle_direction_policy(
            row.get("direction_policy"),
            result,
            registration_status=str(row.get("direction_policy_status") or "NOT_REGISTERED"),
            kickoff=row.get("kickoff"),
        )
        direction_rows.append(item)
    metrics = summarize_direction_policy_metrics(direction_rows)
    aliases = [alias for alias in load_version_aliases(identity.get("model_version"))
               if alias.get("alias_to_model_version") == identity.get("model_version")
               and alias.get("alias_to_probability_signature") == identity.get(
                   "probability_signature")]
    current_model_version = str(identity.get("model_version") or "")
    current_signature = identity.get("probability_signature")
    raw_current_verified = 0
    alias_verified = 0
    for row in primary:
        if str(row.get("match_id") or "") not in verified_official_ids:
            continue
        is_raw = (row.get("model_version") == current_model_version
                  and row.get("probability_signature") == current_signature)
        if is_raw:
            raw_current_verified += 1
        elif any(alias_matches(row, alias) for alias in aliases):
            alias_verified += 1
    lock_report = _release_lock_report(identity, Path(release_lock_path))
    recommendation = _read_json_object(Path(recommendation_policy_path))
    drift_counts = Counter(
        str(group.get("status") or "UNKNOWN")
        for group in progress.get("signature_drift_groups") or []
    )
    admission_reasons = ["paired_market_evidence_not_evaluated_by_direction_report"]
    if progress["current"]["settled"] < MIN_RECALIBRATION:
        admission_reasons.append("current_sample_below_minimum")
    if lock_report["status"] != "MATCH":
        admission_reasons.append("release_lock_not_current")
    if drift_counts:
        admission_reasons.append("signature_drift_groups_remain_isolated")
    if not recommendation.get("production_recommendations_enabled", False):
        admission_reasons.append("production_recommendations_disabled")
    return {
        "schema_version": "direction-governance-report-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": str(root),
        "snapshot_policy": snapshot_policy,
        "current_identity": identity,
        "release_lock": lock_report,
        "sample_identity": {
            "raw_current_registry_settled_upper_bound_n": progress["raw_current_n"],
            "approved_alias_registry_settled_upper_bound_n": progress["approved_alias_n"],
            "registry_settled_upper_bound_n": progress["current"]["settled"],
            "raw_current_verified_official_settled_n": raw_current_verified,
            "approved_alias_verified_official_settled_n": alias_verified,
            "verified_official_settled_n": raw_current_verified + alias_verified,
            "current_pending_n": progress["current"]["pending"],
        },
        "approved_aliases": _alias_summaries(primary, aliases, verified_official_ids),
        "signature_drift_groups": progress.get("signature_drift_groups") or [],
        "drift_group_status_counts": dict(sorted(drift_counts.items())),
        "direction_policy_metrics": metrics,
        "version_admission": {
            "status": "HOLD",
            "reasons": admission_reasons,
            "uses_direction_coverage": False,
            "production_recommendations_enabled": bool(
                recommendation.get("production_recommendations_enabled", False)),
            "note": "方向覆盖命中只做独立审计，不构成模型方向正确或版本准入证据。",
        },
        "read_only": {
            "aliases_written": False,
            "release_lock_written": False,
            "weights_changed": False,
            "gates_changed": False,
        },
    }


def direction_governance_main(argv: list[str] | None = None) -> int:
    """Read-only CLI: intentionally offers no output or mutation option."""
    parser = argparse.ArgumentParser(description="只读方向与签名治理报告")
    parser.add_argument("--store", default=str(backtest_store()))
    parser.add_argument("--snapshot-policy",
                        choices=("latest_before_kickoff", "prematch", "closing"),
                        default="latest_before_kickoff")
    args = parser.parse_args(argv)
    report = build_direction_governance_report(Path(args.store), args.snapshot_policy)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def render(report: dict) -> str:
    cur = report["current"]
    alias_text = ("，含经重放验证等价的 " + "/".join(report["counted_as_current_aliases"])
                  if report.get("counted_as_current_aliases") else "")
    lines = [
        f"当前版本 {report['current_model_version']} "
        f"(概率签名 {report['current_probability_signature']}{alias_text})",
        f"  已结算 {cur['settled']} 场 | 在途未结算 {cur['pending']} 场 "
        f"| 全部结算后可达 {cur['projected_after_pending']} 场",
        f"  距重校准门槛({MIN_RECALIBRATION}) 还差 {cur['to_recalibration']} 场"
        f" | 距阈值复审({THRESHOLD_REVIEW}) 还差 {cur['to_threshold_review']} 场",
        "",
        "各版本分布（主快照口径）：",
    ]
    for version, stat in report["by_model_version"].items():
        sigs = ",".join(f"{k}×{v}" for k, v in sorted(stat["signatures"].items()))
        lines.append(f"  {version:<16} 已结算 {stat['settled']:>5} | 在途 {stat['pending']:>4}"
                     f" | 作废 {stat['cancelled']:>3} | 签名 {sigs}")
    if report["signature_drift"]:
        lines.append("")
        lines.append(f"⚠ 概率签名漂移 {len(report['signature_drift'])} 条："
                     "同为当前版本但签名不同，这些样本不会计入 current cohort")
        for item in report["signature_drift"][:10]:
            lines.append(f"    {item['prediction_id']} 签名={item['signature']}")
    audit = report.get("main_registry_audit") or {}
    if audit.get("current_not_in_backtest"):
        lines.append("")
        lines.append(
            f"⚠ 主登记库有 {audit['current_not_in_backtest']} 条当前版本记录尚未接续到回测库；"
            "已独立计数，不自动并入 current cohort"
        )
        if audit.get("signature_counts"):
            sigs = ", ".join(f"{sig}×{n}" for sig, n in sorted(audit["signature_counts"].items()))
            lines.append(f"  主库该版本签名分布：{sigs}")
    if report["unreadable_records"]:
        lines.append("")
        lines.append(f"⚠ {report['unreadable_records']} 条登记记录无法读取预测文件")
    lines.append("")
    lines.append(report["note"])
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--direction-governance-report":
        return direction_governance_main(sys.argv[2:])
    ap = argparse.ArgumentParser(description="按 model_version 统计样本累积进度")
    ap.add_argument("--store", default=str(backtest_store()))
    ap.add_argument("--snapshot-policy", choices=("latest_before_kickoff", "prematch", "closing"),
                    default="latest_before_kickoff")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非人读文本")
    ap.add_argument("--output", help="同时写入指定文件")
    a = ap.parse_args()

    report = build_report(assert_writable_target(Path(a.store)), a.snapshot_policy)
    text = json.dumps(report, ensure_ascii=False, indent=2) if a.json else render(report)
    print(text)
    if a.output:
        out = Path(a.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
