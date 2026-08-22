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
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# 本模块常被 importlib.spec_from_file_location 直接加载（测试、外部工具），
# 那种加载方式不会把 scripts/ 放进 sys.path，同目录模块会 ModuleNotFoundError。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from runtime_paths import backtest_store

# 2026-08-16 修正：原默认值硬编码指向外部 football-quant-fusion-suite。
# 那是一份物理拷贝、且比仓库内唯一事实源旧，忘了传 --store 就会**静默评测错的库**
# （calibration_gate、current_version_n 全部跟着错）。改走 runtime_paths 的仓库内默认值。
DEFAULT_STORE = backtest_store()


# [中文功能] 按行读取 jsonl
def load_jsonl(path):
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def dedupe_snapshot_rows(rows):
    """同一比赛、快照和概率版本只保留 created_at 最新的一条。

    同场在新版本发布后重跑属于不同可审计概率 cohort，不能被旧版本
    的同名 ``prematch`` 快照静默覆盖；主评测随后仍按赛前时刻只选一条。
    """
    selected = {}
    dropped = []
    for row in rows:
        model = row.get("model") or {}
        key = (
            row.get("match_id"),
            str(row.get("snapshot_type") or "unspecified").lower(),
            str(model.get("model_version") or "unknown"),
            str(model.get("probability_signature") or "unknown"),
        )
        current = selected.get(key)
        if current is None or str(row.get("created_at") or "") > str(current.get("created_at") or ""):
            if current is not None:
                dropped.append({"match_id": key[0], "snapshot_type": key[1],
                                "superseded": current.get("prediction_id")})
            selected[key] = row
        else:
            dropped.append({"match_id": key[0], "snapshot_type": key[1],
                            "superseded": row.get("prediction_id")})
    return list(selected.values()), dropped


def _snapshot_rank(snapshot_type):
    value = str(snapshot_type or "").lower().replace("_", "-").replace(" ", "")
    if value in {"closing", "close"}:
        return 60
    if value in {"prematch", "pre-match"}:
        return 50
    if value in {"t-4h", "tminus4h", "tminus-4h"}:
        return 40
    if value in {"t-6h", "tminus6h", "tminus-6h"}:
        return 35
    if value in {"t-24h", "tminus24h", "tminus-24h"}:
        return 25
    if value in {"opening", "open"}:
        return 10
    return 0


def _selection_time(row):
    """Return the auditable prediction time used for primary-snapshot choice.

    ``snapshot_type`` is a label (for example, an older generic ``prematch``
    or a later ``T-7h``) and must not decide which deployed version is
    evaluated.  Formal records carry ``prediction_as_of``; legacy records
    fall back to their immutable registry creation time.
    """
    raw = row.get("prediction_as_of") or row.get("created_at") or ""
    if not isinstance(raw, str):
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def select_primary_rows(rows, policy="latest_before_kickoff"):
    """按比赛选择一个主评估快照；其他快照仅用于时点研究。"""
    by_match = {}
    for row in rows:
        by_match.setdefault(row.get("match_id"), []).append(row)
    selected = []
    for candidates in by_match.values():
        if policy in {"prematch", "closing"}:
            exact = [r for r in candidates
                     if str(r.get("snapshot_type") or "").lower() == policy]
            if not exact:
                continue
            chosen = max(exact, key=lambda r: str(r.get("created_at") or ""))
        elif policy == "latest_before_kickoff":
            chosen = max(candidates, key=lambda r: (_selection_time(r),
                                                     _snapshot_rank(r.get("snapshot_type")),
                                                     str(r.get("created_at") or "")))
        else:
            raise ValueError(f"unknown snapshot policy: {policy}")
        selected.append(chosen)
    return selected


def _is_sha256(value):
    v = str(value or "")
    return len(v) == 64 and all(c in "0123456789abcdef" for c in v.lower())


