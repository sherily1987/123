# R2④ power 去水下重拟合体彩 K/T（结论：不切换，验证过的负结果）

日期：2026-08-02　脚本：[refit_kt_power.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\refit_kt_power.py>)

## 协议

- 数据：体彩2026收盘HAD（closing_had + 赛果），train 940（<2026-05-17）/ test 410（>=2026-05-17），与原 1348 场切分一致
- 去水：power（当前生产默认）；K×T 网格（K∈[0.80,1.40]、T∈[0.80,1.20]），train ECE 选优，test 报告

## 结果

| 配置 | train Brier / ECE | **test Brier / ECE** | test LL |
| --- | ---: | ---: | ---: |
| 重拟合 K=1.16 / T=0.82 | 0.6002 / 0.0054 | 0.5580 / 0.0255 | 0.9422 |
| **现有 K=1.14 / T=0.96（proportional 拟合）** | 0.6020 / 0.0191 | **0.5554 / 0.0172** | **0.9378** |
| 无校准 K=1.0 / T=1.0 | 0.6058 / 0.0363 | 0.5582 / 0.0210 | 0.9422 |

## 结论（负结果，防了一次错误切换）

- power 下重拟合选出的 T=0.82 是**训练集过拟合**：train ECE 0.0054（最优）但 test ECE 0.0255（最差）；
- 现有 K=1.14/T=0.96 在 power 去水下**测试集依旧最优**（Brier 0.5554、ECE 0.0172、LL 0.9378）——说明该校准层对去水方法稳健，不需要因切 power 而重拟合；
- **引擎不变**：`DRAW_CALIBRATION_K=1.14`、`CALIBRATION_TEMPERATURE=0.96` 维持；
- 附带确认：去水切 power 的收益（三源验证）不受影响，校准层兼容。

## 跟进

- 若体彩样本继续增长（>2000），可重跑本脚本复核（选择准则建议换成 test-ECE 或嵌套验证，避免 T 过拟合）；
- O/U Platt 校准层同样按 proportional 拟合，暂无证据需要重拟合（其输入为聚合层，方法敏感性更低），可定期复核。
