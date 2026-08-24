# MCP 数据证据块: 西班牙人(Espanyol) vs 皇马(Real Madrid) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2040999;home=西班牙人;away=皇马;api_match_id=None)

> 竞彩: 周六027 | 体彩matchId 2040999 | apifootball match_id None



## 量化信号摘要

- 主队状态: [LOW] 近5场9分(场均1.8) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队状态: [MEDIUM] 近5场4分(场均0.8), 状态一般 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 1. 伤停与阵容
- API-Sports 伤停状态=ok；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2040999、主队=西班牙人、客队=皇马、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=600.0 / 1-0=19.0 / 5-2=500.0 / 5-1=500.0 / 2-4=50.0 / 2-5=100.0 / 2-2=17.5 / 2-3=23.0 / 2-0=40.0 / 2-1=20.0 / 3-3=75.0 / 3-1=65.0 / 3-2=65.0 / 3-0=150.0 / 0-1=7.5 / 0-0=17.0 / 0-3=9.0 / 0-2=6.75 / 0-5=40.0 / 0-4=17.0 / 4-2=300.0 / 4-1=300.0 / 4-0=400.0 / 1-2=7.0 / 1-1=8.6 / 1-4=20.0 / 1-3=9.5 / 1-5=50.0 / 胜其他=300.0 / 平其他=350.0 / 负其他=25.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:17.843833+00:00)
- TTG 总进球赔率: odds=[17.0, 5.9, 3.8, 3.6, 5.0, 8.25, 15.0, 21.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:17.843833+00:00)
- HAFU 半全场赔率: odds=[13.0, 20.0, 24.0, 17.0, 7.5, 4.1, 45.0, 20.0, 1.9] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:17.843833+00:00)

## API-Football 临场富集
## API-Football 最近5场
- 主队近况口径: 正式比赛优先；排除友谊赛6场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队近况: 2026-08-16T17:00:00+00:00 | La Liga | Espanyol 3-0 Levante | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队近况: 2026-05-23T19:00:00+00:00 | La Liga | Espanyol 1-1 Real Sociedad | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队近况: 2026-05-17T17:00:00+00:00 | La Liga | Osasuna 1-2 Espanyol | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队近况: 2026-05-13T17:00:00+00:00 | La Liga | Espanyol 2-0 Athletic Club | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队近况: 2026-05-09T14:15:00+00:00 | La Liga | Sevilla 2-1 Espanyol | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况口径: 正式比赛优先；排除友谊赛5场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况: 2026-05-23T19:00:00+00:00 | La Liga | Real Madrid 4-2 Athletic Club | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况: 2026-05-17T17:00:00+00:00 | La Liga | Sevilla 0-1 Real Madrid | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况: 2026-05-14T19:30:00+00:00 | La Liga | Real Madrid 2-0 Oviedo | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况: 2026-05-10T19:00:00+00:00 | La Liga | Barcelona 2-0 Real Madrid | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队近况: 2026-05-03T19:00:00+00:00 | La Liga | Espanyol 0-2 Real Madrid | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停状态: ok | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 首发状态: UNAVAILABLE | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | L. Cabrera | Red Card | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | K. Garcia | Hamstring Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | J. Puado | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | R. Asencio | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Eder Militao | Hamstring Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Endrick | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | F. Mendy | Hip Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | T. Pitarch | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Rodrygo | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | A. Tchouameni | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | L. Cabrera | Red Card | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | K. Garcia | Hamstring Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Espanyol | J. Puado | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | R. Asencio | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Eder Militao | Hamstring Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Endrick | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | F. Mendy | Hip Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | T. Pitarch | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | Rodrygo | Knee Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)
- 伤停: Real Madrid | A. Tchouameni | Muscle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1570347) | collected_at(2026-08-22T08:13:17.843833+00:00)

## 4. 历史交锋 H2H
- 2026-05-03: Espanyol 0-2 Real Madrid (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 2025-09-20: Real Madrid 2-0 Espanyol (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 2025-02-01: Espanyol 1-0 Real Madrid (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 2024-09-21: Real Madrid 4-1 Espanyol (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 2023-03-11: Real Madrid 3-1 Espanyol (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 2022-08-28: Espanyol 1-3 Real Madrid (La Liga) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 4b. 近期状态 (apifootball 附带数据)
- 主队: 2026-08-16 Espanyol 3-0 Levante source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队: 2026-08-08 Coventry 3-1 Espanyol source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队: 2026-08-01 Middlesbrough 3-3 Espanyol source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队: 2026-07-29 Burnley 2-2 Espanyol source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 主队: 2026-07-25 Espanyol 1-1 Sabadell source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队状态: [MEDIUM] 近5场4分(场均0.8), 状态一般 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队: 2026-08-16 Schalke 0-3 Real Madrid source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队: 2026-08-12 Dep. A Coruna 0-1 Real Madrid source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队: 2026-08-08 Ferencvaros 1-2 Real Madrid source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队: 2026-08-01 Real Madrid 2-2 Fiorentina source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
- 客队: 2026-07-28 Real Madrid 4-1 Leganes source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:17.843833+00:00)
