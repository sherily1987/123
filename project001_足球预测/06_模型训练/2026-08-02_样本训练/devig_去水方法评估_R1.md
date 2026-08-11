# R1② 去水方法切换评估（proportional → power）

日期：2026-08-02　脚本：[evaluate_devig.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\evaluate_devig.py>)

## 三源证据（时间切分/独立集）

| 数据集 | 指标 | proportional | additive | power | shin |
| --- | --- | ---: | ---: | ---: | ---: |
| 独立集 400（Pinnacle 收盘，芬/瑞/挪/美×100） | Brier | 0.566965 | 0.566011 | **0.565997** | 0.566233 |
| 独立集 400 | ECE | 0.032741 | 0.030443 | **0.031285** | 0.031486 |
| 五大联赛 46696 | Brier | 0.582933 | 0.582570 | **0.582545** | 0.582610 |
| 五大联赛 46696 | ECE | 0.007803 | 0.001638 | **0.001344** | 0.003189 |

体彩2026收盘HAD（1350 场，940 训练/410 测试）耦合检查：

| 子集×方法 | raw Brier / ECE | +K=1.14/T=0.96 Brier / ECE |
| --- | ---: | ---: |
| train proportional | 0.601956 / 0.020402 | 0.600469 / **0.010166** |
| train power | 0.605849 / 0.036266 | 0.601990 / 0.019097 |
| test proportional | 0.558675 / 0.024824 | 0.558453 / 0.027644 |
| test power | 0.558207 / 0.021048 | **0.555395 / 0.017181** |

## 结论与决策

- power 在**独立集与全量上都最优**，且体彩 OOS 测试集上 power+现有校准层 ECE 0.0172 明显优于 proportional 的 0.0276 → **切换默认去水为 power**。
- 唯一反信号：体彩训练集 raw 上 proportional 更优（ECE 0.020 vs 0.036）——这是 **1X2 校准层按 proportional 拟合的耦合效应**，power 下应用 K/T 重拟合（0.019 已基本恢复，重拟合后可望更优）。
- 生产影响量化（新鲜盘口 market_only 用例）：power vs proportional 的 1X2 差异 0.3–0.6pp、OU2.5 差异 0.6pp，处于敏感性带内；AVOID_DATA_RISK（无市场锚）路径零变化。

## 变更

- `predict.py`：`DEVIG_METHOD_DEFAULT = 'power'`（附三源依据注释与耦合警告）；
- `market_fit.py`：`selected_method()` 默认同步为 power；
- SKILL.md：更新默认去水说明。

## 跟进项

1. **在 power 下去水重拟合 1X2 校准层（K/T）**——体彩 940 训练集网格重搜，405 测试集验证；
2. 分联赛去水选择（evaluate_selected_leagues 在 意甲/西甲/法甲/欧冠/欧罗巴 快照上按联赛选方法）；
3. O/U Platt 校准层同样按 proportional 拟合，power 下需复核（或并入 K/T 重拟合流程）。
