---
name: zu-yu-dashi-3.4.1
description: 足预大师3.4.4，校准导向的职业足球量化预测技能。支持中国体彩移动端官方HAD/HHAD/CRS/TTG/HAFU采集、多市场联合λ拟合、胜平负、Top比分、晋级、大小球、BTTS、亚洲盘、联赛感知校准（五大联赛与其余联赛分离）、赔率区间参照与回测审计。适用于欧冠、欧联、欧协联、联赛和杯赛。用户提到足预大师3.0/3.4.1/3.4.4、足球预测、胜平负、让球、大小球、晋级、盘口分析、跨模型对比时触发。不用于纯直播比分查询。
version: 3.4.4
---
# 足预大师 3.4.4

以可审计数据和 Python 为唯一数字出口的足球量化预测技能。**自包含知识库**：`references/` 下含建模方法、数据源、字段规范、回测规范、输出模板、**踩坑记录**（`pitfalls.md`），任何模型加载本 skill 后按文档执行即可复现全部能力，无需重新摸索。

## 版本历史

- **3.0**：成对字段验证、零值误判、市场重复计权、四分之一亚洲盘、加时/点球建模、攻防分离伤停与战意、质量评分拆分。
- **3.1**：常数出处标注、赛事级 goal_total、可靠性缺陷自报（`reliability_flags`）、输入敏感性区间（`sensitivity`）、校准回测工具（`backtest.py`）。
- **3.2**：**λ 求解从线性映射改为数值反解**。旧法强制 `λ主+λ客 ≡ total`，压缩强弱差；3504场回测实测使Brier比市场差0.0070。新法反解出能还原市场1X2的λ，损失归零。⚠️ **3.2 是「无损」不是「更优」**——忠实复现市场，未超越。
- **3.3**：模式—字段一致性验证、体彩Selling资格与时区、结构化HHAD去水审计、双重主场警告、market_only衍生市场敏感性、原始概率和完整比分矩阵、统一版本登记、离线/登记库双回测、市场/频率基线、校准分箱与ECE。
- **3.4**：HAD＋HHAD＋O/U＋TTG多市场联合λ拟合；免费多平台xG标准化；StatsBomb Open Data事件导入；每日体彩前瞻样本流水线；`fetch_sporttery_full.py` 采集CRS/TTG/HAFU。当前实现已切换到移动端官方`getMatchDataPageListV1`＋逐场`getFixedBonusV1`链路。
- **3.4.4**（本次）：**联赛感知校准层**。`predict.py` 新增 `league_calibration()`，按比赛 `competition/stage/league` 精确识别五大联赛（英超/西甲/德甲/意甲/法甲，含英文名与 football-data Div 码 E0/SP1/D1/I1/F1）。五大联赛使用 2026-08-02 football-data 46,696 场时间外推验证的校准参数 `K=1.0/T=1.0`（test 13,997 场 Brier 0.577228、ECE 0.00442，优于原参数 Brier 0.578084、ECE 0.01410）；**其余联赛沿用体彩 3.4.2 拟合参数 `K=1.14/T=0.96`，行为与 3.4.3 完全一致**。次级联赛（英冠/英甲/西乙/德乙/意乙/法乙）不会被误判。输出 `calibration.league_key`/`league_basis` 供审计。⚠️ 五大联赛参数迁移未经体彩侧五大联赛子集复验；若体彩五大联赛场次也按 BIG5 识别，需留意此点。
- **3.4.3**：把校准从 1X2 扩展到衍生盘口。同一 1348 场数据集、同一时间序列切分，逐盘口拟合并**逐项在测试集验证**：O/U2.5 与 O/U3.5 采用 Platt 校准（ECE 分别改善 27.2%、41.7%）；**BTTS 实测校准反而恶化 24.4%，故不采用**（负结果如实保留）；`rho` 与 `FIRST_HALF_SHARE` 经拟合复核后确认默认值已最优，维持不变。新增 `derived_market_status` 字段逐盘口标注拟合状态，`UNFITTED_CONSTANTS` flag 改为更精确的 `PARTIALLY_FITTED_CONSTANTS`。**Top比分、亚洲盘、晋级、半场1X2 仍为 UNFITTED**。
- **3.4.2**：**首个经真实拟合的校准层**。在体彩2026全联赛1348场收盘HAD上按时间序列切分（训练943/测试405）拟合平局修正 `DRAW_CALIBRATION_K=1.14` + 温度 `CALIBRATION_TEMPERATURE=0.96`。动机是实测发现市场去水后平局被系统性低估（期望331.9场 vs 实际368场，z=+2.30）。测试集 ECE 0.04697→0.03456（改善26.4%），Brier/LogLoss 微降。新增 `confidence` 星级字段（五档，区间由同一数据集拟合、测试集实测命中率单调递增）与 `final_1x2_display` 百分比字段。⚠️ **校准提升的是概率可信度不是命中率**，argmax命中率 55.80%→55.31% 基本不变。可用 `"calibration": false` 关闭。
- **3.4.1**：
  - 新增 `references/pitfalls.md`：数据采集、建模校准、工具使用三大类踩坑记录，含已证伪说法清单。
  - `references/modeling.md` 新增两张**赔率区间经验参照表**（3504场五大联赛实测）：主胜赔率7档、平局赔率6档，含平局率单调性规律；明确标注杯赛无样本（`NO_CUP_SAMPLE`）。
  - `references/modeling.md` 新增 **TTG完整8档直接约束λ** 方法：实测把大2.5球概率偏差从13~15pp收窄至2~3pp；手工TTG期望总进球仅作审计，不参与有赔率路径求解。
  - `references/sources.md` 新增中国体彩**移动端全盘口采集**与 sgodds/betherosports/ClubElo 高效批量采集技巧。
  - 修正：曾被验证为**错误**的"联赛低平赔是诱盘"说法已从文档移除，不得引用。

