# API-Football 数据覆盖调研报告（2026-08-13）

调研对象：api-football.com（API-Sports 官方覆盖页 https://www.api-football.com/coverage）
方法：页面被 Cloudflare 保护，无法直连/提取 → 改用 Wayback Machine 存档（2025-10-15 与 2026-04-10 两个快照，均已完整解析 1238 行覆盖矩阵）+ 官方文档 + MCP 一手实测 + 第三方交叉验证。

## ⚠️ 最重要的澄清：两家"API-Football"是不同的公司

| | api-football.com（本任务评估对象） | apifootball.com（用户 MCP 实际连接的服务商） |
|---|---|---|
| API 域名 | v3.football.api-sports.io | apiv3.apifootball.com |
| 认证 | x-apisports-key 请求头 | ?APIkey= 查询参数 |
| 覆盖声明 | 1238 联赛/杯赛，所有套餐含全部联赛 | 按 plan 区分覆盖（WORLDWIDE plan 含韩国/日本） |

**关键结论：用户 MCP 中"韩职/日职 count=0"是 apifootball.com 的套餐限制，不是 api-football.com 覆盖问题，两者不能混为一谈。**

---

## 1. 联赛/赛事覆盖

**官方数字：1238 个联赛/杯赛**（2026-04-10 快照页面显示 "1238 Leagues & Cups"；2025-10-15 快照为 1212；官网首页 meta 声称 "+1 200"；RapidAPI 页面为较旧的 "+1 100"）
- 国家数：**170 个国家 + World（国际赛事组）= 171 个分组**（由页面国旗+国家名解析得出）
- 全部联赛按国家分组列出，页面注明 "All competitions are included in all our plans"（所有套餐包含全部联赛——API-Sports 侧）

主要联赛覆盖（2026-04-10 快照，✓=有该数据）：
- **五大联赛**：英超 Premier League（9 项全开含赔率）、西甲 La Liga（全开含赔率）、德甲 Bundesliga（全开含赔率）、意甲 Serie A（全开含赔率）、法甲 Ligue 1（全开含赔率）
- **欧洲二级**：荷甲 Eredivisie、葡超 Primeira Liga、比甲 Jupiler Pro League、土超 Süper Lig、希超 Super League 1、苏超、瑞超、奥超、俄超、乌超、挪超、瑞超、丹超、波超、捷甲等（多数含赔率）
- **亚洲**：日职 **J1 League/J2/J3**（J1 全开含赔率）、韩职 **K League 1/K League 2/K3 League**（K1 全开含赔率）、中超 Super League（全开含赔率）、沙特 Pro League（全开含赔率）、卡塔尔、阿联酋、印度、澳大利亚 A-League、泰国、越南、伊朗、伊拉克、马来西亚、新加坡等
- **南美**：巴西（110 项，Serie A 全开含赔率）、阿根廷（多级别）、哥伦比亚、智利、秘鲁、乌拉圭、厄瓜多尔、巴拉圭、玻利维亚、委内瑞拉
- **北美**：美国、墨西哥（Liga MX 系）、加拿大、哥斯达黎加、巴拿马、洪都拉斯、牙买加等
- **非洲**：埃及、摩洛哥、阿尔及利亚、突尼斯、尼日利亚、南非、加纳、塞内加尔、喀麦隆、科特迪瓦、马里、肯尼亚、赞比亚、安哥拉、坦桑尼亚等
- **国际赛事（World 组 181 项）**：世界杯及六大洲预选赛、欧洲杯、亚洲杯、非洲杯、美洲杯、欧冠/欧联/欧协联（含赔率）、解放者杯/南美杯（含赔率）、亚冠精英/亚冠2、非冠/非联杯（含赔率）、中北美冠军杯、友谊赛等

来源：Wayback 快照 https://web.archive.org/web/20260410171008/https://www.api-football.com/coverage（完整 1238 行矩阵解析，本地文件 api_football_coverage_20260410_full.json）

## 2. 赔率覆盖

- **官方覆盖矩阵：426/1238 联赛（34.4%）有赛前赔率**；韩职 K League 1/2/K3、日职 J1/J2/J3、中超、五大联赛、欧冠/欧联、解放者杯等均 ✓（2026-04-10 快照）
- 赛前赔率：官方博客称"赛前 1 至 14 天可用，每 3 小时更新"（RapidAPI 官方讨论帖同口径）
- 滚球赔率：官方定价页高级功能列明确含 "In-play Odds"（滚动赔率）
- 赔率类型（apifootball.com 官方文档 get_odds 示例 + MCP 实测）：
  - 1X2（odd_1/odd_x/odd_2）
  - 双机会 Double Chance（odd_1x/odd_12/odd_x2）
  - 亚洲让球 AH：-4.5 至 +4.5 全盘口
  - 大小球 O/U：0.5 至 5.5 多盘口
  - BTTS 双方进球
