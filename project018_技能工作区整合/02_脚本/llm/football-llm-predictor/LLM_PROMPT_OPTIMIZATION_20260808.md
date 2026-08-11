# LLM 提示词全面优化 · 2026-08-08

## 改动文件
- `llm_prompt_rules.py`（新建）共享规则/角色/检索词/反坍缩
- `football_predictor.py` 四玩法 JSON+角色+聚合
- `predict.py` 证据轨 JSON+角色+聚合
- 技能 `football-evidence-collection` 检索词表

## 要点
1. 示例比分改为 1-0/1-1，禁止无依据 2-1
2. ou25/hafu 独立字段
3. reasoning 必须【类别:事实】，纯赔率降权
4. 分歧强度<60% 强制双选
5. 2-1 坍缩 + 无效 reasoning 降权
6. 国内三模附加冷门/低比分职责

## 验证
`python -c "import football_predictor, predict, llm_prompt_rules"`
