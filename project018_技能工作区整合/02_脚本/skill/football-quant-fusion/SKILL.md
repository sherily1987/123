---
name: football-quant-fusion
description: 全赛事足球量化研究与竞彩决策支持融合技能。融合足彩批量流水线、战意/赔率走势/状态研究与欧冠严格数据治理、阵容伤停、双回合晋级能力；输出胜平负、比分、大小球、BTTS、体彩让球、亚洲盘、晋级概率、数据质量、敏感性、赔率异动和可回测登记。用户提到今日推荐、足彩分析、竞彩足球、足球预测、欧冠预测、双回合晋级、夺冠模拟、让球、大小球、比分、赔率截图、盘口波动、串关、回测、回测已经预测的比赛或跨模型分析时触发。不用于纯实时比分查询。
version: 1.4.0
---
# 足球量化融合引擎 1.4.0

一个统一入口，覆盖单场、批量竞彩、欧冠/杯赛双回合、截图赔率与赛后回测。旧 `soccer-lottery` 与 `ucl-predictor` 只作历史对照；生产预测、快照登记、组合和回测统一执行本技能。旧入口不得绕过本技能的推荐门控、版本登记和数据使用审计。组合必须通过 `scripts/fusion_combo.py` 校验后才能进入生产记录。赛事级夺冠 Monte Carlo 尚未落地，触发后只说明缺口，不伪称已模拟。

## 1.4.0 变更（三Skill横向审计补丁，2026-08-02）

对 `football-quant-fusion`、`soccer-lottery`、`zu-yu-dashi-3`（当前核心 3.4.4）做了代码级（非仅文档）测试审计，把验证有效的能力补进本技能，详见 `references/pitfalls.md` 第1节：

1. **修复两处核心引擎未捕获崩溃**：`odds` 缺新鲜度锚、或全部盘口过期时，`core.predict()` 会抛 `ZeroDivisionError`/`TypeError` 而不是返回结构化错误。`fusion_predict.py` 现在捕获并转为 `fusion_status=blocked` + 诊断信息（含各盘口新鲜度现场快照），不再让调用方看到裸 traceback。根因在核心引擎，未改核心文件，详见 pitfalls 1.1。
2. **补齐被静默丢弃的核心输出**：`zu-yu-dashi-3` 3.4.x 已拟合的 `confidence`（星级）、`final_1x2_display`（百分比）、`derived_market_status`（逐盘口拟合状态）此前算出来后被融合层丢弃，现通过新增顶层字段 `core_calibration` 透传，并显式区分"核心单项盘口校准"与"融合层组合/edge校准"两个不同粒度，避免混用（详见 pitfalls 1.3）。
3. **新增一体化流水线** `fusion_daily_pipeline.py` / `fusion_cli.py daily-pipeline`：移植 zu-yu-dashi-3 的 回填赛果→采集→登记→赔率移动库 编排模式，但改走 fusion 自己的销售日采集器（不漏跨午夜场次）和 `fusion_cli.py record`（写入完整融合payload，不是裸核心输出）。
4. **新增战意/赔率走势证据映射参考表** `references/motive_evidence_reference.md`：吸收 soccer-lottery 的具体量化经验（保级战/争四战区间、赔率走势阈值），但严格降级为 UNFITTED 参考起点，纳入既有 `adjustment_ledger` 流程，不采纳其固定加权和热度降权做法。
5. ~~微信文章图片抓取桥接~~ **已移除（2026-08-03，用户确认不需要）**：`wechat-images` / `wechat-parse` 子命令及委托脚本已删除，公众号截图场景改由用户直接发图或粘贴正文处理。
6. **新增本技能专属** `references/pitfalls.md`：记录融合层自身的坑，与底层引擎的 pitfalls.md 分层维护。
7. **新增双轨预测流程（2026-08-03 试点固化）**：见下节「双轨预测流程」——量化轨道（fusion_predict）与 LLM 轨道（搜索证据+结构化判断）默认并行执行，赛后统一回测对比。试点：project013_LLM对比轨道试点（巴西国际 vs 科林蒂安）。
8. **融合层分档/edge 校准批准（2026-08-03）**：推荐门控 `calibration_status` 由 UNFITTED 翻为 VALID。`confidence` 使用分档命中率表（全快照池 1439 场版本审计样本，60/20/20 时间切分；band ECE test：全池 0.0602→0.0438、closing 0.0804→0.0715），并启用 edge 门槛（低于门槛不给 confidence）。**模型 Brier 不优于市场（全池 0.627 vs 0.586）——本工件只校准 confidence 数值，不构成"优于市场"声明**；门控仍要求 edge_significant 且 UNFITTED 旗标未清除前不出胆。回滚：恢复 `config/recommendation_policy.json.bak_2026-08-03`。
9. **通用联赛历史下载器 + 双轨回测脚本 + 自动回测（2026-08-04 收编）**：新增 `scripts/download_league_history.py`（把韩职/挪超/芬超/瑞超/巴西杯反复出现的同模板下载脚本收编为单入口，`--league-id/--league-name/--slug/--project`，断点续传+限速，输出到目标项目 `04_素材/`）；新增 `scripts/backtest_dual_track.py`（量化轨道 1X2/比分 vs LLM 轨道双选/单选/比分 合并回测，读 `待回测记录/<date>/index.json` + `index_llm.json` + 官方赛果，输出 JSON+MD）；新增 `scripts/auto_backtest.py`（一键回测所有已预测比赛：settle 回填 → 共享库量化回测 → 扫描各项目 `待回测记录/<date>/` 逐日双轨回测 → 合并报告）。

