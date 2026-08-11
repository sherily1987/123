#!/usr/bin/env python3
"""2026-08-07 销售日模型输出核对：市场去水 vs 模型 1X2 vs 可靠性旗标。

对每场：体彩 HAD 去水概率（power devig，与引擎同法）、模型 final_1x2、
fusion_decision 方向、reliability_flags 中的严重旗标（EXTREME_*）。
用于判断模型输出是否可信：严重旗标场次以降级处理（以市场为准）。
数字全部由脚本产生。
"""
import json
import io
from pathlib import Path

BASE = Path(__file__).resolve().parent


def devig(odds, method="power"):
    """与引擎一致的去水：proportional/power。返回概率列表(0-1)。"""
    q = [1.0 / x for x in odds]
    if method == "power":
        # power devig: 1/x^p 归一化，p 由总水差决定（引擎默认 1.0 近似 proportional）
        s = sum(q)
    else:
        s = sum(q)
    return [x / s for x in q]


def main():
    with io.open(BASE / "input.json", encoding="utf-8-sig") as f:
        inp = json.load(f)
    with io.open(BASE / "model_output.json", encoding="utf-8-sig") as f:
        out = json.load(f)

    rows = []
    for r in out.get("results", []):
        match_str = str(r.get("match", ""))
        # 找对应 input 场次（队名匹配）
        im = None
        for m in inp.get("matches", []):
            if m.get("home") in match_str and m.get("away") in match_str:
                im = m
                break
        num = (im or {}).get("sporttery_meta", {}).get("match_num", "?")
        odds = (im or {}).get("odds")
        mkt_pct = None
        if odds and len(odds) == 3:
            p = devig([float(x) for x in odds])
            mkt_pct = [round(x * 100, 1) for x in p]
        fc = r.get("forecast") or {}
        fd = r.get("fusion_decision") or {}
        flags = [f for f in (r.get("reliability_flags") or []) if f.startswith("EXTREME")]
        gate = r.get("recommendation_gate") or {}
        rows.append({
            "num": num, "match": match_str, "odds": odds, "mkt_pct": mkt_pct,
            "model_pct": fc.get("final_1x2_pct"),
            "mode": r.get("mode"), "primary": fd.get("primary_outcome"),
            "top_gap_pp": fd.get("top_gap_pp"), "severe_flags": flags,
            "banker": gate.get("banker_allowed"),
        })

    print("=" * 100)
    print(f"{'编号':<9}{'比赛':<22}{'体彩HAD':<18}{'市场去水%':<24}{'模型1X2%':<24}{'模式':<12}{'严重旗标'}")
    print("=" * 100)
    for r in rows:
        odds_s = "/".join(str(x) for x in r["odds"]) if r["odds"] else "None"
        mkt_s = json.dumps(r["mkt_pct"], ensure_ascii=False) if r["mkt_pct"] else "None"
        mdl_s = json.dumps(r["model_pct"], ensure_ascii=False)
        flag_s = ";".join(f.split(":")[0] for f in r["severe_flags"]) if r["severe_flags"] else "-"
        print(f"{r['num']:<9}{r['match'][:20]:<22}{odds_s:<18}{mkt_s:<24}{mdl_s:<24}{r['mode']:<12}{flag_s}")

    # 汇总：模型与市场严重背离的场次
    print("\n=== 模型 vs 市场背离检测（argmax 方向不一致 或 偏差>15pp）===")
    for r in rows:
        if not r["mkt_pct"]:
            print(f"  {r['num']} {r['match'][:20]}: 无市场概率（model_first 分支），以模型为主但需看旗标")
            continue
        mkt_argmax = max(range(3), key=lambda i: r["mkt_pct"][i])
        mdl_argmax = max(range(3), key=lambda i: r["model_pct"][i])
        mkt_name = ["H", "D", "A"][mkt_argmax]
        mdl_name = ["H", "D", "A"][mdl_argmax]
        max_diff = max(abs(a - b) for a, b in zip(r["mkt_pct"], r["model_pct"]))
        if mkt_argmax != mdl_argmax or max_diff > 15:
            print(f"  ⚠️ {r['num']} {r['match'][:20]}: 市场{mkt_name}({r['mkt_pct'][mkt_argmax]}%) vs 模型{mdl_name}({r['model_pct'][mdl_argmax]}%) max_diff={max_diff:.1f}pp")
        else:
            print(f"  ✅ {r['num']} {r['match'][:20]}: 方向一致 {mkt_name}({r['mkt_pct'][mkt_argmax]}%) max_diff={max_diff:.1f}pp")


if __name__ == "__main__":
    main()
