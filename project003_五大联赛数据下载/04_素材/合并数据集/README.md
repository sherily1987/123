# 五大联赛合并数据集（体彩快照 × football-data 46696）

生成时间：2026-08-02　脚本：[merge_big5_snapshots.py](../../02_脚本/merge_big5_snapshots.py)

## 用途与口径

把两套样本按联赛去重合并，缺字段的样本不丢弃：

1. **football-data 五大联赛 46696 场**（`shared/zu-yu-dashi-3/datasets/football_data_big5_backtest.json`）
2. **体彩竞彩快照 378 条**（`shared/football-quant-fusion/backtest/snapshots/by_league/{英超,西甲,意甲,法甲,德甲}.jsonl`）

合并规则：
- 去重键 =（联赛, 北京时间开球日期+分钟, 主队中文canonical, 客队中文canonical）；
- football-data 的开球时间按**英国时间→北京时间**换算（冬令时+8h / 夏令时+7h）；
- 中英文队名靠"同联赛同日同时刻恰有一场对一场"自动挖掘别名表（95 条）；
- 同场比赛两源都有时合并进一条记录：体彩字段（中文队名/盘口快照/赛果）为主，
  football-data 字段（season/div/actual/odds/football_data）并入，`sources` 标明来源；
- 两源都匹配不上/缺字段的样本原样保留（如法甲 4 条、德甲 3 条体彩独有）。

## 输出（技能数据集目录）

`shared/football-quant-fusion/datasets/merged_big5/`

| 联赛 | football-data | 体彩快照 | 跨源同场 | 合并后 |
| --- | ---: | ---: | ---: | ---: |
| 英超 | 9880 | 60 | 60 | 9880 |
| 西甲 | 9878 | 98 | 98 | 9878 |
| 意甲 | 9575 | 107 | 107 | 9575 |
| 法甲 | 9407 | 58 | 54 | 9411 |
| 德甲 | 7956 | 55 | 52 | 7959 |
| **合计** | **46696** | **378** | **371** | **46703** |

同目录还有 `summary.json`（完整统计）与 `team_alias.json`（挖掘到的中英文队名别名）。

## 字段说明（合并记录）

- `home/away`：中文队名（体彩口径）；`home_en/away_en`：英文队名（football-data 口径）
- `kickoff`：北京时间；`match_id`：体彩官方 ID；`match_uid`：football-data ID
- `season/div/actual/fd_odds/football_data`：football-data 侧字段
- `snapshots/result_1x2/score_90/...`：体彩盘口快照与赛果
- `sources`：`["sporttery", "football-data"]`（合并）/ 单源

## 维护

数据源更新后重跑：`python 02_脚本/merge_big5_snapshots.py`（输出会覆盖合并目录）。
若别名挖掘率下降，检查两源开球时间口径是否变化（默认：football-data 为英国时间）。
