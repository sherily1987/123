#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第 4 级取数：用真浏览器记下页面自己发出的 XHR/fetch，再给人拿去纯 HTTP 复验。

不是反爬工具。遇人机验证/登录墙只记缺口。默认不保存响应正文（避免把整页
写进仓库），只记 URL、方法、状态、content-type、字节数、JSON 顶层键。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


def _json_keys(body: bytes) -> list[str] | None:
    try:
        text = body.decode("utf-8", "replace").lstrip("\ufeff")
        if text.startswith("console.log("):
            text = text[len("console.log("):]
            if text.endswith(");"):
                text = text[:-2]
        data = json.loads(text)
    except (UnicodeError, ValueError):
        return None
    if isinstance(data, dict):
        return list(data.keys())[:24]
    if isinstance(data, list):
        return [f"list[{len(data)}]"]
    return [type(data).__name__]


def capture(url: str, *, wait_ms: int = 8000) -> dict:
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.set_default_timeout(45000)

        def on_response(resp):
            req = resp.request
            rtype = req.resource_type
            if rtype not in ("xhr", "fetch"):
                return
            body = b""
            try:
                body = resp.body()
            except Exception:
                body = b""
            ctype = (resp.headers or {}).get("content-type", "")
            rows.append({
                "url": resp.url,
                "method": req.method,
                "status": resp.status,
                "resource_type": rtype,
                "content_type": ctype,
                "bytes": len(body),
                "json_keys": _json_keys(body) if body else None,
                "host": urlparse(resp.url).netloc,
            })

        page.on("response", on_response)
        nav = {"final_url": None, "title": None, "status": None, "error": None}
        try:
            reply = page.goto(url, wait_until="domcontentloaded")
            nav["status"] = None if reply is None else reply.status
            page.wait_for_timeout(wait_ms)
            nav["final_url"] = page.url
            nav["title"] = page.title()
        except Exception as exc:
            nav["error"] = f"{type(exc).__name__}: {exc}"
        browser.close()
    rows.sort(key=lambda r: (-(r["bytes"] or 0), r["url"]))
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "start_url": url,
        "nav": nav,
        "xhr_n": len(rows),
        "xhr": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", action="append", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--wait-ms", type=int, default=8000)
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pack = [capture(u, wait_ms=args.wait_ms) for u in args.url]
    args.out.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in pack:
        print(item["start_url"], "xhr", item["xhr_n"],
              "title", (item["nav"] or {}).get("title"),
              "err", (item["nav"] or {}).get("error"))
        for row in item["xhr"][:8]:
            print(" ", row["status"], row["bytes"], row["method"], row["url"][:140],
                  row["json_keys"])


if __name__ == "__main__":
    main()
