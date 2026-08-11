#!/usr/bin/env python3
"""SofaScore 抓取（Playwright stealth + 用户手动过 Cloudflare 验证）。

加强反检测：覆盖 navigator.webdriver 等自动化特征，headful 真实 Chrome + 本机代理。
用户在弹出的窗口完成验证后，脚本自动抓取指定日期的欧冠比赛
event/statistics/lineups 到项目 04_素材/sofascore/。
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

STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = {runtime: {}};
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 0});
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-05")
    ap.add_argument("--league-filter", default="Champions League")
    ap.add_argument("--wait-seconds", type=int, default=420)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=CHROME, headless=False, proxy=PROXY,
            args=["--disable-blink-features=AutomationControlled",
                  "--disable-infobars", "--no-first-run", "--no-default-browser-check"])
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="zh-CN")
        ctx.add_init_script(STEALTH_JS)
        page = ctx.new_page()
        page.goto("https://www.sofascore.com/", timeout=60000, wait_until="domcontentloaded")
        print(f"[提示] 请在浏览器窗口完成 Cloudflare 验证（若出现验证框请点击），等待最多 {a.wait_seconds}s", flush=True)

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
                print(f"  等待验证... {waited}s | cookies: {[c['name'] for c in cookies][:6]}", flush=True)
        if not cf:
            print("[失败] 等待超时，未获得 cf_clearance", flush=True)
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

        d = api(f"/sport/football/scheduled-events/{a.date}")
        events = d.get("events", []) if isinstance(d, dict) else []
        ucl = [e for e in events
               if a.league_filter.lower() in ((e.get("tournament") or {}).get("name") or "").lower()]
        print(f"当日赛事 {len(events)} | 欧冠 {len(ucl)}", flush=True)
        for e in ucl:
            eid = e.get("id")
            print(f"  [{eid}] {(e.get('homeTeam') or {}).get('name')} vs {(e.get('awayTeam') or {}).get('name')}", flush=True)
            try:
                for tag, path in (("event", f"/event/{eid}"),
                                  ("statistics", f"/event/{eid}/statistics"),
                                  ("lineups", f"/event/{eid}/lineups")):
                    payload = api(path)
                    (OUT / f"{eid}_{tag}.json").write_text(
                        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                print("    已保存", flush=True)
            except Exception as ex:
                print(f"    ERR {str(ex)[:160]}", flush=True)
        (OUT / f"events_{a.date}.json").write_text(
            json.dumps({"date": a.date, "events": ucl}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成。输出目录 {OUT}", flush=True)
        browser.close()


if __name__ == "__main__":
    main()
