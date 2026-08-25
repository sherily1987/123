from __future__ import annotations

import json
import subprocess
from pathlib import Path


def test_league_hit_rates_combines_all_settled_dates_into_one_row_per_league():
    """Catches the league report splitting one league back into date-specific rows."""
    script_file = Path(__file__).resolve().parent / "static" / "league_hit_rates.js"
    history = {
        "sections": [
            {
                "day": "2026-08-22",
                "matches": [
                    {"league": "英超", "settled": True, "hit": True, "llm_scored": True, "llm_hit": False},
                ],
            },
            {
                "day": "2026-08-24",
                "matches": [
                    {"league": "西甲", "settled": True, "hit": False, "llm_scored": False},
                    {"league": "英超", "settled": True, "hit": True, "llm_scored": True, "llm_hit": True},
                    {"league": "英超", "settled": False, "hit": False, "llm_scored": False},
                ],
            },
        ],
    }
    run = subprocess.run(
        [
            "node",
            "-e",
            (
                f"const page=require({json.dumps(str(script_file))});"
                f"process.stdout.write(JSON.stringify(page.buildLeagueHitRates({json.dumps(history, ensure_ascii=False)})));"
            ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        {"rank": 1, "league": "英超", "quant": {"hit": 2, "n": 2, "rate": 100.0},
         "llm": {"hit": 1, "n": 2, "rate": 50.0}},
        {"rank": 2, "league": "西甲", "quant": {"hit": 0, "n": 1, "rate": 0.0},
         "llm": {"hit": 0, "n": 0, "rate": None}},
    ]


def test_league_hit_rates_page_is_available_without_reusing_the_main_dashboard():
    """Catches the top-level entry opening a missing page instead of a standalone league report."""
    from fastapi.testclient import TestClient
    import app as web

    response = TestClient(web.app).get("/league-hit-rates.html")

    assert response.status_code == 200
    assert "联赛命中率" in response.text
    assert response.headers["cache-control"] == "no-store"
