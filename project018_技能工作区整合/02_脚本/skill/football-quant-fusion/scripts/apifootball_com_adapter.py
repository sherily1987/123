#!/usr/bin/env python3
"""Runtime entry point for the apifootball.com adapter.

The project007 file is the auditable source copy; this launcher keeps the
active consolidated skill path callable without duplicating implementation.
"""
from __future__ import annotations

import runpy
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[5]
SOURCE = WORKSPACE / "project007_APIFootball数据接入" / "02_脚本" / "apifootball_com_adapter.py"

if not SOURCE.is_file():
    raise SystemExit(f"适配器源文件不存在: {SOURCE}")

runpy.run_path(str(SOURCE), run_name="__main__")
