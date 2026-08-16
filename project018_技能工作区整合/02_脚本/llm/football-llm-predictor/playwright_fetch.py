#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JS 渲染页面的证据抓取（真浏览器）。

定位：补上 curl / web_extract 只能拿到骨架的那一类源。**不是**反爬对抗工具。

边界（与 CRAWL4AI_EVIDENCE.md 第 5 条一致）：
    页面若返回人机验证 / 登录墙 / 付费墙，一律判 ``challenge`` 或 ``blocked``
    并如实记录缺口，不做任何绕过。判定逻辑在 `classify_verdict`，抓取逻辑不
    含任何指纹伪装；UA 只声明为普通桌面 Chrome，与实际使用的内核一致。

与 crawl_evidence.py 的分工：
    crawl_evidence.py 走「来源清单 + 关键词验证 + 跨域门槛 → 主证据」的完整
    门禁，是写入 evidence_NNN_*.md 的唯一合法路径。本模块只负责把页面**取到**
    并留下可审计快照，不写主证据、不生成事实。取到的快照仍需按来源清单流程
    才能进入证据。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 与实际内核一致的普通桌面 UA；不伪装成其它浏览器或设备。
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")

# 人机验证 / 拦截页的公开特征词，命中即判缺口。
CHALLENGE_PATTERN = re.compile(
    r"just a moment|attention required|checking your browser|verify you are human|"
    r"cf-chl|challenge-platform|enable javascript and cookies|请稍候|"
    r"access denied|are you a robot",
    re.I,
)

# 低于此信息量视为骨架页（JS 未渲染或内容被抽走）。单位见 text_weight。
THIN_TEXT_WEIGHT = 2500

# 中日韩表意文字区段：一个字承载的信息约等于若干个拉丁字母，按字符数直接
# 比长度会把内容完整的日文页误判成骨架（jleague.jp 实测 2254 字符已是全量赛程）。
_CJK_PATTERN = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")
_CJK_WEIGHT = 3.0


def text_weight(text: str) -> int:
    """正文信息量估计：CJK 字符按 _CJK_WEIGHT 折算，其余按 1。"""
    body = (text or "").strip()
    cjk = len(_CJK_PATTERN.findall(body))
    return int(len(body) - cjk + cjk * _CJK_WEIGHT)


def classify_verdict(status: int | None, title: str, text: str) -> str:
    """判定抓取结果。verdict 不是「成功与否」，是「这页能不能当证据用」。

    challenge  —— 命中人机验证特征，按缺口记录，不得绕过
    blocked    —— 服务端明确拒绝（403/406/429 等）
    http_error —— 其它 4xx/5xx
    thin       —— 拿到 200 但正文过短，多半仍是骨架
    ok         —— 正文足量，可进入来源清单验证流程
    """
    blob = f"{title or ''} {(text or '')[:4000]}"
    if CHALLENGE_PATTERN.search(blob):
        return "challenge"
    if status is not None:
        if status in (401, 403, 406, 429):
            return "blocked"
        if status >= 400:
            return "http_error"
    if text_weight(text) < THIN_TEXT_WEIGHT:
        return "thin"
    return "ok"


def url_key(url: str) -> str:
    """快照文件名：URL 的稳定短哈希，避免路径非法字符。"""
    return hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:16]


def same_host(url_a: str, url_b: str) -> bool:
    """同 hostname 判定（仅容忍 www. 差异），口径与 crawl_evidence.py 一致。"""
    def host(u: str) -> str:
        parsed = urlparse(str(u or ""))
        return (parsed.hostname or "").casefold().removeprefix("www.")
    return bool(host(url_a)) and host(url_a) == host(url_b)