## 硬规则

1. **数字只由脚本产生**：不得手算或凭文字印象编造概率、xG、比分概率、晋级概率、组合概率。
2. 主概率引擎调用 `scripts/fusion_predict.py`；它复用已验证的多市场 Dixon–Coles/Poisson 引擎，并增加融合决策审计。
3. 区分四个概念，不得混称"信心"：
   - `forecast_probability`：结果概率；
   - `data_quality`：输入完整度/来源/新鲜度；
   - `model_uncertainty`：敏感性与可靠性缺陷；
   - `decision_value`：相对市场是否存在超过不确定性的差异。
4. **不使用固定"战意40%+赔率35%+历史25%"制造胜率**。战意、伤停、轮换只可在有来源证据时写成结构化、有界修正；否则仅作叙事因素。
5. 不得声称"热门队天然降权""赔率<1.5天然爆冷""已验证87%+"或用单轮命中率证明模型有效。低赔率代表高隐含概率，不代表必爆冷；评价以长期 Brier、Log Loss、ECE、CLV 与市场基线为准。
6. H2H 仅作低权重背景，须考虑年代、教练、阵容、主客和赛事差异；不得直接用历史胜负频率当下一场概率。
7. `quality.overall_pct` 只能叫"输入数据质量"，不得叫预测置信度。
8. 必须原样展示引擎的 `reliability_flags` 与 `sensitivity`，不得删弱风险。
9. 用户声明"以截图为准/不要联网赔率"时，赔率数据源锁定为截图；读不清就请用户补图或手输，禁止联网替数。若用户要求 API 对照，截图与 API 分栏，默认仍以截图为主。
10. 严格模式关键字段不足可停止预测；实战模式允许 `market_only`，但必须说明它主要复述市场，不能声称有独立 edge。
11. 双回合按当前规则不使用客场进球；90分钟、加时、点球和总晋级分开报告。
12. 融合 1.3 的新组合路径尚未完成独立大样本回测；必须标为 `UNFITTED_FUSION`，不得声称比市场或旧 Skill 更准。
13. 生产推荐硬门槛：`UNFITTED`、无显著 edge、未通过批准的时间序列校准或盘口陈旧时，不得列为胆，不生成手工 confidence；只输出概率、风险和观察/回避。
14. HHAD必须同时展示让胜/让平/让负三态；整数 -1 盘的让平就是主队一球胜，若让平风险达到策略阈值，禁止单推让负。
15. 组合腿必须通过登记ID强校验；缺失或重复腿ID的组合标记 `invalid_combo_reference`，不得计入组合命中率。
16. 生产阈值在已结算样本达到100场前不重校准，达到200场后才进行阈值复审。
17. 最终固定附注：**概率模型输出，非投注建议。**

