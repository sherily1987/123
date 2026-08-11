# APIFootball 赔率候选基线设计

## 目标

五大联赛 2021/22–2025/26 的候选模型训练和离线评估改用 APIFootball `get_odds` 的 1X2 赔率，不依赖体彩历史赔率。

## 边界

- 该市场基线命名为 `provider_market`，字段必须带 `provider=apifootball.com`、`provider_only=true`、`sporttery_compatible=false`。
- 它用于候选模型的去水概率、Brier/Log Loss 比较和校准研究；不得生成体彩玩法标签，不得替代未来竞彩生产流程中的体彩官方赔率。
- `get_predictions` 不进入训练或基线；statistics、lineup、player_statistics 继续排除。
- 原始赔率和标准化结果保留在本项目 `04_素材/`，不写入密钥且不提交 Git；轻量覆盖、拒绝和训练报告可提交。

## 数据流

1. 读取现有五大联赛的标准化赛果，按全部赛历日期去重。
2. 对每个日期调用一次 `get_odds(from=..., to=...)`，缓存原始 provider 信封；接口没有 `league_id` 参数，因此不得在每条联赛循环中重复请求。
3. 按 `match_id` 把赔率联接到五大联赛赛果；只接受三个正赔率俱全的 1X2 记录。
4. 选择每场开球前最新的赔率快照，按倒数归一化为去水概率。保留 bookmaker、赔率原值、`odd_date`、选择理由和被拒绝原因。
5. 将供应商概率写入训练记录的 `provider_market_1x2`；时间切分保持原有的 60/20/20 且同一开球日不跨集合。
6. 报告中将现有 `market` 比较替换为 `provider_market` 比较，并分别报告可匹配数、覆盖率、被拒绝的赛后/时间不确定记录、Brier 和 Log Loss。

## 时间与泄漏控制

APIFootball 文档为 `get_odds` 定义 `odd_date`，但未定义其时区；本实现暂采用 **Europe/Berlin 运行时解释**，这是可审计假设而不是供应商保证。每条入选市场记录写入 `timestamp_basis="provider_undocumented_assumed_europe_berlin"`。

- 把赛事开球时间转换到 Europe/Berlin 后，只有 `odd_date < kickoff` 才可入选。
- 无法解析时间、等于或晚于开球、或没有完整 1X2 的记录均拒绝。
- 若后续确认供应商时区不同，必须重新标准化和重跑所有候选评估；旧报告不能比较或用于结论。

## 验收

- 下载器不会把任何 provider 赔率标为体彩兼容。
- 五大联赛每个赛历日只请求一次赔率；缓存可断点续跑。
- 输出包含赔率覆盖与拒绝原因，且仅使用开球前快照。
- 回归测试覆盖 match_id 联接、去水、赛后拒绝、时区假设标签、缺失赔率和 provider 基线评估。
- 完整重跑后，五个模型仍为 `candidate`；只有在供应商基线留出集验证通过后，才可另行讨论升级。
