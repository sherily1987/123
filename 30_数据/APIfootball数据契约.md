---
type: data-contract
provider: apifootball.com
api_version: v3
updated: 2026-08-12
---

# APIfootball数据契约

## 接口与用途

| 接口 | 用途 | 当前限制 |
|---|---|---|
| `get_football_matches` | 比赛列表（赛程/结果） | 需 date_from/date_to；kickoff_utc 带时区 |
| `get_match_details` | 单场详情（球场/主裁/轮次/lineups） | 首发可能为空=未发布 |
| `get_head_to_head` | 历史交锋 + 双方近5场 | 不收 match_id，传 team1_name/team2_name 或 id |
| `get_football_standings` | 积分榜 | 请求时榜单，历史需快照 |
| `get_football_odds` | 真实博彩赔率（1X2/BTTS/O-U2.5） | 只进入市场层和CLV研究 |
| `get_football_predictions` | 官方数学预测概率 | 保存为 `p_apifootball`，不是xG |
| `get_football_topscorers` | 射手榜 | ⚠️ 当前套餐权限受限 |

## 时间规则

```text
collected_at < kickoff
```

才可以作为当前比赛赛前数据；带时区 offset，无 offset 不猜测。否则状态必须是 `POST_MATCH_NOT_USABLE`。

## xG规则

APIfootball 统计中没有稳定 xG 字段：`Shots Total ≠ xG`，`prob_HW/prob_D/prob_AW ≠ xG`。轨道A 的 `goal_rate` 是 `proxy_lambda`（MULTI_MARKET_XG 多市场反解），不等于事件 xG。

## 三家数据服务商勿混

```text
football-data.org  → X-Auth-Token
api-sports.io     → x-apisports-key
apifootball.com   → APIkey query 参数（当前会员key）
```

## ⚠️ 已知数据分裂（2026-08-12 更新）

1. **registry.jsonl（预测登记库）**：~~仓库内 1550 vs 外部 1555，差 8 条~~ **已合并（2026-08-12）**——`merge_registry_gap.py` 将 8 条（`sporttery-2040812~2040818、2040830`）按正规哈希链重算并入仓库内，现 **1558 条**，整链验证通过（备份 `registry.jsonl.bak_20260812_merge8`）。
2. **production_movement.jsonl（赔率移动）**：`fusion_daily_pipeline.py` 的 STORE/ODDS_STORE/WORK 仍硬编码指向外部套件，而 `FUSION_DATA_ROOT` 配置的是仓库内路径。外部副本（926KB，写到 08-12 09:00）比仓库内（753KB，到 08-11 10:00）更新更大。**合并/确认权威来源前，不要改这三个路径**。

## 洲际赛事数据可用性（2026-08-12 实测）

### ⚠️ 韩职/日职数据源真相（2026-08-12 查明）

- **fd_kor_events.jsonl 是坏数据，已隔离**：31 支"球队"全是挪威联赛队名（Molde/Rosenborg/Aalesund…）。根因：football-data.co.uk 的 `new/KOR.csv` 请求被服务器**重定向到 NOR.csv**（该站根本没有韩职文件），当初下载时把挪威数据当韩职入库。已移至 `project021/04_素材/corrupt_data_quarantine/`，README 记录了根因。此前"韩 K1 695 场 +0.0290"回测成绩实为挪威数据，**无效**。
- ~~**韩职当前无任何可行数据源**~~ **已推翻（2026-08-16）**——原结论只排除了三条路：
  football-data.co.uk 无韩职（KOR.csv→NOR.csv、K1.csv 300 Multiple Choices）；apifootball
  套餐无韩职（count=0）；fbref 有 K League 1（comps/55）但 Cloudflare 拦截不可爬
  （2026-08-16 用无头 Chromium 复验仍为 403 人机验证页，**这条不变，且不绕过**）。
  但另有两条路实测可用，见下「韩职可用源（2026-08-16 实测）」。**注意区分口径**：
  新增的是赛果/阵容/伤停类证据源，**不是训练数据源**——韩职仍无 xG、无历史赔率整档，
  训练轨的空缺没有被填上，量化轨口径不变。
- **日职 fd_jpn 数据正确**：真实 J1 球队（浦和/鹿岛/大阪钢巴等），4523 场 2012-2025，赛果+收盘赔率，与 football-data `new/JPN.csv` 逐场一致；无 xG（走"无 xG"训练路径，实测 +0.0178 跑赢收盘线）。
- 其余 fd_* 已核验无污染：fd_e1=英冠、fd_f2=法乙、fd_bra=巴甲、fd_arg=阿甲。

