# project023 足球预测工作台（本地 Web 应用）

把现有预测流水线（体彩采集 / LLM 3模型证据轨 / 量化轨 / 回测）包装成浏览器可用的软件。

## 启动

```
双击 02_脚本/start.bat
→ 浏览器自动打开 http://127.0.0.1:8765
```

或命令行：`cd 02_脚本 && python app.py`

## 使用流程

1. **① 采集场次**：拉体彩官方接口当前在售未开球场次（含赔率、让球、量化档位标注），约 2-3 分钟
2. **② 一键预测**：自动生成轻量证据 → 3 模型投票（glm-4-flash / deepseek-chat / doubao）→ 方向/强度/下注建议/比分/大小球/EV，约 30-60 分钟（48 场）
3. **③ 回测赛果**：比赛结束后采体彩 `sectionsNo999` 90分钟比分，自动比对命中
4. **导出报告**：生成当日预测报告 markdown

## 重要说明（必读）

- **轻量证据 = 降级口径**：一键预测的证据只含体彩官方赔率/身份 + 量化档位（自动生成），伤停/首发/近况新闻不自动搜索 → 预测会带 ⚠证据缺口标记、EV 风控偏保守。需要深度证据时：手工把证据文件放到
  `C:\Users\Administrator\football-llm-predictor\data\evidence_YYYY-MM-DD\evidence_NNN_主队_客队.md`
  （NNN = raw 场次序号，六类标题格式见 `football-evidence-collection` 技能），再点预测会跳过已有证据文件。
- **LLM 轨依赖 3 个 API key**（环境变量：DEEPSEEK_API_KEY / 智谱 / ARK）。量化轨与采集完全离线。
- **仅绑定 127.0.0.1**，单机单用户，无鉴权。
- 数据存 `02_脚本/data/app.db`（SQLite）；原始采集在 C 盘 predictor 的 data 目录（与既有流程共用，单一事实源）。

## 架构

```
static/index.html（原生 JS 单页）
  │ fetch
app.py（FastAPI, 127.0.0.1:8765）
  ├─ collector.py   体彩采集（subprocess 调 project015 fetch_sporttery_full.py）+ 量化档位
  ├─ light_evidence.py  轻量证据生成（门禁合规，六类标题+事实行）
  ├─ runner.py      流水线调度（subprocess 调 predict.py / parse_predictions.py，线程后台任务）
  └─ db.py          SQLite（matches/predictions/backtests/runs）
```

## 复用的既有资产（不复制代码）

- 体彩采集：`project015/02_脚本/fetch_sporttery_full.py`
- LLM 预测：`C:\Users\Administrator\football-llm-predictor\predict.py`（3模型投票+EV+坍缩检测+熔断）
- 解析：`parse_predictions.py`
- 量化档位：`project021/05_交付/full_backtest.json`（复刻 league_tiers 分档规则）

## 规划文档

`01_规划/2026-08-15_方案设计.md`（MVP 范围、分期、风险）
