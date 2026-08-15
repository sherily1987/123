---
type: model-design
updated: 2026-08-15
---

# 模型版本管理方案：打破 current=0 死锁

> **落地状态：已完成（2026-08-15）**。§4 的 7 处改动已全部实现并通过测试
> （fusion tests 35/35、project021 tests 11/11、端到端回测、违规检测验证）。
> 初始 `model_version=m1`，`probability_signature=5b608c3debf8`。

## 0. 一句话结论

死锁的根因不是「样本不够」，而是 **cohort 主键用了「全量字节哈希」**——
任何一次防御性改动（crash 处理、日志、注释、字段解析）都会让哈希变化、把之前攒的
样本全部打成 legacy。解法是把 cohort 主键从「字节哈希」换成「**语义版本（model_version）
+ 概率签名审计**」，让「概率等价」的变更不再重置样本。

## 1. 死锁诊断（已实证）

### 1.1 机制链

```
build_identity()  →  哈希 8 个源文件 + 3 个 config 的「字节」  →  engine_bundle_sha256
version_cohort()  →  要求 5 字段精确匹配才算 current（含 engine_bundle_sha256）
                    ↓
任何字节改动（哪怕加一段 crash 处理、改一行注释）→ 哈希变 → 全部样本降级 legacy
```

### 1.2 本轮实测证据（verify_deadlock_root.py）

```text
当前 predict.py（核心引擎）哈希：8761e177703e
legacy 样本的 engine_sha256（predict.py 哈希）分布：
  9fe6e8e8a988  1466 场   ← 绝大多数登记用的是旧字节
  b30608d06d7f    62 场
  8761e177703e     4 场   ← 与当前一致，只有这 4 场能算 current
  22b40da0774c     2 场
  aef6f9cfb625     1 场

当前 config_sha256 = 938685852bf2，legacy 里与当前一致的仅 4 场
```

### 1.3 死锁本质

1. **字节哈希无法区分「影响概率数值的变更」与「不影响概率的变更」**。
   predict.py 的 `ENGINE_VERSION` 一直是 `3.4.4`（语义版本没变），但文件字节在
   2026-08-12 改过 → 哈希从 9fe6e8e8a988 变 8761e177703e → 1466 场全部失联。
2. **项目迭代极快**（version_manifest.json 的 notes 显示几乎每天有改动），哈希几乎
   每天变，永远攒不到 100 场同版本样本。
3. **重校准门槛绑错了对象**：真正需要「≥100 场同版本样本」才能安全重校准的是
   **模型参数**（市场权重、Dixon-Coles 系数、校准系数），而不是框架代码。改框架
   bug 不应该重置重校准进度，但当前机制会。

## 2. 方案：三层机制

### 2.1 语义版本 `model_version`（主锚）

在 `config/version_manifest.json` 新增 `model_version` 字段（如 `"m1"` 起递增，
或 `"2026-08-15.1"`）。

**只有「概率数值输出可能改变」的变更才 bump `model_version`：**

| 变更类型 | 是否 bump | 例子 |
| --- | --- | --- |
| 改概率模型参数 | ✅ bump | 市场权重、Dixon-Coles 系数、K/T 校准、去水方法、band/edge 表 |
| 改概率计算逻辑 | ✅ bump | predict.py 的 λ 反解、泊松、校准层 |
| 改框架/防御代码 | ❌ 不 bump | crash 处理、字段解析、IO、日志、报错字符串、注释 |
| 改无关脚本 | ❌ 不 bump | 采集、结算、导出、文档 |

### 2.2 概率签名 `probability_signature`（机器审计）

单独哈希「**影响概率数值的文件组**」，与全量 `engine_bundle_sha256` 分离：

```text
概率核心文件：predict.py, market_fit.py, odds_methods.py, team_strength.py
模型参数配置：market_weights.json, recommendation_policy.json
```

用途：记录在每条登记里 + manifest 里。审计脚本校验
「`model_version` 与 `probability_signature` 的一致性」——若签名变了但版本没 bump，
说明有人改了概率文件却漏了 bump 版本，立刻报警（这是纪律违规信号，不是静默通过）。

### 2.3 发布冻结纪律（防哈希漂移）

- 每次跑生产预测批次前，用脚本把当前 `model_version` + `probability_signature`
  写入一个 `release_lock.json`（发布快照）。
- 发布窗口内（建议 ≥7 天，目标是攒够 100 场同版本样本）**禁止改概率文件**；
  框架代码的 bug 修复不触发版本 bump，可以照常进行。
