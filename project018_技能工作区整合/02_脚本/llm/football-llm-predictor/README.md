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
```bash
# bash / git-bash
export ZHIPU_API_KEY=「redacted:…」

# Windows PowerShell
$env:ZHIPU_API_KEY="「redacted:…」"

# 或直接写入系统环境变量(长期有效)
```

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
# 1) 采集某开球日的比赛与官方全盘口（胜平负/让球/比分/总进球/半全场）
cd "/h/claude AI自媒体/project015_足彩移动采集接口导出/02_脚本"
python fetch_sporttery_full.py --date 2026-08-05 --method all \
    --output "C:\Users\Administrator\football-llm-predictor\data\raw_2026-08-05.json" --delay 1.2

# 2) 对采集到的每场比赛做多LLM预测（赔率作为参考输入, 证据驱动）
cd /c/Users/Administrator/football-llm-predictor
python predict.py --input data/raw_2026-08-05.json --evidence-dir data/evidence_2026-08-05

# 2b) 生成报告 (Markdown + Excel)
python export_report.py data/predictions_2026-08-05.txt data/raw_2026-08-05.json

# 3) 赛后采集赛果，回测预测
python fetch_sporttery_full.py --results --date 2026-08-06 --output data/results.json
python backtest.py
```

`predict.py` 会把官方赔率（胜平负/让球/总进球/比分/半全场）+ 六类证据拼进每个模型的提示词，
模型参考赔率但保留独立判断；输出综合预测 + 官方赔率隐含概率对照。

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

## 自定义模型
编辑 `football_predictor.py` 顶部的 `DEFAULT_MODELS`，或运行时用 `--models` 指定。

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

