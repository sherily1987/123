# LLM 预测关键词库（导出版）

从足球量化融合技能（football-quant-fusion 1.4.0）双轨预测流程中导出的 LLM 轨道工具包：搜索关键词库、证据记录模板、映射参考与工作流。可直接拿到其它项目（hremes / 自建脚本）使用，配合量化轨道做双轨对比。

## 目录结构

```
project016_LLM预测关键词库导出/
├── README.md                        # 本说明
├── 01_关键词库/
│   └── llm_search_keywords.md       # 六类关键词表（中英双语）+ 搜索纪律
├── 02_记录模板/
│   ├── llm_track_template.json      # llm-track-1.0 可填模板
│   └── evidence_mapping.md          # mapped 字段枚举 + 战意/赔率映射参考（UNFITTED）
├── 03_示例/
│   └── llm_示例_20260805_周二004_圣吉联合vs博德闪耀.json  # 真实登记示例
└── 04_工作流/
    └── llm_track_workflow.md        # 每场六步流程 + 硬纪律
```

## 快速上手

1. 打开 `01_关键词库/llm_search_keywords.md`，按六类关键词搜索（中英双语、每类至少两个来源交叉验证）。
2. 用 `02_记录模板/llm_track_template.json` 填写证据表与判断（`mapped` 取值见 `evidence_mapping.md`）。
3. 开球前把记录写入待回测目录并登记 `index_llm.json`（禁止赛后补录）。
4. 赛后用 `backtest_dual_track.py` 对比量化 vs LLM 命中率。

## 关键纪律

- LLM 轨道只输出**定性方向与比分偏好**，禁止伪概率/伪 xG（数字只由量化脚本产生）。
- 每条证据必须带来源 URL + 采集时间，无引用事实不得进入记录。
- LLM 判断不参与推荐门控，只作双轨对比研究。
- 样本累计 ≥100 场才评估、≥200 场才做结论，单场命中不说明问题。

## 来源

- 原始出处：`football-quant-fusion` 1.4.0 双轨预测流程（SKILL.md）+ `project013_LLM对比轨道试点/01_规划/关键词库.md` + `references/motive_evidence_reference.md`。
- 导出时间：2026-08-04。
