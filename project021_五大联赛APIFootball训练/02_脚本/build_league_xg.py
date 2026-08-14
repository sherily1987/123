#!/usr/bin/env python3
"""逐联赛自动选择代理 xG 口径并生成 xg.jsonl。

## 为什么必须自动选

统计质量跨联赛差异极大（实测乌超禁区内外切分仅 0.5% 可用、捷克 53%，
而荷甲/土超/奥超 99%）。人工逐个判断在 40 个联赛的规模上不可行，也不可复现。

选择规则（阈值写死以便复现），两道门缺一不可：

  第一道 选口径——看该口径在**已有统计行**中的可用率：
    禁区内外切分 >= 70%   -> inside_outside（信息最强：含射门位置）
    否则 射正 >= 70%      -> shots_on_target（较弱：只有一个有效变量）
    否则                  -> 无

  第二道 是否启用——看可用场次占**完赛场次**的比例（>= 60%）：
    只看第一道会高估。斯洛文尼亚 887 场完赛只有 296 行统计，其中射正 96.6% 可用，
    按统计行算是 96.6%，按完赛场次算只有 32%。xG 版强度若只由三分之一的比赛拟合，
    与进球版不可同日而语，混合只会引入噪声——宁可不启用。

## 系数为何用「按口径合并拟合」而非逐联赛拟合

实测 a 在五大联赛间只波动 ±5%，射正系数在英冠/捷克/乌超间是 0.314/0.319 高度一致；
而逐联赛选参在 xG 权重上已被证明是**负收益**（验证集过拟合）。
故按口径各拟合一套合并系数，样本更足、更稳。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROXY = ROOT / "project007_APIFootball数据接入" / "02_脚本" / "proxy_xg.py"
THRESHOLD = 0.70          # 选口径：该口径在已有统计行中的可用率
MIN_MATCH_SHARE = 0.60    # 启用 xG 通道：可用场次须覆盖该联赛完赛场次的比例


def coverage(stats_path: Path) -> dict:
    """按**实际字段**判可用率，不能用 `xg_usable` 标记。

    该标记在两个源里含义不同：apifootball 写的是禁区内外切分是否可用，
    football-data.co.uk 写的是射正是否可用。混用会把只有射正的联赛
    误判成有禁区切分，随后取字段时直接 KeyError。
    """
    rows = [json.loads(l) for l in stats_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not rows:
        return {"n": 0, "box": 0.0, "sot": 0.0, "box_n": 0, "sot_n": 0, "finished": 0}
    box = sot = 0
    for r in rows:
        inside, outside = r.get("shots_inside_box"), r.get("shots_outside_box")
        total = r.get("shots_total")
        if inside and outside and all(v is not None for v in list(inside) + list(outside)):
            box += 1
        on = r.get("shots_on_target") or r.get("shots_on_goal")
        if on and total and all(v is not None for v in list(on) + list(total)):
            sot += 1
    return {"n": len(rows), "box": box / len(rows), "sot": sot / len(rows),
            "box_n": box, "sot_n": sot}


def usable_share(cov: dict, basis: str | None, finished: int) -> float:
    """xG 可用场次占**完赛场次**的比例。

    以统计行数为分母会高估：斯洛文尼亚 887 场完赛只有 296 行统计，
    其中射正 96.6% 可用，按统计行算是 96.6%，按完赛场次算只有 32%。
    xG 版强度若只由三分之一的比赛拟合，与进球版不可同日而语，混合会引入噪声。
    """
    if not basis or not finished:
        return 0.0
    n = cov["box_n"] if basis == "inside_outside" else cov["sot_n"]
    return n / finished


def pick_basis(cov: dict) -> str | None:
    if cov["n"] == 0:
        return None
    if cov["box"] >= THRESHOLD:
        return "inside_outside"
    if cov["sot"] >= THRESHOLD:
        return "shots_on_target"
    return None


def run(cmd: list[str]) -> dict:
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(f"失败：{' '.join(cmd[-4:])}\n{out.stderr[-500:]}")
    # fit 打印多行缩进 JSON、apply 打印单行 JSON，两种都要能解析
    text = out.stdout.strip()
    for candidate in (text, text.splitlines()[-1] if text else ""):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, IndexError):
            continue
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--train-until", required=True, help="系数拟合截止日，须早于所有联赛的测试切分")
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--force-include", nargs="*", default=[],
                     help="显式豁免第二道门槛（可用场次占比<60%）的联赛 slug 列表；"
                          "仅在已确认知晓样本量偏低风险时使用，结果会在 plan 里标 forced_low_share=true")
    a = ap.parse_args()
    force_include = set(a.force_include)

    norm = a.project / "04_素材" / "标准化"
    models = a.project / "04_素材" / "模型"
    models.mkdir(parents=True, exist_ok=True)

    plan = {}
    for stats in sorted(norm.glob("*_match_stats.jsonl")):
        slug = stats.name.replace("_match_stats.jsonl", "")
        if not (norm / f"{slug}_events.jsonl").exists():
            continue
        finished = sum(1 for _ in (norm / f"{slug}_events.jsonl").read_text(encoding="utf-8").splitlines() if _.strip())
        cov = coverage(stats)
        cov["finished"] = finished
        basis = pick_basis(cov)
        share = usable_share(cov, basis, finished)
        # 覆盖率不足时不启用 xG——宁可只用进球版，也不混入一个由少数比赛拟合的噪声模型。
        # 显式豁免（--force-include）不改变门槛本身，只对指定联赛放行，且结果标记
        # forced_low_share，下游（回测/报告）应能看到这是低样本强度、不与其余联赛同等看待。
        if basis and share < MIN_MATCH_SHARE:
            if slug in force_include:
                plan[slug] = {"coverage": cov, "basis": basis, "match_share": round(share, 4),
                              "forced_low_share": True,
                              "note": f"人工豁免第二道门槛：可用场次仅占完赛 {share:.1%}，低于 {MIN_MATCH_SHARE:.0%}，"
                                      "强度由少数比赛拟合，置信度低于其余启用xG的联赛"}
            else:
                plan[slug] = {"coverage": cov, "basis": None, "match_share": round(share, 4),
                              "skipped_reason": f"xG 可用场次仅占完赛 {share:.1%}，低于 {MIN_MATCH_SHARE:.0%}"}
            continue
        plan[slug] = {"coverage": cov, "basis": basis, "match_share": round(share, 4)}

    by_basis: dict[str, list[str]] = {}
    for slug, info in plan.items():
        if info["basis"]:
            by_basis.setdefault(info["basis"], []).append(slug)

    coeffs = {}
    for basis, slugs in sorted(by_basis.items()):
        out_path = models / f"proxy_xg_coeffs_{basis}_all.json"
        cmd = [sys.executable, str(PROXY), "fit",
               "--stats", *[str(norm / f"{s}_match_stats.jsonl") for s in slugs],
               "--events", *[str(norm / f"{s}_events.jsonl") for s in slugs],
               "--basis", basis, "--train-until", a.train_until, "--output", str(out_path)]
        run(cmd)
        c = json.loads(out_path.read_text(encoding="utf-8"))
        coeffs[basis] = {"path": str(out_path), "a": c["a_inside_box"], "b": c["b_outside_box"],
                         "n_matches": c["n_matches"], "leagues": len(slugs),
                         "self_check": c["self_check"]}
        print(f"[{basis}] {len(slugs)} 个联赛 {c['n_matches']} 场  "
              f"a={c['a_inside_box']:.4f} b={c['b_outside_box']:.4f} "
              f"比值={c['self_check']['primary_secondary_ratio']}", flush=True)

    # 判定不启用的联赛，必须删掉可能存在的旧 xg 文件。
    # 下游按「文件是否存在」推断 xG 是否启用，留着陈旧文件会**整个绕过覆盖率门槛**
    # （实测乌超因此用了只覆盖 35% 场次的 xG，评估集从 221 场缩到 120 场）。
    removed = []
    for slug, info in sorted(plan.items()):
        stale = norm / f"{slug}_xg.jsonl"
        if not info["basis"] and stale.exists():
            stale.unlink()
            removed.append(slug)
    if removed:
        print(f"清理 {len(removed)} 个陈旧 xg 文件（计划判定不启用）：{removed}", flush=True)

    applied = 0
    for slug, info in sorted(plan.items()):
        if not info["basis"]:
            continue
        res = run([sys.executable, str(PROXY), "apply",
                   "--stats", str(norm / f"{slug}_match_stats.jsonl"),
                   "--coeffs", coeffs[info["basis"]]["path"],
                   "--output", str(norm / f"{slug}_xg.jsonl")])
        info["xg_rows"] = res.get("count")
        applied += 1

    payload = {"threshold": THRESHOLD, "train_until": a.train_until,
               "coefficients": coeffs, "leagues": plan}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'联赛':<38}{'完赛':>6}{'统计行':>7}{'禁区%':>7}{'射正%':>7}{'占完赛%':>8}{'口径':>17}{'xg行':>7}")
    for slug, info in sorted(plan.items()):
        c = info["coverage"]
        flag = " ⚠forced" if info.get("forced_low_share") else ""
        print(f"{slug:<38}{c.get('finished', 0):>6}{c['n']:>7}{c['box'] * 100:>7.1f}{c['sot'] * 100:>7.1f}"
              f"{info.get('match_share', 0) * 100:>8.1f}{str(info['basis'] or '无'):>17}{info.get('xg_rows') or 0:>7}{flag}")
    no_xg = {s: i.get("skipped_reason", "统计字段不足（禁区与射正可用率均低于阈值）")
             for s, i in plan.items() if not i["basis"]}
    forced = {s: i["note"] for s, i in plan.items() if i.get("forced_low_share")}
    print(f"\n共 {len(plan)} 个联赛，{applied} 个启用 xG 通道，{len(no_xg)} 个未启用，{len(forced)} 个人工豁免：")
    for s, why in no_xg.items():
        print(f"    {s:<38}{why}")
    if forced:
        print("人工豁免（低样本，置信度低）：")
        for s, why in forced.items():
            print(f"    {s:<38}{why}")
    print(f"报告：{a.report}")


if __name__ == "__main__":
    main()
