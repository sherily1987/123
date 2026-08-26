"""Shared release-lock checks for formal football-quant-fusion registration."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_REPLAY_FIELDS = (
    "final_1x2_pct", "model_1x2_pct", "ou_2_5", "ou_3_5", "btts",
    "hafu_model", "ttg_score_consistency", "top_scores", "score_matrix",
)


class ReleaseGovernanceError(RuntimeError):
    """A formal prediction may not be registered under the requested identity."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ReleaseGovernanceError(f"无法读取发布治理文件：{path}") from exc
    if not isinstance(payload, dict):
        raise ReleaseGovernanceError(f"发布治理文件不是对象：{path}")
    return payload


def _identity_pair(identity: dict[str, Any]) -> tuple[str, str]:
    return (str(identity.get("model_version") or ""),
            str(identity.get("probability_signature") or ""))


def _is_non_negative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _is_sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value.lower()))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _parse_aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_grouped_alias_attestation(
    report: dict[str, Any], *, current_identity: dict[str, Any]
) -> dict[str, Any]:
    """Validate a Task 2 group proof before an exact alias can be approved.

    This validator accepts machine evidence only.  It does not mutate the
    proof, release lock, historical predictions, or alias configuration.
    """
    if report.get("schema_version") != "signature-drift-attestation-1.0":
        raise ReleaseGovernanceError("不是 Task 2 签名漂移证明")
    if report.get("status") != "PENDING_REVIEW":
        raise ReleaseGovernanceError("证明状态必须为 PENDING_REVIEW")
    if report.get("alias_eligible") is not False:
        raise ReleaseGovernanceError("机器证明不得自行批准别名")

    old_identity = report.get("old_identity")
    target_identity = report.get("current_identity")
    old_model_version = old_identity.get("model_version") if isinstance(old_identity, dict) else None
    if (not isinstance(old_model_version, str) or not old_model_version.strip()
            or old_model_version != old_model_version.strip()):
        raise ReleaseGovernanceError("证明缺少旧模型身份")
    if not _is_sha256(old_identity.get("probability_signature")):
        raise ReleaseGovernanceError("旧概率签名不是完整 SHA256")
    target_model_version = (target_identity.get("model_version")
                            if isinstance(target_identity, dict) else None)
    if (not isinstance(target_model_version, str) or not target_model_version.strip()
            or target_model_version != target_model_version.strip()):
        raise ReleaseGovernanceError("证明缺少目标模型身份")
    if not _is_sha256(target_identity.get("probability_signature")):
        raise ReleaseGovernanceError("目标概率签名不是完整 SHA256")
    if _identity_pair(target_identity) != _identity_pair(current_identity):
        raise ReleaseGovernanceError("证明目标身份与当前发布锁不一致")
    if _identity_pair(old_identity) == _identity_pair(target_identity):
        raise ReleaseGovernanceError("旧身份与当前目标为相同身份，不得建立别名")

    route = report.get("route")
    if not isinstance(route, str) or not route.strip() or route != route.strip():
        raise ReleaseGovernanceError("证明缺少精确登记路由")
    fields = report.get("compare_fields")
    if (not isinstance(fields, list) or len(fields) != len(REQUIRED_REPLAY_FIELDS)
            or set(fields) != set(REQUIRED_REPLAY_FIELDS)):
        raise ReleaseGovernanceError("证明比较字段不是完整必需九字段")
    tolerance = report.get("float_tolerance")
    if type(tolerance) is not float or tolerance != 1e-10:
        raise ReleaseGovernanceError("证明浮点容差必须精确为 1e-10")

    record_count = report.get("record_count")
    results = report.get("results")
    if (type(record_count) is not int or record_count < 1
            or not isinstance(results, list) or len(results) != record_count):
        raise ReleaseGovernanceError("证明全组记录数量不完整")
    for result in results:
        if not isinstance(result, dict) or result.get("status") != "identical":
            raise ReleaseGovernanceError("证明不是全组等价")
        if result.get("route") != route:
            raise ReleaseGovernanceError("逐场路由与证明组路由不一致")
        if not _is_sha256(result.get("input_sha256")):
            raise ReleaseGovernanceError("逐场证明缺少完整输入 SHA256")
        if not isinstance(result.get("prediction_as_of"), str) or not result["prediction_as_of"].strip():
            raise ReleaseGovernanceError("逐场证明缺少 prediction_as_of")
        if (result.get("time_audit") or {}).get("usable") is not True:
            raise ReleaseGovernanceError("逐场时间审计未通过")
        if result.get("diffs") not in ({}, None):
            raise ReleaseGovernanceError("完全一致记录仍包含差异")

        registered = result.get("registered_identity")
        stored_input = result.get("input_identity")
        if not isinstance(registered, dict) or not isinstance(stored_input, dict):
            raise ReleaseGovernanceError("逐场证明缺少完整记录身份或输入身份")
        for field in ("match_id", "home", "away", "competition"):
            registered_value = registered.get(field)
            input_value = stored_input.get(field)
            if (not isinstance(registered_value, str) or not registered_value.strip()
                    or not isinstance(input_value, str) or not input_value.strip()):
                raise ReleaseGovernanceError(f"逐场身份字段不完整：{field}")
            if registered_value != input_value:
                raise ReleaseGovernanceError(f"逐场记录身份与输入身份不一致：{field}")
        if (registered.get("model_version") != old_model_version
                or registered.get("probability_signature")
                != old_identity.get("probability_signature")):
            raise ReleaseGovernanceError("逐场模型版本或概率签名与证明组身份不一致")
        if registered.get("route") != route or stored_input.get("route") != route:
            raise ReleaseGovernanceError("逐场记录/输入路由与证明组路由不一致")
        if (result.get("match_id") != registered.get("match_id")
                or result.get("prediction_as_of") != registered.get("prediction_as_of")):
            raise ReleaseGovernanceError("逐场结果顶层身份与不可变记录身份不一致")

        registered_as_of = _parse_aware_time(registered.get("prediction_as_of"))
        input_as_of = _parse_aware_time(stored_input.get("prediction_as_of"))
        registered_kickoff = _parse_aware_time(registered.get("kickoff"))
        input_kickoff = _parse_aware_time(stored_input.get("kickoff"))
        if None in (registered_as_of, input_as_of, registered_kickoff, input_kickoff):
            raise ReleaseGovernanceError("逐场时间身份缺失、不可解析或不含时区")
        if registered_as_of != input_as_of or registered_kickoff != input_kickoff:
            raise ReleaseGovernanceError("逐场记录时间与输入时间不一致")
        if registered_as_of >= registered_kickoff:
            raise ReleaseGovernanceError("逐场 prediction_as_of 不严格早于 kickoff，非赛前证明")

        audit = result.get("time_audit")
        if not isinstance(audit, dict):
            raise ReleaseGovernanceError("逐场时间审计缺失")
        expected_audit_times = {
            "registered_prediction_as_of": registered.get("prediction_as_of"),
            "input_prediction_as_of": stored_input.get("prediction_as_of"),
            "registered_kickoff": registered.get("kickoff"),
            "input_kickoff": stored_input.get("kickoff"),
        }
        if (audit.get("usable") is not True or audit.get("reason") is not None
                or any(audit.get(key) != value for key, value in expected_audit_times.items())
                or audit.get("prediction_before_kickoff") is not True
                or audit.get("evidence_after_prediction_as_of") is not False):
            raise ReleaseGovernanceError("逐场时间审计字段与实际时间关系不一致")

    hash_input = report.get("report_hash_input")
    expected_hash_input = {key: value for key, value in report.items() if key not in {
        "generated_at", "report_sha256", "report_hash_input", "attestation_path",
    }}
    if hash_input != expected_hash_input:
        raise ReleaseGovernanceError("证明内部哈希输入与报告内容不一致")
    try:
        internal_hash = hashlib.sha256(
            _canonical_json(hash_input).encode("utf-8")
        ).hexdigest()
    except (TypeError, ValueError) as exc:
        raise ReleaseGovernanceError("证明内部哈希输入无法规范化") from exc
    if report.get("report_sha256") != internal_hash:
        raise ReleaseGovernanceError("证明内部 SHA256 校验失败")

    return {
        "model_version": str(old_identity["model_version"]),
        "probability_signature": str(old_identity["probability_signature"]),
        "route": route,
        "alias_to_model_version": str(target_identity["model_version"]),
        "alias_to_probability_signature": str(target_identity["probability_signature"]),
    }


