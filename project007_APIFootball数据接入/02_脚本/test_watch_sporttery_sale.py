from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE = (Path(__file__).parents[2] / "project021_五大联赛APIFootball训练" / "02_脚本" /
          "watch_sporttery_sale.py")
sys.path.insert(0, str(MODULE.parent))
SPEC = importlib.util.spec_from_file_location("watch", MODULE)
watch = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(watch)


def test_neutral_competitions_are_recognized_exactly():
    for name in watch.NEUTRAL_COMPETITIONS:
        assert watch.is_neutral_venue(name) is True


def test_two_legged_knockout_is_not_neutral():
    """双回合淘汰赛两回合都在各自主场，不属中立场——即使同属欧战。"""
    for name in ("欧冠", "欧联", "欧协联", "欧冠资格赛", "欧联资格赛"):
        assert watch.is_neutral_venue(name) is False


def test_domestic_league_is_not_neutral():
    assert watch.is_neutral_venue("英超") is False
    assert watch.is_neutral_venue("解放者杯") is False


def test_missing_or_none_league_name_is_not_neutral():
    assert watch.is_neutral_venue(None) is False
    assert watch.is_neutral_venue("") is False


def test_whitespace_variants_still_match():
    """体彩接口偶有前后空白，不能因此漏判。"""
    assert watch.is_neutral_venue(" 欧超杯 ") is True
