#!/usr/bin/env python3
"""fusion_backtest — 融合层回测（Brier / LogLoss / ECE / CLV）。

评估 football-quant-fusion 实际登记输出（完整 fusion payload），而非仅底层核心。
同一 (match_id, snapshot_type) 只算一个样本（保留 created_at 最新一条）。
指标：1X2 Brier/LogLoss/ECE/准确率、比分 Top1/3/5 与 LogLoss、O/U2.5、BTTS、CLV。
CLV：同一比赛存在多个快照时，用「收盘快照隐含概率 − 本快照隐含概率」对首选结果计算；
无收盘快照则不计 CLV。按 engine_version / 联赛 / snapshot 分组报告。
样本 <200 不宣称优于市场；100 场前不重校准。
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_STORE = Path("H:\claude AI自媒体\project017_football-quant-fusion技能导出\03_共享数据\football-quant-fusion/backtest")


# [中文功能] 按行读取 jsonl
def load_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# [中文功能] 旧容器路径 /var/minis/... 自动映射到本机 shared 目录
def resolve_path(p_str, root):
    p = Path(p_str)
    if p.exists():
        return p
    if p_str.startswith("/var/minis/shared/"):
        return root.parents[1] / p_str[len("/var/minis/shared/"):]
    return p


# [中文功能] 在融合输出中按多级位置查找字段
def find(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
        if isinstance(d, dict):
            d = d.get(k) or {}
    return default


# [中文功能] 取比分对应的胜平负索引
def actual_1x2(h, a):
    return 0 if h > a else (1 if h == a else 2)


# [中文功能] 三分类 Brier
def brier(probs, idx):
    return sum((p - (1 if i == idx else 0)) ** 2 for i, p in enumerate(probs))


# [中文功能] 对数损失
def logloss(probs, idx):
    return -math.log(max(1e-12, min(1 - 1e-12, probs[idx])))


# [中文功能] 比例去水（默认）
def devig(o):
    q = [1.0 / x for x in o]
    s = sum(q)
    return [x / s for x in q]


# [中文功能] ECE：按 10 桶统计 (概率, 结果) 三元组
def ece_from_obs(obs):
    if not obs:
        return None, []
    total = len(obs)
    ece = 0.0
    bins = []
    for b in range(10):
        lo, hi = b / 10, (b + 1) / 10
        g = [(p, y) for p, y in obs if lo <= p < (hi if b < 9 else 1.000001)]
        if not g:
            continue
        ap = sum(x[0] for x in g) / len(g)
        aa = sum(x[1] for x in g) / len(g)
        ece += len(g) / total * abs(ap - aa)
        bins.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": len(g), "avg_prob": round(ap, 6), "actual_rate": round(aa, 6)})
    return round(ece, 6), bins


# [中文功能] 汇总一组样本的指标
def summarize(rows):
    obs, bs, ls, hit = [], [], [], []
    top1 = top3 = top5 = sll = 0
    n_ou = n_bt = 0
    ou_b = bt_b = 0.0
    clv = []
    for r in rows:
        probs, idx = r["probs"], r["actual_idx"]
        obs += [(p, 1 if i == idx else 0) for i, p in enumerate(probs)]
        bs.append(brier(probs, idx))
        ls.append(logloss(probs, idx))
        hit.append(int(max(range(3), key=lambda i: probs[i]) == idx))
        if r.get("top_scores") is not None and r.get("actual_score") is not None:
            top1 += int(r["top_scores"].get("top1"))
            top3 += int(r["top_scores"].get("top3"))
            top5 += int(r["top_scores"].get("top5"))
            sll += r["top_scores"].get("log_loss", 0.0)
        if r.get("ou25") is not None:
            n_ou += 1
            ou_b += (r["ou25"]["over"] - r["ou25"]["actual"]) ** 2
        if r.get("btts") is not None:
            n_bt += 1
            bt_b += (r["btts"]["yes"] - r["btts"]["actual"]) ** 2
        if r.get("clv_pp") is not None:
            clv.append(r["clv_pp"])
    n = len(rows)
    ece, bins = ece_from_obs(obs)
    out = {
        "n": n,
        "accuracy_pct": round(sum(hit) / n * 100, 3) if n else None,
        "brier_mean": round(sum(bs) / n, 8) if n else None,
        "brier_sum": round(sum(bs), 8) if n else None,
        "log_loss": round(sum(ls) / n, 8) if n else None,
        "ece": ece,
        "calibration_bins": bins,
    }
    if top1:
        out["score"] = {
            "top1_accuracy_pct": round(top1 / n * 100, 2),
            "top3_accuracy_pct": round(top3 / n * 100, 2),
            "top5_accuracy_pct": round(top5 / n * 100, 2),
            "score_log_loss": round(sll / n, 5),
        }
    if n_ou:
        out["ou_2_5_brier"] = round(ou_b / n_ou, 6)
    if n_bt:
        out["btts_brier"] = round(bt_b / n_bt, 6)
    if clv:
        out["clv_mean_pp"] = round(sum(clv) / len(clv), 3)
        out["clv_n"] = len(clv)
    return out


# [中文功能] 从一条融合记录解析可回测字段；结果缺失返回 None
def score_record(rec, root):
    mid = rec.get("match_id")
    rp = root / "results" / (mid + ".json")
    if not rp.exists():
        return None, "no_result"
    try:
        rs = json.loads(rp.read_text(encoding="utf-8"))
    except Exception:
        return None, "invalid_result"
    s90 = rs.get("score_90")
    if not isinstance(s90, dict) or s90.get("home") is None:
        return None, "invalid_or_pending_result"
    out = rec.get("output") or {}
    core = out.get("core_output") or out
    fc = out.get("forecast") or core.get("forecast") or {}
    probs_pct = find(out, "final_1x2_pct", "final_1x2") or find(core, "final_1x2_pct")
    if not isinstance(probs_pct, list) or len(probs_pct) != 3:
        return None, "missing_1x2"
    h, a = int(s90["home"]), int(s90["away"])
    probs = [x / 100.0 for x in probs_pct]
    idx = actual_1x2(h, a)
    top_list = fc.get("top_scores") or core.get("top_scores") or []
    score_view = None
    actual_score = f"{h}-{a}"
    if top_list:
        pm = {str(x.get("score")): float(x.get("prob_pct", 0)) / 100.0 for x in top_list if x.get("score") is not None}
        ranked = [x.get("score") for x in sorted(top_list, key=lambda x: x.get("prob_pct", 0), reverse=True)]
        p_actual = pm.get(actual_score, 1e-6)
        score_view = {
            "top1": int(ranked and ranked[0] == actual_score),
            "top3": int(actual_score in ranked[:3]),
            "top5": int(actual_score in ranked[:5]),
            "log_loss": -math.log(max(1e-6, p_actual)),
        }
    ou = fc.get("ou_2_5") or core.get("ou_2_5") or {}
    ou_view = None
    if ou.get("over_pct") is not None:
        ou_view = {"over": float(ou["over_pct"]) / 100.0, "actual": 1 if h + a > 2.5 else 0}
    bt = fc.get("btts") or core.get("btts") or {}
    bt_view = None
    if bt.get("yes_pct") is not None:
        bt_view = {"yes": float(bt["yes_pct"]) / 100.0, "actual": 1 if h > 0 and a > 0 else 0}
    _m = rec.get("model")
    _version = _m.get("version") if isinstance(_m, dict) else str(_m or "")
    return {
        "prediction_id": rec.get("prediction_id"),
        "match_id": mid,
        "snapshot_type": rec.get("snapshot_type"),
        "version": _version,
        "league": ((rec.get("match") or {}).get("competition")) or ((rec.get("match") or {}).get("stage")) or "?",
        "probs": probs,
        "actual_idx": idx,
        "actual_score": actual_score,
        "top_scores": score_view,
        "ou25": ou_view,
        "btts": bt_view,
        "clv_pp": None,
        "snapshot_odds": (rec.get("input") or {}).get("odds"),
        "kickoff": ((rec.get("match") or {}).get("kickoff")),
    }, None


# [中文功能] 同场比赛跨快照计算 CLV（收盘隐含概率 − 本快照隐含概率，首选结果）
def attach_clv(rows):
    by_match = {}
    for i, r in enumerate(rows):
        if r.get("snapshot_odds"):
            by_match.setdefault(r["match_id"], []).append(i)
    for mid, idxs in by_match.items():
        if len(idxs) < 2:
            continue
        closing = None
        closing_t = None
        for i in idxs:
            t = rows[i].get("created_at") or ""
            if closing_t is None or t > closing_t:
                closing, closing_t = i, t
        for i in idxs:
            if i == closing:
                continue
            try:
                p_snap = devig([float(x) for x in rows[i]["snapshot_odds"]])
                p_close = devig([float(x) for x in rows[closing]["snapshot_odds"]])
                top = max(range(3), key=lambda k: rows[i]["probs"][k])
                rows[i]["clv_pp"] = round((p_close[top] - p_snap[top]) * 100, 3)
            except Exception:
                pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="可选：离线历史 JSON（含 output+actual 的融合记录）")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--snapshot")
    ap.add_argument("--output")
    a = ap.parse_args()
    root = Path(a.store)

    if a.input:
        raw = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
        items = raw.get("matches", raw) if isinstance(raw, dict) else raw
        rows = []
        for it in items:
            out = it.get("output") or it
            probs_pct = find(out, "final_1x2_pct", "final_1x2")
            s90 = it.get("actual")
            if not probs_pct or not s90:
                continue
            rows.append({
                "match_id": it.get("match_id", "offline"),
                "snapshot_type": it.get("snapshot_type", "offline"),
                "version": str(it.get("engine_version") or "offline"),
                "league": str(it.get("competition") or it.get("stage") or "?"),
                "probs": [x / 100.0 for x in probs_pct],
                "actual_idx": actual_1x2(int(s90[0]), int(s90[1])),
                "actual_score": f"{int(s90[0])}-{int(s90[1])}",
                "top_scores": None, "ou25": None, "btts": None, "clv_pp": None,
                "snapshot_odds": None, "created_at": it.get("created_at") or "",
            })
    else:
        seen = {}
        dropped = []
        rows = []
        for e in load_jsonl(root / "registry.jsonl"):
            p = resolve_path(e.get("path", ""), root)
            if not p.exists():
                continue
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if a.snapshot and rec.get("snapshot_type") != a.snapshot:
                continue
            row, exc = score_record(rec, root)
            if row is None:
                continue
            key = (row["match_id"], row["snapshot_type"])
            cur = seen.get(key)
            if cur is None or (rec.get("created_at") or "") > (cur[1] or ""):
                if cur is not None:
                    dropped.append({"match_id": key[0], "snapshot_type": key[1], "superseded": cur[0]})
                seen[key] = (row["prediction_id"], rec.get("created_at"))
                row["created_at"] = rec.get("created_at") or ""
                rows.append(row)
            else:
                dropped.append({"match_id": key[0], "snapshot_type": key[1], "superseded": row["prediction_id"]})
        rows = attach_clv(rows)

    overall = summarize(rows)
    by_version = {}
    by_league = {}
    by_snapshot = {}
    for r in rows:
        by_version.setdefault(r["version"], []).append(r)
        by_league.setdefault(r["league"], []).append(r)
        by_snapshot.setdefault(r["snapshot_type"], []).append(r)
    report = {
        "schema_version": "fusion-backtest-1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": str(root),
        "sample_size": len(rows),
        "deduped_duplicates": len(dropped),
        "deduped_detail": dropped,
        "overall": overall,
        "by_version": {k: summarize(v) for k, v in sorted(by_version.items())},
        "by_league": {k: summarize(v) for k, v in sorted(by_league.items())},
        "by_snapshot": {k: summarize(v) for k, v in sorted(by_snapshot.items())},
        "calibration_gate": {
            "min_recalibration": 100,
            "threshold_review": 200,
            "ready_for_recalibration": len(rows) >= 100,
            "ready_for_threshold_review": len(rows) >= 200,
        },
        "warning": None if len(rows) >= 200 else "样本<200时结论不可靠。",
        "disclaimer": "概率模型输出，非投注建议。",
    }
    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "sample_size": len(rows),
        "deduped_duplicates": len(dropped),
        "overall": {k: v for k, v in overall.items() if k != "calibration_bins"},
        "by_version": {k: {x: y for x, y in summarize(v).items() if x != "calibration_bins"} for k, v in by_version.items()},
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
