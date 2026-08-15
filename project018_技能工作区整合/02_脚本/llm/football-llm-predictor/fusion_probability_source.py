# -*- coding: utf-8 -*-
"""从量化轨（football-quant-fusion）登记库取校准概率，供 EV 计算使用。

为什么需要它
------------
`ev_calculator.py` 于 2026-08-15 改成 fail closed：没有真实概率来源就不算 EV。
本模块提供那个来源——轨道A融合引擎登记的 `final_1x2_pct`。

它**不是**投票比例：核心引擎对该联赛做过 draw_multiplier + temperature_scaling 校准
（记录里 `calibration.applied=true`，带 `league_basis` 与 test ECE），是真正的概率。
与之相对，融合层的「推荐置信度」仍未校准——两者是不同产物，不可互相替代。

一条必须保留的限制
------------------
量化轨绝大多数记录是 `mode=market_only`：概率主要由体彩赔率去水反解而来。
拿它对**同一个盘口**算 EV，量到的是庄家水位，不是独立信息带来的 edge。
所以本模块会把 `market_derived` 标出来，由 `ev_calculator` 拒绝据此出胆
（与融合技能 `edge_min_pp=5` / `max_market_dependency_pct` 的判断一致：
实测 675 样本 edge 范围 [-6.3, +1.6]pp，market_only 几乎必然不出胆）。

双轨纪律
--------
借用轨道A的概率**只发生在 EV 这一层**。轨道B的方向、比分、投票与登记仍然独立，
两轨依旧各自登记、各自结算、不合并。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

DIRECTIONS = ["主胜", "平局", "客胜"]

DEFAULT_DATA_ROOT = Path(
    r"F:\HM足球比赛预测\project018_技能工作区整合\04_素材\shared-data\football-quant-fusion"
)


def fusion_store() -> Path:
    """量化轨登记库；与融合技能同一个 FUSION_DATA_ROOT 约定。"""
    root = os.environ.get("FUSION_DATA_ROOT")
    return (Path(root) if root else DEFAULT_DATA_ROOT) / "backtest"


def _iter_registry(store: Path):
    registry = store / "registry.jsonl"
    if not registry.exists():
        return
    for line in registry.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _resolve(path_value: str, store: Path) -> Path:
    """登记里的绝对路径可能来自别的机器/旧目录，优先按 store 内相对段定位。"""
    norm = str(path_value).replace("\\", "/")
    marker = "/football-quant-fusion/backtest/"
    if marker in norm:
        candidate = store / norm.split(marker, 1)[1]
        if candidate.exists():
            return candidate
    return Path(path_value)


def load_fusion_probabilities(match_id, store: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """取该场最新一条量化轨登记的校准概率。

    match_id: 体彩官方数字 id（LLM 原始输入里的 `match_id`），内部拼成 `sporttery-<id>`。
    返回 None 表示量化轨还没登记这场——调用方应据此 skip，不得回退到投票比例。
    """
    store = Path(store) if store else fusion_store()
    target = f"sporttery-{match_id}"

    best = None
    for entry in _iter_registry(store):
        if entry.get("match_id") != target:
            continue
        if best is None or str(entry.get("created_at") or "") > str(best.get("created_at") or ""):
            best = entry
    if best is None:
        return None

    path = _resolve(best.get("path", ""), store)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None

    output = record.get("output") or {}
    pct = output.get("final_1x2_pct")
    if not isinstance(pct, list) or len(pct) != 3:
        return None

    calibration = output.get("calibration") or {}
    model = record.get("model") or {}
    mode = str(record.get("mode") or "").lower()
    applied = bool(calibration.get("applied"))

    return {
        "probabilities": {d: pct[i] / 100.0 for i, d in enumerate(DIRECTIONS)},
        "source": f"fusion-{model.get('model_version') or '?'}-final_1x2_pct",
        "calibration_status": "VALID" if applied else "UNFITTED",
        "calibration_basis": calibration.get("league_basis") or calibration.get("fitted_on"),
        # market_only 的概率由同一个盘口去水而来，据此算 EV 只量到水位，不构成 edge
        "market_derived": mode == "market_only",
        "mode": mode or None,
        "market_dependency_pct": output.get("market_dependency_pct"),
        "prediction_id": record.get("prediction_id"),
        "snapshot_type": record.get("snapshot_type"),
        "model_version": model.get("model_version"),
    }
