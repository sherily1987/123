# ⚽ 多LLM足球比分预测系统 (多服务商免费模型版)

## 快速开始

### 1. 获取 API Key (免费)
系统使用多个免费 LLM 服务商，全部免费无需付费：
1. **智谱** (https://open.bigmodel.cn) — `ZHIPU_API_KEY`，glm-4-flash 完全免费无限量
2. **千问/阿里云百炼** (https://bailian.console.aliyun.com) — `DASHSCOPE_API_KEY`，qwen-flash 完全免费无限量
3. **Groq** (https://console.groq.com) — `GROQ_API_KEY`，需代理
4. **Moonshot/Kimi** (https://platform.moonshot.cn) — `MOONSHOT_API_KEY`
5. **Google Gemini** (https://aistudio.google.com) — `GOOGLE_API_KEY`，需代理
6. **火山方舟/豆包** (https://console.volcengine.com/ark) — `ARK_API_KEY`，需控制台开通模型

### 2. 设置环境变量

密钥只从环境变量读取，**不写进任何文件**（含本 README）。

```bash
# bash / git-bash
export ZHIPU_API_KEY=<你的key>

# Windows PowerShell
$env:ZHIPU_API_KEY="<你的key>"

# 或直接写入 Windows 用户环境变量(长期有效)
setx ZHIPU_API_KEY "<你的key>"
```

> 2026-08-16 更正：此处原本写着 `「redacted:…」`——那是某次会话把工具层遮蔽后的输出
> 写回了文件，不是真实密钥，但会让人照着复制出错。

### 2.5 环境重建（2026-08-16 迁移后必读）

本工程于 2026-08-16 从 `C:\Users\Administrator\football-llm-predictor`
迁入仓库。**`.venv` 与 `node_modules` 没有跟着拷过来**——虚拟环境里烧死了创建时的
绝对路径，直接拷贝到新位置是坏的。在新位置首次使用前重建：

```bash
cd "/f/HM足球比赛预测/project018_技能工作区整合/02_脚本/llm/football-llm-predictor"

# Python 虚拟环境（crawl_evidence.py 依赖 Crawl4AI，装在这里）
python -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip

# Node 依赖（build_ppt_*.js 生成 PPT 用）
npm install
```

日常 pytest 不依赖 `.venv`，用仓库通用解释器即可；只有实际跑 Crawl4AI 抓取才需要它。

### 3. 运行预测
```bash
cd football-llm-predictor

# 基本用法
python football_predictor.py "曼城" "利物浦"

# 带联赛和附加信息(近期状态、积分、伤停等)
python football_predictor.py "曼城" "利物浦" --league "英超" --extra "曼城近5场3胜2平, 利物浦客场2胜1平2负"

# 自定义模型列表
python football_predictor.py "皇马" "巴萨" --models google/gemma-4-31b-it:free openai/gpt-oss-20b:free

# 不调API, 用模拟数据演示(dry-run)
python football_predictor.py "曼城" "利物浦" --dry-run
```

## 工作原理
1. 每个模型独立收到相同的比赛信息，各自预测比分 + 置信度 + 理由
2. 7个模型并行调用（线程池），单个失败不影响整体
3. 聚合：比分众数投票 → 综合预测；赛果众数 → 综合赛果
4. 输出平均置信度 + 分歧度（分歧大 = 谨慎参考）

## 完整流水线：体彩采集 → 多LLM预测
配合足彩移动采集器（中国体彩官方移动端链路，零依赖零Key）使用：

```bash
# 2026-08-16：本工程已从 C:\Users\Administrator\football-llm-predictor 迁入仓库，
# 现位于 F:\HM足球比赛预测\project018_技能工作区整合\02_脚本\llm\football-llm-predictor。
# 下面用 $LLM 代指该目录。（旧文档里的 /h/claude AI自媒体 是已废弃的 H 盘路径。）
LLM="/f/HM足球比赛预测/project018_技能工作区整合/02_脚本/llm/football-llm-predictor"

# 1) 采集某开球日的比赛与官方全盘口（胜平负/让球/比分/总进球/半全场）
cd "/f/HM足球比赛预测/project015_足彩移动采集接口导出/02_脚本"
python fetch_sporttery_full.py --date 2026-08-05 --method all \
    --output "$LLM/data/raw_2026-08-05.json" --delay 1.2

# 2) 对采集到的每场比赛做多LLM预测（赔率作为参考输入, 证据驱动）
cd "$LLM"
python predict.py --input data/raw_2026-08-05.json --evidence-dir data/evidence_2026-08-05

# 2a) 自动加入最近5场、CRS/TTG/HAFU，并在T−75刷新伤停/首发
python mcp_evidence.py --input data/raw_2026-08-05.json \
    --out-dir data/evidence_2026-08-05 \
    --watch-refresh --refresh-before-minutes 75 --poll-seconds 60

# 2b) 生成报告 (Markdown + Excel)
python export_report.py data/predictions_2026-08-05.txt data/raw_2026-08-05.json

# 3) 赛后采集赛果，回测预测
python fetch_sporttery_full.py --results --date 2026-08-06 --output data/results.json
python backtest.py
```

watcher 在开球前会持续重试；只有 API-Sports 已给出首发或证据已满足首发条件时才停止刷新。旧 canonical 证据归档至 `snapshots/`，开球后禁止生成新的赛前证据。

`predict.py` 会把官方赔率（胜平负/让球/总进球/比分/半全场）+ 六类证据拼进每个模型的提示词，
模型参考赔率但保留独立判断；输出综合预测 + 官方赔率隐含概率对照。

## 证据源采集（2026-08-16 新增）

三个取数脚本，都**只采集不预测**，产出仍须走 `crawl_evidence.py` 门禁才能进主证据。

```bash
# 通用取页：先纯 HTTP，取不到才开浏览器；遇人机验证记缺口不绕过
.venv/Scripts/python.exe playwright_fetch.py --out-dir data/crawl_snapshots/manual \
    --url "https://www.transfermarkt.com/laliga/verletztespieler/wettbewerb/ES1"

# understat xG（五大联赛）。cutoff 必须带时区 offset
.venv/Scripts/python.exe understat_xg.py --league 西甲 --season 2025 \
    --team Espanyol --team Levante --cutoff "2026-08-17T02:00:00+08:00" \
    --out-dir data/xg_snapshots

# K League 官方数据：赛程（gameId 与队代码的来源）/ 积分榜 / 单场球员
.venv/Scripts/python.exe kleague_portal.py fixtures
.venv/Scripts/python.exe kleague_portal.py standings
.venv/Scripts/python.exe kleague_portal.py players --meet-year 2026 --meet-seq 1 \
    --game-id 133 --home-team K22 --away-team K03   # ⚠️ 赛后数据

# FotMob 联赛 JSON（understat 覆盖不到的联赛）。cutoff 必须带时区
.venv/Scripts/python.exe fotmob_league.py --list
.venv/Scripts/python.exe fotmob_league.py --league 日职 --cutoff "2026-08-17T02:00:00+08:00"
.venv/Scripts/python.exe fotmob_league.py --league 沙职 --match-id 5803519   # match xG 赛后才有

# 第 4 级发现：记下页面自己发出的 XHR，再拿去纯 HTTP 复验
.venv/Scripts/python.exe capture_xhr.py --url "https://www.fotmob.com/leagues/57/overview/eredivisie" \
    --out data/xhr_captures/manual.json
```

各源可达性与封锁状态见仓库 `30_数据/网页源可达性矩阵.md`；
fbref / forebet / whoscored / besoccer 确认被人机验证挡住，按缺口记录，不绕过。

## 玩法预测（4 大玩法全覆盖）

| 玩法 | 预测方式 | 官方对照 |
|---|---|---|
| 胜平负/比分 | 模型直接预测比分(0-7) + 赛果 | 官方HAD隐含概率 |
| 让球胜平负 HHAD | 预测比分自动换算(让胜/让平/让负 或 受让胜/受让平/受让负) | 官方HHAD最低赔方向 |
| 总进球 TTG | 模型预测 total_goals(0-7+)，与比分之和校验 | 官方TTG最低赔档 |
| 半全场 HAFU | 模型预测半场结果 + 全场结果 → 九宫格(胜胜/胜平/…/负负) | 官方HAFU最低赔组合 |

每个玩法都输出 `✅一致 / ⚠️分歧` 标记——模型与官方市场判断不同即为分歧场。
注意：分歧 ≠ 机会，也可能是模型错了，请结合置信度与分歧度综合判断。

## 数据驱动模拟器（Dixon-Coles 引擎，免费）

`simulate_from_odds.py`：官方赔率 → 去水 → 反推λ → Dixon-Coles 比分分布 → 4玩法概率 + Monte Carlo 模拟。
引擎直接复用 Codex 技能 `zu-yu-dashi-3` 的 `predict.py`（已回测校准），不重复建设。

```bash
python simulate_from_odds.py --input data/raw_2026-08-05.json --sim 10000
```

输出：λ/期望进球、官方vs引擎1X2、Top比分、让球/总进球/半全场概率、模拟N场比分统计。
与 LLM 投票形成互补：**引擎给概率分布（客观），LLM 给主观推理**。

## 模型配置

默认只调用 `moonshot/kimi-k3`，包括证据审计与研究意见。单模型输出标记为 `single_model_research` / `action=observe`：它不是投票共识，不显示投票强度或 LLM 概率，也不会计算 EV、生成单选或下注建议。只有显式传入两个独立投票模型时，才可能形成 `consensus`；即使如此，LLM 轨仍只作研究，不能替代量化轨校准概率。

需要做隔离实验时，可运行时用 `--models` 指定模型列表；不要修改默认池或把实验输出混入生产登记/回测。

**多 provider 支持**：模型 ID 加前缀路由到不同服务商——
- `zhipu/glm-4-flash` → 智谱（完全免费无限量，国内直连，key 已持久化 `ZHIPU_API_KEY`）
- `qwen/qwen-flash` → 千问/阿里云百炼（完全免费无限量，国内直连，key 用 `DASHSCOPE_API_KEY`，需在 https://bailian.console.aliyun.com 创建）
- `groq/llama-3.3-70b-versatile` → Groq（需代理 `127.0.0.1:10809`，key 已持久化 `GROQ_API_KEY`）
- `moonshot/kimi-k3` → Kimi K3（推理模型，国内直连，key 已持久化 `MOONSHOT_API_KEY`）
- `deepseek/deepseek-chat` → DeepSeek V3（国内直连，强推理，极低价，key 用 `DEEPSEEK_API_KEY`，需在 https://platform.deepseek.com 注册）
- `gemini/gemini-3-flash-preview` → Google Gemini 3（需代理，key 已持久化 `GOOGLE_API_KEY`；注意 2.5 系列已对新用户关闭，用 3 系列）
- `ark/doubao-seed-evolving` → 豆包/火山方舟（key 已持久化 `ARK_API_KEY`；需控制台开通模型，当前账户已开通 doubao-seed-evolving）
- 无前缀 → 智谱 `zhipu`（glm-4-flash，免费无限量）

**快捷入口**：用 `./run.sh` 代替 `python`，自动设置代理 + 读取所有持久化 key：
```bash
./run.sh predict.py --input data/raw_2026-08-05.json --evidence-dir data/evidence_2026-08-05
```

## ⚠️ 重要声明
- 足球比分预测本质极难，LLM 预测仅供参考娱乐，**不可作为投注依据**
- 声称 88-92% 正确率的预测产品是不现实的营销话术
- 免费模型为开源/轻量模型(GLM-4-Flash/Qwen-Flash/Llama等)，非 GPT-4o/Claude 真身

## 态势模型 MatchSituation（v1）

把证据 + 量化 + LLM 合成**局面/冲突/动作**，不是再算一套胜平负。

```bash
python match_situation.py   --evidence-dir data/evidence_YYYY-MM-DD   --model-output path/to/model_output.json   --llm-report data/预测报告_YYYY-MM-DD.md   --dual-json path/to/dual_track_4markets.json   --raw data/raw_YYYY-MM-DD.json   --out-dir data/situation_YYYY-MM-DD
```

输出: `situations.json` + `态势报告.md`  
动作: `single`(单选对照,非出胆) / `dual` / `observe`；**永不设胆**。

### 并入双轨报告 + 切片回测

```bash
python integrate_situation_dual.py   --situation data/situation_YYYY-MM-DD/situations.json   --dual-json path/to/dual_track_4markets.json   --dual-report path/to/今日双轨报告.md   --out-dir path/to/今日推荐目录   --date-label YYYY-MM-DD

python backtest_situation_slices.py   --situation data/situation_YYYY-MM-DD/situations.json   --results data/results_YYYY-MM-DD.json   --dual-json path/to/dual_track_with_situation.json   --out-dir data/situation_backtest
```

