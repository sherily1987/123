#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""单次赛前证据编排与浏览器回补协议。

结构化 API/MCP 与本地网页抓取在一次采集窗口内完成；采集不到的部分不会
被猜测，也不会等待固定的开球前分钟数。浏览器回补是一个明确的 JSON 交接：
本地程序写 ``browser_tasks.json``，Codex 浏览器完成任务后把快照放回目录，
再由本模块按同一套身份、域名和开球前时间门禁验证。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import crawl_evidence as ce
import llm_track_contract as contract


COLLECTION_MODE = "single_pass"


def _match_id(value: Any) -> str:
    normalized = contract.normalize_match_id(value)
    return normalized or str(value or "").strip()


def _market_present(raw_match: dict[str, Any], evidence: dict[str, Any]) -> bool:
    return any(raw_match.get(name) or evidence.get(name) for name in ("crs", "ttg", "hafu"))


def _independent_section_statuses(manifest: dict[str, Any]) -> list[str]:
    sections = manifest.get("sections") or {}
    return [name for name, item in sections.items()
            if name not in {"crs", "ttg", "hafu"}
            and isinstance(item, dict) and item.get("status") in {"AVAILABLE", "PARTIAL"}]


def collection_manifest(
    raw_match: dict[str, Any],
    evidence: dict[str, Any],
    *,
    collected_at: str | None = None,
) -> dict[str, Any]:
    """Return the canonical one-shot collection status.

    ``ONLY_ODDS`` means that official Sporttery markets exist but no independent
    pre-match section was verified. It is a usable research input, never a bet
    or a probability source.
    """
    base = contract.build_evidence_manifest(raw_match, evidence)
    independent = _independent_section_statuses(base)
    if base["overall_status"] == "COMPLETE":
        status = "COMPLETE"
    elif _market_present(raw_match, evidence) and not independent:
        status = "ONLY_ODDS"
    elif independent:
        status = "PARTIAL"
    else:
        status = "UNAVAILABLE"
    return {
        "match_id": base["match_id"],
        "kickoff": base.get("kickoff"),
        "collected_at": collected_at or base.get("collected_at"),
        "collection_mode": COLLECTION_MODE,
        "collection_status": status,
        "gap_sections": list(base.get("gap_sections") or []),
        "required_sections": list(base.get("required_sections") or []),
        "sections": base.get("sections") or {},
    }


