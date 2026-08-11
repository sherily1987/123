# fusion_predict.py 源码重建报告

日期：2026-08-02　任务：把损坏源码的 `fusion_predict`（此前只能靠 cpython-312 字节码 + 运行时补丁运行）重建为可读源码。

## 背景

- 原 `fusion_predict.py` 源码在文件系统同步事故中损坏，此前通过 `fusion_predict_core.cpython-312.pyc`（33KB）加载运行，并带两个运行时 hack：
  1. 注入 `market_freshness_meta = {}` 修 NameError；
  2. 把 `recommendation_policy.py` 复制进 `__pycache__` 修路径。
- 字节码不可审计、不可迭代，是评估报告 S1 的核心风险。

## 重建方法

1. `marshal` 解析 pyc 得到完整 code object（模块 + 14 个函数）；
2. `dis` 全量反汇编（340KB），逐函数还原控制流、常量、异常表；
3. 手写等价源码 `fusion_predict_core.py`（约 640 行），保留全部公共 API：`main / predict_one / load_core / decision / build_goal_rate / build_injury_view`；
4. `fusion_predict.py` 改为纯源码入口（不再引用任何 .pyc）。

## 重建中确认并修复的缺陷

1. **NameError 根因**：字节码在"无市场锚/陈旧盘口"分支引用从未赋值的模块级 `market_freshness_meta`（原源码就有的 bug，靠外层补丁掩盖）。源码中显式初始化为 `{}`，修复进根。
2. **容器路径残留**：`CORE_DIR` 默认值 `/var/minis/...` 改为本机路径，并保留 `FUSION_CORE_DIR` 环境变量覆盖。
3. 重建过程中还发现并修正了一处反编译误读（ledger_audit 的 `lambda_prior not in ledger_fields` 判断），已通过输出对比回归确认。

## 验证结果（全部通过）

| 验证项 | 结果 |
| --- | --- |
| 4 场批量（hybrid.json）旧 pyc vs 新源码 | **逐字节一致**（149,016 字符） |
| 无盘口 model_first 冒烟（原 NameError 崩溃路径） | exit 0，正常输出 UNFITTED 门控 |
| `fusion_cli.py record` 登记链路 | exit 0，预测+登记成功 |
| `fusion_predict.py` 新入口转发 API | 与旧加载器签名一致 |

## 产出

- 引擎内：[fusion_predict_core.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\fusion_predict_core.py>)（源码，生产入口）、[fusion_predict.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\fusion_predict.py>)（源码入口）
- 本目录：`fusion_predict_core.py` 副本、`fusion_predict_core_dis.txt`（反汇编底稿，可审计）
- 旧的 `fusion_predict_workaround.py`（project005 交付目录）已过时，可删除

## 下一步（R0 剩余项）

## R0 完成情况（2026-08-02）

1. ~~重建缺失脚本~~ **已完成**：
   - [fusion_backtest.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\fusion_backtest.py>)：融合层全参数回测（Brier/LogLoss/ECE/比分Top1-5/OU/BTTS/CLV，按版本/联赛/快照分组；`fusion_cli.py backtest` 已自动启用，实测 10 个已结算样本出指标）；
   - [football_data_adapter.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\football_data_adapter.py>) + [football_data_enrich.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\football_data_enrich.py>)：football-data.org v4 适配与输入 enrich（Key 仅环境变量；无 Key 时干净降级 UNAVAILABLE）；
   - [apply_time_decay.py](</C:\Users\Administrator\.codex\skills\football-quant-fusion-suite\skills\football-quant-fusion\scripts\apply_time_decay.py>)：委托 zu-yu-dashi-3 的时间衰减 λ 先验实现；
   - wechat 桥接：无需重建（soccer-lottery 脚本在，fusion_cli 路径已通，已实测 --help 正常）。
2. ~~修复核心 predict.py 两处崩溃~~ **已完成**：ZeroDivisionError/TypeError 根治于核心（见 `2026-08-02_核心引擎崩溃修复记录.md`），融合层 try/except 降级为纯安全网。
3. ~~接入比分/半场温度校准~~ **已完成**：T=1.4/1.22 已进 predict.py，`top_scores/ht_top_scores` 用校准矩阵，`derived_market_status.top_scores → CALIBRATED`；4 场批量回归确认 1X2/OU/BTTS/HHAD 零扰动。
4. 全量回归：本会话所有引擎改动后，4 场批量输出与校准后基线逐字节一致（151,437 字符）。

## 剩余（R1 起）

- `market_ablation.py`（fusion_cli market-ablation 命令）仍缺失，未列入本次范围；
- `football_data_adapter` 需要用户提供 `FOOTBALL_DATA_API_KEY` 才能联调（当前无 Key）；
- `__pycache__` 旧 pyc 可清理；SKILL.md/pitfalls 中"字节码加载"表述待更新。

---
概率模型输出，非投注建议。
