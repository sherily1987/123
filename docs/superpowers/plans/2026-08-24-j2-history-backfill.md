# 日乙历史比赛数据补录实施计划

> **For agentic workers:** 本计划用于当前会话内按阶段执行；每个阶段完成后必须通过数据质量检查，再进入下一阶段。

**Goal:** 为已有预测但缺少独立历史训练集的日乙建立可审计的多赛季90分钟赛果数据集，并输出质量摘要。

**Architecture:** 使用现有 api-sports.io 赛果下载器，仅保存事件赛果，不伪造赔率；原始 JSONL、目录登记和质量报告全部放在 project021 内。先完成身份、赛季、比分和状态核验，再决定是否进入模型训练。

**Tech Stack:** Python 3、现有 `fetch_apisports_league.py`、JSONL、PowerShell/Python 质量检查。

**Spec:** 用户要求按优先级补充“有预测但历史数据不足”的联赛，日乙为第一项。

## Global Constraints

- 体彩赔率仍是生产基准；API-Sports 只提供历史赛果，不进入生产赔率字段。
- 90分钟赛果必须可核验；加时/点球场次不得混入常规联赛90分钟训练分母。
- 原始数据、质量报告、脚本输出均存放在 project021 项目目录内。
- 首次补录完成后先作数据质量验收，再决定是否加入训练目录。

### Task 1: 下载日乙多赛季赛果

**Files:**
- Create: `project021_五大联赛APIFootball训练/04_素材/apisports_japan_j2_events.jsonl`
- Modify: `project021_五大联赛APIFootball训练/02_脚本/second_tier_catalog.json`（仅在数据验收通过后）

- [x] 使用现有下载器请求 API-Sports league id=99，赛季 2021–2026。
- [x] 检查每条记录的主客队、开球时间、90分钟比分和 Finished 状态。
- [x] 记录空赛季、API错误和重复 fixture id。

### Task 2: 输出质量摘要

**Files:**
- Create: `project021_五大联赛APIFootball训练/05_交付/日乙历史数据补录_质量报告.json`

- [x] 统计总行数、Finished且有比分行数、按赛季行数、重复数、缺比分数。
- [x] 明确该数据没有历史赔率，不能与 closing_market 口径混合。
- [x] 只有质量通过后，才进入后续训练评估队列。

### Task 3: 验证

- [x] 运行现有项目测试中与 API-Sports 下载器相关的测试。
- [x] 对下载文件进行 JSONL 解析和赛季覆盖检查。
- [x] 输出当前阶段完成/阻塞原因，不提前声称模型已训练。