def engine_build_key(row):
    """样本的引擎构建指纹，用于区分「同版本样本」（评测规则要求按引擎完整哈希分组）。

    冻结哈希（engine_bundle_sha256）是首选口径。2026-08-03 版本戳修复之前登记的样本
    没有冻结哈希，但 model.engine_sha256（predict.py 源码哈希）+ core_engine_version
    足以把它们分成互不混淆的构建组——这些样本可归因，只是归因粒度较粗，
    不应与真正无法归因的样本混在同一个桶里。返回 "" 表示确实无法归因。
    """
    model = row.get("model") or {}
    bundle = model.get("engine_bundle_sha256")
    if _is_sha256(bundle):
        return f"bundle-{str(bundle)[:12]}"
    engine = model.get("engine_sha256")
    if _is_sha256(engine):
        core = str(row.get("core_engine_version") or model.get("core_version") or "?")
        return f"engine-{str(engine)[:12]}+core-{core}"
    return ""


def load_version_aliases(target_model_version=None):
    """读取 manifest 里经重放验证的等价旧版本清单。

    2026-08-16 新增。`probability_signature` 是概率文件的**字节**哈希，所以对
    `probability_files` 名单里的文件而言，「改一个字节就重置样本」的死锁原样存在——
    m1→m2 就是这么丢掉 34 场的（影子路由重构，生产路由概率一位没变）。

    别名的唯一合法来源是 `probability_replay_check.py` 的 `equivalent` 判定：
    用旧样本登记时保存的 input 重跑当前代码，概率逐场一致才可写进 manifest。
    匹配要求 (model_version, probability_signature, equivalent_to_model_version)
    **精确成对**：别名只属于当时已重放验证的目标版本，不能跨越之后的
    概率变更（例如 m3 的1X2等价不能把 m4 的比分/O-U样本也算作已验证）。
    """
    path = Path(__file__).resolve().parent.parent / "config" / "version_manifest.json"
    if not path.exists():
        return []
    try:
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    aliases = manifest.get("model_version_aliases") or []
    valid = [a for a in aliases if isinstance(a, dict)
             and a.get("model_version") and _is_sha256(a.get("probability_signature"))
             and a.get("equivalent_to_model_version")]
    if target_model_version is None:
        return valid
    return [a for a in valid if str(a["equivalent_to_model_version"]) == str(target_model_version)]


def version_cohort(row, current_identity):
    """语义版本 model_version + 概率签名匹配才属于 current；旧版 legacy，其余 unknown。

    2026-08-15 版本管理方案：cohort 主键从「5 字段全量字节哈希」改为
    「model_version + probability_signature」，框架代码/日志/注释的改动不再重置样本。
    旧记录无 model_version/probability_signature 时回退到引擎构建指纹归 legacy。

    2026-08-16 补充：经重放验证概率等价的旧版本（manifest `model_version_aliases`）
    也算 current——否则一次数值中性的重构就要重新攒 100 场。
    """
    model = row.get("model") or {}
    row_mv = str(model.get("model_version") or "").strip()
    row_ps = str(model.get("probability_signature") or "").strip()
    cur_mv = str(current_identity.get("model_version") or "").strip()
    cur_ps = str(current_identity.get("probability_signature") or "").strip()
    if cur_mv and cur_mv != "unknown" and cur_ps and _is_sha256(cur_ps):
        if row_mv == cur_mv and row_ps == cur_ps:
            return "current"
        for alias in load_version_aliases(cur_mv):
            if (str(alias.get("equivalent_to_model_version")) == cur_mv
                    and row_mv == alias["model_version"]
                    and row_ps == alias["probability_signature"]):
                return "current"
    version = str(row.get("version") or "").strip().lower()
    identifiable = version and version not in {"unknown", "offline", "none"} and "unknown" not in version
    if identifiable or engine_build_key(row):
        return "legacy"
    return "unknown"


