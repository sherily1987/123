# 融合层踩坑记录（football-quant-fusion 专属）

> ⚠️ REBUILT 2026-08-02：原文件在文件系统同步事故中损坏，本文件基于 SKILL.md 1.4.0 变更记录、会话记忆与运行产物恢复重建。与底层引擎的 `zu-yu-dashi-3/references/pitfalls.md` 分层维护：底层坑位（数据采集/建模/校准）见底层文件，本文件只记录融合层自身的坑。

## 0. 生产门控与签名边界（1.5.0，2026-08-15）

- 原门控会把未校准的原始最大概率当成推荐置信度，使 `MARKET_BASELINE`、`AVOID_DATA_RISK` 或 HHAD 在达到50%时仍可能出胆。现改为全局默认关闭、校准概率缺失即拒绝，HHAD固定为 shadow。
- 候选球队强度原先只要总样本量达标就可能自动进入 `hybrid`，还会乘任意0.9系数。现要求两队分别达标；默认只写 `research_candidate`，显式 `--research-route` 才产生 `research_only` 输出。
- 原概率签名遗漏生产路由，却包含不改变概率的推荐政策。现拆成概率、决策政策、证据管线三条签名，避免漏追踪概率变更和无关重置样本。
- SKILL 原先把意图标签写得像命令，并承诺所有衍生市场。现只列真实入口；缺失盘口必须输出 `VALID` / `UNAVAILABLE` / `UNFITTED` / `NOT_OFFERED` 状态，不得补数。

## 1. 三Skill横向审计补丁（1.4.0，2026-08-02）

对 football-quant-fusion / soccer-lottery / zu-yu-dashi-3.4.1 做了代码级（非仅文档）审计后发现的融合层问题：

### 1.1 核心引擎两处未捕获崩溃 → fusion 层兜底为 blocked
- **ZeroDivisionError**：`odds` 完整但 `field_meta.odds.observed_at` 缺失、且无 elo/lambda 兜底时，市场锚被新鲜度判定清零后 `build_lambdas()` 对空 pairs 求和相除。
- **TypeError**：HAD 及全部 hhad/ou/ttg/hafu 均过期（OUTDATED/UNKNOWN）时 `multi_fit=None`，但后续无条件解包 `multi_fit['lambda_home']`。
- 用真实体彩数据（39.5~44.8小时旧快照，2026-08-02 周日012-014）可复现 TypeError。
- **修复（1.4.0 融合层兜底）**：`fusion_predict.py` 包 try/except，返回 `fusion_status=blocked` + `core_output.market_pool_freshness` 现场快照 + `likely_cause`，调用方不再看到裸 traceback。
- **经验**：核心引擎3.4.x 仍有此 bug；fusion 层必须继续兜底，直到核心修复。

### 1.1b 核心引擎根治（2026-08-02，predict.py）
- **无锚不得当生产 1X2（m3）**：`NO_ANCHOR_FALLBACK` 仍用于避免除零，但 1X2 不得输出 37.4/25.3/37.4。有可用 HAD 钉回 `market_only`；否则 `status=no_independent_anchor`，融合层 `blocked`。43 场低依赖里 36 场是这条回退。
- **ZeroDivisionError 根治**：`build_lambdas()` 空锚时回退中性 λ 并打 `NO_ANCHOR_FALLBACK`；m3 起该标签不能再进入生产概率。
- **TypeError 根治**：`multi_fit` 可能为 None（全盘口 OUTDATED/UNKNOWN）时不再无条件解包，改为 None 走 `build_lambdas()` 兜底。
- 验证：crash1/crash2 复现用例由崩溃改为 `fusion_status=ok + AVOID_DATA_RISK + xg_tags=[NO_ANCHOR_FALLBACK]`；4 场批量输出与修复前**逐字节一致**（149016 字符）；无盘口冒烟一致。核心 py_compile 通过。
- 融合层 try/except 降级为纯安全网（正常路径不再触发），不删除（保留对未来未知异常的最后防线）。