## 意图路由

按用户最后一条明确指令选择，勿无差别跑全部流程：

| 模式 | 触发 | 执行 |
|---|---|---|
| `screenshot_only` | 赔率截图、以图为准、变盘 | OCR→转写→截图内波动；不拉 API 赔率 |
| `single` | 单场预测、欧冠对阵 | 身份核验→数据采集→建模→审计→报告 |
| `batch_lottery` | 今日推荐、足彩分析、怎么买 | 体彩全盘口→批量建模→风险排序→可选组合登记 |
| `two_leg` | 晋级、次回合 | 单场模型 + 首回合总比分 + 加时/点球路径 |
| `tournament` | 夺冠/各轮概率 | 验证赛制/参赛队/路径→固定 seed 模拟→概率表 |
| `backtest` | 回测、赛后验证 | 官方赛果回填→按版本/快照去重→校准指标 |
| `backtest_all` | **回测已经预测的比赛**、全部待回测 | 运行 `scripts/auto_backtest.py`：settle 回填→共享库量化回测→各项目待回测目录双轨回测→合并报告 |
| `report` | PPT、深度报告 | 只读取已生成 JSON，不二次改数字 |

## 双轨预测流程（LLM 对比轨道，2026-08-03 试点固化）

每场预测（`single` / `batch_lottery`）默认执行双轨，赛后统一回测对比：

### 轨道一：量化轨道（现有，必须执行）

`fusion_predict.py` 建模（market_only / hybrid / model_first）→ `fusion_record` 登记
（snapshot=prematch，版本+数据使用审计），输出概率与比分 Top3。

### 轨道二：LLM 轨道（搜索证据 + LLM 直接判断）

- 目标：用可引用证据给出**定性方向判断**，作为与量化模型的独立对照，不混入量化概率。
- 输出格式（赛前预登记 JSON，schema `llm-track-1.0`）：
  - `direction`：单选或双选（H/D/A），可带 `single_preference`；
  - `score_picks`：比分 Top1-3 偏好；
  - `signals`：风险信号（伤停/轮换/战意/赛制/天气等）；
  - `evidence[]`：每条事实含 `{fact, source(URL), collected_at, mapped, basis}`。
- 关键词库：按证据类型搜索（伤停/阵容、战意/动机、近况、主客/旅行/天气、赔率异动、
  身份核验），中英双语、官方来源优先、每类至少两个来源交叉验证；模板见
  `F:\HM足球比赛预测\90_归档\project013_LLM对比轨道试点\01_规划\关键词库.md`（项目已归档，模板文件仍在原相对结构内）。

### 纪律（硬性）

1. **数字只由脚本产生**：LLM 轨道只输出定性方向/比分偏好，禁止生成伪概率、伪 xG；
2. **赛前预登记**：LLM 判断必须在开球前写入 `llm-track-1.0` 记录，禁止赛后补录；
3. **证据必须可引用**：无来源 URL 与采集时间的事实不得进入记录；映射字段
   （`attack_absence_*` / `defense_absence_*` / `gk_absence_*` / `rotation_*` /
   `attack_motive_*`）遵循 `references/motive_evidence_reference.md`；
4. **归档并排**：量化记录与 LLM 记录同场同文件夹（待回测记录），附 index；
5. **对比口径**：赛后 `settle` 回填 → 对比量化 argmax vs LLM 单选/双选命中、
   比分 Top1/Top3 命中；累计 ≥100–200 场再评价优劣，单场不结论；