### 韩职可用源（2026-08-16 实测）

| 源 | 拿到什么 | 取法 | 实测 |
|---|---|---|---|
| `transfermarkt.com/k-league-1/verletztespieler/wettbewerb/RSK1` | **球员级伤停**：伤情类型 + 身价 | 纯 HTTP | ✅ 徐永在踝伤、河昌来肌肉伤、石田雅俊椎体伤、Erick Farias 跟腱手术… |
| `transfermarkt.com/k-league-1/startseite/wettbewerb/RSK1` | 球队、阵容、身价 | 纯 HTTP | ✅ 9666 字符 |
| `kleague.com/api/recentMatchResult.do` | **赛程/赛果 + gameId + 队代码 + endYn** | 纯 HTTP POST | ✅ 已接入 `kleague_portal.py fixtures` |
| `kleague.com/api/clubRank.do` | **积分榜 + 近6场走势**（赛前可用） | 纯 HTTP POST | ✅ 已接入 `kleague_portal.py standings` |
| `portal.kleague.com/data/matc/matchPlayerPosInfo.do` | 单场 40 人球员数据（号码/位置/队长/出场/进球/助攻） | 纯 HTTP POST | ✅ 已接入 `kleague_portal.py` |
| `portal.kleague.com/data/matc/scoreInfoForMain.do` | 比分信息 | 同上 | ✅ 200 |

门户接口参数（2026-08-16 抓包确定）：

```text
POST /data/matc/matchPlayerPosInfo.do
     meetYear=2026&meetSeq=1&gameId=133&homeTeam=K22&awayTeam=K03
POST /data/matc/scoreInfoForMain.do
     meetYear=2026&meetSeq=1&gameId=133
```

`meetSeq` 1=K League 1、2=K League 2；队代码形如 `K22`/`K03`。响应是 HTML 片段，
但球员数组以 JSON 内嵌在 `log([...])` 里，`kleague_portal.extract_players()` 解析
的是 JSON 而非 DOM 属性。

另有**官网 API 层**（2026-08-16 抓包），返回规范 JSON 信封 `{resultCode,resultMsg,data}`：

```text
POST https://www.kleague.com/api/recentMatchResult.do   近期赛程/赛果
POST https://www.kleague.com/api/clubRank.do            积分榜 + 近6场走势
```

`recentMatchResult.do` **就是 gameId 与队代码的来源**，含 `endYn`（Y=已完赛）、
`gameDate`/`gameTime`、比分、球场、轮次，K1/K2 一起返回（`leagueId` 区分）。
**gameId 缺口已解决**，三个接口现由 `kleague_portal.py` 的 `fixtures` /
`standings` / `players` 三个子命令统一封装。

**三条硬约束，接入前必读**：

1. **官方门户没有赛前首发**（2026-08-16 实测确认，别再找了）。`matchPlayerPosInfo.do`
   对已完赛场次返回 40 人（含 goalQty/workTime 等赛后字段），对未开赛场次
   （`endYn=N`）**返回 0 人**。它只能用于赛果、回测、历史库；按 `collected_at < kickoff`
   对赛前证据是 **POST_MATCH_NOT_USABLE**，`looks_post_match()` 自动标记。
   韩职**赛前可用**的是赛程（开球时刻/对阵）与积分榜/近6场走势。
2. **未开赛场次的比分是占位 0-0**，不能当比分透出；`parse_fixtures()` 已置为 `None`。
3. **开球时刻不带时区 offset**。韩职在韩国办，KST(+09:00) 是显然读法，但接口没声明，
   模块不替调用方假设——默认只给 `kickoff_naive`，要带时区须显式传 `--assume-offset +09:00`。

**交叉验证（2026-08-16）**：`evidence_2026-08-15/evidence_005` 当时从 Wikipedia 取到
「首尔 22 轮 44 分领跑、领先蔚山 7 分」；官方 API 现示首尔 23 轮 47 分、蔚山 37 分，
与 08-15 主场 4-2 胜大田（gameId=135）完全对得上。**这条链可以把韩职的战意/近况类
证据从 Wikipedia 换成权威结构化源。**

这直接补上了 `evidence_2026-08-15` 里「韩职官方伤停名单未公布，球员级伤停检索
（web_search + Transfermarkt 队页）均未取到」那条缺口——**队页本来就取得到**，
当初失败是抽取问题不是封锁，同 [[30_数据/网页源可达性矩阵]] 的头号结论。

`portal.kleague.com` 两个 `.do` 端点是数据门户页面自身发出的公开请求，无鉴权、
无验证码；未带参数时返回通用片段，接入前需先确定比赛参数。

