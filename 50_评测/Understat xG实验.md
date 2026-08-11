---
type: xg-experiment
experiment_id: understat-xg-experiment
provider: Understat
model_version: understat-xg-experiment
status: planned
production_mode: MARKET_BASELINE
created: 2026-08-09
---

# Understat xG实验

## 固定配置

```text
数据源：Understat
联赛：五大联赛
样本量：每联赛100场
模型版本：understat-xg-experiment
用途：xG转λ与概率校准实验
生产模式：保持MARKET_BASELINE
```

## 目标样本

| 联赛 | 可用xG记录 | 实验目标 | 当前登记 |
|---|---:|---:|---:|
| 英超 | 760 | 100 | 0 |
| 西甲 | 760 | 100 | 0 |
| 意甲 | 760 | 100 | 0 |
| 德甲 | 612 | 100 | 0 |
| 法甲 | 611 | 100 | 0 |
| **合计** | **3503** | **500** | **0** |

## 训练与验证

```text
每个联赛按时间排序
前70%：xG→λ拟合/校准
后30%：样本外验证
```

比较组：

```text
market_baseline
goals_only
understat_xg
```

## 进入实验的条件

- 比赛有有效90分钟赛果；
- `home_xg`和`away_xg`均非空；
- 主客队、比赛日期和比赛ID可以匹配；
- 所有滚动特征满足`as_of < kickoff`；
- 当前比赛赛后统计不得回流；
- 保留source、collected_at、state_as_of和no_future_leakage。

## 不允许的操作

```text
不把历史Understat比赛伪装成当前版本预测样本
不直接修改MARKET_BASELINE权重
不把10场或单一时间段结果宣称为长期优势
不把Understat forecast当作真实xG
```

## 初次校准结果（2026-08-09）

时间顺序切分：

```text
训练：2452场
测试：1051场
最佳全局xG缩放：0.9
```

| 指标 | Understat xG | Understat forecast对照 |
|---|---:|---:|
| Brier | 0.542692 | 0.545052 |
| Log Loss | 0.919378 | 0.926858 |
| 1X2命中率 | 58.33% | 58.61% |
| ECE | 0.024922 | 0.042525 |

配对bootstrap（5000次）：

```text
Brier差值 xG−旧版：-0.002360
95% CI：[-0.007408, 0.002629]

Log Loss差值 xG−旧版：-0.007480
95% CI：[-0.020112, 0.005059]
```

解释：xG实验组点估计更好，但置信区间跨0，当前只能记录为改善信号，不能宣称稳定优于旧版，也不立即改变生产权重。

## 允许改权重的条件

达到每联赛100场并完成时间顺序样本外验证后，若同时满足：

- Brier和Log Loss不劣于旧版；
- paired差值达到预设准入标准；
- ECE没有恶化；
- 不存在单一联赛或单一时间段完全支撑总体结果；
- 没有未来信息泄漏；

才允许把Understat xG作为小比例先验进入新生产版本。改权重必须产生新的完整身份哈希，旧版样本不迁移。

## 事实源

- 实验清单：`模型评测/understat-xg-experiment_20260809.json`
- xG数据：`C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/football-quant-fusion/datasets/understat_store.jsonl`
- 处理脚本：`C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/skills/zu-yu-dashi-3/scripts/understat_xg.py`
- 当前样本积累规则：[[样本积累与评测规则]]
