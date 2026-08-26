#!/usr/bin/env python3
"""Approve and revalidate route-scoped probability-signature aliases.

Aliases can only be materialized from a complete Task 2 attestation.  Loading
is deliberately fail-closed: every call re-hashes the immutable proof and
checks its target against the current release lock.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from release_governance import (ReleaseGovernanceError,
                                validate_grouped_alias_attestation)


SCHEMA_VERSION = "probability-aliases-1.0"
SKILL_ROOT = Path(__file__).resolve().parents[1]
MANAGED_ALIAS_PATH = SKILL_ROOT / "config" / "probability_aliases.json"
MANAGED_RELEASE_LOCK_PATH = SKILL_ROOT / "config" / "release_lock.json"


class ProbabilityAliasError(RuntimeError):
    """An attestation cannot be approved as an exact probability alias."""


def _read_object(path: Path, *, purpose: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError) as exc:
        raise ProbabilityAliasError(f"无法读取{purpose}：{path}") from exc
    if not isinstance(value, dict):
        raise ProbabilityAliasError(f"{purpose}不是 JSON 对象：{path}")
    return value


def _is_sha256(value: Any) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value.lower()))


def _lock_identity(lock: dict[str, Any]) -> dict[str, str]:
    model_version = lock.get("model_version")
    signature = lock.get("probability_signature")
    if not isinstance(model_version, str) or not model_version.strip() or not _is_sha256(signature):
        raise ProbabilityAliasError("当前发布锁缺少完整模型身份")
    return {"model_version": model_version, "probability_signature": signature}


def _proof_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise ProbabilityAliasError(f"无法计算证明文件 SHA256：{path}") from exc


def _validated_proof(report_path: Path, lock_path: Path) -> tuple[dict[str, str], str]:
    report_path = Path(report_path).resolve()
    report = _read_object(report_path, purpose="重放证明")
    lock = _lock_identity(_read_object(Path(lock_path), purpose="发布锁"))
    declared_path = report.get("attestation_path")
    if not isinstance(declared_path, str):
        raise ProbabilityAliasError("证明缺少 attestation_path")
    try:
        if Path(declared_path).resolve() != report_path:
            raise ProbabilityAliasError("证明 attestation_path 与审批文件不一致")
    except OSError as exc:
        raise ProbabilityAliasError("证明 attestation_path 无法解析") from exc
    try:
        identity = validate_grouped_alias_attestation(report, current_identity=lock)
    except ReleaseGovernanceError as exc:
        raise ProbabilityAliasError(str(exc)) from exc
    return identity, _proof_sha256(report_path)


def _read_alias_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "aliases": []}
    payload = _read_object(path, purpose="概率别名清单")
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(payload.get("aliases"), list):
        raise ProbabilityAliasError("概率别名清单 schema 无效")
    return payload


def approve_attestation(report_path: Path, alias_path: Path, lock_path: Path) -> dict:
    """Approve one complete PENDING_REVIEW proof without accepting raw keys."""
    report_path = Path(report_path).resolve()
    identity, proof_hash = _validated_proof(report_path, Path(lock_path))
    approved = {
        "status": "EQUIVALENT_ALIAS",
        **identity,
        "attestation_path": str(report_path),
        "attestation_sha256": proof_hash,
    }
    alias_path = Path(alias_path)
    document = _read_alias_document(alias_path)
    key = (approved["model_version"], approved["probability_signature"], approved["route"])
    kept = []
    for item in document["aliases"]:
        if not isinstance(item, dict):
            continue
        item_key = (item.get("model_version"), item.get("probability_signature"), item.get("route"))
        if item_key != key:
            kept.append(item)
    kept.append(approved)
    kept.sort(key=lambda item: (
        str(item.get("model_version") or ""),
        str(item.get("probability_signature") or ""),
        str(item.get("route") or ""),
    ))
    document = {"schema_version": SCHEMA_VERSION, "aliases": kept}
    alias_path.parent.mkdir(parents=True, exist_ok=True)
    alias_path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return approved


def _entry_matches_proof(entry: dict[str, Any], proof_identity: dict[str, str], proof_hash: str) -> bool:
    expected = {
        "model_version": proof_identity["model_version"],
        "probability_signature": proof_identity["probability_signature"],
        "route": proof_identity["route"],
        "alias_to_model_version": proof_identity["alias_to_model_version"],
        "alias_to_probability_signature": proof_identity["alias_to_probability_signature"],
    }
    return (entry.get("status") == "EQUIVALENT_ALIAS"
            and all(entry.get(key) == value for key, value in expected.items())
            and entry.get("attestation_sha256") == proof_hash)


def load_approved_aliases(alias_path: Path, lock_path: Path) -> list[dict]:
    """Load only aliases whose proof and release target are valid right now."""
    try:
        document = _read_alias_document(Path(alias_path))
        # Validate the lock even for an empty list, so malformed governance
        # state cannot be mistaken for a healthy empty configuration.
        _lock_identity(_read_object(Path(lock_path), purpose="发布锁"))
    except ProbabilityAliasError:
        return []
    approved = []
    seen = set()
    for entry in document["aliases"]:
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("attestation_path")
        if not isinstance(path_value, str) or not _is_sha256(entry.get("attestation_sha256")):
            continue
        try:
            proof_identity, proof_hash = _validated_proof(Path(path_value), Path(lock_path))
        except ProbabilityAliasError:
            continue
        if not _entry_matches_proof(entry, proof_identity, proof_hash):
            continue
        key = (entry["model_version"], entry["probability_signature"], entry["route"])
        if key in seen:
            continue
        seen.add(key)
        approved.append(dict(entry))
    return approved


def _registered_route(row: dict[str, Any]) -> str | None:
    values = []
    for container in (row, row.get("model") or {}, row.get("input") or {}):
        if isinstance(container, dict):
            value = container.get("route") or container.get("mode")
            if value not in (None, ""):
                if not isinstance(value, str):
                    return None
                values.append(value.strip())
    if not values or not values[0] or any(value != values[0] for value in values):
        return None
    return values[0]


def matches(row: dict[str, Any], approved_alias: dict[str, Any]) -> bool:
    """Return whether a registered row matches one exact approved alias key."""
    model = row.get("model") if isinstance(row.get("model"), dict) else row
    model_version = model.get("model_version")
    signature = model.get("probability_signature")
    return (
        isinstance(model_version, str)
        and isinstance(signature, str)
        and model_version == approved_alias.get("model_version")
        and signature == approved_alias.get("probability_signature")
        and _registered_route(row) == approved_alias.get("route")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从完整重放证明审批精确概率别名")
    parser.add_argument("--attestation", required=True)
    args = parser.parse_args(argv)
    try:
        approved = approve_attestation(
            Path(args.attestation), MANAGED_ALIAS_PATH, MANAGED_RELEASE_LOCK_PATH,
        )
    except ProbabilityAliasError as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(approved, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
