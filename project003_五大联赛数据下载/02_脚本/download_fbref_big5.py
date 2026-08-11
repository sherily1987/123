from __future__ import annotations

import csv
import io
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import requests
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "04_素材" / "fbref"
LOG = ROOT / "06_复盘" / "download_log.csv"
HISTORY = "https://fbref.com/en/comps/Big5/history/Big-5-European-Leagues-Seasons"
LEAGUES = {"9": "eng_premier_league", "12": "fra_ligue_1", "20": "ger_bundesliga", "11": "ita_serie_a", "13": "esp_la_liga"}
WAIT = 3.0

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; research downloader; contact user)"})

def get(url: str) -> str:
    time.sleep(WAIT)
    r = session.get(url, timeout=45)
    r.raise_for_status()
    return r.text

def log(row):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG.exists()
    with LOG.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["url", "status", "file", "message"])
        if new: w.writeheader()
        w.writerow(row)

def save_tables(url: str, dest: Path):
    html = get(url)
    # FBref wraps many tables in HTML comments; expose them to read_html.
    visible = re.sub(r"<!--|-->", "", html)
    tables = pd.read_html(io.StringIO(visible))
    dest.mkdir(parents=True, exist_ok=True)
    for i, table in enumerate(tables):
        table.to_csv(dest / f"table_{i:02d}.csv", index=False, encoding="utf-8-sig")
    (dest / "source.html").write_text(html, encoding="utf-8")
    return len(tables)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    soup = lxml_html.fromstring(get(HISTORY))
    links = {}
    for a in soup.xpath("//a[@href]"):
        href = a.get("href", "")
        m = re.match(r"/en/comps/(9|11|12|13|20)/(\d{4}-\d{4})/([^#?]+)", href)
        if m and m.group(1) in LEAGUES:
            links[(m.group(1), m.group(2), href)] = urljoin(HISTORY, href)
    for (comp, season, href), url in sorted(links.items()):
        folder = OUT / LEAGUES[comp] / season / Path(href).name.replace("-Stats", "")
        marker = folder / "source.html"
        if marker.exists():
            continue
        try:
            n = save_tables(url, folder)
            log({"url": url, "status": "ok", "file": str(folder), "message": f"{n} tables"})
            print("OK", url, n)
        except Exception as e:
            log({"url": url, "status": "error", "file": "", "message": repr(e)})
            print("ERROR", url, repr(e))

if __name__ == "__main__":
    main()