6. LLM 轨道不参与 `recommendation_gate`，不影响出胆判断。

### 执行步骤（每场）

1. 量化：采集盘口 → `fusion_predict` → `fusion_record`（snapshot=prematch）；
2. LLM：按关键词库搜索（agent-reach / Exa / 网页读取）→ 整理证据表 → LLM 结构化判断；
3. 双轨记录入同一待回测文件夹 + index；
4. 赛后：`fusion_cli.py settle` → 回测对比（可复用 project012 `backtest_pending.py` 模式）。

## 统一数据流程

### 1. 身份与比赛上下文

先核验：主客队、赛事、阶段、开球时间及时区、90分钟口径、首回合比分、竞彩编号/官方 matchId。中文简称有歧义时优先官方 teamId 或英文全名。

### 2. 数据源优先级

- 赛事/赛果：赛事官网、官方联赛、体彩官方列表。
- 补充足球数据：`football-data.org`，只读取环境变量 `FOOTBALL_DATA_API_KEY`；用于其覆盖赛事的赛程、积分、近期结果和交锋交叉核验。该源无赛事覆盖时必须标 `UNAVAILABLE`，不得用其他联赛数据替代。
- 补充足球数据：`API-Football v3`（`scripts/api_football_adapter.py`，Key 只从环境变量 `API_FOOTBALL_KEY` 读取）：赛程/赛果、积分榜、伤停、H2H。**Free 套餐限制**：仅开放 2022–2024 赛季（2025/2026 当前赛季会报错）、每日 100 次请求；`/odds` 赔率接口未适配且免费套餐覆盖不稳定——赔率仍以体彩官方采集为准。该源仅用于历史样本补齐与前瞻证据，不参与生产赔率。
- 补充足球数据：`apifootball.com`（`scripts/apifootball_com_adapter.py`，Key 只从环境变量 `APIFOOTBALL_COM_KEY` 读取）：这是独立供应商，使用 `apiv3.apifootball.com` 与查询参数 `APIkey`，不能与上面的 API-Sports v3 适配器混用。首期支持账户可用国家/联赛清单、赛程赛果、积分榜、球队、首发和统计原始结果；先落盘 provider 信封并标准化预览，字段核验后才允许接入特征。`get_odds` 可在显式 `apifootball_primary` 路径中作为 `provider_only` 市场输入，但不能伪装成体彩赔率或生成体彩玩法标签。
- `apifootball.com` 文档口径补充：`get_events` 支持 `timezone/from/to/country_id/league_id/match_id/team_id/match_live/withPlayerStats`；`get_standings` 使用 `overall_league_*` 字段；`get_lineups`/`get_statistics` 按 match id 包裹对象；`get_predictions` 始终为 `PROVIDER_BENCHMARK`，不能直接当作独立模型 edge。详见 `project007_APIFootball数据接入/05_交付/接入说明.md`。
- `apifootball.com` 联赛训练：用 `scripts/download_apifootball_com_history.py` 下载按联赛的历史赛果，随后运行 `scripts/league_training_audit.py` 自动分为 `independent` / `calibration` / `pooled`；仅被 scope 精确标为国内联赛且满足样本、赛季、测试集和球队 ID 覆盖门槛者可独立训练。赛后 statistics、lineup、player_statistics 被标记 `POST_MATCH`，不得进入赛前输入。`scripts/provider_market_input.py` 仅支持显式 `apifootball_primary`，输出 `provider_only`，不生成体彩玩法标签。
- 五大联赛候选训练：从 `project021_五大联赛APIFootball训练/02_脚本/run_five_league_pipeline.py` 运行 2021/22–2025/26 的英超、西甲、意甲、德甲、法甲下载、审计与时间切分训练。赛果按联赛月度续跑，`get_odds` 按全部比赛日全局缓存一次并按 `match_id` 联接；仅采纳开球前的 1X2 供应商赔率，经去水与跨 bookmaker 中位数汇总为 `provider_market`。`odd_date` 暂按 Europe/Berlin 解释且必须标记时间假设。独立模型只写为 `candidate`，`provider_market` 不得伪装为体彩赔率、生成体彩玩法或接入生产推荐。
- 体彩赔率：移动端官方 HAD/HHAD/CRS/TTG/HAFU；保留更新时间和原始 URL。**赔率一律以体彩官方为准。**
- 国际盘赔率（The Odds API，可选）：**仅作移动赔率/CLV 参考**；不参与概率建模、不替换体彩盘口、不进推荐门控。默认不启用（未设置 `ODDS_API_KEY` 自动跳过）。
- 阵容/伤停：俱乐部/赛事官方优先，至少一个可信备源交叉验证。
- 状态/积分/xG：官方统计、FBref、StatsBomb、ClubElo、可信统计站；记录 provider_model。
- 新闻/发布会：只用于战意、轮换和场外信息，不可冒充数值事实。
- 图片：标 `IMAGE_EXTRACTED`；模糊值标 `UNVERIFIED`。

