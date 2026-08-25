"""Stable process identity shared by the B3 server and its launcher.

The identity is deliberately tied to the resolved project checkout.  A B3
service from another checkout therefore cannot be adopted or stopped merely
because it exposes the same generic UI version.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent.resolve()
PRIMARY_WORKSPACE_ROOT = SCRIPT_DIR.parents[1].resolve()
FUSION_SCRIPTS = (
    PRIMARY_WORKSPACE_ROOT / "project018_技能工作区整合" / "02_脚本" /
    "skill" / "football-quant-fusion" / "scripts"
)
assert ".worktrees" not in str(PROJECT_DIR)
BUILD_IDENTITY = "b3:" + hashlib.sha256(
    f"project023-web-workbench\0{PROJECT_DIR}".encode("utf-8")
).hexdigest()[:24]
PROCESS_ID = os.getpid()
