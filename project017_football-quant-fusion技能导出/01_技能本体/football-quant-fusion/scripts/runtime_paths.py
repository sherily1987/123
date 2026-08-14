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
