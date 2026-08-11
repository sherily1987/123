# 足球预测系统可审计优化实施计划

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** 将当前四模型证据LLM轨、市场基线量化轨和官方赛果回测，升级为证据先行、赛前冻结、同版本可比、可复现回测的生产体系；不修改历史预测和历史赛果。

**Architecture:** 预测链分为三层：`官方/可追溯数据与证据 → 双轨预测 → 冻结登记与官方90分钟回测`。量化生产始终为`MARKET_BASELINE/market_only`；LLM生产池为智谱、千问、DeepSeek、Kimi，且必须通过证据门禁。实验模型、海外模型和实验特征永远单独登记、单独评估。

**Tech Stack:** Python 3.11、pytest/unittest、JSON/JSONL、OpenAI-compatible API、移动中国体彩网赛果、Windows + Git Bash。

---

## 不变规则

```text
生产量化：MARKET_BASELINE / market_only
生产LLM：zhipu/glm-4-flash + qwen/qwen-flash + deepseek/deepseek-chat + moonshot/kimi-k2.6
国内模型：运行前清除 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY 及小写变量
赛果评分：finished + settlement_scope=90min + 完整score_90 + 中国体彩网移动端官方赛果
正式胆：0；不足100场同版本OOS样本不改变生产权重
```

## Task 1：统一证据采集契约与证据文件完整性

**Objective:** 每场进入LLM之前都有一份独立、可溯源、开球前采集的六类证据文件。

**Files:**
- Modify: `C:\Users\Administrator\football-llm-predictor\predict.py`
- Modify: `F:\HM足球比赛预测\scripts\evidence_paths.py`
- Create/Modify: `C:\Users\Administrator\football-llm-predictor\test_prompt_rules.py`
- Create/Modify: `F:\HM足球比赛预测\tests\test_evidence_paths.py`

**Step 1: Write failing tests**

测试必须覆盖：
- 缺少`evidence_NNN_主队_客队.md`时返回`evidence_insufficient`且绝不初始化任何LLM client；
- 六个章节、`source(https://...)`、`collected_at(...)`缺任一项即拒绝；
- `collected_at >= kickoff`时拒绝为未来信息；
- 有最低真实事实但包含缺口时强制`evidence_gap=true`、`caution=true`、`alt_direction`非空；
- 文件路径必须是`今日推荐_双轨四玩法_YYYYMMDD/evidence/evidence_NNN_主队_客队.md`且非法Windows字符被清理。

**Step 2: Run RED**

```bash
cd C:/Users/Administrator/football-llm-predictor
python -m pytest -q test_prompt_rules.py -k evidence
cd F:/HM足球比赛预测
python -m pytest -q tests/test_evidence_paths.py
```

Expected: new behavior tests fail because kickoff-time validation is absent.

**Step 3: Minimal implementation**

- 在`assess_evidence()`接受可选`kickoff`，解析每条`collected_at`；任一被引用事实晚于开球时返回`evidence_after_kickoff`；
- 输出结构加入`evidence_file_sha256`、`evidence_collected_at_min/max`；
- 证据路径由`evidence_path()`唯一生成，禁止多个采集器在销售日目录写不同命名模式。

**Step 4: GREEN**

运行上述两组测试和`python -m py_compile`。

**Acceptance:** 无证据或未来证据绝不调用模型；有缺口只能双选/observe。

---

## Task 2：四模型生产LLM轨的可复现输出与个体审计

**Objective:** 智谱、千问、DeepSeek、Kimi四模型每场均保存独立输出、模型身份、失败状态和聚合规则版本。

**Files:**
- Modify: `C:\Users\Administrator\football-llm-predictor\football_predictor.py`
- Modify: `C:\Users\Administrator\football-llm-predictor\predict.py`
- Modify: `C:\Users\Administrator\football-llm-predictor\test_prompt_rules.py`
- Modify: `F:\HM足球比赛预测\治理\技能路由策略.json`

**Step 1: Write failing tests**

测试默认生产池必须精确等于：

```python
[
  "zhipu/glm-4-flash",
  "qwen/qwen-flash",
  "deepseek/deepseek-chat",
  "moonshot/kimi-k2.6",
]
```

并覆盖：Kimi调用使用`temperature=1`；单一模型失败不会中断其他模型；输出包含`model_id`、`provider`、`status`、`prompt_sha256`、`evidence_file_sha256`、`aggregation_rule_version`。

**Step 2: Run RED**

```bash
python -m pytest -q test_prompt_rules.py -k "model or kimi or aggregation"
```

**Step 3: Minimal implementation**

- 保持当前四模型`DEFAULT_MODELS`；
- 每场输出保存`individual`对象，不只保存最终投票；
- 对429、空响应、非JSON采用`status=failed`，不把失败模型当成反向票；
- 记录模型池数组哈希与聚合规则哈希；
- 继续使用国内直连，调用前后清除六个代理变量。

**Step 4: GREEN**

```bash
python -m pytest -q test_prompt_rules.py
python -m py_compile football_predictor.py predict.py
```

**Acceptance:** 四模型输出可追溯；Kimi加入正式投票但没有“额外权重”。

---

## Task 3：赛前冻结登记与同版本cohort

**Objective:** 每个正式预测在开球前被冻结，后续不能被重新运行覆盖；不同引擎/配置/模型池不得混样。

**Files:**
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_record.py`
- Create/Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\tests\test_p0_evaluation.py`
- Modify: `F:\HM足球比赛预测\scripts\run_llm_4markets.py`（仅保留为研究兼容入口，正式轨不得绕过Task 1）

**Step 1: Write failing tests**

