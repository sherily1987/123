from pathlib import Path


def test_daily_pipeline_has_no_legacy_suite_write_defaults():
    script = Path(__file__).parents[1] / "scripts" / "fusion_daily_pipeline.py"
    text = script.read_text(encoding="utf-8")
    assert "football-quant-fusion-suite/shared" not in text
    assert "backtest_store()" in text
    assert "odds_store()" in text
    assert "forward_work_dir()" in text
