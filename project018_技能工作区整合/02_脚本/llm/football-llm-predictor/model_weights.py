# -*- coding: utf-8 -*-
"""
模型权重管理：基于历史回测表现动态调整投票权重。
=================================================
问题诊断(2026-08-12)：
  - glm-4-flash 几乎每场输出"战意强烈/主场优势"空话，reasoning 无信息量
  - 6 模型虚假共识（看同一份证据，推理路径高度相关）
  
方案：
  1. 硬编码先验权重（基于已知表现）
  2. 可选：从回测日志自动更新（未来）
"""
from __future__ import annotations

from typing import Dict, Optional

# 基于 08-05 / 08-07 / 08-08 三场回测的诊断先验权重
# glm-4-flash: 几乎所有场次输出空话"战意强烈"，信息量为零，权重砍到 0.3
# qwen-flash / qwen3.8-max: 市场派，赔率推理质量尚可，但有时盲从市场
# deepseek-chat: 推理质量最好，正反推演有信息量
# kimi-k3: 新生产投票模型，沿用 Kimi 基准权重，待独立回测
# llama-3.3-70b: 冷门猎手，有时过头但提供差异化视角
# doubao-seed-evolving: 逆向思维，有差异化但波动大
# gemini-3-flash-preview: 战术流，质量中等

MODEL_PRIOR_WEIGHTS: Dict[str, float] = {
    "zhipu/glm-4-flash": 0.3,       # 噪音制造机，大幅降权
    "qwen/qwen-flash": 0.8,         # 市场派，中等
    "qwen/qwen3.8-max": 0.9,        # 千问 Max 更强
    "deepseek/deepseek-chat": 1.2,  # 推理质量最好
    "moonshot/kimi-k3": 1.0,        # 历史 K3 研究模型，基准权重
    "deepseek/deepseek-v4-flash": 1.0,  # 当前默认 DeepSeek V4 Flash
    "groq/llama-3.3-70b-versatile": 0.8,  # 冷门猎手，有差异化
    "ark/doubao-seed-evolving": 0.9,       # 逆向思维
    "gemini/gemini-3-flash-preview": 0.7,  # 战术流，中等
}

# 模型独立性分组：同组模型共享相似推理路径，投票权重打折
# 问题：所有模型看同一份证据，本质不是独立投票
INDEPENDENCE_GROUPS = {
    "market_follower": {"qwen/qwen-flash", "qwen/qwen3.8-max"},  # 市场派组
    "domestic_reasoning": {"deepseek/deepseek-chat", "deepseek/deepseek-v4-flash", "moonshot/kimi-k3"},  # 国内推理组
    "overseas": {"groq/llama-3.3-70b-versatile", "gemini/gemini-3-flash-preview"},  # 海外组
    "noise": {"zhipu/glm-4-flash"},  # 噪音组
    "contrarian": {"ark/doubao-seed-evolving"},  # 逆向组
}


def get_model_weight(model: str, all_models_in_pool: Optional[list] = None) -> float:
    """获取模型的投票权重（先验 × 独立性修正）。
    
    独立性修正：同一独立性组内有 N 个模型时，每个模型权重 × (1/N)。
    这防止 2 个市场派模型 = 2 票但实际只有 1 个独立视角。
    """
    prior = MODEL_PRIOR_WEIGHTS.get(model, 0.8)  # 默认 0.8
    
    if not all_models_in_pool:
        return prior
    
    pool_set = set(all_models_in_pool)
    for group_name, group_models in INDEPENDENCE_GROUPS.items():
        overlap = pool_set & group_models
        if model in overlap and len(overlap) > 1:
            # 同组内有 N 个模型，权重打折
            independence_penalty = 1.0 / len(overlap)
            return prior * independence_penalty
    
    return prior


def get_all_weights(model_pool: list) -> Dict[str, float]:
    """为模型池中的所有模型计算权重。"""
    return {m: get_model_weight(m, model_pool) for m in model_pool}


def summarize_weight_adjustments(model_pool: list) -> str:
    """生成可读的权重调整摘要。"""
    weights = get_all_weights(model_pool)
    lines = []
    for m, w in sorted(weights.items(), key=lambda x: -x[1]):
        short = m.split("/")[-1][:20]
        lines.append(f"  {short:<20} → 权重 {w:.2f}")
    return "\n".join(lines)
