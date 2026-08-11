from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


MODULE = Path(__file__).with_name("run_workspace_tests.py")


def load_runner():
    spec = importlib.util.spec_from_file_location("workspace_test_runner", MODULE)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_required_pytest_suite_runs_from_its_own_working_directory(tmp_path):
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_cwd.py").write_text(
        "from pathlib import Path\n"
        "def test_cwd():\n"
        "    assert Path.cwd().name == 'suite'\n",
        encoding="utf-8",
    )
    manifest = {"suites": [{"id": "active", "kind": "pytest", "cwd": "suite", "required": True}]}

    report = load_runner().run_manifest(manifest, tmp_path)

    assert report["ok"] is True
    assert report["summary"] == {"passed": 1, "failed": 0, "archived_failures": 0}
    assert report["suites"][0]["status"] == "PASS"


def test_archived_failure_is_reported_without_being_called_a_pass(tmp_path):
    manifest = {
        "suites": [{
            "id": "archive",
            "kind": "command",
            "cwd": ".",
            "command": ["-c", "import sys; sys.exit(1)"],
            "required": False,
        }]
    }

    report = load_runner().run_manifest(manifest, tmp_path)

    assert report["ok"] is True
    assert report["summary"] == {"passed": 0, "failed": 0, "archived_failures": 1}
    assert report["suites"][0]["status"] == "ARCHIVED_FAILURE"


def test_default_root_is_the_workspace_containing_project020():
    assert load_runner().default_root() == MODULE.parents[2]


def test_cli_writes_requested_json_report(tmp_path):
    manifest = tmp_path / "manifest.json"
    report = tmp_path / "report.json"
    manifest.write_text(json.dumps({"suites": []}), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(MODULE), "--root", str(tmp_path), "--manifest", str(manifest), "--report", str(report)],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0
    assert json.loads(report.read_text(encoding="utf-8"))["summary"] == {"passed": 0, "failed": 0, "archived_failures": 0}


def test_command_suite_reads_its_json_summary_not_only_exit_code(tmp_path):
    (tmp_path / "engine.json").write_text(json.dumps({"summary": {"fail": 1}}), encoding="utf-8")
    manifest = {
        "suites": [{
            "id": "archive",
            "kind": "command",
            "cwd": ".",
            "command": ["-c", "pass"],
            "result_report": "engine.json",
            "required": False,
        }]
    }

    report = load_runner().run_manifest(manifest, tmp_path)

    assert report["suites"][0]["returncode"] == 0
    assert report["suites"][0]["status"] == "ARCHIVED_FAILURE"
