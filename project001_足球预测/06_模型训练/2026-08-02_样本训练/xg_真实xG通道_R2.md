# R2② Understat 真实 xG 通道

日期：2026-08-02　脚本：[understat_xg.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\scripts\understat_xg.py>) + [understat_enrich.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\understat_enrich.py>)

## 数据

- `understat/matches.json` → `understat_store.jsonl`（**3503 场**五大联赛 2024/2025，含 home/away xG、进球、Understat 内置博彩 forecast）
- 覆盖：EPL / La_liga / Bundesliga / Serie_A / Ligue_1 ↔ 英超/西甲/德甲/意甲/法甲

## OOS 验证（时间切分 70/30，训练 2452 / 测试 1051）

| 指标 | xG 模型（scale=0.9） | Understat 博彩 forecast | 胜者 |
| --- | ---: | ---: | ---: |
| Brier | **0.5427** | 0.5451 | xG |
| LogLoss | **0.9194** | 0.9269 | xG |
| 准确率 | 58.3% | 58.6% | 市场（持平） |
| ECE | **0.0249** | 0.0425 | xG |

分联赛 Brier（xG vs 市场）：英超 0.5876 vs 0.5942、西甲 0.5413 vs 0.5429、德甲 0.5276 vs 0.5273（持平）、法甲/意甲略输。

**结论**：真实 xG 是引擎第一个**在 OOS 上不输（多数维度优于）市场**的独立信号——它是事件级质量数据，不是赔率/赛果的衍生子集（与 Elo 不同）。scale=0.9（xG 轻微下调）在训练集上最优，测试集保持优势。

## 接入方式

```sh
python scripts/understat_enrich.py --input match.json --output enriched.json [--mode model_first|hybrid_prior] [--prior-weight 0.05]
```

- `model_first`：写入 lambda_home/away = 成对 xG + xG 软先验；有盘口时先验参与多市场拟合（λ 被拉向 xG），无盘口时 λ≈xG、门控 AVOID_DATA_RISK（诚实）；
- `hybrid_prior`：只写 lambda_prior，市场主导 + xG 软约束。
- 演示（Everton vs Arsenal，xG 1.229/1.403）：hybrid λ=1.26/1.145（市场 1.095/0.955 → xG），pure λ=1.23/1.405，1X2 33.9/24.1/42.0。

## 核心修复（2026-08-02，插队完成）

- **已修**：`predict.py` 多市场拟合路径现在消费显式 λ——`mode=model_first` 且显式 λ 存在时，以 `W_EXPLICIT=0.85` 权重注入 `lambda_prior`（source=explicit_model_first），市场只校准/对照；标签 `EXPLICIT_XG_PRIOR`，`goal_rate.kind=model_goal_rate`。
- **已修**：纯显式路径（无盘口）的 goal_rate 标签从 proxy_lambda 纠正为 model_goal_rate（POST_FIT_LAMBDA_REENTRY 属显式 λ 流程标签，非市场代理）。
- 验证：xG model_first（有盘口）λ=1.27/1.34（xG 1.229/1.403 主导，市场仅微调 pulled 0.04/-0.06）；纯 xG λ=1.229/1.403；4 场批量回归零扰动。
- xG 仅覆盖五大联赛近两季；历史赛季/其他联赛需另行来源。

## 跟进项

1. 修核心盲点（显式 λ 入多市场拟合）；
2. xG 与 DC 团队强度模型融合（λ = 加权 xG 与 rating）；
3. 接入 daily-pipeline 自动 enrich（先验权重 0.05 需回测标定）。
