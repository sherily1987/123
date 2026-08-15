# 统一输入与证据账本（data contract）

> ⚠️ REBUILT 2026-08-02：原文件损坏后基于 SKILL.md 与 zu-yu-dashi-3/references/fields_schema.md 恢复。底层字段合法范围/状态枚举详见底层 fields_schema.md。

## 1. 单场输入（fusion_predict 裸 dict）

```json
{
  "home": "蔚山现代",
  "away": "安养FC",
  "competition": "韩职",
  "stage": "韩职",
  "kickoff": "2026-08-02T18:30:00+08:00",
  "mode": "market_only",
  "odds": [1.86, 3.45, 3.32],
  "context_confirmed": true,
  "field_meta": {
    "odds": {"reliability": 100, "freshness": 100,
             "source": "中国体彩网移动端官方固定奖金接口",
             "observed_at": "2026-08-02 12:31:05"},
    "hhad": {...}, "ttg": {...}, "hafu": {...}, "crs": {...}
  },
  "hhad": {"line": -1.0, "odds": [3.6, 3.7, 1.72]},
  "ttg": {"odds": [14.0, 5.5, 3.4, 3.4, 5.1, 9.0, 16.0, 23.0]},
  "hafu": {"odds": [3.1, 14.0, 30.0, 4.9, 5.2, 7.5, 23.0, 14.0, 5.5]},
  "crs": {"1-0": 8.25, "0-0": 14.0, ...},
  "assumptions": [],
  "sporttery_meta": {"match_id": 2040688, "match_num": "周日001",
                     "home_team_id": 1090, "away_team_id": 1035899}
}
```

## 2. 阻断字段（缺则停止）

- `home` / `away` / `stage`
- `kickoff`（或 context_confirmed=true 时明确轮次语境）
- 至少一组完整强度锚：`odds`（3项均>1）**或** `elo_home+elo_away` **或** `lambda_home+lambda_away`（均>0）。单边不构成锚。

## 3. 数据模式

- `market_only`：只有市场赔率；1X2=去水市场概率，比分衍生盘依赖市场反解。**只能概率排序，不给价值优势**。
- `hybrid`：赔率 + 独立强度/人员事实；市场锚 + 独立信息软约束（如 lambda_prior 相对偏差惩罚，权重 0.02 量级，须归一化）。
- `model_first`：成对真实 λ/xG 或可靠独立模型优先，市场只校准/对照。无锚时输出须标 UNFITTED_NO_VALUE / AVOID_DATA_RISK。

## 4. 体彩盘口换算

- HHAD 是体彩 3 态让球盘，**不得自动映射为亚洲盘 ah_line**。
- TTG 8档（0,1,2,3,4,5,6,7+）完整，进联合拟合；无 TTG 时用现有市场反解。
- HAFU 9宫格（hh,hd,ha,dh,dd,da,ah,ad,aa）进联合拟合；可推半场1X2（HALF_SHARE=0.45）。
- CRS 只做**同场相对比分排序**对照（crs_overlap_audit），不归一化进拟合（边际40.9%过高）。

## 5. 证据账本（adjustment_ledger）

人员/战意/环境系数必须结构化登记：

| 字段 | 含义 | 合法范围 |
|---|---|---|
| injury_home/away | 伤停强度 | 0–0.5 |
| rotation_* | 轮换 | 0–0.5 |
| attack_absence_* / defense_absence_* / gk_absence_* | 缺阵 | 0–0.5 |
| attack_motive_* | 必须抢攻 | 0.5–1.35 |
| defense_risk_* | 压上风险 | 0–0.5 |
| home_adv / altitude / travel | 环境 | -0.3–0.4 |
| ah_line | 亚洲盘线 | 0.25 倍数，主队视角 |

每条含：事实、来源、采集时间、映射值、依据、是否已回测。未回测标 UNFITTED。

## 6. 字段状态枚举

通用证据状态：`VALID` / `MISSING` / `UNAVAILABLE` / `UNVERIFIED` / `OUTDATED` / `IMAGE_EXTRACTED` / `ASSUMED` / `PROXY_XG` / `EXPLICIT_XG`。
数值 0 或 false 仍算已提供。`field_meta.<pool>.observed_at` 必须与 kickoff 同时区（Asia/Shanghai），按相对开球时间算新鲜度：FRESH(<6h)/AGING(<12h)/STALE(<24h)/OUTDATED(≥24h)。

衍生市场必须使用独立状态：`VALID` / `UNAVAILABLE` / `UNFITTED` / `NOT_OFFERED`。其中 `UNFITTED` 允许保留研究值但禁止生产推荐；`NOT_OFFERED` 表示该市场未开售或不适用。人工复核写入 `manual_check`，不得覆盖脚本生产字段。

## 7. APIfootball赛前特征

适配器原始数据统一放在`api_football`，经过
`apifootball_model_features.py`后生成`api_features`：

```json
{
  "api_features": {
    "provider": "apifootball.com",
    "as_of": {"kickoff": "...", "collected_at": "...", "usable": true},
    "pre_kickoff_usable": true,
    "history_matches": 114,
    "team_strength": {
      "status": "VALID",
      "lambda_home": 1.85,
      "lambda_away": 1.66,
      "source": "dixon_coles_team_strength"
    },
    "rolling_statistics": {},
    "standings": {},
    "lineups": {},
    "official_prediction": {
      "prob_home": 42,
      "prob_draw": 28,
      "prob_away": 30,
      "not_xg": true
    },
    "external_market": {"bookmaker_rows": 10},
    "no_future_leakage": true
  }
}
```

时间规则：

- `api_features.as_of.usable=false`时，statistics、standings、lineups、official_prediction、external_market只能保留原始审计，状态写为`POST_MATCH_NOT_USABLE`；
- `get_statistics`中的射门、射正、禁区内射门只能进入后续比赛的滚动历史特征；
- `get_predictions`只能输出`p_apifootball`，不得改名为xG；
- `get_odds`只能进入外部市场层，不进入独立球队强度训练；
- 候选 `lambda_prior` 默认只写入 `research_candidate`，生产保持 `market_only`。只有显式 `--research-route` 才可注入，并必须标 `research_only=true`、包含 `adjustment_ledger`；未完成联赛OOS校准时标记 `UNFITTED`，不得登记进生产回测库。
