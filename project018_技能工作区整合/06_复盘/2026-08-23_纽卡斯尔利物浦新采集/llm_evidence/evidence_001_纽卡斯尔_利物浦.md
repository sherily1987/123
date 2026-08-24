赛事：英超（体彩官方场次）
竞彩编号：周日017
主队：纽卡斯尔联（短名纽卡斯尔）
客队：利物浦（短名利物浦）
开球：2026-08-23T23:30:00+08:00
量化模型档位：无模型
收集时刻：2026-08-23T18:38:44+08:00

## 1. 伤停/阵容
- 体彩官方接口无伤病/大名单字段 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
> 采集规则：首发只接受带身份、来源和采集时间的真实页面/API快照；未发布就标记 UNAVAILABLE。
> 采集规则：伤停只接受带身份、来源和采集时间的真实页面/API快照；无法核验就标记 UNAVAILABLE。
> 采集规则：历史投票包仅作待采任务清单，不是事实来源。首发、伤停和近5场必须来自可审计的 API/网页快照；页面身份、来源、采集时间和开球前门禁全部通过后才能写入。验证码、403、重定向到其他域名或缺少关键词都记为缺口，不绕过。
> 说明：以上仅为采集规则，不是本场事实；必须由真实快照替换，不能直接喂给模型作为首发/伤停。

## 2. 战意/动机
- 本场为竞彩周日017场次，英超在售未开球场次之一，开球时间 2026-08-23T23:30:00+08:00 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
> 说明：轻量证据未抓取教练/球员赛前言论与轮次背景。

## 3. 近况/状态
- 量化 Dixon-Coles 模型覆盖标注：英超 档位 无模型（见 full_backtest.json 滚动回测） | source(file://F:/HM足球比赛预测/project021_五大联赛APIFootball训练/05_交付/full_backtest.json) | collected_at(2026-08-23T18:38:44+08:00)
> 采集规则：近5场必须来自可核验的正式比赛页面/API快照，逐场保留日期、对手、比分和来源；找不到就记录 FORM_UNAVAILABLE，不得用投票或常识补齐。 本场联赛「英超」检索入口如下。候选入口：https://understat.com/getLeagueData/EPL/2026
> 近5场候选来源（待抓取并核验）：https://understat.com/getLeagueData/EPL/2026
> 近5场候选来源（待抓取并核验）：https://understat.com/getLeagueData/EPL/2025
> 近5场候选来源（待抓取并核验）：https://www.flashscore.com/
> 近5场封锁源不采：fbref.com、whoscored.com、forebet.com、besoccer.com
> 说明：候选 URL 不是事实；只有通过快照身份、时间和关键词门禁的页面内容才能进入证据。

## 4. 主客/旅行/天气
- 主队 纽卡斯尔 主场作战，客队 利物浦 客场远征（体彩官方对阵口径） | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
> 说明：轻量证据未抓取天气/旅行距离。

## 5. 赔率
- 体彩官方胜平负即时赔率：主3.43/平3.8/客1.74 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
- 体彩赔率仅单快照，无初盘→即时异动记录 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
- 体彩让球盘（1.0球）：[1.85, 3.88, 3.02] | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
> 说明：外部盘口（欧赔）未抓取。

## 6. 身份核验
- 体彩官方全名：主队"纽卡斯尔联"、客队"利物浦" | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2041017) | collected_at(2026-08-23T18:38:44+08:00)
- 联赛：英超（体彩联赛名口径）；开球时间 2026-08-23T23:30:00+08:00 与体彩列表接口一致 | source(https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry) | collected_at(2026-08-23T18:38:44+08:00)

## 已采集证据快照（LLM可引用）
- team_stats: status=VALID；source=sporttery.preview；refreshed_at=2026-08-23T18:16:02+08:00
- recent_form: status=PARTIAL；source=fotmob.bb_browser；refreshed_at=2026-08-23T18:23:00+08:00；reason=PRESEASON_SCOPE_MIXED
- injury: status=VALID；source=goal.preview；refreshed_at=2026-08-23T18:23:00+08:00
- suspensions: status=VALID；source=goal.preview；refreshed_at=2026-08-23T18:23:00+08:00
  - facts="no suspensions recorded in preview"
- starting_xi: status=PREDICTED；source=fotmob.match_preview；refreshed_at=2026-08-23T18:23:00+08:00；reason=PREDICTED_XI_NOT_CONFIRMED
> 说明：以上是采集器快照事实；预计首发仍是预测值，不等同官方确认首发；LLM票数不得当作概率。

## 证据缺口
> 说明：轻量证据自动生成（project023）。若上方存在融合采集器快照，则优先引用其来源、状态和时间戳；预计首发标记为 PREDICTED，不等同官方确认。未采集或状态不完整的字段继续保留缺口，不能用常识补齐。