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


def test_load_llm_pending_reads_only_llm_jobs_and_applies_date(tmp_path):
    store = tmp_path / "backtest"
    jobs = tmp_path / "jobs" / "2026-08-24"
    jobs.mkdir(parents=True)
    (jobs / "sporttery-9.json").write_text(
        '{"identity":{"match_id":"sporttery-9","home":"A","away":"B",'
        '"kickoff":"2026-08-24T12:00:00+08:00"},'
        '"outputs":[{"track":"llm"}]}', encoding="utf-8")
    (jobs / "sporttery-10.json").write_text(
        '{"identity":{"match_id":"sporttery-10","home":"C","away":"D",'
        '"kickoff":"2026-08-25T12:00:00+08:00"},'
        '"outputs":[{"track":"llm"}]}', encoding="utf-8")
    got = settle.load_llm_pending(store, set(), "2026-08-24")
    assert [row["match_id"] for row in got] == ["sporttery-9"]
