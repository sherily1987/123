---
type: guide
updated: 2026-08-16
---

# n8n 编排层（project023 工作台的调度外壳）

n8n **不参与任何计算**。它只做三件事：按点触发、轮询任务状态、失败报警。
所有写操作仍然经 `project023` 的 FastAPI → `runner.py` → `fusion_cli.py`，
登记纪律（market_only、工单 `sporttery-<id>`、两轨分列）一条不变。

## 为什么走 HTTP 而不是让 n8n 直接跑 Python

`runner.py` 已经把 `fusion_cli` 的子进程调用、Python 解释器解析（`resolve_python()`）、
去代理环境（`_no_proxy_env()`）、超时和进度落库全部封装好了。n8n 里再写一遍 Execute Command
等于把这套约束复制一份到工作流画布上——那是本仓库反复踩过的「同一件事两份实现，其中一份
静默过期」的坑。**n8n 只调 HTTP，不碰路径、不碰解释器。**

## 可用端点（`app.py`）

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/api/health` | GET | 存活探针，返回 store 路径与 `quant_mode` |
| `/api/collect` | POST | 体 `{"kickoff_date":"YYYY-MM-DD"}`，返回 `{run_id, status}` |
| `/api/predict` | POST | 同上，登记 market_only |
| `/api/llm` | POST | 同上，LLM 轨：复用当日采集，跑 `predict.py`，落盘 `forward/{date}/` |
| `/api/settle` | POST | 同上，手动结算（`/api/backtest` 是它的别名） |
| `/api/run/{id}` | GET | 轮询：`status` ∈ `running` / `done` / `error`，带 `done`/`total`/`message` |
| `/api/board` | GET | 看板 JSON |
| `/api/job?match_id=` | GET | 按 `sporttery-<id>` 读统一工单 |
| `/api/export/report` | GET | 返回看板 Markdown 文件 |

**POST 是异步的**：立刻返回 `run_id`，真正的活在后台线程里跑。
所以工作流必须「POST → Wait → GET `/api/run/{id}` → 判状态 → 回到 Wait」，
不能 POST 完就当已完成。

## 别让 n8n 写文件（2026-08-16 实测踩坑）

n8n **2.x 起 `N8N_RESTRICT_FILE_ACCESS_TO` 的默认值不再是空**，而是 `~/.n8n-files`
（见安装包 `@n8n/config/dist/configs/security.config.js:40`）。也就是说 Read/Write File 节点
**默认只能写 `C:\Users\Administrator\.n8n-files`**，写项目目录一律报
`Access to the file is not allowed.`——按旧版「默认不限制」的印象写工作流会直接踩中。

初版工作流最后挂了个 `落盘看板`（readWriteFile）节点，就是这么失败的。**已删除，因为它本来就多余**：
`/api/export/report` 自己会把 Markdown 写到 `02_脚本/data/board_report.md`（见 `app.py`
的 `out.write_text(...)`），n8n 那一步是重复劳动 + 多一道权限门。

**结论：落盘一律由工作台负责，n8n 只触发和轮询。** 真要 n8n 写文件再考虑放开白名单
（`N8N_RESTRICT_FILE_ACCESS_TO`，分号分隔），但那是放宽安全设置，要单独决定。

## 文件

- `工作流_每日采集与登记.json`：09:00 触发 → 健康检查 → 采集 → 轮询 → 登记预测 → 轮询 → 导出看板（落盘由工作台完成）。
- `工作流_LLM轨预测.json`：09:45 触发 → 健康检查 → `POST /api/llm` → 60 秒轮询。不深挖网页；有现成证据就复用，否则写轻量缺口。产物在 `forward/{date}/llm_predictions.txt` 和 `LLM轨.md`。
- `工作流_次日结算.json`：11:00 触发 → 结算 D-1 → 轮询 → 读看板汇总。
- `validate_workflow.js`：离线校验节点参数，改完工作流先跑它再导入。

导入（二选一）：

- 画布右上角 `…` → **Import from File**；
- CLI（不用登录，直接写 sqlite）：

```powershell
npx -y n8n import:workflow --input="F:\HM足球比赛预测\project023_足球预测Web应用\02_脚本\n8n\工作流_每日采集与登记.json"
```

**JSON 顶层必须带 `id`**：n8n 2.34 的 `import:workflow` 不会自动生成，缺了直接报
`SQLITE_CONSTRAINT: NOT NULL constraint failed: workflow_entity.id`。
带上 `id` 后重复导入是幂等更新（覆盖同一条），不会刷出一堆重名工作流。
当前三个 id：`hmQuantDaily0001` / `hmQuantLlm0001` / `hmQuantSettle001`。

## 改完怎么验（不执行、无副作用）

```powershell
node "F:\HM足球比赛预测\project023_足球预测Web应用\02_脚本\n8n\validate_workflow.js" "F:\HM足球比赛预测\project023_足球预测Web应用\02_脚本\n8n\工作流_每日采集与登记.json"
```

它直接加载 n8n 安装包里 `n8n-nodes-base/dist/node-definitions/nodes/n8n-nodes-base/<节点>/v<版本>.schema.js`
的 zod 定义来校验参数结构，能查出「节点类型不存在 / typeVersion 不存在 / 必填参数漏了 /
参数在当前 displayOptions 下根本不生效」。**Code 节点没有 schema**（`jsCode` 自由文本），
会标 `~ skipped`，那部分只能靠实跑。

2026-08-16 实测：25 个节点全过，3 个 Code 节点跳过。

## 前置条件（不满足就等于没配）

1. **工作台必须在跑**：`启动工作台.bat` 是手动前台进程，关窗口即停。
   n8n 定时触发时它不在，工作流只会稳定地失败在健康检查那一步。
   要么把它注册成开机自启的计划任务，要么接受「先手动开工作台再跑 n8n」。
2. **n8n 自身也是手动前台进程**（当前是 `npx n8n`），同样的问题。
3. 两者都在 `127.0.0.1`，n8n 若改用 Docker 跑，`127.0.0.1:8765` 在容器内指向容器自己，
   需要改成 `host.docker.internal:8765`。

## 纪律（改工作流前必读）

- n8n **不得新开第四种落盘格式**。它只读写既有工单/看板，产物是投影不是事实源。
- n8n **不得绕过 `recommendation_gate`**：报告里不要把 `action=skip` 的场次当推荐输出。
  这是 08-15 人工环节真实翻过一次车的地方。
- 汇总播报里**不得合并两轨**成一个「更准」的结论，样本门槛（100 场评估 / 200 场结论）没到。
