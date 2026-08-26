#!/usr/bin/env python3
"""Create immutable Task 7 baselines and raw, independently verifiable command evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def _file_record(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve(strict=True)
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def write_baseline(paths: list[Path], output_path: Path, *, run_id: str) -> dict[str, Any]:
    payload = {
        "schema_version": "task7-immutable-baseline-1.0",
        "run_id": run_id,
        "generated_at": utc_now(),
        "files": [_file_record(Path(path)) for path in paths],
    }
    _write_json_exclusive(Path(output_path), payload)
    return payload


def _command_definition(command: dict[str, Any]) -> dict[str, Any]:
    argv = command.get("argv")
    cwd = command.get("cwd")
    expected = command.get("expected_exit_codes", [0])
    env = command.get("env", {})
    if (not isinstance(command.get("name"), str) or not command["name"].strip()
            or not isinstance(argv, list) or not argv
            or not all(isinstance(item, str) for item in argv)
            or not isinstance(cwd, str) or not cwd
            or not isinstance(expected, list) or not expected
            or not all(type(item) is int for item in expected)
            or not isinstance(env, dict)
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in env.items())):
        raise ValueError(f"invalid command definition: {command!r}")
    core = {
        "name": command["name"],
        "argv": argv,
        "cwd": str(Path(cwd).resolve()),
        "expected_exit_codes": expected,
        "env": env,
    }
    return {**core, "command_sha256": sha256_bytes(canonical_json(core).encode("utf-8"))}


def _safe_name(index: int, name: str) -> str:
    filtered = "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
    return f"{index:02d}_{filtered or 'command'}"


def run_command(command: dict[str, Any], output_dir: Path, index: int) -> dict[str, Any]:
    definition = _command_definition(command)
    stem = _safe_name(index, definition["name"])
    raw_dir = Path(output_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / f"{stem}.stdout.txt"
    stderr_path = raw_dir / f"{stem}.stderr.txt"
    environment = os.environ.copy()
    environment.update(definition["env"])
    started_at = utc_now()
    completed = subprocess.run(
        definition["argv"], cwd=definition["cwd"], env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    ended_at = utc_now()
    stdout_path.write_bytes(completed.stdout)
    stderr_path.write_bytes(completed.stderr)
    return {
        **definition,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit_code": completed.returncode,
        "exit_code_expected": completed.returncode in definition["expected_exit_codes"],
        "stdout_path": str(stdout_path.relative_to(output_dir)),
        "stderr_path": str(stderr_path.relative_to(output_dir)),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
    }


def write_post_hashes(baseline: dict[str, Any], output_path: Path) -> dict[str, Any]:
    files = []
    for before in baseline["files"]:
        path = Path(before["path"])
        exists = path.is_file()
        after_hash = sha256_file(path) if exists else None
        after_size = path.stat().st_size if exists else None
        files.append({
            "path": before["path"],
            "before_sha256": before["sha256"],
            "after_sha256": after_hash,
            "unchanged": exists and after_hash == before["sha256"],
            "before_size_bytes": before["size_bytes"],
            "after_size_bytes": after_size,
        })
    payload = {
        "schema_version": "task7-post-hashes-1.0",
        "run_id": baseline["run_id"],
        "generated_at": utc_now(),
        "all_unchanged": all(item["unchanged"] for item in files),
        "files": files,
    }
    _write_json_exclusive(Path(output_path), payload)
    return payload


def run(config_path: Path, output_dir: Path) -> int:
    config_bytes = Path(config_path).read_bytes()
    config = json.loads(config_bytes.decode("utf-8-sig"))
    if not isinstance(config, dict) or not isinstance(config.get("run_id"), str):
        raise ValueError("config must contain run_id")
    immutable_paths = config.get("immutable_paths")
    commands = config.get("commands")
    if not isinstance(immutable_paths, list) or not isinstance(commands, list) or not commands:
        raise ValueError("config must contain immutable_paths and commands")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # This exclusive baseline is deliberately the first run artifact and is
    # never reopened for writing.  Corrections belong in a separate sidecar.
    baseline = write_baseline(
        [Path(item) for item in immutable_paths], output_dir / "baseline.json",
        run_id=config["run_id"],
    )
    definitions = [_command_definition(command) for command in commands]
    plan = {
        "schema_version": "task7-command-plan-1.0",
        "run_id": config["run_id"],
        "generated_at": utc_now(),
        "config_path": str(Path(config_path).resolve()),
        "config_sha256": sha256_bytes(config_bytes),
        "commands": definitions,
    }
    _write_json_exclusive(output_dir / "command_plan.json", plan)

    results = [run_command(command, output_dir, index)
               for index, command in enumerate(commands, start=1)]
    manifest = {
        "schema_version": "task7-command-manifest-1.0",
        "run_id": config["run_id"],
        "generated_at": utc_now(),
        "all_exit_codes_expected": all(item["exit_code_expected"] for item in results),
        "commands": results,
    }
    _write_json_exclusive(output_dir / "command_manifest.json", manifest)
    post = write_post_hashes(baseline, output_dir / "post_hashes.json")
    return 0 if manifest["all_exit_codes_expected"] and post["all_unchanged"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 Task 7 不可变基线与原始命令证据")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        return run(Path(args.config), Path(args.output_dir))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "REJECTED", "reason": str(exc)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