def build_record(
    url: str,
    *,
    final_url: str,
    status: int | None,
    title: str,
    text: str,
    fetched_at: str,
    error: str = "",
) -> dict[str, Any]:
    """可审计快照记录；不保存 cookie、会话或凭据。"""
    body = str(text or "")
    verdict = "error" if error else classify_verdict(status, title, body)
    return {
        "url": url,
        "final_url": final_url,
        "redirected_offsite": bool(final_url) and not same_host(url, final_url),
        "http_status": status,
        "title": str(title or ""),
        "verdict": verdict,
        "text_chars": len(body.strip()),
        "fetched_at": fetched_at,
        "content_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "error": error,
        "text": body,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_http(url: str, *, timeout_s: int = 25) -> dict[str, Any]:
    """纯 HTTP 取页（不开浏览器）。

    2026-08-16 实测：transfermarkt 伤停表、oddsportal 1X2、jleague 赛程的正文
    都在服务端 HTML 里，纯 HTTP 即可拿到——历史证据里记的「未取到」是抽取/截断
    问题，不是封锁。所以先走这条便宜路径，拿不到再升级到浏览器。
    """
    import httpx

    try:
        response = httpx.get(url, headers={"User-Agent": USER_AGENT},
                             timeout=timeout_s, follow_redirects=True)
    except Exception as exc:
        return build_record(url, final_url="", status=None, title="", text="",
                            fetched_at=_now_iso(),
                            error=f"{type(exc).__name__}: {str(exc)[:200]}")
    html = response.text
    stripped = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ",
                      html, flags=re.S | re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    stripped = re.sub(r"[ \t]+", " ", stripped)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    record = build_record(url, final_url=str(response.url),
                          status=response.status_code,
                          title=title_match.group(1).strip() if title_match else "",
                          text=stripped, fetched_at=_now_iso())
    record["fetched_via"] = "http"
    return record


def fetch_urls(
    urls: list[str],
    *,
    wait_ms: int = 4000,
    timeout_ms: int = 40000,
    locale: str = "en-US",
) -> list[dict[str, Any]]:
    """用无头 Chromium 渲染每个 URL，返回快照记录列表。"""
    from playwright.sync_api import sync_playwright

    records: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=USER_AGENT, locale=locale,
            viewport={"width": 1366, "height": 900})
        for url in urls:
            # 每个 URL 用独立 page：一个 URL 的失败导航会打断同一 page 上后续
            # 的 goto（实测 ERR_CONNECTION_CLOSED 后整批连环报 "interrupted by
            # another navigation"），必须隔离，否则一个坏源污染整批。
            page = context.new_page()
            try:
                response = page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                page.wait_for_timeout(wait_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass  # networkidle 超时不影响已渲染内容
                text = page.evaluate("() => document.body ? document.body.innerText : ''")
                records.append(build_record(
                    url,
                    final_url=page.url,
                    status=response.status if response else None,
                    title=page.title(),
                    text=text,
                    fetched_at=_now_iso(),
                ))
            except Exception as exc:  # 单页失败不影响整批
                records.append(build_record(
                    url, final_url="", status=None, title="", text="",
                    fetched_at=_now_iso(),
                    error=f"{type(exc).__name__}: {str(exc)[:200]}"))
            finally:
                page.close()
        browser.close()
    for record in records:
        record.setdefault("fetched_via", "browser")
    return records


def fetch_http_first(urls: list[str], **browser_kwargs: Any) -> list[dict[str, Any]]:
    """先纯 HTTP，仅对 HTTP 未取到正文的 URL 开浏览器。

    challenge / blocked 不升级——人机验证和服务端拒绝换个客户端也不该硬闯，
    按缺口记录。只有 thin / error（多为 JS-only 页）才值得付渲染的代价。
    """
    http_records = {url: fetch_http(url) for url in urls}
    needs_browser = [url for url, record in http_records.items()
                     if record["verdict"] in {"thin", "error"}]
    rendered = {r["url"]: r for r in fetch_urls(needs_browser, **browser_kwargs)} \
        if needs_browser else {}

    results = []
    for url in urls:
        http_record = http_records[url]
        browser_record = rendered.get(url)
        if browser_record and browser_record["verdict"] not in {"thin", "error"}:
            browser_record["http_verdict"] = http_record["verdict"]
            results.append(browser_record)
        else:
            if browser_record:
                http_record["browser_verdict"] = browser_record["verdict"]
            results.append(http_record)
    return results


def write_records(records: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for record in records:
        path = out_dir / f"{url_key(record['url'])}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def format_report(records: list[dict[str, Any]]) -> str:
    lines = [f"{'verdict':<11} {'via':<8} {'chars':>7}  {'status':>6}  url"]
    for record in records:
        lines.append(
            f"{record['verdict']:<11} {record.get('fetched_via', 'http'):<8} "
            f"{record['text_chars']:>7}  "
            f"{str(record['http_status'] or '-'):>6}  {record['url']}")
    gaps = [r for r in records if r["verdict"] in {"challenge", "blocked", "error", "thin"}]
    if gaps:
        lines.append("")
        lines.append(f"缺口 {len(gaps)}/{len(records)}——按证据纪律如实记录，不绕过：")
        for record in gaps:
            note = record["error"] or record["verdict"]
            lines.append(f"  - {urlparse(record['url']).hostname}: {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="用真浏览器渲染取页；遇人机验证只记缺口，不绕过。")
    parser.add_argument("--url", action="append", default=[], help="目标 URL，可重复")
    parser.add_argument("--urls-file", help="每行一个 URL 的文件（# 开头为注释）")
    parser.add_argument("--out-dir", required=True, help="快照输出目录")
    parser.add_argument("--wait-ms", type=int, default=4000, help="domcontentloaded 后额外等待")
    parser.add_argument("--timeout-ms", type=int, default=40000)
    parser.add_argument("--locale", default="en-US")
    parser.add_argument("--browser-only", action="store_true",
                        help="跳过纯 HTTP 尝试，直接渲染（默认先 HTTP，取不到才开浏览器）")
    args = parser.parse_args(argv)

    urls = list(args.url)
    if args.urls_file:
        for line in Path(args.urls_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        parser.error("至少需要一个 --url 或 --urls-file")

    fetcher = fetch_urls if args.browser_only else fetch_http_first
    records = fetcher(urls, wait_ms=args.wait_ms,
                      timeout_ms=args.timeout_ms, locale=args.locale)
    write_records(records, Path(args.out_dir))
    print(format_report(records))
    return 0 if any(r["verdict"] == "ok" for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
