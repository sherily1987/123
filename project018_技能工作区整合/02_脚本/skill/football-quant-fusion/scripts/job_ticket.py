#!/usr/bin/env python3
"""统一工单：多智能体共用的输入/输出钥匙。

一场球一张卡，主键永远是 sporttery-<体彩数字id>。
量化轨和 LLM 轨各写 outputs[] 里自己的一条，禁止揉成「更准」。
PPT / 控制台 / SQLite 只是投影，不是事实源。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "football-job-1.0"
DIR_TO_CODE = {"主胜": "H", "平局": "D", "客胜": "A"}
CODE_TO_DIR = {"H": "主胜", "D": "平局", "A": "客胜"}
RESEARCH_SIDECARS = ("intl_kelly", "odds_movement")
_STAKE_KEYS = ("kelly_fraction", "f_star", "f*", "stake", "recommended_stake")


def normalize_match_id(value) -> str | None:
    """2040898 / '2040898' / 'sporttery-2040898' → 'sporttery-2040898'。"""
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


def identity_from(data: dict | None, extra: dict | None = None) -> dict:
    """从融合裸 dict、体彩 raw 场次、或已有输出里抽出身份。"""
    data = data or {}
    extra = extra or {}
    sm = data.get("sporttery_meta") or extra.get("sporttery_meta") or {}
    match_id = normalize_match_id(
        sm.get("match_id")
        or data.get("match_id")
        or extra.get("match_id")
    )
    kickoff = (
        data.get("kickoff")
        or data.get("kickoff_iso")
        or extra.get("kickoff")
        or extra.get("kickoff_iso")
    )
    sales_day = (
        data.get("sales_day")
        or extra.get("sales_day")
        or sm.get("business_date")
        or _date_from_kickoff(kickoff)
    )
    return {
        "match_id": match_id,
        "match_num": sm.get("match_num") or data.get("match_num") or extra.get("match_num") or extra.get("num"),
        "sales_day": sales_day,
        "home": data.get("home") or extra.get("home"),
        "away": data.get("away") or extra.get("away"),
        "competition": (
            data.get("competition")
            or data.get("stage")
            or data.get("league")
            or extra.get("competition")
            or extra.get("league")
        ),
        "kickoff": kickoff,
    }


def stamp_identity(payload: dict, data: dict | None) -> dict:
    """把 match_id / match_num 写到融合输出根上（不覆盖已有非空值）。"""
    ident = identity_from(data, payload)
    if ident.get("match_id") and not payload.get("match_id"):
        payload["match_id"] = ident["match_id"]
    if ident.get("match_num") and not payload.get("match_num"):
        payload["match_num"] = ident["match_num"]
    return payload


def assemble_job(
    *,
    identity: dict,
    input_obj: dict | None = None,
    quant: dict | None = None,
    llm: dict | None = None,
    research: dict | None = None,
    settlement: dict | None = None,
    existing: dict | None = None,
) -> dict:
    """组装或合并一张工单。同轨后写覆盖前写；不同轨并存。"""
    ident = {k: identity.get(k) for k in (
        "match_id", "match_num", "sales_day", "home", "away", "competition", "kickoff"
    )}
    ident["match_id"] = normalize_match_id(ident.get("match_id"))
    if existing and existing.get("identity"):
        for key, value in existing["identity"].items():
            if ident.get(key) in (None, "") and value not in (None, ""):
                ident[key] = value
    outputs = []
    if existing:
        outputs.extend(existing.get("outputs") or [])
    if quant:
        outputs = _upsert_track(outputs, _normalize_quant(quant))
    if llm:
        outputs = _upsert_track(outputs, _normalize_llm(llm))
    research_obj = dict((existing or {}).get("research") or {})
    if research:
        hybrid_src = dict(research)
        sidecars = {}
        for key in RESEARCH_SIDECARS:
            if key in hybrid_src:
                sidecars[key] = hybrid_src.pop(key)
        if hybrid_src:
            blob = hybrid_src
            blob["research_only"] = True
            research_obj["hybrid"] = blob
        for key, value in sidecars.items():
            item = dict(value) if isinstance(value, dict) else {"value": value}
            item["research_only"] = True
            research_obj[key] = item
    job = {
        "schema": SCHEMA,
        "job_id": _job_id(ident),
        "identity": ident,
        "input": input_obj if input_obj is not None else (existing or {}).get("input"),
        "outputs": outputs,
        "research": research_obj or None,
        "settlement": settlement if settlement is not None else (existing or {}).get("settlement"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return job


def validate_job(job: dict) -> list[str]:
    """返回错误列表；空列表 = 可交卷。"""
    errors = []
    if not isinstance(job, dict):
        return ["job must be an object"]
    ident = job.get("identity") or {}
    mid = normalize_match_id(ident.get("match_id") or job.get("match_id"))
    if not mid:
        errors.append("identity.match_id required (sporttery-<id>)")
    if job.get("schema") and job["schema"] != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if "combined" in job or "winner_track" in job:
        errors.append("do not merge tracks into a single winner")
    for item in job.get("outputs") or []:
        track = item.get("track")
        if track not in ("quant", "llm"):
            errors.append(f"unknown track: {track}")
            continue
        if track == "quant":
            pct = item.get("final_1x2_pct")
            if pct is not None and not _is_pct_triple(pct):
                errors.append("quant.final_1x2_pct must be [H,D,A]")
            if item.get("strength") is not None:
                errors.append("quant must not carry LLM strength")
            if item.get("evidence_gap") is True and item.get("action") == "bet":
                errors.append("quant evidence_gap=true cannot be action=bet")
        if track == "llm":
            strength = item.get("strength")
            if strength is not None:
                if not isinstance(strength, dict) or strength.get("type") != "vote_share":
                    errors.append("llm.strength must be {type: vote_share, value: 0..1}")
                else:
                    try:
                        value = float(strength.get("value"))
                    except (TypeError, ValueError):
                        errors.append("llm.strength.value must be a number")
                    else:
                        if not 0 <= value <= 1:
                            errors.append("llm.strength.value must be in 0..1")
            if "final_1x2_pct" in item and item["final_1x2_pct"] is not None:
                errors.append("llm must not emit final_1x2_pct")
            evs = item.get("evs")
            action = item.get("action")
            if evs and action != "bet":
                errors.append("llm.evs only allowed when action=bet")
    hybrid = ((job.get("research") or {}).get("hybrid")) if job.get("research") else None
    if hybrid:
        if hybrid.get("research_only") is not True:
            errors.append("research.hybrid must set research_only=true")
        pct = hybrid.get("final_1x2_pct")
        if pct is not None and not _is_pct_triple(pct):
            errors.append("research.hybrid.final_1x2_pct must be [H,D,A]")
    intl = ((job.get("research") or {}).get("intl_kelly")) if job.get("research") else None
    if intl:
        if intl.get("research_only") is not True:
            errors.append("research.intl_kelly must set research_only=true")
        cal = intl.get("calibration")
        if cal is not None and str(cal).upper() != "UNFITTED":
            errors.append("research.intl_kelly.calibration must be UNFITTED")
        if any(k in intl for k in _STAKE_KEYS):
            errors.append("research.intl_kelly must not carry stake fields")
    return errors


def jobs_root(store: Path | None = None) -> Path:
    """jobs 与 backtest 并列，都在 FUSION_DATA_ROOT 下。"""
    if store is None:
        from runtime_paths import data_root
        return data_root() / "jobs"
    store = Path(store)
    return store.parent / "jobs" if store.name == "backtest" else store / "jobs"


def job_path(root: Path, identity: dict) -> Path:
    mid = normalize_match_id(identity.get("match_id"))
    if not mid:
        raise ValueError("cannot write job without match_id")
    day = identity.get("sales_day") or _date_from_kickoff(identity.get("kickoff")) or "unknown"
    return Path(root) / str(day) / f"{mid}.json"


def upsert_job(
    root: Path,
    identity: dict,
    *,
    input_obj: dict | None = None,
    quant: dict | None = None,
    llm: dict | None = None,
    research: dict | None = None,
    settlement: dict | None = None,
) -> Path:
    path = job_path(root, identity)
    existing = None
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = None
    job = assemble_job(
        identity=identity,
        input_obj=input_obj,
        quant=quant,
        llm=llm,
        research=research,
        settlement=settlement,
        existing=existing,
    )
    errors = validate_job(job)
    if errors:
        raise ValueError("invalid job: " + "; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def load_job(root: Path, match_id, sales_day: str | None = None) -> dict | None:
    mid = normalize_match_id(match_id)
    if not mid:
        return None
    if sales_day:
        path = Path(root) / sales_day / f"{mid}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None
    matches = list(Path(root).glob(f"*/{mid}.json"))
    if not matches:
        return None
    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return json.loads(matches[0].read_text(encoding="utf-8"))


def quant_from_fusion_output(out: dict, *, prediction_id: str | None = None) -> dict:
    forecast = out.get("forecast") or {}
    core = out.get("core_output") or out
    decision = out.get("fusion_decision") or {}
    gate = out.get("recommendation_gate") or {}
    pct = forecast.get("final_1x2_pct") or out.get("final_1x2_pct")
    banker = gate.get("banker_allowed")
    action = decision.get("action")
    if action is None:
        action = "skip" if banker is False else None
    ttg = core.get("ttg_score_consistency") or {}
    hafu = core.get("hafu_model") or {}
    derived_status = core.get("derived_market_status") or {}
    market_dependency = (
        out.get("market_dependency_pct")
        if out.get("market_dependency_pct") is not None
        else gate.get("market_dependency_pct")
    )
    conditioned_meta = {
        "probability_source": "market_conditioned_model",
        "independent_from_same_pool": False,
        "market_dependency_pct": market_dependency,
    }
    market_forecasts = {
        "CRS": {
            "top_scores": forecast.get("top_scores") or core.get("top_scores") or [],
            "calibration_status": derived_status.get("top_scores"),
            **conditioned_meta,
        },
        "TTG": {
            "model_prob_pct": ttg.get("model_prob_pct"),
            "market_prob_pct": ttg.get("market_prob_pct"),
            "calibration_status": derived_status.get("ttg") or derived_status.get("ou_2_5"),
            **conditioned_meta,
        },
        "HAFU": {
            "model_prob_pct": hafu.get("prob_pct"),
            "calibration_status": hafu.get("calibration_status") or derived_status.get("hafu_half_time"),
            **conditioned_meta,
        },
    }
    evidence_audit = out.get("evidence_audit") or core.get("evidence_audit") or {}
    return {
        "track": "quant",
        "prediction_id": prediction_id or out.get("prediction_id"),
        "model_version": (out.get("build_identity") or {}).get("model_version") or out.get("model_version"),
        "final_1x2_pct": pct,
        "primary_outcome": decision.get("primary_outcome"),
        "status": decision.get("status") or out.get("fusion_status"),
        "action": action,
        "market_dependency_pct": market_dependency,
        "mode": out.get("mode"),
        "market_forecasts": market_forecasts,
        "evidence_audit": evidence_audit,
        "evidence_gap": bool(evidence_audit.get("evidence_gap", False)),
        "evidence_gap_reasons": list(evidence_audit.get("evidence_gap_reasons") or []),
        "market_source_policy": {
            "HAD": "Sporttery official odds",
            "TTG": "Sporttery official odds",
            "HAFU": "Sporttery official odds",
            "CRS": "Sporttery official odds",
            "international_odds": "research_only",
        },
    }


def hybrid_from_fusion_output(out: dict, *, prior: dict | None = None, skip_reason: str | None = None) -> dict:
    forecast = (out or {}).get("forecast") or {}
    candidate = ((out or {}).get("research_candidate") or {}).get("lambda_prior") if out else None
    return {
        "research_only": True,
        "status": (out or {}).get("fusion_status") or skip_reason or "skipped",
        "mode": (out or {}).get("mode"),
        "final_1x2_pct": forecast.get("final_1x2_pct") or (out or {}).get("final_1x2_pct"),
        "model_1x2_pct": forecast.get("model_1x2_pct") or (out or {}).get("model_1x2_pct"),
        "market_1x2_pct": forecast.get("market_prob_pct") or (out or {}).get("market_prob_pct"),
        "market_dependency_pct": (out or {}).get("market_dependency_pct"),
        "lambda_prior": prior or candidate,
        "skip_reason": skip_reason,
    }


def _as_direction_code(value):
    if value is None:
        return None
    if isinstance(value, dict):
        pick = value.get("single_preference") or value.get("pick") or value.get("direction")
        return _as_direction_code(pick)
    text = str(value).strip()
    if text in DIR_TO_CODE:
        return DIR_TO_CODE[text]
    if text in CODE_TO_DIR:
        return text
    for token, code in (("主胜", "H"), ("平局", "D"), ("客胜", "A"),
                        ("(H)", "H"), ("(D)", "D"), ("(A)", "A")):
        if token in text:
            return code
    return text or None


def llm_from_parsed(row: dict) -> dict:
    gate = row.get("risk_gate") or {}
    strength = row.get("strength")
    if strength is None:
        strength = gate.get("strength")
    if isinstance(strength, dict) and strength.get("type") == "vote_share":
        packed = strength
    elif isinstance(strength, dict):
        packed = None
    elif strength is None:
        packed = None
    else:
        value = float(strength)
        if value > 1:
            value = value / 100.0
        packed = {"type": "vote_share", "value": round(value, 4)}
    action = row.get("ev_action") or row.get("action") or gate.get("action")
    if row.get("sp_skip") and not action:
        action = "skip"
    evs = row.get("evs") if action == "bet" else None
    direction = _as_direction_code(row.get("dir") or row.get("direction"))
    alt = _as_direction_code(row.get("alt") or row.get("alt_direction"))
    gap = row.get("evidence_gap")
    if gap is None:
        gap = "缺口" in str(gate.get("reason") or "")
    direction_obj = row.get("direction") if isinstance(row.get("direction"), dict) else {}
    scores = row.get("score_picks") or []
    return {
        "track": "llm",
        "direction": direction,
        "alt_direction": alt,
        "strength": packed,
        "action": action,
        "reason": row.get("ev_reason") or row.get("reason") or gate.get("reason"),
        "evidence_gap": bool(gap),
        "single_pick": row.get("sp") or row.get("single_pick") or direction_obj.get("single_preference"),
        "score": row.get("score") or row.get("top_score_pref") or (scores[0] if scores else None),
        "evs": evs,
    }


def _normalize_quant(item: dict) -> dict:
    out = dict(item)
    out["track"] = "quant"
    return out


def _normalize_llm(item: dict) -> dict:
    if item.get("track") == "llm" and isinstance(item.get("strength"), dict):
        return dict(item)
    return llm_from_parsed(item)


def _upsert_track(outputs: list, item: dict) -> list:
    track = item.get("track")
    kept = [row for row in outputs if row.get("track") != track]
    kept.append(item)
    return kept


def _job_id(identity: dict) -> str | None:
    mid = normalize_match_id(identity.get("match_id"))
    if not mid:
        return None
    as_of = identity.get("kickoff") or identity.get("sales_day") or ""
    return f"{mid}@{as_of}" if as_of else mid


def _is_pct_triple(value) -> bool:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return False
    try:
        return all(isinstance(x, (int, float)) for x in value)
    except TypeError:
        return False


def _date_from_kickoff(kickoff) -> str | None:
    if not kickoff:
        return None
    text = str(kickoff)
    return text[:10] if len(text) >= 10 and text[4] == "-" else None


def _cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="组装或读取统一工单")
    ap.add_argument("--input", help="融合裸 dict 或体彩 raw（单场）")
    ap.add_argument("--quant", help="融合输出 JSON")
    ap.add_argument("--llm", help="LLM parsed 单场或 {..} 列表里的一场")
    ap.add_argument("--match-id", help="只读：按 ID 取已落盘工单")
    ap.add_argument("--sales-day")
    ap.add_argument("--store", help="backtest 目录或 jobs 父目录")
    ap.add_argument("--out", help="写出路径；默认写入共享 jobs/")
    args = ap.parse_args(argv)

    root = jobs_root(Path(args.store) if args.store else None)
    if args.match_id and not (args.input or args.quant or args.llm):
        job = load_job(root, args.match_id, args.sales_day)
        if not job:
            raise SystemExit(f"job not found: {args.match_id}")
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 0

    inp = json.loads(Path(args.input).read_text(encoding="utf-8")) if args.input else {}
    if isinstance(inp, dict) and isinstance(inp.get("matches"), list):
        raise SystemExit("job 一次只收单场；批量 raw 请先拆成裸 dict")
    quant_out = json.loads(Path(args.quant).read_text(encoding="utf-8")) if args.quant else None
    llm_row = None
    if args.llm:
        raw_llm = json.loads(Path(args.llm).read_text(encoding="utf-8"))
        if isinstance(raw_llm, list):
            target = normalize_match_id(args.match_id) or normalize_match_id((inp.get("sporttery_meta") or {}).get("match_id") or inp.get("match_id"))
            llm_row = next((r for r in raw_llm if normalize_match_id(r.get("match_id")) == target), None)
            if llm_row is None and len(raw_llm) == 1:
                llm_row = raw_llm[0]
            if llm_row is None:
                raise SystemExit("llm 列表里找不到这场的 match_id")
        else:
            llm_row = raw_llm
    ident = identity_from(inp, quant_out or {})
    if args.sales_day:
        ident["sales_day"] = args.sales_day
    quant_item = quant_from_fusion_output(quant_out) if quant_out else None
    job = assemble_job(identity=ident, input_obj=inp or None, quant=quant_item, llm=llm_row)
    errors = validate_job(job)
    if errors:
        raise SystemExit("invalid job: " + "; ".join(errors))
    if args.out:
        Path(args.out).write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(args.out)
    else:
        path = upsert_job(root, ident, input_obj=inp or None, quant=quant_item, llm=llm_row)
        print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