- 正式`prematch`登记缺`prediction_as_of`、route/mode、三类sha256、输入/输出sha256任一项即拒绝；
- `prediction_as_of >= kickoff`即拒绝；
- 同一`match_id + snapshot=prematch`二次登记拒绝；
- 不同模型池哈希的LLM记录进入不同cohort；
- 旧的无证据`run_llm_4markets.py`输出不得被标记为生产LLM记录。

**Step 2: Run RED**

```bash
python -m unittest C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_p0_evaluation.py -v
```

**Step 3: Minimal implementation**

- 登记记录增加`llm_model_pool_sha256`、`evidence_sha256`、`prediction_as_of`；
- `cohort_key`由`prediction_code_sha256 + config_sha256 + engine_bundle_sha256 + llm_model_pool_sha256 + route + mode`生成；
- 快照只追加，禁止覆盖；实验必须使用明确`experiment_*` snapshot。

**Step 4: GREEN**

运行P0评估测试、记录脚本编译和一个`TemporaryDirectory`端到端登记验证。

**Acceptance:** 历史预测不被改写；每场唯一且能证明是开球前版本。

---

## Task 4：官方90分钟结算与第三方交叉验证分层

**Objective:** 官方赛果可以评分；搜索、截图和用户核对结果可保存证据但不应静默伪装为抓取到的官方响应。

**Files:**
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\backtest_dual_track.py`
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\auto_backtest.py`
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\tests\test_backtest_hardening.py`

**Step 1: Write failing tests**

- 仅接受`finished + 90min + score_90 + 中国体彩网移动端官方赛果`进入正式分母；
- 截图/搜索只能写`cross_validation`，除非有显式`user_confirmed_official_sporttery_result`和保留核验注记；
- 缺官方半场比分永远为`unresolved_missing_official_halftime_score`；
- ET、点球、延期、取消、判罚赛不作为普通90分钟赛果；
- 每次回测保存结果源hash、输入index hash、脚本hash。

**Step 2: Run RED**

```bash
python -m unittest C:/Users/Administrator/.codex/skills/football-quant-fusion/tests/test_backtest_hardening.py -v
```

**Step 3: Minimal implementation**

- 把来源与状态语义写成单独`validate_90min_settlement()`；
- `user_confirmed_official_sporttery_result`必须记录确认时间、来源注记和原始证据引用；
- 默认`auto_backtest.py`只读；仅`--settle`才允许请求官方接口。

**Step 4: GREEN**

运行回测硬化测试与临时目录结算/拒绝用例。

**Acceptance:** 没有合格官方90分钟数据绝不评分；每个已评分行可定位其结果证据版本。

---

## Task 5：按match_id去重、严格配对和指标报告

**Objective:** 避免同场重跑、销售日目录迁移、量化/LLM不同版本导致虚增样本或错误对比。

**Files:**
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\auto_backtest.py`
- Modify: `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\production_route_evaluation.py`
- Modify: corresponding `tests/test_backtest_hardening.py`, `tests/test_production_route_evaluation.py`

**Step 1: Write failing tests**

- 同一`match_id`多目录时，选择`latest_before_kickoff`唯一快照；
- 赛后生成的预测必须丢弃；
- 量化轨和LLM轨只有在相同`match_id`、相同赛果、相同版本cohort下才能计算配对差值；
- 样本少于100场返回`insufficient_paired_samples`，不得输出“优于市场”；
- 输出1X2、比分Top1/Top3、Brier、Log Loss、校准、市场配对差值和样本身份。

**Step 2: Run RED**

```bash
python -m unittest discover -s C:/Users/Administrator/.codex/skills/football-quant-fusion/tests -v
```

**Step 3: Minimal implementation**

- 以`match_id`为主键做候选快照选择；
- 结果报告内保存`included/excluded`清单及原因；
- `current/legacy/unknown`版本cohort分开输出，禁止合并总体平均。

**Step 4: GREEN**

执行全部量化技能测试、`test_engine_full.py`和镜像检测。

**Acceptance:** 报告中的每个分母都能还原为具体match_id清单；小样本只作描述。

---

## Task 6：影子运行、样本积累与准入决策

**Objective:** 在不改变市场基线生产权重前，积累四模型证据轨的同版本OOS数据。

**Files:**
- Modify: `F:\HM足球比赛预测\模型评测\模型样本积累清单_20260808.json`
- Create: `F:\HM足球比赛预测\模型评测\四模型LLM影子评估_YYYYMMDD.json`
- Modify: `F:\HM足球比赛预测\治理\技能路由策略.md`

**Process:**
1. 每天只对证据合格场次生成赛前冻结预测；
2. 记录四模型个体输出和聚合输出；
3. 赛后仅由官方90分钟结果回填；
4. 30场：检查JSON失败率、证据拒绝率、模型分歧与坍缩率；
5. 100场：开始做同版本校准、Brier/Log Loss、配对市场差值；
6. 200场：才允许评审是否改变模型权重或正式策略；任何阶段均不允许设胆。

**Acceptance:** 模型数量增加不等于权重增加；所有结论带样本数、版本哈希和时间顺序边界。

---

## 全量验收与安全检查

```bash
cd C:/Users/Administrator/football-llm-predictor
python -m pytest -q test_prompt_rules.py
python -m py_compile football_predictor.py predict.py

cd F:/HM足球比赛预测
python -m pytest -q tests/test_skill_routing_policy.py tests/test_run_llm_4markets_contract.py tests/test_evidence_paths.py tests/test_verify_fusion_skill_mirror.py
python -m unittest discover -s C:/Users/Administrator/.codex/skills/football-quant-fusion/tests -v
python C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/test_engine_full.py --output <temporary-output.json>
python scripts/verify_fusion_skill_mirror.py
```

额外安全检查：不得打印、写入、提交或在报告记录API Key；所有凭据只从环境变量读取；不提交或推送Git，除非用户明确要求。
