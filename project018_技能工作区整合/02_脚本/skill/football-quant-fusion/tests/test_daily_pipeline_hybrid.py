import importlib.util
import json
import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("fusion_daily_pipeline", SCRIPTS / "fusion_daily_pipeline.py")
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(pipeline)


def test_hybrid_shadow_uses_the_exact_collected_batch_and_sales_day(monkeypatch, tmp_path):
    """保护：双轨必须共享同一次采集市场快照，不能用隔日输入补跑。"""
    batch = tmp_path / "inputs_T-7h.json"
    batch.write_text(json.dumps({"matches": []}), encoding="utf-8")
    seen = []

    def fake_run(command, retries=0):
        seen.append((command, retries))
        return type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"research_only": True, "n": 2, "ok": 1, "skipped": 1}),
            "stderr": "",
        })()

    monkeypatch.setattr(pipeline, "run", fake_run)

    report = pipeline.run_hybrid_shadow(batch, "2026-08-23", tmp_path, "T-7h")

    command, retries = seen[0]
    assert command[0].name == "hybrid_shadow.py"
    assert command[command.index("--input") + 1] == batch
    assert command[command.index("--sales-day") + 1] == "2026-08-23"
    assert retries == 0
    assert report == {"status": "ok", "n": 2, "ok": 1, "skipped": 1,
                      "output": str(tmp_path / "hybrid_T-7h.json")}


def test_half_time_research_captures_then_enriches_without_touching_settlement(monkeypatch, tmp_path):
    seen = []
    fixtures = tmp_path / "research" / "half-time-fixtures" / "apifootball" / "fixtures.json"

    def fake_run(command, retries=0):
        seen.append((command, retries))
        if command[0].name == "collect_half_time_apifootball.py":
            fixtures.parent.mkdir(parents=True, exist_ok=True)
            fixtures.write_text("[]", encoding="utf-8")
            payload = {"status": "ok", "fixtures": str(fixtures), "provider_rows": 3}
        elif command[0].name == "half_time_enrichment.py":
            payload = {"status": "ok", "rows": 2, "verified": 1}
        else:
            raise AssertionError(command)
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr(pipeline, "run", fake_run)

    report = pipeline.run_half_time_research(tmp_path / "backtest")

    assert report == {"status": "ok", "provider_rows": 3, "rows": 2, "verified": 1}
    capture, enrich = [entry[0] for entry in seen]
    assert capture[0].name == "collect_half_time_apifootball.py"
    assert enrich[0].name == "half_time_enrichment.py"
    assert enrich[enrich.index("--fixtures") + 1] == fixtures
    assert "--aliases" in enrich and "--output" in enrich


def test_derivative_research_runs_from_verified_half_time_sidecar(monkeypatch, tmp_path):
    seen = []

    def fake_run(command, retries=0):
        seen.append((command, retries))
        output = command[command.index("--output") + 1]
        return type("Result", (), {
            "returncode": 0,
            "stdout": json.dumps({"status": "ok", "output": str(output),
                                    "metrics": {"ou_2_5": {"n": 3}, "hafu": {"n": 1}}}),
            "stderr": "",
        })()

    monkeypatch.setattr(pipeline, "run", fake_run)

    report = pipeline.run_derivative_research(tmp_path / "backtest")

    command, retries = seen[0]
    assert command[0].name == "derivative_diagnostics.py"
    assert command[command.index("--store") + 1] == tmp_path / "backtest"
    assert command[command.index("--half-time-evidence") + 1].name == "apifootball_verified_latest.json"
    assert report == {"status": "ok", "output": str(tmp_path / "research" / "derivative-diagnostics" / "latest.json"),
                      "metrics": {"ou_2_5": {"n": 3}, "hafu": {"n": 1}}}
    assert retries == 0


