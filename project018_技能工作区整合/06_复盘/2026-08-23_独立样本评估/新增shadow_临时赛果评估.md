# 新增 shadow 临时赛果评估（研究-only）

来源：Sporttery 官方结算链 `2026-08-23 --dry-run`。本文件只记录内存评估，未写入正式结算库。

| 样本数 | hybrid Brier | market Brier | Brier 差值 | hybrid LogLoss | market LogLoss | LogLoss 差值 |
|---:|---:|---:|---:|---:|---:|---:|
| 3 | 0.595880 | 0.588599 | +0.007281 | 0.989132 | 0.977415 | +0.011717 |

结论：新增 3 场中 hybrid 暂未优于同场 Sporttery 市场基线。样本极少，仅作过程诊断，不能据此调参或开放投注。

涉及比赛：`sporttery-2041001`、`sporttery-2041002`、`sporttery-2041003`。
