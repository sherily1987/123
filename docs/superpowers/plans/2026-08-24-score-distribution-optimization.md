# 比分分布数值与一致性优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变已验证生产参数的前提下，提高比分矩阵的尾部数值稳定性，并增加比分与衍生市场的一致性诊断。

**Architecture:** 保留现有双变量泊松和 Dixon-Coles 路由；先把比分矩阵计算与尾部处理做成可验证的纯函数，再在预测输出中增加一致性诊断。任何 `lambda3`、温度或代理xG参数变更必须另行样本外评估。

**Tech Stack:** Python、pytest、现有 `predict.py`。

## Global Constraints

- Sporttery仍是生产结算基准。
- 不使用赛后xG或进球倒推赛前xG。
- 不在本轮直接改动 `lambda3`、比分温度或生产版本。
- 仅有样本外回测证据的参数才可进入生产。

### Task 1: 比分矩阵尾部稳定性

**Files:**
- Modify: `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/predict.py`
- Test: `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/test_predict.py`

- [x] 为高λ和低λ场景增加矩阵总和、非负性、尾部质量测试。
- [x] 保持现有API和默认矩阵大小，新增稳定研究入口修复尾部聚合导致的数值偏差。
- [x] 运行比分相关测试和全套核心测试。

### Task 2: 市场一致性诊断

**Files:**
- Modify: `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/predict.py`
- Test: `project018_技能工作区整合/02_脚本/core/zu-yu-dashi-3/scripts/test_predict.py`

- [ ] 增加比分矩阵聚合HAD、总进球概率的可复核诊断字段。
- [ ] 诊断只用于报告和研究，不覆盖生产HAD概率。
- [ ] 验证无TTG或无赔率输入时仍不报错。

**当前证据门禁：** 已审计现有交付输入，仅有42条HAD+TTG联合记录，已结算联合样本为0，低于最低120场样本外门槛；因此本任务暂不拟合、不改生产。

### Task 3: 口径文档校准

**Files:**
- Modify: `project021_五大联赛APIFootball训练/05_交付/2026-08-16_比分参数按联赛组研究.md`
- Modify: `project021_五大联赛APIFootball训练/05_交付/2026-08-16_比分负二项研究.md`

- [ ] 明确报告中的历史基线与当前生产参数差异。
- [ ] 不把研究参数写成生产参数。