访问失败要区分：`MISSING`、`UNAVAILABLE`、`UNVERIFIED`、`OUTDATED`、`INVALID`。单源失败后尝试两个合理备源；不得虚构。

### 3. 数据模式

- `market_only`：只有市场赔率；1X2=去水市场概率，比分衍生盘依赖市场反解。
- `hybrid`：赔率 + 独立强度/人员事实；市场作为锚，独立信息以软约束或结构化修正进入。
- `model_first`：成对真实 λ/xG 或可靠独立模型优先，市场只校准/对照。

输入字段和状态见 `references/data_contract.md`。

### 4. 概率建模

写入 JSON 后运行：

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_predict.py input.json
```

有体彩全盘口时：HAD + HHAD + TTG + HAFU 联合拟合 λ；CRS 只做相对比分排序对照，不直接归一化。输出至少包括：
- 市场公平概率、模型概率、最终1X2；
- 进球率口径（`goal_rate.kind=proxy_lambda|model_goal_rate`，`real_event_xg` 无数据则为 null）；
- Top比分、半场Top；
- O/U 2.5/3.5、BTTS；
- 体彩HHAD、亚洲盘五态；
- 双回合晋级路径（如适用）；
- 数据质量、市场依赖、敏感性、可靠性缺陷；
- `fusion_decision`：方向排序与 edge 是否超过不确定性。

### 5. 人员、战意与环境

事实先于评分。仅当证据明确时映射：
- 进攻缺阵→`attack_absence_*`；后防/门将→`defense_absence_*` / `gk_absence_*`；
- 轮换→`rotation_*`；
- 必须抢攻→`attack_motive_*`，同时用 `defense_risk_*` 表示压上风险；
- 海拔、旅行、天气等→单独字段并写原因。

所有系数必须列入 `adjustment_ledger`，包含事实、来源、采集时间、映射值、依据和是否已回测。未回测系数标 `UNFITTED`，不得假装精确。

### 6. 输出与推荐

先给总表，再逐场展开。推荐层遵循：
- `market_only` 只能做概率排序/玩法结构，不给"价值优势"；
- edge 小于敏感性宽度时，结论为"无显著决策价值"；
- `UNFITTED_FUSION` 且市场依赖度高或没有显著 edge 时，只输出市场基线，不生成独立单选推荐；
- 1X2、比分、大小球、BTTS、让球分别计算不确定性，不能把1X2等级继承给衍生市场；
- **让球推荐**（`recommendation_policy.evaluate()` 返回的 `hhad_recommendation` 字段，2026-08-13 加入）：基于体彩让球胜平负（HHAD）三项概率的独立出胆判断，跟1X2用同一 `banker_prob_threshold`（默认50%）阈值但分别判定——1X2不出胆不代表让球轨也不出胆，反之亦然。**这是体彩HHAD固定让球线三项盘，不是真正的亚洲盘**（win/push/half结算），字段里已标注 `market_type: sporttery_hhad_3way`，不得混用两者的结算规则。`calibration_status` 未独立验证，读结果时仍要看整体 `calibration_status` 字段；
- 数据冲突、阵容未定、盘口陈旧或依赖过高时降级；
- 可输出"单选/双选/回避"，但理由必须来自脚本与证据；
- 串关须提示腿间相关性，不把各场"信心"机械相乘；默认优先少腿、低相关，不追求最高组合赔率。

标准格式见 `references/output_contract.md`。

## 体彩自动管道

采集今日或指定场次：

```sh
# 默认入口：完整竞彩销售日（自动合并跨午夜周六001…周六016）；输出必须明确"销售日口径"，不得简称为自然日全部比赛
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py collect --sales-day YYYY-MM-DD --output raw.json --emit-input input.json
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py sales-day-collect --sales-day YYYY-MM-DD --output raw.json --emit-input input.json
# 兼容别名：等价于 collect（同 sales_day_collect.py）；参数同为 --sales-day / --output
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py collect-date --sales-day YYYY-MM-DD --output raw_date.json --emit-input input_date.json
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_predict.py input.json > output.json
```

需要官方前瞻、伤停与近况时：

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py preview --from-collect raw.json --output preview.json
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py merge-preview --input input.json --preview preview.json --output hybrid.json
```

