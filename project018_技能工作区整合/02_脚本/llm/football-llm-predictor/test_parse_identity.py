import parse_predictions as pp


def _raw():
    return {
        "sales_day": "2026-08-16",
        "matches": [
            {"match_id": 2040001, "match_num": "周日001", "home": "甲", "away": "乙",
             "league": "英超", "kickoff_iso": "2026-08-16T22:00:00+08:00"},
            {"match_id": 2040002, "match_num": "周日002", "home": "丙", "away": "丁",
             "league": "西甲", "kickoff_iso": "2026-08-16T23:00:00+08:00"},
        ],
    }


def _audit(match_id, match_num, direction="主胜"):
    return {
        "match_id": f"sporttery-{match_id}",
        "match_num": match_num,
        "direction": direction,
        "alt_direction": None,
        "strength": 0.6,
        "all_votes": {"主胜": 2, "平局": 1, "客胜": 0},
        "single_pick": {"pick": direction, "skip": True, "confidence": 0.5},
        "top_score_pref": "1-0",
        "individual": {},
    }


def test_aligns_by_match_id_even_if_order_is_reversed():
    raw = _raw()
    audits = [_audit(2040002, "周日002", "客胜"), _audit(2040001, "周日001", "平局")]
    parsed = pp.parse_audits(audits, raw)
    by_id = {row["match_id"]: row for row in parsed}
    assert by_id["sporttery-2040001"]["dir"] == "平局"
    assert by_id["sporttery-2040001"]["home"] == "甲"
    assert by_id["sporttery-2040002"]["dir"] == "客胜"
    assert all(row["aligned_by"] == "match_id" for row in parsed)


def test_order_fallback_only_when_audit_has_no_identity():
    raw = _raw()
    audits = [_audit(2040001, "周日001")]
    audits[0].pop("match_id")
    audits[0].pop("match_num")
    parsed = pp.parse_audits(audits, raw)
    assert parsed[0]["aligned_by"] == "order"
    assert parsed[0]["match_id"] == "sporttery-2040001"


def test_unmatched_id_is_skipped():
    raw = _raw()
    parsed = pp.parse_audits([_audit(9999999, "周日999")], raw)
    assert parsed == []


def test_single_pick_action_is_carried_to_parsed_output():
    raw = _raw()
    audit = _audit(2040001, "周日001")
    audit["single_pick"].update({"action": "observe", "bettable": False})
    row = pp.parse_audits([audit], raw)[0]
    assert row["sp_action"] == "observe"
    assert row["sp_bettable"] is False
