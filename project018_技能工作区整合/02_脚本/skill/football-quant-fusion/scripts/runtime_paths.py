"""Resolve canonical football-workspace paths without hardcoded user directories."""

from __future__ import annotations

import os
import hashlib
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


def legacy_core_scripts_dir() -> Path:
    """Location of the optional external physical core copy."""
    return Path(os.environ.get(
        "FUSION_LEGACY_CORE_DIR",
        Path.home() / ".codex" / "skills" / "football-quant-fusion-suite" /
        "skills" / "zu-yu-dashi-3" / "scripts",
    )).resolve()


def core_copy_status() -> dict:
    """Compare critical core files without modifying either copy."""
    repo, external = core_scripts_dir(), legacy_core_scripts_dir()
    critical = ("predict.py", "team_strength.py")
    mismatches: list[str] = []
    missing: list[str] = []
    hashes: dict[str, dict[str, str | None]] = {}
    for name in critical:
        row: dict[str, str | None] = {"repo": None, "external": None}
        for label, path in (("repo", repo / name), ("external", external / name)):
            if path.exists():
                row[label] = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[name] = row
        if row["repo"] is None or row["external"] is None:
            missing.append(name)
        elif row["repo"] != row["external"]:
            mismatches.append(name)
    status = "MATCH" if not mismatches and not missing else ("MISSING" if missing else "MISMATCH")
    return {"status": status, "repo": str(repo), "external": str(external),
            "critical_files": list(critical), "mismatches": mismatches,
            "missing": missing, "hashes": hashes}


def backtest_store() -> Path:
    return data_root() / "backtest"


def odds_store() -> Path:
    return data_root() / "odds" / "production_movement.jsonl"


def forward_work_dir() -> Path:
    return data_root() / "forward"


def late_info_store() -> Path:
    return data_root() / "late_info"


def is_legacy_suite_path(path: Path) -> bool:
    normalized = str(Path(path).resolve()).replace("\\", "/").lower()
    return "/.codex/skills/football-quant-fusion-suite/" in normalized


def assert_writable_target(path: Path, allow_legacy: bool = False) -> Path:
    resolved = Path(path).resolve()
    if is_legacy_suite_path(resolved) and not allow_legacy:
        raise ValueError(f"legacy fusion suite is read-only: {resolved}")
    return resolved


def validate_cli_paths(argv: list[str], *, allow_legacy: bool = False) -> list[Path]:
    """Validate path-valued CLI options before any delegated command runs.

    The guard is intentionally centralized so ``fusion_cli.py`` cannot be
    bypassed by passing an old external store explicitly. Values are returned
    for diagnostics/tests; callers may ignore the list.
    """
    paths: list[Path] = []
    path_options = {"--store", "--odds-store", "--work-dir"}
    for index, value in enumerate(argv):
        if value not in path_options or index + 1 >= len(argv):
            continue
        paths.append(assert_writable_target(Path(argv[index + 1]), allow_legacy=allow_legacy))
    return paths
