# LLM 证据采集标准（20 源投票）

以后每场都按这个模式采。投票结果就是可用首发、可用伤停、可用近 5 场，不再等官方。

对照成品：`data/evidence_rerun33/evidence_031_加的夫城_雷克斯.md`、`evidence_022_西班牙人_莱万特.md`、`evidence_032_拉科_埃尔切.md`。

## 必须投票的三件事

1. 预测十一人（按位置计票，不是整份名单一刀切）
2. 缺阵/停赛
3. 对其他对手的最近最多 5 场正式赛

## 计票规则

- 开 20 个独立主机槽。名单由 `evidence_vote.slot_hosts(联赛)` 给出；最后两槽按联赛换成地区媒体 + 官网。
- 两个独立媒体对同一位置、同一人缺阵、同一场比分一致，即可写入。
- 平票取票多一侧；再平取结构化阵型页（FotMob / Flashscore / ESPN）。
- 封锁源只占槽、不采正文：`besoccer.com`、`whoscored.com`、`forebet.com`、`fbref.com`。
- 转载不算第二家（Yahoo = BBC，OneFootball = 原报社）。
- 403 / 验证码 / 人机验证：记缺口，不绕过。
- 揭幕战或该队本季第一场：用对其他对手的上季或最近正式赛，不得当「无近 5 场」。
- 热身票数低于正式赛则不采用。
- 空表 / fully fit 票数低于点名缺阵则不采用。
- 伤停表有名但仍被写成预测首发的，不进缺阵名单（评估票多于确认缺席同理）。
- 对不齐的比分不编造。写已对齐的场次即可，最多 5 场。
- `collected_at` 必须早于开球。已经开球的场次不得用新的赛前票；开球后确认阵容不得回写成预测票。

## 落盘步骤

1. `evidence_vote.new_pack(...)` 开空包，写入 `data/vote_packs/sporttery-<体彩id>.json`。
2. 按 源1…源20 填每家看到的 XI / 伤停 / 近 5 场（没有就写「无十一人」或「仅伤停」）。
3. 按位置计票，写入 `home_xi` / `away_xi` / `injury_line` / `home_form_line` / `away_form_line`。
4. 证据保持六节。第 1 节放 源1–20 + 三条「二十源整合」；第 3 节放投票近 5 场。
5. `runner.prepare_llm_evidence` 会自动 `apply_pack_file`。手工文件也可直接写成对照成品那样。

## 评测入口

预测登记后使用 `evaluate_llm_track.py` 评估 K3 研究轨：

```bash
python evaluate_llm_track.py \
  --predictions data/llm_records.json \
  --results data/results.json \
  --output data/llm_track_evaluation.json
```

评测只接受 `score_90_status=verified` 的90分钟赛果，按 `sporttery-<体彩id>` 去重；重复、缺失或未核验记录只写入排除审计，不进入指标分母。

## 禁止

- 不得因官方未出而整维弃权。
- 不得把整维阵容或近况标不可用。
- 不得只用一家预测站交差。
- 不得把 Playwright 当验证码绕过工具。

## EV / 凯利（2026-08-18 固化）

票比不是概率，不得算 EV。有量化轨校准 \(p\) 时走 `ev_calculator.generate_betting_recommendation`；`market_derived` 必须附带 `same_book_audit`。三个同一盘口 EV 必须全负，否则 `KELLY_SANITY_FAIL`，`action` 仍为 `skip`。禁止输出仓位。国际盘凯利指数不在本工程算，在融合技能 `hybrid-shadow` → `research.intl_kelly`。细则：融合技能 `references/kelly_research.md`。
