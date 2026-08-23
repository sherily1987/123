---
name: football-quant-fusion
description: Use when the user needs auditable pre-match football probability research, Sporttery market analysis, odds movement review, two-leg qualification analysis, prediction registration, settlement, or backtesting; not for live-score-only lookup.
---

# 足球量化融合引擎

本技能连接比赛身份、体彩市场、独立强度证据、版本化概率、赛前登记和90分钟结算。它是研究与决策支持工具，不保证覆盖所有赛事、所有盘口或任何收益。

默认入口：

```powershell
$cli = 'C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_cli.py'
python $cli --help
```

生产数据唯一事实源：`F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\`。

## 先判定请求

意图标签不是 CLI 子命令。`single`、`batch`、`two_leg`、`report` 等词只用于理解用户目标，执行时必须映射到下方真实命令或脚本，不得虚构入口。

| 请求 | 执行入口 |
|---|---|
| 单场正式预测并登记 | `record` |
| 销售日采集或批处理 | `collect` / `daily-pipeline` |
| 赔率移动对照 | `odds-add` / `odds-drift` / `odds-intl` |
| 凯利研究（卫生 / 国际盘 \(G\)） | 见下节；不是独立 CLI。卫生在 EV 层，\(G\) 随 `hybrid-shadow` |
| LLM赛前证据采集 | `llm-evidence` |
| 结算与回测 | `settle` / `backtest` |
| 当前版本还差多少样本 | `version-progress` |
| 统一工单读写 | `job` |
| 影子 hybrid（不登记） | `hybrid-shadow` |
| 赛前证据回补（只写研究库） | `llm-evidence` + `evidence_orchestrator.py` |
| 赛事模拟 | `tournament`，仅在赛制和输入已核验时 |
| 双回合晋级 | 先分别计算每场90分钟，再显式处理总比分、加时和点球；没有统一 CLI 时不得声称已自动完成 |

只运行完成当前请求所需的最小链路。

## 不可突破的边界

1. 正式生产概率、xG、比分和组合数字必须来自已发布脚本。人工核对可写入 `manual_check`，但不得覆盖生产字段。
2. 正式赛前记录不可赛后改写；更新必须生成新 snapshot，并保留 `prediction_as_of`。
3. 体彩官方盘口是竞彩生产赔率源。国际赔率只用于移动、CLV和研究对照，不进入生产概率或推荐门控。
4. 赛果必须区分90分钟、加时、点球和晋级；90分钟比分未验证时不得进入正式分母。
5. 数据冲突不得静默覆盖；密钥只能从环境变量读取，不能写入文件、日志或报告。
6. 投票比例、数据质量、模型概率和推荐置信度是四个不同量，禁止互相替代。
7. `action=skip` 的结果不得进入推荐表；LLM轨的票数不能用于EV计算。
8. 中文盘口「凯利指数」\(G=\)体彩赔率\(\times\)国际共识去水\(p\)，与 Kelly 仓位 \(f^*=\mathrm{EV}/(\mathrm{odds}-1)\) 禁止混称。\(G\) 只作研究特征；未获准前不得输出 \(f^*\)、注额或建议仓位。
9. `market_only` / `market_derived` 对**同一体彩盘口**算 EV 量到的是庄家水位。三个方向必须全 \(\le 0\)，否则标 `KELLY_SANITY_FAIL`，`action` 仍为 `skip`。卫生检查走 LLM 工程 `ev_calculator.same_book_ev_audit`。
10. 国际盘凯利指数只写工单 `research.intl_kelly`（`research_only=true`，`calibration=UNFITTED`），由 `hybrid-shadow` 在预测之后附加。不进生产概率、不进 `predict_one` 输入、不进推荐门控。缺国际盘快照时 `status=skipped`，不阻断 hybrid。

## 生产门控：默认拒绝推荐

当前推荐层尚未完成独立校准，`production_recommendations_enabled=false`。系统可以输出概率研究，但不得输出生产胆项。

- `MARKET_BASELINE`、`AVOID_DATA_RISK` 永不出胆。
- `UNFITTED_NO_VALUE` 不得形成独立单选。
- HHAD 未独立校准时只作 shadow；一球胜风险达到门槛时必须附加阻断原因。
- 没有显著独立 edge、市场依赖过高、盘口陈旧或校准概率缺失时一律 fail closed。
- `confidence_pct` 只允许来自已验证的校准概率；否则为 `null`，同时保留 `raw_primary_probability` 供审计。

恢复生产推荐必须经过版本化的样本外校准、基线比较、阈值评审和发布锁更新，不能仅改一个开关。

## 数据与市场状态

输入至少要能唯一确认主客队、赛事、开球时间/时区，并具有完整体彩1X2或成对独立强度锚。只有市场时固定为 `market_only`，只描述市场概率结构，不声称价值优势。

每个衍生市场必须单独给状态，不得因1X2可用而推断其他市场可用：

- `VALID`：输入、算法与校准契约均满足；
- `UNAVAILABLE`：当前数据源无法取得所需数据；
- `UNFITTED`：能计算研究值，但没有足够的独立校准；
- `NOT_OFFERED`：目标市场本身未开售或不适用。

伤停、天气等不可得时写 `UNAVAILABLE`，不能解释为“没有风险”。首发分为 `VALID`（官方确认）和 `PREDICTED`（来源明确、时间戳明确的预计首发）；预计首发可以进入赛前研究输入，但必须保留“未确认”风险标签，并在临场官方名单出现后刷新。所有人员、战意和环境数值调整必须进入 `adjustment_ledger`，包含事实、来源、采集时间、映射依据和验证状态。

## 研究路由与双轨纪律

生产默认路由保留 `market_only`。候选球队强度只能附在 `research_candidate` 中，不得悄悄改变生产概率。显式实验时才允许：

```powershell
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_predict.py match.json --research-route --output research.json
```

`--research-route` 的输出必须带 `research_only=true`，不能写入正式预测登记库或 current cohort。`--production-route` 仅运行生产安全路由和 shadow 候选，不表示候选模型已获准融合。

LLM轨只负责证据整理和定性分析。生产默认只调用 DeepSeek V4 Flash（`deepseek/deepseek-v4-flash`）；Kimi K3 仅保留为历史兼容或显式隔离实验模型，不能把票数当概率或共识。每条输出必须展示来源、缺口、`action` 和 `reason`。真实生产 LLM 工程位于本仓库 `project018_技能工作区整合/02_脚本/llm/football-llm-predictor/`（2026-08-16 迁入），可用环境变量 `FOOTBALL_LLM_ROOT` 覆盖：

```powershell
python $cli llm-evidence --input match.json --out-dir evidence
```

量化采集器已经保存的 `evidence_chain`、`evidence_snapshot_ref` 和
`browser_evidence_ref` 会先由 `evidence_merge.py` 合并，再自动投影到 LLM 的证据 Markdown；LLM 可以引用其中的事实、来源和
时间戳。该投影只扩大证据可见性，不改变 LLM 的票数语义，也不把 LLM 输出写成量化概率；
`PREDICTED` 首发必须继续标注为预计而非官方确认。

证据链在单次采集窗口内尽量采集两队最近5场、CRS/TTG/HAFU、伤停和首发；官方首发未发布时可采集预计首发并标记 `starting_xi.status=PREDICTED`，不得改写为官方确认。
本地 HTTP/Playwright 优先；失败项写入 `browser_tasks.json`，由当前 Codex 浏览器回补并落成可审计快照。
BB-browser 适配器不得假定固定联赛网址：`--url-map` 的每场映射至少包含该场 URL 和
来源所需的比赛 ID；可选 `official_domains`（比赛级官方域名提示）、`source_id`、`provider`
用于跨联赛来源发现和 provenance。自定义来源复用统一 `evidence_audit` 契约时，必须保留
真实来源身份，不能把其他联赛页面标成 `fotmob.bb_browser`。来源候选只是待审计入口，未取得
带时间戳的字段事实前不得提升为 `VALID`，也不得进入生产概率。
API/结构化端点失败或关键字段缺失后，采集器按映射顺序调用 Scrapling 动态页面回退；
映射既可由 `--url-map` 提供，也可随单场输入放在 `evidence_sources` 中。回退结果始终
带 `research_only=true`、`scrapling_attempts` 和字段级来源，不会覆盖已有有效 API 字段；
未提供经过审计的页面映射时只生成待处理任务，不会把搜索候选直接当作事实来源。
启用 `daily-pipeline --bb-browser-discover` 时，发现到的官方候选优先、已知第三方候选其次，
会自动进入 Scrapling 有序尝试；只有页面解析出带时间戳的字段事实才写入快照，失败仍保留
`browser_tasks.json` 待人工复核。这样 API 不可用时会实际执行回退，而不是只记录搜索链接。
所有事实必须通过身份、来源域名、采集时间早于开球和关键词门禁；采集不到就保留缺口，不用投票或常识填充。
仅剩体彩赔率时 DeepSeek V4 Flash 仍可输出研究意见，但强制 `evidence_gap=true`、`confidence=null`、`action=observe`，
禁止 EV/Kelly/下注推荐。若外部脚本不存在，明确失败；不得静默改用仓库内旧副本。

## 凯利研究路径（2026-08-18 固化）

细则与禁令见 `references/kelly_research.md`。执行顺序不得跳级：

1. **路径 A（已落地）**：有校准确率时必须跑同一盘口卫生检查。`same_book_audit` 是研究字段；`market_derived` 出现正 EV 只加 `KELLY_SANITY_FAIL`，不得当成价值投注。
2. **路径 B（已落地）**：先 `odds-intl` 写入 `odds/intl_production.jsonl`，再 `hybrid-shadow`。共识 \(p\) 优先 Pinnacle h2h（忽略 lay），否则各家去水等权平均。读 \(G\) 的三向相对差（`gap_max_minus_mid` / `softest_direction`），禁止用「\(G>1\) 才买」。
3. **路径 C（未开放）**：纸面 1/4 Kelly 仅在影子 hybrid 样本外同时打败市场（Brier **和** logloss；场次达到复审触发点且结论成立）之后才允许讨论。当前 `research.hybrid` 有独立 1X2 的场次不得把仅含 quant 的工单算进分母。

`hybrid-shadow --score` 只评 `research.hybrid` 相对同场市场，不并入 current，不开 m4。

## 常用命令

```powershell
python $cli collect --sales-day YYYY-MM-DD --output raw.json --emit-input input.json
python $cli daily-pipeline --sales-day YYYY-MM-DD --dry-run
python $cli record --input match.json --output model_output.json --snapshot prematch
python $cli settle --date YYYY-MM-DD --dry-run
python $cli settle --date YYYY-MM-DD --apifootball-fallback --dry-run
python $cli backtest --snapshot closing
python $cli odds-intl --match-file raw.json --dry-run
```

`record` 只接受单场裸对象；批量 `{matches:[...]}` 使用 `daily-pipeline` 或拆分后逐场登记。APIFootball fallback 只有显式启用且 `score_90_status=verified` 才能进入结算分母。

## 已有预测的重新采集与重预测

同一场比赛需要更新盘口或赛前证据时，必须遵循
`references/reprediction_workflow.md`：保留旧登记，生成带新
`prediction_as_of` 的替代快照并出具新旧对比。预计首发可以用
`starting_xi.status=PREDICTED` 进入证据链，但不得冒充官方确认；官方名单发布后再生成
`VALID` 快照。生产仍跑 `market_only`，独立信息只进入研究/影子路由。报告必须同时列出
概率差异、盘口差异、证据缺口、`model_version` 和 `probability_signature`，不能只展示新预测。

## 版本、样本与结论纪律

current cohort 以 `model_version + probability_signature` 识别。概率算法或概率配置改变时必须升级 `model_version` 并重建发布锁；推荐政策和证据管线分别使用 `decision_policy_signature`、`evidence_pipeline_signature`，避免非概率变化重置模型样本。

100场、200场等数量只能作为复审触发点，不是统计证明。任何效果结论都要同时报告赛事范围、时间切分、版本、样本量、基线、指标点估计和不确定性；样本外结果不优于基线时不得推广。

```powershell
python $cli odds-intl --match-file raw.json
python $cli llm-evidence --input raw.json --out-dir evidence
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\evidence_orchestrator.py \
  --input raw.json --sources crawl_sources.json --snapshot-dir crawl_snapshots \
  --browser-task-file evidence/browser_tasks.json
