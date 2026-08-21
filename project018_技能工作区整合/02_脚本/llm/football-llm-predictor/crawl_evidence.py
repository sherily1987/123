#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页快照的赛前事实验证。

本模块将网页抓取与事实写入分离：只有来源清单声明的事实，且页面身份、
抓取时间和关键词均通过验证，才能进入现有 evidence_NNN_*.md 主证据。
取页引擎（Crawl4AI / Playwright）可替换；纯验证函数不依赖浏览器。
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _aware_datetime(value: Any) -> datetime | None:
    """解析带时区 ISO 时间；禁止依据本机时区猜测。"""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _normalise_text(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _has_http_url(value: Any) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalise_host(value: Any) -> str:
    return urlparse(str(value or "")).hostname.casefold().removeprefix("www.") if _has_http_url(value) else ""


def build_snapshot(
    raw_match: dict[str, Any],
    source: dict[str, Any],
    *,
    title: str,
    markdown: str,
    final_url: str,
    crawled_at: str,
) -> dict[str, Any]:
    """Create the auditable, credential-free record saved after a crawl."""
    body = str(markdown or "")
    return {
        "sporttery_match_id": raw_match.get("match_id"),
        "raw_home": raw_match.get("home"),
        "raw_away": raw_match.get("away"),
        "canonical_home": source.get("canonical_home"),
        "canonical_away": source.get("canonical_away"),
        "kickoff_iso": raw_match.get("kickoff_iso"),
        "url": source.get("url"),
        "final_url": final_url,
        "source_level": source.get("source_level"),
        "title": str(title or ""),
        "crawled_at": crawled_at,
        "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "markdown": body,
    }


def verified_facts_for_snapshot(
    raw_match: dict[str, Any], source: dict[str, Any], snapshot: dict[str, Any]
) -> list[dict[str, str | int]]:
    """Return declared facts only when identity/time/wording are all verified.

    ``source.facts`` is an explicit, human-reviewed declaration. ``required_terms``
    must occur on the captured page, so a crawler cannot turn arbitrary text or an
    LLM-generated sentence into a fact.
    """
    if str(source.get("sporttery_match_id", "")) != str(raw_match.get("match_id", "")):
        return []
    source_url = str(source.get("url", "")).strip()
    if not _has_http_url(source_url):
        return []
    if _normalise_host(source_url) != _normalise_host(snapshot.get("final_url")):
        return []

    crawled_at = _aware_datetime(snapshot.get("crawled_at"))
    kickoff = _aware_datetime(raw_match.get("kickoff_iso"))
    if crawled_at is None or kickoff is None or crawled_at >= kickoff:
        return []

    title = str(snapshot.get("title", ""))
    markdown = str(snapshot.get("markdown", ""))
    page_text = _normalise_text(f"{title}\n{markdown}")
    canonical_home = _normalise_text(source.get("canonical_home"))
    canonical_away = _normalise_text(source.get("canonical_away"))
    if not canonical_home or not canonical_away:
        return []
    if canonical_home not in page_text or canonical_away not in page_text:
        return []

    verified: list[dict[str, str | int]] = []
    for fact in source.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        text = str(fact.get("text", "")).strip()
        section = fact.get("section")
        terms = [str(term).strip() for term in (fact.get("required_terms") or [])
                 if str(term).strip()]
        if not text or not isinstance(section, int) or section not in range(1, 7):
            continue
        if not terms:
            continue
        if not all(_normalise_text(term) in page_text for term in terms):
            continue
        verified.append({
            "section": section,
            "text": text,
            "source": source_url,
            "collected_at": str(snapshot["crawled_at"]),
            "source_level": str(source.get("source_level", "")),
        })
    return verified


SECTION_TITLES = {
    1: "伤停/阵容",
    2: "战意/动机",
    3: "近况/状态",
    4: "主客/旅行/天气",
    5: "赔率",
    6: "身份核验",
}


def render_primary_evidence(
    raw_match: dict[str, Any], facts: list[dict[str, Any]]
) -> tuple[str | None, dict[str, Any]]:
    """Render a primary evidence document only after every section has 2 domains."""
    by_section: dict[int, list[dict[str, Any]]] = {number: [] for number in SECTION_TITLES}
    for fact in facts:
        section = fact.get("section")
        if section in by_section:
            by_section[section].append(fact)
    for section, section_facts in by_section.items():
        domains = {
            urlparse(str(fact.get("source", ""))).netloc.casefold()
            for fact in section_facts
            if _has_http_url(fact.get("source"))
        }
        if len(domains) < 2:
            return None, {"ok": False, "reason": f"insufficient_independent_sources:{section}"}

    lines = [
        f"# {raw_match.get('match_num', '')} {raw_match.get('home', '')} vs {raw_match.get('away', '')}｜已核验证据",
        "",
        "> 所有事实均由抓取快照的页面关键词、比赛身份和赛前时间门禁验证；网页全文不直接进入 LLM。",
        "",
    ]
    for section, title in SECTION_TITLES.items():
        lines.append(f"## {section}. {title}")
        for fact in by_section[section]:
            lines.append(
                f"- {fact['text']} | source({fact['source']}) | collected_at({fact['collected_at']})"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n", {"ok": True}


def _primary_evidence_paths(evidence_dir: Path, match_index: int) -> list[Path]:
    prefix = f"evidence_{match_index:03d}"
    return [
        path for path in evidence_dir.glob("*.md")
        if path.name.startswith((prefix + "_", prefix + "."))
        and not path.name.lower().endswith("_mcp.md")
    ]


def write_primary_evidence(
    evidence_dir: Path | str,
    match_index: int,
    raw_match: dict[str, Any],
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create a primary evidence file, never overwriting a reviewed primary file."""
    evidence_dir = Path(evidence_dir)
    document, status = render_primary_evidence(raw_match, facts)
    if not status["ok"]:
        return status
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if _primary_evidence_paths(evidence_dir, match_index):
        return {"ok": False, "reason": "existing_primary_evidence"}
    output = evidence_dir / f"evidence_{match_index:03d}_crawl.md"
    output.write_text(document, encoding="utf-8")
    return {"ok": True, "path": str(output)}


def _load_raw_matches(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    matches = data.get("matches", []) if isinstance(data, dict) else data
    if not isinstance(matches, list):
        raise ValueError("raw JSON 缺少 matches 列表")
    return [match for match in matches if isinstance(match, dict)]


def _snapshot_path(snapshot_dir: Path, raw_match: dict[str, Any], source_url: str) -> Path:
    date_part = str(raw_match.get("kickoff_iso", "")).split("T", 1)[0] or "unknown-date"
    url_hash = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16]
    return snapshot_dir / date_part / str(raw_match.get("match_id")) / f"{url_hash}.json"


def _selected_sources(
    raw_matches: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    match_ids: set[str] | None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    raw_by_id = {str(match.get("match_id")): match for match in raw_matches}
    selected = [
        source for source in sources
        if isinstance(source, dict)
        and str(source.get("sporttery_match_id")) in raw_by_id
        and (match_ids is None or str(source.get("sporttery_match_id")) in match_ids)
    ]
    return raw_by_id, selected


async def fetch_page_via_playwright(url: str, *, browser_only: bool = False) -> dict[str, Any]:
    """Adapter: playwright_fetch record -> title/markdown/final_url payload."""
    import playwright_fetch as pf

    fetcher = pf.fetch_urls if browser_only else pf.fetch_http_first
    record = (await asyncio.to_thread(fetcher, [url]))[0]
    if record.get("verdict") != "ok":
        return {"ok": False, "reason": f"playwright:{record.get('verdict')}"}
    return {
        "ok": True,
        "title": str(record.get("title") or ""),
        "markdown": str(record.get("text") or ""),
        "final_url": str(record.get("final_url") or url),
    }


async def crawl_manifest(
    raw_matches: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    snapshot_dir: Path | str,
    *,
    match_ids: set[str] | None = None,
    engine: str = "crawl4ai",
    fetch_page: Any = None,
    browser_only: bool = False,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Crawl manifest URLs, persist snapshots, and return only verified facts.

    Browser engines are imported only when used. Tests inject ``fetch_page`` so
    verification can run without Crawl4AI or Playwright installed.
    """
    raw_by_id, selected = _selected_sources(raw_matches, sources, match_ids)
    facts_by_match: dict[str, list[dict[str, Any]]] = {}
    statuses: list[dict[str, Any]] = []
    snapshot_root = Path(snapshot_dir)
    engine_name = str(engine or "crawl4ai").casefold()

    async def ingest(fetcher: Any) -> None:
        for source in selected:
            match_id = str(source["sporttery_match_id"])
            raw_match = raw_by_id[match_id]
            url = str(source.get("url", ""))
            try:
                page = await fetcher(url)
            except Exception as exc:
                statuses.append({"match_id": match_id, "url": source.get("url"), "ok": False,
                                 "engine": engine_name, "reason": f"crawl_error:{str(exc)[:160]}"})
                continue
            if not page.get("ok"):
                statuses.append({"match_id": match_id, "url": source.get("url"), "ok": False,
                                 "engine": engine_name,
                                 "reason": str(page.get("reason") or "crawl_failed")[:160]})
                continue
            snapshot = build_snapshot(
                raw_match,
                source,
                title=str(page.get("title") or ""),
                markdown=str(page.get("markdown") or ""),
                final_url=str(page.get("final_url") or url),
                crawled_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            )
            output = _snapshot_path(snapshot_root, raw_match, url)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            facts = verified_facts_for_snapshot(raw_match, source, snapshot)
            facts_by_match.setdefault(match_id, []).extend(facts)
            statuses.append({"match_id": match_id, "url": source.get("url"), "ok": True,
                             "engine": engine_name, "snapshot": str(output),
                             "verified_fact_count": len(facts)})

    if fetch_page is not None:
        await ingest(fetch_page)
        return facts_by_match, statuses
    if engine_name == "playwright":
        async def fetch_playwright(url: str) -> dict[str, Any]:
            return await fetch_page_via_playwright(url, browser_only=browser_only)

        await ingest(fetch_playwright)
        return facts_by_match, statuses
    if engine_name != "crawl4ai":
        raise ValueError(f"unknown engine: {engine}")

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError as exc:  # pragma: no cover - exercised by CLI environment
        raise RuntimeError("缺少 Crawl4AI；请使用 .venv/Scripts/python.exe 运行") from exc

    browser_config = BrowserConfig(headless=True)
    run_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async def fetch_crawl4ai(url: str) -> dict[str, Any]:
            result = await crawler.arun(url=url, config=run_config)
            if not result.success:
                return {"ok": False, "reason": f"crawl_failed:{str(result.error_message or '')[:160]}"}
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            return {
                "ok": True,
                "title": str(metadata.get("title") or ""),
                "markdown": str(result.markdown or ""),
                "final_url": str(result.url or url),
            }

        await ingest(fetch_crawl4ai)
    return facts_by_match, statuses


def main() -> None:
    parser = argparse.ArgumentParser(description="赛前网页证据采集与验证")
    parser.add_argument("--input", required=True, help="体彩 raw_YYYY-MM-DD.json")
    parser.add_argument("--sources", required=True, help="人工审核的来源清单 JSON")
    parser.add_argument("--snapshot-dir", default="data/crawl_snapshots", help="快照根目录")
    parser.add_argument("--evidence-dir", help="仅配合 --write-primary 使用")
    parser.add_argument("--match-id", action="append", default=[], help="可重复指定体彩 match_id")
    parser.add_argument("--write-primary", action="store_true", help="双域齐全时创建新主证据；已有主证据拒绝覆盖")
    parser.add_argument("--engine", choices=("crawl4ai", "playwright"), default="crawl4ai",
                        help="取页引擎；验证门槛不变")
    parser.add_argument("--browser-only", action="store_true",
                        help="Playwright 引擎跳过纯 HTTP，直接渲染")
    args = parser.parse_args()

    raw_matches = _load_raw_matches(Path(args.input))
    manifest = json.loads(Path(args.sources).read_text(encoding="utf-8-sig"))
    sources = manifest.get("sources", []) if isinstance(manifest, dict) else manifest
    if not isinstance(sources, list):
        raise SystemExit("来源清单必须是 sources 数组或 JSON 数组")
    if args.write_primary and not args.evidence_dir:
        raise SystemExit("--write-primary 必须同时提供 --evidence-dir")

    facts_by_match, statuses = asyncio.run(
        crawl_manifest(raw_matches, sources, args.snapshot_dir,
                       match_ids={str(value) for value in args.match_id} or None,
                       engine=args.engine, browser_only=args.browser_only)
    )
    raw_index = {str(match.get("match_id")): (index, match) for index, match in enumerate(raw_matches, 1)}
    for status in statuses:
        print(json.dumps(status, ensure_ascii=False))
    if args.write_primary:
        for match_id, facts in facts_by_match.items():
            index, raw_match = raw_index[match_id]
            result = write_primary_evidence(args.evidence_dir, index, raw_match, facts)
            print(json.dumps({"match_id": match_id, "primary_evidence": result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
