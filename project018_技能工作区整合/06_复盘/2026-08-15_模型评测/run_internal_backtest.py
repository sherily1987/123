#!/usr/bin/env python3
"""run_internal_backtest — 强制从仓库内唯一事实源读取预测文件跑融合全量回测。

背景：
  registry.jsonl 中绝大多数记录的 path 字段指向外部套件
  C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/...，
  fusion_backtest.resolve_path() 对这些存在的外部文件会直接读取，导致评测混读外部副本。
  本包装脚本 monkey-patch resolve_path，把任何含 /football-quant-fusion/backtest/
  的 path 重定向到 --store 指向的仓库内 backtest/predictions/...，
  不修改 registry.jsonl（哈希链不可动）。

用法：
  python run_internal_backtest.py --store <仓库内backtest目录> --output <报告.json>
其余参数与 fusion_backtest.py 一致（--snapshot-policy / --walk-forward-folds 等）。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\skill\football-quant-fusion\scripts")
sys.path.insert(0, str(SCRIPTS))

import fusion_backtest as fb  # noqa: E402

MARKER = "/football-quant-fusion/backtest/"

# 审计计数（redirect=外部路径重定向到仓库内；direct=原本就在仓库内；missing=仓库内找不到）
_AUDIT = {"redirect": 0, "direct": 0, "missing": 0, "checked": 0}


def resolve_internal(p_str, root):
    """把外部套件 path 重定向到仓库内 predictions；其余路径原样返回。"""
    norm = str(p_str).replace("\\", "/")
    if MARKER in norm:
        tail = norm.split(MARKER, 1)[1]
        cand = root / tail
        _AUDIT["checked"] += 1
        if cand.exists():
            _AUDIT["redirect"] += 1
            return cand
        _AUDIT["missing"] += 1
        return Path(p_str)  # 保留原路径，交由调用方 p.exists() 过滤
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
    # main() 正常返回后，把审计信息打到 stderr，不污染 stdout 的 JSON 报告
    print(f"[run_internal_backtest audit] {_AUDIT}", file=sys.stderr)
