# 版本与数据迁移

生产登记、赔率移动和工作目录统一位于仓库内 `project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/`。路径优先级为命令行参数、专用环境变量、仓库默认值。旧外部 suite 目录只作历史读取，默认拒绝生产写入。

版本分为：匹配 `model_version + probability_signature` 的 `current`、可识别旧版本 `legacy`、证据不足的 `unknown_legacy`，以及只表示结构更新的 `schema_migrated`。旧记录不得通过补字段伪装成 current。

自 1.5.0 / model m2 起，发布身份拆为三条相互独立的签名：

- `probability_signature`：只覆盖会改变概率数值的核心算法、生产路由和概率配置；
- `decision_policy_signature`：模型 build identity 的推荐/决策治理 bundle 发布审计签名；
- `direction_policy_signature`：单场 `direction_policy` 专用，只覆盖方向分类配置与实现，
  固定声明 `direction_policy_signature_scope=direction_policy_config_and_implementation`；
  两者不得互换或用同一字段承载；
- `evidence_pipeline_signature`：覆盖赛前采集、特征适配与LLM证据入口。

概率代码改变必须升级 `model_version` 并重建发布锁。只改推荐政策或证据管线不得伪装成新概率模型，但正式登记仍须冻结三条签名以便复现。

2026-08-15审计确认：仓库 registry 1596条、外部 registry 1555条，两条链完整；外部记录全部存在于仓库且内容相同，仓库多41条，其中34条识别为 `m1`。因此不重写历史预测或原链，只生成1555条来源映射并切断旧默认写入口。审计产物位于 `project018_技能工作区整合/05_交付/数据统一迁移/2026-08-15/`。

回滚时只回退路径提交；不要让任一数据副本反向覆盖另一份。旧外部库保持只读，作为迁移前证据。
