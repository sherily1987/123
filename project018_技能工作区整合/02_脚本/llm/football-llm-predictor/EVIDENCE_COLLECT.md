# LLM 证据采集标准（单次、可审计）

每场在一个采集窗口内尽量完成结构化 API 与网页抓取。只有通过身份、来源域名、
采集时间早于开球和关键词门禁的事实才能进入提示词；找不到就写缺口，不用投票或常识补齐。

对照成品：`data/evidence_rerun33/evidence_031_加的夫城_雷克斯.md`、`evidence_022_西班牙人_莱万特.md`、`evidence_032_拉科_埃尔切.md`。

## 必须采集的三类事实

1. 预测十一人（按位置计票，不是整份名单一刀切）
2. 缺阵/停赛
3. 对其他对手的最近最多 5 场正式赛

## 采集与验证规则

- 来源清单由 `crawl_sources_YYYY-MM-DD.json` 显式声明；不再用 20 槽投票替代事实。
- 本地 HTTP/Playwright 优先；失败或需要当前 Codex 浏览器时生成 `browser_tasks.json`。
- 浏览器快照由 `evidence_orchestrator.merge_browser_snapshots` 再次验证后才可合并。
- 403 / 验证码 / 人机验证：记缺口，不绕过。
- 揭幕战没有可核验的上季或最近正式赛时，明确标记 FORM_UNAVAILABLE。
- 热身赛不当正式近5场；不齐的比分不编造。
- 对不齐的比分不编造。写已对齐的场次即可，最多 5 场。
- `collected_at` 必须早于开球。已经开球的场次不得用新的赛前票；开球后确认阵容不得回写成预测票。

## 落盘步骤

1. `mcp_evidence.py` 完成一次结构化 API/MCP 采集。
2. `evidence_orchestrator.py` 调用本地抓取并输出 `browser_tasks.json`。
3. Codex 浏览器把任务结果保存为带 `url/final_url/crawled_at/markdown` 的 JSON 快照。
4. 重新运行编排器，验证通过的事实才写入主证据；预测程序读取同一目录。

## 评测入口

预测登记后使用 `evaluate_llm_track.py` 评估 K3 研究轨：

```bash
python evaluate_llm_track.py \
  --predictions data/llm_records.json \
  --results data/results.json \
  --output data/llm_track_evaluation.json
```

评测只接受 `score_90_status=verified` 的90分钟赛果，按 `sporttery-<体彩id>` 去重；重复、缺失或未核验记录只写入排除审计，不进入指标分母。

## 禁止

- 不得用投票、占位文本或模型常识补齐缺失事实。
- 不得把候选 URL、抓取失败或 UNAVAILABLE 当成事实。
- 不得只用一家预测站交差。
- 不得把 Playwright 当验证码绕过工具。

## EV / 凯利（2026-08-18 固化）

票比不是概率，不得算 EV。有量化轨校准 \(p\) 时走 `ev_calculator.generate_betting_recommendation`；`market_derived` 必须附带 `same_book_audit`。三个同一盘口 EV 必须全负，否则 `KELLY_SANITY_FAIL`，`action` 仍为 `skip`。禁止输出仓位。国际盘凯利指数不在本工程算，在融合技能 `hybrid-shadow` → `research.intl_kelly`。细则：融合技能 `references/kelly_research.md`。
