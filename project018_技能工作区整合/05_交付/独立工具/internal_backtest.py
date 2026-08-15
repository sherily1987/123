#!/usr/bin/env python3
"""internal_backtest — 强制从仓库内唯一事实源读预测文件跑融合全量回测。

registry.jsonl 的 path 字段大多指向外部套件（C:/Users/Administrator/.codex/...），
fusion_backtest.resolve_path() 对存在的外部文件会直接读取，导致评测混读外部副本。
本包装 monkey-patch resolve_path，把任何含 /football-quant-fusion/backtest/ 的
path 重定向到 --store 指向的仓库内 predictions/，不修改 registry.jsonl（哈希链不可动）。

用法与 fusion_backtest.py 相同：--store <仓库内backtest> --output <报告.json>
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

import fusion_backtest as fb  # noqa: E402

MARKER = "/football-quant-fusion/backtest/"
_AUDIT = {"redirect": 0, "direct": 0, "missing": 0, "checked": 0}


def resolve_internal(p_str, root):
    norm = str(p_str).replace("\\", "/")
    if MARKER in norm:
        tail = norm.split(MARKER, 1)[1]
        cand = root / tail
        _AUDIT["checked"] += 1
        if cand.exists():
            _AUDIT["redirect"] += 1
            return cand
        _AUDIT["missing"] += 1
        return Path(p_str)
    if norm.startswith("/var/minis/shared/"):
        cand = root.parents[1] / norm[len("/var/minis/shared/"):]
        if cand.exists():
            _AUDIT["direct"] += 1
            return cand
        _AUDIT["missing"] += 1
        return Path(p_str)
    _AUDIT["direct"] += 1
    return Path(p_str)


fb.resolve_path = resolve_internal

if __name__ == "__main__":
    fb.main()
    print(f"[internal_backtest audit] {_AUDIT}", file=sys.stderr)