补充调用 football-data.org（Key 只从环境变量读取，不写入输出）：

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/football_data_adapter.py --competition CODE --output football_data.json
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/football_data_adapter.py --team "Team name" --output team_search.json
# 将唯一匹配的足球数据来源元信息安全合并到模型输入，不覆盖体彩赔率
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py football-data-enrich --input input.json --home-query "Home FC" --away-query "Away FC" --output enriched.json  # ⚠️ 暂不可用：脚本事故损坏待恢复
# 多市场消融实验；当前配置标记UNFITTED，只用于比较，不代表已校准最优
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py market-ablation --input input.json --output ablation.json  # ⚠️ 暂不可用：脚本事故损坏待恢复
```

历史赛果批量下载（API-Football 免费版，2022–2024 赛季；复用 `api_football_adapter.py`）：

```sh
# 目标项目必须已存在（按全局工作台 SOP 建 projectXXX_项目名称）；输出写入其 04_素材/
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/download_league_history.py \
  --league-id 103 --league-name Eliteserien --slug eliteserien \
  --project "F:\HM足球比赛预测\projectXXX_项目名称"
# 已拉过时快速重合并（不请求）：加 --delay 0
```

API-Football 联赛 id 可查 `/leagues?season=2024`；免费版限 100 次/天、10 次/分钟，脚本默认 7 秒/请求并断点续传。

正式预测在开赛前登记，更新用新 snapshot，不覆盖旧记录：

> ⚠️ **输入格式要求**：`record` 只接受**单场裸 dict**（home/away/odds/field_meta/...）。`collect --emit-input` 产出的是 `{matches:[...]}` 批量文件，**不能直接喂给 record**；批量场景请用 `daily-pipeline`（内部自动拆分），或自行拆成单场后逐个 record。

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py record --input input.json --output model_output.json --snapshot prematch
# 若同时有原始采集 raw.json，可附带赔率移动入库
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py record --input input.json --output model_output.json --snapshot prematch --odds-source raw.json
```

