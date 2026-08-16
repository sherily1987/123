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
| LLM赛前证据采集 | `llm-evidence` |
| 结算与回测 | `settle` / `backtest` |
| 当前版本还差多少样本 | `version-progress` |
| 统一工单读写 | `job` |
| 影子 hybrid（不登记） | `hybrid-shadow` |
| 盘后伤停 / T-75 首发（只写研究库） | `late-info` |
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

伤停、首发、天气等不可得时写 `UNAVAILABLE`，不能解释为“没有风险”。所有人员、战意和环境数值调整必须进入 `adjustment_ledger`，包含事实、来源、采集时间、映射依据和验证状态。

## 研究路由与双轨纪律

生产默认路由保留 `market_only`。候选球队强度只能附在 `research_candidate` 中，不得悄悄改变生产概率。显式实验时才允许：

```powershell
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_predict.py match.json --research-route --output research.json
```

`--research-route` 的输出必须带 `research_only=true`，不能写入正式预测登记库或 current cohort。`--production-route` 仅运行生产安全路由和 shadow 候选，不表示候选模型已获准融合。

LLM轨只负责证据整理和定性分析。DeepSeek先分析、Kimi K3与GLM复核投票时，仍必须分别展示来源、弃权理由、`action` 和 `reason`；不得把共识票数当概率。真实生产 LLM 工程位于本仓库 `project018_技能工作区整合/02_脚本/llm/football-llm-predictor/`（2026-08-16 迁入），可用环境变量 `FOOTBALL_LLM_ROOT` 覆盖：

```powershell
python $cli llm-evidence --input match.json --out-dir evidence --watch-refresh --refresh-before-minutes 75
```

证据链应采集两队最近5场、CRS/TTG/HAFU，并在开球前约75分钟重新拉取首发和伤停。若外部脚本不存在，明确失败；不得静默改用仓库内旧副本。

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

## 版本、样本与结论纪律

current cohort 以 `model_version + probability_signature` 识别。概率算法或概率配置改变时必须升级 `model_version` 并重建发布锁；推荐政策和证据管线分别使用 `decision_policy_signature`、`evidence_pipeline_signature`，避免非概率变化重置模型样本。

100场、200场等数量只能作为复审触发点，不是统计证明。任何效果结论都要同时报告赛事范围、时间切分、版本、样本量、基线、指标点估计和不确定性；样本外结果不优于基线时不得推广。

```powershell
python $cli late-info --from-collect raw.json
python $cli late-info --from-collect raw.json --watch
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

输出只包含实际可算且契约允许的市场。至少保留：1X2、数据质量、市场依赖、敏感性、可靠性缺陷、门控结论、版本身份；Top比分、总进球、BTTS、HHAD、亚洲盘等按各自状态输出，不得补齐不存在的值。

身份歧义、概率脚本失败、非法概率、时间穿越、版本签名不匹配或登记冲突均阻断。来源失败记录原因；国际赔率失败不阻断体彩主链路。截图读不清时要求高清局部或手工录入到 `manual_check`，不联网替换截图值。

按需读取：

- `references/data_contract.md`：输入、状态和证据账本；
- `references/output_contract.md`：报告字段与门控；
- `references/motive_evidence_reference.md`：赛前事实映射；
- `references/pitfalls.md`：工程与方法论踩坑；
- `references/version_and_data_migration.md`：唯一事实源、版本与回滚。

最终固定附注：**概率模型输出，仅用于研究与决策支持，不保证准确性或收益；如涉及付费投注，请自行核验信息并承担风险。**
