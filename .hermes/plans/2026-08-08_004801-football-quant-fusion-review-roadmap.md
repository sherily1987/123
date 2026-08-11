# 足球量化融合模型综合改造计划

> **For Hermes:** 实施时按任务逐项执行；每项采用TDD，完成后做独立代码审查。未经当前版本严格样本外验证，不改变生产推荐门控。

**目标：** 将 football-quant-fusion 从“稳定的市场基线与风险审计器”升级为“评估口径可信、具备可验证独立信号、只有在统计证据成立时才输出价值判断”的量化模型。

**架构：** 独立生成层采用“动态层级Dixon–Coles/贝叶斯Poisson + xG球队攻防强度 + λ联合后验 + posterior predictive Monte Carlo”；市场层保留体彩HAD作为独立基准，在融合层按模型后验不确定性和OOS学习权重，不把盘口混进球队强度训练。先重建无泄漏回测，再训练独立生成模型，最后校准与市场融合；所有生产切换必须由时间滚动OOS和市场配对比较决定。

**技术栈：** Python 3.11、PyMC（首选免费实现）或NumPyro、动态层级Dixon–Coles/贝叶斯Poisson、xG/xGA、posterior predictive Monte Carlo、体彩官方赔率、football-data.org、apifootball.com、JSONL回测库、时间滚动验证、paired bootstrap、Brier/Log Loss/ECE/CRPS/CLV/ROI。

---

## 一、缺点目录

### A. 评估证据缺陷（最高优先级）

1. **回测记录不等于独立比赛**：约1496条登记只有约415个独立match_id，大量比赛有opening/t-24h/t-6h/closing四条快照。
2. **版本污染**：1481条已结算样本中1442条版本为unknown；当前1.4.0明确样本很少，历史总成绩不能代表当前版本。
3. **校准存在同池拟合风险**：当前band表使用全快照池重拟合，且出现明显非单调关系，可能过拟合样本构成。
4. **整体ECE掩盖高概率段失准**：0.60–0.70段预测约64.5%，实际约42.7%；整体ECE 0.018被0.2–0.4低信息区间稀释。
5. **基准口径不统一**：研究集使用Pinnacle/Bet365，生产使用体彩；不同庄家、时点和抽水结构不能直接混用参数。
6. **缺少配对显著性检验**：目前列Brier/Log Loss均值，但没有按同场比赛做paired bootstrap置信区间。

### B. 模型预测能力缺陷

7. **market_only没有独立edge**：最新10场已稳定为10/10 MARKET_BASELINE；历史edge范围约-6.3～+1.6pp。
8. **多盘口并非独立证据**：HAD/HHAD/TTG/HAFU来自同一市场体系，联合拟合改善结构自洽性，但不能自动创造优势。
9. **独立球队强度不足**：生产输入经常没有真实事件xG、首发、伤停量化、休息天数、旅行与赛程密度。
10. **独立模型弱于市场**：1680场OOS中模型Brier 0.5993、命中50.71%，市场Brier 0.5833、命中53.10%。
11. **跨联赛泛化差**：共享回测英超命中约37.4%，西甲约53.4%；统一参数不适合所有联赛。
12. **杯赛/资格赛分布漂移**：两回合、首回合、淘汰赛战意和联赛不同，现有样本极少。
13. **平局决策能力弱**：平局很少成为argmax，但真实平局率不低；单纯argmax会系统性漏平。
14. **比分模型上限明显**：Top1约11.55%、Top3约31.13%，Poisson类模型难表达红牌、领先降速、末段压上和厚尾比分。
15. **衍生玩法校准不稳定**：统一Platt在部分联赛改善、部分联赛恶化；亚盘、半全场、晋级概率验证强度不一致。

### C. 工程与数据治理缺陷

16. **新鲜度仍有旧输入兼容风险**：有显式freshness时已修复；缺失freshness的旧输入仍使用kickoff_distance_legacy估算。
17. **采集时间语义不完整**：observed_at可能是最后变价时间，不一定是本次抓取时间；应分离observed_at与collected_at/as_of。
18. **版本/schema标识不统一**：skill 1.4.0、fusion_schema_version 1.3.0、core 3.4.4并存，报告容易混淆。
19. **大量绝对路径和动态导入**：代码绑定C:\Users\Administrator\.codex路径，迁移、测试和复现成本高。
20. **源码治理薄弱**：套件目录不是Git仓库，核心源码曾由pyc反编译重建，缺少可审计变更历史。
21. **测试体系是自定义脚本**：已有test_engine_full.py，但没有标准pytest发现、fixture和CI质量门。
22. **输出结构重复且庞大**：forecast与core_output重复字段，易发生新旧解析路径漂移。

