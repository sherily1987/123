#!/usr/bin/env python3
"""Stable skill entrypoint for the workspace LLM evidence orchestrator."""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

root = Path(os.environ.get("FOOTBALL_LLM_ROOT") or
            r"F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\llm\football-llm-predictor").resolve()
target = root / "evidence_orchestrator.py"
if not target.is_file():
    raise SystemExit(f"LLM evidence orchestrator not found: {target}")
sys.path.insert(0, str(root))
runpy.run_path(str(target), run_name="__main__")
