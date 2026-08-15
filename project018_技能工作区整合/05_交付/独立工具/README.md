# 足球预测量化工具（独立工具）

双击 `fusion_tool.bat` 即可使用——不依赖 Codex / DSH 会话，任何 Windows 终端可跑。
入口是 `fusion_menu.py` 的交互式菜单，底层调用 `football-quant-fusion` 技能脚本。

## 启动

1. 双击 `fusion_tool.bat`（或给它建个桌面快捷方式）；
2. 菜单输入数字选择功能，按提示操作；
3. 每次执行的结果自动存日志到 `logs/` 目录（`YYYYMMDD_HHMMSS_<功能>.log`）。

## 菜单功能

| 编号 | 功能 | 底层命令 |
| --- | --- | --- |
| 1 | 每日开售预测（采集+预测+登记） | `fusion_cli.py daily-pipeline --store <仓库内>` |
| 2 | 赛果回填（结算） | `fusion_cli.py settle --store <仓库内>` |
| 3 | 全量回测（融合模型报告） | `internal_backtest.py`（强制仓库内唯一事实源） |
| 4 | 双轨回测（量化 vs LLM，按日期） | `backtest_dual_track.py` |
| 5 | 版本管理（锁定发布 / 审计漂移） | `release_lock.py` / `audit_version_consistency.py` |
| 6 | 查看最近报告（记事本打开） | — |
| 7 | 欧冠夺冠模拟（Monte Carlo） | `fusion_cli.py tournament` |
| 8 | 国际盘对照 | `fusion_cli.py odds-intl` |
| 9 | 生成 PPT 报告 | `gen_report_ppt.py`（预测结果 / 回测报告 → PPT） |

### 实时进度显示（2026-08-15 起）

运行长命令时窗口实时显示：旋转指示 + 已用时长 + **子流程逐步输出**（settle 逐场、
采集逐场、登记逐场的进度都能看到）。之前"日志 0 字节、像卡住"的问题已修复——
根因是整条调用链（菜单→fusion_cli→流水线→子命令）每层都用 `capture_output` 把下层
输出吞掉，现已全部改为实时转发。

## 关键纪律（与 AGENTS.md / 评测规则一致）

- 所有登记/结算/回测**显式 `--store` 指向仓库内唯一事实源**
  `project018_技能工作区整合/04_素材/shared-data/football-quant-fusion/backtest/`，不碰外部套件副本。
- 回测（菜单 3）走 `internal_backtest.py`：强制把 registry 里指向外部套件的预测路径
  重定向到仓库内 predictions，不改 registry 哈希链。
- 版本管理（菜单 5）：生产预测批次前先「锁定发布」；改过概率文件后跑「审计」，
  若报 VIOLATION 说明改了概率但忘了 bump `config/version_manifest.json` 的 `model_version`。

## 环境依赖

- Python（系统 `python` 命令可用即可，菜单内部自动切换融合脚本所需的 3.12 运行时）；
- 用户级环境变量 `FUSION_DATA_ROOT` / `FUSION_CORE_DIR` / `FUSION_WORKSPACE_ROOT`
  （已配置，若换机器需重设）；
- 网络：菜单 1/2 需要访问体彩官方接口，菜单 8 需要 The Odds API key。

## 修改工具

- 菜单内容改 `fusion_menu.py`；
- 工具目录下各文件是仓库交付物，改动请按项目纪律记录；
- 每日预测/回测类任务本身仍归 `project021/05_交付/每日开售预测/<日期>/`，本工具只是入口。
