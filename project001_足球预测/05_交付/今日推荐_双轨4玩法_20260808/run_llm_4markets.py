# -*- coding: utf-8 -*-
"""Batch LLM 4-market prediction — fixed client/env loading."""
from __future__ import annotations

import io
import argparse
import json
import os
import sys
import time
import winreg
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"C:/Users/Administrator/football-llm-predictor")
sys.path.insert(0, str(ROOT))


def load_user_env_keys():
    names = [
        "ZHIPU_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "GROQ_API_KEY",
        "GOOGLE_API_KEY",
        "ARK_API_KEY",
    ]
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment")
    except OSError:
        return
    for name in names:
        try:
            val, _ = winreg.QueryValueEx(key, name)
            if val and not os.environ.get(name):
                os.environ[name] = str(val)
        except OSError:
            pass
    for k in list(os.environ):
        if "proxy" in k.lower():
            os.environ.pop(k, None)


load_user_env_keys()
import football_predictor as fp  # noqa: E402

RUN_DIR = Path(__file__).resolve().parent
RAW = RUN_DIR / "raw_llm.json"
OUT_TXT = RUN_DIR / "llm_predictions.txt"
OUT_JSON = RUN_DIR / "llm_predictions.json"
MODELS = [
    "zhipu/glm-4-flash",
    "qwen/qwen-flash",
    "deepseek/deepseek-chat",
]


def build_extra(m: dict) -> str:
    parts = []
    odds = m.get("model_odds") or m.get("odds")
    if isinstance(odds, (list, tuple)) and len(odds) >= 3:
        parts.append(f"体彩胜平负HAD: 主{odds[0]}/平{odds[1]}/客{odds[2]}")
    hhad = m.get("hhad")
    if isinstance(hhad, dict):
        gl = hhad.get("goal_line")
        if gl is not None:
            parts.append(f"让球线{gl} 赔率{hhad.get('odds')}")
    elif isinstance(hhad, list) and hhad:
        parts.append(f"让球盘条目数{len(hhad)}")
    ttg = m.get("ttg")
    if isinstance(ttg, dict) and ttg:
        # pick lowest odds band as market lean if numeric
        try:
            items = [(k, float(v)) for k, v in ttg.items() if v not in (None, "")]
            if items:
                best = min(items, key=lambda x: x[1])
                parts.append(f"TTG市场最低赔档:{best[0]}@{best[1]}")
        except Exception:
            pass
    hafu = m.get("hafu")
    if isinstance(hafu, dict) and hafu:
        try:
            items = [(k, float(v)) for k, v in hafu.items() if v not in (None, "")]
            if items:
                best = min(items, key=lambda x: x[1])
                parts.append(f"HAFU市场最低赔:{best[0]}@{best[1]}")
        except Exception:
            pass
    return "；".join(parts)


def load_evidence(home: str, away: str) -> str:
    ev_dir = ROOT / "data" / "evidence_2026-08-08"
    if not ev_dir.exists():
        return ""
    for p in sorted(ev_dir.glob("evidence_*.md")):
        name = p.name
        if home and home in name:
            return p.read_text(encoding="utf-8", errors="replace")[:2500]
        if away and away in name:
            return p.read_text(encoding="utf-8", errors="replace")[:2500]
    return ""


def call_one(model: str, prompt: str) -> tuple:
    """Return (model_id, prediction_dict). call_model already parses JSON."""
    provider = fp.provider_for(model)
    client = fp.get_client(provider)
    # pass full model id; call_model strips provider internally
    mid, pred = fp.call_model(client, model, prompt, models_used=MODELS)
    if not isinstance(pred, dict):
        return model, {"error": f"bad pred type {type(pred)}"}
    return model, pred


