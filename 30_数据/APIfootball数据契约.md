---
type: data-contract
provider: apifootball.com
api_version: v3
updated: 2026-08-08
---

# APIfootball数据契约

## 接口与用途

| 接口 | 用途 | 当前限制 |
|---|---|---|
| `get_events` | 历史赛果、进球、赛程、状态 | 必须区分90分钟/加时/点球/延期 |
| `get_statistics` | 射门、射正、禁区内射门、控球等 | 赛后过程数据；当前不稳定提供xG |
| `get_standings` | 积分榜、主客场表现 | 默认是请求时榜单，历史比赛需快照或重建 |
| `get_lineups` | 首发、替补、缺阵、教练 | 必须验证采集时间是否早于开球 |
| `get_predictions` | 官方数学预测概率 | 保存为`p_apifootball`，不是xG |
| `get_odds` | 国际赔率、亚洲盘、大小球、BTTS | 只进入市场层和CLV研究 |

## 原始数据位置

```text
api_football
```

## 特征数据位置

```text
api_features
```

典型字段：

```text
as_of
pre_kickoff_usable
history_matches
team_strength
rolling_statistics
standings
lineups
official_prediction
external_market
no_future_leakage
```

## 时间规则

```text
collected_at < kickoff
```

才可以作为当前比赛赛前数据。否则保留原始证据，但状态必须是：

```text
POST_MATCH_NOT_USABLE
```

## xG规则

当前实测APIfootball统计中没有稳定xG字段：

```text
Shots Total ≠ xG
prob_HW/prob_D/prob_AW ≠ xG
```

## 事实源

- 适配器：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_adapter.py`
- 特征构建：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_model_features.py`
- 数据契约：`C:\Users\Administrator\.codex\skills\football-quant-fusion\references\data_contract.md`
