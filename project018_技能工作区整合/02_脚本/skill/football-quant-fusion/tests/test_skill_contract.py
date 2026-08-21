from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_skill_frontmatter_and_trigger_are_minimal_and_discoverable():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    frontmatter = text.split("---", 2)[1]
    assert "name: football-quant-fusion" in frontmatter
    assert "description: Use when" in frontmatter
    assert "version:" not in frontmatter


def test_skill_distinguishes_intent_labels_from_cli_commands():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    assert "意图标签不是 CLI 子命令" in text
    assert "llm-evidence" in text
    assert "--research-route" in text


def test_skill_allows_labeled_manual_verification_but_not_production_override():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    assert "manual_check" in text
    assert "不得覆盖生产字段" in text


def test_contract_requires_status_instead_of_fabricating_missing_markets():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    output = (ROOT / "references" / "output_contract.md").read_text(encoding="utf-8-sig")
    for status in ("VALID", "UNAVAILABLE", "UNFITTED", "NOT_OFFERED"):
        assert status in skill
        assert status in output


def test_sample_counts_are_review_triggers_not_proof_thresholds():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    assert "复审触发点" in text
    assert "不是统计证明" in text


def test_market_baseline_and_data_risk_are_never_banker_states():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    assert "MARKET_BASELINE`、`AVOID_DATA_RISK` 永不出胆" in text


def test_kelly_research_is_hardened_and_not_a_stake():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    detail = (ROOT / "references" / "kelly_research.md").read_text(encoding="utf-8-sig")
    output = (ROOT / "references" / "output_contract.md").read_text(encoding="utf-8-sig")
    assert "KELLY_SANITY_FAIL" in skill
    assert "research.intl_kelly" in skill
    assert "不得输出" in skill and "f^*" in skill
    assert "kelly_research.md" in skill
    assert "路径 C（未开放）" in skill
    assert "Pinnacle" in detail
    assert "不得把只有 `outputs.quant`" in detail
    assert "research.intl_kelly" in output
    assert "KELLY_SANITY_FAIL" in output
