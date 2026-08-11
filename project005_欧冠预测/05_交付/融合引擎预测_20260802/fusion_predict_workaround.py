#!/usr/bin/env python3
"""fusion_predict 非侵入式启动器（Workaround，2026-08-02）

背景：fusion_predict_core.cpython-312.pyc 在“市场赔率缺失/陈旧”分支引用
模块级变量 market_freshness_meta，但该变量从未被赋值，导致
NameError: name 'market_freshness_meta' is not defined（原始源码在文件系统
事故中损坏，无法直接改源码）。本启动器加载同一字节码模块后注入
market_freshness_meta = {}，使该分支按 `... or {}` 的语义继续执行。

只修复崩溃，不修改任何概率计算逻辑；仍按 fusion_predict 原入口转发 main()。
"""
import importlib.util
import os
import sys
from pathlib import Path

_PYC = Path(__file__).resolve().parent.parent / "fusion_predict_core.pyc"
if not _PYC.exists():
    _PYC = Path(
        r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\__pycache__\fusion_predict_core.cpython-312.pyc"
    )
if not _PYC.exists():
    raise SystemExit(f"fusion_predict bytecode missing: {_PYC}")

_spec = importlib.util.spec_from_file_location("_fusion_predict_core", _PYC)
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)

# Workaround：注入缺失的模块级回退值
if not hasattr(_core, "market_freshness_meta"):
    _core.market_freshness_meta = {}

# 允许通过环境变量覆盖核心引擎目录（Windows 移植用）
_override = os.environ.get("FUSION_CORE_DIR")
if _override:
    _core.CORE_DIR = Path(_override).resolve()
    _core.CORE_FILE = _core.CORE_DIR / "predict.py"
    _candidate = _core.CORE_DIR.parent / "config" / "version_manifest.json"
    if not _candidate.exists():
        # 核心目录（zu-yu-dashi-3）无 config 时回退到 fusion 自身的版本清单
        _candidate = Path(
            r"C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\config\version_manifest.json"
        )
    _core.VERSION_FILE = _candidate

if __name__ == "__main__":
    _core.main()