### xG 来源（2026-08-16 实测）

`api-sports数据能力实测.md` 里「xG 仍缺，fbref 是唯一来源」**已过期**：
`understat.com/league/<联赛>` 免费、无验证，覆盖五大联赛，提供

- 球队级 xG/xGA/xPTS（实测巴萨 38 场 xG 99.67 / xGA 50.71 / xPTS 79.06）
- 单场 xG（实测比亚雷亚尔 5-1 马竞，2.80 vs 1.58）

**取法已升级为公开 JSON 接口，不再需要渲染**（2026-08-16 抓包）：

```text
GET https://understat.com/getLeagueData/<联赛代号>/<赛季起始年>
必须带 X-Requested-With: XMLHttpRequest，否则返回的不是 JSON
```

返回全联赛逐场 `xG/npxG/xGA/npxGA/xpts/ppda/deep/scored/missed`，实测西甲 20 队 ×38 场
共 530KB。已接入 `understat_xg.py`（`--league 西甲 --season 2025 --team X --cutoff ...`）。

**时间口径**：understat 的 `date` 是**无时区裸时间**（"2025-08-16 11:30:00"）。按本契约
「无 offset 不猜测」，`understat_xg.py` 不给它假设时区，而是按最坏情况 ±14h 过滤——
一场比赛只有在任何时区解释下都早于 cutoff 才计入赛前统计。代价是 cutoff 前 14h 内的
比赛被保守丢弃，换来赛后数据绝不混进赛前证据。

覆盖范围限五大联赛 + RFPL。**逐场 npxG/ppda 仍只有 understat**。
五大联赛以外：日职、沙职现有 FotMob **赛季累计** table.xg（见下节），不是逐场历史；
韩职 / 韩K2 / 日乙 / 芬超 / MLS 的 FotMob 积分榜没有 xG 列——训练轨「无 xG 路径」对这些联赛仍不变。

### FotMob 联赛接口（2026-08-16 实测，第 4 级）

understat 覆盖之外的体彩联赛，用同一手法（抓页面自己的请求，再纯 HTTP 复验）落到
FotMob 公开 JSON，不再渲染联赛页。

```text
GET https://www.fotmob.com/api/data/allLeagues              联赛 id 目录（86KB）
GET https://www.fotmob.com/api/data/leagues?id=<联赛ID>     积分榜 + 全季赛程（400KB～1.2MB）
GET https://www.fotmob.com/api/data/matchDetails?matchId=   单场统计，含球队 xG
```

无鉴权。id **不要猜**：`allLeagues` 是发现路径。2026-08-16 已复验：

| 联赛 | fotmob id | 赛程 utcTime | table.xg（赛季累计） |
|---|---|---|---|
| 荷甲 | 57 | 带 Z | 有 |
| 葡超 | 61 | 带 Z | 有 |
| 日职 J1 | 223 | 带 Z | 有（广岛 2 轮 xG 5.95 / xGA 0.62） |
| 日乙 J2 | 8974 | 带 Z | **无** |
| 美职 MLS | 130 | 带 Z | **无** |
| 瑞超 | 67 | 带 Z | 有 |
| 挪超 | 59 | 带 Z | 有 |
| 英冠 | 48 | 带 Z | 有 |
| 巴甲 | 268 | 带 Z | 有 |
| 芬超 | 51 | 带 Z | **无** |
| 沙职 | 536 | 带 Z | 有（希拉尔揭幕 xG 4.46 / xGA 1.86） |
| 韩职 | 9080 | 带 Z | **无** |
| 韩 K2 | 9116 | 带 Z | **无** |

已接入 `fotmob_league.py`。**三条硬约束**：

1. **`status.utcTime` 带 Z**（如 `2026-08-07T10:25:00Z`），按 `collected_at < kickoff`
   过滤即可，不必走 understat 那套 ±14h。cutoff 仍必须带 offset，无 offset 直接抛错。
2. **table.xg 是抓取时刻的赛季累计快照**，不是逐场历史。对当场比赛要当赛前证据，
   必须 `collected_at < 该场 kickoff`；开球后再拉的榜已经含本场，状态是
   `POST_MATCH_NOT_USABLE`。
3. **`matchDetails` 的球队 xG 是赛后字段**（实测日职 5803519 完场才有 1.46 / 3.44）。
   `looks_post_match` 为真时不得写入该场赛前证据，只能回测。

页面 HTML 仍是骨架（矩阵里 fotmob.com 那行「必须渲染」指伤停正文，不是指这份 JSON）。
**不写入生产 1X2，不与量化轨融合。**

