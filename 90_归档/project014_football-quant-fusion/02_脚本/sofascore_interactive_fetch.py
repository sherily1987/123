#!/usr/bin/env python3
"""SofaScore 交互式抓取（Playwright + 用户手动过 Cloudflare 验证）。

流程：
1. 用系统 Chrome + 本机代理打开 www.sofascore.com（可见窗口）；
2. 用户在弹出的窗口里完成 Cloudflare 验证（点击/等待自动通过）；
3. 脚本检测到 cf_clearance cookie 后，自动抓取指定日期的比赛列表、
   欧冠场次的 event/statistics/lineups，保存到项目 04_素材/sofascore/。

用法：
  python sofascore_interactive_fetch.py --date 2026-08-05 [--league-filter "Champions League"]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROXY = {"server": "http://127.0.0.1:10809"}
OUT = Path(r"H:\claude AI自媒体\project014_football-quant-fusion\04_素材\sofascore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-05")
    ap.add_argument("--league-filter", default="Champions League",
                    help="赛事名子串过滤（默认欧冠）")
    ap.add_argument("--wait-seconds", type=int, default=600,
                    help="等待用户完成验证的最长秒数")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, headless=False, proxy=PROXY,
            args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.goto("https://www.sofascore.com/", timeout=60000, wait_until="domcontentloaded")
        print(f"[提示] 浏览器窗口已打开，请在窗口里完成 Cloudflare 验证"
              f"（出现验证框就点击，或等待自动通过），最多等待 {a.wait_seconds}s", flush=True)

        cf = None
        waited = 0
        while waited < a.wait_seconds:
            time.sleep(5)
            waited += 5
            cookies = ctx.cookies()
            cf = next((c for c in cookies if "cf_clearance" in c.get("name", "")), None)
            if cf:
                print(f"[OK] 验证通过（{waited}s），开始抓取 {a.date}", flush=True)
                break
            if waited % 30 == 0:
                print(f"  仍在等待验证... {waited}s", flush=True)
        if not cf:
            print("[失败] 等待超时，未获得验证 cookie", flush=True)
            browser.close()
            raise SystemExit(1)

        def api(path):
            data = page.evaluate(
                """async (p) => {
                    const r = await fetch(p, {headers: {'Accept':'application/json'}});
                    if (!r.ok) return {__error__: r.status};
                    return await r.json();
                }""", "/api/v1" + path)
            if isinstance(data, dict) and "__error__" in data:
                raise RuntimeError(f"API {path} -> {data['__error__']}")
            return data

        # 1) 当日比赛列表
        d = api(f"/sport/football/scheduled-events/{a.date}")
        events = d.get("events", []) if isinstance(d, dict) else []
        print(f"当日赛事总数: {len(events)}", flush=True)
        ucl = [e for e in events
               if a.league_filter.lower() in ((e.get("tournament") or {}).get("name") or "").lower()]
        print(f"过滤[{a.league_filter}] 场次: {len(ucl)}", flush=True)

        saved = []
        for e in ucl:
            eid = e.get("id")
            home = (e.get("homeTeam") or {}).get("name")
            away = (e.get("awayTeam") or {}).get("name")
            print(f"  [{eid}] {home} vs {away}", flush=True)
            try:
                ev = api(f"/event/{eid}")
                st = api(f"/event/{eid}/statistics")
                lu = api(f"/event/{eid}/lineups")
                for tag, payload in (("event", ev), ("statistics", st), ("lineups", lu)):
                    fp = OUT / f"{eid}_{tag}.json"
                    fp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                saved.append(eid)
                print(f"    已保存 event/statistics/lineups", flush=True)
            except Exception as ex:
                print(f"    ERR: {str(ex)[:160]}", flush=True)

        # 2) 保存当日列表
        (OUT / f"events_{a.date}.json").write_text(
            json.dumps({"date": a.date, "events": ucl}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n完成。保存 {len(saved)} 场欧冠到 {OUT}", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
