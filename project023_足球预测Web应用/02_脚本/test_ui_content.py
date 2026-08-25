from pathlib import Path


def test_b3_shell_keeps_all_governed_concepts():
    static = Path(__file__).parent / "static"
    b3_files = [static / "index.html", static / "daily_strategy.js", *sorted((static / "js").rglob("*.js"))]
    text = "\n".join(path.read_text(encoding="utf-8") for path in b3_files)
    for phrase in ["100元娱乐策略", "未验证正EV", "market_only", "90分钟", "LLM", "版本治理", "仅重试失败项", "导出报告"]:
        assert phrase in text


def test_b3_shell_uses_match_pro_style_horizontal_layout_contract():
    static = Path(__file__).parent / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    css = "\n".join((static / "css" / name).read_text(encoding="utf-8")
                      for name in ("tokens.css", "layout.css", "components.css", "responsive.css"))
    assert 'class="app-header sidebar"' in html
    assert 'class="desktop-nav sidebar-nav"' in html
    assert 'class="topbar control-deck"' in html
    for selector in (".overview-hero", ".hero-command", ".live-match-card", ".dashboard-grid"):
        assert selector in css
    assert "grid-template-columns: minmax(0, 1.05fr) minmax(22rem, .95fr)" in css


def test_brand_uses_project_football_svg_instead_of_system_emoji():
    static = Path(__file__).parent / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    icon = static / "assets" / "match-lab-football.svg"

    assert 'src="assets/match-lab-football.svg"' in html
    assert "⚽" not in html
    assert icon.exists()
    svg = icon.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert 'aria-hidden="true"' in html
