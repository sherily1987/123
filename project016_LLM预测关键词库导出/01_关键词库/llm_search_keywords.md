# LLM 预测关键词库（导出版）

用于足球量化双轨预测中的 **LLM 轨道**：搜索证据驱动定性判断。按证据类型分六类，中英双语，官方来源优先；每类至少两个来源交叉验证，无来源 URL 与采集时间的事实不得进入记录。

## 六类关键词表

| 证据类型 | 中文关键词 | 英文关键词 | 映射字段 |
| --- | --- | --- | --- |
| 伤停/阵容 | `<队名> 伤停 阵容 预计首发`；`<队名> 停赛 伤病名单` | `<team> injury list lineup news`；`<team> predicted lineup`；`<team> confirmed lineup` | `attack_absence_*` / `defense_absence_*` / `gk_absence_*` |
| 战意/动机 | `<队名> 战意 保级 争冠 轮换`；`<队名> 主教练 发布会` | `<team> motivation relegation must win`；`<team> rotation press conference`；`<team> manager quotes` | `attack_motive_*` / `rotation_*` / `defense_risk_*` |
| 近况/状态 | `<队名> 近期战绩 状态 xG` | `<team> form last 5 matches xG`；`<team> recent results` | 现状核实（narrative，不进概率） |
| 主客/旅行/天气 | `<队名> 客场 远征 天气 人工草皮` | `<team> away trip travel weather`；`<team> artificial turf` | 单独字段 + 原因说明 |
| 赔率异动 | `<赛事> 赔率 走势 盘口变化` | `[league] odds movement`；`[match] odds drift` | 与 `odds-drift` 对照，不直接改概率 |
| 身份核验 | `<中文简称> 英文名 官方` | `<team> official site`；`<team> full name` | 防张冠李戴（队名歧义时） |

## 通用追加词（所有类别可用）

- `site:fbref.com`（xG/统计）
- `site:transfermarkt.com`（身价/阵容/伤停）
- `[联赛] round standings [赛季]`（积分榜/战意核实）
- `[队名] 前瞻`（中文前瞻，如 7m / 搜狐 / 懂球帝）
- `[队名] preview [联赛]`（英文前瞻，如 Onefootball / 本地媒体）

## 搜索纪律

1. **中英双语并行**：中文源（7m、搜狐、懂球帝、网易、虎扑）+ 英文/本地源（Onefootball、VI.nl、La DH、Tipsbladet、官方站），避免单一语种盲区。
2. **每类至少两个来源交叉验证**：同一事实必须在两个独立来源一致后采信；冲突时记录双方，不掩盖分歧。
3. **官方优先**：俱乐部/赛事官网、官方伤停名单 > 主流媒体 > 聚合站。
4. **来源可引用**：每条证据必须带 `source(URL)` + `collected_at`，禁止凭印象写事实。
5. **定性不伪概率**：LLM 轨道只输出方向（H/D/A 单选或双选）与比分偏好，禁止生成伪概率、伪 xG。

## 试点实测案例（巴西国际 vs 科林蒂安）

实际查询组合：`injury lineup` / `form last 5` / `head to head` / 中文伤停前瞻 / 联赛积分榜，共六组查询，跨 5 个来源完成交叉验证。
