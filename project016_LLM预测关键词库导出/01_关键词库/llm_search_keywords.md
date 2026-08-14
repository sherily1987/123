# LLM 预测关键词库（导出版）

用于足球量化双轨预测中的 **LLM 轨道**：搜索证据驱动定性判断。按证据类型分六类，中英双语，官方来源优先；每类至少两个来源交叉验证，无来源 URL 与采集时间的事实不得进入记录。

> ⚠️ 本文件是**导出版**。唯一事实源为 `llm_prompt_rules.py::SEARCH_KEYWORDS`（project018 `02_脚本/llm/football-llm-predictor/` 与 C 盘生产副本同步一致）。修改关键词请改事实源，勿直接编辑本文件。
> 2026-08-12 修订：关键词改为 **required（必搜）/ optional（按赛事与语言扩展）** 分层；清理伪关键词（get_lineups / team_ids / wttr / 勿混淆）；补齐两回合制战意词与南美语言词。

## 六类关键词表（分层）

| 证据类型 | required（每类至少搜一次） | optional（按赛事/语言扩展） |
| --- | --- | --- |
| 伤停/阵容 | `injury` `injured` `doubtful` `suspended` `team news`；`大名单` `伤停` `缺阵` `停赛` | `predicted lineup` `confirmed lineup` `official lineup` `team announcement` `starting XI` `missing players`；`伤病名单` `赛前发布会`；`blessure` `opstelling` `desfalques` `lesão` `infortunio` `ausfälle`；南美：`escalação` `once titular` `formación` |
| 战意/动机 | `first leg` `second leg` `aggregate` `qualifying round`；`首回合` `次回合` | `opening day` `promoted` `relegation` `title race` `rotation` `midweek` `extra time` `penalties` `away goals rule` `trophy` `final` `showpiece`；`揭幕` `升级` `保级` `争冠` `轮换` |
| 近况/状态 | `last 5` `form` `recent results`；`近5场` `状态` | `home form` `away form` `winning streak` `losing streak` `undefeated` `xG` `xG for` `xG against` `clean sheet`；`走势` |
| 主客/旅行/天气 | `home advantage` `travel` `weather`；`主场` `客场` `天气` | `artificial turf` `pitch condition` `altitude` `heat` `temperature` `long journey`；`草皮` `远征` |
| 赔率异动 | `opening odds` `closing odds`；`初盘` `即盘` | `odds movement` `odds drift` `market move` `steam` `drift`；`让球线` `冷热` `升水` `降水` |
| 身份核验 | `official name` `full name`；`官方全名` | `official site` `official page` `match page` `UEFA official`；`球队官方` `官网` |

## 通用追加词（所有类别可用）

- `site:fbref.com`（xG/统计）
- `site:transfermarkt.com`（身价/阵容/伤停）
- `[联赛] round standings [赛季]`（积分榜/战意核实）
- `[队名] 前瞻`（中文前瞻，如 7m / 搜狐 / 懂球帝）
- `[队名] preview [联赛]`（英文前瞻，如 Onefootball / 本地媒体）

## 两回合制/杯赛必查（2026-08-12 新增）

资格赛与杯赛（8月主战场：欧冠/欧罗巴/解放者杯资格赛、欧超杯）除了常规六类，还必须查：

- **回合与总比分**：`second leg` / `aggregate` / `qualifying round` / `首回合 比分`
- **晋级规则**：`extra time` / `penalties` / `away goals rule`
- **单场决赛**：`trophy` / `final` / `showpiece`（如欧超杯）

先验明"第几回合 + 当前总比分"再写战意证据；不要把资格赛轮次误读为半决赛/决赛。

## 搜索纪律

1. **中英双语并行**：中文源（7m、搜狐、懂球帝、网易、虎扑）+ 英文/本地源（Onefootball、VI.nl、La DH、Tipsbladet、官方站），避免单一语种盲区。南美赛事补西/葡语（escalação / desfalques / formación）。
2. **每类至少两个来源交叉验证**：同一事实必须在两个独立来源一致后采信；冲突时记录双方，不掩盖分歧。
3. **官方优先**：俱乐部/赛事官网、官方伤停名单 > 主流媒体 > 聚合站。
4. **来源可引用**：每条证据必须带 `source(URL)` + `collected_at`，禁止凭印象写事实。
5. **定性不伪概率**：LLM 轨道只输出方向（H/D/A 单选或双选）与比分偏好，禁止生成伪概率、伪 xG。
6. **required 词每类至少命中一次**：避免某类证据因"忘了搜"变成缺口；optional 词按联赛与语言按需扩展。

## 试点实测案例（巴西国际 vs 科林蒂安）

实际查询组合：`injury lineup` / `form last 5` / `head to head` / 中文伤停前瞻 / 联赛积分榜，共六组查询，跨 5 个来源完成交叉验证。
