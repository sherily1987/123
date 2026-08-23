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


def test_recent_form_fallback_is_explicitly_aging(monkeypatch):
    calls = []

    def fake_recent(_team, _league, season, n=5):
        calls.append(season)
        return [{"date": str(season), "result": "胜"}] * (5 if season == 2024 else 2)

    monkeypatch.setattr(briefing, "recent_fixtures", fake_recent)
    rows, used_season, status = briefing.recent_form_with_fallback(1, 135, 2025)
    assert len(rows) == 5
    assert used_season == 2024
    assert status == "AGING"
    assert calls == [2025, 2024]


def test_recent_form_keeps_partial_when_both_seasons_are_short(monkeypatch):
    monkeypatch.setattr(briefing, "recent_fixtures", lambda *_args, **_kwargs: [{"result": "平"}] * 2)
    rows, used_season, status = briefing.recent_form_with_fallback(1, 135, 2025)
    assert len(rows) == 2
    assert used_season == 2025
    assert status == "PARTIAL"


def test_safe_wrappers_keep_briefing_running_when_provider_fails(monkeypatch):
    monkeypatch.setattr(briefing, "recent_form_with_fallback", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tls")))
    monkeypatch.setattr(briefing, "standings_row", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tls")))
    monkeypatch.setattr(briefing, "h2h", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("tls")))
    assert briefing.safe_recent_form(1, 135, 2026) == ([], 2026, "UNAVAILABLE")
    assert briefing.safe_standing(135, 2026, 1) is None
    assert briefing.safe_h2h(1, 2) == []
