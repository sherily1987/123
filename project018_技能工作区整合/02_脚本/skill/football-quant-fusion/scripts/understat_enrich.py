#!/usr/bin/env python3
"""understat_enrich — 把 Understat 真实 xG 并入模型输入（R2②）。

模式：
- model_first（默认）：写入 lambda_home/lambda_away = 成对 xG（真实事件级强度），保留 odds 作对照；
- hybrid_prior：写入 lambda_prior（软约束，multi_market_fit 内与盘口联合拟合）。
不覆盖体彩赔率；附加 field_meta.understat 与 source_evidence。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import core_scripts_dir, data_root  # noqa: E402
# 2026-08-16：原硬编码指向外部 football-quant-fusion-suite 的 zu-yu-dashi-3 物理拷贝
# （靠人工 cp 同步、历史上真的漂移过）。改走 core_scripts_dir()，默认仓库内唯一事实源。
sys.path.insert(0, str(core_scripts_dir()))
import understat_xg as UX

CN2US = {"英超": "EPL", "西甲": "La_liga", "德甲": "Bundesliga", "意甲": "Serie_A", "法甲": "Ligue_1"}


def enrich_match(m, rows, mode, prior_weight):
    lg_cn = str(m.get("competition") or m.get("stage") or m.get("league") or "")
    us = CN2US.get(lg_cn)
    if not us:
        m.setdefault("field_meta", {})["understat"] = {"status": "UNAVAILABLE", "reason": "league not covered"}
        return m
    kick = (m.get("kickoff") or "")
    date = kick[:10] if kick else None
    hit = None
    if date:
        for d0 in (date, ):
            hit = UX.lookup(rows, us, m.get("home", ""), m.get("away", ""), d0)
            if hit:
                break
    if not hit:
        hit = UX.lookup(rows, us, m.get("home", ""), m.get("away", ""), None)
    if not hit or hit.get("status") != "VALID":
        m.setdefault("field_meta", {})["understat"] = {"status": "UNAVAILABLE", "reason": "match not found in store"}
        return m
    m.setdefault("field_meta", {})["understat"] = {
        "status": "VALID", "source": "understat", "datetime": hit["datetime"],
        "home_xg": hit["home_xg"], "away_xg": hit["away_xg"],
    }
    m.setdefault("source_evidence", []).append("understat xG")
    if mode == "model_first":
        m["lambda_home"] = hit["lambda_home"]
        m["lambda_away"] = hit["lambda_away"]
        m["mode"] = "model_first"
        m.setdefault("assumptions", []).append(
            "model_first：λ=Understat 成对 xG（显式 λ）；核心以 W_EXPLICIT 并入多市场拟合。")
    else:
        m["lambda_prior"] = {
            "lambda_home": hit["lambda_home"], "lambda_away": hit["lambda_away"],
            "weight": prior_weight, "source": "understat_xg",
            "sample_legs": None, "note": "Understat 真实 xG 软先验（未回测最优权重）",
        }
        m.setdefault("field_meta", {}).setdefault("lambda_prior", {})["source"] = "understat_xg"
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    # 2026-08-16：默认值原指向外部套件的 datasets（物理拷贝），改走仓库内唯一事实源
    ap.add_argument("--store", default=str(data_root() / "datasets" / "understat_store.jsonl"))
    ap.add_argument("--mode", default="model_first", choices=("model_first", "hybrid_prior"))
    ap.add_argument("--prior-weight", type=float, default=0.05)
    a = ap.parse_args()
    rows = [json.loads(x) for x in Path(a.store).read_text(encoding="utf-8").splitlines() if x.strip()]
    data = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict) and "matches" in data:
        data["matches"] = [enrich_match(m, rows, a.mode, a.prior_weight) for m in data["matches"]]
    else:
        data = enrich_match(data, rows, a.mode, a.prior_weight)
    Path(a.output).parent.mkdir(parents=True, exist_ok=True)
    Path(a.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "mode": a.mode, "output": a.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
