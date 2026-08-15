# football-quant-fusion 数据统一报告

## 结论

仓库登记库已经是旧外部登记库的完整、无冲突超集，不需要重写历史预测或重算哈希链。生产默认路径已统一到仓库唯一事实源，旧外部套件目录默认拒绝写入。

## 已验证事实

| 项目 | 仓库库 | 外部旧库 |
|---|---:|---:|
| registry记录 | 1596 | 1555 |
| 唯一 prediction_id | 1596 | 1555 |
| 哈希链 | 通过 | 通过 |
| 缺失预测文件 | 0 | 0 |
| 内容哈希不符 | 0 | 0 |

- 外部1555条全部在仓库中找到相同内容。
- 同一 `prediction_id` 的内容冲突为0。
- 仓库比外部多41条。
- 仓库记录中识别到34条 `m1`；其余1562条按当前证据归为 `unknown_legacy`，没有伪装成当前版本。
- `migration_map.jsonl` 保存1555条逐记录来源路径、来源哈希、旧链 entry hash、canonical路径和canonical链 entry hash。

## 实施决定

没有创建第二份1596条数据副本，也没有覆盖任何原始预测。统一动作是：验证仓库超集、生成迁移映射、把每日流水线的 backtest/odds/work 默认路径改为仓库数据根，并对旧 suite 写入增加保护。

## 验收证据

- `source_inventory.json`：两套来源的只读盘点。
- `migration_report.json`：canonical超集验证结果，`ok=true`。
- `migration_map.jsonl`：逐记录映射。
- 自动测试覆盖链验证、缺失文件、重复/冲突识别、canonical超集和旧路径拒写。