# [中文功能] 旧容器路径 /var/minis/... 自动映射到本机 shared 目录
def resolve_path(p_str, root):
    """解析预测文件路径，`--store` 指向的仓库内目录是唯一权威来源。

    2026-08-15 修正：原实现优先信任 registry 里记录的绝对路径（`p.exists()` 命中
    就直接用），但那是登记当时生效的容器/外部套件路径。仓库内 `--store` 与外部套件
    `C:/Users/Administrator/.codex/skills/football-quant-fusion-suite/shared/...`
    是两份物理分裂的目录（见 AGENTS.md §0），只要外部那份文件还在，就会被静默读取，
    --store 形同虚设（复盘 `06_复盘/2026-08-15_模型评测/复盘_模型评测_20260815.md`
    审计出全部 1562 条走的都是这条隐藏分支，只是内容当时恰好一致，不能保证以后也一致）。
    现改为优先按 `.../football-quant-fusion/backtest/` 标记之后的相对段落定位到
    `--store` 内；只有仓库内确实找不到，才退回 registry 记录的原始路径兜底。
    """
    norm = str(p_str).replace("\\", "/")
    marker = "/football-quant-fusion/backtest/"
    if marker in norm:
        cand = root / norm.split(marker, 1)[1]
        if cand.exists():
            return cand
    if norm.startswith("/var/minis/shared/"):
        cand = root.parents[1] / norm[len("/var/minis/shared/"):]
        if cand.exists():
            return cand
    return Path(p_str)


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


def _percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    pos = (len(ordered) - 1) * q
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def paired_market_comparison(rows, iterations=2000, seed=20260808):
    """同场比较模型与市场，按比赛差值做确定性paired bootstrap。"""
    pairs = []
    for row in rows:
        market = row.get("market_probs")
        if not isinstance(market, list) or len(market) != 3:
            continue
        idx = row["actual_idx"]
        pairs.append((brier(row["probs"], idx) - brier(market, idx),
                      logloss(row["probs"], idx) - logloss(market, idx)))
    if not pairs:
        return {"n": 0, "status": "no_paired_market_probability"}
    n = len(pairs)
    b_mean = sum(x[0] for x in pairs) / n
    l_mean = sum(x[1] for x in pairs) / n
    rng = random.Random(seed)
    boot_b, boot_l = [], []
    for _ in range(max(1, int(iterations))):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        boot_b.append(sum(x[0] for x in sample) / n)
        boot_l.append(sum(x[1] for x in sample) / n)
    return {
        "n": n,
        "bootstrap_iterations": max(1, int(iterations)),
        "seed": seed,
        "brier_delta_model_minus_market": round(b_mean, 8),
        "brier_delta_95ci": [round(_percentile(boot_b, 0.025), 8),
                             round(_percentile(boot_b, 0.975), 8)],
        "log_loss_delta_model_minus_market": round(l_mean, 8),
        "log_loss_delta_95ci": [round(_percentile(boot_l, 0.025), 8),
                                round(_percentile(boot_l, 0.975), 8)],
        "interpretation": "负值表示模型优于同场市场；95%CI不跨0才视为有统计证据。",
    }


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
    top1 = top3 = top5 = score_n = 0
    full_score_n = 0
    sll = 0.0
    n_ou = n_ou35 = n_bt = 0
    ou_b = ou35_b = bt_b = 0.0
    ou_hit = ou35_hit = 0
    clv = []
    for r in rows:
        probs, idx = r["probs"], r["actual_idx"]
        obs += [(p, 1 if i == idx else 0) for i, p in enumerate(probs)]
        bs.append(brier(probs, idx))
        ls.append(logloss(probs, idx))
        hit.append(int(max(range(3), key=lambda i: probs[i]) == idx))
        if r.get("top_scores") is not None and r.get("actual_score") is not None:
            score_n += 1
            top1 += int(r["top_scores"].get("top1"))
            top3 += int(r["top_scores"].get("top3"))
            top5 += int(r["top_scores"].get("top5"))
        matrix = r.get("score_matrix")
        if isinstance(matrix, dict) and r.get("actual_score") is not None:
            probability = matrix.get(r["actual_score"])
            if isinstance(probability, (int, float)) and not isinstance(probability, bool) and probability > 0:
                full_score_n += 1
                sll += -math.log(max(1e-12, min(1 - 1e-12, float(probability))))
        if r.get("ou25") is not None:
            n_ou += 1
            ou_b += (r["ou25"]["over"] - r["ou25"]["actual"]) ** 2
            ou_hit += int((r["ou25"]["over"] >= 0.5) == bool(r["ou25"]["actual"]))
        if r.get("ou35") is not None:
            n_ou35 += 1
            ou35_b += (r["ou35"]["over"] - r["ou35"]["actual"]) ** 2
            ou35_hit += int((r["ou35"]["over"] >= 0.5) == bool(r["ou35"]["actual"]))
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
    if score_n:
        out["score"] = {
            "top1_accuracy_pct": round(top1 / score_n * 100, 2),
            "top3_accuracy_pct": round(top3 / score_n * 100, 2),
            "top5_accuracy_pct": round(top5 / score_n * 100, 2),
            "full_matrix_n": full_score_n,
            "score_log_loss": round(sll / full_score_n, 5) if full_score_n else None,
        }
    if n_ou:
        out["ou_2_5_brier"] = round(ou_b / n_ou, 6)
        out["ou_2_5"] = {"n": n_ou, "brier": round(ou_b / n_ou, 6),
                          "accuracy_pct": round(ou_hit / n_ou * 100, 2)}
    if n_ou35:
        out["ou_3_5"] = {"n": n_ou35, "brier": round(ou35_b / n_ou35, 6),
                          "accuracy_pct": round(ou35_hit / n_ou35 * 100, 2)}
    if n_bt:
        out["btts_brier"] = round(bt_b / n_bt, 6)
    if clv:
        out["clv_mean_pp"] = round(sum(clv) / len(clv), 3)
        out["clv_n"] = len(clv)
    return out


