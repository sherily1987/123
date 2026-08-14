#!/usr/bin/env python3
"""LLM 轨道的概率档位：让定性判断能进 Brier / log loss 体系。

## 为什么需要

LLM 轨道原本只输出「双选 / 单选偏好」，理由是不想编造伪精度。动机没错，
但代价是**整条轨道无法用正规评分规则打分**——而 Brier、log loss 正是本项目
其余部分的全部评价基础。只剩命中率的话：

- 命中率信息效率极低，区分「55% 真实水平」与「50%」需要几百场；
  Brier 只需要几十场。所以「累计 100 场再评估」这个门槛在只有命中率时远远不够。
- 双选（三选二）的随机基线就是 66.67%，长期大概率一直卡在「看不出差别」。

## 折中：离散档位，不是精确数字

LLM 为胜/平/负各选一个**档位**（区间），评分时取中点归一化。
既不假装精确到小数点，又能进正规评分体系。档位表刻意做粗，
且原始档位与归一化后的概率**同时记录**，事后可复核。

## 一致性检查

三档中点之和若严重偏离 100%，说明 LLM 的档位分配自相矛盾
（例如三项都选「很高」）。这本身是有价值的质量信号，必须记录而非静默归一化。
"""
from __future__ import annotations

# 档位表：名称 -> (下界%, 上界%)。刻意做粗，避免伪精度。
BANDS: dict[str, tuple[float, float]] = {
    "极低": (0.0, 10.0),
    "很低": (10.0, 20.0),
    "偏低": (20.0, 30.0),
    "中低": (30.0, 40.0),
    "中高": (40.0, 50.0),
    "偏高": (50.0, 65.0),
    "很高": (65.0, 80.0),
    "极高": (80.0, 100.0),
}
ALIASES = {"H": "H", "D": "D", "A": "A", "主胜": "H", "平局": "D", "客胜": "A", "平": "D"}
# 中点之和落在此区间外视为档位分配自相矛盾
COHERENT_RANGE = (70.0, 130.0)


def midpoint(band: str) -> float:
    if band not in BANDS:
        raise ValueError(f"未知档位 {band!r}；可选：{sorted(BANDS)}")
    lo, hi = BANDS[band]
    return (lo + hi) / 2


def normalize(bands: dict) -> dict:
    """档位 -> 可评分概率。

    返回 ``raw_sum_pct``（归一化前的中点之和）与 ``coherent``（是否落在合理区间）。
    **归一化不掩盖矛盾**：三项都选「很高」时 raw_sum 会是 217.5，coherent=False。
    """
    keyed = {}
    for k, v in bands.items():
        key = ALIASES.get(str(k).strip())
        if key is None:
            raise ValueError(f"未知结果键 {k!r}；应为 H/D/A 或 主胜/平局/客胜")
        keyed[key] = str(v).strip()
    missing = {"H", "D", "A"} - set(keyed)
    if missing:
        raise ValueError(f"档位不完整，缺少 {sorted(missing)}")
    mids = {k: midpoint(v) for k, v in keyed.items()}
    total = sum(mids.values())
    probs = [round(mids[k] / total, 6) for k in ("H", "D", "A")]
    # 舍入残差并入最大项，保证三项精确相加为 1（引擎有概率守恒审计）
    big = max(range(3), key=lambda i: probs[i])
    probs[big] = round(probs[big] + (1.0 - sum(probs)), 6)
    return {
        "bands": keyed,
        "midpoints_pct": {k: mids[k] for k in ("H", "D", "A")},
        "raw_sum_pct": round(total, 2),
        "coherent": COHERENT_RANGE[0] <= total <= COHERENT_RANGE[1],
        "probs_1x2": probs,
        "basis": "band_midpoint_normalized",
    }


def brier(probs: list[float], actual_idx: int) -> float:
    return sum((probs[i] - (1 if i == actual_idx else 0)) ** 2 for i in range(3))


def log_loss(probs: list[float], actual_idx: int) -> float:
    import math
    return -math.log(max(1e-12, probs[actual_idx]))


def from_record(record: dict) -> dict | None:
    """从 LLM 登记记录里取档位；没有则返回 None（旧记录只有双选/单选）。"""
    bands = ((record.get("direction") or {}).get("probability_bands")
             or record.get("probability_bands"))
    if not bands:
        return None
    return normalize(bands)
