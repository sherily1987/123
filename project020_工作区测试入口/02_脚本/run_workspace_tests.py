from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_manifest(manifest: dict, root: Path) -> dict:
    results = []
    for suite in manifest["suites"]:
        cwd = (root / suite["cwd"]).resolve()
        if suite["kind"] == "pytest":
            command = [sys.executable, "-m", "pytest", "-q", suite.get("target", ".")]
        else:
            command = [sys.executable, *suite["command"]]
        command = [part.format(root=str(root)) for part in command]
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
        required = suite.get("required", True)
        engine_summary = None
        engine_failed = False
        if suite.get("result_report"):
            report_path = root / suite["result_report"].format(root=str(root))
            engine_summary = json.loads(report_path.read_text(encoding="utf-8"))["summary"]
            engine_failed = int(engine_summary.get("fail", 0)) > 0
        status = "PASS" if completed.returncode == 0 and not engine_failed else ("FAIL" if required else "ARCHIVED_FAILURE")
        results.append({
            "id": suite["id"],
            "required": required,
            "status": status,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "archive_reason": suite.get("archive_reason"),
            "engine_summary": engine_summary,
        })
    summary = {
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] == "FAIL" for item in results),
        "archived_failures": sum(item["status"] == "ARCHIVED_FAILURE" for item in results),
    }
    return {"ok": summary["failed"] == 0, "summary": summary, "suites": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run independent workspace test suites without cross-project imports.")
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("workspace_test_manifest.json"))
    parser.add_argument("--report", type=Path, help="Optional JSON report destination.")
    args = parser.parse_args()
    report = run_manifest(json.loads(args.manifest.read_text(encoding="utf-8")), args.root.resolve())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