### D. 决策与实盘闭环缺陷

23. **没有固定投注策略回测**：概率好坏与可下注策略没有完全分离，缺少固定时点、赔率和选择规则。
24. **CLV仍为负**：共享回测CLV均值约-0.144pp，尚无持续获取更优价格的证据。
25. **没有ROI置信区间与回撤指标**：缺少最大回撤、连续亏损、收益分布和策略稳定性。
26. **双选只有覆盖逻辑，缺成本收益逻辑**：双选命中率提高不等于期望收益提高。

---

## 二、总体改造顺序

1. **先修评估口径**：否则无法判断后续任何优化是否有效。
2. **再建立独立信号**：只在市场残差上学习，不与市场正面竞争绝对概率。
3. **再做分联赛/分赛制校准**：样本不足时回退全局参数。
4. **最后建立策略层**：只有OOS概率与CLV成立后才研究ROI和推荐。

---

## 三、实施计划表

| 阶段 | 优先级 | 任务 | 主要修改位置 | 验收标准 | 预计工作量 |
|---|---|---|---|---|---|
| 0 | P0 | 冻结当前基线与版本清单 | `config/version_manifest.json`、回测报告 | 明确当前生产版本、核心hash、配置hash；旧unknown样本隔离 | 0.5天 |
| 1 | P0 | 重建“一场一快照”回测数据集 | `scripts/fusion_backtest.py`、`scripts/sample_audit.py` | 主评估每个match_id只保留指定prematch快照；其他快照只用于时点研究 | 1天 |
| 2 | P0 | 当前版本隔离评估 | `scripts/fusion_backtest.py` | 报告分别输出current_version、legacy、unknown；禁止混合结论 | 0.5天 |
| 3 | P0 | 建立严格walk-forward OOS | 新建 `scripts/evaluate_walk_forward.py` | 按match_id分组、按时间切分；训练/校准/测试比赛不重叠 | 1天 |
| 4 | P0 | 增加市场配对比较和置信区间 | 同上 | 每项输出模型−市场的Brier/Log Loss差、paired bootstrap 95% CI | 1天 |
| 5 | P0 | 完成采集时间语义 | `scripts/sales_day_collect.py`、核心`market_fit.py` | 每个盘口同时保存collected_at和source_updated_at；不再依赖kickoff距离判新鲜度 | 0.5天 |
| 6 | P0 | 统一版本/schema | `fusion_predict_core.py`、`version_manifest.json`、登记脚本 | 输出中skill/fusion/core/schema/config_hash字段一致且可回溯 | 0.5天 |
| 7 | P1 | 替换非单调band校准 | 新建 `scripts/calibrate_oos.py`、`recommendation_policy.json` | 使用训练/校准集拟合单调校准器；测试集只评估；不改善则保持原始市场概率 | 1天 |
| 8 | P1 | 建立xG球队强度数据层 | 新建 `scripts/xg_feature_store.py`及数据适配器 | 每条xG/xGA和阵容特征有as_of与provider；覆盖率、缺失率、口径漂移可审计 | 2–3天 |
| 9 | P1 | 动态层级DC/贝叶斯Poisson | 新建 `models/dynamic_bayesian_dc.py` | 联赛/球队攻防部分池化、时间随机游走、DC低比分相关；无数据球队可回退联赛先验 | 3–5天 |
| 10 | P1 | λ联合后验与Monte Carlo | 新建 `models/posterior_predictive.py` | 每场保存λH/λA联合抽样、区间和相关性；模拟概率收敛且可复现 | 1–2天 |
| 11 | P1 | 不确定性感知市场融合 | 新建 `models/market_fusion.py`、修改`fusion_predict_core.py` | 独立输出model/market/fused三套概率；模型越不确定越向市场收缩；权重只用OOS拟合 | 2天 |
| 12 | P1 | 独立模型准入门 | `fusion_predict_core.py`、推荐策略 | 只有独立模型和融合模型均通过OOS才进入hybrid；否则保持MARKET_BASELINE | 1天 |
| 13 | P2 | 分玩法OOS校准 | `evaluate_selected_leagues.py`及新评估脚本 | 1X2、OU、BTTS、HHAD分别比较raw/cal；恶化的联赛自动不启用校准 | 2天 |
| 14 | P2 | 比分模型专项评估 | 比分模型与回测脚本 | 报告RPS/Log Loss/TopK/尾部比分及后验区间覆盖；不只看Top1命中 | 1天 |
| 15 | P2 | 平局与双选决策模型 | 新建 `scripts/evaluate_cover_policy.py` | 同时计算覆盖率、赔率成本、EV；不再只按命中率选双选 | 1天 |
| 16 | P2 | 固定策略模拟与CLV闭环 | `fusion_backtest.py`、国际盘快照库 | 固定投注时点和规则；输出ROI、CLV、最大回撤、置信区间 | 2天 |
| 17 | P3 | 工程标准化 | 引入`tests/`、pytest、相对路径配置 | 核心行为由pytest可发现；无硬编码用户目录；完整回归通过 | 1–2天 |

