"""resolve_path 回归测试（2026-08-15）。

背景：原实现优先信任 registry 里记录的绝对路径，只要该路径在磁盘上仍然存在
就直接读取——而这个路径往往是登记当时生效的外部套件路径
（C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/...），
与 --store 指向的仓库内目录是两份物理分裂的副本（AGENTS.md §0）。
`06_复盘/2026-08-15_模型评测/复盘_模型评测_20260815.md` 审计出全部 1562 条记录
都走了这条隐藏分支，只是内容当时恰好一致，--store 形同虚设。
修复后必须优先按 store 相对路径解析，只有 store 内确实找不到才退回原始路径兜底。

不依赖 pytest fixture（本机未装 pytest），每个测试自建临时目录并在结束时清理，
以便既能被本仓库的轻量 runner 执行，也兼容真正的 pytest。
"""
import importlib.util
import shutil
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("fusion_backtest", SCRIPTS / "fusion_backtest.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)


def _tmp():
    return Path(tempfile.mkdtemp(prefix="resolve_path_test_"))


def test_store_relative_file_is_preferred_over_stale_external_path():
    """store 内文件存在时必须优先用它，即便 registry 记录的外部绝对路径也存在。"""
    root = _tmp()
    try:
        store = root / "store"
        (store / "predictions" / "2026" / "08").mkdir(parents=True)
        internal = store / "predictions" / "2026" / "08" / "m1.json"
        internal.write_text('{"source": "internal"}', encoding="utf-8")

        external_root = root / "external_suite"
        (external_root / "football-quant-fusion" / "backtest" / "predictions" / "2026" / "08").mkdir(
            parents=True)
        external = (external_root / "football-quant-fusion" / "backtest" /
                    "predictions" / "2026" / "08" / "m1.json")
        external.write_text('{"source": "external"}', encoding="utf-8")

        registry_path = str(external).replace("\\", "/")
        resolved = fb.resolve_path(registry_path, store)
        assert resolved == internal, f"expected internal store copy, got {resolved}"
        assert '"source": "internal"' in resolved.read_text(encoding="utf-8")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_falls_back_to_original_path_when_store_copy_missing():
    """store 内没有对应文件时，退回 registry 记录的原始路径（供 p.exists() 上层过滤）。

    比较 Path 对象而非字符串：Windows 上 str(Path(...)) 会把正斜杠规整成反斜杠，
    按字符串比较会对同一路径产生假失败。
    """
    missing_store = Path("Z:/does-not-exist-store")
    original = ("C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/"
                "football-quant-fusion/backtest/predictions/2026/08/only-external.json")
    resolved = fb.resolve_path(original, missing_store)
    assert resolved == Path(original)


def test_legacy_var_minis_prefix_still_supported():
    root = _tmp()
    try:
        store = root / "shared" / "football-quant-fusion" / "backtest"
        (store / "predictions").mkdir(parents=True)
        target = store / "predictions" / "legacy.json"
        target.write_text("{}", encoding="utf-8")

        legacy_path = "/var/minis/shared/football-quant-fusion/backtest/predictions/legacy.json"
        resolved = fb.resolve_path(legacy_path, store)
        assert resolved == target
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_plain_local_path_without_markers_passes_through():
    root = _tmp()
    try:
        f = root / "plain.json"
        f.write_text("{}", encoding="utf-8")
        resolved = fb.resolve_path(str(f), root / "unrelated_store")
        assert resolved == f
    finally:
        shutil.rmtree(root, ignore_errors=True)
