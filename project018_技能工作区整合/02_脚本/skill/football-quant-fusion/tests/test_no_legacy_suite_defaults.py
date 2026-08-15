"""守住「默认值不得指向外部 football-quant-fusion-suite」这条线（2026-08-16）。

背景：`assert_writable_target()` 只在 `fusion_daily_pipeline.py` 里被调用，**不是全局守卫**。
2026-08-16 复查时发现 `fusion_backtest.py` / `sample_audit.py` / `evaluate_walk_forward.py` /
`fusion_combo.py` 的 `--store` 默认值、`odds_api_adapter.py` 的 odds 写入目录、
`sales_day_collect.py` 的核心采集器路径，以及 8 个研究脚本的 `sys.path.insert`
都还硬编码指向外部套件——忘了传参就静默读写错的库。

外部套件是**物理拷贝**，靠人工 cp 同步，历史上真的漂移过（AGENTS.md §0）。
本测试防止这些默认值被重新引入。注释里提到该路径是允许的（讲历史就得写出来），
只有**可执行代码**里的字面量才算违规。
"""
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
LEGACY_MARKER = "football-quant-fusion-suite"
# runtime_paths.py 必须写出这个字符串——它就是识别并拒绝该路径的那段守卫
ALLOWED_FILES = {"runtime_paths.py"}


def _code_lines(text):
    """去掉注释行与文档字符串，只留可执行代码。"""
    without_docstrings = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", text)
    for line in without_docstrings.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            yield line


def test_no_script_defaults_to_the_legacy_suite():
    offenders = {}
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name in ALLOWED_FILES:
            continue
        hits = [line.strip() for line in _code_lines(path.read_text(encoding="utf-8"))
                if LEGACY_MARKER in line]
        if hits:
            offenders[path.name] = hits
    assert not offenders, (
        "以下脚本在可执行代码里硬编码了外部套件路径，会静默读写错的库；"
        f"请改走 runtime_paths：{offenders}"
    )


def test_runtime_paths_still_recognises_the_legacy_suite():
    """守卫本身必须保留该字符串，否则 assert_writable_target 会失效。"""
    text = (SCRIPTS / "runtime_paths.py").read_text(encoding="utf-8")
    assert LEGACY_MARKER in text
    assert "is_legacy_suite_path" in text
