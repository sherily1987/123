"""Shared release-lock checks for formal football-quant-fusion registration."""
from __future__ import annotations

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


def validate_replay_attestation(report: dict[str, Any], *, previous_lock: dict[str, Any],
                                current_identity: dict[str, Any]) -> dict[str, Any]:
    """Validate a same-version signature migration before a lock may be replaced."""
    previous_mv, previous_sig = _identity_pair(previous_lock)
    current_mv, current_sig = _identity_pair(current_identity)
    if not previous_mv or not previous_sig or not current_mv or not current_sig:
        raise ReleaseGovernanceError("发布锁或当前身份缺少模型版本/概率签名")
    schema_version = report.get("schema_version")
    incomplete_verdicts = {"partial", "limited", "incomplete"}
    if schema_version == "fusion-probability-replay-2.0":
        total = report.get("records_total")
        selected = report.get("records_selected")
        if (not _is_non_negative_int(total) or not _is_non_negative_int(selected)
                or total != selected
                or report.get("is_complete_replay") is not True
                or str(report.get("verdict") or "") in incomplete_verdicts):
            raise ReleaseGovernanceError("重放证明不完整（partial/limited/incomplete），不得用于发布锁迁移")
    elif schema_version not in (None, "", "fusion-probability-replay-1.0"):
        raise ReleaseGovernanceError(f"不支持的重放证明 schema：{schema_version}")
    # Genuine historical reports may predate explicit coverage fields, but a
    # legacy report that does declare itself incomplete still fails closed.
    elif (report.get("is_complete_replay") is False
          or str(report.get("verdict") or "") in incomplete_verdicts):
        raise ReleaseGovernanceError("重放证明不完整（partial/limited），不得用于发布锁迁移")
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
