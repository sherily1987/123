# MCP 数据证据块: 尼斯(Nice) vs 洛里昂(Lorient) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2040997;home=尼斯;away=洛里昂;api_match_id=None)

> 竞彩: 周六025 | 体彩matchId 2040997 | apifootball match_id None



## 量化信号摘要

- 主队状态: [MEDIUM] 近5场10分(场均2.0), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队状态: [MEDIUM] 近5场12分(场均2.4), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 1. 伤停与阵容
- API-Sports 伤停状态=ok；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2040997、主队=尼斯、客队=洛里昂、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=150.0 / 1-0=8.0 / 5-2=200.0 / 5-1=100.0 / 2-4=100.0 / 2-5=500.0 / 2-2=13.0 / 2-3=40.0 / 2-0=9.5 / 2-1=7.0 / 3-3=60.0 / 3-1=16.0 / 3-2=24.0 / 3-0=19.0 / 0-1=10.0 / 0-0=11.0 / 0-3=50.0 / 0-2=18.0 / 0-5=500.0 / 0-4=150.0 / 4-2=70.0 / 4-1=45.0 / 4-0=55.0 / 1-2=10.5 / 1-1=6.25 / 1-4=90.0 / 1-3=30.0 / 1-5=350.0 / 胜其他=70.0 / 平其他=450.0 / 负其他=120.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:12.011415+00:00)
- TTG 总进球赔率: odds=[11.0, 4.7, 3.35, 3.75, 5.8, 11.5, 21.0, 35.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:12.011415+00:00)
- HAFU 半全场赔率: odds=[3.25, 15.0, 34.0, 5.1, 5.2, 7.5, 27.0, 15.0, 5.7] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:12.011415+00:00)

## API-Football 临场富集
## API-Football 最近5场
- 主队近况口径: 正式比赛优先；排除友谊赛5场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队近况: 2026-05-29T18:45:00+00:00 | Ligue 1 | Nice 4-1 Saint Etienne | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队近况: 2026-05-26T18:45:00+00:00 | Ligue 1 | Saint Etienne 0-0 Nice | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队近况: 2026-05-22T19:00:00+00:00 | Coupe de France | Lens 3-1 Nice | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队近况: 2026-05-17T19:00:00+00:00 | Ligue 1 | Nice 0-0 Metz | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队近况: 2026-05-10T19:00:00+00:00 | Ligue 1 | Auxerre 2-1 Nice | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况口径: 正式比赛优先；排除友谊赛6场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况: 2026-05-17T19:00:00+00:00 | Ligue 1 | Lorient 0-2 Le Havre | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况: 2026-05-10T19:00:00+00:00 | Ligue 1 | Metz 0-4 Lorient | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况: 2026-05-02T15:00:00+00:00 | Ligue 1 | Paris Saint Germain 2-2 Lorient | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况: 2026-04-26T13:00:00+00:00 | Ligue 1 | Lorient 2-3 Strasbourg | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队近况: 2026-04-18T15:00:00+00:00 | Ligue 1 | Lorient 2-0 Marseille | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停状态: ok | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 首发状态: UNAVAILABLE | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | M. Abdelmonem | Ankle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | L. Abergel | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | M. Bombito | Leg Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | N. Ngoumou | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Lorient | M. Bamba | Lacking Match Fitness | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | M. Abdelmonem | Ankle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | L. Abergel | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | M. Bombito | Leg Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Nice | N. Ngoumou | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)
- 伤停: Lorient | M. Bamba | Lacking Match Fitness | source(https://v3.football.api-sports.io/injuries?fixture=1552734) | collected_at(2026-08-22T08:13:12.011415+00:00)

## 4. 历史交锋 H2H
- 2026-02-22: Nice 3-3 Lorient (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 2025-11-30: Lorient 3-1 Nice (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 2024-04-19: Nice 3-0 Lorient (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 2023-08-20: Lorient 1-1 Nice (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 2023-03-19: Nice 1-1 Lorient (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 2022-10-30: Lorient 1-2 Nice (Ligue 1) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 4b. 近期状态 (apifootball 附带数据)
- 主队状态: [MEDIUM] 近5场10分(场均2.0), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队: 2026-08-15 Hull 0-0 Nice source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队: 2026-07-31 Juventus 2-0 Nice source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队: 2026-07-25 Marseille 0-3 Nice source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队: 2026-07-18 Nice 4-0 Nimes source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 主队: 2026-05-29 Nice 4-1 St Etienne source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队状态: [MEDIUM] 近5场12分(场均2.4), 状态不错 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队: 2026-08-15 Elversberg 4-1 Lorient source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队: 2026-08-08 Angers 2-1 Lorient source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队: 2026-08-04 Lorient 5-1 UNFP source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队: 2026-07-25 Guingamp 0-2 Lorient source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
- 客队: 2026-07-18 Lorient 1-0 Nantes source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:12.011415+00:00)
