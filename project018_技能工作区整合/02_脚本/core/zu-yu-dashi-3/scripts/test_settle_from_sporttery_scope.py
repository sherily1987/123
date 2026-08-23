import settle_from_sporttery as settle


def test_filter_pending_by_date_blocks_match_id_cross_date_leakage():
    rows = [
        {"match_id": "sporttery-1", "kickoff": "2026-08-23 23:30:00"},
        {"match_id": "sporttery-2", "kickoff": "2026-08-24 00:30:00"},
    ]
    got = settle.filter_pending_by_date(rows, "2026-08-23")
    assert [row["match_id"] for row in got] == ["sporttery-1"]


def test_filter_pending_by_date_preserves_all_rows_without_scope():
    rows = [{"match_id": "sporttery-1", "kickoff": "2026-08-23 23:30:00"}]
    assert settle.filter_pending_by_date(rows, None) == rows