一体化每日流水线（回填赛果→采集销售日→登记快照→赔率移动库）：

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py daily-pipeline --sales-day YYYY-MM-DD
# 或直接
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_daily_pipeline.py --sales-day YYYY-MM-DD [--dry-run]
```

单场登记仍可用上面的 `record` 分步命令；批量场景优先用 `daily-pipeline`，避免手动串4-5步遗漏赔率移动库或去重。

1.3.0 最小生效补丁：
- 自动加载 `config/market_weights.json`（UNFITTED，可复现）
- 赔率去水支持 `proportional`（默认）、`additive`、`power`、`shin`；后三者必须显式指定并回测，不自动替换默认
- `apply_time_decay.py` 提供近期攻防指数衰减候选，默认不激活；`fusion_backtest.py` 增加 CLV 收盘线评价
- `rotation_*` 进入核心事实修正
- CRS 仅做 Top重合度审计（`crs_overlap_audit`）
- `collect/record` 可自动/附带 `odds-add` 写入融合赔率移动库

## 回测与赔率移动

样本分母审计：
```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/sample_audit.py --snapshot SNAPSHOT --output sample_audit.json
```
组合腿校验：
```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_combo.py --legs combos.json --output combo_validation.json
```

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py settle --date YYYY-MM-DD --dry-run
# 体彩官方结果缺失时，显式启用 APIFootball 欧冠 fallback；默认关闭
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py settle --date YYYY-MM-DD --apifootball-fallback --dry-run
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py backtest --snapshot closing
# 该命令评估 football-quant-fusion 实际输出，不是仅评估底层 3.4.4 核心引擎
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py odds-add --source raw.json
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py odds-drift --date YYYY-MM-DD
```

### 国际盘对照（可选，The Odds API）

体彩官方盘口是主赔率源；国际盘对照仅用于 CLV / edge 独立研究，**不参与概率建模、不替换体彩盘口、不影响推荐门控**。默认不启用：未设置 `ODDS_API_KEY` 时自动跳过。

```sh
# 手动抓取一次（--match-file 传体彩 raw/input JSON，做联赛+开球时间+队名 best-effort 匹配）
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py odds-intl --match-file raw.json --out intl_snapshot.json
python3 .../fusion_cli.py odds-intl --match-file raw.json --dry-run      # 只看计划，不发请求
python3 .../fusion_cli.py odds-intl --check-sports                       # 校验配置里的 sport key
```

- 环境变量：`ODDS_API_KEY`（https://the-odds-api.com/ ，免费 500 次/月）
- 配置：`config/intl_odds_sources.json`（联赛→sport key 映射、队名别名、默认市场）
- 落盘：`odds/intl_production.jsonl`（追加，每次运行一行）+ 快照 JSON；`daily-pipeline` 设置了 key 时自动附带该步骤，失败只记录、不阻断主链路
- 配额纪律：默认每联赛 1 个请求（h2h）；追加市场（如 `--markets h2h,totals`）会额外计次；`--check-sports` 会额外消耗 1 次
- 未匹配场次（联赛无映射 / 无国际盘事件 / 队名对不上）如实列在 `unmatched`，不得伪造匹配

双轨（量化+LLM）合并回测：

```sh
# 在项目根目录运行（默认读 04_素材/待回测记录/<date>/，官方赛果由 settle 回填）
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/backtest_dual_track.py --date 20260803
# 或显式指定记录目录与输出
python3 .../backtest_dual_track.py --records-dir <待回测记录目录> --output out.json --report out.md
```

输出口径：量化 1X2 argmax、LLM 双选、LLM 单选偏好、比分 Top1/Top3 分轨道命中率；
按 SKILL 纪律，样本 <100 场不评价优劣、<200 场不做结论，只列命中统计与分歧清单。

一键回测所有已预测比赛（手动关键词「回测已经预测的比赛」/ 自动计划任务 `FootballQuantAutoBacktest`）：

```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/auto_backtest.py \
  --workspace "F:\HM足球比赛预测" --output-dir <项目>/05_交付/auto_backtest
# 允许回填并显式启用 APIFootball 欧冠 fallback
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/auto_backtest.py \
  --settle --apifootball-fallback --workspace "F:\HM足球比赛预测" --output-dir <项目>/05_交付/auto_backtest
```

流程：① settle 回填共享库官方赛果（幂等）→ ② fusion_backtest 统计共享库量化记录 →
③ 扫描各项目 `04_素材/待回测记录/<date>/` 逐日双轨回测 → ④ 输出合并报告
（`auto_backtest_report_<日期>.md/json`，每日期明细写入所属项目 `05_交付/`）。