- **书商数量**：
  - apifootball.com（MCP 实测 2026-08-16 比赛日）：返回 **12 家**：10Bet、1xBet、bet365、Betfair、BetVictor、Betano、Dafabet、Marathon、Pinnacle(Pncl)、SBO(Sbo)、Unibet、WilliamHill
  - api-football.com（API-Sports）侧：官方页面未给总数，**未找到确切官方数字**；行业第三方描述通常为"约 90-100 家书商"（推测，需向官方确认）

来源：Wayback 快照覆盖矩阵；https://apifootball.com/documentation/（get_odds 字段）；MCP get_football_odds 实测；https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide

## 3. 数据统计覆盖

- **每场比赛 14 种团队统计**（apifootball.com 官方文档 get_statistics 实测示例字段）：
  射门总数 Shots Total、射正 Shots On Goal、射偏 Shots Off Goal、被封堵 Shots Blocked、禁区内射门 Shots Inside Box、禁区外射门 Shots Outside Box、犯规 Fouls、角球 Corners、越位 Offsides、控球率 Ball Possession、黄牌 Yellow Cards、扑救 Saves、总传球 Passes Total、传球成功 Passes Accurate
- **⚠️ 无 xG（预期进球）**：官方文档示例字段中不含 Expected Goals；第三方对比（TheStatsAPI 2026-05）也提示"api-football 的 xG/npxG/xA 不可假设为标准字段"。预测端点返回的是数学概率而非 xG
- 球员级统计：约 30+ 字段（进球、助攻、射门、越位、犯规、抢断、拦截、解围、扑救、对抗、过人、黄牌等）
- 官方覆盖矩阵：比赛统计（Fixtures Statistics）仅 **155/1238（12.5%）** 联赛提供；球员统计 689/1238（55.7%）

来源：https://apifootball.com/documentation/（get_statistics 示例 JSON）；Wayback 快照覆盖矩阵；https://www.thestatsapi.com/blog/xg-api-football（第三方，2026-05）

## 4. 其他数据覆盖（2026-04-10 官方矩阵，✓比例）

| 数据 | 覆盖联赛数 | 占比 |
|---|---|---|
| 比赛事件 Events（进球/牌/换人） | 1034/1238 | 83.5% |
| 阵容 Lineups | 797/1238 | 64.4% |
| 比赛统计 Fixtures Statistics | 155/1238 | 12.5% |
| 比赛球员数据 Fixtures Players | 130/1238 | 10.5% |
| 预测 Predictions | 1238/1238 | 100% |
| 赔率 Odds | 426/1238 | 34.4% |
| 球员统计 Player Statistics | 689/1238 | 55.7% |
| 射手榜 Top Scorers | 689/1238 | 55.7% |
| 积分榜 Standings | 701/1238 | 56.6% |

其他（官方定价页功能清单）：H2H 交锋（Head 2 Head）、直播比分 Livescore、赛程 Fixtures、球员资料 Players、伤病 Injuries、Sidelined（停赛）、转会 Transfers、奖杯 Trophies（后四项为高级功能）
来源：Wayback 快照；https://www.api-football.com/pricing（搜索摘要）

## 5. 关键数字汇总

- **1238** Leagues & Cups（2026-04-10 官方 coverage 页）
- **170** 国家 + World 组（页面解析）
- **1212** Leagues & Cups（2025-10-15 快照）；**+1 200**（官网首页）；**+1 100**（RapidAPI，较旧）
- **426** 联赛有赔率（34.4%）；**14** 种团队统计/场；**12** 家书商（MCP 实测）；**100%** 联赛有预测
- 统计覆盖矩阵：events 83.5% / lineups 64.4% / stats_fixtures 12.5% / players_fixtures 10.5% / odds 34.4% / stats_players 55.7% / standings 56.6%

## 6. 针对用户问题的专项结论（韩职/日职）

- **api-football.com 官方声称覆盖韩职/日职且含赔率**（K League 1/2/K3 ✓odds、J1/J2/J3 ✓odds，2026-04-10 快照）
- **但用户 MCP 实测（apifootball.com 服务商）**：
  - 数据库有韩职/日职历史数据：get_head_to_head 返回 K League 1（league_id=219，Jeonbuk 2026-08-08 比赛）与 J1 League（league_id=209，2026-08-07 比赛）完整历史
  - 但 get_events（赛程）报 **"No event found (please check your plan)"**；get_odds 报 **"No odd found (please check your plan)"** —— **明确为套餐限制**
  - search_football_leagues 对 Japan/South Korea count=0 是 MCP 本地缓存快照缺失 + 套餐限制的双重表现
- **建议**：① 确认/升级 apifootball.com 套餐至覆盖 Korea Republic/Japan 的档位（其 coverage 页显示这两国在 WORLDWIDE plan 中）；② 或直接评估 API-Sports 官方（api-football.com，其页面声明所有联赛包含在所有套餐中）

## 产出文件（F:\HM足球比赛预测\）
- api_football_coverage_wayback.html / api_football_coverage_wayback_20260410.html（原始快照）
- api_football_coverage_parsed.json / api_football_coverage_parsed_20260410.json / api_football_coverage_20260410_full.json（解析后的 1212/1238 行覆盖矩阵）
