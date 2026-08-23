#!/usr/bin/env python3
"""解析 predict.py 输出，生成 PPT/报告用的 parsed JSON。

用法: python parse_predictions.py <predict_txt> [...] --out <parsed.json> --raw <raw.json>
对齐顺序：match_id → match_num → 无身份时才按输出顺序（aligned_by=order）。
"""

import json
import sys
from pathlib import Path

_FUSION_SCRIPTS = Path(__file__).resolve().parents[2] / "skill" / "football-quant-fusion" / "scripts"
if str(_FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_FUSION_SCRIPTS))
try:
    from job_ticket import identity_from, jobs_root, llm_from_parsed, normalize_match_id, upsert_job
except ImportError:  # pragma: no cover
    normalize_match_id = None
    upsert_job = None


def _fallback_normalize(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower().startswith("sporttery-"):
        rest = text.split("-", 1)[1].strip()
        return f"sporttery-{rest}" if rest else None
    if text.isdigit():
        return f"sporttery-{text}"
    return None


def canon_id(value):
    fn = normalize_match_id or _fallback_normalize
    return fn(value)


def extract_audit_lines(path):
    """predict.py 输出中每场一条 JSON（顶层含 direction/votes/strength 的 audit record）。"""
    rows = []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "direction" in obj and "all_votes" in obj and "match_index" not in obj and "status" not in obj:
            if obj.get("single_pick"):
                rows.append(obj)
    return rows


def index_raw(matches):
    by_id, by_num = {}, {}
    for match in matches:
        mid = canon_id(match.get("match_id"))
        if mid:
            by_id[mid] = match
        if match.get("match_num"):
            by_num[match["match_num"]] = match
    return by_id, by_num


def align_audit(audit, by_id, by_num, matches, order_index, start_index):
    mid = canon_id(audit.get("match_id"))
    num = audit.get("match_num")
    if mid and mid in by_id:
        return by_id[mid], "match_id"
    if num and num in by_num:
        return by_num[num], "match_num"
    if mid or num:
        return {}, "unmatched"
    pos = start_index - 1 + order_index
    if 0 <= pos < len(matches):
        return matches[pos], "order"
    return {}, "unmatched"


def parse_audits(audits, raw, start_index=1):
    matches = raw.get("matches") or []
    by_id, by_num = index_raw(matches)
    parsed = []
    for j, audit in enumerate(audits):
        meta, aligned_by = align_audit(audit, by_id, by_num, matches, j, start_index)
        if aligned_by == "unmatched":
            print(f"跳过未对齐 audit: match_id={audit.get('match_id')} match_num={audit.get('match_num')}")
            continue
        sp = audit.get("single_pick") or {}
        evs = {}
        eva = (audit.get("ev_recommendation") or {}).get("ev_analysis") or {}
        for direction, value in eva.items():
            evs[direction] = round(value["ev"], 4)
        mid = canon_id(audit.get("match_id") or meta.get("match_id"))
        parsed.append({
            "match_id": mid,
            "num": meta.get("match_num") or audit.get("match_num") or "",
            "home": meta.get("home", audit.get("home", "")),
            "away": meta.get("away", audit.get("away", "")),
            "league": meta.get("league", audit.get("league", "")),
            "kickoff": meta.get("kickoff_iso") or meta.get("kickoff") or audit.get("kickoff") or "",
            "dir": audit.get("direction"),
            "alt": audit.get("alt_direction"),
            "probs_1x2": audit.get("probs_1x2") or audit.get("probs"),
            "confidence": audit.get("confidence"),
            "decision": audit.get("decision"),
            "strength": round((audit.get("strength") or 0) * 100),
            "votes": audit.get("votes"),
            "total_votes": audit.get("total_votes"),
            "sp": sp.get("pick"),
            "sp_conf": round((sp.get("confidence") or 0) * 100),
            "sp_skip": sp.get("skip"),
            "sp_action": sp.get("action") or ("observe" if sp.get("skip") else None),
            "sp_bettable": sp.get("bettable"),
            "score": audit.get("top_score_pref"),
            "top_scores": audit.get("top_scores") or audit.get("score_prefs"),
            "score_prefs": audit.get("score_prefs"),
            "ou25": audit.get("top_ou25"),
            "hafu": audit.get("top_hafu"),
            "evs": evs,
            "ev_action": (audit.get("ev_recommendation") or {}).get("action"),
            "ev_reason": (audit.get("ev_recommendation") or {}).get("reason"),
            "caution": audit.get("caution"),
            "collapse_flags": audit.get("collapse_flags"),
            "evidence_gap": audit.get("evidence_gap"),
            "model_dirs": {k.split("/")[-1]: v.get("direction") for k, v in (audit.get("individual") or {}).items()},
            "aligned_by": aligned_by,
        })
    parsed.sort(key=lambda p: p["num"])
    return parsed


def write_jobs(parsed, raw):
    if upsert_job is None or identity_from is None:
        return 0
    written = 0
    sales_day = raw.get("sales_day")
    by_id, by_num = index_raw(raw.get("matches") or [])
    for row in parsed:
        meta = by_id.get(row.get("match_id")) or by_num.get(row.get("num")) or {}
        ident = identity_from(meta, row)
        ident["sales_day"] = ident.get("sales_day") or sales_day
        if not ident.get("match_id"):
            continue
        upsert_job(jobs_root(), ident, llm=llm_from_parsed(row))
        written += 1
    return written


def main():
    args = list(sys.argv[1:])
    out_path = None
    raw_path = None
    start_index = 1
    write_job_files = True
    txts = []
    i = 0
    while i < len(args):
        if args[i] == "--out":
            out_path = args[i + 1]
            i += 2
        elif args[i] == "--raw":
            raw_path = args[i + 1]
            i += 2
        elif args[i] == "--start-index":
            start_index = int(args[i + 1])
            i += 2
        elif args[i] == "--no-jobs":
            write_job_files = False
            i += 1
        else:
            txts.append(args[i])
            i += 1
    raw = json.load(open(raw_path, encoding="utf-8"))
    audits = []
    for path in txts:
        audits.extend(extract_audit_lines(path))
    print(f"提取 audit 记录: {len(audits)} 条（起始序号 {start_index}）")
    parsed = parse_audits(audits, raw, start_index)
    if write_job_files:
        n = write_jobs(parsed, raw)
        if n:
            print(f"工单已更新: {n} 场")
    if out_path:
        json.dump(parsed, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"写出: {out_path} 共 {len(parsed)} 场")
    else:
        print(json.dumps(parsed, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
