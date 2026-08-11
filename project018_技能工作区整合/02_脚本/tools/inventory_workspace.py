"""生成迁移来源的只读 SHA-256 清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable


EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path


def inventory(sources: dict[str, Path]) -> dict:
    files: list[dict] = []
    unreadable: list[dict] = []
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)

    for name, root in sorted(sources.items()):
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f"source is not a directory: {name}={root}")
        for path in _files(root):
            relative = path.relative_to(root).as_posix()
            try:
                size = path.stat().st_size
                digest = _sha256(path)
            except OSError as error:
                unreadable.append({"source": name, "path": relative, "error": str(error)})
                continue
            record = {"source": name, "path": relative, "size": size, "sha256": digest}
            files.append(record)
            groups[(digest, size)].append({"source": name, "path": relative})

    duplicate_groups = [
        {"sha256": digest, "size": size, "files": records}
        for (digest, size), records in sorted(groups.items())
        if len(records) > 1
    ]
    return {
        "schema": "football-workspace-inventory-1.0",
        "sources": {name: str(Path(path).resolve()) for name, path in sorted(sources.items())},
        "files": files,
        "duplicate_groups": duplicate_groups,
        "unreadable": unreadable,
    }


def _parse_source(value: str) -> tuple[str, Path]:
    try:
        name, raw_path = value.split("=", 1)
    except ValueError as error:
        raise argparse.ArgumentTypeError("source must use NAME=ABSOLUTE_PATH") from error
    path = Path(raw_path)
    if not name or not path.is_absolute():
        raise argparse.ArgumentTypeError("source must use NAME=ABSOLUTE_PATH")
    return name, path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a read-only migration inventory")
    parser.add_argument("--source", action="append", type=_parse_source, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sources = dict(args.source)
    report = inventory(sources)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
