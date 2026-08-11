# big5_odds_full.csv 数据说明

- 来源：football-data.co.uk（五大联赛 mmz4281 全历史 CSV，93/94–25/26）
- 生成：`project003/02_脚本/build_big5_odds_full.py`（2026-08-03）
- 行数：59079（{'英超': 12704, '西甲': 12704, '意甲': 11726, '德甲': 10098, '法甲': 11847}）
- 覆盖：{'min': '1993-94', 'max': '2025-26'}
- 列数：141

## 列结构

- 基础列：match_uid（与 merged_big5/46696 场体系同一 uid）、league、season、div、match_date、home、away、FTR、hg、ag
- 1X2：`x2_<来源>_h/d/a`，来源 27 个（含开盘+收盘：Bet365、Pinnacle、MarketMax、MarketAvg、BetfairExchange、WilliamHill、Ladbrokes、VCBet、CL、BMG、BV、BFE 等）
- 大小球2.5：`ou25_<来源>_over/_under`，来源 10 个（B365、Pinnacle、MarketMax、MarketAvg、BFE × 开盘/收盘）
- 亚盘：`ah_<来源>_line/_home/_away`，来源 10 个

## 覆盖统计

{
  "x1x2_pinnacle_close": 24383,
  "ou25_pinnacle_close": 11534,
  "ah_pinnacle_close": 11606,
  "ah_b365_close": 12457,
  "ou25_b365_close": 12457
}

> 注：老赛季（如 93/94–2004/05）多数公司只有 1X2，亚盘/大小球/收盘盘口自 2005/06 前后才逐步齐全；缺失单元格为空。
