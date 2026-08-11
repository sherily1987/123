# 韩职数据获取与样本积累 SOP

## 1. 数据现状（2026-08-02）

| 数据集 | 场次 | 来源 | 赛季 |
| --- | --- | --- | --- |
| K League 1 赛果 | 2,468 | FBref（2014–2021 共 1,772）+ API-Football（2022–2024 共 696） | 2014–2024 |
| K League 2 赛果 | 694 | API-Football | 2022–2024 |

合并文件：`04_素材/标准化/k_league_1_2_results_2014_2024.csv`
字段：`competition, season_end_year, date, home, away, home_goals, away_goals, status, source`

## 2. 一次性补历史数据

脚本：`02_脚本/fetch_k_league_apifootball.py`（复用 project007 的 api_football_adapter）

- key 从环境变量 `API_FOOTBALL_KEY` 读取；
- 每个 (联赛, 赛季) 只调 1 次 `/fixtures`（返回整季全部场次）；
- 自动断点续传：raw JSON 已存在且含数据则跳过；
- 默认 7 秒/请求（免费版 10 次/分钟限流）。

```powershell
python 02_脚本\fetch_k_league_apifootball.py              # k1+k2, 2022-2024
python 02_脚本\fetch_k_league_apifootball.py --delay 0     # 已拉过时快速重合并
```

注意：免费版只开放 2022–2024 赛季；加新赛季改脚本内 `SEASONS` 后重跑即可（幂等）。

## 3. 每日流水线自动覆盖韩职

fusion 引擎 `daily-pipeline --kickoff-date YYYY-MM-DD` 按开球日期采集体彩全盘口，
韩职是竞彩常开赛事，**自动包含在采集范围内，无需改代码**。每轮韩职约 6–9 场开售、
日更 1–3 场；持续跑流水线即可积累"体彩赔率+赛果"配对样本。

## 4. 样本跟踪与门槛

```powershell
python C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\sample_audit.py `
  --league 韩职 --output H:\claude AI自媒体\project004_韩国联赛历史数据下载\04_素材\k_league_sample_audit.json
```

门槛（融合引擎硬规则）：已结算样本 ≥100 场才重校准，≥200 场才阈值复审；
样本 <200 不宣称优于市场。

2026-08-02 基线：韩职登记 5 条（3 场唯一比赛），settled=0，远未达门槛；
按日更 1–3 场估算，攒到 100 场约需 3–6 个月。

## 5. 口径提醒

- 回测配对样本必须来自体彩登记链（官方赔率 + 官方赛果）；API-Football 是博彩公司口径，
  只能用于赛果/强度建模，不能替代体彩盘口。
- 数据文件全部保留在项目文件夹内（raw JSON 在 `04_素材/apifootball_raw/`）。
