import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "scrapling_generic_fallback.py"
spec = importlib.util.spec_from_file_location("scrapling_generic_fallback", MODULE)
sg = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(sg)


def test_parse_markdown_keeps_source_and_extracts_explicit_sections():
    text = """# Match preview
## Recent form
- Team A 2-1 Team B (W)
- Team A 1-0 Team C (W)
- Team A 0-0 Team D (D)
- Team A 1-2 Team E (L)
- Team A 3-1 Team F (W)
## Predicted lineup
- GK: Alice Keeper
- DEF: Bob Defender
## Injuries
- Carol Midfielder — hamstring injury
## Suspensions
- Dan Striker — suspended
"""
    row = sg.parse_markdown(text, {"match_id": "sporttery-1", "home": "A", "away": "B"},
                           "https://league.example/match/1", "2026-08-24T00:00:00Z",
                           source_id="league.example.preview", provider="league_preview")
    entries = row["evidence_audit"]["entries"]
    assert row["research_only"] is True
    assert entries["recent_form"]["status"] == "VALID"
    assert entries["starting_xi"]["status"] == "PREDICTED"
    assert entries["injury"]["status"] == "VALID"
    assert entries["suspensions"]["status"] == "VALID"
    assert entries["injury"]["source_id"] == "league.example.preview"
    assert entries["starting_xi"]["source_url"] == "https://league.example/match/1"


def test_parse_markdown_does_not_promote_unlabelled_text():
    row = sg.parse_markdown(
        """# Match preview\nA player may be unavailable.\nNo confirmed lineup here.\n""",
        {"match_id": "sporttery-2"}, "https://example.test/2", "2026-08-24T00:00:00Z",
        source_id="example.test", provider="generic_preview",
    )
    entries = row["evidence_audit"]["entries"]
    assert entries["starting_xi"]["status"] == "UNAVAILABLE"
    assert entries["injury"]["status"] == "UNAVAILABLE"
    assert entries["suspensions"]["status"] == "UNAVAILABLE"
    assert row["evidence_audit"]["evidence_gap"] is True
