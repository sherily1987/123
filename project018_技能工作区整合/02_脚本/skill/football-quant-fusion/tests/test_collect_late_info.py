from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "collect_late_info",
    SCRIPTS / "collect_late_info.py",
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

UTC = timezone.utc


def test_fold_injuries_caps_and_splits_attack_defense():
    raw = {
        "home": {
            "teamShortName": "H",
            "injuriesAndSuspensionsList": [{
                "personName": "Pedrinho",
                "playerPositionCode": "Forward",
                "playerPositionDesc": "前锋",
                "appearanceCnt": 10,
                "startedMatchCnt": 10,
                "injuryFlag": 1,
                "suspensionFlag": 0,
            }],
        },
        "away": {"injuriesAndSuspensionsList": []},
    }
    folded = mod.fold_injuries(raw)
    assert folded["attack_absence_home"] == 0.10
    assert folded["defense_absence_home"] == 0.0
    assert folded["home"]["count"] == 1
    assert folded["away"]["count"] == 0


def test_t75_window_only_inside_75_minutes():
    kick = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
    assert mod.in_t75_window(kick, kick - timedelta(minutes=30))
    assert not mod.in_t75_window(kick, kick - timedelta(minutes=120))
    assert not mod.in_t75_window(kick, kick + timedelta(minutes=1))


def test_due_and_jsonl_are_research_only(tmp_path: Path):
    matches = [{
        "match_id": 2040907,
        "home": "A",
        "away": "B",
        "kickoff_iso": "2026-08-17T01:00:00+08:00",
        "had_updated_at": "2026-08-16 12:00:00",
        "mode": "market_only",
    }]
    due_path = tmp_path / "late_info_due.json"
    due = mod.write_due(due_path, matches, "T-7h")
    data = json.loads(due_path.read_text(encoding="utf-8"))
    assert data["research_only"] is True
    assert due[0]["match_id"] == 2040907
    row = mod.base_row(
        matches[0], "injury", "T-7h",
        datetime(2026, 8, 16, 8, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 4, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 17, 0, tzinfo=UTC),
    )
    assert row["research_only"] is True
    assert row["production_unchanged"] is True
    assert row["gate"]["late"] is True
    assert "mode" not in row


def test_daily_pipeline_hooks_research_collector_not_record_merge():
    text = (Path(__file__).resolve().parents[1] / "scripts" / "fusion_daily_pipeline.py").read_text(encoding="utf-8")
    assert "collect_late_info.py" in text
    assert "不并入下面的正式登记 input" in text
    rec_idx = text.index("fusion_cli.py', 'record'")
    late_idx = text.index("collect_late_info.py")
    assert late_idx < rec_idx
