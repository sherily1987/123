# 足预大师3.0字段与验证

## 阻断字段

- `home`, `away`, `stage`
- `kickoff`，或在 `context_confirmed=true` 时允许明确轮次语境替代
- 至少一组完整强度锚：
  1. `odds`恰好3项且每项>1；或
  2. `elo_home`与`elo_away`均存在；或
  3. `lambda_home`与`lambda_away`均存在且>0

单边Elo/λ不构成强度锚。

## 合法范围

| 字段 | 范围 |
|---|---|
| Elo | 800–2400 |
| λ | 0.05–6.0 |
| injury/rotation | 0–0.5 |
| attack_absence/defense_absence/gk_absence | 0–0.5 |
| motive | 0.5–1.35 |
| defense_risk | 0–0.5 |
| home_adv/altitude/travel | -0.3–0.4 |
| market_weight | 0–1 |
| penalty_home_prob | 0.35–0.65 |
| first_leg | 两项非负整数 |
| ah_line | 0.25的倍数，主队视角 |

## 字段状态

`VALID`, `MISSING`, `UNAVAILABLE`, `UNVERIFIED`, `OUTDATED`, `IMAGE_EXTRACTED`, `ASSUMED`, `PROXY_XG`, `EXPLICIT_XG`。

推荐在 `field_meta` 中保存：

```json
{
  "injury_home": {
    "status": "VALID",
    "source": "club official",
    "observed_at": "2026-07-29T08:00:00+08:00",
    "note": "confirmed no absences"
  }
}
```

数值为0或布尔值false仍算已提供。

## 模式选择

- `market_only`：只有赔率；最终1X2采用市场公平概率，矩阵用于比分/衍生盘。
- `hybrid`：赔率 + Elo或其他独立锚；λ融合后，可做轻度市场后验校准。
- `model_first`：成对显式λ；市场仅用于校准和对比。
- 未指定时脚本自动判定。

## 推荐输入

```json
{
  "home":"Home FC", "away":"Away FC",
  "stage":"UCL Q2 Leg2", "kickoff":"2026-07-29T23:00:00+08:00",
  "odds":[2.06,3.10,3.11], "first_leg":[0,1],
  "elo_home":1294, "elo_away":1457,
  "attack_absence_home":0, "defense_absence_home":0,
  "gk_absence_away":0.12,
  "ah_line":-0.75, "auto_motive":true,
  "field_meta":{}, "assumptions":[], "seed":42
}
```

## 质量评分

分别计算：
- `completeness_pct`：字段覆盖。
- `source_reliability_pct`：从`field_meta`来源等级计算；缺元数据则保守。
- `freshness_pct`：按采集时间与有效期衰减。
- `overall_pct = 0.50*完整度 + 0.30*来源 + 0.20*新鲜度`。
- `market_dependency_pct`：根据λ来源与最终校准权重报告，不等同于质量。
