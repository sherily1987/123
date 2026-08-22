import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "hafu_sporttery_evaluation.py"
spec = importlib.util.spec_from_file_location("hafu_sporttery_evaluation", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def test_extract_rows_uses_closing_hafu_and_official_hafu_settlement():
    """保护：若错误读取赛后赔率或错映射 HAFU 标签，样本外评估会失真。"""
    rows = module.extract_rows([
        {
            "kickoff_iso": "2026-02-03T20:00:00+08:00",
            "closing_pre_match": {
                "hafu": {
                    "hh": "2.0", "hd": "4.0", "ha": "8.0",
                    "dh": "5.0", "dd": "6.0", "da": "10.0",
                    "ah": "12.0", "ad": "15.0", "aa": "20.0",
                }
            },
            "match_result_list": [{"code": "HAFU", "combination": "D:H"}],
        },
        {
            "kickoff_iso": "2026-02-04T20:00:00+08:00",
            "closing_pre_match": {"hafu": {"hh": "0"}},
            "match_result_list": [{"code": "HAFU", "combination": "H:H"}],
        },
    ])

    assert len(rows) == 1
    assert rows[0]["outcome"] == 3  # HAFU 九态顺序 HH/HD/HA/DH/DD/DA/AH/AD/AA
    assert rows[0]["prob"] == [
        0.3243243243, 0.1621621622, 0.0810810811,
        0.1297297297, 0.1081081081, 0.0648648649,
        0.0540540541, 0.0432432432, 0.0324324324,
    ]


def test_paired_bootstrap_reports_negative_delta_when_temperature_improves_every_row():
    """保护：候选温度若只在总体均值看似变好，CI 不能被错误标成确定改善。"""
    rows = [
        {"prob": [0.8] + [0.025] * 8, "outcome": 0},
        {"prob": [0.75] + [0.03125] * 8, "outcome": 0},
        {"prob": [0.7] + [0.0375] * 8, "outcome": 0},
        {"prob": [0.85] + [0.01875] * 8, "outcome": 0},
    ]

    report = module.paired_bootstrap(rows, temperature=0.5, draws=200, seed=7)

    assert report["brier"]["delta_candidate_minus_raw"] < 0
    assert report["brier"]["ci95_high"] < 0
    assert report["log_loss"]["delta_candidate_minus_raw"] < 0
    assert report["log_loss"]["ci95_high"] < 0
