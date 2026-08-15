from pathlib import Path


SKILL = Path(__file__).parents[1] / "SKILL.md"


def test_skill_uses_current_entry_and_drops_legacy_suite_commands():
    text = SKILL.read_text(encoding="utf-8-sig")
    assert "football-quant-fusion-suite/skills/football-quant-fusion" not in text
    assert "C:\\Users\\Administrator\\.codex\\skills\\football-quant-fusion\\scripts\\fusion_cli.py" in text
    assert "football-data-enrich" not in text
    assert "market-ablation" not in text


def test_skill_preserves_production_boundaries_and_graded_gates():
    text = SKILL.read_text(encoding="utf-8-sig")
    for phrase in ("体彩官方盘口", "国际赔率", "90分钟", "model_version", "研究模式", "生产模式", "阻断", "降级", "警告"):
        assert phrase in text
    assert "样本 <100 场不评价" not in text
    assert "达到200场后才" not in text
