# 足球预测技能冲突整改 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将当前足球预测流程收敛为一条可审计生产主链，隔离旧OpenRouter技能与实验轨，消除代理/目录/结算契约冲突，同时不改写任何已冻结赛前样本。

**Architecture:** 以“生产、实验、历史参考、基础设施”四层治理替代删除技能。量化生产固定为`MARKET_BASELINE/market_only`；LLM生产固定为国内智谱、千问、DeepSeek三模型且进程级清代理；证据、赛果、回测均通过显式元数据和门禁验证。旧技能保留，但不进入生产路由。

**Tech Stack:** Python 3.11、现有`football-quant-fusion`脚本、移动体彩官方赛果、JSON/JSONL、标准库`unittest`。

---

## 不可变约束

- 不删除任何技能，也不修改已经登记的预测概率、LLM结果或赛果。
- 正式量化输出只能为`MARKET_BASELINE/market_only`；Understat/APIfootball仅作为独立实验cohort。
- 当前LLM生产模型池固定：`zhipu/glm-4-flash`、`qwen/qwen-flash`、`deepseek/deepseek-chat`。
- 国内三模型调用前必须清除`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`及小写同名变量；海外模型只能在独立实验进程使用代理。
- 普通1X2、比分回测必须验证`status=finished`、`settlement_scope=90min`、完整`score_90`和移动体彩官方来源。半全场必须有`score_ht`，否则明确标记未评分。
- 版本身份字段不可省略：`prediction_code_sha256`、`config_sha256`、`engine_bundle_sha256`、`snapshot`、`route`、`prediction_as_of`。

---

### Task 1: 建立生产技能路由策略

**Objective:** 让每个预测环节只有一个明确生产入口，旧技能不再被误选。

**Files:**
- Create: `F:/HM足球比赛预测/治理/技能路由策略.json`
- Create: `F:/HM足球比赛预测/治理/技能路由策略.md`
- Test: `F:/HM足球比赛预测/tests/test_skill_routing_policy.py`

**Step 1: 写失败测试**

验证策略必须包含：

```python
assert policy["production"]["quant"] == "football-quant-fusion-prediction"
assert policy["production"]["llm_ops"] == "llm-football-prediction-ops"
assert "football-llm-ensemble-prediction" in policy["legacy_only"]
assert policy["proxy_policy"]["domestic_llm"] == "unset_all_proxy"
```

**Step 2: 实现最小策略文件**

定义四层：

```text
production
experiment
legacy_only
infrastructure
```

并明确：

```text
football-llm-ensemble-prediction = legacy_only
football-match-evidence = auxiliary_only
football-evidence-collection = production evidence collector
```

**Step 3: 验证**

```bash
python -m unittest F:/HM足球比赛预测/tests/test_skill_routing_policy.py -v
```

Expected: PASS。

---

### Task 2: 收敛国内三模型执行入口与代理隔离

**Objective:** 将当前日期目录内的LLM运行逻辑收敛到项目唯一脚本，避免旧OpenRouter或全局代理脚本误入生产。

**Files:**
- Create: `F:/HM足球比赛预测/scripts/run_llm_4markets.py`
- Create: `F:/HM足球比赛预测/tests/test_run_llm_4markets_contract.py`
- Modify: 后续销售日任务只调用上述脚本；历史日期目录内脚本不删除，仅停止作为生产入口。

**Step 1: 写失败测试**

验证脚本：

```python
assert "--raw" in help_output
assert "--out-json" in help_output
assert "--out-txt" in help_output
assert "HTTP_PROXY" in source and "pop" in source
```

**Step 2: 实现唯一入口**

- 迁移当前已验证的参数化`run_llm_4markets.py`逻辑。
- 在Python进程内显式清除所有代理变量，不依赖调用者shell。
- 固定默认国内三模型池；模型池、温度、提示词版本写入输出元数据。
- 输出保持四玩法：`1x2`、`score`、`ou25`、`hafu`，并写入`alt_direction`、`caution`、`collapse_flags`。
- 不使用OpenRouter/Groq/Gemini作为默认回退。

**Step 3: 验证**

```bash
python -m py_compile F:/HM足球比赛预测/scripts/run_llm_4markets.py
python F:/HM足球比赛预测/scripts/run_llm_4markets.py --help
python -m unittest F:/HM足球比赛预测/tests/test_run_llm_4markets_contract.py -v
```

Expected: PASS；不调用任何真实模型API。

---

### Task 3: 固化证据轨唯一落盘位置

**Objective:** 避免`football-match-evidence`与`football-evidence-collection`将同一批次事实写到不同目录而失去预测可追溯性。

**Files:**
- Create: `F:/HM足球比赛预测/scripts/evidence_paths.py`
- Create: `F:/HM足球比赛预测/tests/test_evidence_paths.py`
- Modify: 未来采集调用显式传入输出根，不改动历史证据文件。

**Step 1: 写失败测试**

```python
path = evidence_path("20260810", "周一001", "天狼星", "布鲁马波")
assert str(path).startswith(r"F:\HM足球比赛预测\今日推荐_双轨四玩法_20260810")
assert path.name.startswith("evidence_001_")
```

**Step 2: 实现路径函数**

统一目标：

```text
F:/HM足球比赛预测/今日推荐_双轨四玩法_YYYYMMDD/evidence/
```

