from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "task7_acceptance_evidence.py"
SPEC = importlib.util.spec_from_file_location("task7_acceptance_evidence", SCRIPT_PATH)
evidence = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(evidence)


def test_baseline_is_exclusive_and_cannot_be_manually_rewritten(tmp_path):
    immutable = tmp_path / "immutable.json"
    immutable.write_text('{"value":1}\n', encoding="utf-8")
    baseline = tmp_path / "baseline.json"

    first = evidence.write_baseline([immutable], baseline, run_id="run-1")
    before = baseline.read_bytes()

    with pytest.raises(FileExistsError):
        evidence.write_baseline([immutable], baseline, run_id="run-1-correction")
    assert baseline.read_bytes() == before
    assert first["generated_at"]
    assert first["files"] == [{
        "path": str(immutable.resolve()),
        "sha256": evidence.sha256_file(immutable),
        "size_bytes": immutable.stat().st_size,
    }]


def test_runner_records_raw_streams_timing_exit_code_and_command_hash(tmp_path):
    immutable = tmp_path / "immutable.txt"
    immutable.write_text("unchanged\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "run_id": "strict-run",
        "immutable_paths": [str(immutable)],
        "commands": [{
            "name": "expected-rejection",
            "argv": [
                sys.executable, "-c",
                "import sys; print('raw-out'); print('raw-error', file=sys.stderr); raise SystemExit(1)",
            ],
            "cwd": str(tmp_path),
            "expected_exit_codes": [1],
        }],
    }), encoding="utf-8")

    assert evidence.main(["--config", str(config), "--output-dir", str(run_dir)]) == 0

    baseline = json.loads((run_dir / "baseline.json").read_text(encoding="utf-8"))
    plan = json.loads((run_dir / "command_plan.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "command_manifest.json").read_text(encoding="utf-8"))
    post = json.loads((run_dir / "post_hashes.json").read_text(encoding="utf-8"))
    result = manifest["commands"][0]
    assert baseline["generated_at"]
    assert plan["commands"][0]["command_sha256"] == result["command_sha256"]
    assert result["started_at"] and result["ended_at"]
    assert result["exit_code"] == 1
    assert result["exit_code_expected"] is True
    assert (run_dir / result["stdout_path"]).read_text(encoding="utf-8").strip() == "raw-out"
    assert (run_dir / result["stderr_path"]).read_text(encoding="utf-8").strip() == "raw-error"
    assert result["stdout_sha256"] == evidence.sha256_file(run_dir / result["stdout_path"])
    assert result["stderr_sha256"] == evidence.sha256_file(run_dir / result["stderr_path"])
    assert post["generated_at"]
    assert post["all_unchanged"] is True
    assert post["files"] == [{
        "path": str(immutable.resolve()),
        "before_sha256": baseline["files"][0]["sha256"],
        "after_sha256": baseline["files"][0]["sha256"],
        "unchanged": True,
        "before_size_bytes": immutable.stat().st_size,
        "after_size_bytes": immutable.stat().st_size,
    }]


def test_runner_fails_when_command_exit_is_unexpected_but_still_writes_post_hashes(tmp_path):
    immutable = tmp_path / "immutable.txt"
    immutable.write_text("unchanged\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "run_id": "failed-run",
        "immutable_paths": [str(immutable)],
        "commands": [{
            "name": "unexpected-failure",
            "argv": [sys.executable, "-c", "raise SystemExit(2)"],
            "cwd": str(tmp_path),
            "expected_exit_codes": [0],
        }],
    }), encoding="utf-8")
    run_dir = tmp_path / "run"

    assert evidence.main(["--config", str(config), "--output-dir", str(run_dir)]) == 1
    result = json.loads(
        (run_dir / "command_manifest.json").read_text(encoding="utf-8")
    )["commands"][0]
    assert result["exit_code"] == 2
    assert result["exit_code_expected"] is False
    assert (run_dir / "post_hashes.json").is_file()


def test_runner_fails_closed_when_an_immutable_file_changes(tmp_path):
    immutable = tmp_path / "immutable.txt"
    immutable.write_text("before\n", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "run_id": "drift-run",
        "immutable_paths": [str(immutable)],
        "commands": [{
            "name": "mutator",
            "argv": [
                sys.executable, "-c",
                "from pathlib import Path; Path('immutable.txt').write_text('after\\n')",
            ],
            "cwd": str(tmp_path),
            "expected_exit_codes": [0],
        }],
    }), encoding="utf-8")
    run_dir = tmp_path / "run"

    assert evidence.main(["--config", str(config), "--output-dir", str(run_dir)]) == 1
    post = json.loads((run_dir / "post_hashes.json").read_text(encoding="utf-8"))
    assert post["all_unchanged"] is False
    assert post["files"][0]["unchanged"] is False
