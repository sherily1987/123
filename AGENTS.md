# AGENTS.md — 新 agent 接手第一份文档

这是本仓库（`F:\HM足球比赛预测`，足球比赛预测/量化融合系统）的单一入口。
先读这份，再按需去看 `全局工作台.md`（总规范）、`新项目SOP.md`（建项目流程）、
`全局复利与踩坑日志.md`（历史踩坑记录）。这三份不重复摘抄，本文档只做路由 + 关键风险提示。

## 0. 头号警告：一份需要手动同步的外部拷贝

`C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\zu-yu-dashi-3\`
是仓库外的**物理拷贝**，不是符号链接，不会自动跟仓库内代码同步。

- 改了 `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/` 下的任何核心引擎代码（比如
  `team_strength.py`）之后，必须手动 `cp` 到上面那个外部路径，否则它会静默过期。
- **本轮会话已经实测踩过一次**：外部副本的 `team_strength.py` 还是 337 行的旧版，仓库内
  已经是 676 行，两边差出一大截新功能。
- 另一个符号链接 `C:\Users\Administrator\.codex\skills\football-quant-fusion\` 指向
  `project018_技能工作区整合/02_脚本/skill/football-quant-fusion/`，**这个是自动同步的**，
  不用管。别把这两个搞混。
- `project017_football-quant-fusion技能导出/` 是给 Hermes 用的可重新生成导出包，跑
  `export_skill_for_hermes.py` 会重新拉取 `project018` 的当前代码打包（2026-08-12 已把
  该脚本里硬编码指向已废弃 H 盘的路径改成了 F 盘，之前一直在写一个不存在的目标）。

### ✅ 数据分裂：已修复并核验（2026-08-15 复核，此前长期标记为「未解决」）

这一节曾经写着「`fusion_daily_pipeline.py` 里 `STORE`/`ODDS_STORE`/`WORK` 仍硬编码
指向外部套件」和「registry 还差 8 条没补」。**两条都已经不成立，2026-08-15 逐条实测**：

1. **路径已统一**：`fusion_daily_pipeline.py` 的三个路径走
   `02_脚本/skill/football-quant-fusion/scripts/runtime_paths.py`，默认解析到仓库内
   `04_素材/shared-data/football-quant-fusion/`，可用 `FUSION_DATA_ROOT` 覆盖，
   并由 `assert_writable_target()` 拒绝写入路径含
   `/.codex/skills/football-quant-fusion-suite/` 的目标（抛
   `legacy fusion suite is read-only`）。`fusion_backtest.resolve_path()` 也已改为
   优先按 `--store` 内相对路径定位，不再因为外部文件还在就静默读外部那份。

   **但 2026-08-16 复查发现「已统一」当时只覆盖了 daily-pipeline**：`fusion_backtest.py`、
   `sample_audit.py`、`evaluate_walk_forward.py`、`fusion_combo.py` 的 `--store` 默认值，
   以及 `odds_api_adapter.py` 的 odds 输出目录，都还硬编码指向外部套件——忘了传 `--store`
   就**静默评测/写入错的库**（`calibration_gate`、`current_version_n` 会跟着一起错）。
   这几处已在 2026-08-16 一并改走 `runtime_paths`。
   `assert_writable_target()` 只在 `fusion_daily_pipeline.py` 里被调用，**不是全局守卫**，
   其余脚本靠默认值正确；显式传 `--store` 指向外部仍然能绕开。
   仍以 `sys.path.insert` 方式引用外部套件 zu-yu-dashi-3 的一次性研究脚本
   （`calibrate_league_kt.py`、`refit_kt_power.py`、`understat_enrich.py` 等）本轮未动。
2. **8 条缺口已补齐**：按 `prediction_id` 全量比对，仓库内 1597 条 ⊃ 外部 1555 条，
   **外部独有 0 条**，仓库内多出 42 条（08-12 之后新登记的）。合并痕迹见
   `backtest/registry.jsonl.bak_20260812_merge8`。哈希链完整性有
   `registry_chain_verification_20260814.json` 佐证。

保留的教训：外部套件是**物理拷贝不是链接**，历史上确实发生过「流水线默认写外部、
仓库内唯一事实源缺数据」。现在靠 `runtime_paths.py` 的默认值 + 写入守卫兜住，
但只要有人显式传 `--store` 指向外部，仍然能绕开——传路径参数时看清指向哪一份。

## 1. 三个当前活跃的核心项目

- **`project007_APIFootball数据接入`**：多数据源接入（apifootball.com / api-sports /
  football-data.co.uk），赛前赔率快照、代理 xG、联赛可用性核查。有 pytest 套件。
- **`project018_技能工作区整合`**：融合引擎 + `zu-yu-dashi-3` 核心库的**唯一事实源**
  （F 盘），LLM 对比轨、体彩官方采集/结算链路也在这里。有 pytest 套件。
- **`project021_五大联赛APIFootball训练`**：Dixon-Coles 团队强度模型，53 个联赛训练（含
  2026-08-12 新增的芬超低样本豁免、法乙、世界杯；2026-08-13 新增 api-sports.io
  （api-sports.io，跟 apifootball.com 是两个不同供应商，`API_FOOTBALL_KEY` 环境变量已配置
  Pro套餐/7500次每日额度）补的沙职/乌超/塞浦路斯甲/保加利亚甲/塞尔维亚甲/韩职/日联，
  slug 统一 `apisports_` 前缀，跟同名旧联赛数据分开、不合并 match_id；日联100%自然
  通过两道门槛，没有强行豁免）、跨联赛标尺校准、
  开售监控（`watch_sporttery_sale.py`）与无赔率预测（`predict_no_odds.py`）。有 pytest 套件。
  **2026-08-12 起模型 lifecycle 由 `candidate` 改为 `production`**（`team_strength.py`/
  `train_five_leagues.py`）——`predict_no_odds.py` 自带的 A/B/C/D 分档+可用/降级/拒绝
  裁决才是真正的质量门禁，`production` 标签只表示"已训练"，不代表该联赛质量达标，
  黑山甲/波黑甲仍未跑赢频率基线，芬超/乌超/塞浦路斯甲/保加利亚甲/韩职xG是低样本
  强行纳入（`build_league_xg.py --force-include`），读结果时仍要看分档裁决。
  **韩职(fd_kor)数据曾经是坏的**：football-data.co.uk 的 `new/KOR.csv` 实际重定向到
  `new/NOR.csv`（挪威联赛），已隔离到 `04_素材/corrupt_data_quarantine/`，改用
  api-sports.io（id=292）重新接入。**淘汰赛制赛事的90分钟结算 bug**：apifootball.com/
  api-sports.io 两边下载器原先只认 `Finished`/`FT` 状态，打了加时/点球的比赛（`After
  Pen.`/`PEN` 等状态）被整场丢弃，且比分字段本身是点球战后的最终比分不是90分钟比分；
  已修复为优先取 `ft_score`/`score.fulltime`，世界杯决赛、欧冠21场+欧联27场点球大战
  已找回，跨联赛校准已用修复后数据重跑。**2026-08-13 起无 xG 数据源的联赛不再追加
  校准豁免**——只有已明确验证过的这 5 个（芬超/乌超/塞浦路斯甲/保加利亚甲/韩职）保留
  低样本豁免，新联赛没有任何数据源能给xG时就用纯进球模型，不再找理由强行纳入。
  截至本轮，`predict_no_odds.py` 尚无一条真实登记进共享回测库的记录，首次实盘调用后
  应按今日双轨实测同样的方式登记验证。世界杯因赛事间隔过大（每4年一届，两次赛事
  中间3年半空窗）无法用现有滚动重拟合方法论训练，标 `not_trained`，非数据问题。

这三个的内部目录结构（尤其 `02_脚本/core/zu-yu-dashi-3/`、`02_脚本/skill/football-quant-fusion/`）
被至少 40 处硬编码路径/动态 `importlib` 依赖，**不要改名、不要挪动内部子目录**。
project018 内部还有一个指向自身 `02_脚本/skill/football-quant-fusion` 的 junction
（`05_交付/plugin/football-quant-fusion/skills/football-quant-fusion`），同样不能动。

**版本管理（2026-08-15 起，重要）**：融合引擎的 cohort 主键已从「5 字段全量字节哈希」
改为「语义版本 `model_version` + 概率签名 `probability_signature`」，打破 current=0 死锁。
- 改框架/日志/注释**不再重置样本**；只有改变概率数值输出（市场权重/校准系数/去水方法/
  市场锚逻辑）才需要 bump `config/version_manifest.json` 的 `model_version`。
- 生产预测批次前跑 `python release_lock.py` 锁定发布快照；改概率文件后跑
  `python audit_version_consistency.py` 检测「改了概率但忘了 bump 版本」的违规（非 0 即违规）。
- **当前 `model_version=m2`**（概率签名 `ceab23711523`，发布锁 2026-08-15T15:33Z）。
  m1 只存活了约两小时：08-15 13:32 UTC 登记的 08-16 那批 34 场签的是 m1，两小时后
  「融合门控与契约一致性修订」改动了 `production_router.py`/`fusion_predict_core.py`
  触发 bump，**m2 的样本从 0 起算，那 34 场 m1 结算后进的是一个不会再增长的队列**。
  1466 场 legacy 经重放审计确认概率不等价，同样不归入 current。
  完整机制见 `40_模型/模型版本管理_打破current死锁.md`。
- **签名字节哈希的死锁没有真正解除，用重放等价性兜底（2026-08-16）**：
  `probability_signature` 仍是概率文件的**字节**哈希，所以对 `probability_files` 名单里的
  文件而言，「改一个字节 → 签名变 → 审计要求 bump → 样本清零」原样成立，
  只是范围从全部源文件缩小到了那几个。m1→m2 就是这么丢的。
  新增 `scripts/probability_replay_check.py` 回答字节哈希答不了的那个问题——**概率变没变**：

  ```powershell
  python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\probability_replay_check.py --model-version m1
  ```

  它取旧样本登记时保存的 `input` 用当前代码重跑，与登记的 `final_1x2_pct`/`model_1x2_pct`
  逐场比对。判 `equivalent` 才可以把旧版本写进 `version_manifest.json` 的
  `model_version_aliases`，由 `fusion_backtest.version_cohort()` 按 current 计。
  **m1 已实测 35/35 完全一致**（仅 market_only 路由），已登记为 m2 的别名，
  那 34 场因此不必重攒。别名必须 `(model_version, probability_signature)` 精确成对，
  且等价结论不可外推到未重放的路由/衍生市场。这与 08-15 用同一把尺子**否决** 1466 场
  legacy 并入是同一套方法论，只是这次结论是肯定的。
- 查「当前版本还差多少样本」用（2026-08-15 新增，不必跑全量回测）：

  ```powershell
  python C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\fusion_cli.py version-progress
  ```

  它同时给**已结算**和**在途未结算**两个数——后者原先没有任何入口，只能手写脚本查。
  它的 settled 是回测 `n` 的上界（回测会丢弃已结算但无法评分的记录；2026-08-16 实测
  两边都是 474，当前没有这类记录，但别假定永远相等），门禁分子仍以 `backtest` 的
  `calibration_gate` 为准。`signature_drift` 非空 = 有人改了概率文件却没 bump 版本，
  那些样本会被静默排除出 current。

**精度现状与靶子（2026-08-16 诊断）**：模型 Brier 不优于市场（473 场 delta +0.0076，
95%CI 跨 0）。但这个全局数字**具有误导性**——劣势由 43 场（9%）产生，即市场依赖度 <80%、
模型真正动用独立信息偏离市场的那批（delta +0.0903）；其余 430 场 delta −0.0006、
CI ±0.002，因为 market_only 模式下模型概率就是同一份赔率去水反解的，**同源，不是打平**。
按联赛/分箱排出来的名次全部不显著，**照着调校准层会调错地方**，靶子是独立信息融合通路。
完整分解与三个候选方向见
`project018_技能工作区整合/06_复盘/2026-08-16_精度诊断/诊断_模型在哪里输给市场_20260816.md`。
注意 n=43、CI 跨 0，是有机制的假设不是定论；要坐实它需要**有意识地积累 hybrid 路由样本**，
继续堆 market_only 学不到任何东西。

**LLM 轨报告纪律（2026-08-15，重要，写报告前必读；同日两次更正，见下）**：

✅ **2026-08-16：LLM 轨生产工程已迁入本仓库，双份分裂结束。**
唯一事实源现在是 `project018_技能工作区整合/02_脚本/llm/football-llm-predictor/`。
`FOOTBALL_LLM_ROOT` 环境变量仍可覆盖（当前未设置，各处默认值已改为仓库内相对路径）。

~~头号事实：LLM 轨真正的生产代码不在这个 git 仓库里~~ —— 这条曾经是本文件的头号警告：
生产在 `C:\Users\Administrator\football-llm-predictor\`（非 Git），仓库里那份是**停更旧分支**
（生产 `predict.py` 1101 行 vs 仓库副本 800 行，副本缺 `ev_calculator`/`model_weights` 导入、
缺主胜比例熔断、缺次回合战意提示），两边无任何同步机制。**它导致过一次真实翻车**：
只查仓库 git 历史就断言「这个仓库没有任何代码计算 EV」，而生产目录里 `ev_calculator.py`
一直在跑。教训保留：**查证范围只覆盖仓库，不等于事实覆盖仓库**。

迁移的边界，改代码前先知道：

- **C 盘原目录 `C:\Users\Administrator\football-llm-predictor\` 仍在原地未删**（迁移时刻意
  保留以便回滚）。它现在是**过期快照**——所有活跃入口都已指向仓库内，别再往它写东西，
  也别拿它的内容推断当前行为。确认新位置稳定后可自行删除。
- **`.venv`（350M）与 `node_modules` 没有迁**：虚拟环境烧死了创建时的绝对路径，拷过来是
  坏的，必须在新位置重建，见该目录 `README.md` §2.5。日常 pytest 不依赖 `.venv`。
- **一次性网页抓取不入库**：根目录 129 个 `*.html`、`data/` 下的 `.tmp_evi*` 等由该目录
  `.gitignore` 排除（文件仍在磁盘上可用）。真正留档的证据在 `data/evidence_<日期>/`，入库。
- 已重新指向新位置的活跃消费方：`fusion_cli.py::run_llm_evidence()`、
  `project023_足球预测Web应用/02_脚本/` 的 `runner.py`/`collector.py`/`light_evidence.py`/
  `app.py`。`project001`、`project021` 里那些**按日期归档的一次性脚本没有改**——它们是历史
  运行记录，改了等于篡改历史。

注：`00_项目入口.md` 与 `30_数据/APIfootball数据契约.md` 里的旧 C 盘路径已同步更新。
另外 **`project023` 编号已被 `project023_足球预测Web应用` 占用**，本文件 §4 说的
「当前是 project023」已过时，下一个可用编号是 `project024`。

- `predict.py::aggregate_directions()` 的 `strength` 字段是**投票比例**
  （`top_votes / total_votes`，如 2/3、5/6），**不是校准概率**，这一点两边代码一致，是真的。
- ~~"这个仓库没有任何代码计算 EV"~~ **这是本节 2026-08-15 当天写下又被推翻的错误结论**：
  C 盘生产目录下的 `ev_calculator.py` 真实存在、`predict.py` 第 31/826 行确有
  `import ev_calculator as evc` 和 `evc.generate_betting_recommendation(...)` 调用，
  产出的 EV 会打进控制台输出（`💰 下注推荐` 段）。当时判断"从未落地"只是因为
  `git log --all` 只查了本仓库历史，没意识到生产代码根本不在仓库里——**结论的错误来源是
  查证范围只覆盖了仓库，不是代码真的不存在**。
- ~~`ev_calculator.py` 用 `votes_to_probabilities()` 把投票计数归一化当概率代入 EV~~
  **已于 2026-08-15 修复**（备份 `ev_calculator.py.bak_20260815_pre_ev_fix`）：
  - `votes_to_probabilities()` 已删除，调用直接抛 `NotImplementedError`，不再静默返回假概率；
    要票比用 `votes_to_vote_share()`，语义写死在函数名里。
  - `generate_betting_recommendation()` **无校准概率来源时 fail closed**：必须同时传
    `calibrated_probs` 和 `prob_source` 才产出 EV，否则 `action=skip`，只给
    `vote_share_analysis`（**刻意不含 `ev` 键**，下游误用会 KeyError 而不是拿到假数字）。
  - `predict.py` 的决策层同步收紧：只有 `action=bet` 的 `ev_analysis` 才传给
    `decide_single_pick()`。此前无论 skip 与否都传，等于在代码里绕开了自己的风控闸门——
    与 8-15 报告手工摘录时犯的是同一个错，只是那次发生在人工环节。
  - 顺带修掉 `find_positive_ev_bets()` 里那个签名上有、函数体里从没用过的
    `max_strength_threshold` 参数（调用方以为设了强度门槛，其实没生效）。
  - 配套测试 `test_ev_calculator.py`（10 项），C 盘生产与仓库副本两侧均 66 项通过。
  - **概率来源已于 2026-08-16 接上**：新增 `fusion_probability_source.py`，按
    `sporttery-<match_id>`（LLM 原始输入里就有 `match_id`）从量化轨登记库取最新一条
    `final_1x2_pct`。那是核心引擎按联赛校准过的真概率（记录里 `calibration.applied=true`，
    带 `league_basis` 与 test ECE），与未校准的「融合层推荐置信度」不是一个东西。
    取不到就返回 `None`，`ev_calculator` 照常 fail closed——**不得回退到投票比例**。
  - **但接上之后仍然出不了胆，这是对的**：`ev_calculator` 新增两道闸门——概率来源
    `calibration_status != VALID` 不出胆；`market_derived=True`（量化轨 `mode=market_only`，
    概率由**同一个盘口**去水反解而来）也不出胆，因为对同一盘口算 EV 量到的是庄家水位
    而不是独立信息 edge。当前登记的绝大多数是 market_only，所以实际表现是
    「给出 EV 数字 + `action=skip`」。这与融合技能 `edge_min_pp=5` 的判断一致
    （实测 675 样本 edge 范围 [-6.3,+1.6]pp，market_only 几乎必然不出胆）。
  - **修复前后的量级**（阿森纳vs曼城 08-16，真实登记场次）：旧口径票比 57.1% 当概率、
    平局 EV **+88.6%**；新口径校准概率 30.1%、平局 EV **-0.7%**。单场虚高 89 个百分点。
  - 双轨纪律不变：借用轨道A概率**只发生在 EV 这一层**，方向/比分/投票/登记仍各自独立。
- `generate_betting_recommendation()` 自己是有风控闸门的：`evidence_gap=True` 或
  `strength < 0.6` 时返回 `action=skip`，理由就是"证据存在缺口，风险过高"
  / "投票强度 X% < 60.0%，共识不足"这两句**硬编码字符串**（不是报告撰写者现编的）。
  但 2026-08-15 报告的"正 EV 下注推荐 Top"栏目里，恰恰是这几个被判定 `skip` 的场次
  带着 EV 数字出现在推荐表里——**没找到一个把 `predict.py` 控制台输出转成这份 markdown
  表格的脚本**，大概率是撰写报告的会话手动摘录时把 `skip` 场次的 `ev_analysis`
  （所有方向都有数字，不管 skip/bet）当成了 `recommended_bets`（只有 bet 时才有）来抄，
  绕开了代码自己的风控判断——**这个具体因果没有百分百实锤，是较强推测，不是定论**。
- **规则（修正版）**：①改 LLM 轨代码前先确认在改 C 盘生产目录还是 F 盘仓库副本，两边都要
  改就都要改，只改一边等于没改；②`strength` 不是概率，不要在任何新写的分析里把它当概率用；
  ③`ev_calculator.py` 的 EV 数字方法论上有效但依据不可靠（投票比例≠概率），报告里出现 EV
  时必须同时展示 `action`（`bet`/`skip`）和 `reason`，**不能只摘 EV 数字不摘判定结果**；
  ④若某场 `action=skip`，报告里就不能把它塞进"推荐"表，哪怕它的 EV 数字很好看。
- 若确实需要更可靠的 EV 排序，应该先有一个真实概率来源（如轨道 A 融合引擎的
  `final_1x2_pct`），不能用轨道 B 的投票比例替代——这也是双轨"各自登记、各自结算、
  不合并"纪律的延伸。

**独立工具（2026-08-15 新增）**：`project018_技能工作区整合/05_交付/独立工具/` 是给用户
日常双击使用的菜单入口（`fusion_tool.bat`，桌面有「足球预测工具」快捷方式），菜单 8 项
覆盖预测/回测结算/版本管理/辅助功能，所有操作显式 `--store` 指向仓库内唯一事实源。
改菜单逻辑改 `fusion_menu.py`；工具只是入口，每日预测/回测产物仍归
`project021/05_交付/每日开售预测/<日期>/`。

跑测试：

```bash
python -m pytest "project007_APIFootball数据接入/02_脚本" "project021_五大联赛APIFootball训练/02_脚本" -q
```

## 2. 已归档的历史项目在哪

`90_归档/`（2026-08-12 之前这个目录只有一份 README，从没真正归档过东西）。

已确认无任何活代码引用、整体迁入的 13 个：`001`小白Codex教程、`002`、`004`、`005`、
`006`、`008`~`011`（挪超/芬超/瑞超/巴西杯一次性下载）、`012`、`013`、`014`、`019`。
完整清单和每个的归档理由见 `全局工作台.md` 第 6 节「项目索引」。

**`project003_五大联赛数据下载` 看着像历史项目，但不能归档**——`project021` 的
`cross_league_calibration.py` 还在读它的 `04_素材/合并数据集/team_alias.json`，是活依赖。

**`project001` 有个已知的编号撞车**（`project001_小白Codex安装图文教程` 与
`project001_足球预测` 用了同一个编号）——这是文档自己承认的历史遗留，本轮没有处理，
维持现状。

## 3. "导出快照"是一个独立类别，不是旧项目

`project015`、`project016`、`project017` 都是刻意的、可重新生成的导出包（给 Hermes 或
其他工具用）。它们**不能归档，也不能直接手改内容**——源头都在 `project018`，改了源头后
重新跑对应导出脚本（如 `project017/export_skill_for_hermes.py`）就会覆盖生成新的一份。
直接编辑导出目录里的文件，下次重新导出会被覆盖，改动会丢失。

## 4. 项目文件夹约定

标准结构（详见 `全局工作台.md` §3）：`01_规划/ 02_文案/ 03_配图/ 04_素材/ 05_交付/ 06_复盘/`，
数据/代码类项目常用 `02_脚本` 替代 `02_文案+03_配图`。新建项目前先看
`全局工作台.md` 第 6 节确认下一个可用编号（**2026-08-16 更正：`project023` 已被
`project023_足球预测Web应用` 占用，下一个可用是 `project024`**），流程按 `新项目SOP.md` 走。

**每日一次的预测/回测类任务不再新开项目编号**——归到对应长期项目的
`05_交付/<任务名>/<日期>/`，例如 `project021_五大联赛APIFootball训练/05_交付/每日开售预测/2026-08-12/`。
这条是 2026-08-12 新加的：此前 `project019`（08-11 开售预测）和
`project022_20260812开售预测`（08-12 开售预测，还撞上了另一个已提交的 `project022`）
都是每天新开编号导致的连续两次撞车，这次已经把后者并入 `project021` 对应日期子目录，
根目录当天散落的十几个网页快照证据文件也一并挪了进去。

## 5. 根目录纪律

根目录只允许：3 份全局文档（本文件之外的 `全局工作台.md`/`全局复利与踩坑日志.md`/
`新项目SOP.md`）+ `AGENTS.md` + `projectNNN_*` 项目文件夹 + `全局工作台.md` §7 列出的
少量存量白名单项。**新产生的文件不要直接扔在根目录**，哪怕是临时抓取/调试用的——
2026-08-12 刚清理过一批散落在根目录的网页快照（属于某次开售预测工作，但没放进项目
文件夹），已按上一条约定挪进对应日期子目录。
