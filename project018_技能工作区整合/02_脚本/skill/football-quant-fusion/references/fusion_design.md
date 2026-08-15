# 融合设计（football-quant-fusion 1.5.0 / model m2）

> ⚠️ REBUILT 2026-08-02：原文件在文件系统同步事故中损坏，本文件基于 SKILL.md、会话记忆（2026-07-31/08-01/08-02 每日记录）恢复重建。

## 1. 定位

football-quant-fusion 是统一生产入口，覆盖单场、批量竞彩、双回合、截图赔率与回测。旧 `soccer-lottery` 与 `ucl-predictor` 只作历史对照，**生产预测、快照登记、组合、回测必须走 fusion**，旧入口不得绕过 fusion 的推荐门控、版本登记和数据使用审计。

## 2. 对旧 Skill 的保留/重写/淘汰决策

| 能力 | 来源 | 处理 |
|---|---|---|
| 体彩全盘口采集（HAD/HHAD/CRS/TTG/HAFU） | soccer-lottery 官方链路 | **保留**：采集器与官方 matchId 链路复用（fetch_sporttery_full.py），fusion 增加销售日采集器 sales_day_collect.py 并修复跨午夜漏采 |
| 批量推荐/组合/回测流水线 | soccer-lottery | **重写**：登记写完整融合 payload（fusion_record.py），组合过 fusion_combo.py 腿ID强校验，回测按 (match_id, snapshot) 去重 |
| 战意/赔率走势量化 | soccer-lottery（5星分级、赔率走势阈值） | **降级为 UNFITTED 参考起点**（motive_evidence_reference.md），纳入 adjustment_ledger 流程；**不采纳**固定加权、热度降权、超低赔率爆冷等已证伪做法 |
| 概率核心 | zu-yu-dashi-3（3.4.x） | **保留**：单一 3.4.4 概率核心（多市场 Dixon-Coles/Poisson），fusion 包装并兜底崩溃 |
| 严格数据治理/阵容伤停/双回合 | ucl-predictor | **吸收**：证据账本、market_fit 后独立事实修正、双回合 90分钟/加时/点球分离报告 |
| 赛事级 Monte Carlo | ucl-predictor | **未落地**：禁止伪称已模拟，只输出缺口与实现计划 |

## 3. 分离四个概念

1. `forecast_probability`：结果概率（脚本产生）
2. `data_quality`：输入完整度/来源/新鲜度（不是置信度）
3. `model_uncertainty`：敏感性与可靠性缺陷（必须原样展示）
4. `decision_value`：相对市场是否存在超过不确定性的差异（edge vs sensitivity）

混称"信心"是禁止的。推荐门控 `recommendation_gate` 采用 fail closed：当前 `production_recommendations_enabled=false`；UNFITTED、MARKET_BASELINE、AVOID_DATA_RISK、无显著 edge、市场依赖过高或盘口陈旧均不得出胆，`confidence_pct=null`。

## 4. 校准分层

- **核心单项盘口校准（FITTED）**：1X2（draw_k=1.14, temperature=0.96，体彩1348场时间切分训练943/测试405，ECE 0.04697→0.03456）、O/U2.5（Platt a=1.03 b=-0.08）、O/U3.5（Platt a=1.05 b=-0.11）、BTTS（**验证后刻意不校准**——Platt 反而恶化 24.4%）、星级区间（★≥70% 实测命中87.5% 等五档单调）。
- **融合层组合/edge 校准（UNFITTED）**：组合路径尚未完成独立大样本回测 → 标 `UNFITTED_FUSION`，不得声称优于市场。
- 100场、200场只作为复审触发点，不是统计证明。推广仍需样本外时间切分、基线比较、误差区间和版本一致性证据。

## 5. 数据治理要点

- 正式生产数字只由发布脚本产生；人工核验可写入 `manual_check`，不得覆盖生产字段或编造概率。
- 访问失败区分 MISSING/UNAVAILABLE/UNVERIFIED/OUTDATED/INVALID；单源失败尝试两个合理备源，不得虚构。
- football-data.org 只读环境变量 FOOTBALL_DATA_API_KEY，无覆盖标 UNAVAILABLE。
- 截图模式锁定截图数据源，读不清就请用户补图/手输，禁止联网替数。
- 所有系数列入 adjustment_ledger（事实/来源/采集时间/映射值/依据/是否回测），未回测标 UNFITTED。
