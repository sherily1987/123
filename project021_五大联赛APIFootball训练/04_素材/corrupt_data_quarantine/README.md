# 坏数据隔离区

## fd_kor_events.jsonl.CORRUPT_NORWAY_DATA（2026-08-12 隔离）

**问题**：此文件 31 支"球队"全部是挪威联赛球队（Aalesund/Molde/Rosenborg/Bodo-Glimt 等），
不是韩职 K League 球队。

**根因（已查明）**：football-data.co.uk 的 `new/KOR.csv` 实际重定向到 `new/NOR.csv`
（挪威 Eliteserien）——football-data 根本没有韩职数据文件，当初下载时把挪威数据
当韩职入库，`team_id_basis=name_derived` 掩盖了错误。

**影响**：`run_full_backtest.py` 自动发现 `fd_*_events.jsonl` 曾把它当"韩 K1"训练，
报告里"韩 K1 695 场 +0.0290"实为挪威数据成绩，**无效**。2026-08-12 起已隔离，
不再被自动发现。

**替代源状态**：football-data.co.uk 无韩职；apifootball 套餐无韩职（count=0）；
fbref 有 K League 1（comps/55）但被 Cloudflare 拦截。韩职数据待可行源。
