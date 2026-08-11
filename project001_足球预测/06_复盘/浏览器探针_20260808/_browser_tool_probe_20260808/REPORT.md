# 网页抓取能力实测（换用 Hermes 内置 browser）2026-08-08

## 你问的「另一个技能」是什么？

本环境里和「抓网页」相关的有多层，**不是只有 agent-browser**：

| 名称 | 类型 | 状态 | 说明 |
|---|---|---|---|
| **Hermes 内置 `browser_*`** | 会话工具 | ✅ **本次实测可用** | `browser_navigate` / click / snapshot |
| **dev-browser** | CLI 技能（football-evidence 文档） | ⚠️ 本机装了但 daemon 易卡住 | Playwright；你之前推荐装的那个 |
| **agent-browser** | 刚装的 Vercel CLI | ⚠️ 部分站 open 超时 | CDP + @eN |
| **web_extract / web_search** | 工具 | ✅ 可用 | 非完整浏览器，适合静态/API 页 |
| football-evidence-collection | 流程技能 | ✅ | 规定用哪些源，不负责开浏览器 |

**结论：现在最稳的是 Hermes 内置 browser 工具**（不是 agent-browser / dev-browser CLI）。

---

## 实测对照（以前 curl 常失败 / 只能骨架）

| 站点 | curl | Hermes browser | 抓到的有效信息 |
|---|---|---|---|
| **jleague.jp**（JS 站，以前 curl 骨架） | visible~4.6k，多为 Loading/壳 | ✅ 成功 | 比分：横滨3-4鹿岛、钢巴4-3浦和等；积分榜；**伤停新闻标题**「Gamba Osaka Announce Injuries to DF Miura and MF Okunuki」 |
| **antlers.co.jp** 鹿岛官网 | curl 有部分文本 | ✅ 成功 | **J联第2节 08.15 18:00 vs 名古屋（メルスタ）**；开幕战4-3逆转；新闻列表 |
| **flashscore.com** | curl 有首页文本 | ✅ 成功 | 大量实时赛程/联赛列表（荷甲 Nijmegen-Telstar 等） |
| **transfermarkt.com** | 维护页 Maintenance | （未深测） | curl 已是维护页 |
| **sofascore.com** | **403 Forbidden JSON** | 待测 | curl 完全被拒 |

---

## 关键发现（对足球证据有用）

从 **jleague.jp** 浏览器快照直接读到：

1. **赛果**：Yokohama F.Marinos 3-4 Kashima Antlers；Gamba Osaka 4-3 Urawa Reds  
2. **伤停线索**：Gamba Osaka 宣布 DF Miura、MF Okunuki 伤停（2026-08-08）  
3. **积分榜**：Machida 3分领跑；鹿岛/钢巴各 3 分  

从 **鹿岛官网** 读到：

1. 主场「メルスタ」  
2. **第2節 8/15 18:00 vs 名古屋**（与之前证据技能里的轮次判定一致）  
3. 开幕战 1-3 落后翻成 4-3  

→ **以前 curl 说「J联官网只有骨架」的问题，用内置 browser 已经解决。**

---

## 实操建议（以后抓证据）

1. **默认用 Hermes `browser_navigate`**，不要先折腾 agent-browser/dev-browser CLI（两者本机都容易卡）。  
2. curl 仍优先打：体彩 API、维基、wttr.in、部分球迷站。  
3. JS 站 / 俱乐部官网 / Flashscore → **browser**。  
4. Sofascore / 强 Cloudflare → 仍可能失败，换源。  
5. agent-browser / dev-browser：仅当内置 browser 不够用时再试，且必须先 `unset` 代理、短超时。

## 产物目录

`F:/HM足球比赛预测/_browser_tool_probe_20260808/`
