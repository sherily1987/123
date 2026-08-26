import subprocess
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import fusion_cli


def test_top_level_help_lists_supported_commands():
    script = Path(__file__).parents[1] / "scripts" / "fusion_cli.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"], text=True, capture_output=True, check=False
    )

    assert completed.returncode == 0
    assert "record" in completed.stdout
    assert "backtest" in completed.stdout
    assert "hybrid-evaluate" in completed.stdout
    assert "odds-intl-capture" in completed.stdout
    assert "draw-watch-evaluate" in completed.stdout
    assert "draw-ttg-shadow-research" in completed.stdout
    assert "strategy-plan" in completed.stdout
    assert "independent-market-shadow" in completed.stdout
    assert "version-admission" in completed.stdout
    assert "direction-governance-report" in completed.stdout
    assert "signature-replay" in completed.stdout
    assert "signature-alias-approve" in completed.stdout


def test_direction_governance_report_routes_to_read_only_version_progress(monkeypatch):
    calls = []
    monkeypatch.setattr(sys, "argv", [
        "fusion_cli.py", "direction-governance-report", "--store", "audit-store",
    ])
    monkeypatch.setattr(fusion_cli, "validate_cli_paths", lambda _rest: [])
    monkeypatch.setattr(fusion_cli, "core_copy_status", lambda: {"status": "MATCH"})
    monkeypatch.setattr(fusion_cli, "run_script", lambda script, rest: calls.append((script, rest)))

    fusion_cli.main()

    assert calls == [("version_progress.py", [
        "--direction-governance-report", "--store", "audit-store",
    ])]


@pytest.mark.parametrize(("command", "script"), [
    ("signature-replay", "signature_drift_governance.py"),
    ("signature-alias-approve", "probability_aliases.py"),
])
def test_signature_governance_commands_route_to_dedicated_scripts(
        monkeypatch, command, script):
    calls = []
    monkeypatch.setattr(sys, "argv", ["fusion_cli.py", command, "--example", "value"])
    monkeypatch.setattr(fusion_cli, "validate_cli_paths", lambda _rest: [])
    monkeypatch.setattr(fusion_cli, "core_copy_status", lambda: {"status": "MATCH"})
    monkeypatch.setattr(fusion_cli, "run_script", lambda name, rest: calls.append((name, rest)))

    fusion_cli.main()

    assert calls == [(script, ["--example", "value"])]


def test_production_record_release_lock_gate_fails_closed(monkeypatch):
    class Result:
        returncode = 1
        stdout = "{\"status\":\"VIOLATION\"}"
        stderr = ""

    monkeypatch.setattr(fusion_cli.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(SystemExit, match="发布锁"):
        fusion_cli.assert_release_lock_clean()


def test_record_checks_release_lock_before_running_prediction(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fusion_cli.py", "record", "--input", "m.json", "--output", "o.json"])

    def blocked():
        raise SystemExit("发布锁审计未通过")

    monkeypatch.setattr(fusion_cli, "assert_release_lock_clean", blocked)
    monkeypatch.setattr(fusion_cli, "record_fusion", lambda _rest: pytest.fail("record must not run before lock check"))

    with pytest.raises(SystemExit, match="发布锁"):
        fusion_cli.main()
