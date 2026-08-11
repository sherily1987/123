# 数据采集手册

顺序：官方/主源直连 → 可信备源 → 无验证码搜索 → 用户截图OCR → `UNAVAILABLE`。

| 字段 | 主源 | 备源 |
|---|---|---|
| 赛程/规则/系数 | UEFA | 官方联赛、football-coefficient |
| Elo | ClubElo | FootballDatabase等，标差异 |
| 身价/名单 | Transfermarkt | 俱乐部官网 |
| 伤停/首发 | 俱乐部官方、FotMob | Sofascore、可靠媒体 |
| xG/比赛统计 | FBref | Understat、FotMob、Sofascore |
| 天气 | Open-Meteo | 当地气象/FotMob |
| 赔率 | **中国体彩网官方竞彩接口**（竞彩场次优先）、sgodds（整轮1X2）、betherosports（Pinnacle尖锐盘） | 用户截图、oddspedia、oddstorm、sofascore |

## 中国体彩网官方竞彩接口（竞彩场次优先）

- 移动端赛程页：`https://m.sporttery.cn/mjc/zqsj/?tab=concern`
- **唯一采集链路（移动端 webapi）**：
  - `https://webapi.sporttery.cn/gateway/uniform/fb/getConditionsV1.qry?method=concern`：日期范围、赛事列表；
  - `https://webapi.sporttery.cn/gateway/uniform/fb/getMatchDataPageListV1.qry?method=concern&matchDate=YYYY-MM-DD`：赛程、竞彩编号、状态、HAD、`matchId`；
  - `https://webapi.sporttery.cn/gateway/uniform/football/getFixedBonusV1.qry?clientCode=3001&matchId=...`：HAD、HHAD、CRS、TTG、HAFU及赔率历史。
- 已删除/禁止：任何 PC 计算器接口、旧 `fetch_sporttery.py` / `sporttery_to_input.py`、以及 `getMatchCalculatorV1.qry`。不得重试、不得作为回退。
- 体彩发布的赛程、赛果、销售状态和固定奖金属于官方数据，可作为高可靠信息源；`bssj`统计页明确提示部分数据来自第三方，历史交锋、积分、近况、球员和伤停应标`SPORTTERY_DISPLAYED_THIRD_PARTY`，可靠性低于官方赔率。
- 赛程页不仅用于未来竞彩：将`method`切换为`result`或`all`并配合`matchDate`、分页参数，可采集已完成比赛的官方赛果/比分；列表中的`sectionsNo1`、`sectionsNo999`、`sectionsPenalty`分别保留阶段、全场及点球信息，具体语义以接口返回和页面显示交叉核验。赛后建库优先保存90分钟比分，额外时间和点球必须分字段，禁止混入90分钟模型标签。
- “赛果开奖”列表下拉区还展示各玩法的**开奖项与对应固定奖金**：HAD赛果+奖金、HHAD让球线/赛果+奖金、CRS赛果+奖金、TTG赛果+奖金、HAFU赛果+奖金。它适合构建历史市场基线与ROI/命中回测，但页面单值通常是中奖选项奖金，不等于完整三项/全盘口收盘快照；若要重建赛前公平概率，必须用该场`matchId`调用`getFixedBonusV1`保存完整且带发布时间的最后一版赛前赔率。严禁把赛后开奖结果或中奖项泄漏到赛前特征。
- 单场历史交锋和近期比分走 `getResultHistoryV1` 与 `getMatchResultV1`；它们是体彩页面展示的第三方统计，用于低权重状态特征，不得与竞彩官方赛果或市场赔率等权。
- HAD/HHAD基础采集脚本：
  ```sh
  python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/fetch_sporttery_full.py --date YYYY-MM-DD --output /path/raw_sporttery.json --emit-input /path/model_input.json
  ```
- 完整全盘口采集脚本（CRS、TTG、HAFU及HAD/HHAD）：
  ```sh
  python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/fetch_sporttery_full.py --date YYYY-MM-DD --output /path/raw_sporttery_full.json --emit-input /path/model_input.json
  ```
  支持`--date`、`--match-num 周四001`、`--match-id 1234567`筛选；逐场请求默认间隔1.5秒。赛果快速采集用`--results --date YYYY-MM-DD`，不会逐场拉赔率。