def test_daily_pipeline_default_snapshot_is_truthful_generic_prematch(monkeypatch, tmp_path):
    """A default run may not claim an arbitrary T-minus hour it did not measure."""
    seen = []

    def fake_run(command, retries=0):
        seen.append(command)
        if command[0].name == "fusion_settle.py":
            payload = {"official": {"report": []}, "apifootball_fallback": {"report": []}}
        elif command[0].name == "sales_day_collect.py":
            output = command[command.index("--output") + 1]
            emitted = command[command.index("--emit-input") + 1]
            Path(output).write_text("{}", encoding="utf-8")
            Path(emitted).write_text(json.dumps({"matches": []}), encoding="utf-8")
            payload = {"count": 0}
        elif command[0].name == "odds_movement.py":
            payload = {"added": 0}
        elif command[0].name == "odds_api_adapter.py":
            payload = {"status": "ok", "research_only": True}
        else:
            raise AssertionError(f"unexpected command: {command}")
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(pipeline.sys, "argv", [
        "fusion_daily_pipeline.py", "--kickoff-date", "2026-08-25", "--dry-run",
        "--store", str(tmp_path / "backtest"),
        "--odds-store", str(tmp_path / "odds.jsonl"),
        "--work-dir", str(tmp_path / "forward"),
    ])

    pipeline.main()

    collect = next(command for command in seen if command[0].name == "sales_day_collect.py")
    assert Path(collect[collect.index("--output") + 1]).name == "sporttery_prematch.json"
    assert Path(collect[collect.index("--emit-input") + 1]).name == "inputs_prematch.json"


def test_daily_pipeline_refreshes_derivatives_after_a_new_settlement(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_run(command, retries=0):
        if command[0].name == "fusion_settle.py":
            payload = {"settled": 1, "official": {"pending": 0, "report": [{"status": "settled"}]}}
        elif command[0].name == "sales_day_collect.py":
            output = command[command.index("--output") + 1]
            emitted = command[command.index("--emit-input") + 1]
            Path(output).write_text("{}", encoding="utf-8")
            Path(emitted).write_text(json.dumps({"matches": []}), encoding="utf-8")
            payload = {"count": 0}
        else:
            raise AssertionError(command)
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(pipeline, "run_half_time_research", lambda store: calls.append(("half", store)) or {"status": "ok"})
    monkeypatch.setattr(pipeline, "run_derivative_research", lambda store: calls.append(("derivative", store)) or {"status": "ok"})
    monkeypatch.setattr(pipeline.sys, "argv", [
        "fusion_daily_pipeline.py", "--kickoff-date", "2026-08-25",
        "--store", str(tmp_path / "backtest"), "--odds-store", str(tmp_path / "odds.jsonl"),
        "--work-dir", str(tmp_path / "forward"),
    ])

    pipeline.main()

    assert [name for name, _ in calls] == ["half", "derivative"]
    report = json.loads(capsys.readouterr().out)
    assert report["derivative_research"] == {"status": "ok"}


def test_daily_pipeline_skips_market_sidecars_when_collector_has_no_formal_inputs(monkeypatch, tmp_path):
    """Unopened Sporttery rows are not prediction samples or international-odds work."""
    seen = []

    def fake_run(command, retries=0):
        seen.append(command)
        if command[0].name == "fusion_settle.py":
            payload = {"official": {"report": []}, "apifootball_fallback": {"report": []}}
        elif command[0].name == "sales_day_collect.py":
            output = command[command.index("--output") + 1]
            emitted = command[command.index("--emit-input") + 1]
            Path(output).write_text("{}", encoding="utf-8")
            Path(emitted).write_text(json.dumps({"matches": []}), encoding="utf-8")
            payload = {"count": 11}
        else:
            raise AssertionError(f"sidecar should not run without formal inputs: {command}")
        return type("Result", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(pipeline.sys, "argv", [
        "fusion_daily_pipeline.py", "--kickoff-date", "2026-08-25",
        "--store", str(tmp_path / "backtest"),
        "--odds-store", str(tmp_path / "odds.jsonl"),
        "--work-dir", str(tmp_path / "forward"),
    ])

    pipeline.main()

    assert [command[0].name for command in seen] == ["fusion_settle.py", "sales_day_collect.py"]
