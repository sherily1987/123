#!/usr/bin/env python3
"""fusion_predict — 源码入口（2026-08-02 重建）

原源码在文件系统同步事故中损坏，此前以 cpython-312 字节码 + 运行时补丁运行；
现由 fusion_predict_core.py（反编译重建的源码）提供全部逻辑，本文件仅做
模块加载与公共 API 转发，不再依赖任何 .pyc。
"""
import importlib.util
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("_fusion_predict_core_src", _HERE / "fusion_predict_core.py")
if _SPEC is None or _SPEC.loader is None:
    raise SystemExit("fusion_predict_core.py missing")
_core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_core)

# 转发公共 API（与旧加载器一致）
main = _core.main
predict_one = _core.predict_one
load_core = _core.load_core
decision = _core.decision
build_goal_rate = _core.build_goal_rate
build_injury_view = _core.build_injury_view

if __name__ == "__main__":
    _core.main()
