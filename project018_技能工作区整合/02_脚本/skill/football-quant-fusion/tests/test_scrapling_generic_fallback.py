import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "scripts" / "scrapling_generic_fallback.py"
spec = importlib.util.spec_from_file_location("scrapling_generic_fallback", MODULE)
sg = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(sg)


def test_parse_markdown_keeps_source_and_extracts_explicit_sections():
    text = """# Match preview
## Recent form
- Team A 2-1 Team B (W)
- Team A 1-0 Team C (W)
- Team A 0-0 Team D (D)
- Team A 1-2 Team E (L)
- Team A 3-1 Team F (W)
## Predicted lineup
- GK: Alice Keeper
- DEF: Bob Defender
## Injuries
- Carol Midfielder — hamstring injury
## Suspensions
- Dan Striker — suspended
"""
    row = sg.parse_markdown(text, {"match_id": "sporttery-1", "home": "A", "away": "B"},
                           "https://league.example/match/1", "2026-08-24T00:00:00Z",
                           source_id="league.example.preview", provider="league_preview")
    entries = row["evidence_audit"]["entries"]
    assert row["research_only"] is True
    assert entries["recent_form"]["status"] == "VALID"
    assert entries["starting_xi"]["status"] == "PREDICTED"
    assert entries["injury"]["status"] == "VALID"
    assert entries["suspensions"]["status"] == "VALID"
    assert entries["injury"]["source_id"] == "league.example.preview"
    assert entries["starting_xi"]["source_url"] == "https://league.example/match/1"
    assert entries["starting_xi"]["source_tier"] == "C"


def test_parse_markdown_does_not_promote_unlabelled_text():
    row = sg.parse_markdown(
        """# Match preview\nA player may be unavailable.\nNo confirmed lineup here.\n""",
        {"match_id": "sporttery-2"}, "https://example.test/2", "2026-08-24T00:00:00Z",
        source_id="example.test", provider="generic_preview",
    )
    entries = row["evidence_audit"]["entries"]
    assert entries["starting_xi"]["status"] == "UNAVAILABLE"
    assert entries["injury"]["status"] == "UNAVAILABLE"
    assert entries["suspensions"]["status"] == "UNAVAILABLE"
    assert row["evidence_audit"]["evidence_gap"] is True


def test_parse_markdown_supports_chinese_sections_and_explicit_strength():
    text = """# 比赛前瞻
## 近期状态
- 主队 2：1 客队（胜）
- 主队 1-0 甲队（胜）
- 主队 0：0 乙队（平）
- 主队 1-2 丙队（负）
- 主队 3：1 丁队（胜）
## 预计首发
- 门将：主队门将
## 伤停
- 主队中场：肌肉伤势
## 停赛
- 客队后卫：累计黄牌
## xG与攻防强度
- 主队 xG 1.72，防守强度 0.91
- 客队 xG 1.18，进攻强度 1.03
"""
    row = sg.parse_markdown(
        text, {"match_id": "sporttery-cn-1", "home": "主队", "away": "客队"},
        "https://league.example/cn/1", "2026-08-24T00:00:00Z",
        source_id="league.example.cn", provider="league_preview",
    )
    entries = row["evidence_audit"]["entries"]
    assert entries["team_stats"]["status"] == "VALID"
    assert entries["recent_form"]["status"] == "VALID"
    assert entries["starting_xi"]["status"] == "PREDICTED"
    assert entries["injury"]["status"] == "VALID"
    assert entries["suspensions"]["status"] == "VALID"
    assert "xG" in entries["team_stats"]["value"]["raw_rows"][0]


def test_parse_markdown_supports_setext_headings_and_bold_predicted_lineups():
    text = """Bologna pre-season form:

* L
* D
* W
* W
* L
* L

Team News
---------

While Nicolo Casale is the hosts' sole fitness doubt, Lazio could be missing Isaksen.
Mario Gila has left for Milan.

**Bologna possible starting lineup:**

Skorupski; Zortea, Vitik, Heggem, Miranda

**Lazio possible starting lineup:**

Mandas; Marusic, Doekhi, Pedraza
"""
    row = sg.parse_markdown(
        text, {"match_id": "sporttery-it-1", "home": "Bologna", "away": "Lazio"},
        "https://www.sportsmole.co.uk/football/bologna/preview/example.html",
        "2026-08-24T03:28:41Z", source_id="sportsmole.preview", provider="scrapling_generic",
    )
    entries = row["evidence_audit"]["entries"]
    assert entries["recent_form"]["status"] == "VALID"
    assert entries["starting_xi"]["status"] == "PREDICTED"
    assert entries["injury"]["status"] == "VALID"
    # No explicit suspension section: do not infer that nobody is suspended.
    assert entries["suspensions"]["status"] == "UNAVAILABLE"
