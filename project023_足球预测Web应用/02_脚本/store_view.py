#!/usr/bin/env python3
"""只读融合库：看板用。不写 registry / predictions。"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[1]
FUSION_SCRIPTS = (
    VAULT / "project018_技能工作区整合" / "02_脚本" / "skill" / "football-quant-fusion" / "scripts"
)
CORE = (
    VAULT / "project018_技能工作区整合" / "02_脚本" / "core" / "zu-yu-dashi-3" / "scripts"
)
if str(FUSION_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FUSION_SCRIPTS))
from runtime_paths import data_root  # noqa: E402

CST = timezone(timedelta(hours=8))
LATE_TARGET = 200
# 临近开球体会把「已开售」改成「暂停销售」，看板仍应列出这些场。
SALE_WINDOW = ("已开售", "暂停销售")
LLM_DATA = Path(os.environ.get("FOOTBALL_LLM_ROOT") or (
    VAULT / "project018_技能工作区整合" / "02_脚本" / "llm" / "football-llm-predictor"
)) / "data"
C_LLM_DATA = Path(r"C:\Users\Administrator\football-llm-predictor\data")
P021_DAILY = (
    VAULT / "project021_五大联赛APIFootball训练" / "05_交付" / "每日开售预测"
)
_EVIDENCE_ID_RE = re.compile(
    r"(?:sporttery-|matchId\s*[=:（(\s]+|match_id\s*[=:\s]+)(\d{7})",
    re.I,
)
_EVIDENCE_NAME_RE = re.compile(r"^evidence_\d{3}_(.+)_(.+)\.md$", re.I)
STATUS_ZH = {
    "UNAVAILABLE": "暂无数据",
    "VALID": "有效",
    "NO_API_ID": "无供应商场次号",
    "TOO_EARLY": "未进入动态采集窗口",
    "POST_KICKOFF": "已开球",
    "MISSING": "缺失",
    "MARKET_BASELINE": "市场基线",
}


def status_zh(code):
    if not code:
        return None
    return STATUS_ZH.get(str(code), str(code))


def store_root() -> Path:
    return data_root()


def parse_dt(value):
    if value in (None, ""):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        if "T" in s:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CST)
    return dt.astimezone(timezone.utc)


def sporttery_id(value) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.lower().startswith("sporttery-"):
        rest = text.split("-", 1)[1]
        return f"sporttery-{rest}" if rest else None
    if text.isdigit():
        return f"sporttery-{text}"
    return None


def remap_pred_path(raw: str, root: Path | None = None) -> Path:
    root = root or store_root()
    text = str(raw).replace("\\", "/")
    marker = "football-quant-fusion/"
    if marker in text:
        tail = text.split(marker, 1)[1]
        return root / Path(tail)
    return Path(raw)


def list_had(row: dict) -> list[float] | None:
    try:
        odds = [float(row.get("h")), float(row.get("d")), float(row.get("a"))]
    except (TypeError, ValueError):
        return None
    if min(odds) > 1:
        return odds
    return None


def classify(has_odds: bool, not_kicked: bool, predicted: bool, finished: bool) -> str:
    if finished:
        return "finished"
    if not not_kicked:
        return "kicked"
    if not has_odds:
        return "no_odds"
    if predicted:
        return "predicted"
    return "missing_pred"


def extract_quant(payload: dict) -> dict:
    """正式登记在 output，流水线副本在 forecast。两处都认。"""
    blobs = [
        payload.get("output") if isinstance(payload.get("output"), dict) else None,
        payload.get("forecast") if isinstance(payload.get("forecast"), dict) else None,
        (payload.get("core_output") or {}).get("forecast") if isinstance(payload.get("core_output"), dict) else None,
        payload.get("core_output") if isinstance(payload.get("core_output"), dict) else None,
        payload,
    ]
    pct = tops = gate = None
    for blob in blobs:
        if not blob:
            continue
        if pct is None and isinstance(blob.get("final_1x2_pct"), list) and len(blob["final_1x2_pct"]) >= 3:
            pct = [float(x) for x in blob["final_1x2_pct"][:3]]
        if tops is None and isinstance(blob.get("top_scores"), list):
            labs = []
            for item in blob["top_scores"][:3]:
                if isinstance(item, dict) and item.get("score"):
                    labs.append(str(item["score"]))
            if labs:
                tops = labs
        if gate is None:
            rg = blob.get("recommendation_gate")
            if isinstance(rg, dict) and rg.get("status"):
                gate = rg["status"]
    ou = hafu = None
    for blob in blobs:
        if not blob:
            continue
        raw_ou = blob.get("ou_2_5") if isinstance(blob.get("ou_2_5"), dict) else None
        if ou is None and raw_ou:
            ou = {"under_pct": raw_ou.get("under_pct"), "over_pct": raw_ou.get("over_pct")}
        raw_hafu = blob.get("hafu_model") if isinstance(blob.get("hafu_model"), dict) else None
        if hafu is None and raw_hafu:
            labels = raw_hafu.get("state_labels") or []
            probs = raw_hafu.get("prob_pct") or []
            if labels and probs:
                i = max(range(len(probs)), key=lambda k: float(probs[k] or 0))
                hafu = {"top": labels[i], "pct": probs[i]}
    return {"final_1x2_pct": pct, "top_scores": tops or [], "gate": gate, "ou_2_5": ou, "hafu": hafu}


def extract_match_meta(payload: dict) -> dict:
    match = payload.get("match") if isinstance(payload.get("match"), dict) else {}
    meta = match.get("sporttery_meta") if isinstance(match.get("sporttery_meta"), dict) else {}
    home = match.get("home")
    away = match.get("away")
    if isinstance(home, dict):
        home = home.get("name") or home.get("short")
    if isinstance(away, dict):
        away = away.get("name") or away.get("short")
    kick = parse_dt(match.get("kickoff") or meta.get("kickoff"))
    return {
        "home": home or meta.get("home_full"),
        "away": away or meta.get("away_full"),
        "league": match.get("competition") or meta.get("league"),
        "match_num": meta.get("match_num"),
        "kickoff": kick.astimezone(CST).isoformat() if kick else None,
        "snapshot": payload.get("snapshot_type"),
    }


def had_direction(pct) -> str | None:
    if not isinstance(pct, (list, tuple)) or len(pct) < 3:
        return None
    try:
        vals = [float(x) for x in pct[:3]]
    except (TypeError, ValueError):
        return None
    return ("主胜", "平局", "客胜")[max(range(3), key=lambda i: vals[i])]


def score_direction(score) -> str | None:
    if isinstance(score, dict):
        home, away = score.get("home"), score.get("away")
    elif isinstance(score, (list, tuple)) and len(score) >= 2:
        home, away = score[0], score[1]
    else:
        return None
    if not isinstance(home, int) or not isinstance(away, int):
        return None
    if home > away:
        return "主胜"
    if home < away:
        return "客胜"
    return "平局"


def load_registry_quant(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    reg = root / "backtest" / "registry.jsonl"
    latest: dict[str, dict] = {}
    if not reg.exists():
        return latest
    for line in reg.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        mid = sporttery_id(rec.get("match_id"))
        if not mid:
            continue
        prev = latest.get(mid)
        if prev is None or str(rec.get("created_at") or "") >= str(prev.get("created_at") or ""):
            latest[mid] = rec
    out = {}
    for mid, rec in latest.items():
        path = remap_pred_path(rec.get("path") or "", root)
        payload = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
        extracted = extract_quant(payload)
        meta = extract_match_meta(payload)
        bi = payload.get("build_identity") or payload.get("model") or {}
        out[mid] = {
            "predicted": True,
            "mode": payload.get("mode") or (payload.get("output") or {}).get("mode"),
            "gate": extracted["gate"],
            "final_1x2_pct": extracted["final_1x2_pct"],
            "top_scores": extracted["top_scores"],
            "ou_2_5": extracted.get("ou_2_5"),
            "hafu": extracted.get("hafu"),
            "direction": had_direction(extracted["final_1x2_pct"]),
            "prediction_as_of": payload.get("prediction_as_of") or rec.get("created_at"),
            "prediction_id": rec.get("prediction_id"),
            "path": str(path),
            "home": meta["home"],
            "away": meta["away"],
            "league": meta["league"],
            "match_num": meta["match_num"],
            "kickoff": meta["kickoff"],
            "snapshot": meta["snapshot"],
            "hashes": {
                "engine_bundle_sha256": bi.get("engine_bundle_sha256"),
                "prediction_code_sha256": bi.get("prediction_code_sha256"),
                "config_sha256": bi.get("config_sha256"),
            },
        }
    return out


def load_jobs_llm(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    jobs = root / "jobs"
    out: dict[str, dict] = {}
    if not jobs.exists():
        return out
    for path in jobs.rglob("sporttery-*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = sporttery_id((job.get("identity") or {}).get("match_id") or path.stem)
        if not mid:
            continue
        llm = next((o for o in (job.get("outputs") or []) if o.get("track") == "llm"), None)
        if not llm:
            continue
        strength = llm.get("strength") if isinstance(llm.get("strength"), dict) else None
        scores = _llm_scores(llm)
        out[mid] = {
            "direction": llm.get("direction") or llm.get("dir"),
            "alt_direction": llm.get("alt_direction") or llm.get("alt"),
            "top_scores": scores,
            "probs_1x2": _llm_probs(llm),
            "vote_share": None if not strength else strength.get("value"),
            "action": llm.get("action"),
            "note": "证据方向，不是概率",
            "source": "job",
        }
    return out


def _llm_scores(blob: dict) -> list[str]:
    raw = blob.get("top_scores")
    out = []
    if isinstance(raw, list):
        for item in raw[:3]:
            if isinstance(item, dict) and item.get("score"):
                out.append(str(item["score"]))
            elif item not in (None, "", "分散", "-"):
                out.append(str(item))
    if not out:
        one = blob.get("score") or blob.get("top_score_pref")
        if one not in (None, "", "分散", "-"):
            out = [str(one)]
    return out


def _llm_probs(blob: dict) -> list[float] | None:
    raw = blob.get("probs_1x2")
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    try:
        return [float(x) for x in raw[:3]]
    except (TypeError, ValueError):
        return None


def _read_llm_pred_blob(rec: dict) -> dict | None:
    mid = sporttery_id(rec.get("match_id"))
    direction = rec.get("direction") or rec.get("dir")
    if not mid or not direction:
        return None
    return {
        "direction": direction,
        "alt_direction": rec.get("alt_direction") or rec.get("alt"),
        "top_scores": _llm_scores(rec),
        "probs_1x2": _llm_probs(rec),
        "note": "证据方向，不是概率",
        "source": "pred_file",
    }


def load_llm_pred_files(root: Path | None = None, include_shared: bool = True) -> dict[str, dict]:
    """读独立 LLM 预测 JSON：胜平负 + 比分。不与量化合成。"""
    folders: list[Path] = []
    base = root or store_root()
    folders.append(base / "llm_preds")
    fwd = base / "forward"
    if fwd.is_dir():
        folders.extend(sorted(p for p in fwd.iterdir() if p.is_dir()))
    if include_shared:
        folders.extend([LLM_DATA, C_LLM_DATA])
    out: dict[str, dict] = {}
    seen: set[Path] = set()
    for folder in folders:
        if not folder.is_dir():
            continue
        key = folder.resolve()
        if key in seen:
            continue
        seen.add(key)
        for path in list(folder.glob("predictions_*.json")) + list(folder.glob("llm_parsed.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            rows = []
            if isinstance(data, dict) and data.get("match_id"):
                rows = [data]
            elif isinstance(data, dict) and isinstance(data.get("rows"), list):
                rows = data["rows"]
            for rec in rows:
                if not isinstance(rec, dict):
                    continue
                got = _read_llm_pred_blob(rec)
                if got:
                    out[sporttery_id(rec.get("match_id")) or ""] = got
    out.pop("", None)
    return out


def iter_evidence_dirs(base: Path) -> list[Path]:
    if not base.is_dir():
        return []
    dirs = [p for p in sorted(base.glob("evidence_*")) if p.is_dir()]
    extra = base / "llm_evidence"
    if extra.is_dir():
        dirs.append(extra)
    return dirs


def iter_forward_evidence_dirs(base: Path) -> list[Path]:
    fwd = base / "forward"
    if not fwd.is_dir():
        return []
    return [day / "llm_evidence" for day in sorted(fwd.iterdir()) if (day / "llm_evidence").is_dir()]


def extra_evidence_dirs() -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for base in (LLM_DATA, C_LLM_DATA):
        for path in iter_evidence_dirs(base):
            key = path.resolve()
            if key not in seen:
                seen.add(key)
                dirs.append(path)
    if P021_DAILY.is_dir():
        for day in P021_DAILY.iterdir():
            ev = day / "llm_evidence"
            if ev.is_dir():
                key = ev.resolve()
                if key not in seen:
                    seen.add(key)
                    dirs.append(ev)
    for path in iter_forward_evidence_dirs(store_root()):
        key = path.resolve()
        if key not in seen:
            seen.add(key)
            dirs.append(path)
    return dirs


def parse_evidence_match_id(text: str) -> str | None:
    match = _EVIDENCE_ID_RE.search(text or "")
    if not match:
        return None
    return sporttery_id(match.group(1))


def load_llm_evidence_files(root: Path | None = None, include_shared: bool = True) -> dict[str, dict]:
    """读磁盘上的 evidence_*.md；有文件就算已采集。"""
    root = root or store_root()
    dirs = list(iter_evidence_dirs(root))
    dirs.extend(iter_forward_evidence_dirs(root))
    if include_shared:
        dirs.extend(extra_evidence_dirs())
    by_id: dict[str, dict] = {}
    newest: dict[str, float] = {}
    for folder in dirs:
        for path in folder.glob("evidence_*.md"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            mid = parse_evidence_match_id(text)
            if not mid:
                continue
            mtime = path.stat().st_mtime
            if mtime < newest.get(mid, -1):
                continue
            newest[mid] = mtime
            names = _EVIDENCE_NAME_RE.match(path.name)
            by_id[mid] = {
                "direction": None,
                "note": "已采集",
                "source": "file",
                "evidence_file": str(path),
                "home": names.group(1) if names else None,
                "away": names.group(2) if names else None,
            }
    return by_id


def _section_body(text: str, heading: str) -> str:
    parts = re.split(r"(?=^## )", text or "", flags=re.M)
    for part in parts:
        if part.startswith(heading) or part.startswith("## " + heading.lstrip("# ").split("/")[0]):
            return part
    return ""


def _has_injury_fact(facts: str) -> bool:
    """有球员级伤停表述。『无伤病/无伤停』只说明接口没字段，不算事实。"""
    cleaned = facts or ""
    for neg in ("无伤病", "无伤停", "没有伤停", "没有伤病"):
        cleaned = cleaned.replace(neg, "")
    return any(k in cleaned for k in ("伤", "停赛", "Out", "不可用", "缺阵"))


def classify_evidence(text: str) -> dict:
    """近5场 / 首发 / 伤停三盏灯。只读证据正文，不编造。"""
    body = text or ""
    sec1 = _section_body(body, "## 1.")
    sec3 = _section_body(body, "## 3.")
    form_src = sec3 or ""
    voted_form = any(k in form_src for k in ("二十源整合", "20源投票", "得票最高", "投票近5"))
    if voted_form:
        form = "previous" if any(k in form_src for k in ("上季正式", "对其他对手")) else "current"
        form_reason = "近况节按 20 源投票写入得票最高的近5场，不再等官方联赛页。"
    elif any(k in form_src for k in ("对其他对手", "上季正式", "不得当「无近5场」")):
        form = "previous"
        form_reason = "近况节写了揭幕战/对其他对手的上季或最近正式近5场。"
    elif any(k in form_src for k in ("战绩不适用", "未抓取双方近 5 场", "完整近5场", "近5场完整", "未从官方联赛页")):
        form = "missing"
        form_reason = "近况节标明近5场未逐场核验或未写入，不是「球队没有比赛」。"
    elif "近5场" in form_src or "最近5场" in form_src:
        form = "current"
        form_reason = "近况节写了近5场正式赛果。"
    else:
        form = "missing"
        form_reason = "近况节没有近5场事实行，灯不表示检索过全网。"

    lineup_src = sec1 or ""
    lineup_facts = "\n".join((sec1 or "").splitlines()[1:])
    voted_xi = any(k in lineup_src for k in ("二十源整合", "20源投票", "得票最高"))
    has_policy = voted_xi or any(k in lineup_src for k in ("两源一致", "两个独立媒体", "两家独立媒体", "两源首发"))
    has_conflict = (not voted_xi) and any(k in lineup_src for k in ("对不上", "2 对 2", "2对2", "位置冲突"))
    has_xi = any(k in lineup_facts for k in ("预计首发", "预期十一", "4-2-3-1", "4-3-3", "4-4-2", "4-5-1", "十一人"))
    has_injury_fact = _has_injury_fact(lineup_facts)
    official_gap = "官方首发" in lineup_src or "首发未公布" in lineup_src
    if has_policy and has_conflict:
        lineup = "conflict"
        lineup_reason = "已按两源交叉，仅部分位置两家对不上；不是整维没有首发。"
    elif voted_xi:
        lineup = "two_source"
        lineup_reason = "20 源投票得票最高的名单已当可用首发，不再等官方。"
    elif has_policy:
        lineup = "two_source"
        lineup_reason = "两个独立媒体对同一位置一致，已当可用首发。"
    elif has_xi:
        lineup = "not_written"
        lineup_reason = "写了预计阵容，但未做两家独立媒体交叉，不能当可用首发。"
    elif official_gap or has_injury_fact:
        lineup = "not_written"
        lineup_reason = "第1节只写了伤停或「官方首发未公布」，没有十一人名单。不是检索结论为「找不到首发」。"
    else:
        lineup = "not_collected"
        lineup_reason = "证据第1节没有首发采集记录。"

    hosts = []
    for url in re.findall(r"source\((https?://[^)]+)\)", sec1):
        host = url.split("/")[2].lower().removeprefix("www.")
        if host and "sporttery" not in host:
            hosts.append(host)
    uniq = list(dict.fromkeys(hosts))
    voted_injury = any(k in lineup_src for k in ("二十源整合伤停", "20源投票伤停", "投票伤停"))
    if voted_injury or (len(uniq) >= 2 and has_injury_fact):
        injury = "dual"
        injury_reason = (
            "20 源投票得票最高的伤停已当可用伤停，不再等官方。"
            if voted_injury
            else "伤停来自至少两家媒体：" + "、".join(uniq[:4]) + "。"
        )
    elif uniq and has_injury_fact:
        injury = "single"
        injury_reason = "伤停只有一家媒体：" + uniq[0] + "。"
    elif "无伤病" in lineup_src or "无伤停" in lineup_src:
        injury = "none"
        injury_reason = "证据写明接口/页面无伤停字段，不是「确认全员健康」。"
    else:
        injury = "none"
        injury_reason = "第1节没有可引用的伤停事实行。"

    return {
        "form": form,
        "lineup": lineup,
        "injury": injury,
        "form_zh": {"previous": "上季正式", "current": "本季近5", "missing": "近5未写"}[form],
        "lineup_zh": {
            "two_source": "两源首发",
            "conflict": "首发冲突",
            "not_written": "未写首发",
            "not_collected": "未采首发",
        }[lineup],
        "injury_zh": {"dual": "伤停双源", "single": "伤停单源", "none": "伤停未写"}[injury],
        "form_reason": form_reason,
        "lineup_reason": lineup_reason,
        "injury_reason": injury_reason,
    }


def lights_for_file(path) -> dict | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return classify_evidence(p.read_text(encoding="utf-8"))
    except OSError:
        return None


def match_card(match_id: str, root: Path | None = None) -> dict | None:
    use_shared = root is None
    root = root or store_root()
    mid = sporttery_id(match_id)
    if not mid:
        return None
    quant = load_registry_quant(root).get(mid)
    res = load_results(root).get(mid)
    llm = merge_llm(
        load_jobs_llm(root).get(mid),
        load_llm_evidence_files(root, include_shared=use_shared).get(mid),
        load_llm_pred_files(root, include_shared=use_shared).get(mid),
    )
    ev = (llm or {}).get("evidence_file")
    text = ""
    if ev and Path(ev).is_file():
        text = Path(ev).read_text(encoding="utf-8")
    lights = classify_evidence(text) if text else None
    facts = []
    for line in text.splitlines():
        if line.lstrip().startswith("-") and "source(" in line.lower():
            facts.append(line.lstrip("- ").strip())
    return {
        "match_id": mid,
        "quant": quant,
        "result": res,
        "llm": llm,
        "lights": lights,
        "evidence_file": ev,
        "evidence_facts": facts[:24],
        "note": "量化与 LLM 分列，不合成。",
    }


def merge_llm(job: dict | None, ev: dict | None, pred: dict | None = None) -> dict | None:
    if not job and not ev and not pred:
        return None
    out = {}
    if ev:
        out.update({k: v for k, v in ev.items() if k not in ("home", "away")})
    for blob in (pred, job):
        if not blob:
            continue
        for key, value in blob.items():
            if value not in (None, [], ""):
                out[key] = value
        out.setdefault("note", "证据方向，不是概率")
    return out


def load_results(root: Path | None = None) -> dict[str, dict]:
    root = root or store_root()
    folder = root / "backtest" / "results"
    out = {}
    if not folder.exists():
        return out
    for path in folder.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        mid = sporttery_id(rec.get("match_id") or path.stem)
        if not mid:
            continue
        sc = rec.get("score_90") or {}
        score = None
        if isinstance(sc, dict) and isinstance(sc.get("home"), int) and isinstance(sc.get("away"), int):
            score = [sc.get("home"), sc.get("away")]
        out[mid] = {
            "score_90": score,
            "status": rec.get("status"),
            "direction": score_direction(sc),
            "settlement_scope": rec.get("settlement_scope"),
        }
    return out


def load_late_info(root: Path | None = None) -> tuple[dict[str, dict], dict]:
    root = root or store_root()
    path = root / "late_info" / "events.jsonl"
    by: dict[str, dict] = {}
    n_inj = n_xi = n_late = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            mid = sporttery_id(rec.get("match_id"))
            if not mid:
                continue
            slot = by.setdefault(mid, {"injury": None, "lineup": None, "late": False})
            kind = rec.get("kind")
            if kind in ("injury", "lineup"):
                slot[kind] = rec.get("status")
                slot[f"{kind}_zh"] = status_zh(rec.get("status"))
            if (rec.get("gate") or {}).get("late"):
                slot["late"] = True
                n_late += 1
            if kind == "injury" and rec.get("status") == "VALID":
                n_inj += 1
            if kind == "lineup" and rec.get("status") == "VALID":
                n_xi += 1
    summary = {
        "events_file": str(path),
        "injury_valid": n_inj,
        "lineup_valid": n_xi,
        "late_events": n_late,
        "unique_matches": len(by),
        "toward_200": LATE_TARGET,
        "note": "研究库，不进生产 1X2",
    }
    return by, summary


_LIVE_CACHE: dict = {"rows": [], "at": None}


def _fetch_live_selling_impl(now=None) -> list[dict]:
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    import fetch_sporttery_full as sporttery

    now = now or datetime.now(CST)
    seen: dict[int, dict] = {}
    dates = [(now + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(0, 4)]
    for method in ("all", "concern"):
        for day in dates:
            try:
                data = sporttery.fetch_pages({"method": method, "matchDate": day, "isFix": 0})
            except Exception:
                continue
            for row in sporttery.parse_list(data):
                mid = row.get("matchId")
                if mid is not None:
                    seen[int(mid)] = row
    return list(seen.values())


def fetch_live_selling(now=None, timeout_s: float = 12.0) -> list[dict]:
    """拉体彩在售。超时或失败回退上一份，避免刷新按钮一直转圈。"""
    box: dict = {"rows": None, "err": None}

    def work():
        try:
            box["rows"] = _fetch_live_selling_impl(now)
        except Exception as exc:
            box["err"] = exc

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout_s)
    if not t.is_alive() and box["rows"] is not None:
        _LIVE_CACHE["rows"] = box["rows"]
        _LIVE_CACHE["at"] = datetime.now(CST)
        return box["rows"]
    return list(_LIVE_CACHE.get("rows") or [])


def board(now=None, live_rows: list[dict] | None = None, root: Path | None = None) -> dict:
    use_shared_evidence = root is None
    root = root or store_root()
    now = now or datetime.now(CST)
    now_utc = now.astimezone(timezone.utc)
    live = live_rows if live_rows is not None else fetch_live_selling(now)
    quant = load_registry_quant(root)
    llm_jobs = load_jobs_llm(root)
    llm_files = load_llm_evidence_files(root, include_shared=use_shared_evidence)
    llm_preds = load_llm_pred_files(root, include_shared=use_shared_evidence)
    files_by_name = {
        (rec.get("home"), rec.get("away")): rec
        for rec in llm_files.values()
        if rec.get("home") and rec.get("away")
    }
    results = load_results(root)
    late_by, late_sum = load_late_info(root)
    rows = []
    for raw in live:
        mid = sporttery_id(raw.get("matchId"))
        kick = parse_dt(f"{raw.get('matchDate') or ''} {raw.get('matchTime') or ''}".strip())
        odds = list_had(raw)
        st = raw.get("matchStatusName") or ""
        finished = "完成" in st or mid in results
        not_kicked = bool(kick and kick > now_utc) and not finished
        q = quant.get(mid)
        bucket = classify(bool(odds), not_kicked, bool(q), finished)
        home = raw.get("homeTeamAbbName")
        away = raw.get("awayTeamAbbName")
        ev = llm_files.get(mid) or files_by_name.get((home, away))
        rows.append({
            "match_id": mid,
            "match_num": raw.get("matchNumStr"),
            "league": raw.get("leagueAbbName"),
            "home": home,
            "away": away,
            "kickoff": kick.astimezone(CST).isoformat() if kick else None,
            "status_name": st,
            "has_odds": bool(odds),
            "odds": odds,
            "not_kicked": not_kicked,
            "quant": q,
            "llm": merge_llm(llm_jobs.get(mid), ev, llm_preds.get(mid)),
            "lights": lights_for_file((ev or {}).get("evidence_file")),
            "late_info": late_by.get(mid),
            "result": results.get(mid),
            "bucket": bucket,
        })
    rows.sort(key=lambda r: (r.get("kickoff") or "", r.get("match_num") or ""))
    selling = [r for r in rows if r["status_name"] in SALE_WINDOW]
    future = [r for r in selling if r["not_kicked"]]
    with_odds = [r for r in future if r["has_odds"]]
    missing = [r for r in with_odds if r["bucket"] == "missing_pred"]
    predicted = [r for r in with_odds if r["bucket"] == "predicted"]
    return {
        "as_of": now.isoformat(),
        "store": str(root),
        "read_only_store": True,
        "manual_backtest": True,
        "summary": {
            "listed": len(rows),
            "on_sale": len(selling),
            "future": len(future),
            "has_odds": len(with_odds),
            "predicted": len(predicted),
            "missing_pred": len(missing),
            "no_odds": sum(1 for r in future if not r["has_odds"]),
            "llm_collected": sum(1 for r in selling if r.get("llm")),
            "llm_predicted": sum(1 for r in selling if (r.get("llm") or {}).get("direction")),
        },
        "matches": rows,
        "by_league": group_by_league(selling),
        "missing": [{"match_id": r["match_id"], "match_num": r["match_num"],
                     "home": r["home"], "away": r["away"], "kickoff": r["kickoff"],
                     "odds": r["odds"]} for r in missing],
        "late_info": late_sum,
        "note": "量化轨数字来自正式登记；LLM 另列胜平负与比分，不与量化合成。",
    }


def kickoff_day(iso_text) -> str:
    dt = parse_dt(iso_text)
    if not dt:
        return "未知"
    return dt.astimezone(CST).date().isoformat()


_DIR_WORDS = ("主胜", "平局", "客胜")


def parse_llm_pick(text) -> dict:
    """从 index_llm / 作业票里拆出单选方向和可选双选。"""
    raw = str(text or "")
    found = [word for word in _DIR_WORDS if word in raw]
    direction = found[0] if found else None
    alt = found[1] if len(found) > 1 else None
    return {"direction": direction, "alt_direction": alt}


def load_llm_indexes() -> dict[str, dict]:
    """读销售日 index_llm.json；只取有方向的登记，不与量化合成。"""
    out: dict[str, dict] = {}
    if not P021_DAILY.is_dir():
        return out
    for path in P021_DAILY.rglob("index_llm.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for rec in data.get("records") or []:
            mid = sporttery_id(rec.get("match_id"))
            if not mid:
                continue
            parsed = parse_llm_pick(rec.get("llm_pick_raw") or rec.get("llm_pick"))
            if not parsed["direction"]:
                continue
            out[mid] = {
                "direction": parsed["direction"],
                "alt_direction": parsed["alt_direction"],
                "note": rec.get("reason") or rec.get("llm_pick") or "证据方向，不是概率",
                "source": "index_llm",
                "caution": bool(rec.get("caution")),
            }
    return out


def history_rows(root: Path | None = None, include_shared: bool = True) -> list[dict]:
    root = root or store_root()
    recs = load_registry_quant(root)
    results = load_results(root)
    llm_jobs = load_jobs_llm(root)
    llm_files = load_llm_evidence_files(root, include_shared=include_shared)
    llm_preds = load_llm_pred_files(root, include_shared=include_shared)
    llm_idx = load_llm_indexes() if include_shared else {}
    rows = []
    for mid, rec in recs.items():
        res = results.get(mid)
        pred_dir = rec.get("direction")
        if not pred_dir or not rec.get("final_1x2_pct"):
            continue
        actual = (res or {}).get("direction")
        settled = bool(res and res.get("status") == "finished" and actual)
        hit = settled and pred_dir == actual
        llm = merge_llm(llm_jobs.get(mid), llm_files.get(mid), llm_preds.get(mid))
        if llm_idx.get(mid):
            extra = llm_idx[mid]
            llm = dict(llm or {})
            llm["direction"] = extra.get("direction") or llm.get("direction")
            if extra.get("alt_direction"):
                llm["alt_direction"] = extra["alt_direction"]
            llm["note"] = extra.get("note") or llm.get("note")
            llm["source"] = extra.get("source") or llm.get("source")
        llm_dir = (llm or {}).get("direction")
        llm_alt = (llm or {}).get("alt_direction")
        llm_scored = bool(settled and llm_dir in _DIR_WORDS)
        llm_hit = llm_scored and llm_dir == actual
        if llm_scored and llm_alt in _DIR_WORDS:
            llm_double_hit = actual in (llm_dir, llm_alt)
        else:
            llm_double_hit = llm_hit
        rows.append({
            "match_id": mid,
            "match_num": rec.get("match_num"),
            "league": rec.get("league"),
            "home": rec.get("home"),
            "away": rec.get("away"),
            "kickoff": rec.get("kickoff"),
            "day": kickoff_day(rec.get("kickoff")),
            "quant": {
                "mode": rec.get("mode"),
                "gate": rec.get("gate"),
                "final_1x2_pct": rec.get("final_1x2_pct"),
                "top_scores": rec.get("top_scores"),
                "direction": pred_dir,
                "snapshot": rec.get("snapshot"),
            },
            "llm": llm,
            "lights": lights_for_file((llm or {}).get("evidence_file")),
            "result": res,
            "settled": settled,
            "hit": hit,
            "llm_scored": llm_scored,
            "llm_hit": llm_hit,
            "llm_double_hit": llm_double_hit,
        })
    rows.sort(key=lambda r: (r.get("kickoff") or "", r.get("match_num") or "", r["match_id"]))
    return rows


def summarize_hits(rows: list[dict]) -> dict:
    """量化命中率与 LLM 命中率分列，不合成。"""
    settled = [r for r in rows if r.get("settled")]
    hits = sum(1 for r in settled if r.get("hit"))
    n_s = len(settled)
    rate = None if n_s == 0 else round(100.0 * hits / n_s, 1)
    llm_scored = [r for r in rows if r.get("llm_scored")]
    llm_hits = sum(1 for r in llm_scored if r.get("llm_hit"))
    llm_n = len(llm_scored)
    llm_rate = None if llm_n == 0 else round(100.0 * llm_hits / llm_n, 1)
    llm_double_hits = sum(1 for r in llm_scored if r.get("llm_double_hit"))
    llm_double_rate = None if llm_n == 0 else round(100.0 * llm_double_hits / llm_n, 1)
    return {
        "n": len(rows),
        "settled": n_s,
        "scored": n_s,
        "hit": hits,
        "miss": n_s - hits,
        "hit_rate": rate,
        "hit_rate_text": None if n_s == 0 else f"{hits}/{n_s}",
        "llm_n": llm_n,
        "llm_hit": llm_hits,
        "llm_miss": llm_n - llm_hits,
        "llm_hit_rate": llm_rate,
        "llm_hit_rate_text": None if llm_n == 0 else f"{llm_hits}/{llm_n}",
        "llm_double_hit": llm_double_hits,
        "llm_double_hit_rate": llm_double_rate,
        "llm_double_hit_rate_text": None if llm_n == 0 else f"{llm_double_hits}/{llm_n}",
    }


def history_groups_by_league(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(row.get("league") or "未标注", []).append(row)
    out = []
    for name, items in buckets.items():
        items = sorted(items, key=lambda r: (r.get("kickoff") or "", r.get("match_num") or ""))
        stats = summarize_hits(items)
        out.append({
            "league": name,
            "matches": items,
            "first_kickoff": items[0].get("kickoff") if items else None,
            **stats,
        })
    out.sort(key=lambda g: (g.get("first_kickoff") or "", g["league"]))
    return out


def _history_day_payload(day: str, items: list[dict]) -> dict:
    stats = summarize_hits(items)
    return {
        "day": day,
        "matches": items,
        "by_league": history_groups_by_league(items),
        "summary": stats,
        **stats,
    }


def history_index(root: Path | None = None) -> dict:
    use_shared = root is None
    rows = history_rows(root, include_shared=use_shared)
    days: dict[str, list[dict]] = {}
    for row in rows:
        days.setdefault(row["day"], []).append(row)
    out = []
    for day, items in days.items():
        stats = summarize_hits(items)
        leagues = history_groups_by_league(items)
        out.append({
            "day": day,
            **stats,
            "leagues": [
                {
                    "league": g["league"],
                    "n": g["n"],
                    "settled": g["settled"],
                    "hit": g["hit"],
                    "miss": g["miss"],
                    "hit_rate": g["hit_rate"],
                    "hit_rate_text": g["hit_rate_text"],
                    "llm_n": g["llm_n"],
                    "llm_hit": g["llm_hit"],
                    "llm_hit_rate": g["llm_hit_rate"],
                    "llm_hit_rate_text": g["llm_hit_rate_text"],
                }
                for g in leagues
            ],
        })
    out.sort(key=lambda d: d["day"], reverse=True)
    overall = summarize_hits(rows)
    return {
        "days": out,
        "total": overall["n"],
        "settled": overall["settled"],
        "hit": overall["hit"],
        "miss": overall["miss"],
        "hit_rate": overall["hit_rate"],
        "hit_rate_text": overall["hit_rate_text"],
        "llm_n": overall["llm_n"],
        "llm_hit": overall["llm_hit"],
        "llm_hit_rate": overall["llm_hit_rate"],
        "llm_hit_rate_text": overall["llm_hit_rate_text"],
        "note": "只列有量化胜平负预测的登记。量化命中=最大概率方向对上官方 90 分钟赛果。"
                "LLM 命中单独计，只评已登记方向的已结算场，不与量化合成。"
                "样本未满长期标准只列统计，不评价模型。",
    }


def history_day(day: str, root: Path | None = None) -> dict:
    use_shared = root is None
    rows = [r for r in history_rows(root, include_shared=use_shared) if r["day"] == day]
    payload = _history_day_payload(day, rows)
    payload["note"] = (
        "量化方向是 market_only 去水后的最大项，不是独立 edge。"
        "LLM 命中与量化命中分列，不合成。按联赛分列；命中率只计已结算场。"
    )
    return payload


def history_full(root: Path | None = None) -> dict:
    use_shared = root is None
    rows = history_rows(root, include_shared=use_shared)
    days: dict[str, list[dict]] = {}
    for row in rows:
        days.setdefault(row["day"], []).append(row)
    sections = [_history_day_payload(day, days[day]) for day in sorted(days, reverse=True)]
    idx = history_index(root)
    return {
        **idx,
        "sections": sections,
        "note": idx["note"] + "本页按开球日再按联赛分开。",
    }


def group_by_league(rows: list[dict]) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for row in rows:
        buckets.setdefault(row.get("league") or "未标注", []).append(row)
    out = []
    for name, items in buckets.items():
        items = sorted(items, key=lambda r: (r.get("kickoff") or "", r.get("match_num") or ""))
        out.append({
            "league": name,
            "n": len(items),
            "predicted": sum(1 for r in items if r.get("quant")),
            "missing_pred": sum(1 for r in items if r.get("bucket") == "missing_pred"),
            "first_kickoff": items[0].get("kickoff") if items else None,
            "matches": items,
        })
    out.sort(key=lambda g: (g.get("first_kickoff") or "", g["league"]))
    return out
