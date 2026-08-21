# Crawl4AI 赛前证据采集接入

## 定位

`crawl_evidence.py` 是网页证据采集器，不是预测器，不替代体彩 raw、apifootball 或 `predict.py`。

**以后每场的首发 / 伤停 / 近 5 场一律走 20 源投票**，标准见 `EVIDENCE_COLLECT.md`。投票结果就是可用数据，不再等官方名单。封锁源占槽不采正文。本文件只约束「怎么取页和验证」，不改计票规则。

```text
来源清单 → Crawl4AI 或 Playwright 快照 → 身份/时间/关键词验证 → 跨域门槛 → 主证据 → predict.py
```

网页全文只保存于快照，**不直接拼入 LLM prompt**。进入 `evidence_NNN_*.md` 的只能是来源清单中人工声明、且确实出现在该网页快照中的事实。

## 运行环境

Crawl4AI 装在项目虚拟环境：

```bash
cd /c/Users/Administrator/football-llm-predictor
.venv/Scripts/python.exe crawl_evidence.py --help
```

不要用 Hermes 的 `python` 运行实际抓取；普通 pytest 不依赖 Crawl4AI。

## 来源清单契约

来源清单按比赛日期放在 `data/crawl_sources_YYYY-MM-DD.json`。每条来源必须绑定体彩 `match_id`，并声明英文主客队全名、来源等级和待验证事实：

```json
{
  "sources": [
    {
      "sporttery_match_id": 2040829,
      "url": "https://official.example/match",
      "source_level": "official_competition",
      "canonical_home": "Kairat Almaty",
      "canonical_away": "Levski Sofia",
      "facts": [
        {
          "section": 2,
          "text": "官方页面确认本场为第三资格赛第二回合。",
          "required_terms": ["Third qualifying round", "2nd leg"]
        }
      ]
    }
  ]
}
```

- `section` 只能是 1～6，对应既有六类主证据标题。
- `text` 是要写入证据的事实；它不是模型生成内容。
- `required_terms` 中每个词必须真实出现于 Crawl4AI 抓取的标题或 Markdown。
- 网页必须同时出现 `canonical_home` 与 `canonical_away`；仅有联赛、时间或单队名不会通过。
- 来源 URL 与抓取后的 `final_url` 必须是同一 hostname（仅容忍 `www.` 差异）；跨域重定向页面不会继承原来源的官方等级。
- 页面抓取时间、来源已声明的发布时间（若后续接入）都必须早于 `kickoff_iso`；无时区时间不猜测。

## 采集命令

只抓取并保存快照：

```bash
.venv/Scripts/python.exe crawl_evidence.py \
  --input data/raw_YYYY-MM-DD.json \
  --sources data/crawl_sources_YYYY-MM-DD.json \
  --snapshot-dir data/crawl_snapshots \
  --match-id <体彩match_id>
```

五大联赛官网 / 媒体预览等 JS 页改用 Playwright 取页（验证门槛不变）：

```bash
.venv/Scripts/python.exe crawl_evidence.py \
  --engine playwright \
  --input data/raw_YYYY-MM-DD.json \
  --sources data/crawl_sources_YYYY-MM-DD.json \
  --snapshot-dir data/crawl_snapshots \
  --match-id <体彩match_id>
```

JS 场次页（如 ESPN match）需要强制渲染时加 `--browser-only`。

`--engine playwright` 调用 `playwright_fetch.py`：默认先纯 HTTP，只有骨架页才开 Chromium。人机验证和 403 记缺口，不绕过。

快照写入：

```text
data/crawl_snapshots/YYYY-MM-DD/<体彩match_id>/<url_hash>.json
```

每份快照保留 `sporttery_match_id`、中英文队名、`kickoff_iso`、原始/最终 URL、来源级别、抓取时间、正文哈希和 Markdown；不保存 cookie、浏览器会话或凭据。

## 主证据写入保护

只有显式指定 `--write-primary` 时才尝试生成主证据：

```bash
.venv/Scripts/python.exe crawl_evidence.py \
  --input data/raw_YYYY-MM-DD.json \
  --sources data/crawl_sources_YYYY-MM-DD.json \
  --snapshot-dir data/crawl_snapshots \
  --evidence-dir data/evidence_YYYY-MM-DD \
  --write-primary
```

写入前强制条件：

1. 六类栏目每类至少有两个不同 hostname 的已验证来源；
2. 每条事实都有 `source(...)`、带 offset 的 `collected_at(...)`；
3. 当前场次目录内不存在主证据文件；存在则拒绝覆盖；
4. `_mcp.md` 不是主证据，不能替代这套门槛。

因此，`insufficient_independent_sources:N` 是预期的安全拒绝，不是网络失败。补齐来源清单后重新运行即可；不得通过删减栏目、复用同域页面或降低关键词条件来绕过。

## 来源优先级与边界

1. 俱乐部、赛事、联赛官方页面：Crawl4AI 的首选目标；
2. 第三方媒体：仅作交叉验证，必须明确 `source_level`；
3. 体彩赔率：继续使用 raw/API，不用网页爬虫替代；
4. 结构化首发、交锋、外盘：继续走 `mcp_evidence.py` / apifootball，并保持第三方数据标签；
5. 验证码、登录、付费墙或赛后更新：不得绕过；记录失败或缺口。
