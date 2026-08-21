# 凯利研究（路径 A–C）

2026-08-18 固化。本文件是凯利相关事实的唯一细则；SKILL 只保留硬规则。  
概率模型输出，仅用于研究与决策支持，不是投注建议。

## 两个不得混称的量

| | 中文盘口凯利指数 \(G\) | Kelly 仓位 \(f^*\) |
|---|---|---|
| 公式 | \(G_i=o_i^{\text{体彩}}\times p_i^{\text{国际共识}}\) | \(f^*=\mathrm{EV}/(\mathrm{odds}-1)\)，\(\mathrm{EV}=p\times o-1\) |
| 用途 | 体彩相对国际盘的松紧（形状特征） | 独立校准 \(p\) 之后的纸面仓位 |
| 现状 | 路径 B，工单 `research.intl_kelly` | **未开放**（路径 C） |

\(G\) 的绝对水平几乎永远 \(<1\)（体彩返还低于欧洲盘）。禁止用民间口诀「\(G>1\) 才买」。有信息的是三个方向的相对差。

## 路径 A — 同一盘口卫生

脚本：LLM 工程 `ev_calculator.py`（`same_book_ev_audit` / `implied_payout`）。

有 `calibrated_probs` 时必须产出 `same_book_audit`（`research_only`）：

- `payout`：\(1/\sum(1/o_i)\)
- `ev_same_book`：三个方向对同一盘口的 EV
- `ev_vs_payout`：比例去水恒等式（返还率 \(-1\)），只作对照
- `kelly_sign`：三个 EV 是否全 \(\le 0\)
- `flags`：`market_derived` 且某方向 EV \(>0\) 时为 `KELLY_SANITY_FAIL`

`market_derived=true` 时正 EV 不是价值，是去水/校准假信号。`action` 仍为 `skip`。  
禁止输出 `kelly_fraction` / `f_star` / `stake` / `recommended_stake`。  
LLM 票比不是概率：无 `calibrated_probs` 时不得算 EV，`vote_share_table` 不得带 `ev` 键。

## 路径 B — 体彩相对国际盘的 \(G\)

脚本：`odds_api_adapter.py`（`odds-intl`）→ `intl_kelly_index.py` → `hybrid_shadow.py`。

1. `odds-intl` 追加 `odds/intl_production.jsonl`（默认关；无 `ODDS_API_KEY` 则跳过，不阻断体彩主链路）。
2. `hybrid-shadow` 在 `predict_one` **之后**按 `match_id` 取最新国际盘行，写入工单 `research.intl_kelly`，不改 match 输入。
3. 共识 \(p\)：有 Pinnacle 的 `h2h` 只用 Pinnacle；否则各家比例去水后等权平均。忽略 `h2h_lay`。
4. 字段：`index` / `gap_max_minus_mid` / `softest_direction` / `intl_source` / `ledger_entry`（`calibration=UNFITTED`，`backtested=false`）。
5. 无快照或对不上队名：`status=skipped`，`reason=intl_odds_unavailable` 或 `no_complete_h2h`。

`job_ticket.assemble_job` 把 `intl_kelly` 拆成与 `research.hybrid` 并列的侧车；`validate_job` 拒绝 `research_only≠true`、非 `UNFITTED` 校准、以及仓位字段。

## 路径 C — 纸面仓位（未开放）

前置：影子 hybrid 相对**同场市场**样本外同时更好（Brier **和** logloss），场次达到 SKILL 里的复审触发点，且 `market_derived=false`、edge 大于敏感性。  
才允许研究字段 \(f_{\mathrm{paper}}=\frac14\max(f^*,0)\)，`action` 仍为 `skip`，推荐总闸保持关闭。  
胜平负互斥，不得三个 \(f^*\) 相加。

## 分母

- 影子 hybrid 有效样本 = 工单里 `research.hybrid` 有 `final_1x2_pct` 且无 `skip_reason` 的场次。
- 不得把只有 `outputs.quant`、`research=null` 的工单算作 hybrid 样本。
- `late_info` 伤停快照不是 hybrid 概率，单独计数。
- 生产 `research_candidate` 不得冒充已跑通的 hybrid。