- 窗口结束或要改概率时，显式 bump `model_version` 开新窗口。

## 3. cohort 判定规则（改后）

```text
current  =  model_version 与当前 manifest 精确匹配
           且 probability_signature 与当前一致
legacy   =  model_version 与当前不同（历史版本）
unknown  =  无法取得 model_version 或 probability_signature（08-03 之前的旧记录）

重校准门槛 / 审阈值门槛 = 按 model_version 分组的样本数
```

对比现状：现在的 current 要求 fusion/core/engine_bundle/prediction_code/config
五个哈希全匹配；改后只要求 `model_version` + `probability_signature` 两个锚匹配，
框架代码、日志、注释的改动不再重置样本。

## 4. 实施步骤（改动清单）

1. **`config/version_manifest.json`**：新增 `model_version`（初始值 `m1`），
   并加 `probability_signature` 与 `probability_files` 清单字段。
2. **`fusion_predict_core.py::build_identity()`**：新增返回
   `probability_signature`（哈希 §2.2 文件组）与 `model_version`（读 manifest），
   保留原有 `engine_bundle_sha256`（仍作全量审计，不参与 cohort 判定）。
3. **`fusion_record.py`**：登记时把 `model_version`、`probability_signature` 写入
   `model` 字段；`cohort_key()` 改以 `model_version` 为主键（保留 route/mode 维度）。
4. **`fusion_backtest.py::version_cohort()`**：current 判定改为
   `model_version 匹配 && probability_signature 匹配`；新增 `by_model_version` 分组
   与按 model_version 的校准门禁。
5. **新增 `release_lock.py`**：发布前锁定/校验 `model_version` + `probability_signature`。
6. **新增 `audit_version_consistency.py`**：检测「签名变但版本未 bump」的违规。
7. **跑 pytest**：`project018` 与 `project021` 两套测试确保改动不破坏哈希链与登记幂等。

## 5. 迁移路径（现有 1466 场 legacy 的再利用）

### 5.1 已审计：1466 场概率不等价，不能合并（2026-08-15 定论）

1466 场用 predict.py `9fe6e8e8a988`（字节已丢失，git/仓库/外部均无副本），当前是
`8761e177703e`。用「重放测试」定论（见
`project018_技能工作区整合/06_复盘/2026-08-15_模型评测/审计_1466场概率等价性_20260815.md`）：

- 抽样 30 场，用当前 predict.py 重跑旧 input：**19 场一致、11 场（37%）概率不同**；
- 差异根源是 `market_freshness` 等**市场锚处理逻辑的实质改动**（旧版对回填记录判
  市场锚不可用 → `market_prob=None` → 对称先验 `37.4/25.3/37.4`；新版对同样 odds
  用 power 去水得真实概率），不是展示层或注释级差异。

**结论：走保守路径**——1466 场不归入 current，从 `model_version=m1` 重新累积；
1466 场 legacy 保留用于 walk-forward OOS 训练/对照。这反证了本方案的必要性：
若当时有语义版本机制，市场锚逻辑的改动会在当刻 bump 版本并标记「概率变更」，
而不是事后靠重放测试才能发现。

### 5.2 legacy 的兜底用途

即使 1466 场不能归入 current，它们仍可：
- 作为 walk-forward OOS 的**扩展训练/验证集**（不同版本可作稳健性对照）；
- 用于验证「按 model_version 分组后，各版本的概率质量是否单调改进」。

## 6. 风险与纪律

1. **语义版本靠人判断**，存在「该 bump 没 bump」的漏判风险 → 由 §2.2 的
   `probability_signature` 审计脚本兜底（签名变而版本未变即报警）。
2. **发布窗口与敏捷迭代的张力**：窗口内禁止改概率文件可能拖慢开发 →
   约定「概率文件的改动集中到窗口边界提交」，非概率改动不受限。
3. **不可回退**：本方案只改 cohort 判定与登记字段，**不动 registry 哈希链**、
   不动预测产出、不动结算——历史记录的可验证性（previous_hash/entry_hash 链）保持完整。
4. **验收标准**：
   - 改一行框架日志后，`model_version`/`probability_signature` 不变，样本不再降级 legacy；
   - 改一个校准常量后，审计脚本能报出「签名变但版本未 bump」；
   - 新登记的预测能在下一次全量回测中落入 `current`（不再是 0）。
