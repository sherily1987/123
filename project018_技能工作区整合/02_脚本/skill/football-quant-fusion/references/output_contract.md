# 统一报告模板（output contract）

> ⚠️ REBUILT 2026-08-02：原文件损坏后基于 SKILL.md 输出节与 fusion_predict 实际输出 schema（model_output_full.json）恢复。

工单层：融合输出根字段必须含 `match_id`（`sporttery-<id>`）与 `match_num`。这是身份，不是概率。双轨对照走 `jobs/` 工单，不在本模板里合并两轨数字。

研究侧车（不得写入 `outputs[]`、不得进生产 1X2）：

- `research.hybrid`：影子 hybrid 概率，必须 `research_only=true`。
- `research.intl_kelly`：体彩相对国际盘凯利指数，必须 `research_only=true` 且 `calibration=UNFITTED`；禁止仓位字段。缺国际盘则为 `status=skipped`。
- LLM EV 层的 `same_book_audit` 同属研究字段：`market_derived` 正 EV 只标 `KELLY_SANITY_FAIL`。

## 1. 报告结构

先给总表，再逐场展开。总表列：编号 / 对阵 / 主平客概率 / 方向 / 数据质量 / 不确定性 / 决策状态。

## 2. 单场展开模板

```markdown
## ⚽ {home} vs {away} — {stage}
**开球**：{kickoff}　**模式**：{mode}　**引擎**：fusion-{v}+core-{v}　**快照**：{snapshot}

### 数据质量
| 完整度 | 来源可信度 | 新鲜度 | 综合 | 市场依赖度 | 决策 |
|---:|---:|---:|---:|---:|---|
| % | % | % | % | % | {fusion_decision.status} |

（quality.overall_pct 只叫"输入数据质量"，不是预测置信度。）

### 胜平负（90′）
| 主胜 | 平局 | 客胜 |
|---:|---:|---:|
| 45.5% | 28.5% | 26.1% |

市场公平：47.6/25.7/26.7；纯模型：48.5/22.8/28.7；最终：45.5/28.5/26.1
校准：draw_k=1.14, temperature=0.96（league_key=OTHER/BIG5）；edge：{仅独立模型可报，market_only 报 N/A}

### λ与比分
λ：1.61—1.17；来源：proxy_lambda（MULTI_MARKET_XG）；real_event_xg：null
| Top比分 | 概率 | | 半场Top | 概率 |
|---|---|---|---|---|
| 1-0 | 10.92% | | ... | ... |

**λ/零封审计**：λ高低比/零封概率；EXTREME_* flag 只能提示风险，不得改概率或表述为稳胆。

### 衍生市场
- O/U 2.5：大 50.7%（Platt 校准 applied=true, shift -1.92pp）
- O/U 3.5：大 27.3%（shift -3.11pp）
- BTTS：是 54.2%（校准 applied=false，理由：Platt 测试集恶化24.4%）
- 体彩HHAD（-1）：让胜 24.7 / 让平 23.8 / 让负 51.5；一球胜风险 23.8%（≥18% 禁单推让负）
- HHAD研究输出：主方向让负（原始概率51.5%）；当前校准状态 `UNFITTED`，只作 shadow，`banker_allowed=false`。它不是亚洲盘（win/push/half），仅指体彩固定让球线三项盘。
- 亚洲盘五态（如有 ah_line）

### 风险与门控
- reliability_flags：原样列出（HIGH_MARKET_DEPENDENCY/TTG_SCORE_CONFLICT/EXTREME_*/...）
- sensitivity：λ扰动±10%下各概率区间
- recommendation_gate：production_recommendations_enabled / banker_allowed / raw_primary_probability / calibrated_primary_probability / confidence_pct / stale_pools / reasons
- evidence_audit：统一记录 `team_stats` / `recent_form` / `injury` / `suspensions` / `starting_xi` 的 status、source_id、source_url、refreshed_at、age_hours。`starting_xi.status=PREDICTED` 表示来源明确的预计首发：可作为赛前输入并不再单独触发 `evidence_gap`，但必须保留 `PREDICTED_XI_NOT_CONFIRMED` 风险标签，且不得在报告中称为官方确认首发；官方名单发布后应生成新快照。其它关键字段缺失、未验证或赛后采集时 `evidence_gap=true`，推荐门禁按缺口处理并保留 `evidence_gap_reasons`。
- market_source_policy：HAD/TTG/HAFU/CRS 生产基准均为 Sporttery 官方赔率；国际赔率只能写入 `research_only` 侧车。
- recommendation_gate.hhad_recommendation：让球轨独立研究字段；在独立校准完成前 `calibration_status=UNFITTED`、`banker_allowed=false`

**结论**：{fusion_decision.action} —— MARKET_BASELINE 只作基线；UNFITTED_NO_VALUE / AVOID_DATA_RISK → 观察/回避。
```

## 3. 强制输出项（不可删弱）

- `reliability_flags` 与 `sensitivity` 原样展示
- `fusion_decision`：status / primary_outcome / top_gap_pp / sensitivity_width_pp / edge_pp_for_primary（market_only=null）/ uncertainty_level / action
- `core_calibration`：one_x2_calibration（applied/method/league_key/draw_k/temperature/test_set_effect）、confidence、derived_market_status——**不等同于融合推荐置信度**
- `hhad_recommendation`：available/line/primary_pick/raw_primary_probability/calibrated_primary_probability/confidence_pct/banker_allowed/reasons；非亚洲盘
- 每个可选市场必须单列 `status` 和 `value`：`VALID` / `UNAVAILABLE` / `UNFITTED` / `NOT_OFFERED`。不得用零值或推测值填补缺失市场。
- 组合：腿ID强校验结果（valid/invalid_combo_reference）+ 腿间相关性提示
- 最终固定附注：**概率模型输出，非投注建议。**

## 4. 决策状态字典

| status | 含义 | 动作 |
|---|---|---|
| MARKET_BASELINE | 仅复述市场（market_only） | 只给概率排序/玩法结构，不给价值优势，永不出胆 |
| UNFITTED_NO_VALUE | 无市场锚或无显著 edge | 观察/回避，不形成独立单选 |
| AVOID_DATA_RISK | 数据风险（陈旧/极端λ/冲突） | 回避，永不出胆 |
| blocked | 核心引擎崩溃被兜底 | 报诊断，禁止手工补概率 |

## 5. 回测报告

- 至少分版本/联赛/市场/快照；同 (match_id, snapshot_type) 一个样本（去重计数）。
- 主指标 Brier / Log Loss / ECE；命中率只作辅指标；100/200场等样本数只是复审触发点，不是统计证明。只有固定赛前策略、真实赔率、样本外基线比较和不确定性报告齐全时才评 ROI/CLV 或推广。
