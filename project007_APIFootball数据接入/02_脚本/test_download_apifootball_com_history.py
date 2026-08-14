from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
import pytest

MODULE = Path(__file__).with_name("download_apifootball_com_history.py")
SPEC = importlib.util.spec_from_file_location("history", MODULE)
history = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(history)


def test_normalize_finished_event_keeps_only_training_safe_fields():
    row = history.normalize_event({"match_id": "7", "league_id": "152", "league_name": "Premier League", "league_year": "2025/2026", "match_status": "Finished", "match_date": "2025-08-10", "match_time": "20:00", "match_hometeam_id": "1", "match_hometeam_name": "Home", "match_awayteam_id": "2", "match_awayteam_name": "Away", "match_hometeam_score": "2", "match_awayteam_score": "1", "statistics": [{"type": "Shots Total"}]}, "2026-08-11T00:00:00+00:00")
    assert row["actual"] == [2, 1]
    assert row["field_availability"]["statistics"] == "POST_MATCH"
    assert "statistics" not in row


def test_deduplicate_prefers_one_provider_match_id():
    rows = [{"provider": "apifootball.com", "match_id": 7}, {"provider": "apifootball.com", "match_id": 7}]
    assert history.deduplicate(rows) == [rows[0]]


FINISHED_EVENT = {
    "match_id": "7", "league_id": "152", "league_name": "Premier League", "league_year": "2021/2022",
    "match_status": "Finished", "match_date": "2021-07-10", "match_time": "20:00",
    "match_hometeam_id": "1", "match_hometeam_name": "Home", "match_awayteam_id": "2", "match_awayteam_name": "Away",
    "match_hometeam_score": "2", "match_awayteam_score": "1",
}


def test_download_history_reuses_a_valid_monthly_raw_block(tmp_path, monkeypatch):
    raw = tmp_path / "04_素材" / "apifootball_com_raw" / "premier_league" / "2021-07.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps({"response": [FINISHED_EVENT]}), encoding="utf-8")
    monkeypatch.setattr(history.adapter, "request", lambda *_: pytest.fail("must reuse cached month"))

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path, "premier_league", False, 0, 0)

    assert report["months_reused"] == ["2021-07"]
    assert len(report["rows"]) == 1


def test_download_history_records_month_failure_without_leaking_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr(
        history.adapter,
        "request",
        lambda *_: (_ for _ in ()).throw(RuntimeError("HTTP 429 APIkey=secret-value")),
    )

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path, "premier_league", True, 0, 0)

    assert report["rows"] == []
    assert report["failures"][0]["error_type"] == "RuntimeError"
    assert "secret-value" not in report["failures"][0]["error"]


# --- 球队级统计（withPlayerStats） ---

# 实测供应商会重复输出同一 type，且重复项为 0
DUPLICATED_STATS = [
    {"type": "Attacks", "home": "96", "away": "137"},
    {"type": "Attacks", "home": "0", "away": "0"},
    {"type": "Shots Total", "home": "14", "away": "17"},
    {"type": "Shots On Goal", "home": "5", "away": "6"},
    {"type": "Shots Off Goal", "home": "7", "away": "6"},
    {"type": "Shots Blocked", "home": "2", "away": "5"},
    {"type": "Shots Inside Box", "home": "9", "away": "9"},
    {"type": "Shots Outside Box", "home": "5", "away": "8"},
    {"type": "Corners", "home": "0", "away": "6"},
    {"type": "Ball Possession", "home": "31%", "away": "69%"},
]


def test_stat_map_takes_first_occurrence_not_last():
    """重复 type 的后一条是 0，字典推导会取错。"""
    assert history.stat_map(DUPLICATED_STATS)["Attacks"] == (96.0, 137.0)


def test_normalize_statistics_parses_shots_and_possession():
    row = history.normalize_statistics({**FINISHED_EVENT, "statistics": DUPLICATED_STATS}, "2026-08-12T00:00:00+00:00")
    assert row["shots_inside_box"] == [9.0, 9.0]
    assert row["shots_outside_box"] == [5.0, 8.0]
    assert row["possession_pct"] == [31.0, 69.0]
    assert row["data_class"] == "POST_MATCH"
    assert row["consistent"] is True  # 9+5==14, 9+8==17
    assert row["xg_usable"] is True


def test_normalize_statistics_flags_inconsistent_split():
    """切分存在但加不回总数：供应商数据自相矛盾。"""
    bad = [x for x in DUPLICATED_STATS if x["type"] != "Shots Inside Box"]
    bad.append({"type": "Shots Inside Box", "home": "99", "away": "9"})
    row = history.normalize_statistics({**FINISHED_EVENT, "statistics": bad}, "2026-08-12T00:00:00+00:00")
    assert row["split_available"] is True
    assert row["consistent"] is False and row["xg_usable"] is False


def test_normalize_statistics_flags_partial_split():
    """实测有场次只给主队的 inside/outside，客队为空——不能用于 xG。"""
    partial = [x for x in DUPLICATED_STATS if x["type"] != "Shots Outside Box"]
    partial.append({"type": "Shots Outside Box", "home": "5", "away": ""})
    row = history.normalize_statistics({**FINISHED_EVENT, "statistics": partial}, "2026-08-12T00:00:00+00:00")
    assert row["split_available"] is False and row["xg_usable"] is False


def test_normalize_statistics_returns_none_when_absent():
    assert history.normalize_statistics({**FINISHED_EVENT, "statistics": []}, "t") is None


def test_download_history_with_player_stats_writes_separate_files(tmp_path, monkeypatch):
    """统计必须写独立文件，赛前训练集不得被污染；原始响应也另存目录。"""
    monkeypatch.setattr(history.adapter, "request",
                        lambda action, params: [{**FINISHED_EVENT, "statistics": DUPLICATED_STATS}])

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path,
                                      "premier_league", True, 0, 0, with_player_stats=True)

    events = [json.loads(l) for l in
              (tmp_path / "04_素材" / "标准化" / "premier_league_events.jsonl").read_text(encoding="utf-8").splitlines()]
    # 赛前训练集只允许出现 field_availability 里的 POST_MATCH 标记，不得有任何统计数值
    assert not (set(events[0]) & set(history.SHOT_FIELDS))
    assert "statistics" not in events[0]
    assert events[0]["field_availability"]["statistics"] == "POST_MATCH"
    assert report["statistics"]["count"] == 1
    assert report["statistics"]["xg_usable"] == 1
    assert report["statistics"]["coverage_pct"] == 100.0
    assert report["statistics"]["inconsistent"] == 0
    assert report["statistics"]["partial_split"] == 0
    # 带 flag 的原始响应存到独立目录，避免与旧缓存互相污染
    assert (tmp_path / "04_素材" / "apifootball_com_raw_stats" / "premier_league" / "2021-07.json").exists()
    assert not (tmp_path / "04_素材" / "apifootball_com_raw" / "premier_league").exists()


def test_download_history_counts_missing_statistics(tmp_path, monkeypatch):
    monkeypatch.setattr(history.adapter, "request",
                        lambda action, params: [{**FINISHED_EVENT, "statistics": []}])

    report = history.download_history(152, date(2021, 7, 1), date(2021, 7, 31), tmp_path,
                                      "premier_league", True, 0, 0, with_player_stats=True)

    assert report["statistics"] == {**report["statistics"], "count": 0, "missing": 1, "coverage_pct": 0.0}
