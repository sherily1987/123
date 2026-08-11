# 足预大师3.4.1回测规范

## 存储
默认：`C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/shared/zu-yu-dashi-3/backtest/`。技能目录只放代码。预测和赛果分开；已有记录禁止静默覆盖。

## 正式预测登记

```sh
python3 scripts/record_prediction.py --input input.json --output output.json --predict --snapshot T-24h
```

每次生成`match_id`、`prediction_id`、输入/输出/引擎SHA-256，并追加链式registry。必须在开赛前登记；更新预测创建新snapshot，不覆盖旧预测。测试/敏感性分析可不登记。**开球时间必须带时区**，例如`2026-08-01T01:00:00+08:00`；无时区会被登记器拒绝。

### 同快照去重（3.4.1 补丁）

同一 `(match_id, snapshot_type)` **只能贡献一个回测样本**。重复登记会让同一场比赛在指标里被计权两次，人为放大样本量并按该场结果扭曲 Brier/ECE。两层防护：

1. **登记层**：`record_prediction.py` 检测到同一比赛同一快照已存在时，打印 `status=skipped_duplicate_snapshot` 并以 exit 0 退出（幂等，重跑流水线不报错）。确需覆盖时显式加 `--replace-snapshot`。
2. **回测层**：`backtest.py --store` 读取时按 `(match_id, snapshot_type)` 去重，保留 `created_at` 最新的一条，并在输出中报告 `deduped_duplicates` 与 `deduped_detail`。历史上已写入的重复记录不删除（链式 registry 不可变），只是不重复计权。

同一比赛的**不同**快照（T-7h / closing）仍各自独立，但必须**分别**统计，不得混入同一次回测。

## 赛果回填

```sh
python3 scripts/settle_result.py --match-id ID --score-90 1-1 --score-et 0-0 --penalty-winner away --advanced away --source UEFA
```

1X2只按90分钟；晋级按加时/点球后最终结果。联赛不填advanced。

## 回测

登记库：
```sh
python3 scripts/backtest.py --store C:\Users\Administrator\.codex\skills\football-quant-fusion-suite/shared/zu-yu-dashi-3/backtest --snapshot closing
```
离线JSON：
```sh
python3 scripts/backtest.py history.json
```

离线每场含正常predict输入及`actual:[主队90分钟进球,客队90分钟进球]`。计算1X2准确率、Brier Sum/Mean、Log Loss、校准分箱、ECE、基础频率与市场基线、比分Top1/3/5与比分Log Loss、O/U2.5、BTTS、晋级。Brier Sum为三分类平方误差之和，Mean=Sum/3。

## 限制
- 回测使用登记时未四舍五入概率最理想；当前引擎仅保存百分比，后续版本应增加raw概率与完整比分矩阵。
- 不能用赛后数据重建赛前预测。
- 按模型版本、snapshot和时间隔离；小样本不得宣称优于市场。
- 同一 `(match_id, snapshot_type)` 只算一个样本；回测输出的 `deduped_duplicates` 若大于 0，说明登记库存在重复登记，应核查流水线是否被重复触发。
- ROI需要赛前明确策略、盘口赔率与投注方向；当前基础回测不计算ROI。

