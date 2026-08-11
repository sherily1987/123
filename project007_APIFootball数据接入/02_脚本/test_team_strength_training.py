from __future__ import annotations
import importlib.util, json, subprocess, sys
from pathlib import Path

MODULE=Path(__file__).parents[2] / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts" / "team_strength.py"
SPEC=importlib.util.spec_from_file_location("strength",MODULE); strength=importlib.util.module_from_spec(SPEC); assert SPEC and SPEC.loader; SPEC.loader.exec_module(strength)

def test_results_only_league_filter_loads_finished_rows(tmp_path):
    p=tmp_path/'rows.jsonl'; p.write_text(json.dumps({"league_id":152,"actual":[2,1],"home":"A","away":"B","kickoff":"2025-01-01"})+'\n'+json.dumps({"league_id":1,"actual":[1,0],"home":"C","away":"D","kickoff":"2025-01-02"})+'\n',encoding='utf-8')
    rows=strength.load_matches(p,league_id=152,require_odds=False)
    assert len(rows)==1 and rows[0]['gh']==2 and rows[0]['league']=='152'


def test_cli_exposes_results_only_and_league_filter():
    result = subprocess.run(
        [sys.executable, str(MODULE), "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--results-only" in result.stdout
    assert "--league-id" in result.stdout


def test_results_only_validation_marks_market_as_unavailable(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {
        "teams": ["A", "B"],
        "home_adv": 0.0,
        "alpha": [0.0, 0.0],
        "beta": [0.0, 0.0],
    }
    report = strength.validate(
        [
            {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "152", "odds": []},
            {"home": "B", "away": "A", "gh": 0, "ga": 1, "day": 2, "league": "152", "odds": []},
        ],
        model,
        from_day=2,
    )
    assert report["model"]["n"] == 1
    assert report["market"] == {"status": "UNAVAILABLE", "reason": "no_pre_match_odds"}


def test_results_only_validation_honors_exclusive_to_day(monkeypatch):
    monkeypatch.setattr(strength, "dc_matrix", lambda lh, la, rho: [lh, la])
    monkeypatch.setattr(strength, "dc_one", lambda values: [0.5, 0.3, 0.2])
    model = {"teams": ["A", "B"], "home_adv": 0.0, "alpha": [0.0, 0.0], "beta": [0.0, 0.0]}
    rows = [
        {"home": "A", "away": "B", "gh": 1, "ga": 0, "day": 1, "league": "152", "odds": []},
        {"home": "B", "away": "A", "gh": 0, "ga": 1, "day": 2, "league": "152", "odds": []},
        {"home": "A", "away": "B", "gh": 1, "ga": 1, "day": 3, "league": "152", "odds": []},
    ]

    report = strength.validate(rows, model, from_day=2, to_day=3)

    assert report["n"] == 1
