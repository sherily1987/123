from pathlib import Path

import fusion_settle


def test_build_commands_defaults_to_official_only(tmp_path):
    commands = fusion_settle.build_commands(tmp_path, None, False, False)
    assert len(commands) == 1
    assert commands[0]["source"] == "official"


def test_build_commands_adds_provider_only_when_explicit(tmp_path):
    commands = fusion_settle.build_commands(tmp_path, "2026-08-11", True, True)
    assert [row["source"] for row in commands] == ["official", "apifootball"]
    assert "--dry-run" in commands[1]["cmd"]


def test_combined_report_does_not_hide_official_success_when_provider_fails():
    report = fusion_settle.combine_reports(
        {"settled": 2, "report": []},
        {"status": "provider_unavailable", "settled": 0},
    )
    assert report["settled"] == 2
    assert report["official"]["settled"] == 2


def test_build_commands_can_include_llm_jobs_for_calibration(tmp_path):
    commands = fusion_settle.build_commands(tmp_path, "2026-08-24", True, False, True)
    assert "--include-llm-jobs" in commands[0]["cmd"]
