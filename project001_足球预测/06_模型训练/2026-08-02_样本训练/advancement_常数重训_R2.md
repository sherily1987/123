# R2① 双回合晋级常数重训（点球 / 加时）

日期：2026-08-02　脚本：[train_advancement.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\train_advancement.py>)　样本：[advancement_library.jsonl](</H:\claude AI自媒体\project001_足球预测\06_模型训练\2026-08-02_样本训练\advancement_library.jsonl>)（280 系列）

## 估计结果

| 常数 | 旧默认 | 新值（样本估计） | 95% CI | 样本 |
| --- | ---: | ---: | ---: | ---: |
| penalty_home_prob（次回合主场点球胜率） | 0.50 | **0.38** | [0.21, 0.57] | 24 场点球决胜（次回合主场 9/24） |
| et_tempo（加时进球率相对 90 分钟的倍率） | 0.92 | **0.83** | [0.63, 1.02] | 31 场加时系列（49 加时球 / 178 常规球） |

## 方法

- 点球：从两回合样本库取 24 场点球决胜，按"次回合主场球队"口径计点球胜率（bracket 约定 team1 打首回合主场、team2 打次回合主场 → 点球在次回合主场球队场地）。Wilson 95% CI。
- 加时：从 Wikipedia 淘汰赛/资格赛页的 `{{Football box|aet=y}}` 块抓取进球时间戳，≥91 分钟计为加时球；90 分钟总进球 = 两腿最终进球（bracket 含加时后的最终比分）− 加时球。tempo = 3 × Σ加时球 / Σ90分钟球。
- 覆盖：280 系列中 31/35 加时系列匹配到 box（其余 4 场为队名变体/页面缺失），48 场点球? 24 场点球全匹配。

## 解读

- **点球主场优势为负（0.38）**：样本内次回合主场球队只赢了 9/24 场点球。这与"真正显著的是先罚方优势、主场优势接近零"的公开研究方向一致，也提示当前引擎把主队当"点球有利方"可能方向性错误。⚠️ n=24、CI 含 0.50，属于小样本方向性证据，非定论。
- **加时进球率约为 90 分钟的 83%**（旧 0.92 偏高但仍在 CI 内）：加时更谨慎、换人后进攻质量下降，方向合理。

## 引擎变更

- `predict.py`：`PENALTY_HOME_PROB_DEFAULT = 0.38`、`ET_TEMPO_DEFAULT = 0.83`（附样本/CI 注释）；
- `derived_market_status.advancement`：UNFITTED → **FITTED-SMALL**（标注 n 与 CI，提醒绝对概率谨慎解读）；
- 回归：4 场批量仅 derived_market_status 文案变化；两回合冒烟（first_leg=1-1）输出 via_pens_home 6.4% vs via_pens_away 10.4%（主队点球劣势已体现）、to_extra_time 27.6%。

## 跟进项

1. 补充欧冠资格赛更早赛季 + 国内杯赛（点球样本到 100+ 后再定方向）；
2. 用首回合 λ 检验两腿独立性假设（advancement 目前假设两腿独立泊松）；
3. 加时换人/红牌等状态未建模（记录为模型边界）。