---

## 四、分阶段详细步骤

### 阶段0：冻结基线

**目标：** 防止优化后无法确认究竟改了什么。

**文件：**
- 修改：`C:/Users/Administrator/.codex/skills/football-quant-fusion/config/version_manifest.json`
- 修改：`C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/fusion_record.py`
- 测试：`C:/Users/Administrator/.codex/skills/football-quant-fusion/scripts/test_engine_full.py`

**步骤：**
1. 写失败测试：登记记录必须包含fusion/core/schema/config_hash。
2. 运行测试确认当前缺字段。
3. 计算配置文件hash并写入每次预测/登记。
4. 重新运行测试。
5. 生成基线清单：当前10场、当前配置、当前测试报告。

### 阶段1：修复回测口径

**目标：** 得到可用于决策的独立样本外结果。

**文件：**
- 修改：`scripts/fusion_backtest.py`
- 修改：`scripts/sample_audit.py`
- 新建：`scripts/evaluate_walk_forward.py`
- 测试：建议新建`tests/test_backtest_sampling.py`

**步骤：**
1. 构造一场比赛四快照fixture。
2. 失败测试：主评估只能计入一场，快照研究可计入四条。
3. 加入`evaluation_unit=match`和`snapshot_policy=prematch|closing|latest_before_kickoff`。
4. 按match_id分组后再做时间切分。
5. current/legacy/unknown分别报告。
6. 对同场模型与市场做paired bootstrap。
7. 输出有效独立比赛数，不再只显示记录数。

### 阶段2：重做校准

**目标：** 去除当前非单调band表的样本内波动。

**文件：**
- 新建：`scripts/calibrate_oos.py`
- 修改：`config/recommendation_policy.json`（只有OOS通过后）
- 测试：`tests/test_calibration.py`

**步骤：**
1. 将比赛按时间分为训练、校准、测试三段。
2. 在校准段比较：不校准、temperature scaling、isotonic。
3. 测试段只评估，不重新拟合。
4. 输出整体ECE之外的高概率段误差、Brier、Log Loss。
5. 只有测试段Brier不恶化且高概率校准改善才切换。
6. 样本不足联赛回退全局校准。

### 阶段3：建立独立信号

**目标：** 从“复述市场”升级为“市场锚 + 可验证独立修正”。

#### 3.1 动态层级球队强度

每支球队在时间`t`有潜在进攻强度`attack[i,t]`和防守强度`defence[i,t]`，按随机游走或AR(1)动态更新；升班马、新赛季和小样本球队向联赛总体先验收缩。联赛层保存基础进球率与主场优势，杯赛/两回合使用单独上下文系数。

核心结构：

```text
log λ_home = league_base + home_advantage
             + attack_home(t) - defence_away(t) + context_features

log λ_away = league_base
             + attack_away(t) - defence_home(t) + context_features
```

需要sum-to-zero等可识别性约束，避免进攻、防守和联赛基础率互相漂移。

#### 3.2 xG观测层

- xG/xGA作为潜在攻防质量的主要过程观测；
- 实际进球作为离散结果观测，保留终结能力但向均值收缩；
- 如果多家xG口径混用，必须增加provider偏差项，不能直接拼接；
- 先验证可稳定获得的历史xG覆盖，无法覆盖的联赛回退到进球观测版Bayesian Poisson；
- 所有观测必须带`as_of`，禁止使用开球后修订数据。

#### 3.3 Dixon–Coles低比分相关

对0-0、0-1、1-0、1-1使用DC相关修正`rho`。`rho`也进行联赛层级收缩，样本不足时回退全局先验；不得为每个小联赛独立自由拟合。

#### 3.4 λ联合后验

λ不是手工指定的正态/对数正态噪声，而是由每次后验参数抽样自然导出：

```text
posterior draw
  -> attack/defence/league/home_adv/rho/context
  -> (λ_home, λ_away)
```

