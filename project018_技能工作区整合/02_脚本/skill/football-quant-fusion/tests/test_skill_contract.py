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
    assert "NO_EVIDENCE" in skill
    assert "hybrid_sample_governance.md" in skill
    assert "Pinnacle" in detail
    assert "不得把 `jobs/` 文件数" in detail
    assert "research.intl_kelly" in output
    assert "KELLY_SANITY_FAIL" in output


def test_hybrid_sample_governance_is_hardened():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8-sig")
    gov = (ROOT / "references" / "hybrid_sample_governance.md").read_text(encoding="utf-8-sig")
    assert "REGISTERED_HYBRID_BACKTEST_V1" in skill
    assert "LIVE_HYBRID_REVIEW_UNIQUE" in skill
    assert "HISTORICAL_HYBRID_REPLAY_CURRENT" in skill
    assert "禁止跨口径" in skill or "不得跨口径" in skill
    assert "hybrid_cohort_key" in skill
    assert "EVIDENCE_BETTER_THAN_MARKET" in skill
    assert "NO_EVIDENCE" in gov
    assert "不得相减" in gov or "禁止跨口径" in gov
    lock = (ROOT / "config" / "hybrid_review_cohort.json").read_text(encoding="utf-8-sig")
    assert "48d50abee08c6c1ed3854dda4d76e762c9106134d1bd0fa5202c15e460d0798b" in lock
