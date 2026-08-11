# 足彩移动采集接口（导出版）

本文件夹是把"中国体彩移动端官方链路采集器"从足球量化融合技能中导出的自包含版本，可直接拿到其它项目（如 hremes / hyperframes / 自建脚本）中使用。

## 目录结构

```
project015_足彩移动采集接口导出/
├── README.md                  # 本说明
├── 01_接口文档/
│   └── sporttery_mobile_api.md # 端点、请求头、参数、字段、限速纪律
├── 02_脚本/
│   ├── fetch_sporttery_full.py        # 核心采集器（赛程/赛果 + 单场全盘口）
│   ├── sales_day_collect.py           # 批量采集（按开球日期 / 按销售日，双口径）
│   └── fetch_sporttery_history_all.py # 历史回补（断点续传、并发受限）
└── 03_示例/
    └── sample_raw.json        # 真实采集输出示例（2026-08-04 销售日，周二002）
```

## 快速上手

仅需 Python 3.8+ 标准库（urllib），无需安装第三方包、无需 API Key。

```bash
# 采集某开球日的全盘口
python 02_脚本/fetch_sporttery_full.py --date 2026-08-05 --method all --output raw.json

# 批量采集（推荐入口，按开球日期分组、matchId 去重）
python 02_脚本/sales_day_collect.py --kickoff-date 2026-08-05 --output raw_kickoff.json

# 赛后采赛果（回测用）
python 02_脚本/fetch_sporttery_full.py --results --date 2026-08-05 --output results.json

# 历史数据回补（示例：2024 全年，支持中途中断后重跑续传）
python 02_脚本/fetch_sporttery_history_all.py --start 2024-01-01 --end 2024-12-31 --output hist_2024.json --workers 3
```

## 脚本说明

### fetch_sporttery_full.py（核心）

- 唯一链路：`getMatchDataPageListV1.qry` 取赛程列表 → 按 `matchId` 逐场 `getFixedBonusV1.qry` 取 HAD/HHAD/CRS/TTG/HAFU。
- 常用参数：`--output`（必填）、`--date YYYY-MM-DD`、`--match-id` / `--match-num`（单场）、`--results`（只采赛果）、`--delay`（默认 1.5s）、`--method all|concern|result`、`--emit-input`（顺带输出模型输入 JSON）。

### sales_day_collect.py（批量）

- 新规则（推荐）：`--kickoff-date YYYY-MM-DD`，按开球日期分组，双查 all+concern 后按 `matchId` 去重。
- 旧口径：`--sales-day YYYY-MM-DD --sales-label 周二`，按销售日编号前缀筛选（如 周二001）。
- 内部调用同目录 `fetch_sporttery_full.py`（相对路径定位，导出后可整体搬走）。

### fetch_sporttery_history_all.py（历史）

- `getConditionsV1.qry` 获取可采集日期范围，逐日 `getMatchDataPageListV1.qry(method=result)` 列场次，再并发补 `getFixedBonusV1.qry`。
- 支持 `--include-league` / `--exclude-league` 子串过滤、`--max-matches` 冒烟上限、`--list-only`；按 `matchId` 断点续传，原子写盘。
- `closing_*` 字段取开球前最近一次盘口快照。

## 重要纪律

- 逐场请求必须限速（`--delay` 不低于 0.5s；历史脚本内置 0.2–0.55s 抖动 + 并发上限）。
- 收到 `403/429/567` 立即停止，稍后再跑。
- HHAD 是体彩官方三态池，不是亚洲盘两态线；CRS 只作相对排序。
- 未完成场次没有赛果，不得臆补。
- 数据仅供研究，不构成投注建议。

## 来源与版本

- 原始出处：`football-quant-fusion` 融合技能（1.4.0）内的 `sales_day_collect.py`、`fetch_sporttery_history_all.py` 与 `zu-yu-dashi-3` 的 `fetch_sporttery_full.py`（collector_version `mobile-3.5.0`）。
- 导出时间：2026-08-04；导出版相对原版仅将批量脚本中的核心采集器路径改为同目录相对定位。
