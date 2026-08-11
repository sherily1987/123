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
| 赔率 | 用户截图/多庄家 | 单一来源须注明边际与时间 |

验证码：请用户在当前标签完成；不绕过。Google拦截不等于无数据，至少尝试两个备源。

OCR：截图数字标`IMAGE_EXTRACTED`；关键数值放大并交叉核对。模糊值列候选，不猜测。

每个字段记录URL/页面名、采集时间、数据日期、来源等级、状态。缓存必须检查有效期，禁止复用过期缓存而不标注。

推荐可信度：官方/UEFA/ClubElo/FBref/Open-Meteo=5；FotMob/Sofascore/Transfermarkt/Understat=4；ESPN/BBC/Sky=3；综合媒体=2；社媒论坛=1。
