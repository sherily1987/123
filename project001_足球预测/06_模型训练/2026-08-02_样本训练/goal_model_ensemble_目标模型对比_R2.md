# R2③ 目标模型对比（DC / 双变量泊松 / 负二项 / ensemble）

日期：2026-08-02　脚本：[goal_model_ensemble.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts\goal_model_ensemble.py>)

## 协议

- 数据：football-data 五大联赛 46696 场（λ 由市场 1X2 power 去水 + solve_lam_from_probs 反解，与引擎同口径）
- 样本：等距抽样 23348 场，时间切分 train 16343 / test 7005
- 每个模型独立拟合温度 T（train 比分 LogLoss 网格）；BP 网格 λ3∈{0.05,0.1,0.15}、NB 网格 r∈{4,8,16}

## 结果（test 7005）

| 模型 | 参数 | 比分LL | Top1% | Top3% | ECE | OU2.5 Brier | BTTS Brier |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DC（基线） | ρ=-0.08, T=1.4 | 2.9247 | 10.92 | 30.51 | 0.00023 | 0.24225 | 0.25507 |
| **双变量泊松 BP** | λ3=0.05, T=1.3 | **2.9137** | **11.56** | **32.36** | **0.00003** | **0.24209** | **0.25122** |
| 负二项 NB | r=4, T=1.3 | 2.9863 | 9.32 | 26.94 | 0.00060 | 0.24355 | 0.26363 |
| 等权 ensemble | DC+BP+NB | 2.9373 | 10.55 | 30.11 | 0.00026 | 0.24256 | 0.25603 |

## 结论

1. **双变量泊松（λ3=0.05）全维度优于 DC 基线**：比分 LL -0.011、Top1 +0.64pp、Top3 +1.85pp、ECE 降 87%、OU/BTTS Brier 均改善。低比分主客进球正相关（λ3>0）比 DC 的低比分修正更贴近真实结构。
2. **负二项被否定**：过离散把概率质量推向极端比分，比分 LL +0.06、Top1 -1.6pp，OU/BTTS 也变差——当前数据下不应采用。
3. **等权 ensemble 稀释最优模型**（LL 2.937 > BP 2.914）——BP 已足够，无 ensemble 收益；若未来要 ensemble，需在 train 上拟权重而非等权。

## 接入生产（2026-08-02 已完成，双矩阵并行）

- `predict.py` 新增 `bp_matrix()`；`SCORE_MODEL='bp'`、`SCORE_LAMBDA3=0.05`、`SCORE_TEMPERATURE_FT=1.30`；
- **双矩阵并行设计**：1X2 路径（λ 反解 solve_lam_from_probs / one / sensitivity）保留 DC 矩阵，保证无损复现市场零扰动；衍生市场（比分/O-U/BTTS/HHAD/AH/晋级/TTG一致性）切换 BP。
- 回归（4 场批量）：final_1x2 与 model_1x2 **逐项一致**；OU2.5 +1.5~2.5pp、BTTS +2.4~3.6pp、Top1 微移（OOS 验证的改善方向）；fresh market_only 的 1X2 与切换前一致（K/T 校准路径未受影响）；两回合/无盘口冒烟正常。
- 半场矩阵（T=1.22）暂沿用 DC 拆分，BP 半场属后续项。
