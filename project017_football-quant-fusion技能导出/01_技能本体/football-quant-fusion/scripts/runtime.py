#!/usr/bin/env python3
"""Python 运行时解析：融合核心字节码是 cpython-312，其他版本解释器自动切到内置 3.12。"""
import os
import sys
from pathlib import Path

# 候选 Python 3.12 解释器（按优先级；FUSION_PY312 环境变量可覆盖）
_CANDIDATES = (
    os.environ.get("FUSION_PY312"),
    r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
    r"C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe",
)


# [中文功能] 解析应使用的Python解释器（非3.12自动切换到内置3.12）
def resolve_python():
    """返回应执行本套件的 Python 解释器路径。

    当前解释器已是 3.12 时直接返回 sys.executable；否则在候选路径中找 3.12
    （FUSION_PY312 环境变量优先）；找不到时回退当前解释器（由调用方报错）。
    """
    if sys.version_info[:2] == (3, 12):
        return sys.executable
    for cand in _CANDIDATES:
        if cand and Path(cand).exists():
            return str(Path(cand).resolve())
    return sys.executable
