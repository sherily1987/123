# football-quant-fusion 技能导出包（给 Hermes）

导出版本：skill 1.4.0 / core 3.4.4
导出时间：2026-08-06
来源：本机 Codex 技能 `C:\Users\Administrator\.codex\skills\football-quant-fusion`（与 football-quant-fusion-suite 内同源）

这是一个**自包含、可移植**的技能包：把 Codex 里正在用的「足球量化融合引擎」完整复制出来，并已把脚本中指向本机的绝对路径改写为包内相对路径，拷到任意一台有 Python 的机器即可运行。

## 一、三种接入 Hermes 的方式（按方便程度排序）

### 方式 A：Hermes 与 Codex 在同一台电脑（零拷贝，推荐）

直接让 Hermes 读取并遵循本机技能入口，不需要导出任何文件，永远是最新版：

> 请读取并严格遵守 `C:\Users\Administrator\.codex\skills\football-quant-fusion\SKILL.md`。
> 需要跑脚本时，在 `C:\Users\Administrator\.codex\skills\football-quant-fusion\scripts\` 下用 `python fusion_cli.py ...` 执行。

### 方式 B：Hermes 支持导入「技能目录 / 知识库文件夹」

把本包里的 `01_技能本体/football-quant-fusion/` 整个文件夹放到 Hermes 的技能目录（或让它把该路径加为知识库根目录），并告诉它「先读 SKILL.md」。核心引擎依赖在 `02_核心引擎依赖/`，共享数据在 `03_共享数据/`，路径已在脚本中改写，解压后即可用。

### 方式 C：Hermes 只能粘贴文本（单文件手册）

把 `05_单文件手册/SKILL_完整手册.md` 的全文一次性粘贴给 Hermes，作为它的常驻技能说明；脚本仍留在本包目录里，需要执行时让 Hermes 用 `python` 直接调用本包内的脚本路径。

## 二、目录结构

```
project017_football-quant-fusion技能导出/
├── README.md                      本说明
├── export_skill_for_hermes.py     一键重新导出脚本（技能升级后再跑一次）
├── 01_技能本体/football-quant-fusion/
│   ├── SKILL.md                   技能主文档（Hermes 首先读这个）
│   ├── config/                    市场权重 / 推荐门控 / 版本清单
│   ├── references/                数据契约 / 输出契约 / 踩坑记录 / 功能映射等
│   └── scripts/                   全部可执行脚本（fusion_cli 等）
├── 02_核心引擎依赖/zu-yu-dashi-3/
│   ├── SKILL.md                   底层核心引擎说明
│   ├── references/
│   └── scripts/                   核心库：market_fit / backtest_lib / predict 等
├── 03_共享数据/football-quant-fusion/
│   ├── datasets/                  精选小数据（understat xG 等）；大训练集未打包（见下）
│   ├── odds/                      盘口移动日志（production_movement.jsonl）
│   ├── backtest/                  回测注册表目录（空骨架，首次运行自动建）
│   ├── forward/  metrics/  today/ 运行时目录（空骨架）
├── 04_示例/
│   ├── sample_input.json          单场示例输入（塞萨洛 vs 安德莱）
│   └── 运行示例.md                 从采集到回测的完整命令示例
└── 05_单文件手册/SKILL_完整手册.md  全文合并版（给只能粘贴文本的 Hermes）
```

## 三、运行依赖

- Python 3.11 或 3.12（脚本自带 3.12 探测；没有 3.12 时回退当前解释器）
- 标准库即可完成采集 → 预测 → 登记 → 回测主流程
- 可选环境变量（不设置则跳过对应功能，不影响核心预测）：
  - `API_FOOTBALL_KEY`：API-Football v3，历史赛果/伤停/积分榜（免费 100 次/天）
  - `FOOTBALL_DATA_API_KEY`：football-data.org，赛程/积分补充
- 需要联网访问中国体彩移动端接口（采集盘口）与 API-Football（历史数据）

## 四、快速开始（在本包根目录执行）

```sh
# 1) 采集今日竞彩销售日盘口（自动合并跨午夜场次）
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py collect --sales-day YYYY-MM-DD --output raw.json --emit-input input.json

# 2) 批量预测（胜平负/比分/大小球/BTTS/让球）
python 01_技能本体/football-quant-fusion/scripts/fusion_predict.py input.json > output.json

# 3) 登记 prematch 快照到待回测库
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py record --input input.json --output model_output.json --snapshot prematch

# 4) 开球后回填赛果并回测
python 01_技能本体/football-quant-fusion/scripts/fusion_cli.py settle --date YYYY-MM-DD
python 01_技能本体/football-quant-fusion/scripts/backtest_dual_track.py --date YYYYMMDD
```

详细命令见 `04_示例/运行示例.md`。

## 五、技能升级后如何重新导出

在本机技能更新后，重新运行一次：

```sh
python export_skill_for_hermes.py            # 默认导出 + 路径改写 + 打包 zip
python export_skill_for_hermes.py --with-datasets   # 额外带上大数据训练集（约 1.2GB）
python export_skill_for_hermes.py --no-zip   # 只更新目录不重新打包
```

## 六、纪律红线（导出内容已包含，Hermes 使用时必须遵守）

- 数字只由脚本产生；LLM 轨道只给方向与比分偏好，不输出伪概率
- `market_only` 本质是复述市场盘口，不声称优于市场（Brier 全池 0.627 vs 市场 0.586）
- 融合组合/edge 路径仍为 UNFITTED_FUSION，不生成数值 confidence、不出胆
- 比分 Top1 单格概率约 8%–11%，比分天然比胜平负不确定
- 最终输出必须带「概率模型输出，非投注建议」

## 七、已知限制

- 大数据训练集（`sporttery_all_leagues_history_2026_with_big5.json` 等，共约 1.2GB）默认不打包；如 Hermes 需要完整历史建模样本，用 `--with-datasets` 重新导出。
- 历史回测注册表（约 57MB）默认不打包；预测登记会从空骨架开始积累。
- 脚本内指向本机的绝对路径已改写为包内相对路径；若你在本机直接使用原技能目录（方式 A），不受影响。
- 免费 API-Football 仅覆盖 2022–2024 赛程，2025/2026 当前赛程会报错，属正常限制。

**概率模型输出，非投注建议。**
