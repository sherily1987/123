---
type: data-contract
provider: apifootball.com
api_version: v3
updated: 2026-08-12
---

# APIfootball数据契约

## 接口与用途

| 接口 | 用途 | 当前限制 |
|---|---|---|
| `get_football_matches` | 比赛列表（赛程/结果） | 需 date_from/date_to；kickoff_utc 带时区 |
| `get_match_details` | 单场详情（球场/主裁/轮次/lineups） | 首发可能为空=未发布 |
| `get_head_to_head` | 历史交锋 + 双方近5场 | 不收 match_id，传 team1_name/team2_name 或 id |
| `get_football_standings` | 积分榜 | 请求时榜单，历史需快照 |
| `get_football_odds` | 真实博彩赔率（1X2/BTTS/O-U2.5） | 只进入市场层和CLV研究 |
| `get_football_predictions` | 官方数学预测概率 | 保存为 `p_apifootball`，不是xG |
| `get_football_topscorers` | 射手榜 | ⚠️ 当前套餐权限受限 |

## 时间规则

```text
collected_at < kickoff
```

才可以作为当前比赛赛前数据；带时区 offset，无 offset 不猜测。否则状态必须是 `POST_MATCH_NOT_USABLE`。

## xG规则

APIfootball 统计中没有稳定 xG 字段：`Shots Total ≠ xG`，`prob_HW/prob_D/prob_AW ≠ xG`。轨道A 的 `goal_rate` 是 `proxy_lambda`（MULTI_MARKET_XG 多市场反解），不等于事件 xG。

## 三家数据服务商勿混

```text
football-data.org  → X-Auth-Token
api-sports.io     → x-apisports-key
apifootball.com   → APIkey query 参数（当前会员key）
```

## ⚠️ 已知数据分裂（2026-08-12 更新）

1. **registry.jsonl（预测登记库）**：~~仓库内 1550 vs 外部 1555，差 8 条~~ **已合并（2026-08-12）**——`merge_registry_gap.py` 将 8 条（`sporttery-2040812~2040818、2040830`）按正规哈希链重算并入仓库内，现 **1558 条**，整链验证通过（备份 `registry.jsonl.bak_20260812_merge8`）。
2. **production_movement.jsonl（赔率移动）**：`fusion_daily_pipeline.py` 的 STORE/ODDS_STORE/WORK 仍硬编码指向外部套件，而 `FUSION_DATA_ROOT` 配置的是仓库内路径。外部副本（926KB，写到 08-12 09:00）比仓库内（753KB，到 08-11 10:00）更新更大。**合并/确认权威来源前，不要改这三个路径**。

## 洲际赛事数据可用性（2026-08-12 实测）

### ⚠️ 韩职/日职数据源真相（2026-08-12 查明）

- **fd_kor_events.jsonl 是坏数据，已隔离**：31 支"球队"全是挪威联赛队名（Molde/Rosenborg/Aalesund…）。根因：football-data.co.uk 的 `new/KOR.csv` 请求被服务器**重定向到 NOR.csv**（该站根本没有韩职文件），当初下载时把挪威数据当韩职入库。已移至 `project021/04_素材/corrupt_data_quarantine/`，README 记录了根因。此前"韩 K1 695 场 +0.0290"回测成绩实为挪威数据，**无效**。
- **韩职当前无任何可行数据源**：football-data.co.uk 无韩职（KOR.csv→NOR.csv、K1.csv 300 Multiple Choices）；apifootball 套餐无韩职（count=0）；fbref 有 K League 1（comps/55）但 Cloudflare 拦截不可爬（curl/Crawl4AI/Playwright 4 种方式实测全失败）。
- **日职 fd_jpn 数据正确**：真实 J1 球队（浦和/鹿岛/大阪钢巴等），4523 场 2012-2025，赛果+收盘赔率，与 football-data `new/JPN.csv` 逐场一致；无 xG（走"无 xG"训练路径，实测 +0.0178 跑赢收盘线）。
- 其余 fd_* 已核验无污染：fd_e1=英冠、fd_f2=法乙、fd_bra=巴甲、fd_arg=阿甲。

### 洲际/无源赛事矩阵

| 赛事 | 体彩盘口 | apifootball | 训练轨模型 | 跨联赛标尺 | 可用路径 |
|---|---|---|---|---|---|
| 欧冠/欧罗巴/欧协联 | ✅ | ✅ | ❌ 按设计不训练 | ✅（-0.0706 改善） | market_only 或标尺 |
| 欧超杯 | ✅ | ✅ | ❌ | ✅（PSG vs 维拉实测 λ1.15:1.28） | market_only 或标尺（C档降级） |
| 解放者杯 | ✅ | ✅ 联赛有 | ❌ 南美联赛不在训练集 | ❌ 无偏移表 | **仅 market_only** |
| 亚冠精英 | ✅ 五盘口齐全 | ❌ count=0 | ❌ | ❌ 无 J/K 联赛偏移 | **仅 market_only**（实测江原FC vs 大阪钢巴通过） |
| 沙职 | ✅ | ❌ | ❌ | ❌ | 仅 market_only |

要点：
- **亚冠精英实测可用**（2026-08-11 江原FC vs 大阪钢巴）：体彩 HAD [2.73,3.05,2.3] 五盘口 → fusion market_only 正常输出（λ0.905/1.085、Top比分0-1/1-1/0-0、大2.5 32.5%）。本地快照库已有 `by_league/亚冠精英.jsonl`。
- **所有洲际赛事只给 market_only 基线**（市场依赖100%），无独立模型；体彩未开售场次无法算基线。
- apifootball 队名注意：法甲用 `PSG`、英超 `Aston Villa`（非 Paris Saint Germain）。

## MCP 与 Crawl 证据层（2026-08-11 起）

- MCP 是第三方结构化数据，只能作主证据独立过门禁后的补充；sidecar 需 `match_identity(...)` 与体彩ID、主客队一致。
- Crawl4AI（`project018_技能工作区整合/02_脚本/llm/football-llm-predictor/crawl_evidence.py`，2026-08-16 从 C 盘迁入仓库）只采官方/已知可信 JS 网页快照，`url`/`final_url` 同 hostname（仅容忍 www.），每类实质事实至少2个独立域名，默认不覆盖已有主证据。详见同目录 `CRAWL4AI_EVIDENCE.md`。
- 网页全文只存快照，禁止整页投给 LLM。

## 事实源

- 适配器：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_adapter.py`
- 特征构建：`C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\apifootball_model_features.py`
- 数据契约：`C:\Users\Administrator\.codex\skills\football-quant-fusion\references\data_contract.md`
- MCP 查询器：`project001_足球预测\02_脚本\mcp_query.py`（C盘 `mcp_evidence.py` 依赖此路径）