### 洲际/无源赛事矩阵

| 赛事 | 体彩盘口 | apifootball | 训练轨模型 | 跨联赛标尺 | 可用路径 |
|---|---|---|---|---|---|
| 欧冠/欧罗巴/欧协联 | ✅ | ✅ | ❌ 按设计不训练 | ✅（-0.0706 改善） | market_only 或标尺 |
| 欧超杯 | ✅ | ✅ | ❌ | ✅（PSG vs 维拉实测 λ1.15:1.28） | market_only 或标尺（C档降级） |
| 解放者杯 | ✅ | ✅ 联赛有 | ❌ 南美联赛不在训练集 | ❌ 无偏移表 | **仅 market_only** |
| 亚冠精英 | ✅ 五盘口齐全 | ❌ count=0 | ❌ | ❌ 无 J/K 联赛偏移 | **仅 market_only**（实测江原FC vs 大阪钢巴通过） |
| 沙职 | ✅ | ❌ | ❌ | ❌ | 仅 market_only |

要点：
- **亚冠精英实测可用**（2026-08-11 江原FC vs 大阪钢巴）：体彩 HAD [2.73,3.05,2.3] 五盘口 → fusion market_only 正常输出（λ0.905/1.085、Top比分0-1/1-1/0-0、大2.5 32.5%）。本地快照库已有 `by_league/亚冠精英.jsonl`。
- **所有洲际赛事只给 market_only 基线**（市场依赖100%），无独立模型；体彩未开售场次无法算基线。
- apifootball 队名注意：法甲用 `PSG`、英超 `Aston Villa`（非 Paris Saint Germain）。

## MCP 与 Crawl 证据层（2026-08-11 起）

- MCP 是第三方结构化数据，只能作主证据独立过门禁后的补充；sidecar 需 `match_identity(...)` 与体彩ID、主客队一致。
- Crawl4AI（`project018_技能工作区整合/02_脚本/llm/football-llm-predictor/crawl_evidence.py`，2026-08-16 从 C 盘迁入仓库）只采官方/已知可信 JS 网页快照，`url`/`final_url` 同 hostname（仅容忍 www.），每类实质事实至少2个独立域名，默认不覆盖已有主证据。详见同目录 `CRAWL4AI_EVIDENCE.md`。
- 网页全文只存快照，禁止整页投给 LLM。

### 无数据源时的取数阶梯（2026-08-16 定）

某项数据「没有源」时，按代价从低到高逐级尝试，**不要停在第一次失败上**——
08-15 那批缺口就是停早了造成的：

1. **API**：apifootball / 体彩 / open-meteo 等既有契约接口；
2. **纯 HTTP**（带普通桌面 UA）：Transfermarkt 伤停、OddsPortal 1X2、jleague 赛程、
   K League 官网实测都在这一层拿到。**页面 HTML 常达 128KB～764KB，必须确认关键字段
   真的在正文里，别被 `web_extract` 的截断骗成「未取到」**；
3. **真浏览器渲染**（`playwright_fetch.py`，无头 Chromium）：数据只存在于 JS 变量或
   页面正文、没有对应 JSON 接口的站点（fotmob **页面**伤停仍属此类）；
4. **抓站点自身的公开接口**：用 `capture_xhr.py` 记录页面发出的 XHR/fetch，再纯 HTTP
   复验。understat `/getLeagueData`、FotMob `/api/data/leagues`、K League
   `portal.kleague.com/data/matc/*.do` 与 `kleague.com/api/*.do` 都由此得来；
5. **换源**：同一事实找别的域名，这也是六类证据「每类两个独立 hostname」的本意；
6. **记缺口**。

阶梯到第 6 级为止。**命中人机验证、登录墙、付费墙的站点（fbref / forebet /
whoscored / besoccer）一律停在这里如实记缺口，不做绕过**——这是 `CRAWL4AI_EVIDENCE.md`
的既有边界，也是工具层的硬限制：`fetch_http_first` 不会把 403 自动换客户端重试。
fbref 有会员的话，人工登录后导出、再交给解析脚本，是合规路径。

各源实测状态见 [[30_数据/网页源可达性矩阵]]。

## 事实源

- 适配器：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_adapter.py`
- 特征构建：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_model_features.py`
- 数据契约：`C:\Users\Administrator\.codex\skills\football-quant-fusion\references\data_contract.md`
- MCP 查询器：`project001_足球预测\02_脚本\mcp_query.py`（C盘 `mcp_evidence.py` 依赖此路径）