def validate_replay_attestation(report: dict[str, Any], *, previous_lock: dict[str, Any],
                                current_identity: dict[str, Any]) -> dict[str, Any]:
    """Validate a same-version signature migration before a lock may be replaced."""
    previous_mv, previous_sig = _identity_pair(previous_lock)
    current_mv, current_sig = _identity_pair(current_identity)
    if not previous_mv or not previous_sig or not current_mv or not current_sig:
        raise ReleaseGovernanceError("发布锁或当前身份缺少模型版本/概率签名")
    schema_version = report.get("schema_version")
    incomplete_verdicts = {"partial", "limited", "incomplete"}
    if schema_version != "fusion-probability-replay-2.0":
        raise ReleaseGovernanceError(
            "旧重放 schema 仅供只读展示；发布锁状态变更只接受完整 schema 2 证明"
        )
    total = report.get("records_total")
    selected = report.get("records_selected")
    if (not _is_non_negative_int(total) or not _is_non_negative_int(selected)
            or total != selected
            or report.get("is_complete_replay") is not True
            or str(report.get("verdict") or "") in incomplete_verdicts):
        raise ReleaseGovernanceError("重放证明不完整（partial/limited/incomplete），不得用于发布锁迁移")
    if str(report.get("verdict") or "") != "equivalent":
        raise ReleaseGovernanceError("重放报告显示数值不等价；必须升级模型版本")
    if str(report.get("replayed_model_version") or "") != current_mv:
        raise ReleaseGovernanceError("重放报告模型版本与当前发布身份不一致")
    report_current = report.get("current_identity") or {}
    if _identity_pair(report_current) != (current_mv, current_sig):
        raise ReleaseGovernanceError("重放报告当前身份与待锁定身份不一致")
    replayed_signatures = {str(item) for item in (report.get("replayed_probability_signatures") or [])}
    if previous_sig not in replayed_signatures:
        raise ReleaseGovernanceError("重放报告未覆盖旧发布锁概率签名")
    fields = {str(item) for item in (report.get("compare_fields") or [])}
    missing = sorted(set(REQUIRED_REPLAY_FIELDS) - fields)
    if missing:
        raise ReleaseGovernanceError("重放报告比较字段不完整：" + ",".join(missing))
    modes = {str(item) for item in (report.get("replayed_modes") or [])}
    if "market_only" not in modes:
        raise ReleaseGovernanceError("重放报告未覆盖 market_only 正式路由")
    counts = report.get("counts") or {}
    if int(counts.get("identical") or 0) < 1:
        raise ReleaseGovernanceError("重放报告没有可确认的完全一致样本")
    return {
        "previous_model_version": previous_mv,
        "previous_probability_signature": previous_sig,
        "replayed_probability_signatures": sorted(replayed_signatures),
        "replayed_modes": sorted(modes),
        "compare_fields": list(REQUIRED_REPLAY_FIELDS),
        "replay_verdict": "equivalent",
    }