**不得修改或覆盖** `zu-yu-dashi-2` 与 `ucl-predictor`。

## 硬规则

1. 所有对外概率必须来自：
   ```sh
   python "<技能目录>\scripts\predict.py" "<输入JSON绝对路径>"
   ```
2. 先读取 `references/fields_schema.md`；采数参考 `sources.md`；审计参考 `modeling.md`；输出参考 `output_template.md`。
3. 输入模式必须标明：
   - `market_only`：只有赔率；市场1X2不二次混合，edge不适用。
   - `hybrid`：市场 + 完整Elo/基本面锚。
   - `model_first`：显式真实λ/xG优先，市场仅后验校准。
4. 严格验证完整组合：`odds`三项，或成对Elo，或成对λ；单边字段不得放行。
5. `0`和`false`是有效值，不得当作缺失；字段状态与字段数值分开。
6. 假设写入 `assumptions[]`；赔率反推λ标 `PROXY_XG`；真实λ标 `EXPLICIT_XG`。
7. 验证码由用户在当前页面完成；不得自动绕过。图片和网页图表应OCR，标 `IMAGE_EXTRACTED`。
8. 用户给出竞彩编号、体彩截图或中国体彩网场次时，使用中国体彩网**移动端官方链路**；停用持续返回 HTTP 567 的 `getMatchCalculatorV1.qry`，不得再重试该接口：
   1. `uniform/fb/getConditionsV1.qry?method=concern` 获取日期范围与赛事；
   2. `uniform/fb/getMatchDataPageListV1.qry?method=concern&matchDate=YYYY-MM-DD` 获取竞彩编号、对阵、状态、HAD与`matchId`；
   3. 按`matchId`低频请求 `uniform/football/getFixedBonusV1.qry?clientCode=3001&matchId=...`，获取HAD、HHAD、CRS、TTG、HAFU及赔率历史；
   4. 同一`matchId`可请求 `getMatchFeatureV1`、`getResultHistoryV1`、`getMatchTablesV1`、`getMatchResultV1`、`getFutureMatchesV1`、`getMatchPlayerV1`、`getInjurySuspensionV1`、`getMatchHeadV1`，采集特征、交锋、积分、近况、赛程、球员、伤停和身份信息。
   将HAD按`[h,d,a]`写入模型`odds`；TTG按`[0,1,2,3,4,5,6,7+]`写入`ttg.odds`；CRS仅作比分市场排序对照，不得直接替代模型比分矩阵；HHAD是三项让球胜平负，不得冒充亚洲盘或普通1X2。盘口与赛程属于体彩官方发布数据，可作为高可靠来源；历史统计页面明确提示部分数据来自第三方，须标记`SPORTTERY_DISPLAYED_THIRD_PARTY`，不得与官方赔率同计100分。伤停“暂无数据”标`UNAVAILABLE`，不得解释为确认无人伤停。保存接口URL、发布时间、比赛状态、采集时间和原始响应；任何缺项不得臆补。