def one_match(m: dict, idx: int) -> dict:
    home = m.get("home")
    away = m.get("away")
    league = m.get("league") or m.get("competition") or ""
    num = m.get("match_num") or (m.get("sporttery_meta") or {}).get("match_num") or f"M{idx:03d}"
    kick = m.get("kickoff_iso") or m.get("kickoff") or ""
    extra = build_extra(m)
    ev = load_evidence(home or "", away or "")
    if ev:
        extra = (extra + "\n【赛前证据】\n" + ev)[:3500]
    prompt = fp.build_user_prompt(home, away, league, extra)

    pred_map = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(call_one, model, prompt): model for model in MODELS}
        for fut in as_completed(futs):
            model = futs[fut]
            try:
                mid, pred = fut.result()
                pred_map[mid] = pred
            except Exception as e:
                pred_map[model] = {"error": str(e)}

    # aggregate expects dict model->pred
    agg = fp.aggregate(pred_map, MODELS)

    good = [
        {**p, "model": mid}
        for mid, p in pred_map.items()
        if isinstance(p, dict) and "error" not in p and p.get("result")
    ]

    # score from aggregate
    top_score = agg.get("top_score")
    if isinstance(top_score, (list, tuple)) and len(top_score) == 2:
        score = f"{top_score[0]}-{top_score[1]}"
    elif isinstance(top_score, str):
        score = top_score
    elif good:
        p0 = good[0]
        score = f"{p0.get('home_score')}-{p0.get('away_score')}"
    else:
        score = None

    ttg = agg.get("top_total_goals")
    if not ttg and score and "-" in str(score):
        try:
            a, b = str(score).split("-", 1)
            s = int(a) + int(b)
            ttg = "7+" if s >= 7 else str(s)
        except Exception:
            pass

    hafu = agg.get("top_hafu")
    ou_explicit = agg.get("top_ou25")
    hafu_votes = agg.get("all_hafu") or {}
    if not hafu and good:
        votes = {}
        for p in good:
            hr, fr = p.get("half_result"), p.get("result")
            if hr and fr:
                label = fp.hafu_result(hr, fr)
                if label:
                    votes[label] = votes.get(label, 0) + 1
        hafu_votes = votes
        hafu = max(votes, key=votes.get) if votes else None

    ou25 = locals().get("ou_explicit")
    if not ou25 and ttg is not None:
        try:
            n = 7 if ttg == "7+" else int(ttg)
            ou25 = "大2.5" if n >= 3 else "小2.5"
        except Exception:
            pass

    result_1x2 = agg.get("top_result")
    if not result_1x2 and good:
        from collections import Counter
        c = Counter(p.get("result") for p in good if p.get("result"))
        if c:
            result_1x2 = c.most_common(1)[0][0]

    model_rows = []
    for mid, p in pred_map.items():
        row = dict(p) if isinstance(p, dict) else {"error": str(p)}
        row["model"] = mid
        model_rows.append(row)

    return {
        "match_num": num,
        "home": home,
        "away": away,
        "league": league,
        "kickoff": kick,
        "models": model_rows,
        "aggregate": agg,
        "markets": {
            "1x2": result_1x2,
            "score": score,
            "ttg": ttg,
            "ou25": ou25,
            "hafu": hafu,
            "hafu_votes": hafu_votes,
            "confidence": (agg.get("avg_confidence") if isinstance(agg, dict) else None),
            "alt_direction": agg.get("alt_direction") if isinstance(agg, dict) else None,
            "caution": agg.get("caution") if isinstance(agg, dict) else None,
            "collapse_flags": agg.get("collapse_flags") if isinstance(agg, dict) else None,
            "votes": agg.get("all_results") if isinstance(agg, dict) else None,
        },
        "odds": m.get("model_odds") or m.get("odds"),
        "ok": bool(result_1x2) and "error" not in agg,
    }


def json_safe(obj):
    """Make nested structures JSON-serializable (tuple keys etc.)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, tuple):
                nk = "-".join(str(x) for x in k)
            elif isinstance(k, (str, int, float, bool)) or k is None:
                nk = k
            else:
                nk = str(k)
            out[nk] = json_safe(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [json_safe(x) for x in obj]
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--out-json", default=str(OUT_JSON))
    ap.add_argument("--out-txt", default=str(OUT_TXT))
    args = ap.parse_args()
    raw_path = Path(args.raw)
    out_json = Path(args.out_json)
    out_txt = Path(args.out_txt)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    load_user_env_keys()
    print("keys", {k: bool(os.environ.get(k)) for k in ["ZHIPU_API_KEY", "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY"]})
    raw = json.loads(io.open(raw_path, encoding="utf-8-sig").read())
    matches = raw.get("matches") or []
    results = []
    lines = [f"LLM 4玩法 {time.strftime('%Y-%m-%d %H:%M')} models={MODELS} n={len(matches)}\n"]

    for i, m in enumerate(matches, 1):
        print(f"\n=== {i}/{len(matches)} {m.get('home')} vs {m.get('away')} ===", flush=True)
        try:
            r = one_match(m, i)
        except Exception as e:
            r = {
                "home": m.get("home"),
                "away": m.get("away"),
                "match_num": m.get("match_num"),
                "error": str(e),
                "ok": False,
                "markets": {},
            }
        results.append(json_safe(r))
        mk = r.get("markets") or {}
        lines.append(
            f"\n⚽ {r.get('match_num')} {r.get('home')} vs {r.get('away')} | {r.get('league')} | {r.get('kickoff')}\n"
            f"  胜平负:{mk.get('1x2')} 比分:{mk.get('score')} 总进球:{mk.get('ttg')} "
            f"大小2.5:{mk.get('ou25')} 半全场:{mk.get('hafu')}\n"
        )
        for p in r.get("models") or []:
            if p.get("error"):
                lines.append(f"  - {p.get('model')}: ERROR {p.get('error')}\n")
            else:
                lines.append(
                    f"  - {p.get('model')}: {p.get('result')} {p.get('home_score')}-{p.get('away_score')} "
                    f"总:{p.get('total_goals')} 半:{p.get('half_result')} — {str(p.get('reasoning') or '')[:100]}\n"
                )
        out_txt.write_text("".join(lines), encoding="utf-8")
        out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        if i < len(matches):
            time.sleep(2)

    ok = sum(1 for r in results if r.get("ok"))
    print("DONE", len(results), "ok", ok, out_json)


if __name__ == "__main__":
    main()