- 文件名用当日数组序号`NNN`，避免跨销售日竞彩编号撞号。
- 每份证据写入`match_id`、`kickoff`、`collected_at`、来源URL和`as_of`。
- `football-match-evidence`只允许输出到临时或辅助目录，禁止与生产证据目录并行写入。

**Step 3: 验证**

```bash
python -m unittest F:/HM足球比赛预测/tests/test_evidence_paths.py -v
```

Expected: PASS。

---

### Task 4: 强化双轨回测的90分钟结算门禁

**Objective:** 防止加时、点球、取消、缺半场字段等赛果被错误评分。

**Files:**
- Modify: `C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/backtest_dual_track.py`
- Create: `C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_backtest_dual_track_settlement.py`

**Step 1: 写失败测试**

覆盖以下结果样例：

```python
finished_90min = {"status":"finished", "settlement_scope":"90min", "score_90":{"home":1,"away":0}, "source":{"name":"中国体彩网移动端官方赛果"}}
after_et = {"status":"finished", "settlement_scope":"after_et", "score_90":{"home":1,"away":1}}
cancelled = {"status":"cancelled"}
missing_score = {"status":"finished", "settlement_scope":"90min", "score_90":None}
```

断言：

- 只有`finished_90min`进入1X2与比分评分。
- `after_et`、`cancelled`、缺比分均输出明确的`not_eligible`原因。
- `score_ht is None`时半全场输出`unresolved_missing_official_halftime_score`，不计入分母。
- 缺失`index_llm.json`时报告写`llm_track_status=missing_index`，不得显示“0/0”等同于LLM表现为零。

**Step 2: 最小实现**

新增独立函数，例如：

```python
def validate_90min_settlement(result: dict) -> tuple[bool, str]: ...
```

评分循环先调用此函数；报告新增：

```text
eligible_90min
skipped_by_reason
hafu_status
llm_track_status
```

**Step 3: 验证**

```bash
python -m unittest C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_backtest_dual_track_settlement.py -v
python -m py_compile C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/backtest_dual_track.py
```

Expected: PASS。

---

### Task 5: 防止自动回测报告静默覆盖

**Objective:** 保留同一销售日不同回填时点的审计结果，同时提供固定“最新报告”入口。

**Files:**
- Modify: `C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/auto_backtest.py:74-194`
- Create: `C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_auto_backtest_output_paths.py`

**Step 1: 写失败测试**

断言同一日期、不同运行时刻的输出路径不同：

```python
assert run_path("20260810", "101500") != run_path("20260810", "154000")
```

同时断言固定入口仍存在：

```text
<输出根>/latest/auto_backtest_report.json
<输出根>/latest/auto_backtest_report.md
```

**Step 2: 实现归档布局**

```text
回测结果/archive/YYYYMMDD_HHMMSS/
回测结果/latest/
```

- 每次运行写入新的`archive`目录。
- 完成后更新`latest`固定文件。
- 归档报告记录`ran_at`、输入索引哈希、发现的记录目录、结算文件revision和脚本身份哈希。
- 不覆盖或改写旧归档。

**Step 3: 验证**

```bash
python -m unittest C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_auto_backtest_output_paths.py -v
python -m py_compile C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/auto_backtest.py
```

Expected: PASS。

---

### Task 6: 为镜像技能加漂移检测，而不删除副本

**Objective:** 保留套件兼容性，同时阻止两个`football-quant-fusion`目录悄然分叉。

**Files:**
- Create: `F:/HM足球比赛预测/scripts/verify_fusion_skill_mirror.py`
- Create: `F:/HM足球比赛预测/tests/test_verify_fusion_skill_mirror.py`

**Step 1: 写失败测试**

使用临时目录构造同内容与不同内容文件，断言：

```python
assert compare_trees(primary, mirror)["status"] == "in_sync"
assert compare_trees(primary, drifted)["status"] == "drift_detected"
```

**Step 2: 实现检测器**

比较：

```text
SKILL.md
scripts/*.py
config/*.json
```

输出JSON：

```text
status
primary_path
mirror_path
same_files
different_files
only_primary
only_mirror
checked_at
```

只读、非修复；检测到差异时以非零退出，阻止把两个版本混合执行。

**Step 3: 验证**

```bash
python -m unittest F:/HM足球比赛预测/tests/test_verify_fusion_skill_mirror.py -v
python F:/HM足球比赛预测/scripts/verify_fusion_skill_mirror.py
```

Expected: 当前镜像输出`in_sync`。

---

## 交付验收

1. 今天3场和已回测的6场样本内容哈希、预测字段、赛果字段不发生变化。
2. 国内LLM执行入口在预置代理环境下仍会清代理；无真实API调用的契约测试通过。
3. 只有合格90分钟赛果能进入1X2/比分指标；半全场缺半场比分不评分。
4. 自动回测同日重复运行生成不同归档目录，`latest`可读取最新结果。
5. 主技能目录与镜像目录出现漂移时检测器失败；当前镜像检测通过。
6. 相关单元测试、`py_compile`、现有`production_route_evaluation`和`production_router`测试均通过。

## 风险与取舍

- 不直接删除镜像技能：避免破坏`football-quant-fusion-suite`的现有依赖；用漂移检测替代。
- 不把海外模型加入当前生产：否则改变已冻结LLM样本的供应商、提示词与运行环境，失去可比性。
- 不用终场比分补半场：宁可半全场暂不评分，也不污染指标。
- 报告归档会增加文件数，但历史运行应进入`archive/`，符合“统一脚本、历史归档”的项目规范。
