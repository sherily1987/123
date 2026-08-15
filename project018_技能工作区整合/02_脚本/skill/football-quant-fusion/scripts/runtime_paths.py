"""Resolve canonical football-workspace paths without hardcoded user directories."""

from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def workspace_root() -> Path:
    return Path(os.environ.get("FUSION_WORKSPACE_ROOT", project_root().parent)).resolve()


def data_root() -> Path:
    return Path(os.environ.get(
        "FUSION_DATA_ROOT",
        project_root() / "04_素材" / "shared-data" / "football-quant-fusion",
    )).resolve()


def core_scripts_dir() -> Path:
    return Path(os.environ.get(
        "FUSION_CORE_DIR",
        project_root() / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts",
    )).resolve()


def backtest_store() -> Path:
    return data_root() / "backtest"


def odds_store() -> Path:
    return data_root() / "odds" / "production_movement.jsonl"


def forward_work_dir() -> Path:
    return data_root() / "forward"


def is_legacy_suite_path(path: Path) -> bool:
    normalized = str(Path(path).resolve()).replace("\\", "/").lower()
    return "/.codex/skills/football-quant-fusion-suite/" in normalized


def assert_writable_target(path: Path, allow_legacy: bool = False) -> Path:
    resolved = Path(path).resolve()
    if is_legacy_suite_path(resolved) and not allow_legacy:
        raise ValueError(f"legacy fusion suite is read-only: {resolved}")
    return resolved
