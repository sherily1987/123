import importlib.util
from pathlib import Path


MODULE = Path(__file__).with_name("build_team_briefing.py")
spec = importlib.util.spec_from_file_location("build_team_briefing", MODULE)
briefing = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(briefing)


def test_injuries_for_team_deduplicates_fixture_repeated_rows(monkeypatch):
    monkeypatch.setattr(
        briefing.adapter,
        "get",
        lambda *_args, **_kwargs: {
            "response": [
                {"player": {"name": "A", "type": "Missing Fixture", "reason": "Knee"}},
                {"player": {"name": "A", "type": "Missing Fixture", "reason": "Knee"}},
                {"player": {"name": "A", "type": "Missing Fixture", "reason": "Red Card"}},
                {"player": {"name": "B", "type": "Missing Fixture", "reason": "Knee"}},
            ]
        },
    )
    rows = briefing.injuries_for_team(135, 2025, 496)
    assert rows == [
        {"player": "A", "type": "Missing Fixture", "reason": "Knee"},
        {"player": "A", "type": "Missing Fixture", "reason": "Red Card"},
        {"player": "B", "type": "Missing Fixture", "reason": "Knee"},
    ]


def test_injuries_for_team_keeps_provider_failure_as_unknown(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(briefing.adapter, "get", fail)
    assert briefing.injuries_for_team(135, 2025, 496) is None
