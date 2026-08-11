# 韩国联赛历史数据下载

目标：保存 FBref K League 1 页面可追溯的历史比赛结果及相关公开数据。

来源页面：<https://fbref.com/en/comps/55/history/K-League-1-Seasons>

本项目优先使用 worldfootballR_data 维护的 FBref 预抓取国内联赛比赛结果，避免高频访问 FBref。若需要球员、阵容、传球、射门等完整比赛报告字段，需在 FBref 允许访问时再补抓；缺失字段不会伪造。

2026-08-02 已接收并整理 14 个 Stathead 导出文件（用户列出的 13 个编号文件加上目录中的 `sportsref_download.xls`）。导出内容识别为 13 张 K League 1 赛季积分表和 1 张球员标准数据表，已统一字段名并保留原始文件。

## 2026-08-02 补充（API-Football）

- K League 1 2022–2024 与 K League 2 2022–2024 赛果已用 `02_脚本/fetch_k_league_apifootball.py` 补齐
  （复用 project007 的 api_football_adapter，免费版，限速+断点续传）。
- 合并数据：`04_素材/标准化/k_league_1_2_results_2014_2024.csv`（K1 2,468 场 2014–2024；
  K2 694 场 2022–2024）。
- 获取与样本积累流程见 `05_交付/韩职数据获取与样本积累SOP.md`。