def walk_forward_report(rows, folds=5, bootstrap_iterations=2000):
    """按开球日期做扩展窗口评估；同一天比赛绝不跨训练/测试边界。"""
    dated = [r for r in rows if str(r.get("kickoff") or "")[:10]]
    dates = sorted({str(r.get("kickoff"))[:10] for r in dated})
    folds = max(1, int(folds))
    if len(dates) < folds + 1:
        return {"status": "insufficient_time_groups", "date_groups": len(dates),
                "requested_folds": folds, "folds": []}
    initial = max(1, len(dates) // (folds + 1))
    remaining = len(dates) - initial
    reports = []
    all_test = []
    for i in range(folds):
        start = initial + round(i * remaining / folds)
        end = initial + round((i + 1) * remaining / folds)
        test_dates = set(dates[start:end])
        if not test_dates:
            continue
        train = [r for r in dated if str(r.get("kickoff"))[:10] < dates[start]]
        test = [r for r in dated if str(r.get("kickoff"))[:10] in test_dates]
        all_test.extend(test)
        reports.append({
            "fold": i + 1,
            "train_start": min(str(r.get("kickoff")) for r in train),
            "train_end": max(str(r.get("kickoff")) for r in train),
            "test_start": min(str(r.get("kickoff")) for r in test),
            "test_end": max(str(r.get("kickoff")) for r in test),
            "train_n": len(train),
            "test_n": len(test),
            "train_match_ids": sorted({r.get("match_id") for r in train}),
            "test_match_ids": sorted({r.get("match_id") for r in test}),
            "test_metrics": summarize(test),
            "paired_market": paired_market_comparison(
                test, iterations=bootstrap_iterations, seed=20260808 + i),
        })
    return {
        "status": "ok",
        "method": "expanding_window_grouped_by_kickoff_date",
        "fold_count": len(reports),
        "folds": reports,
        "combined_test_n": len(all_test),
        "combined_test_metrics": summarize(all_test),
        "combined_paired_market": paired_market_comparison(
            all_test, iterations=bootstrap_iterations, seed=20260808),
    }


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
    market_pct = find(out, "market_prob_pct") or find(core, "market_prob_pct")
    if isinstance(market_pct, list) and len(market_pct) == 3:
        market_probs = [float(x) / 100.0 for x in market_pct]
    else:
        try:
            market_probs = devig([float(x) for x in ((rec.get("input") or {}).get("odds") or [])])
            if len(market_probs) != 3:
                market_probs = None
        except Exception:
            market_probs = None
    idx = actual_1x2(h, a)
    top_list = fc.get("top_scores") or core.get("top_scores") or []
    score_view = None
    score_matrix = None
    actual_score = f"{h}-{a}"
    if top_list:
        ranked = [x.get("score") for x in sorted(top_list, key=lambda x: x.get("prob_pct", 0), reverse=True)]
        score_view = {
            "top1": int(ranked and ranked[0] == actual_score),
            "top3": int(actual_score in ranked[:3]),
            "top5": int(actual_score in ranked[:5]),
        }
    raw_matrix = fc.get("score_matrix") or core.get("score_matrix")
    if isinstance(raw_matrix, dict):
        parsed = {}
        for score, probability in raw_matrix.items():
            if (isinstance(probability, (int, float)) and not isinstance(probability, bool)
                    and 0.0 <= float(probability) <= 1.0):
                parsed[str(score)] = float(probability)
        if parsed and 0.99 <= sum(parsed.values()) <= 1.01:
            score_matrix = parsed
    ou = fc.get("ou_2_5") or core.get("ou_2_5") or {}
    ou_view = None
    if ou.get("over_pct") is not None:
        ou_view = {"over": float(ou["over_pct"]) / 100.0, "actual": 1 if h + a > 2.5 else 0}
    ou35 = fc.get("ou_3_5") or core.get("ou_3_5") or {}
    ou35_view = None
    if ou35.get("over_pct") is not None:
        ou35_view = {"over": float(ou35["over_pct"]) / 100.0, "actual": 1 if h + a > 3.5 else 0}
    bt = fc.get("btts") or core.get("btts") or {}
    bt_view = None
    if bt.get("yes_pct") is not None:
        bt_view = {"yes": float(bt["yes_pct"]) / 100.0, "actual": 1 if h > 0 and a > 0 else 0}
    _m = rec.get("model")
    _version = _m.get("version") if isinstance(_m, dict) else str(_m or "")
    return {
        "prediction_id": rec.get("prediction_id"),
        "match_id": mid,
        "created_at": rec.get("created_at") or "",
        "prediction_as_of": rec.get("prediction_as_of") or "",
        "snapshot_type": rec.get("snapshot_type"),
        "version": _version,
        "model": _m if isinstance(_m, dict) else {},
        "core_engine_version": (rec.get("output") or {}).get("core_engine_version"),
        "league": ((rec.get("match") or {}).get("competition")) or ((rec.get("match") or {}).get("stage")) or "?",
        "probs": probs,
        "market_probs": market_probs,
        "actual_idx": idx,
        "actual_score": actual_score,
        "top_scores": score_view,
        "score_matrix": score_matrix,
        "ou25": ou_view,
        "ou35": ou35_view,
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
    ap.add_argument("--evaluation-unit", choices=("match", "snapshot"), default="match")
    ap.add_argument("--snapshot-policy", choices=("latest_before_kickoff", "prematch", "closing"),
                    default="latest_before_kickoff")
    ap.add_argument("--walk-forward-folds", type=int, default=5)
    ap.add_argument("--bootstrap-iterations", type=int, default=2000)
    ap.add_argument("--output")
    a = ap.parse_args()
    root = Path(a.store)

    if a.input:
        raw = json.loads(Path(a.input).read_text(encoding="utf-8-sig"))
        items = raw.get("matches", raw) if isinstance(raw, dict) else raw
        raw_rows = []
        for it in items:
            out = it.get("output") or it
            probs_pct = find(out, "final_1x2_pct", "final_1x2")
            market_pct = find(out, "market_prob_pct")
            s90 = it.get("actual")
            if not probs_pct or not s90:
                continue
            raw_rows.append({
                "match_id": it.get("match_id", "offline"),
                "snapshot_type": it.get("snapshot_type", "offline"),
                "version": str(it.get("engine_version") or "offline"),
                "model": it.get("model") or {},
                "league": str(it.get("competition") or it.get("stage") or "?"),
                "probs": [x / 100.0 for x in probs_pct],
                "market_probs": ([x / 100.0 for x in market_pct]
                                   if isinstance(market_pct, list) and len(market_pct) == 3 else None),
                "actual_idx": actual_1x2(int(s90[0]), int(s90[1])),
                "actual_score": f"{int(s90[0])}-{int(s90[1])}",
                "top_scores": None, "ou25": None, "btts": None, "clv_pp": None,
                "snapshot_odds": None, "created_at": it.get("created_at") or "",
                "kickoff": it.get("kickoff") or "",
            })
        snapshot_rows, dropped = dedupe_snapshot_rows(raw_rows)
    else:
        raw_rows = []
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
            raw_rows.append(row)
        snapshot_rows, dropped = dedupe_snapshot_rows(raw_rows)
        snapshot_rows = attach_clv(snapshot_rows)

    from fusion_predict_core import build_identity
    current_identity = build_identity()
    for row in snapshot_rows:
        row["version_cohort"] = version_cohort(row, current_identity)
    rows = (select_primary_rows(snapshot_rows, a.snapshot_policy)
            if a.evaluation_unit == "match" else list(snapshot_rows))

    overall = summarize(rows)
    by_version = {}
    by_league = {}
    by_snapshot = {}
    by_cohort = {"current": [], "legacy": [], "unknown": []}
    by_engine_build = {}
    by_model_version = {}
    for r in rows:
        by_version.setdefault(r["version"], []).append(r)
        by_league.setdefault(r["league"], []).append(r)
        by_cohort[r["version_cohort"]].append(r)
        by_engine_build.setdefault(engine_build_key(r) or "unattributable", []).append(r)
        by_model_version.setdefault(
            str((r.get("model") or {}).get("model_version") or "unattributable"), []).append(r)
    for r in snapshot_rows:
        by_snapshot.setdefault(r["snapshot_type"], []).append(r)
    current_n = len(by_cohort["current"])
    report = {
        "schema_version": "fusion-backtest-2.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "store": str(root),
        "evaluation_unit": a.evaluation_unit,
        "snapshot_policy": a.snapshot_policy,
        "record_sample_size": len(snapshot_rows),
        "sample_size": len(rows),
        "unique_match_n": len({r.get("match_id") for r in rows}),
        "deduped_duplicates": len(dropped),
        "deduped_detail": dropped,
        "overall": overall,
        "by_version": {k: summarize(v) for k, v in sorted(by_version.items())},
        "by_version_cohort": {k: summarize(v) for k, v in by_cohort.items()},
        "by_engine_build": {k: summarize(v) for k, v in sorted(by_engine_build.items())},
        "by_model_version": {k: summarize(v) for k, v in sorted(by_model_version.items())},
        "by_league": {k: summarize(v) for k, v in sorted(by_league.items())},
        "snapshot_research": {
            "record_sample_size": len(snapshot_rows),
            "by_snapshot": {k: summarize(v) for k, v in sorted(by_snapshot.items())},
        },
        "paired_market": paired_market_comparison(
            rows, iterations=a.bootstrap_iterations, seed=20260808),
        "walk_forward": walk_forward_report(
            rows, folds=a.walk_forward_folds, bootstrap_iterations=a.bootstrap_iterations),
        "current_identity": current_identity,
        "calibration_gate": {
            "min_recalibration": 100,
            "threshold_review": 200,
            "current_version_n": current_n,
            "ready_for_recalibration": current_n >= 100,
            "ready_for_threshold_review": current_n >= 200,
        },
        "warning": None if current_n >= 200 else "当前精确代码/配置版本独立比赛<200，不得据此宣称优于市场。",
        "disclaimer": "概率模型输出，非投注建议。",
    }
    if a.output:
        Path(a.output).parent.mkdir(parents=True, exist_ok=True)
        Path(a.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "ok",
        "record_sample_size": len(snapshot_rows),
        "sample_size": len(rows),
        "unique_match_n": len({r.get("match_id") for r in rows}),
        "deduped_duplicates": len(dropped),
        "overall": {k: v for k, v in overall.items() if k != "calibration_bins"},
        "by_version": {k: {x: y for x, y in summarize(v).items() if x != "calibration_bins"} for k, v in by_version.items()},
        "output": a.output,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
