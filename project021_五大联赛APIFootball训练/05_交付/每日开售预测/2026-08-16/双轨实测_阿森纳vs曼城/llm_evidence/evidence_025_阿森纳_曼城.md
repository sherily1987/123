赛事：英社区盾（中立场决赛）
竞彩编号：周日011
主队：阿森纳
客队：曼城（曼彻斯特城）
开球：2026-08-16T22:00:00+08:00
收集时刻：2026-08-15T21:22:20+08:00

## 1. 伤停/阵容
- API-Football 本场伤停接口返回 0 条记录；这只表示未获得记录，不能解读为“双方无伤停” | source(https://v3.football.api-sports.io/injuries?fixture=1582365) | collected_at(2026-08-15T21:22:20+08:00)
> 证据缺口：赛前官方首发、伤员名单和轮换安排未核实。

## 2. 战意/动机
- API-Football 将赛事标记为 Community Shield / Final，场地为卡地夫 Principality Stadium，属中立场单场决赛 | source(https://v3.football.api-sports.io/fixtures?id=1582365) | collected_at(2026-08-15T21:22:20+08:00)
> 证据缺口：未获得两队教练赛前发布会或可验证的轮换声明。

## 3. 近况/状态
- API-Football H2H 中最近五场已结束交锋为：曼城 2-1 阿森纳、阿森纳 0-2 曼城、阿森纳 1-1 曼城、阿森纳 5-1 曼城、曼城 2-2 阿森纳；仅作低权重背景，不代替当前阵容状态 | source(https://v3.football.api-sports.io/fixtures/headtohead?h2h=42-50) | collected_at(2026-08-15T21:22:20+08:00)
> 证据缺口：未获得双方当前赛季可比的近 5 场状态与 xG。

## 4. 主客/旅行/天气
- API-Football 赛事身份显示场地为 Principality Stadium, Cardiff，不是阿森纳或曼城常规主场，因此不应赋予常规主场优势 | source(https://v3.football.api-sports.io/fixtures?id=1582365) | collected_at(2026-08-15T21:22:20+08:00)
> 证据缺口：未核实开球时天气与球场状况。

## 5. 赔率
- 中国体彩官方实时重拉取的 HAD 赔率为主 2.37 / 平 3.17 / 客 2.55，采集时对应赛事仍在售 | source(https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry?clientCode=3001&matchId=2040898) | collected_at(2026-08-15T21:22:20+08:00)
- 官方返回的赔率最后变更时间为 2026-08-14 09:47:33；本次重拉取确认该值在 2026-08-15 21:22 仍可见，不把“最后变更”误当“采集时间” | source(https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry?clientCode=3001&matchId=2040898) | collected_at(2026-08-15T21:22:20+08:00)

## 6. 身份核验
- 体彩场次 sporttery-2040898（周日011）为阿森纳 vs 曼城，开球 2026-08-16T22:00:00+08:00 | source(https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry?clientCode=3001&matchId=2040898) | collected_at(2026-08-15T21:22:20+08:00)
- 独立 API-Football 场次 1582365 同样显示 Arsenal vs Manchester City、Community Shield Final、同一开球时间，双源对阵与时间一致 | source(https://v3.football.api-sports.io/fixtures?id=1582365) | collected_at(2026-08-15T21:22:20+08:00)

## 证据缺口
> 伤停/首发、教练言论、近期 xG 与天气未获得可靠双源验证。LLM 必须设置 evidence_gap=true；所有方向只是定性对比，不得输出或冒充校准概率。