def transition_release_lock(lock_path: Path, current_identity: dict[str, Any],
                            replay_report_path: Path | None = None) -> dict[str, Any]:
    """Write a release lock, requiring a complete replay proof for same-version drift."""
    lock_path = Path(lock_path)
    current_mv, current_sig = _identity_pair(current_identity)
    if not current_mv or not current_sig:
        raise ReleaseGovernanceError("当前身份缺少模型版本/概率签名，拒绝锁定")
    previous = _load_json(lock_path) if lock_path.exists() else None
    attestation = None
    if previous is not None:
        previous_mv, previous_sig = _identity_pair(previous)
        if previous_mv == current_mv and previous_sig != current_sig:
            if replay_report_path is None:
                raise ReleaseGovernanceError("同版本签名迁移必须提供重放证明")
            report = _load_json(Path(replay_report_path))
            attestation = validate_replay_attestation(
                report, previous_lock=previous, current_identity=current_identity)
            attestation["replay_report"] = str(Path(replay_report_path))
    payload: dict[str, Any] = {
        "model_version": current_mv,
        "probability_signature": current_sig,
        "locked_at": datetime.now(timezone.utc).isoformat(),
        "note": ("发布快照；发布窗口内禁止改概率文件。"
                 "同版本签名变化必须由完整数值重放证明。"),
    }
    if attestation is not None:
        payload["replay_attestation"] = attestation
    lock_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def assert_output_matches_release_lock(output_identity: dict[str, Any], lock_path: Path) -> None:
    """Defence in depth for callers that bypass fusion_cli and invoke fusion_record directly."""
    if not Path(lock_path).exists():
        raise ReleaseGovernanceError("无发布锁，拒绝正式登记")
    lock = _load_json(Path(lock_path))
    if _identity_pair(output_identity) != _identity_pair(lock):
        raise ReleaseGovernanceError("登记输出身份与发布锁不一致，拒绝正式登记")


def release_status(current_identity: dict[str, Any], lock_path: Path) -> dict[str, Any]:
    """Return a read-only lock status suitable for CLI and dashboard display."""
    current_mv, current_sig = _identity_pair(current_identity)
    if not Path(lock_path).exists():
        return {"status": "NO_LOCK", "current_model_version": current_mv,
                "current_probability_signature": current_sig[:12]}
    lock = _load_json(Path(lock_path))
    locked_mv, locked_sig = _identity_pair(lock)
    status = "LOCKED" if (locked_mv, locked_sig) == (current_mv, current_sig) else "DRIFT"
    return {
        "status": status,
        "current_model_version": current_mv,
        "current_probability_signature": current_sig[:12],
        "locked_model_version": locked_mv,
        "locked_probability_signature": locked_sig[:12],
        "replay_attestation": lock.get("replay_attestation"),
    }
