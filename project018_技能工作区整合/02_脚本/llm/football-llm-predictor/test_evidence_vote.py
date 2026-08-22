from __future__ import annotations

import evidence_vote as ev


def test_laliga_has_twenty_slots_and_blocked_hosts():
    slots = ev.slot_hosts("西甲")
    assert len(slots) == 20
    assert len(set(slots)) == 20
    assert "sportsmole.co.uk" in slots
    assert "laliga.com" in slots
    assert "whoscored.com" in ev.BLOCKED


def test_every_league_gets_twenty_slots_and_championship_uses_efl():
    for league in ("英超", "英冠", "德甲", "中超", ""):
        slots = ev.slot_hosts(league)
        assert len(slots) == 20
        assert len(set(slots)) == 20
    assert "efl.com" in ev.slot_hosts("英冠")
    assert "premierleague.com" in ev.slot_hosts("英超")


def test_new_pack_is_the_default_collection_skeleton():
    pack = ev.new_pack(
        match_id=2040999, home="主", away="客",
        league="西甲", collected_at="2026-08-17T12:00:00+08:00",
    )
    assert len(pack["sources"]) == 20
    assert "不是事实来源" in ev.COLLECT_RULES
    blocked = [s for s in pack["sources"] if "封锁" in s["note"]]
    pending = [s for s in pack["sources"] if s["note"] == "待采"]
    assert len(blocked) >= 2
    assert len(pending) >= 10


def test_pick_requires_two_votes():
    assert ev.pick({"A": 1}) is None
    assert ev.pick({"A": 2, "B": 1}) == "A"


def test_merge_keeps_section_headings_on_line_start(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "PACK_DIR", tmp_path)
    ev.save_pack({
        "match_id": 1,
        "home": "A",
        "away": "B",
        "collected_at": "t",
        "canonical_source": "https://example.test/x",
        "home_xi": {"formation": "4-4-2", "line": "x"},
        "away_xi": {"formation": "3-5-2", "line": "y"},
        "injury_line": "none",
        "home_form_line": "W",
        "away_form_line": "L",
        "sources": [{"host": "fotmob.com", "note": "xi", "url": "https://www.fotmob.com/x"}],
    })
    raw = "## 1. 伤停/阵容\n- old\n\n## 2. 战意/动机\n- motive\n\n## 3. 近况/状态\n- old form\n"
    once = ev.apply_pack_file(raw, 1)
    twice = ev.apply_pack_file(once, 1)
    assert twice == raw
    assert "\n## 2. " in once
    assert "\n## 3. " in once
    assert once.count("## 3. ") == 1


def test_merge_inserts_voted_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "PACK_DIR", tmp_path)
    pack = {
        "match_id": 2040922,
        "home": "拉科",
        "away": "埃尔切",
        "collected_at": "2026-08-17T02:10:00+08:00",
        "canonical_source": "https://www.fotmob.com/x",
        "home_xi": {"formation": "4-4-2", "line": "Roman; Navarro"},
        "away_xi": {"formation": "3-5-2", "line": "Iturbe; Chust"},
        "injury_line": "Yeremay 伤缺",
        "home_form_line": "1-2 负拉斯帕尔马斯",
        "away_form_line": "1-1 平赫罗纳",
        "verified_facts": [
            {"section": 1, "text": "主队首发快照事实", "source": "https://www.fotmob.com/x", "collected_at": "2026-08-17T02:10:00+00:00"},
            {"section": 3, "text": "主队近5场快照事实", "source": "https://www.fotmob.com/x", "collected_at": "2026-08-17T02:10:00+00:00"},
        ],
    }
    ev.save_pack(pack)
    raw = "## 1. 伤停/阵容\n- old\n\n## 3. 近况/状态\n- old form\n"
    got = ev.apply_pack_file(raw, 2040922)
    assert "主队首发快照事实" in got
    assert "主队近5场快照事实" in got
    assert "二十源整合" not in got
    again = ev.apply_pack_file(got, 2040922)
    assert again.count("主队首发快照事实") == 1


def test_pack_sources_render_as_slot_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "PACK_DIR", tmp_path)
    pack = {
        "match_id": 2040907,
        "home": "西班牙人",
        "away": "莱万特",
        "collected_at": "2026-08-16T23:50:00+08:00",
        "canonical_source": "https://www.sportsmole.co.uk/x",
        "home_xi": {"formation": "4-2-3-1", "line": "Dmitrovic", "tally": "计票：门将 3。"},
        "away_xi": {"formation": "4-2-3-1", "line": "Ryan", "tally": ""},
        "injury_line": "Puado 缺席",
        "home_form_line": "L-L-W-W-D",
        "away_form_line": "L-W-W-W-L",
        "sources": [
            {"host": "sportsmole.co.uk", "note": "预测 XI", "url": "https://www.sportsmole.co.uk/x"},
            {"host": "whoscored.com", "note": "封锁源占槽、不采正文", "url": "https://www.whoscored.com/x"},
        ],
    }
    ev.save_pack(pack)
    got = ev.apply_pack_file("## 1. 伤停/阵容\n\n## 3. 近况/状态\n", 2040907)
    assert got == "## 1. 伤停/阵容\n\n## 3. 近况/状态\n"
    again = ev.apply_pack_file(got, 2040907)
    assert again == got