def build_browser_tasks(
    raw_matches: list[dict[str, Any]],
    manifests: dict[str, dict[str, Any]],
    sources: list[dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build match-bound tasks for Codex browser fallback.

    A task is generated only for a documented gap. Source URLs are copied from
    the reviewed manifest; an empty URL list is an explicit discovery gap, not
    permission to browse arbitrary pages without identity checks.
    """
    by_match: dict[str, list[dict[str, Any]]] = {}
    for source in sources or []:
        key = _match_id(source.get("sporttery_match_id"))
        if key:
            by_match.setdefault(key, []).append(source)

    tasks: list[dict[str, Any]] = []
    for raw in raw_matches:
        key = _match_id(raw.get("match_id") or (raw.get("sporttery_meta") or {}).get("match_id"))
        manifest = manifests.get(key) or {}
        gaps = [str(value) for value in (manifest.get("gap_sections") or [])]
        if not gaps:
            continue
        match_sources = by_match.get(key, [])
        urls = [str(source.get("url")) for source in match_sources if str(source.get("url") or "").strip()]
        facts = []
        for source in match_sources:
            for fact in source.get("facts") or []:
                if isinstance(fact, dict) and str(fact.get("section")) in gaps:
                    facts.append({
                        "url": source.get("url"),
                        "source_level": source.get("source_level"),
                        "section": fact.get("section"),
                        "required_terms": list(fact.get("required_terms") or []),
                    })
        tasks.append({
            "task_id": f"browser-{key}",
            "match_id": key,
            "home": raw.get("home"),
            "away": raw.get("away"),
            "kickoff_iso": raw.get("kickoff_iso") or raw.get("kickoff"),
            "sections": gaps,
            "urls": list(dict.fromkeys(urls)),
            "fact_checks": facts,
            "instruction": "只保存开球前快照；页面必须同时出现双方队名，保留最终URL、标题、抓取时间和原文。",
        })
    return {
        "schema_version": 1,
        "collection_mode": COLLECTION_MODE,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "tasks": tasks,
    }


def merge_browser_snapshots(
    raw_matches: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    snapshot_dir: Path | str,
) -> dict[str, dict[str, Any]]:
    """Verify browser snapshots and return facts plus rejection counts."""
    raw_by_id = {
        _match_id(raw.get("match_id") or (raw.get("sporttery_meta") or {}).get("match_id")): raw
        for raw in raw_matches
    }
    source_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources or []:
        source_by_key[(_match_id(source.get("sporttery_match_id")), str(source.get("url") or ""))] = source
    merged: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(snapshot_dir).rglob("*.json")):
        if path.name == "browser_tasks.json":
            continue
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        key = _match_id(snapshot.get("sporttery_match_id"))
        raw = raw_by_id.get(key)
        snapshot_url = str(snapshot.get("url") or snapshot.get("final_url") or "")
        source = source_by_key.get((key, snapshot_url))
        if raw is None or source is None:
            continue
        entry = merged.setdefault(key, {"verified_facts": [], "rejected_snapshots": 0, "accepted_snapshots": 0})
        facts = ce.verified_facts_for_snapshot(raw, source, snapshot)
        if facts:
            entry["verified_facts"].extend(facts)
            entry["accepted_snapshots"] += 1
        else:
            entry["rejected_snapshots"] += 1
    for entry in merged.values():
        seen: set[tuple[Any, ...]] = set()
        unique = []
        for fact in entry["verified_facts"]:
            marker = tuple(fact.get(name) for name in ("section", "text", "source", "collected_at"))
            if marker not in seen:
                seen.add(marker)
                unique.append(fact)
        entry["verified_facts"] = unique
    return merged


def write_browser_snapshot(
    raw_match: dict[str, Any],
    source: dict[str, Any],
    snapshot_dir: Path | str,
    *,
    title: str,
    markdown: str,
    final_url: str,
    crawled_at: str,
) -> Path:
    """Persist one Codex-browser result in the same schema as local crawls."""
    snapshot = ce.build_snapshot(
        raw_match,
        source,
        title=title,
        markdown=markdown,
        final_url=final_url,
        crawled_at=crawled_at,
    )
    match_key = _match_id(raw_match.get("match_id") or (raw_match.get("sporttery_meta") or {}).get("match_id"))
    digest = hashlib.sha256(str(source.get("url") or final_url).encode("utf-8")).hexdigest()[:16]
    path = Path(snapshot_dir) / match_key / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def apply_collection_degradation(aggregation: dict[str, Any], status: str) -> dict[str, Any]:
    """Annotate partial evidence; odds-only is always observe-only."""
    result = dict(aggregation)
    if status in {"PARTIAL", "ONLY_ODDS", "UNAVAILABLE"}:
        result["evidence_gap"] = True
        result["collection_status"] = status
    if status == "ONLY_ODDS":
        result.update({
            "confidence": None,
            "action": "observe",
            "recommendation": None,
            "ev_recommendation": None,
            "single_pick": None,
            "degradation_reason": "odds_only_evidence",
        })
        if not result.get("single_model"):
            result["reason"] = "odds_only_evidence"
    return result


def _load_sources(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload.get("sources", []) if isinstance(payload, dict) else payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="单次证据采集与 Codex 浏览器回补任务生成")
    parser.add_argument("--input", required=True, help="体彩 raw JSON")
    parser.add_argument("--sources", required=True, help="人工审核来源清单 JSON")
    parser.add_argument("--snapshot-dir", required=True, help="网页快照目录")
    parser.add_argument("--browser-task-file", required=True, help="输出 browser_tasks.json")
    parser.add_argument("--evidence-dir", help="可选：双源齐全时写入 primary evidence")
    parser.add_argument("--no-local-crawl", action="store_true", help="只生成浏览器任务，不执行本地抓取")
    args = parser.parse_args(argv)

    raw_matches = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    raw_matches = raw_matches.get("matches", raw_matches) if isinstance(raw_matches, dict) else raw_matches
    sources = _load_sources(Path(args.sources))
    if not args.no_local_crawl:
        asyncio.run(ce.crawl_manifest(raw_matches, sources, args.snapshot_dir, engine="playwright"))
    merged = merge_browser_snapshots(raw_matches, sources, args.snapshot_dir)
    if args.evidence_dir:
        raw_index = {
            _match_id(raw.get("match_id") or (raw.get("sporttery_meta") or {}).get("match_id")): (index, raw)
            for index, raw in enumerate(raw_matches, 1)
        }
        for key, entry in merged.items():
            if key not in raw_index or not entry.get("verified_facts"):
                continue
            index, raw = raw_index[key]
            result = ce.write_primary_evidence(
                args.evidence_dir, index, raw, entry["verified_facts"]
            )
            print(json.dumps({"match_id": key, "primary_evidence": result}, ensure_ascii=False))
    manifests: dict[str, dict[str, Any]] = {}
    for raw in raw_matches:
        key = _match_id(raw.get("match_id") or (raw.get("sporttery_meta") or {}).get("match_id"))
        facts = (merged.get(key) or {}).get("verified_facts") or []
        evidence = {"recent_form": {"home": facts, "away": facts} if any(f.get("section") == 3 for f in facts) else {"home": [], "away": []}}
        manifests[key] = collection_manifest(raw, evidence)
    tasks = build_browser_tasks(raw_matches, manifests, sources)
    output = Path(args.browser_task_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"collection_mode": COLLECTION_MODE, "tasks": len(tasks["tasks"]), "browser_task_file": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
