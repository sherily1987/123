#!/usr/bin/env python3
"""Train FT score-matrix and HT score temperature calibration on football-data big5.

方法（与引擎 predict 同口径）：
- λ 由市场 1X2 反解（solve_lam_from_probs, Dixon-Coles rho=-0.08）
- 全场矩阵 13x13；半场矩阵 7x7（lambda*0.45, rho/2，与 predict.py 半场口径一致）
- 按开球时间排序后等距分层抽样（默认目标 12000 场），再按时间 70/30 切分
- 对全场/半场比分网格分别拟合单一温度 T（logits 温度缩放：p^(1/T) 归一化），
  train 上按比分 LogLoss 选优，test 上报告校准前后指标

输出：参数 JSON + Markdown 报告。数字全部由脚本产生。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runtime_paths import core_scripts_dir  # noqa: E402
# 2026-08-16：原硬编码指向外部 football-quant-fusion-suite 的 zu-yu-dashi-3 物理拷贝
# （靠人工 cp 同步、历史上真的漂移过）。改走 core_scripts_dir()，默认仓库内唯一事实源。
sys.path.insert(0, str(core_scripts_dir()))
import predict as P

CORE = P
FT_N = 13          # 0..12
HT_N = 7           # 0..6
FT_CELLS = FT_N * FT_N
HT_CELLS = HT_N * HT_N
BIN_EDGES = [0.0, 0.02, 0.05, 0.1, 0.2, 0.4, 1.0]


def parse_csv_date(s):
    """football-data Date 列：dd/mm/yy 或 dd/mm/yyyy → ISO yyyy-mm-dd。"""
    s = str(s or "").strip()
    if not s:
        return ""
    parts = s.split("/")
    if len(parts) != 3:
        return s
    try:
        d, m, y = int(parts[0]), int(parts[1]), parts[2]
        if len(str(y)) == 2:
            yy = int(y)
            y = 1900 + yy if yy >= 70 else 2000 + yy
        return f"{int(y):04d}-{m:02d}-{d:02d}"
    except ValueError:
        return s


def ft_index(i, j):
    return i * FT_N + j


def ht_index(i, j):
    return i * HT_N + j


def load_matches(jsonl_path):
    """读取含 1X2 赔率与全场比分的记录；半场比分按 raw_fields.HTHG/HTAG 可选。"""
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            odds = r.get("odds")
            actual = r.get("actual")
            if not odds or not actual or len(actual) < 2:
                continue
            rf = r.get("raw_fields") or {}
            hthg = rf.get("HTHG")
            htag = rf.get("HTAG")
            try:
                odds3 = [float(x) for x in odds[:3]]
                ft = (int(actual[0]), int(actual[1]))
            except (TypeError, ValueError):
                continue
            if any(x <= 1.001 for x in odds3) or ft[0] < 0 or ft[1] < 0 or ft[0] > 12 or ft[1] > 12:
                continue
            ht = None
            if hthg is not None and htag is not None:
                try:
                    ht = (int(hthg), int(htag))
                    if ht[0] < 0 or ht[1] < 0 or ht[0] >= HT_N or ht[1] >= HT_N:
                        ht = None
                except (TypeError, ValueError):
                    ht = None
            kick = r.get("kickoff") or parse_csv_date(rf.get("Date")) or ""
            rows.append(
                {
                    "kickoff": str(kick)[:10] if kick else "0000-00-00",
                    "league": str(r.get("competition") or r.get("stage") or r.get("div") or ""),
                    "odds": odds3,
                    "ft": ft,
                    "ht": ht,
                }
            )
    return rows


def build_vectors(rows):
    """对每场计算全场/半场 DC 矩阵，输出扁平概率向量与真实索引。"""
    ft_p = np.zeros((len(rows), FT_CELLS), dtype=np.float64)
    ht_p = np.zeros((len(rows), HT_CELLS), dtype=np.float64)
    ft_y = np.zeros(len(rows), dtype=np.int64)
    ht_y = np.full(len(rows), -1, dtype=np.int64)
    solved = 0
    skipped = 0
    t0 = time.time()
    for n, r in enumerate(rows):
        try:
            probs, _ = P.devig(r["odds"], "proportional")
            lam = P.solve_lam_from_probs(probs)
            if lam is None:
                skipped += 1
                continue
            lh, la = lam
            m_ft = P.matrix(lh, la, P.RHO_DEFAULT, FT_N)
            m_ht = P.matrix(lh * P.FIRST_HALF_SHARE, la * P.FIRST_HALF_SHARE, P.RHO_DEFAULT / 2, HT_N)
        except Exception:
            skipped += 1
            continue
        solved += 1
        for i in range(FT_N):
            for j in range(FT_N):
                ft_p[n, ft_index(i, j)] = m_ft.get((i, j), 0.0)
        ft_y[n] = ft_index(r["ft"][0], r["ft"][1])
        if r["ht"] is not None:
            for i in range(HT_N):
                for j in range(HT_N):
                    ht_p[n, ht_index(i, j)] = m_ht.get((i, j), 0.0)
            ht_y[n] = ht_index(r["ht"][0], r["ht"][1])
        if (n + 1) % 2000 == 0:
            print(f"  [{n+1}/{len(rows)}] solved={solved} skipped={skipped} {time.time()-t0:.0f}s", flush=True)
    print(f"done: solved={solved} skipped={skipped} {time.time()-t0:.0f}s", flush=True)
    return ft_p, ft_y, ht_p, ht_y


def topk_hit(row_probs, y, k):
    idx = np.argsort(row_probs)[::-1][:k]
    return int(y in idx)


def score_metrics(p_mat, y, mask=None):
    """比分矩阵指标：LogLoss、Top1/3/5、分格 ECE（按 (场,格) 加权）。"""
    if mask is not None:
        p_mat = p_mat[mask]
        y = y[mask]
    n = p_mat.shape[0]
    if n == 0:
        return {}
    p_clip = np.clip(p_mat, 1e-12, 1.0)
    ll = float(-np.log(p_clip[np.arange(n), y]).mean())
    top1 = float(np.mean([topk_hit(p_mat[i], y[i], 1) for i in range(n)]))
    top3 = float(np.mean([topk_hit(p_mat[i], y[i], 3) for i in range(n)]))
    top5 = float(np.mean([topk_hit(p_mat[i], y[i], 5) for i in range(n)]))
    flat_p = p_clip.flatten()
    flat_y = np.zeros(flat_p.shape[0])
    flat_y[np.arange(n) * p_mat.shape[1] + y] = 1.0
    ece = 0.0
    bins = []
    for b in range(len(BIN_EDGES) - 1):
        lo, hi = BIN_EDGES[b], BIN_EDGES[b + 1]
        sel = (flat_p >= lo) & (flat_p < (hi if b < len(BIN_EDGES) - 2 else 1.000001))
        cnt = int(sel.sum())
        if cnt == 0:
            continue
        ap = float(flat_p[sel].mean())
        aa = float(flat_y[sel].mean())
        ece += cnt / len(flat_p) * abs(ap - aa)
        bins.append({"bin": f"{lo}-{hi}", "n": cnt, "avg_prob": round(ap, 5), "actual_rate": round(aa, 5)})
    return {"n": n, "log_loss": round(ll, 5), "top1_acc_pct": round(top1 * 100, 2),
            "top3_acc_pct": round(top3 * 100, 2), "top5_acc_pct": round(top5 * 100, 2),
            "ece": round(ece, 5), "calibration_bins": bins}


def ht_1x2_metrics(ht_p, ht_y, mask=None):
    """半场1X2聚合指标（H/D/A 三态准确率与 LogLoss）。"""
    if mask is not None:
        ht_p = ht_p[mask]
        ht_y = ht_y[mask]
    n = ht_p.shape[0]
    good = ht_y >= 0
    if good.sum() == 0:
        return {"n_ht": int(good.sum())}
    p = ht_p[good]
    y = ht_y[good]
    # 三态聚合
    h = np.zeros((p.shape[0], 3))
    for i in range(HT_N):
        for j in range(HT_N):
            cls = 0 if i > j else (1 if i == j else 2)
            h[:, cls] += p[:, ht_index(i, j)]
    h = np.clip(h, 1e-12, 1.0)
    yy = np.where(y // HT_N > y % HT_N, 0, np.where(y // HT_N == y % HT_N, 1, 2))
    ll = float(-np.log(h[np.arange(h.shape[0]), yy]).mean())
    acc = float(np.mean(np.argmax(h, axis=1) == yy))
    return {"n_ht": int(good.sum()), "ht_1x2_log_loss": round(ll, 5), "ht_1x2_acc_pct": round(acc * 100, 2)}


def temp_apply(p_mat, T):
    return p_mat ** (1.0 / T)


def fit_temperature(p_mat, y, grid):
    """在 train 上按比分 LogLoss 网格选最优温度。"""
    best = (1.0, float("inf"))
    idx = np.arange(p_mat.shape[0])
    for T in grid:
        p = temp_apply(p_mat, T)
        s = p.sum(axis=1, keepdims=True)
        p = p / s
        p = np.clip(p, 1e-12, 1.0)
        ll = float(-np.log(p[idx, y]).mean())
        if ll < best[1]:
            best = (float(T), ll)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="football_data_big5_all_fields.jsonl")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--sample-target", type=int, default=12000)
    ap.add_argument("--test-frac", type=float, default=0.30)
    a = ap.parse_args()
    outdir = Path(a.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    print("loading matches...", flush=True)
    rows = load_matches(a.input)
    print(f"with odds+FT: {len(rows)}", flush=True)
    rows.sort(key=lambda r: r["kickoff"])
    if a.sample_target and len(rows) > a.sample_target:
        step = max(1, len(rows) // a.sample_target)
        rows = rows[::step]
    split = int(len(rows) * (1.0 - a.test_frac))
    train_rows = rows[:split]
    test_rows = rows[split:]
    print(f"train={len(train_rows)} test={len(test_rows)} date_range={rows[0]['kickoff'][:10]}..{rows[-1]['kickoff'][:10]}", flush=True)

    print("solving lambda + matrices (train)...", flush=True)
    ft_p_tr, ft_y_tr, ht_p_tr, ht_y_tr = build_vectors(train_rows)
    print("solving lambda + matrices (test)...", flush=True)
    ft_p_te, ft_y_te, ht_p_te, ht_y_te = build_vectors(test_rows)

    grid = np.round(np.arange(0.50, 1.51, 0.02), 2).tolist()
    print("fitting FT temperature...", flush=True)
    ft_T, ft_ll_train = fit_temperature(ft_p_tr, ft_y_tr, grid)
    print("fitting HT temperature...", flush=True)
    ht_T, ht_ll_train = fit_temperature(ht_p_tr[ht_y_tr >= 0], ht_y_tr[ht_y_tr >= 0], grid)

    def apply_then_metrics(p_mat, y, T, mask=None):
        if mask is not None:
            p_mat = p_mat[mask]
            y = y[mask]
        p = temp_apply(p_mat, T)
        p = p / (p.sum(axis=1, keepdims=True) + 1e-12)
        return score_metrics(p, y)

    m_ft_before_tr = score_metrics(ft_p_tr, ft_y_tr)
    m_ft_after_tr = apply_then_metrics(ft_p_tr, ft_y_tr, ft_T)
    m_ft_before_te = score_metrics(ft_p_te, ft_y_te)
    m_ft_after_te = apply_then_metrics(ft_p_te, ft_y_te, ft_T)

    mask_ht_tr = ht_y_tr >= 0
    mask_ht_te = ht_y_te >= 0
    m_ht_before_tr = score_metrics(ht_p_tr, ht_y_tr, mask_ht_tr)
    m_ht_after_tr = apply_then_metrics(ht_p_tr, ht_y_tr, ht_T, mask_ht_tr)
    m_ht_before_te = score_metrics(ht_p_te, ht_y_te, mask_ht_te)
    m_ht_after_te = apply_then_metrics(ht_p_te, ht_y_te, ht_T, mask_ht_te)

    h1_tr = ht_1x2_metrics(ht_p_tr, ht_y_tr)
    h1_te = ht_1x2_metrics(ht_p_te, ht_y_te)

    # 按联赛的测试集 FT Top1（校准后）
    league_rows = {}
    for r, pv, yv in zip(test_rows, ft_p_te, ft_y_te):
        lg = r["league"] or "?"
        league_rows.setdefault(lg, {"p": [], "y": []})
        league_rows[lg]["p"].append(pv)
        league_rows[lg]["y"].append(yv)
    per_league = {}
    for lg, v in sorted(league_rows.items(), key=lambda x: -len(x[1]["p"])):
        p = np.stack(v["p"])
        y = np.array(v["y"])
        p = temp_apply(p, ft_T)
        p = p / p.sum(axis=1, keepdims=True)
        n = p.shape[0]
        top1 = float(np.mean([topk_hit(p[i], y[i], 1) for i in range(n)]))
        ll = float(-np.log(np.clip(p[np.arange(n), y], 1e-12, 1.0)).mean())
        per_league[lg] = {"n": n, "top1_acc_pct": round(top1 * 100, 2), "score_log_loss": round(ll, 5)}

    params = {
        "schema_version": "score-half-calibration-1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "football-data 五大联赛 football_data_big5_all_fields.jsonl",
        "method": "logits temperature scaling on score grid; p^(1/T) normalized; fitted by train score LogLoss",
        "sample": {
            "with_odds_ft": len(rows),
            "train": len(train_rows),
            "test": len(test_rows),
            "date_range": [rows[0]["kickoff"][:10], rows[-1]["kickoff"][:10]],
            "ft_solved_train": int((ft_y_tr >= 0).sum()),
            "ft_solved_test": int((ft_y_te >= 0).sum()),
            "ht_available_train": int((ht_y_tr >= 0).sum()),
            "ht_available_test": int((ht_y_te >= 0).sum()),
        },
        "calibration": {
            "ft_score_temperature": ft_T,
            "ht_score_temperature": ht_T,
            "train_score_log_loss": {"ft": round(ft_ll_train, 5), "ht": round(ht_ll_train, 5)},
            "status": "TRAINED_ON_SAMPLE_VALIDATED_ON_HOLDOUT",
            "note": "温度仅作用于比分/半场分布；1X2/OU/BTTS 校准层不受影响，仍沿用体彩1348场参数。",
        },
        "metrics": {
            "ft_train_before": m_ft_before_tr,
            "ft_train_after": m_ft_after_tr,
            "ft_test_before": m_ft_before_te,
            "ft_test_after": m_ft_after_te,
            "ht_train_before": m_ht_before_tr,
            "ht_train_after": m_ht_after_tr,
            "ht_test_before": m_ht_before_te,
            "ht_test_after": m_ht_after_te,
            "ht_1x2_train": h1_tr,
            "ht_1x2_test": h1_te,
            "per_league_test_top1_after": per_league,
        },
        "disclaimer": "概率模型输出，非投注建议。",
    }
    params_path = outdir / "score_half_calibration_params.json"
    params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")

    def row(name, m):
        return f"| {name} | {m.get('n','-')} | {m.get('log_loss','-')} | {m.get('top1_acc_pct','-')} | {m.get('top3_acc_pct','-')} | {m.get('top5_acc_pct','-')} | {m.get('ece','-')} |"

    lines = []
    lines.append("# 比分矩阵与半场分布温度校准报告")
    lines.append("")
    lines.append(f"- 数据源：football-data 五大联赛；样本 {len(rows)} 场（train {len(train_rows)} / test {len(test_rows)}），日期 {rows[0]['kickoff'][:10]} → {rows[-1]['kickoff'][:10]}")
    lines.append(f"- λ 反解：市场 1X2 比例去水 → solve_lam_from_probs（DC ρ=-0.08）；半场 = λ×0.45、ρ/2、7×7 网格（与引擎 predict 同口径）")
    lines.append(f"- 校准方法：比分网格 Logits 温度缩放 p^(1/T) 归一化；train 按比分 LogLoss 网格选优")
    lines.append("")
    lines.append("## 校准参数")
    lines.append("")
    lines.append(f"| 网格 | 温度 T | train LogLoss |")
    lines.append("| --- | ---: | ---: |")
    lines.append(f"| 全场比分 13×13 | {ft_T} | {ft_ll_train:.5f} |")
    lines.append(f"| 半场比分 7×7 | {ht_T} | {ht_ll_train:.5f} |")
    lines.append("")
    lines.append("## 全场比分指标")
    lines.append("")
    lines.append("| 数据集 | n | LogLoss | Top1% | Top3% | Top5% | ECE |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(row("train 校准前", m_ft_before_tr))
    lines.append(row("train 校准后", m_ft_after_tr))
    lines.append(row("test 校准前", m_ft_before_te))
    lines.append(row("test 校准后", m_ft_after_te))
    lines.append("")
    lines.append("## 半场比分指标")
    lines.append("")
    lines.append("| 数据集 | n | LogLoss | Top1% | Top3% | Top5% | ECE |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(row("train 校准前", m_ht_before_tr))
    lines.append(row("train 校准后", m_ht_after_tr))
    lines.append(row("test 校准前", m_ht_before_te))
    lines.append(row("test 校准后", m_ht_after_te))
    lines.append("")
    lines.append(f"半场1X2：test 准确率 {h1_te.get('ht_1x2_acc_pct','-')}%，LogLoss {h1_te.get('ht_1x2_log_loss','-')}（n={h1_te.get('n_ht','-')}）")
    lines.append("")
    lines.append("## 分联赛测试集 FT Top1（校准后）")
    lines.append("")
    lines.append("| 联赛 | n | Top1% | 比分LogLoss |")
    lines.append("| --- | ---: | ---: | ---: |")
    for lg, v in sorted(per_league.items(), key=lambda x: -x[1]["n"]):
        lines.append(f"| {lg} | {v['n']} | {v['top1_acc_pct']} | {v['score_log_loss']} |")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 温度 T<1 表示锐化（低概率格被压更低、高概率格抬升）；T>1 表示展平。")
    lines.append("- 校准只改比分/半场分布的形状，不改 1X2/OU/BTTS 已拟合层；正式启用需先在融合引擎做回归验证。")
    lines.append("- Top1 命中率是单格众数命中，天然较低（约 10-13%），评估以 LogLoss/ECE 为主。")
    lines.append("- 概率模型输出，非投注建议。")
    lines.append("")
    report = "\n".join(lines)
    (outdir / "score_half_calibration_report.md").write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