python $cli hybrid-shadow --input raw.json --sales-day YYYY-MM-DD
python $cli hybrid-shadow --score --sales-day YYYY-MM-DD
python $cli job --input match.json --quant model_output.json --out job.json
python $cli job --match-id sporttery-2040898
python $cli version-progress
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\probability_replay_check.py --model-version m1
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\release_lock.py
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\audit_version_consistency.py
```

`probability_signature` 是概率文件的字节哈希，数值中性的重构同样会触发 bump 并清零样本。
`probability_replay_check.py` 用旧样本登记时保存的 input 重跑当前代码，逐场比对概率；
仅当判定 `equivalent` 时，才可把旧版本写入 manifest 的 `model_version_aliases` 并按
current 计入样本。别名要求 `model_version` 与 `probability_signature` 精确成对，
等价结论不得外推到未重放的路由或衍生市场。

`version-progress` 报告当前 `model_version` 的已结算与在途样本数，以及与复审触发点的距离；其中已结算数是回测 `n` 的上界（不含已结算但无法评分的记录），门禁分子仍以 `backtest` 为准。`signature_drift` 非空表示改了概率文件却未升级 `model_version`，这些样本不会计入 current cohort。

版本审计非零退出时不得发布新概率。历史迁移只建立索引与来源映射，不改写原预测。

## 输出与失败处理

输出只包含实际可算且契约允许的市场。至少保留：1X2、数据质量、市场依赖、敏感性、可靠性缺陷、门控结论、版本身份；Top比分、总进球、BTTS、HHAD、亚洲盘等按各自状态输出，不得补齐不存在的值。LLM 的 `single_pick` 即使保留研究方向，也必须同时标 `action=observe`、`bettable=false`；只有 EV/证据门禁明确 `action=bet` 时才可标为可下注。

身份歧义、概率脚本失败、非法概率、时间穿越、版本签名不匹配或登记冲突均阻断。来源失败记录原因；国际赔率失败不阻断体彩主链路。截图读不清时要求高清局部或手工录入到 `manual_check`，不联网替换截图值。

按需读取：

- `references/data_contract.md`：输入、状态和证据账本；
- `references/output_contract.md`：报告字段与门控；
- `references/kelly_research.md`：凯利指数 / 同一盘口卫生 / 路径 A–C；
- `references/motive_evidence_reference.md`：赛前事实映射；
- `references/pitfalls.md`：工程与方法论踩坑；
- `references/version_and_data_migration.md`：唯一事实源、版本与回滚。

最终固定附注：**概率模型输出，仅用于研究与决策支持，不保证准确性或收益；如涉及付费投注，请自行核验信息并承担风险。**
