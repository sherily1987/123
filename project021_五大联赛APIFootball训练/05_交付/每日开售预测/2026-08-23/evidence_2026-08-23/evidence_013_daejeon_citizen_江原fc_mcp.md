# MCP 数据证据块: 大田市民(Daejeon Citizen) vs 江原FC(江原FC) | 



> API-Sports 降级证据: APIFootball 未能安全匹配该场；只保留体彩市场与 API-Sports 近况/伤停/首发，不得把缺失的官方模型、积分榜或交锋信息视作无风险。

> match_identity(sporttery_match_id=2041003;home=大田市民;away=江原FC;api_match_id=None)

> 竞彩: 周日003 | 体彩matchId 2041003 | apifootball match_id None



## 量化信号摘要
- 各项指标均在正常范围, 无显著异常信号 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 1. 伤停与阵容
- API-Sports 伤停状态=UNAVAILABLE；首发状态=UNAVAILABLE。伤停或首发尚不可用，属于证据缺口，不能解读为无人缺阵或首发已确认。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 2. 战意与动机
- 本结构化块不把排名、赛程或主场直接推断为战意；没有逐项可核验事实时属于证据缺口。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 3. 近况与状态
- 两队最近正式比赛、积分与交锋（若供应方返回）保留在下方对应数据块；热身赛不作为正式近况依据。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 4. 主客/旅行/天气
- 当前结构化源未提供旅行与天气事实，属于数据缺口（证据缺口），不能按无影响处理。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 5. 赔率
- 体彩官方市场字段保留在下方；若具体盘口未返回，则属于证据缺口，不得补写或推断赔率。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 6. 身份核验
- 已绑定 sporttery_match_id=2041003、主队=大田市民、客队=江原FC、api_match_id=None。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)

## 体彩官方衍生市场
- CRS 比分赔率: 5-0=300.0 / 1-0=8.25 / 5-2=300.0 / 5-1=250.0 / 2-4=110.0 / 2-5=350.0 / 2-2=14.0 / 2-3=35.0 / 2-0=12.5 / 2-1=8.0 / 3-3=75.0 / 3-1=19.0 / 3-2=32.0 / 3-0=26.0 / 0-1=8.5 / 0-0=10.0 / 0-3=29.0 / 0-2=13.0 / 0-5=350.0 / 0-4=90.0 / 4-2=100.0 / 4-1=60.0 / 4-0=80.0 / 1-2=8.5 / 1-1=5.75 / 1-4=75.0 / 1-3=22.0 / 1-5=300.0 / 胜其他=120.0 / 平其他=400.0 / 负其他=125.0 | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:28.135295+00:00)
- TTG 总进球赔率: odds=[10.0, 4.45, 3.2, 3.75, 6.5, 13.0, 23.0, 38.0] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:28.135295+00:00)
- HAFU 半全场赔率: odds=[4.3, 16.0, 28.0, 5.9, 4.75, 6.0, 27.0, 16.0, 4.4] | source(https://webapi.sporttery.cn/) | collected_at(2026-08-22T08:13:28.135295+00:00)

## API-Football 临场富集
## API-Football 最近5场
- 主队近况: 2026-08-19T10:00:00+00:00 | FA Cup | Asan Mugunghwa 2-3 Daejeon Citizen | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 主队近况: 2026-08-15T10:30:00+00:00 | K League 1 | FC Seoul 4-2 Daejeon Citizen | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 主队近况: 2026-08-08T11:00:00+00:00 | K League 1 | FC Anyang 1-2 Daejeon Citizen | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 主队近况: 2026-08-02T10:30:00+00:00 | K League 1 | Daejeon Citizen 2-0 Gwangju FC | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 主队近况: 2026-07-25T10:30:00+00:00 | K League 1 | Gimcheon Sangmu FC 3-2 Daejeon Citizen | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况口径: 正式比赛优先；排除友谊赛1场 | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况: 2026-08-19T10:30:00+00:00 | FA Cup | Gangwon FC 0-0 Seongnam FC | status=PEN | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况: 2026-08-16T10:30:00+00:00 | K League 1 | Ulsan Hyundai FC 2-3 Gangwon FC | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况: 2026-08-11T10:30:00+00:00 | AFC Champions League Elite | Gangwon FC 0-0 Gamba Osaka | status=AET | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况: 2026-08-01T10:30:00+00:00 | K League 1 | Gangwon FC 0-3 Bucheon FC 1995 | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 客队近况: 2026-07-26T10:30:00+00:00 | K League 1 | FC Anyang 2-1 Gangwon FC | status=FT | source(https://v3.football.api-sports.io/fixtures) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 伤停状态: UNAVAILABLE | source(https://v3.football.api-sports.io/injuries?fixture=1507038) | collected_at(2026-08-22T08:13:28.135295+00:00)
- 首发状态: UNAVAILABLE | source(https://v3.football.api-sports.io/fixtures/lineups?fixture=1507038) | collected_at(2026-08-22T08:13:28.135295+00:00)

## 5. 数据缺口
- APIFootball 身份匹配不可用；官方模型、积分榜与交锋未采集。本场仅以体彩市场和 API-Sports 可核验事实作研究参考。 source(https://v3.football.api-sports.io) collected_at(2026-08-22T08:13:28.135295+00:00)
