---
name: football-quant-fusion
description: 全赛事足球量化研究与竞彩决策支持融合技能。用于赛前单场或批量预测、竞彩让球/大小球/比分、双回合晋级、赔率变化、串关校验和赛后回测；不用于只查询实时比分。
version: 1.4.0
---

# 足球量化融合引擎

本技能把比赛身份、体彩市场、独立强度信息、赛前证据、模型输出、版本登记和赛后结算连接成可审计流程。默认入口：

```powershell
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_cli.py --help
```

生产数据唯一事实源：`F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion\`。

## 意图路由

| 用户意图 | 模式 | 最小流程 |
|---|---|---|
| 单场预测、欧冠对阵 | `single` | 身份核验 → 采集 → 建模 → 登记 |
| 今日竞彩、批量分析 | `batch` | 销售日采集 → 批量建模 → 风险排序 |
| 赔率截图、以图为准 | `screenshot_only` | 转写 → 可读性审计 → 仅使用图中赔率 |
| 次回合、晋级 | `two_leg` | 90分钟 → 总比分 → 加时/点球路径 |
| 赛事模拟 | `tournament` | 核验赛制 → 固定seed模拟 → 自检 |
| 已预测比赛回测 | `backtest` | 赛果回填 → 版本分组 → 指标报告 |
| 报告/PPT | `report` | 读取已有JSON，不重算数字 |

只运行完成当前请求所需的最小链路。

## 不可突破的事实边界

1. 概率、xG、比分和组合数字必须由脚本产生，不得手算补齐。
2. 正式赛前记录不可赛后改写；更新必须生成新 snapshot。
3. **体彩官方盘口是竞彩生产赔率源。**其他供应商不得伪装成体彩盘口。
4. **国际赔率仅用于移动赔率、CLV和对照**，不替换体彩盘口，不直接进入生产推荐门控。
5. 赛果必须区分90分钟、加时、点球和晋级；无法验证90分钟比分时不得进入正式分母。
6. 历史记录保留原 `model_version` 和概率签名；结构迁移不等于模型升级。
7. 数据冲突不得静默覆盖；密钥只从环境变量读取。

## 分级门控

### 阻断

- 主客队、赛事、开球时间或时区不能唯一确认；
- `prediction_as_of` 不早于开球；
- 概率脚本失败或概率输出非法；
- 90分钟赛果无法确认；
- 同一 `prediction_id` 内容冲突；
- 当前版本与 `probability_signature` 不匹配。

### 降级

- 只有体彩市场：使用 `market_only`，可给市场隐含概率和条件方向，但不能声称独立 edge；
- 阵容、伤停或天气不可得：标 `UNAVAILABLE`，不能解释成没有风险；
- 模型和盘口冲突：同时保留，扩大不确定性；
- 衍生市场未独立校准：不继承1X2等级；
- 数据较旧：展示时间戳并降低结论强度。

### 警告

- 小样本、低覆盖、联赛迁移或时点滞后；
- 串关腿相关；
- 推荐阈值来自有限历史；
- 模型未优于市场或差异不稳定。

## 研究模式与生产模式

生产模式只使用发布锁覆盖的概率配置；正式预测必须登记版本、概率签名、赛前时间和数据审计。推荐必须展示 `action`、`reason` 和市场类型；`action=skip` 不能进入推荐表；原样保留 `reliability_flags` 与 `sensitivity`。

研究模式可以运行未校准调整、替代去水方法和候选模型，但必须标记 `research_only`，不得写入生产推荐、混入 current 回测或覆盖发布锁，并须输出基准和敏感性。

## 数据源边界

- 身份与竞彩赔率：体彩官方优先，保留官方 `match_id`、销售日、更新时间和URL。
- 赛果：体彩或赛事官方优先；APIFootball fallback 只有显式启用且 `score_90_status=verified` 才可纳入。
- API-Football 与 apifootball.com 是两个供应商，适配器和密钥不可混用。
- 官方单一伤停来源可以采用；重大非官方消息、模糊消息或来源冲突需要交叉核验。
- 新闻和战意只作有来源事实；映射成数值时必须进入 `adjustment_ledger`。
- The Odds API 是可选国际赔率观察源；失败或无Key不得阻断体彩主链路。

统一状态：`MISSING`、`UNAVAILABLE`、`UNVERIFIED`、`OUTDATED`、`INVALID`、`SOURCE_CONFLICT`。

## 建模和输出

- `market_only`：主要复述去水后的体彩市场；
- `hybrid`：体彩市场锚加可验证独立信息；
- `model_first`：可靠独立强度优先，市场用于校准和对照。

输出至少包含1X2、Top比分、总进球、BTTS、体彩HHAD三态、数据质量、市场依赖、敏感性、可靠性缺陷、门控结论、版本身份和记录ID。体彩HHAD是固定让球线三项盘，不是真正的亚洲盘，两者不得混用结算规则。

样本量不使用机械禁语。任何效果结论必须同时报告样本量、时间范围、版本、基线、点估计和不确定性；样本越小，措辞越弱。达到较大样本也不自动证明优于市场。

## 常用命令

```powershell
$cli = 'C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_cli.py'
python $cli collect --sales-day YYYY-MM-DD --output raw.json --emit-input input.json
python $cli daily-pipeline --sales-day YYYY-MM-DD --dry-run
python $cli record --input match.json --output model_output.json --snapshot prematch
python $cli settle --date YYYY-MM-DD --dry-run
python $cli settle --date YYYY-MM-DD --apifootball-fallback --dry-run
python $cli backtest --snapshot closing
python $cli odds-intl --match-file raw.json --dry-run
```

`record` 只接受单场裸 dict；批量 `{matches:[...]}` 使用 `daily-pipeline` 或拆分后逐场登记。

## 双轨纪律

- 量化轨输出脚本概率、版本登记和门控；
- LLM轨输出可引用证据与定性方向，不生成伪概率；
- 两轨分别登记、分别结算，不把投票比例当校准概率；
- LLM轨报告EV时必须同时展示 `action` 和 `reason`。

## 版本与迁移

current cohort 以 `model_version + probability_signature` 识别。改变概率数值的算法或配置必须先升级 `model_version` 并重建发布锁；框架、日志和文案变化不重置样本。

历史迁移只建立索引与来源映射，不改写原预测。详见 `references/version_and_data_migration.md`。

```powershell
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\release_lock.py
python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\audit_version_consistency.py
```

版本审计非零退出时不得发布新概率。

## 失败处理

| 情况 | 处理 |
|---|---|
| 身份歧义 | 阻断并请求官方ID或完整队名 |
| 截图读不清 | 请求高清局部或手输，不联网替数 |
| 只有市场 | 降级为 `market_only` |
| 伤停不可用 | 标 `UNAVAILABLE`，继续基础模型 |
| 赛果未完 | `not_finished` |
| 90分钟字段不明 | `needs_review`，不进正式分母 |
| 来源冲突 | `SOURCE_CONFLICT`，不覆盖 |
| 国际赔率失败 | 记录失败，体彩链路继续 |

## 按需读取

- `references/data_contract.md`：输入字段和证据账本。
- `references/output_contract.md`：输出结构。
- `references/motive_evidence_reference.md`：赛前事实映射。
- `references/pitfalls.md`：工程和方法论踩坑。
- `references/version_and_data_migration.md`：唯一事实源、版本和回滚。

最终固定附注：**概率模型输出，非投注建议。**
