#!/usr/bin/env python3
"""SofaScore 数据解析器（浏览器辅助抓取 → fusion 可读 JSON）。

输入：用户从浏览器复制粘贴的 SofaScore API 响应 JSON，
      或 HAR 文件（Network → Save all as HAR）。
覆盖：/event/{id}/statistics（xG/射门/控球）、/event/{id}/lineups（阵容/缺阵）、
      /event/{id}（比赛信息）、incidents（事件）。
输出：标准化 JSON：xG、关键统计、阵容、缺阵/伤停线索（供 mapped 枚举映射）。

用法：
  python sofascore_har_parse.py --json 粘贴内容.json --output out.json
  python sofascore_har_parse.py --har 导出.har --output out.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def parse_statistics(payload):
    """解析 /event/{id}/statistics 响应：按 home/away 提取关键统计。"""
    stats = payload.get("statistics") or []
    out = {"home": {}, "away": {}}
    for side, key in (("home", "home"), ("away", "away")):
        for group in stats:
            for item in group.get("statisticsItems", []):
                name = item.get("name")
                if name:
                    out[key][name] = {"home": item.get("home"), "away": item.get("away")}
    # 提取 xG（SofaScore 常用名："Expected goals (xG)"）
    xg = None
    for k, v in out.get("home", {}).items():
        if "expected" in k.lower() and "goal" in k.lower():
            xg = {"label": k, "home": _num(v.get("home")), "away": _num(v.get("away"))}
            break
    return {"statistics": out, "xg": xg}


def parse_lineups(payload):
    """解析 /event/{id}/lineups：首发/替补/缺阵线索。"""
    out = {"home": {"confirmed": None, "players": [], "unavailable": []},
           "away": {"confirmed": None, "players": [], "unavailable": []}}
    for side in ("home", "away"):
        lu = payload.get(side) or {}
        out[side]["confirmed"] = lu.get("confirmed")
        for group in lu.get("players", []):
            for p in group.get("players", []):
                row = {"id": p.get("id"), "name": p.get("name"),
                       "position": (p.get("position") or {}).get("name") if p.get("position") else None,
                       "shirt": p.get("shirtNumber"), "substitute": p.get("substitute")}
                out[side]["players"].append(row)
    # 缺阵/伤停线索：SofaScore lineup 响应中 absent 字段（如存在）
    for side in ("home", "away"):
        lu = payload.get(side) or {}
        for a in lu.get("absent", []) or []:
            out[side]["unavailable"].append({"name": a.get("name"), "reason": a.get("reason")})
    return out


def parse_event(payload):
    """解析 /event/{id}：基本信息。"""
    return {
        "event_id": payload.get("id"),
        "home": (payload.get("homeTeam") or {}).get("name"),
        "away": (payload.get("awayTeam") or {}).get("name"),
        "tournament": (payload.get("tournament") or {}).get("name"),
        "status": (payload.get("status") or {}).get("description"),
        "home_score": (payload.get("homeScore") or {}).get("current"),
        "away_score": (payload.get("awayScore") or {}).get("current"),
        "start_timestamp": payload.get("startTimestamp"),
    }


def from_har(har_path):
    """从 HAR 提取所有匹配 api.sofascore.com 的 JSON 响应。"""
    har = json.loads(Path(har_path).read_text(encoding="utf-8"))
    entries = har.get("log", {}).get("entries", [])
    hits = []
    for e in entries:
        url = e.get("request", {}).get("url", "")
        if "api.sofascore.com" not in url:
            continue
        content = e.get("response", {}).get("content", {})
        text = content.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        kind = "event" if "/event/" in url and not any(x in url for x in ("statistics", "lineups", "incidents", "graph")) else (
            "statistics" if "/statistics" in url else ("lineups" if "/lineups" in url else "other"))
        hits.append({"url": url, "kind": kind, "payload": payload})
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="单个 SofaScore API 响应 JSON 文件")
    ap.add_argument("--har", help="HAR 文件路径")
    ap.add_argument("--output", required=True)
    a = ap.parse_args()

    result = {"schema": "sofascore-parse-1.0", "entries": []}
    if a.har:
        for h in from_har(a.har):
            parsed = {"url": h["url"], "kind": h["kind"]}
            if h["kind"] == "statistics":
                parsed.update(parse_statistics(h["payload"]))
            elif h["kind"] == "lineups":
                parsed.update(parse_lineups(h["payload"]))
            elif h["kind"] == "event":
                parsed.update(parse_event(h["payload"]))
            result["entries"].append(parsed)
    elif a.json:
        payload = json.loads(Path(a.json).read_text(encoding="utf-8"))
        # 尝试按 URL 关键词猜测类型（文件名里含 statistics/lineups 等）
        name = Path(a.json).stem.lower()
        kind = "statistics" if "statistic" in name else ("lineups" if "lineup" in name else (
            "event" if name.startswith("event") else "unknown"))
        parsed = {"source_file": a.json, "kind": kind}
        if kind == "statistics":
            parsed.update(parse_statistics(payload))
        elif kind == "lineups":
            parsed.update(parse_lineups(payload))
        else:
            parsed.update(parse_event(payload))
        result["entries"].append(parsed)
    else:
        raise SystemExit("需要 --json 或 --har 之一")

    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "entries": len(result["entries"]), "output": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