同 `(match_id, snapshot_type)` 只算一个样本。至少分版本、联赛、市场、快照报告；样本 <200 不宣称优于市场。命中率只作辅指标，主指标为 Brier、Log Loss、ECE；有固定赛前策略与赔率才评 ROI。

APIFootball fallback 仅补全普通完赛欧冠赛果。供应商存在加时/点球字段但无法确认90分钟比分时标记 `needs_review`，不得进入正式回测分母；体彩官方结果与供应商结果冲突时标记 `source_conflict`，不得静默覆盖。

## 赛事模拟

全赛事模拟前必须确认当前赛制、赛程、抽签约束、主客顺序和已赛结果。运行次数默认 100,000，固定并报告 seed。不得用已取消的客场进球规则。动态抽签或新版欧冠联赛阶段须显式输入规则；脚本不支持的赛制不得用"平均随机抽签"冒充官方规则。**1.4.0 已收编赛事级 Monte Carlo（`scripts/ucl_tournament_mc.py`，经 `fusion_cli.py tournament` 路由）**：默认内置 2025/26 官方 36 队名单与 2025-08-28 官方分档，生产运行必须带真实实力参数（`--teams teams.json --strength strength.json`）并 `--iterations 100000`；使用示例：
```sh
python3 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/football-quant-fusion/scripts/fusion_cli.py tournament --selftest
python3 .../fusion_cli.py tournament --iterations 100000 --seed YYYYMMDD --teams teams.json --strength strength.json --output out.json
```
赛制单元自检（抽签约束/附加赛配对/16强映射/继承制/加时点球/并列规则）必须 PASS 才允许正式输出；若请求的赛制/参赛队不是脚本内置 36 队名单，须先按规则确认清单核实并显式传入 `--teams`。实力参数状态（2026-08-05）：**生产默认 strength schema 1.2**（2024/25 联赛快照 + UEFA 官方 5 年国家系数标定）；**v2.1 备选**（融合引擎 Dixon-Coles 实时 λ 五大联赛 22 队 + v1.2 混合 + 幂压缩 p=0.7）——个体强队修正到位（PSG 第 5）、四强命中与 v1.2 持平（2/4），但前八命中 4/8 未达 ≥6/8 验收线；v2.0 无压缩版为实验版。所有版本均存在时点滞后与覆盖局限，不构成"优于市场"或"命中冠军"声明；演进与验收见 project005/01_规划/2026-08-04_MonteCarlo生产化路线图.md。

## 失败处理

| 情况 | 处理 |
|---|---|
| 赛事身份/开球时间不明 | 停止并列出待确认项 |
| 概率脚本失败 | 报错；禁止手工补概率 |
| 赔率只有截图且读不清 | 请求高清局部或手输 |
| 只有市场数据 | 输出 market_only，并声明无独立 edge |
| 阵容/伤停访问受阻 | 标 UNAVAILABLE，不等于无人缺阵 |
| 模型与多盘口冲突 | 保留输出、展示冲突、降级比分/衍生盘 |
| 赛果未完 | `not_finished`，不臆测 |

## 资源按需读取

- `references/fusion_design.md`：两 Skill 的保留、重写、淘汰决策与融合原理。
- `references/data_contract.md`：统一输入与证据账本。
- `references/output_contract.md`：统一报告模板。
- `references/motive_evidence_reference.md`：战意/赔率走势事实→证据账本映射参考（UNFITTED，来自soccer-lottery经验降级）。
- `references/pitfalls.md`：融合层自身的踩坑记录（核心引擎崩溃兜底、字段透传缺口、流水线格式假设等）。
- 详细底层建模/回测坑位按需读取 `C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills/zu-yu-dashi-3/references/`；融合 Skill 的脚本对其版本做兼容检查，不静默吞错。



