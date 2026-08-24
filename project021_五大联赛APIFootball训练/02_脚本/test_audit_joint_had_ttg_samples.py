import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_joint_had_ttg_samples.py")
spec = importlib.util.spec_from_file_location("audit_joint", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_summarize_counts_only_settled_rows():
    rows = [
        {"ttg": {"odds": [2] * 8}, "odds": [2, 3, 4], "actual": [1, 0]},
        {"ttg": {"odds": [2] * 8}, "odds": [2, 3, 4]},
        {"odds": [2, 3, 4], "actual": [0, 0]},
    ]
    out = audit.summarize(rows)
    assert out == {"had_rows": 3, "ttg_rows": 2, "joint_rows": 2, "joint_settled_rows": 1}


def test_load_store_rows_attaches_result_score(tmp_path):
    (tmp_path / "predictions").mkdir()
    (tmp_path / "results").mkdir()
    (tmp_path / "predictions" / "m1.json").write_text(
        '{"input":{"odds":[2,3,4],"ttg":{"odds":[2,2,2,2,2,2,2,2]}}}', encoding="utf-8"
    )
    (tmp_path / "results" / "m1.json").write_text(
        '{"score_90":{"home":2,"away":1}}', encoding="utf-8"
    )
    (tmp_path / "registry.jsonl").write_text('{"match_id":"m1","path":"predictions/m1.json"}\n', encoding="utf-8")
    rows = audit.load_store_rows(tmp_path)
    assert rows[0]["actual"] == [2, 1]
