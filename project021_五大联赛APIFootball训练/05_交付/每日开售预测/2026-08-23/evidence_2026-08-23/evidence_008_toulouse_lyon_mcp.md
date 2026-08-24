# MCP 数据证据块: 图卢兹(Toulouse) vs 里昂(Lyon) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2040998;home=图卢兹;away=里昂;api_match_id=None)

> 竞彩: 周六026 | 体彩matchId 2040998 | apifootball match_id None



## 量化信号摘要

- 主队状态: [LOW] 近5场7分(场均1.4) source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 1. 伤停与阵容
- API-Sports 伤停状态=ok；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2040998、主队=图卢兹、客队=里昂、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=250.0 / 1-0=9.25 / 5-2=275.0 / 5-1=150.0 / 2-4=85.0 / 2-5=300.0 / 2-2=12.5 / 2-3=27.0 / 2-0=13.0 / 2-1=8.0 / 3-3=55.0 / 3-1=19.0 / 3-2=26.0 / 3-0=26.0 / 0-1=9.5 / 0-0=12.0 / 0-3=27.0 / 0-2=13.5 / 0-5=300.0 / 0-4=85.0 / 4-2=80.0 / 4-1=55.0 / 4-0=80.0 / 1-2=8.25 / 1-1=6.4 / 1-4=60.0 / 1-3=20.0 / 1-5=175.0 / 胜其他=80.0 / 平其他=350.0 / 负其他=85.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:14.751170+00:00)
- TTG 总进球赔率: odds=[12.0, 5.25, 3.35, 3.5, 5.7, 10.5, 21.0, 35.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:14.751170+00:00)
- HAFU 半全场赔率: odds=[3.8, 15.0, 33.0, 5.75, 5.25, 6.4, 29.0, 15.0, 4.5] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:14.751170+00:00)

## API-Football 临场富集
## API-Football 最近5场
- 主队近况口径: 正式比赛优先；排除友谊赛3场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队近况: 2026-05-17T19:00:00+00:00 | Ligue 1 | Nantes 0-0 Toulouse | status=AWD | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队近况: 2026-05-10T19:00:00+00:00 | Ligue 1 | Toulouse 2-1 Lyon | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队近况: 2026-05-03T15:15:00+00:00 | Ligue 1 | Strasbourg 1-2 Toulouse | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队近况: 2026-04-25T19:05:00+00:00 | Ligue 1 | Toulouse 2-2 Monaco | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队近况: 2026-04-21T19:10:00+00:00 | Coupe de France | Lens 4-1 Toulouse | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况口径: 正式比赛优先；排除友谊赛6场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况: 2026-08-18T19:00:00+00:00 | UEFA Champions League | Fenerbahçe 1-1 Lyon | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况: 2026-08-11T19:00:00+00:00 | UEFA Champions League | Lyon 3-0 Sparta Praha | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况: 2026-08-04T18:00:00+00:00 | UEFA Champions League | Sparta Praha 2-1 Lyon | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况: 2026-05-17T19:00:00+00:00 | Ligue 1 | Lyon 0-4 Lens | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 客队近况: 2026-05-10T19:00:00+00:00 | Ligue 1 | Toulouse 2-1 Lyon | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停状态: ok | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 首发状态: UNAVAILABLE | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Donnum | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Francis | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | D. Methalie | Yellow Cards | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Vossah | Yellow Cards | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | Abner Vinicius | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | R. Kluivert | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | A. Maitland-Niles | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | K. Merah | Ankle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | M. Niakhate | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Donnum | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Francis | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | D. Methalie | Yellow Cards | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Toulouse | A. Vossah | Yellow Cards | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | Abner Vinicius | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | R. Kluivert | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | A. Maitland-Niles | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | K. Merah | Ankle Injury | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)
- 伤停: Lyon | M. Niakhate | Inactive | source(https://v3.football.api-sports.io/injuries?fixture=1552736) | collected_at(2026-08-22T08:13:14.751170+00:00)


## 4b. 近期状态 (apifootball 附带数据)
- 主队: 2026-08-15 Toulouse 1-2 Hamburger SV source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队: 2026-08-08 Elche 3-0 Toulouse source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队: 2026-08-05 Al Ain 0-1 Toulouse source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队: 2026-07-31 Toulouse 2-1 Real Sociedad source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)
- 主队: 2026-07-25 Toulouse 1-1 Rodez source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:14.751170+00:00)
