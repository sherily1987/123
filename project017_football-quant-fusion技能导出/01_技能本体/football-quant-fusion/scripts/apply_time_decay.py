#!/usr/bin/env python3
"""apply_time_decay — 时间衰减 λ 先验候选（委托 zu-yu-dashi-3 实现）。

给官方前瞻近况强度应用指数时间衰减，默认只写 time_decay_candidate 元数据；
--activate 时才写入 lambda_prior（UNFITTED，默认不激活）。
"""
import subprocess
import sys
from pathlib import Path

from runtime import resolve_python

_ZU = Path(r"H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖\zu-yu-dashi-3\scripts\apply_time_decay.py")


def main():
    if not _ZU.exists():
        raise SystemExit(f"依赖脚本缺失：{_ZU}")
    proc = subprocess.run([resolve_python(), str(_ZU), *sys.argv[1:]], text=True, capture_output=True)
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