### 1.2 被静默丢弃的核心输出 → core_calibration 透传
- zu-yu-dashi-3 3.4.2/3.4.3 已拟合的 `confidence`（星级）、`final_1x2_display`（百分比）、`derived_market_status`（逐盘口拟合状态）每次 predict() 都算出来，但旧 fusion 层完全没引用。
- **修复**：新增顶层 `core_calibration` 字段透传（one_x2_calibration / confidence / derived_market_status），并显式区分两个粒度：
  - "核心单项盘口校准"（1X2/O-U2.5/3.5，已在体彩1348场时间序列切分验证）
  - "融合层组合/edge 校准"（仍 UNFITTED，不得用前者描述后者）
- **禁止混用**：`core_calibration` 存在 ≠ `recommendation_gate.banker_allowed` 放行。

### 1.3 流水线格式假设吞错
- zu-yu-dashi-3 的 `daily_pipeline.py` 假设子进程输出单行紧凑 JSON；fusion 的 `sales_day_collect.py` 输出 indent=2 多行 JSON → 旧版照抄解析失败且**被静默吞掉**。
- **修复**：整体 `json.loads(r.stdout)`，不按行解析。

### 1.4 组合腿强校验
- 组合 legs 必须用已登记 prediction_id/cover_id 字符串数组，缺失或重复标 `invalid_combo_reference`，不计入组合命中率。
- `fusion_combo.py --legs combos.json --output combo_validation.json`，legs 是 **ID 字符串数组**（不是 dict 列表；dict 会触发 TypeError: unhashable type）。

## 2. 登记与输入格式

### 2.1 record 输入必须是裸 dict
- `fusion_cli.py record --input x.json`：x.json 必须是被预测**单场的裸 dict**（home/away/odds/field_meta/...），不能是 `{"matches":[...]}`。
- 用 `{"matches":[m]}` 时 fusion_predict 顶层返回 `fusion_status=batch`，record 判定 "fusion prediction blocked; refuse registration" 拒绝登记（虽然单场结果本身 ok）。
- 批量场景：先 `fusion_predict.py input_full.json` 出批量结果；登记需拆成单场裸 dict 逐个 record（或走 `fusion_daily_pipeline.py` 自动拆分）。

### 2.2 快照幂等
- 同 `(match_id, snapshot_type)` 只登记一次；重复登记 `status=skipped_duplicate_snapshot`（exit 0，幂等可重跑）。
- prediction_id 含时间戳，**不能用文件路径是否存在判断重复**（时间戳路径永不重复）。

### 2.3 无市场锚（体彩未开售）路径缺陷（2026-08-02 实测）

- **NameError `market_freshness_meta`**：`fusion_predict_core.cpython-312.pyc` 在"市场赔率缺失/陈旧"分支引用从未赋值的模块级 `market_freshness_meta`，无 odds 输入直接崩溃（此前只兜底了 ZeroDivisionError/TypeError）。修复：加载器 exec_module 后注入 `_core.market_freshness_meta = {}`（已合入 `fusion_predict.py`，项目内留了 `fusion_predict_workaround.py` 副本）。
- **POLICY_ERROR 门控**：pyc 把 `recommendation_policy` 模块路径拼成 `scripts/__pycache__/recommendation_policy.py`，而源文件在 `scripts/recommendation_policy.py`，导致门控无法求值。修复：把源文件复制到 `__pycache__/` 同名路径（失败关闭：UNFITTED、不出胆）。
- **无市场锚的正确输出语义**：mode=model_first + Elo 锚时 `fusion_decision=UNFITTED_NO_VALUE`（或陈旧盘口时 AVOID_DATA_RISK），**只能给概率排序与风险，不得声称 edge/价值**；等体彩开售或用户给截图后再复测。
- **经验**：恢复/移植 pyc 后必须做两条冒烟路径——有盘口（market_only）与无盘口（model_first Elo 锚）；CLI `record` 走 `fusion_predict.py`，修复加载器后登记链路才通。

## 3. 数据采集与合并

