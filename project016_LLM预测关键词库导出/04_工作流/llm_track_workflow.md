# LLM 轨道工作流（每场六步）

## 步骤

1. **身份核验**：确认主客队全名/英文名、赛事阶段、开球时间与时区、90 分钟口径；中文简称有歧义时优先官方 teamId 或英文全名（用"身份核验"类关键词）。
2. **搜索取证**：按六类关键词库搜索，中英双语并行，每类至少两个独立来源交叉验证。
3. **整理证据表**：每条事实写成 `{fact, source(URL), collected_at, mapped, basis}`，填入 llm-track-1.0 模板。
4. **结构化判断**：基于证据给出 `direction`（H/D/A 单选或双选 + single_preference）与 `score_picks`（比分 Top1-3 偏好）；只定性，不输出伪概率。
5. **赛前预登记**：开球前写入 `llm-track-1.0` JSON 到待回测记录目录，与量化记录同场同文件夹，并更新 `index_llm.json`；禁止赛后补录。
6. **赛后对比**：`settle` 回填官方赛果 → 对比量化 argmax vs LLM 单选/双选命中、比分 Top1/Top3；累计 ≥100 场评估、≥200 场做结论，单场不结论。

## 纪律（硬性）

1. **数字只由脚本产生**：LLM 轨道禁止生成伪概率、伪 xG，只输出定性方向与比分偏好。
2. **赛前预登记**：判断必须在开球前写入，禁止赛后补录。
3. **证据必须可引用**：无来源 URL 与采集时间的事实不得进入记录。
4. **归档并排**：量化记录与 LLM 记录同场同文件夹，附 index。
5. **LLM 不参与推荐门控**：不影响 `recommendation_gate` 与出胆判断，仅作对比研究。

## 输出口径

- 量化 1X2 argmax、LLM 双选、LLM 单选偏好、比分 Top1/Top3 分轨道统计。
- 样本 <100 场不评价优劣、<200 场不做结论。

## 回测入口

```bash
python backtest_dual_track.py --date YYYYMMDD
# 或一键回测所有已预测比赛
python auto_backtest.py --workspace "H:\claude AI自媒体" --output-dir <项目>/05_交付/auto_backtest
```
