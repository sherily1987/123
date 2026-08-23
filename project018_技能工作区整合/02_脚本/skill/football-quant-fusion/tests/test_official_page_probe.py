import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "official_page_probe.py"
spec = importlib.util.spec_from_file_location("official_page_probe", MODULE)
probe = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(probe)


def test_extract_facts_requires_both_teams_and_marks_unpublished_lineups_pending():
    text = "CA Osasuna VS Levante UD Scheduled TUE 25.08.2026 01:30 h Previous Lineups"

    got = probe.extract_facts(
        text,
        home="奥萨苏纳",
        away="莱万特",
        kickoff_date="2026-08-25",
    )

    assert got["identity_status"] == "MATCHED"
    assert got["schedule_status"] == "MATCHED"
    assert got["lineup_status"] == "LINEUP_PENDING"
    assert got["content_hash"].startswith("sha256:")


def test_probe_url_returns_auditable_error_when_scrapling_fails(monkeypatch):
    monkeypatch.setattr(probe, "_run_scrapling", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("blocked")))

    got = probe.probe_url(
        "https://official.example/match/1",
        home="A", away="B", kickoff_date="2026-08-25",
    )

    assert got["status"] == "source_fetch_error"
    assert got["reason"] == "blocked"
    assert got["source_url"] == "https://official.example/match/1"
