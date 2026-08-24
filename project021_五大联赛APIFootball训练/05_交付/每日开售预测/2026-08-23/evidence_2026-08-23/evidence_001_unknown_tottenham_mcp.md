# MCP 数据证据块: 布伦特() vs 热刺(Tottenham) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2040990;home=布伦特;away=热刺;api_match_id=None)

> 竞彩: 周六018 | 体彩matchId 2040990 | apifootball match_id None



## 1. 伤停与阵容
- API-Sports 伤停状态=UNAVAILABLE；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2040990、主队=布伦特、客队=热刺、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=150.0 / 1-0=10.0 / 5-2=120.0 / 5-1=90.0 / 2-4=75.0 / 2-5=250.0 / 2-2=11.5 / 2-3=23.0 / 2-0=12.5 / 2-1=7.5 / 3-3=40.0 / 3-1=15.0 / 3-2=19.0 / 3-0=23.0 / 0-1=13.5 / 0-0=16.0 / 0-3=36.0 / 0-2=18.0 / 0-5=350.0 / 0-4=90.0 / 4-2=50.0 / 4-1=38.0 / 4-0=55.0 / 1-2=9.0 / 1-1=7.0 / 1-4=55.0 / 1-3=20.0 / 1-5=200.0 / 胜其他=46.0 / 平其他=250.0 / 负其他=75.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:12:58.436944+00:00)
- TTG 总进球赔率: odds=[16.0, 5.8, 3.9, 3.6, 4.9, 8.5, 14.5, 23.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:12:58.436944+00:00)
- HAFU 半全场赔率: odds=[3.4, 15.0, 30.0, 5.5, 6.0, 6.8, 25.0, 15.0, 4.8] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:12:58.436944+00:00)

## API-Football 临场富集
- API-Sports 状态: UNAVAILABLE: fixture_match_count=0 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:12:58.436944+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:12:58.436944+00:00)
