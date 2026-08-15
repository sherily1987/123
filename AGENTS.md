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

### ⚠️ 未解决的数据分裂（发现但本轮未修，2026-08-12 补充精确范围）

`fusion_daily_pipeline.py` 里 `STORE`/`ODDS_STORE`/`WORK` 三个数据路径仍硬编码指向上面那个
外部套件，而环境变量 `FUSION_DATA_ROOT` 实际配置的是仓库内路径。实测外部副本的
`production_movement.jsonl`（926KB，最后写入 2026-08-12 09:00）比仓库内那份
（753KB，2026-08-11 10:00）更新更大——**这几天的赔率移动数据只写进了外部副本，
仓库内那份"唯一事实源"缺了这段**。在合并两份历史数据、确认权威来源之前，不要
直接把这三个路径也改成走仓库内——会让流水线突然读不到最近几天的数据。

**`backtest/registry.jsonl`（预测登记库本身）的分裂范围已查清、比想象中小**：
仓库内 `project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/backtest/`
已经是 1550 条预测记录的完整物理副本（`predictions/2026/08/` 下文件数与外部一致），
不是空壳。与外部套件（`C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\
shared\football-quant-fusion\backtest\`，1555 条）逐条按 `prediction_id` 比对，
**只差 8 条**：`sporttery-2040812/2040813/2040814/2040815/2040816/2040817/2040818/2040830`，
均来自 2026-08-11 11:02 UTC 那一批（大概率是某次 `fusion_daily_pipeline.py` 用旧默认
外部 `--store` 跑的，早于本轮修 `CORE_DIR` 之前）。

**不能直接把这 8 条 append 到仓库内 `registry.jsonl` 末尾去补齐**——`fusion_record.py`
里 `entry_hash = sha(previous_hash + record_hash)` 是逐文件维护的哈希链，外部那 8 条的
`previous_hash` 是在外部链上算的，接到仓库内链末尾会对不上仓库内链的实际
`entry_hash`，破坏这之后的可验证性。要补齐必须专门写一次"重算哈希链"的合并脚本，
不能手动拼接——这正是之前"需要专门一轮核对再合并"警告里说的那类操作，本轮
仍然没有做，只是把范围从"不知道差多少"精确到了"就差这 8 条"。

2026-08-12 起新登记的预测（比如今天双轨实测的 3 场 UCL/解放者杯赛事）已经用
`--store` 显式指向仓库内路径写入，不会再扩大这个既有的 8 条历史缺口。

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
- 当前 `model_version=m1`，尚无 current 样本（1466 场 legacy 经重放审计确认概率不等价，
  不归入 current，从 m1 重新累积）。完整机制见 `40_模型/模型版本管理_打破current死锁.md`。

**LLM 轨报告纪律（2026-08-15，重要，写报告前必读）**：`predict.py::aggregate_directions()`
的 `strength` 字段是**投票比例**（`top_votes / total_votes`，如 2/3、5/6），不是校准概率；
`build_audit_record()` 的 JSON 输出里**没有 EV 字段**，`export_report.py` 也不产出 EV。
换句话说：**这个仓库目前没有任何代码计算 EV**。
- ⚠️ `全局复利与踩坑日志.md` 2026-08-12 那条"新增 `ev_calculator.py`（EV=预测概率×赔率-1）"
  的记录是**从未落地的**——`git log --all` 对该文件零匹配，此文件在本仓库历史上不存在过。
  别因为日志写了"已新增"就假设它存在或引用它的行为，先用 `git log --all -- <path>` 核实。
- 2026-08-15 的开售预测报告（如 `project001_足球预测/05_交付/2026-08-15_开售预测/`）出现
  的 `EV +113%` 等数字，是**报告撰写环节手算/编造**的，把投票比例当概率代入
  `概率×赔率-1`——不是代码 bug，是没有代码兜底，写报告的会话可以随意编。
- **规则：写每日预测报告时，不得输出任何"EV"/"期望值"字段或列**，除非能指出它是从哪段
  可审计代码算出来的。可以照常展示 `strength`（投票强度，如实标注"投票比例，非概率"），
  但不得拿它去乘赔率、不得包装成"正 EV 推荐"或排序依据。
- 若确实需要 EV 排序，必须先有一个真实概率来源（如轨道 A 融合引擎的 `final_1x2_pct`），
  不能用轨道 B 的投票比例替代——这也是双轨"各自登记、各自结算、不合并"纪律的延伸。

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
`全局工作台.md` 第 6 节确认下一个可用编号（当前是 `project023`），流程按 `新项目SOP.md` 走。

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
