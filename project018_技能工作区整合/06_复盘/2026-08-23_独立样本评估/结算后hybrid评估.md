# 结算后 hybrid 评估（2026-08-23）

本轮已用 Sporttery 官方 90 分钟结果正式结算 5 场，其中 3 场具有独立 hybrid shadow 概率，进入有效配对评测。其余结算场次没有 hybrid 侧车，不计入 hybrid 分母。

- 有效配对样本：9 场
- hybrid 相对市场 Brier 差值：`+0.004503`
- hybrid 相对市场 LogLoss 差值：`+0.010416`
- 结论：仍未优于市场基线，暂不调整生产权重、不开放 Kelly 仓位。
- 路由：全部保持 `research_only=true`，Sporttery 仍是唯一生产赔率和结算源。

新增 3 场结算样本为 `sporttery-2041001`、`sporttery-2041002`、`sporttery-2041003`；完整机器结果见 `hybrid_evaluation_after_settle.json`。