9. 保存到当前项目文件夹 `projectXXX_项目名称\05_交付\足球预测\{date}_{safe_slug}\`：`raw_sources.json`、`model_input.json`、`model_output.json`、`report.md`。不得将项目产物写入技能目录、微信原始目录或项目文件夹之外。
10. 最终报告必须含"概率模型输出，非投注建议"。
11. **必须原样转述 `reliability_flags`**。该字段会主动报告本次输出的可靠性缺陷（edge 循环论证、市场依赖过高、常数未拟合等），不得省略、弱化或只挑好听的说。
12. **必须转述 `sensitivity`**（λ ±10% 扰动下 1X2 的波动区间）。当 `edge_vs_market_pp` 的绝对值小于该区间宽度时，必须明确说明"该 edge 小于输入不确定性，不具决策意义"。
13. **`quality.overall_pct` 不得表述为"预测置信度"**。它衡量的是输入字段完整度，填满字段但填错值分数照样很高——按其 `note` 字段的说法转述。
14. `market_only`的1X2固定为去水市场；敏感性重点转述O/U、BTTS、AH和比分候选，不能用固定1X2区间声称模型稳定。
15. 仅HAD时，比分/大小球/BTTS必须标`DERIVED_FROM_1X2_ONLY`；有HHAD则用结构化`hhad:{line,odds}`进入脚本审计；有TTG/O-U时优先联合约束总进球。
16. Elo模式同时启用`elo_home_adv`与`home_adv`时，必须有`extra_environment_confirmed=true`和`home_adv_reason`，否则原样报告`DOUBLE_HOME_ADV`。
17. 有`ou:{line,odds:[over,under]}`、`ttg:{odds:[0..6,7+]}`或`hafu:{odds:[hh,hd,ha,dh,dd,da,ah,ad,aa]}`时，必须与HAD/HHAD联合拟合λ，并输出`multi_market_fit`；不得继续按HAD-only解释比分与大小球。
    - 拟合权重按实测边际分档（HAD/HHAD≈12.9%、TTG≈25.1%、HAFU≈25.5%、CRS≈40.9%）：`had 1.0 / hhad 0.9 / ou 0.8 / ttg 0.5 / hafu 0.35`。边际越高噪声越大，权重越低。**CRS边际过高，不进拟合**，只作同场内比分相对排序。
    - HAFU是唯一能给**半场**提供市场锚的盘口，有它时半场Top比分不再纯靠常数拆分。官方完整采集器取得TTG后优先使用官方TTG；用户截图仅在官方接口缺项或需要页面核对时使用，并标记`IMAGE_EXTRACTED`。若官方TTG与旧截图不一致，以最新官方接口快照为准，同时保留旧截图数据作为历史来源，不覆盖原始文件。
18. **官方前瞻数据（独立强度锚）**：页面 `m.sporttery.cn/zqlszl/bssj/?mid=` 背后有8个官方接口，全部走 webapi.sporttery.cn：
    ```sh
    python3 scripts/fetch_match_preview.py --from-collect raw_sporttery.json --output prev.json --terms 10
    python3 scripts/merge_preview.py --input model_input.json --preview prev.json --output model_input_hybrid.json
    ```
    `getMatchFeatureV1` 给出近N场场均进球/失球（termLimits 最大30），交叉算出 λ 锚：`λ主=(主队场均进球+客队场均失球)/2`。
    - 该锚以 **`lambda_prior` 软约束**写入，**不覆盖** λ：有赔率时 λ 仍由多市场拟合决定，先验只在目标函数加一项相对偏差惩罚（`W_PRIOR=0.02`，实测λ位移约0.025、盘口拟合代价+7%）。
    - 模式升为 `hybrid`，`lambda_prior` 是合法强度锚之一；tags 增 `PRIOR_CONSTRAINED`，`multi_market_fit.prior.pulled_pp` 记录被拉动幅度。
    - ⚠️ 这些统计**未做对手强度调整**，且是市场早已知晓的公开信息（同 pitfalls 2.2 的 ClubElo 教训）。加入后是否更准**必须回测验证**，不得默认更好。样本<8场标 `LOW_SAMPLE` 并跳过。
    - `getInjurySuspensionV1` 的伤停名单已自动折算为 `attack_absence_*`/`defense_absence_*`/`gk_absence_*`：按 `playerPositionCode` 分档、乘出场率权重（首发满、替补半、10场为满额），多人累加后截 0.5。**这是唯一真正独立于赔率的信息源**，但折算系数标 `[UNFITTED]`，未经回测。
    - `getResultHistoryV1` 含 `halfTimeGoal`，已用于实证 `FIRST_HALF_SHARE`（见下）。
19. 免费xG采用多平台标准库：同一平台同场保留最新记录，跨平台不覆盖，按比赛键聚合中位数并报告范围与平台数。StatsBomb开放数据可自动导入；FBref/FotMob/Sofascore只在公开可访问、许可允许或用户截图OCR时录入，不绕过封锁。
20. 历史xG只能用于其日期之后的预测；不得用本场赛后xG预测本场。跨平台数据必须保留provider_model，不把不同xG口径当完全相同。
21. 每场必须输出`lambda_audit`：原始λ、总和、高低比、主/客零封概率。高λ≥3.2且低λ≤0.45或高低比≥6.0触发`EXTREME_LAMBDA_ASYMMETRY`；任一零封概率>55%触发`EXTREME_CLEAN_SHEET_HOME/AWAY`。审计只提示风险，不得静默修改概率。

## 校准回测

引擎自称"校准导向"，`scripts/backtest.py` 是验证这一点的唯一工具。

离线历史JSON：
```sh
python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/backtest.py <历史比赛JSON>
```
登记库：
```sh
python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/backtest.py --store H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/shared/zu-yu-dashi-3/backtest --snapshot closing
```

离线输入为正常predict字段加每场`actual:[主队90分钟进球,客队90分钟进球]`。输出Brier、log loss、Top比分、分档校准、ECE、基础频率基线和市场基线。

**判据**：模型必须同时打败「基础频率基线」和「市场基线」才算有价值。打不过市场说明它只是在复述盘口并引入噪声。样本量低于 200 场时结论不可靠。

⚠️ `scripts/predict.py` 顶部标注 `[UNFITTED]` 的常数均未经拟合。在跑过回测之前，**绝对概率只可用于相对比较，不应作为可信概率对外表述**。

## 标准工作流

```text
用户输入/截图
→ 球队身份、赛事、时间、主客与首回合核验
→ 直连来源采集 + OCR
→ 字段状态/来源/采集时间/有效期验证
→ 选择 market_only / hybrid / model_first
→ 写 model_input.json
→ 运行 predict.py
→ 审计概率守恒、输入假设、市场依赖、双回合路径
→ 按模板输出；可选生成PPT（必须与JSON一致）
```

## 关键输入

- Tier-0：`home`, `away`, `stage`，以及 `kickoff`或明确轮次语境。
- 强度锚至少一组完整组合：
  - `odds: [主,平,客]`
  - `elo_home` + `elo_away`
  - `lambda_home` + `lambda_away`
- 推荐：`first_leg`、真实xG、大小球赔率、伤停、轮换、首发、天气、旅行、海拔、身价、系数。
- 攻防分离修正优先于旧单值：`attack_absence_*`, `defense_absence_*`, `gk_absence_*`, `attack_motive_*`, `defense_risk_*`。
- 点球：可输入 `penalty_home_prob`；**默认 0.50**（3.1 由 0.52 改为中性值——公开研究不支持点球大战存在主场优势）。不因 seed 改变基础参数。
- 赛事：可输入 `competition` 或 `league`，用于查表确定 `goal_total`（德甲 3.10 / 西甲 2.55 / 欧冠 3.00 等）。
- ⚠️ **`goal_total` 只在「无赔率的启发式路径」生效**。有市场赔率时 λ 由赔率直接求解：多市场走 `multi_market_fit`（HAD/HHAD/O-U/TTG 联合拟合），仅HAD走 `inverse_1x2`（三项数值反解），两条路径都不读 `goal_total`，填了也不会改变结果。以输出中的 `goal_total_input.used_by_lambda_solver` 与其 `note` 为准转述；`GOAL_TOTAL_FALLBACK` 仅在它真被使用时才告警。

## 置信度星级与概率表述（3.4.2）

- 引擎输出 `confidence`：`stars`(1-5)、`label`(★★★☆☆)、`pick`、`pick_prob_pct`、`band_observed_hit_pct`、`band_sample_n`。
- 星级区间与实测命中率（405场测试集，未参与拟合，**单调递增已校验**）：

  | 星级 | 最大概率 | 测试集样本 | 实测命中率 |
  |---|---|---|---|
  | ★★★★★ | ≥70% | 32 | 87.5% |
  | ★★★★☆ | 60–70% | 79 | 69.6% |
  | ★★★☆☆ | 50–60% | 106 | 56.6% |
  | ★★☆☆☆ | 40–50% | 114 | 47.4% |
  | ★☆☆☆☆ | <40% | 74 | 36.5% |

- **星级不是独立信息**，只是最大概率的分档标签。报告中星级必须与概率百分比同时出现，不得只给星级。
- 概率一律用百分比呈现（`final_1x2_display` 已给出 `主胜/平局/客胜` 的 `xx.x%` 字符串），不用小数或赔率倒数。
- 5星与1星档测试样本均<100场，引擎会自动附 `warning`，必须转述。

## 各盘口拟合状态（3.4.3，必须按此口径转述，不得一概而论）

引擎输出 `derived_market_status` 字段，逐盘口标注状态。**不得再笼统说"衍生盘口全部未拟合"，也不得笼统说"已校准"**：

| 盘口 | 状态 | 依据 |
|---|---|---|
| 1X2 | **FITTED** | 平局修正+温度，测试集 ECE 0.04697→0.03456 |
| O/U 2.5 | **FITTED** | Platt(a=1.03,b=-0.08)，ECE 0.06470→0.04710 |
| O/U 3.5 | **FITTED** | Platt(a=1.05,b=-0.11)，ECE 0.06196→0.03611 |
| BTTS | **VALIDATED_NO_CHANGE** | 原始 ECE 0.0213 已良好；校准后恶化至 0.0265，**刻意不施加** |
| rho | **FITTED-CONFIRMED** | 测试集 -0.08 优于拟合值 -0.07，维持默认 |
| FIRST_HALF_SHARE | **FITTED-CONFIRMED** | 1348场实测 0.444/0.450，维持 0.45 |
| Top比分 | **UNFITTED** | 比分分布未独立校准 |
| 亚洲盘 | **UNFITTED** | 由比分矩阵推导，无独立回测 |
| 晋级/加时/点球 | **UNFITTED** | 无样本，点球固定 0.50 中性值 |
| 半场1X2 | **UNFITTED** | 未独立校准 |

- **BTTS 是重要负结果**：不是"忘了校准"，而是**测试后确认校准有害**。任何后续改动想给 BTTS 加校准，必须先复现这个对照实验。
- O/U 校准只对 2.5 和 3.5 两条线拟合过；其他盘口线引擎会输出 `calibration.applied=false` 并说明原因，必须转述。

## 关于「平局全数漏判」的定性（不得当作模型缺陷修复）

1348场实测：市场去水后把平局列为最大概率仅 **6/1348 = 0.4%**，而实际平局率 **27.3%**。
平局概率的**上界结构性地低**——1348场中平局概率最高的150场，实际平局率也只有36.7%，仍低于主胜。

- 这是三分类概率结构的固有性质，**不是模型 bug，不能通过继续调高平局概率解决**。强行让平局成为argmax会同时破坏校准（Brier/LogLoss/ECE全面恶化）。
- 正确做法：**换决策口径，不是换概率**。要覆盖平局必须用双选（主胜/平、平/客胜）或让球盘（HHAD），靠单选打「最大概率」必然系统性漏掉全部平局。
- 引擎已固定输出 `DRAW_ARGMAX_RARE` flag 说明这一点，**必须原样转述**。

## 输出必须包含

- 运行模式、数据完整度、来源可信度、新鲜度、综合质量、市场依赖度。
- 市场公平1X2、纯模型1X2、最终1X2；仅在模型相对独立时报告edge。
- λ、来源标记、ρ、Top比分、半场Top。
- O/U 2.5与3.5、BTTS。
- 亚洲盘：全赢/半赢/走水/半输/全输。
- 双回合：90分钟决出、进加时、加时晋级、点球晋级、总晋级。
- 关键胜负手、事实/衍生/假设分层、风险说明。

## 失败处理

| 情况 | 处理 |
|---|---|
| Tier-0缺失 | `incomplete`，列出缺失字段 |
| 强度锚不成对 | `incomplete`，不得均分λ兜底 |
| 非法赔率/范围 | `invalid`，指出字段与允许范围 |
| 仅市场赔率 | 允许 `market_only`，置信下降、edge=`N/A` |
| 搜索受阻 | 标 `UNAVAILABLE`，尝试至少两个备源 |
| 脚本异常 | 报错并停止数字输出，不手工补概率 |
| 与市场显著偏离 | 保留脚本结果并解释来源，不静默改数 |

## 批量

输入 `{ "matches": [...] }` 一次运行。先输出总表，再逐场展开。跨模型对比时，每个模型单独成列；重复文档不得重复计权。

## 正式预测登记与回测

详细规范见 `references/backtesting.md`。

- 正式赛前预测默认使用：
  ```sh
  python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/record_prediction.py --input input.json --output output.json --predict --snapshot T-24h
  ```
- 预测必须在开赛前登记；已登记记录禁止覆盖，更新预测创建新snapshot。测试和敏感性分析可不登记。
- 每条记录保存模型版本、输入/输出/引擎哈希，并追加到链式registry。
- 赛后回填优先用官方赛果自动化，一条命令扫描登记库缺口并写入：
  ```sh
  python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/settle_from_sporttery.py [--date YYYY-MM-DD] [--dry-run]
  ```
  数据源为移动端 `getMatchDataPageListV1.qry?method=result` 的 `sectionsNo999`（全场）与 `sectionsNo1`（半场）；只回填 `matchStatusName=已完成` 且比分非空的场次，未完成一律 `no_result_yet` 跳过，不臆补。先跑 `--dry-run` 核对匹配是否指向正确球队。
  ⚠️ 该接口**不带 `matchDate` 时只返回约10场滚动窗口**，`pageSize`/`pageNo` 参数无效（见 pitfalls 1.1b）。脚本已改为按待回填场次的开球日期逐日查询（并各自附带前一日以覆盖 businessDate 与 matchDate 跨零点的差异）后合并去重。**不得改回裸调一次**，否则窗口外的已完赛场次会被永久误判为未出赛果。
- 加时、点球、晋级方等官方列表未提供的字段，仍用 `settle_result.py` 手工回填；预测与赛果分开保存。
- 赛果匹配**优先用官方 `match_id`**（采集器已写入 `sporttery_meta`），无ID的旧记录才回退队名模糊匹配；报告中的 `matched_by` 字段标明本次用了哪种。官方 `home_team_id`/`away_team_id`/`league_id` 是稳定主键，用于消除中文简称歧义与关联外部数据。
- 赔率移动追踪：每次采集后运行 `odds_movement.py add --source raw.json` 追加快照（按 match_id+盘口+更新时间去重）。`drift` 子命令输出开盘→最新的去水概率位移，用于CLV与盘口异动分析。长期积累才有价值，建议每日采集。
- 通过`backtest.py`计算1X2准确率、Brier、Log Loss、比分Top1/3/5、O/U、BTTS和晋级评分。
- 回测必须按模型版本、预测快照和时间隔离；禁止使用赛后信息重建赛前输入，小样本不得宣称模型优于市场。
- 快速历史样本：运行`build_historical_dataset.py`下载football-data公开CSV并转成离线回测集；历史回测与前瞻登记库必须分开报告。
- **每日样本流水线（推荐入口）**：`daily_pipeline.py` 一条命令完成 回填赛果→采集全盘口→登记快照→追加赔率移动库：
  ```sh
  python3 H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/scripts/daily_pipeline.py [--date YYYY-MM-DD] [--dry-run]
  ```
  体彩**每天 11:00 开售时刷新全部盘口赔率**，故定时任务设在 11:05，快照标 `T-7h`（离最早开球约7小时）。已配置 minis-scheduled 每日任务，不要重复创建。网络失败自动重试2次。
- 单步排查时才用 `daily_snapshot.py`；只登记Selling且HAD完整、尚未开赛的比赛。同一比赛多快照不能当成多个独立样本。
- **同快照去重（已强制执行）**：同一 `(match_id, snapshot_type)` 只能贡献一个回测样本。`record_prediction.py` 对重复登记返回 `skipped_duplicate_snapshot` 并 exit 0（幂等，可安全重跑流水线），需覆盖才加 `--replace-snapshot`；`backtest.py --store` 按 `(match_id, snapshot_type)` 保留最新一条并报告 `deduped_duplicates`。该字段大于 0 说明登记库有重复登记，须核查流水线是否被重复触发。
- 优先按`closing`快照评估；T-6h、lineup与closing分别统计。

## 跨模型/跨会话复用指引

本 skill 设计为**自包含**：任何模型首次加载，按以下顺序读取即可复现全部已验证能力，不依赖任何外部会话记忆：

1. 本文件（SKILL.md）—— 硬规则与工作流
2. `references/fields_schema.md` —— 输入字段规范
3. `references/sources.md` —— 数据源与采集方法（含体彩全盘口采集、高效批量技巧）
4. `references/modeling.md` —— 建模方法、赔率区间参照表、TTG校正法
5. `references/pitfalls.md` —— **踩坑记录**：已验证的坑与解法、已证伪说法清单，避免重复踩坑
6. `references/output_template.md` —— 标准输出模板
7. `references/backtesting.md` —— 正式登记与回测规范

**关键约定**（不随会话变化）：
- 用户主要需求：中国体彩官方赔率采集 + 胜平负/比分/总进球/BTTS/让球分析 + 可选PPT产出
- 技能目录固定 `H:\claude AI自媒体\project017_football-quant-fusion技能导出\02_核心引擎依赖/skills/zu-yu-dashi-3/`；不得修改 `zu-yu-dashi-2`、`ucl-predictor`
- 交互语言：中文；PPT若有用户提供的模板，优先保留版式，数字直接读取 `model_output.json`

新发现的坑或方法，**追加进 `pitfalls.md`**，不要散落在对话历史里。
