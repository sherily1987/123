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


def build_identity(project_dir: Path, runtime_files) -> str:
    """Bind a service identity to both its formal path and controlled code bytes."""
    project_dir = Path(project_dir).resolve()
    digest = hashlib.sha256()
    digest.update(f"project023-web-workbench\0{project_dir}\0".encode("utf-8"))
    for path in sorted((Path(item).resolve() for item in runtime_files), key=lambda item: str(item).casefold()):
        try:
            label = path.relative_to(project_dir).as_posix()
        except ValueError:
            label = path.name
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return "b3:" + digest.hexdigest()[:24]


RUNTIME_IDENTITY_FILES = [
    SCRIPT_DIR / name
    for name in (
        "app.py", "db.py", "launch.py", "workbench_runtime.py", "runner.py",
        "store_view.py", "daily_strategy_view.py", "static/index.html",
    )
]
RUNTIME_IDENTITY_FILES.extend(sorted((SCRIPT_DIR / "static" / "js").rglob("*.js")))
BUILD_IDENTITY = build_identity(PROJECT_DIR, RUNTIME_IDENTITY_FILES)
PROCESS_ID = os.getpid()