- 字段：`HAD`=非让球胜平负；`HHAD`=让球胜平负；`h/d/a`=主胜/平/客胜；`goalLine`=体彩让球数。
- 只有`HAD`三项均非空时，才能按 `[h,d,a]` 写入模型`odds`。缺项标`UNAVAILABLE`，不得拿HHAD补成普通1X2。
- `HHAD`是三项让球胜平负：负让球时，让胜/让平/让负分别对应让球后主胜/平/负；**不等同二项亚洲盘赔率**。可用于比分差交叉验证，不能直接写入`ah_line`赔率模型。
- 必须保存：`matchId`、`matchNumStr`、球队全名、开球时间、`matchStatus`、`sellStatus`、`lastUpdateTime`、接口URL和采集时间。
- 仅`matchStatus=Selling`且对应pool为`Selling`时视为在售快照；`Define/OddsIn`仅作预告，不作为正式临场赔率。
- 体彩通常为高边际单一来源：先去水，并报告庄家边际；最好再与一个市场源交叉验证。
- 官方接口可直接访问时优先于OCR；用户截图用于核对页面显示、接口缺项或历史留档。

验证码：请用户在当前标签完成；不绕过。Google拦截不等于无数据，至少尝试两个备源。

OCR：截图数字标`IMAGE_EXTRACTED`；关键数值放大并交叉核对。模糊值列候选，不猜测。

每个字段记录URL/页面名、采集时间、数据日期、来源等级、状态。缓存必须检查有效期，禁止复用过期缓存而不标注。

推荐可信度：官方/UEFA/ClubElo/FBref/Open-Meteo=5；FotMob/Sofascore/Transfermarkt/Understat=4；ESPN/BBC/Sky=3；综合媒体=2；社媒论坛=1。

## 中国体彩全盘口采集（移动端官方链路）

按日期调用 `getMatchDataPageListV1.qry` 获得`matchId`，再逐场低频调用 `getFixedBonusV1.qry`。`getMatchCalculatorV1.qry` 已因持续 HTTP 567 停用。单场固定奖金接口包含 HAD/HHAD 及三个扩展盘：

| 盘口 | 内容 | 用途 |
|---|---|---|
| HAD | 非让球胜平负 | 主强度锚 |
| HHAD | 三项让球胜平负 | 净胜球约束 |
| **CRS** | 28个正确比分赔率 | 比分分布交叉验证 |
| **TTG** | 总进球 0~7+ 共8档 | **反推 goal_total（关键）** |
| **HAFU** | 半全场9种组合 | 节奏预期参考 |

⚠️ `getMatchDataPageListV1.qry` 主要负责赛程、赛果、HAD和`matchId`；CRS/TTG/HAFU必须按`matchId`从 `getFixedBonusV1.qry` 获取。不得回退到已停用的计算器总接口。

### TTG 反推 goal_total（实测有效）

TTG 覆盖 0~7+ 完整样本空间，可正确去水；用去水概率算期望总进球，作为 `goal_total` 输入：

```
goal_total = Σ (球数 × 去水概率)，7+ 档按 7.5 计
```

**实测收益**（2026-07-31 三场）：默认 `goal_total` 偏低导致大2.5概率低估 13~15pp；改用 TTG 反推值后偏差收窄至 2~3pp，Top比分也与市场对齐。有 TTG 时**必须**用此法，不得沿用赛事默认表。

⚠️ CRS 只列 28 个具体比分，其余归"胜其他/平其他/负其他"，**样本空间不完整，不可直接归一化去水**；只能做比分间相对排序比较，或以 TTG 去水结果为总量基准分配。

## 赔率快速采集（实测优先级）

hybrid 模式需真实 1X2 赔率。按以下顺序取，可最快拿全：

1. **sgodds.com/football/current-odds** —— 首选。一页列出未来数日全部赛事的 1X2 开盘/即时赔率（新加坡博彩正规盘，接近体彩口径），含大小球/亚盘/比分盘。直接 `get_text` 整表提取，一次拿全整轮多场，无需逐场点。URL 规律：`sgodds.com/football/current-odds/<Home>-vs-<Away>-<编号>` 是单场详情页（含比分盘/BTTS/半场盘）。
2. **betherosports.com/odds/soccer/<赛事>/<home>-vs-<away>/<id>** —— 取 **Pinnacle / bet105**（尖锐盘、低水钱），聚合 300+ 庄家，适合要低 margin 参考盘时用。整表 `get_text`，搜 "Pinnacle" 行拿主/平/客。
3. **ClubElo 历史/即时** —— `api.clubelo.com/<YYYY-MM-DD>` 用 curl 拉当日全欧 CSV（`add_elo.py` 亦用此），一次拿全部球队 Elo，避免逐队开页。
4. 备源：oddspedia、oddstorm（单场1X2对比）、sofascore；或用户体彩截图 OCR。

取赔率时记录：庄家名（如 Pinnacle）、开盘/即时、采集时间、`bookmaker_margin`（水钱）。尖锐盘（Pinnacle）优先于软盘。singapore pools 盘与国内体彩口径接近，可作体彩代理。

首回合比分（次回合双回合需）：**365Scores 的赛事 Results 区一次列全整轮**（`365scores.com/football/league/<赛事id>`），或 ESPN match 页、worldfootball。

