import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "scripts" / "scrapling_fotmob_fallback.py"
spec = importlib.util.spec_from_file_location("scrapling_fotmob_fallback", MODULE)
fallback = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(fallback)


SAMPLE = """Bologna vs Lazio — Tue, August 25, 12:30 AM

Bologna
--------
4-3-3
Predicted lineup
1Skorupski](/players/1/lukasz-skorupski)
20Zortea](/players/2/nadir-zortea)
Lazio
-----
4-3-3
10Zaccagni](/players/3/mattia-zaccagni)
Team form
---------
Bologna 1 - 0 Brighton
Bologna 3 - 1 Cambuur
Unavailable
--------
Nicolò Casale
Muscle injury / Early September 2026
Gustav Isaksen
Groin injury / Doubtful
"""


def test_parse_fotmob_markdown_keeps_predicted_xi_injuries_and_form_as_research():
    got = fallback.parse_markdown(
        SAMPLE,
        {"match_id": "sporttery-2041028", "home": "Bologna", "away": "Lazio"},
        "https://www.fotmob.com/matches/lazio-vs-bologna/2ssnzl",
        "2026-08-24T01:40:00+00:00",
    )

    assert got["research_only"] is True
    assert got["evidence_audit"]["entries"]["starting_xi"]["status"] == "PREDICTED"
    assert "Skorupski" in got["evidence_audit"]["entries"]["starting_xi"]["value"]["players"]
    assert got["evidence_audit"]["entries"]["injury"]["status"] == "VALID"
    assert "Nicolò Casale" in got["evidence_audit"]["entries"]["injury"]["value"]["players"]
    assert got["evidence_audit"]["entries"]["recent_form"]["status"] == "PARTIAL"
