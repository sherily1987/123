from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from evidence_paths import evidence_path
sys.path.pop(0)


def test_evidence_path_uses_sales_day_three_digit_ordinal_and_match_names():
    assert evidence_path("2026-08-10", 7, "上海海港", "北京国安") == Path(
        r"F:\HM足球比赛预测\今日推荐_双轨四玩法_20260810\evidence\evidence_007_上海海港_北京国安.md"
    )


def test_evidence_path_makes_windows_unsafe_team_names_safe():
    path = evidence_path("20260810", 1234, 'A/B:C*D?E"F<G>H|I', "  客 队. ")

    assert path.name == "evidence_1234_A_B_C_D_E_F_G_H_I_客 队.md"
    assert path.parent.name == "evidence"
    assert path.parent.parent.name == "今日推荐_双轨四玩法_20260810"


def test_evidence_path_filename_uniquely_binds_ordinal_home_and_away_for_caller_contract():
    canonical = evidence_path("2026-08-10", 7, "上海海港", "北京国安")

    assert canonical.name == "evidence_007_上海海港_北京国安.md"
    assert canonical != evidence_path("2026-08-10", 8, "上海海港", "北京国安")
    assert canonical != evidence_path("2026-08-10", 7, "上海申花", "北京国安")
    assert canonical != evidence_path("2026-08-10", 7, "上海海港", "山东泰山")