### 3.1 fusion sales-day collect 会漏场次
- `collect --sales-day`（method=all + concern 次日）实测只采到部分场次（2026-08-02 只拿到 001、012-014 共4场），而 soccer-lottery 的 `concern&matchDate=当日` 快照有 001-011。
- **对策**：批量场景把 fusion 采集与 soccer-lottery concern 快照**按官方 match_id 合并去重**（保留 had_updated_at 更新者），再走 fusion 建模/登记。合并逻辑参考 `forward/2026-08-02_v2/merge_sources.py`。

### 3.2 陈旧盘口（observed_at > 24h）
- HAD/HHAD/HAFU 陈旧时引擎按 freshness factor 降权；全部方向性盘口 OUTDATED 时 `used_pools=[]`、模式退化为 model_first 无锚，λ 可能极端（如 λ主3.05/λ客0.075 与官方 HAD 客胜 1.79 直接矛盾）。
- **对策**：方向盘口全陈旧时按 `fusion_decision.status=AVOID_DATA_RISK` 回避，**不得把无锚 model_first 输出当作可推荐概率**。
- 单场 matchId 重采（`fetch_sporttery_full.py --match-id`）可以刷新部分盘口；官方 HAD 若长时间未更新（如 43h），属官方未变盘，不强制重采。
- 014（巴西国际）HHAD/TTG/HAFU 全旧、仅 HAD STALE → 引擎 blocked，回避，等官方刷新。

### 3.3 盘口冲突 flag
- `TTG_SCORE_CONFLICT`（比分矩阵大2.5 与 TTG 差 >7pp）、`CRS_SCORE_WEAK/LOW_OVERLAP`（CRS 与模型 Top3 重合度低）、`OVER_DISTRIBUTED_ACROSS_SCORES`（大球概率分散）出现时：Top比分与大小球结构**降级解读**，不把 1X2 等级继承给衍生市场。

### 3.4 API-Football 免费套餐与适配器限制（2026-08-03 实测）
- Free 套餐仅开放 2022–2024 赛季；查询 2025/2026 当前赛季返回 "Free plans do not have access to this season"——当前赛季赛果/赛程不得依赖该源，继续用体彩官方接口。
- 每日额度 100 次，**报错请求同样计入额度**；批量回填应一次 `/fixtures?league=&season=&from=&to=` 拉整段区间，勿逐场查询。
- 适配器 bug 已修复：`--search` 与 `--current` 不能同传（API 报 current 不能与 search 共用），现为有 search 时自动忽略 current。
- `/odds` 未在适配器中实现；免费套餐赔率覆盖不稳，市场基线仍以体彩官方采集为准。

## 4. 经验教训（追加于 2026-08-02 导出事故）

- **不要在 PRoot 环境下对 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills 用 `cp -al`（硬链接复制）**：overlay 不支持跨层硬链接，会留下 `.l2s.*` 临时文件并损坏部分 dentry（文件 open ENOENT 但 listdir 可见）。
- **写入 C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/skills 必须用 Minis 的 file_write 工具**（走 app 通道）；shell 的 python open 写入可能生成 `.l2s.xxx0001` 临时态（owner 10408）而非正式文件。
- 导出/备份用流式 `zip -r` 直接从源目录打包，不要先建 staging 复制目录。
- 若发现"listdir 有文件但 open ENOENT"：立即停止一切删除操作，先用 `file_read`（app 通道）尝试读取，再从对话/记忆/运行产物重建。

# 2026-08-15：双库看似分裂时先验证集合关系和旧链算法

- 旧 registry 的 `entry_hash` 使用 `sha(canonical_json(previous_hash + record_hash))`，不是直接对字符串字节做 SHA256。审计工具必须复用这一语义，否则会把完整链误报为全链损坏。
- 本轮验证仓库1596条是外部1555条的无冲突超集。此时安全动作是生成来源映射并停止旧路径写入，而不是复制、拼接或重算全部历史记录。
- “结构更新”不能变成“模型版本更新”；旧记录缺少 `model_version + probability_signature` 时归入 `unknown_legacy`。
