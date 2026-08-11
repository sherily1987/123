# 五大联赛数据下载

本项目用于从 FBref 批量保存英超、西甲、意甲、德甲和法甲的赛季统计页面。

- `01_规划/`：下载范围与字段说明
- `02_脚本/`：批量下载脚本
- `04_素材/`：原始 HTML/CSV 数据
- `06_复盘/`：下载日志与异常记录

运行：`python 02_脚本/download_fbref_big5.py`

由于 FBref 对批量请求可能返回 403，逐场比赛公开 CSV 可运行：`python 02_脚本/download_match_csv.py`。该数据来自 football-data.co.uk，不等同于 FBref 的球员/高级统计表。

脚本默认尊重站点访问频率（每次请求间隔 3 秒），断点续传，遇到失败会写入 `06_复盘/download_log.csv`。

## 2026-08-02 五大联赛回测样本登记

- 378 场已结算竞彩快照（2026 年 1–5 月，官方 HAD 四快照+赛果）已批量登记为融合回测样本：
  370 场登记、369 场可回测（英超 57 / 西甲 98 / 意甲 105 / 德甲 53 / 法甲 56）。
- 脚本：`02_脚本/build_big5_backtest_samples.py`（登记）与 `02_脚本/backtest_big5_fusion.py`（评估）。
- 基线报告：`05_交付/big5_backtest_closing_2026H1.json`；复盘见 `06_复盘/2026-08-02_五大联赛回测样本登记.md`。

## 2026-08-02 四快照对比（追加）

同批样本已补登记 opening / t-24h / t-6h，共 1,442 条登记样本。结论：closing 判别力最优
（Brier 0.6116、命中 51.8%），opening 校准最好但判别力弱；英超 closing 异常为小样本波动，
暂不动校准参数。完整对比见 `05_交付/五大联赛快照对比报告_2026H1.md`。

## 2026-08-02 英超样本积累跟踪

- 目标：英超已结算样本攒到 200+ 后做时间序列切分校准复审（当前 57/200）。
- 跟踪：`python 02_脚本\track_epl_sample_progress.py`；计划见 `05_交付/英超样本积累与校准复审计划.md`。
- 持续采集：每日 `fusion_cli.py daily-pipeline --kickoff-date YYYY-MM-DD`（英超 8 月中旬新赛季开赛后开始累积）。

## 2026-08-02 每日采集自动化

- 已注册 Windows 计划任务 `Codex-FusionDailyPipeline`（每天 10:00 运行
  `02_脚本/run_daily_pipeline.ps1`，日志入 `04_素材/daily_pipeline_logs/`），实测运行成功。
- 停用：`schtasks /delete /tn Codex-FusionDailyPipeline /f`。
