"""Read-only drift detection for football-quant-fusion skill mirrors."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PRIMARY_PATH = Path(r"C:\Users\Administrator\.codex\skills\football-quant-fusion")
DEFAULT_MIRROR_PATH = Path(
    r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_files(root: Path) -> dict[str, str]:
    """Return allowed skill files keyed by their POSIX relative paths."""
    candidates = [root / "SKILL.md"]
    for directory, pattern in (("scripts", "*.py"), ("config", "*.json")):
        base = root / directory
        if base.is_dir():
            candidates.extend(path for path in base.glob(pattern) if path.is_file())

    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(candidates, key=lambda item: item.relative_to(root).as_posix())
        if path.is_file()
    }


def compare_trees(primary: str | Path, mirror: str | Path) -> dict[str, Any]:
    """Compare the tracked files in two skill trees without modifying either tree."""
    primary_root = Path(primary)
    mirror_root = Path(mirror)
    for label, root in (("primary", primary_root), ("mirror", mirror_root)):
        if not root.is_dir():
            raise ValueError(f"{label} path is not a directory: {root}")

    primary_files = _tracked_files(primary_root)
    mirror_files = _tracked_files(mirror_root)
    shared_paths = sorted(primary_files.keys() & mirror_files.keys())
    same_files = {
        relative_path: primary_files[relative_path]
        for relative_path in shared_paths
        if primary_files[relative_path] == mirror_files[relative_path]
    }
    different_files = {
        relative_path: {
            "primary_sha256": primary_files[relative_path],
            "mirror_sha256": mirror_files[relative_path],
        }
        for relative_path in shared_paths
        if primary_files[relative_path] != mirror_files[relative_path]
    }
    only_primary = sorted(primary_files.keys() - mirror_files.keys())
    only_mirror = sorted(mirror_files.keys() - primary_files.keys())
    is_same = not different_files and not only_primary and not only_mirror

    return {
        "status": "same" if is_same else "different",
        "primary_path": str(primary_root),
        "mirror_path": str(mirror_root),
        "same_files": same_files,
        "different_files": different_files,
        "only_primary": only_primary,
        "only_mirror": only_mirror,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("primary", nargs="?", type=Path, default=DEFAULT_PRIMARY_PATH)
    parser.add_argument("mirror", nargs="?", type=Path, default=DEFAULT_MIRROR_PATH)
    arguments = parser.parse_args(argv)

    try:
        result = compare_trees(arguments.primary, arguments.mirror)
    except ValueError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False), file=sys.stdout)
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "same" else 1


if __name__ == "__main__":
    raise SystemExit(main())
