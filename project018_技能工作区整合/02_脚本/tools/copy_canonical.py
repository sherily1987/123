"""安全复制迁移来源：仅复制新文件，绝不覆盖字节不同的目标文件。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


EXCLUDED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_files(source: Path):
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.is_file() and not path.is_symlink():
            yield path, relative


def copy_canonical(source: Path, destination: Path) -> dict:
    source = Path(source).resolve()
    destination = Path(destination).resolve()
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    destination.mkdir(parents=True, exist_ok=True)
    result = {"source": str(source), "destination": str(destination), "copied": 0, "skipped": 0, "conflicted": 0, "excluded": 0, "conflicts": []}

    for source_path, relative in _source_files(source):
        target = destination / relative
        if target.exists():
            if target.is_file() and _sha256(source_path) == _sha256(target):
                result["skipped"] += 1
            else:
                result["conflicted"] += 1
                result["conflicts"].append(relative.as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target)
        if _sha256(source_path) != _sha256(target):
            raise OSError(f"copy verification failed: {relative}")
        result["copied"] += 1
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Copy a source into canonical workspace without overwriting conflicts")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    result = copy_canonical(args.source, args.destination)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if result["conflicted"]:
        raise SystemExit(f"copy stopped with {result['conflicted']} conflicts")


if __name__ == "__main__":
    main()
