# MCP 数据证据块: 热那亚(Genoa) vs 那不勒斯(Napoli) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2040995;home=热那亚;away=那不勒斯;api_match_id=None)

> 竞彩: 周六023 | 体彩matchId 2040995 | apifootball match_id None



## 量化信号摘要

- 主队状态: [LOW] 近5场7分(场均1.4) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队状态: [MEDIUM] 近5场10分(场均2.0), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 1. 伤停与阵容
- API-Sports 伤停状态=ok；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2040995、主队=热那亚、客队=那不勒斯、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=700.0 / 1-0=10.0 / 5-2=600.0 / 5-1=600.0 / 2-4=90.0 / 2-5=300.0 / 2-2=17.0 / 2-3=30.0 / 2-0=21.0 / 2-1=13.5 / 3-3=100.0 / 3-1=45.0 / 3-2=55.0 / 3-0=70.0 / 0-1=6.3 / 0-0=8.5 / 0-3=15.0 / 0-2=8.0 / 0-5=100.0 / 0-4=30.0 / 4-2=250.0 / 4-1=175.0 / 4-0=300.0 / 1-2=7.5 / 1-1=6.0 / 1-4=40.0 / 1-3=15.0 / 1-5=100.0 / 胜其他=300.0 / 平其他=600.0 / 负其他=90.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:08.755711+00:00)
- TTG 总进球赔率: odds=[8.5, 4.0, 3.25, 4.0, 7.0, 14.0, 26.0, 40.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:08.755711+00:00)
- HAFU 半全场赔率: odds=[7.0, 17.0, 27.0, 9.25, 4.5, 4.6, 40.0, 17.0, 3.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:08.755711+00:00)

## API-Football 临场富集
## API-Football 最近5场
- 主队近况口径: 正式比赛优先；排除友谊赛5场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队近况: 2026-08-16T16:30:00+00:00 | Coppa Italia | Genoa 4-1 Ascoli | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队近况: 2026-05-24T18:45:00+00:00 | Serie A | Lecce 1-0 Genoa | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队近况: 2026-05-17T10:00:00+00:00 | Serie A | Genoa 1-2 AC Milan | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队近况: 2026-05-10T13:00:00+00:00 | Serie A | Fiorentina 0-0 Genoa | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队近况: 2026-05-02T18:45:00+00:00 | Serie A | Atalanta 0-0 Genoa | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况口径: 正式比赛优先；排除友谊赛5场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况: 2026-05-24T16:00:00+00:00 | Serie A | Napoli 1-0 Udinese | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况: 2026-05-17T10:00:00+00:00 | Serie A | Pisa 0-3 Napoli | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况: 2026-05-11T18:45:00+00:00 | Serie A | Napoli 2-3 Bologna | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况: 2026-05-02T16:00:00+00:00 | Serie A | Como 0-0 Napoli | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队近况: 2026-04-24T18:45:00+00:00 | Serie A | Napoli 4-0 Cremonese | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停状态: ok | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 首发状态: UNAVAILABLE | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | E. Havel | Thigh Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | L. Venturino | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | H. J. Traore | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | A. Buongiorno | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | M. Folorunsho | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | L. Marianucci | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | P. Mazzocchi | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | E. Havel | Thigh Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | L. Venturino | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Genoa | H. J. Traore | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | A. Buongiorno | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | M. Folorunsho | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | L. Marianucci | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)
- 伤停: Napoli | P. Mazzocchi | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1550091) | collected_at(2026-08-22T08:13:08.755711+00:00)

## 4. 历史交锋 H2H
- 2026-02-07: Genoa 2-3 Napoli (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 2025-10-05: Napoli 2-1 Genoa (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 2025-05-11: Napoli 2-2 Genoa (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 2024-12-21: Genoa 1-2 Napoli (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 2024-02-17: Napoli 1-1 Genoa (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 2023-09-16: Genoa 2-2 Napoli (Serie A) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 4b. 近期状态 (apifootball 附带数据)
- 主队: 2026-08-16 Genoa 4-1 Ascoli source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队: 2026-08-08 Genoa 0-1 Dep. A Coruna source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队: 2026-08-04 Bournemouth 10-1 Genoa source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队: 2026-08-01 Leicester 0-1 Genoa source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 主队: 2026-07-25 Genoa 2-2 L.R. Vicenza source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队状态: [MEDIUM] 近5场10分(场均2.0), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队: 2026-08-12 Napoli 6-2 Aris source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队: 2026-08-08 Napoli 1-1 Celta Vigo source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队: 2026-08-05 Napoli 2-1 Osasuna source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队: 2026-07-26 Napoli 2-0 Carrarese source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
- 客队: 2026-07-22 Napoli 1-3 Arezzo source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:08.755711+00:00)
