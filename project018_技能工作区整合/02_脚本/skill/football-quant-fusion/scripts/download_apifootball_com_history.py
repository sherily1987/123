from __future__ import annotations
import runpy
from pathlib import Path
SOURCE = Path(__file__).resolve().parents[5] / "project007_APIFootball数据接入" / "02_脚本" / "download_apifootball_com_history.py"
runpy.run_path(str(SOURCE), run_name="__main__")
