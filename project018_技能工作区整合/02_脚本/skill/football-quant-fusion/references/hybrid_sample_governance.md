# Hybrid 样本管道与版本窗口

2026-08-26 固化。本文件是分母与验收契约的唯一细则；SKILL 只保留硬规则。  
数字快照以 `06_复盘/2026-08-26_hybrid样本管道治理/` 与 `config/hybrid_review_cohort.json` 为准，禁止把过期 n 写进技能当永恒事实。

## 四个分母（禁止跨口径运算）

| denominator_id | 定义 |
|---|---|
| `REGISTERED_HYBRID_BACKTEST_V1` | 回测登记 hybrid 路由 |
| `FROZEN_HYBRID_SIDECAR_AUDIT_20260824` | 指定冻结日的侧车覆盖 |
| `LIVE_HYBRID_REVIEW_UNIQUE` | 唯一 `match_id` 的最后一次合格赛前运行，再按完整 cohort 分组 |
| `HISTORICAL_HYBRID_REPLAY_CURRENT` | 当前签名下的无泄漏历史补跑 |

不得相减、拼接或把某一分母的 Brier 安到另一分母的 n 上。  
2026-08-26 快照：登记 hybrid n=12、Brier 0.64358；冻结侧车 121 行中有效 12 行 Brier 0.628422；实时唯一赛前 n=31（已结算 30）；历史补跑合格 899，判定 `NO_EVIDENCE`。

冻结 121 行淘汰原因不可混用：非独立/未成功 33（口径，以后不写侧车）、缺路由审计 54（工程，Sidecar v2 缺字段非零退出）、赛后运行 3（不可补救）、冻结时缺核验 90 分钟赛果 19、有效 12。

## 身份

`hybrid_cohort_key = model_version + "::" + probability_signature`。  
Sidecar v2 成功记录必须同时持久化完整 `model_version`、64 位 `probability_signature`、`hybrid_cohort_key`，并与发布锁一致。缺任一字段非零退出。禁止用 `model_version_window = current production unchanged` 充当身份。归因只读，不反写历史侧车。现有 market_only 等价别名不得外推到 hybrid。

当前研究窗口见 `config/hybrid_review_cohort.json`。窗口期内改 `probability_files_frozen` 所列文件会作废已积累样本；旧样本留在旧 cohort。

实时归因（2026-08-26）：旧签名 `m4::5c34721…ceb17197` 12 条；当前签名 `m4::48d50abee…60d0798b` 1 条；未能严格复验 18 条。

## 验收

脚本：`hybrid_admission.py`。同一完整 cohort、已结算唯一比赛 ≥100 后：

1. 按开球日期组 70/30 时间切分（开发段不得碰测试段）；
2. 测试集固定种子 10000 次同场配对 bootstrap；
3. 指标为 hybrid−market 的 Brier 差与 LogLoss 差。

| 判定 | 条件 | 后果 |
|---|---|---|
| `INSUFFICIENT_SAMPLE` | n<100 | 无评审资格 |
| `EVIDENCE_BETTER_THAN_MARKET` | 两指标 95% CI **上界均严格 <0** | 仅人工评审，不自动进生产 |
| `NO_EVIDENCE` | CI 接触或跨 0 | 不得声称优于市场 |
| `EVIDENCE_OF_HARM` | 任一指标 CI **下界 >0** | 不得推广 |

禁止只报点估计。n=100 不是证明，只是评审门槛。

## 历史补跑

自然积累在当前开发节奏下预期会在达标前因签名重置，不是主路径。补跑分母必须是 `HISTORICAL_HYBRID_REPLAY_CURRENT`：

- 墙钟：`replay_generated_at`；赛前模拟截点：`simulation_as_of`；禁止伪造 `research_run_at`；
- 逐场用开球前最后一份已核验体彩快照；历史先验严格截断在开球前；
- 当前签名一次生成；评估集不调权重。

2026-08-26 产物 `historical_hybrid_replay_current_v2.json`：899/899 合格，全部当前 cohort；开发 629 / 测试 270；测试段 Brier 差 −0.000565（CI 跨 0）、LogLoss 差 −0.000587（CI 跨 0）→ `NO_EVIDENCE`。因此凯利路径 C 保持关闭。
