# APIFootball 欧冠回测结算设计

## 目标

在现有 `football-quant-fusion` 回测链路中增加 APIFootball 赛果补全能力。体彩官方赛果仍是优先来源；官方结果缺失时，APIFootball 可补全普通完赛比赛，并对无法可靠拆分90分钟、加时和点球的淘汰赛停止自动结算。

## 范围

本项目负责：

- 从 `APIFOOTBALL_COM_KEY` 调用 `get_events` 获取待回测比赛的赛果；
- 将供应商返回值标准化为可审计的结算候选；
- 按严格身份规则将结算候选与赛前预测登记匹配；
- 把可靠的90分钟比分写入现有 `results/<match_id>.json`；
- 记录来源、供应商比赛 ID、匹配方式、原始字段和冲突状态；
- 让 `fusion_cli.py settle` 与 `auto_backtest.py --settle` 可显式启用 APIFootball 补全。

本项目不负责：

- 使用赛后统计、首发或球员表现重新生成赛前特征；
- 用供应商预测结果制造独立 edge；
- 从含糊的最终比分猜测90分钟比分；
- 修改已经存在且来源更高优先级的正式结算结果；
- 把点球大战结果计入胜平负、比分、大小球或 BTTS 的90分钟回测。

## 来源优先级

结算顺序固定为：

1. 体彩官方 `match_id` 精确结果；
2. 体彩官方按日期、主客队匹配结果；
3. APIFootball 精确 `match_id` 结果；
4. APIFootball 经赛事、开球时间和双方球队唯一匹配的结果；
5. 无唯一结果时保持待结算。

APIFootball 不覆盖已存在的体彩官方正式结果。两个来源比分冲突时写入冲突审计，状态为 `source_conflict`，不得进入正式回测分母。

## 数据结构

标准化候选采用 `apifootball-settlement-candidate-1.0`：

```json
{
  "schema": "apifootball-settlement-candidate-1.0",
  "provider": "apifootball.com",
  "provider_match_id": 123456,
  "status": "finished",
  "competition": "UEFA Champions League",
  "kickoff": "2026-03-11T20:00:00+08:00",
  "home": {"id": 1, "name": "Home"},
  "away": {"id": 2, "name": "Away"},
  "score_90": {"home": 1, "away": 1},
  "score_extra_time": null,
  "score_penalties": null,
  "score_90_status": "verified",
  "raw_score_fields": {},
  "collected_at": "2026-08-12T00:00:00Z"
}
```

`score_90_status` 只允许：

- `verified`：供应商字段足以确认90分钟比分；
- `not_finished`：比赛未完成；
- `ambiguous_extra_time`：发生加时但无法确认90分钟比分；
- `ambiguous_penalties`：点球字段存在但常规时间边界不可靠；
- `invalid_score`：比分字段缺失、自相矛盾或无法解析。

只有 `verified` 可以写入正式结果库。

## 90分钟、加时和点球规则

- 普通完赛且不存在加时、点球迹象时，最终主客比分可作为 `score_90`。
- 供应商明确提供独立的90分钟比分时，使用该字段，并保留加时与点球字段供晋级回测。
- 供应商只给最终比分或 `extra_score` 与最终比分相同，且比赛存在加时或点球迹象时，不推算90分钟比分，标记为歧义。
- 点球大战只写入 `score_penalties`，不得改变 `score_90` 的胜平负。
- 未完赛、延期、取消、腰斩和无效场次不得结算。

## 比赛匹配

匹配优先级：

1. 预测登记中的 `provider_refs.apifootball_match_id` 精确命中；
2. 赛事 ID、双方供应商球队 ID 与开球时间共同命中；
3. 配置化球队别名、赛事、主客顺序与开球时间窗口共同唯一命中。

禁止仅凭模糊队名自动结算。时间匹配窗口默认 ±30 分钟；窗口内多场候选、主客颠倒、赛事不符或球队别名缺失时，返回 `ambiguous_match`。未来新预测登记应保存 APIFootball `match_id`，逐步消除别名匹配。

## 组件与数据流

新增组件放在 `project022_APIFootball欧冠回测结算/02_脚本/`：

- `apifootball_settlement.py`：标准化比分阶段、匹配候选并生成结算决策；
- `settle_from_apifootball.py`：读取待结算登记、调用供应商接口、输出候选与审计，并通过现有 `settle_result.py` 写入结果；
- `team_aliases.json`：只保存已验证的球队别名映射；
- 对应测试文件：覆盖普通完赛、未完赛、加时歧义、点球歧义、精确 ID、唯一身份匹配、多候选和来源冲突。

接入点：

```text
registry.jsonl
  -> 读取待结算预测
  -> 体彩官方结算
  -> 对仍待结算项调用 APIFootball
  -> 标准化比赛阶段
  -> 严格身份匹配
  -> verified 才调用 settle_result.py
  -> 写入审计报告
  -> fusion_backtest / backtest_dual_track
```

`fusion_cli.py settle` 增加显式参数 `--apifootball-fallback`。默认不改变现有体彩结算行为。`auto_backtest.py --settle --apifootball-fallback` 才启用供应商补全。

## 结果文件与审计

每次运行写入本项目 `05_交付/settlement_runs/<运行时间>/`：

- `candidates.jsonl`：供应商标准化候选；
- `settlement_audit.json`：每场匹配方式、状态、来源和拒绝原因；
- `settled.json`：本次正式写入的比赛；
- `conflicts.json`：来源冲突或身份冲突；
- `run_metadata.json`：运行参数、脚本哈希、数据窗口和供应商来源。

结算操作保持幂等：同一比赛已有相同比分时跳过；已有不同比分时进入冲突，不覆盖。

## 错误处理

- 缺少 `APIFOOTBALL_COM_KEY`：返回 `missing_credential`，不影响体彩官方结算。
- 接口失败或限流：按现有适配器重试后记录 `provider_unavailable`，保留待结算状态。
- 无赛果：记录 `no_result_yet`。
- 赛事身份不唯一：记录 `ambiguous_match`。
- 比分阶段不可靠：记录 `needs_review`，并附具体歧义原因。
- 来源冲突：记录 `source_conflict`，停止该场自动结算。

任何 APIFootball 失败均不得阻断已经完成的体彩官方结算。

## 测试与验收

实现采用测试先行，最低验收条件：

- 普通完赛能生成正确90分钟比分；
- 加时、点球无法可靠拆分时不会自动结算；
- 未完赛不会结算；
- 供应商 ID 精确匹配优先于别名匹配；
- 多候选或主客颠倒不会自动结算；
- 已有体彩结果不会被覆盖；
- 来源冲突不进入正式回测分母；
- 运行输出不包含 API key；
- 原有 `settle`、`backtest` 和 `auto_backtest` 测试保持通过；
- 使用真实历史样本做一次 `--dry-run`，报告正式可结算、待人工复核、未匹配和冲突数量。

## 成功标准

当体彩官方结果缺失时，普通完赛欧冠比赛可以由 APIFootball 自动、幂等地补全；所有加时、点球、身份和来源歧义均停止自动写入，并能从审计报告追溯到原始字段与判断原因。
