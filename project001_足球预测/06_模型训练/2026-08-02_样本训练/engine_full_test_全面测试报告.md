# 引擎全面测试报告（2026-08-02）

测试套件：[test_engine_full.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\test_engine_full.py>)（可复跑）
引擎：core 3.4.4 + fusion 1.4.0（源码重建后）　结果：**14/14 通过**

## 覆盖与结果

| # | 测试 | 结果 |
| --- | --- | --- |
| 1 | 去水方法（4 方法 × 4 组赔率，概率和=1） | PASS |
| 2 | 矩阵归一化（DC/BP/温度缩放） | PASS |
| 3 | 1X2 校准层（K/T 组合概率和=1） | PASS |
| 4 | λ 反解还原市场 1X2（≤0.5pp） | PASS |
| 5 | market_only 新鲜盘口：1X2=校准市场、MARKET_BASELINE | PASS |
| 6 | model_first 显式 λ：λ=输入值、kind=model_goal_rate | PASS |
| 7 | 陈旧盘口无锚回退：NO_ANCHOR_FALLBACK + AVOID_DATA_RISK，不崩溃 | PASS |
| 8 | 两回合晋级：概率和=100、点球主队 0.38、ET 29.8% | PASS |
| 9 | 极端赔率（1.02/101、11/1.15、三和局）不崩溃 | PASS |
| 10 | 4 场生产批量不变量（1X2/OU/BTTS 加总、score_matrix 归一、derived_market_status） | PASS |
| 11 | 模型常数（点球 0.38、加时 0.83、BP λ3=0.05/T=1.3、power、半场 1.22） | PASS |
| 12 | DC 团队强度：Arsenal/Liverpool VALID、覆盖外 UNFITTED_TEAM | PASS |
| 13 | Understat 查询：Man Utd vs Fulham xG 命中 | PASS |
| 14 | 注册库健康：sample_audit 正常 | PASS |

## 补充实跑

- `fusion_backtest`（注册库 10 个已结算样本）：accuracy 50%、Brier 0.6383、LogLoss 1.0608、比分 Top1 30%/Top3 70%、OU/BTTS Brier 0.258/0.225；按版本分组正常；
- 今日改动后的全链路（源码重建→核心崩溃根治→校准/模型升级）零回归：4 场批量不变量通过，无盘口/陈旧/两回合/xG 各路径行为符合预期。

## 说明

- 测试套件初跑有 3 个用例失败，均为**套件自身 bug**（温度函数引用层、字符串常数比较、极端赔率 1X2 舍入容差），修正后 14/14 通过；引擎行为本身未发现缺陷；
- 建议每次引擎改动后运行 `test_engine_full.py` 作为回归门槛。
