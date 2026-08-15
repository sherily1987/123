赛事：西甲（体彩官方场次）
竞彩编号：周日022
主队：西班牙人（短名西班牙人）
客队：莱万特（短名莱万特）
开球：2026-08-17T01:00:00+08:00
量化模型档位：B (market)
收集时刻：2026-08-15T15:17:15+08:00

## 1. 伤停/阵容
- 体彩官方接口无伤病/大名单字段，赛前官方首发与伤员名单尚未公布 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
> 说明：轻量证据未做伤停新闻深度搜索；以赛前官方名单为准。

## 2. 战意/动机
- 本场为竞彩周日022场次，西甲在售未开球场次之一，开球时间 2026-08-17T01:00:00+08:00 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
> 说明：轻量证据未抓取教练/球员赛前言论与轮次背景。

## 3. 近况/状态
- 量化 Dixon-Coles 模型覆盖标注：西甲 档位 B (market)（见 full_backtest.json 滚动回测） | source(file://F:/HM足球比赛预测/project021_五大联赛APIFootball训练/05_交付/full_backtest.json) | collected_at(2026-08-15T15:17:15+08:00)
> 说明：轻量证据未抓取双方近 5 场战绩；可上传深度证据覆盖本文件。

## 4. 主客/旅行/天气
- 主队 西班牙人 主场作战，客队 莱万特 客场远征（体彩官方对阵口径） | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
> 说明：轻量证据未抓取天气/旅行距离。

## 5. 赔率
- 体彩官方胜平负即时赔率：主1.85/平3.18/客3.65 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
- 赔率异动（初盘→即时）：主1.80→1.85 / 平3.20→3.18 / 客3.85→3.65 | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
> 说明：外部盘口（欧赔）未抓取。

## 6. 身份核验
- 体彩官方全名：主队"西班牙人"、客队"莱万特" | source(http://webapi.sporttery.cn/gateway/uniform/fb/getFixedBonusV1.qry?clientCode=3001&matchId=2040907) | collected_at(2026-08-15T15:17:15+08:00)
- 联赛：西甲（体彩联赛名口径）；开球时间 2026-08-17T01:00:00+08:00 与体彩列表接口一致 | source(https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry) | collected_at(2026-08-15T15:17:15+08:00)

## 证据缺口
> 说明：轻量证据自动生成（project023）：①伤停/首发名单未发布且未深度搜索；②双方近况/轮次背景未抓取；③天气/旅行距离未抓取；④外部欧赔未抓取。可上传深度证据覆盖后重跑预测。