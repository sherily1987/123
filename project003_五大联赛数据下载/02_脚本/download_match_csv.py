from pathlib import Path
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "04_素材" / "football-data_match_csv"
LOG = ROOT / "06_复盘" / "match_csv_log.csv"
LEAGUES = {"E0": "eng_premier_league", "SP1": "esp_la_liga", "I1": "ita_serie_a", "D1": "ger_bundesliga", "F1": "fra_ligue_1"}
session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (research downloader)"

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not LOG.exists():
        LOG.write_text("season,league,status,file,message\n", encoding="utf-8-sig")
    rows = []
    # 1993-94 through 2025-26; files not available are recorded, not fabricated.
    for y in list(range(93, 100)) + list(range(0, 27)):
        season = f"{y:02d}{(y + 1) % 100:02d}"
        for code, name in LEAGUES.items():
            url = f"https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
            dest = OUT / name / f"{season}_{code}.csv"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                continue
            try:
                time.sleep(0.4)
                r = session.get(url, timeout=8)
                if r.status_code == 200 and len(r.content) > 100:
                    dest.write_bytes(r.content)
                    rows.append(f"{season},{code},ok,{dest},downloaded")
                    print("OK", url)
                else:
                    rows.append(f"{season},{code},missing,,HTTP {r.status_code}")
                    print("MISSING", url, r.status_code)
            except Exception as e:
                rows.append(f"{season},{code},error,,{e!r}")
            if rows:
                with LOG.open("a", encoding="utf-8-sig") as f:
                    f.write(rows.pop() + "\n")
    print("Saved logs to", LOG)

if __name__ == "__main__":
    main()
