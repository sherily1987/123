---
type: goals-only-experiment
experiment_id: apifootball-goals-only-experiment
provider: apifootball.com
model_version: apifootball-goals-only-experiment
status: planned
production_mode: MARKET_BASELINE
created: 2026-08-09
---

# APIfootball goals-only实验

## 与Understat xG实验分开

| 项目 | Understat xG实验 | APIfootball goals-only实验 |
|---|---|---|
| 数据源 | Understat | apifootball.com `get_events` |
| 目标 | xG→λ、概率校准 | 历史进球动态攻防强度、概率校准 |
| xG | 使用 | **不使用** |
| 统计射门 | 不作为本实验必需字段 | **不使用** |
| 评测范围 | 五大联赛 | 其他联赛 |
| 生产模式 | MARKET_BASELINE | MARKET_BASELINE |

## 实验联赛

| 联赛 | league_id | 目标 | 当前登记 |
|---|---:|---:|---:|
| 荷甲 Eredivisie | 244 | 100 | 0 |
| 葡超 Primeira Liga | 266 | 100 | 0 |
| 土超 Super Lig | 322 | 100 | 0 |
| 苏格兰 Premiership | 279 | 100 | 0 |
| 瑞士 Super League | 308 | 100 | 0 |
| 挪超 Eliteserien | 253 | 100 | 0 |
| **合计** | — | **600** | **0** |

## 数据口径

只使用：

```text
get_events
match_id
league_id
kickoff
team_ids
官方90分钟比分
```

排除：

```text
After ET
After Pen.
Postponed
Cancelled
Awarded
```

## 评测组

```text
control：MARKET_BASELINE
experiment：goals_only_dynamic_dixon_coles
```

两组使用同一场比赛、同一开球前输入、同一官方90分钟赛果。

## 严格禁止

- 不把APIfootball射门统计改名为xG；
- 不把官方预测概率当成历史xG；
- 不把赔率放进独立goals-only攻防训练；
- 不把本实验样本并入Understat xG样本；
- 未完成样本外验证前不改变生产权重。

## 允许改权重的条件

```text
每联赛至少100场
时间顺序样本外验证
goals_only不劣于MARKET_BASELINE
Brier和Log Loss有稳定改善
ECE不恶化
paired bootstrap支持
```

任何权重变化都必须创建新的完整模型身份哈希。

## 事实源

- 实验清单：`模型评测/apifootball-goals-only-experiment_20260809.json`
- APIfootball适配器：`C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/apifootball_adapter.py`
- Understat独立实验：[[Understat xG实验]]
- 总评测规则：[[样本积累与评测规则]]
