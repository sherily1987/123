# 自动回测报告（20260817_074215）

- 运行时间：2026-08-17T07:42:15.590168+08:00
- 工作区：F:\HM足球比赛预测
- 共享库 settle：{"error": "[settle] matchId 直查命中 3 场（补日期分组漏项）\n{\n  \"pending\": 9,\n  \"official_finished\": 21,\n  \"settled\": 3,\n  \"report\": [\n    {\n      \"match_id\": \"sporttery-2040910\",\n      \"match\
- 共享库量化回测：成功

## 双轨（待回测记录）汇总

- 正式结算：6 场（仅计入正式分母）
- 交叉验证（不计正式分母）：0 场
- 量化 1X2：4/6（66.67%）
- LLM 双选：1/1（100.0%）

## 各日期明细

| 日期 | 正式结算 | 交叉验证 | 量化1X2 | LLM双选 | 报告 |
| --- | --- | --- | --- | --- | --- |
| 2026-08-17 | 6 | 0 | 4/6（66.67%） | 1/1（100.0%） | F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付\auto_backtest\archive\20260817_074215\dual_track\backtest_dual_track_2026-08-17_030268958088.json |
| 2026-08-18 | 0 | 0 | 0/0（None%） | 0/0（None%） | F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付\auto_backtest\archive\20260817_074215\dual_track\backtest_dual_track_2026-08-18_59d7bd5bb967.json |

## 结论边界

样本少时命中率不具结论性；SKILL 纪律：>=100 场评估、>=200 场做结论。

完整数据见同目录 JSON；共享库量化回测明细见 store_backtest_*.json。