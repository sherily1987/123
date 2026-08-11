# R1① Dixon-Coles 团队强度模型（时间衰减）

日期：2026-08-02　脚本：[team_strength.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts\team_strength.py>)

## 模型

- 数据：football-data 五大联赛 44944 场（截止 2025-07-01，含 1X2 赔率与全场比分）
- 结构：λ_home = exp(主场优势 + α主 + β客)，λ_away = exp(α客 + β主)
- 目标：时间衰减加权泊松对数似然 + Dixon-Coles τ 修正（ρ=-0.08，与引擎一致）
- 权重：w = exp(-ln2·(t_max−t)/500天)
- 拟合：scipy L-BFGS（97 次迭代、7.7 秒收敛），Σα=0 约束重归一化
- 覆盖：217 支五大联赛球队

## OOS 验证（2025/26 整季，训练未泄漏）

| 指标 | DC 模型 | 市场 | 频率基线 |
| --- | ---: | ---: | ---: |
| n | 1680 | 1680 | 1680 |
| Brier | 0.5993 | **0.5833** | 0.6478 |
| LogLoss | 1.0041 | **0.9799** | 1.0710 |
| 准确率 | 50.7% | **53.1%** | 45.7% |

分联赛 Brier（模型 vs 市场）：法甲 0.586 vs 0.574、西甲 0.587 vs 0.571、意甲 0.597 vs 0.585、德甲 0.590 vs 0.580、英超 0.635 vs 0.610。

## 诚实解读

- **模型优于频率基线（0.599 < 0.648）**，具备真实预测信息；
- **模型不及市场（0.599 > 0.583）**——与引擎已证明的信息论边界一致：公开数据模型不可能打败市场；
- 因此用途定位：
  1. **无盘口比赛的 model_first λ**（替代 Elo 启发式，杯赛早轮/未开盘场景）；
  2. **官方前瞻 λ 先验的对手强度调整**（修复"近10场简单均值"缺陷）；
  3. 与市场 λ 对照量化分歧。
- 当前 ratings 拟合截止 2025-07-01，用于更晚比赛会随时间陈旧，建议月度重拟合（约 8 秒/次）。

## 接入方式

```sh
python scripts/team_strength.py --predict-home "Arsenal" --predict-away "Liverpool" --ratings <ratings.json> --prior
# 输出 lambda_prior（weight=0.02 软先验）可直接并入模型输入；覆盖外球队返回 UNFITTED_TEAM
```

示例（Arsenal vs Liverpool）：λ 1.575/1.284 → 1X2 45.1/22.8/32.1%，先验 dict 已就绪。

## 下一步

1. 芬超/瑞超/巴西甲按联赛拟合（数据已下载，脚本通用）；
2. 月度/周度滚动重拟合并入 daily-pipeline；
3. 与"近10场均值先验"做 λ 位移与盘口拟合代价的对比回测后决定默认权重；
4. 真实 xG（Understat）通道与双变量泊松/负二项 ensemble（R2）。
