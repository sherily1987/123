# 中国体彩网移动端官方接口（足彩采集）

数据源：中国体育彩票竞彩足球移动端官方链路（`https://m.sporttery.cn/mjc/zqsj/`），全部接口走 `webapi.sporttery.cn/gateway`。无 API Key，模拟移动端 UA 即可访问；数据即体彩官方在售赔率与赛果，是竞彩回测与预测的权威口径。

## 端点清单

| 端点 | 作用 | 方法 |
| --- | --- | --- |
| `/uniform/fb/getConditionsV1.qry` | 查询可采集的日期范围（`startDate` / `endDate`） | GET |
| `/uniform/fb/getMatchDataPageListV1.qry` | 按日期拉取赛程/赛果场次列表（method: all/concern/result） | GET |
| `/uniform/football/getFixedBonusV1.qry` | 按 `matchId` 拉取单场固定奖金全盘口（HAD/HHAD/CRS/TTG/HAFU） | GET |

## 请求头

```http
User-Agent: Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/134 Mobile Safari/537.36
Referer: https://m.sporttery.cn/mjc/zqsj/?tab=concern   # 采赛果时可用 ?tab=result
Accept: application/json,text/plain,*/*
```

## 关键参数

### getMatchDataPageListV1.qry

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `method` | `all` / `concern` / `result` | 关注页 / 全部在售 / 赛果（result 返回含比分字段） |
| `matchDate` | `YYYY-MM-DD` | 查询日期（赛果/开球日期口径） |

返回体：`value.matchInfoList[]` 按天分组，`subMatchList[]` 为场次；关键字段：
`matchId`、`matchNumStr`（如 周二002）、`matchDate`+`matchTime`（开球）、`businessDate`（销售日）、`leagueAbbName`、`homeTeamAbbName`/`awayTeamAbbName`、`matchStatusName`、`sectionsNo1`（半场）、`sectionsNo999`（全场90分钟）。

### getFixedBonusV1.qry

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `clientCode` | `3001` | 固定客户端码 |
| `matchId` | 数字 | 来自列表接口的官方场次 ID |

返回体：`value.oddsHistory` 为各玩法赔率历史，含：
`hadList`（胜平负 H/D/A）、`hhadList`（让球胜平负，含 `goalLine`）、`crsList`（比分）、`ttgList`（总进球 0-7+）、`hafuList`（半全场九宫格）；另有 `team_ids` 相关字段与 `matchResultList`/`sectionsNo999`（赛果）。

## 玩法字段速查

| 玩法 | 字段 | 解析 |
| --- | --- | --- |
| 胜平负 HAD | `hadList` 末行 h/d/a | 三态赔率 |
| 让球胜平负 HHAD | `hhadList` 末行 h/d/a + `goalLine` | 三态赔率 + 让球数（注意：非亚洲盘两态） |
| 比分 CRS | `crsList` 末行 `sHHssAA` 键 | 如 `s11s00` → `1-0`；`s-1sh/s-1sd/s-1sa` → 胜/平/负其他 |
| 总进球 TTG | `ttgList` 末行 `s0`~`s7` | 0-6 档 + `7+` |
| 半全场 HAFU | `hafuList` 末行 `hh/hd/ha/dh/dd/da/ah/ad/aa` | 九宫格 |

## 限速与纪律（重要）

- 逐场固定奖金请求必须限速：默认间隔 `1.5s`，历史回补单场 0.2–0.55s 随机抖动，并发不超过 8。
- 收到 HTTP `403/429/567` 立即停止（脚本会抛出 `STOP_HTTP_*`）。
- 优先低频调用、按 `matchId` 去重；禁止调用任何已废弃的 PC/计算器接口。
- CRS 赔率只作相对排序，不直接归一化为概率；HHAD 是官方三态池，不要当作亚洲盘两态线。
- 未完成场次 `score_90` 为 null，不得臆补赛果。

## 脚本用法速查

```bash
# 1) 核心采集器：按开球/销售日期拉全盘口
python fetch_sporttery_full.py --date 2026-08-05 --method all --output raw.json --delay 1.5

# 2) 核心采集器：只采赛果
python fetch_sporttery_full.py --results --date 2026-08-05 --output results.json

# 3) 批量采集（新规则：按开球日期分组）
python sales_day_collect.py --kickoff-date 2026-08-05 --output raw_kickoff.json --delay 1.5

# 4) 批量采集（旧口径：按销售日编号，如 周二001 前缀）
python sales_day_collect.py --sales-day 2026-08-04 --sales-label 周二 --output raw_salesday.json

# 5) 历史回补（断点续传，按 matchId 去重）
python fetch_sporttery_history_all.py --start 2024-01-01 --end 2024-12-31 --output hist.json --workers 3
```