必须保留`λ_home`和`λ_away`之间的相关性，输出均值、中位数、50%/80%/95%区间及联合样本摘要。

#### 3.5 Posterior predictive Monte Carlo

每次模拟先抽一组联合后验参数，再构造DC修正后的比分分布并抽取比分。聚合生成：

- 1X2；
- 正确比分；
- 大小球；
- BTTS；
- 让球；
- 各玩法置信区间。

模拟次数配置化，不用固定次数冒充精度；以重复种子结果差异和Monte Carlo标准误作为停止条件。相同输入、模型版本和seed必须可复现。

#### 3.6 市场融合层

独立生成层训练时不读取体彩赔率，保持可测量的独立性。预测时同时保留：

```text
p_model   动态贝叶斯DC后验预测
p_market  HAD去水市场概率
p_fused   不确定性感知融合概率
```

融合权重只能在walk-forward OOS中学习：模型后验越宽、数据越旧、xG覆盖越差，越向市场收缩；模型数据完整且历史OOS稳定时才允许增加独立模型权重。禁止用当天结果人工调整权重。

**补充特征：**
- 休息天数与赛程密度；
- 旅行距离/跨时区；
- 确认首发与关键位置缺阵；
- 联赛、杯赛、首回合/次回合标签。

市场开盘到赛前移动只进入融合/价值判断层，不进入独立球队强度层，以免独立模型和市场基准信息重复。

### 阶段4：生产准入门

**目标：** 独立模型不合格时自动退回市场基线。

**建议最低门槛：**
- 当前版本独立OOS比赛数≥300后再做结论；
- 模型相对市场Brier改善至少0.005；
- paired bootstrap 95% CI不跨0；
- Log Loss不得恶化；
- 高概率段绝对校准误差≤7pp（且该段样本≥100）；
- CLV均值>0且样本≥300；
- 任一条件不满足：保持`MARKET_BASELINE`，不开放胆。

这些阈值先作为研究准入线；最终需根据样本量和收益敏感性复审。

### 阶段5：策略与实盘闭环

**目标：** 区分“概率更准”和“可盈利”。

**固定回测内容：**
- 固定预测时点；
- 固定可购买赔率；
- 固定edge阈值；
- 单选和双选分别评估；
- 不用赛后最优阈值；
- 输出投注次数、ROI、CLV、最大回撤、最长连败、bootstrap区间。

---

## 五、验收总表

| 维度 | 当前状态 | 目标状态 |
|---|---|---|
| 模式可靠性 | 已修复，真实10场10/10 market_only | 随机/边界输入1000例无静默切换 |
| 独立样本 | 约415场但1496条记录 | 明确unique_match_n；每场一个主评估样本 |
| 版本纯度 | 1442条unknown | current/legacy/unknown完全隔离 |
| 市场对比 | 模型弱于市场 | OOS配对Brier改善且95% CI通过 |
| 校准 | 整体ECE好看，高概率段失准 | 独立测试集高概率误差受控 |
| 独立edge | market_only为0 | hybrid residual模型产生可复现正edge |
| CLV | -0.144pp | >0且样本足够 |
| 比分 | Top1约11.55% | 重点优化Log Loss/RPS，TopK仅辅助 |
| 推荐 | 全部不出胆是正确门控 | 仅统计门槛全部通过时开放 |
| 工程 | 自定义测试、硬编码路径 | pytest、相对路径、版本hash、可复现 |

---

## 六、主要风险与取舍

1. **最可能的结果是独立模型仍无法战胜市场。** 这不是失败；可靠地证明“没有edge”比错误开放推荐更有价值。
2. **当前样本量不足以细分所有联赛。** 必须使用层级收缩，不能每个小联赛单独拟合。
3. **伤停与战意最容易引入主观噪声。** 先作为结构化事实，后续有足够样本再量化。
4. **Pinnacle参数不能直接写入体彩生产。** 研究与生产市场必须分开校准。
5. **比分模型不应成为主信号。** 优先提升1X2/OU概率质量，再研究比分尾部。
6. **不要先优化ROI。** 在概率与CLV尚未通过前调ROI阈值会严重过拟合。

---

## 七、推荐执行顺序

第一批只执行P0：

1. 版本/hash冻结；
2. 一场一快照回测；
3. current/legacy/unknown隔离；
4. walk-forward + 市场配对置信区间；
5. collected_at/source_updated_at语义修复。

完成P0后再决定是否进入独立特征与残差模型。不要现在继续调band、市场权重或胆阈值。
