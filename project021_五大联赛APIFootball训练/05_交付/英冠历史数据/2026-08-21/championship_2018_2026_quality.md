# 英冠 2018/19—2025/26 数据质量摘要

生成时间：2026-08-21T13:55:40.186Z

- 总场次：**4416**（8 季 × 552）
- 字段：**85**
- 原始球队名：**44**；标准化球队名：**44**
- 重复比赛键：**0**；核心字段缺失：**0**；比分与 FTR 不一致：**0**

## 分赛季核验

| Season | Rows | Fields | Teams | Date range | Closing 1X2 | Shots on target |
|---|---:|---:|---:|---|---:|---:|
| 2018-19 | 552 | 62 | 24 | 2018-08-03–2019-05-05 | 552 | 551 |
| 2019-20 | 552 | 106 | 24 | 2019-08-02–2020-07-22 | 552 | 552 |
| 2020-21 | 552 | 106 | 24 | 2020-09-11–2021-05-08 | 552 | 552 |
| 2021-22 | 552 | 106 | 24 | 2021-08-06–2022-05-07 | 552 | 552 |
| 2022-23 | 552 | 106 | 24 | 2022-07-29–2023-05-08 | 552 | 552 |
| 2023-24 | 552 | 106 | 24 | 2023-08-04–2024-05-04 | 552 | 552 |
| 2024-25 | 552 | 120 | 24 | 2024-08-09–2025-05-03 | 552 | 552 |
| 2025-26 | 552 | 132 | 24 | 2025-08-08–2026-05-02 | 552 | 552 |

## 使用边界

- FTHG/FTAG/FTR are full-time labels; HT* are half-time labels.
- HS/AS/HST/AST/cards/corners are post-match statistics and must not be used as pre-match features without time-aware lagging.
- Canonical team names are a presentation/modeling view; existing fd_e1 JSONL training IDs remain source-stable and are not silently renamed.
- Missing closing odds in 2018-19 are preserved as blanks rather than backfilled from later snapshots.

## 来源指纹

- E1_1819.csv: 112eedf787e26e00aac1442ef86e7fee5d4a43f86552ff2dac31ceb95a849487
- E1_1920.csv: f31450c623c0b74b89692584a85924cc652d33ec89757acf4b2dda5e26261d57
- E1_2021.csv: cf93295e310c60e5b97ae7466d772f8ec6a908ad401e38fceb7e8617369d5073
- E1_2122.csv: a181451be4801b9f838daf5f6aaf21e9f09d36042be9e6c15388e71001e772ea
- E1_2223.csv: cd38ab0586ea8cb4d573c363ff70749117f116da5b2741e5b0ea37da05860b1b
- E1_2324.csv: 5737f6cc95c95092b28317f41d3123e2fb09345434efc1c84bbdf15830849ab3
- E1_2425.csv: f34c340446c916374be66bdc2fb25b87ee7f2662712ca009653d03ac705535f9
- E1_2526.csv: 98954c319950f19158624b17a154ef1c56eb7b8d169ef317f28f06d11d0b9a74

标准化文件：`F:\HM足球比赛预测\project021_五大联赛APIFootball训练\05_交付\英冠历史数据\2026-08-21\championship_2018_2026.csv`