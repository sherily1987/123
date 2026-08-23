import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fusion_settle


def test_parse_command_output_accepts_log_lines_before_json():
    payload = {"official_finished": 3, "settled": 2, "report": [{"status": "would_settle"}]}
    raw = "[settle] matchId 直查命中 5 场\n" + json.dumps(payload, ensure_ascii=False)
    assert fusion_settle.parse_command_output(raw, 0) == payload


def test_parse_command_output_keeps_failure_for_non_json_output():
    parsed = fusion_settle.parse_command_output("network timeout", 7)
    assert parsed["status"] == "failed"
    assert parsed["returncode"] == 7
