from io import StringIO
from pathlib import Path
import re

import pandas as pd
from lxml import html as lxml_html

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "04_素材" / "fbref_member_exports"
OUT = ROOT / "04_素材" / "标准化"
OUT.mkdir(parents=True, exist_ok=True)

def natural_key(p):
    m = re.search(r"\((\d+)\)", p.name)
    return int(m.group(1)) if m else 0

def canonical_columns(raw_html, table):
    root = lxml_html.fromstring(raw_html)
    stats = []
    for th in root.xpath("//table[1]//thead//th[@data-stat]"):
        s = th.get("data-stat")
        if s and s not in stats:
            stats.append(s)
    # Group headers such as header_playing are not data columns.
    leaf_stats = [s for s in stats if not s.startswith("header_")]
    if len(leaf_stats) == len(table.columns):
        return leaf_stats
    if len(stats) == len(table.columns):
        return stats
    cols = []
    for c in table.columns:
        if isinstance(c, tuple):
            cols.append("_".join(str(x) for x in c if str(x) != "nan"))
        else:
            cols.append(str(c))
    return cols

tables = []
manifest = []
for p in sorted(SRC.glob("*.xls"), key=natural_key):
    raw = p.read_bytes().decode("utf-8", errors="replace")
    df = pd.read_html(StringIO(raw))[0]
    df.columns = canonical_columns(raw, df)
    df = df.dropna(how="all").copy()
    df.insert(0, "source_file", p.name)
    out_name = p.stem.replace(" ", "_") + ".csv"
    df.to_csv(OUT / out_name, index=False, encoding="utf-8-sig")
    schema = "player_stats" if "player" in " ".join(df.columns).lower() or len(df) > 20 else "league_table"
    manifest.append({"source_file": p.name, "rows": len(df), "columns": len(df.columns), "schema": schema, "normalized_file": out_name})
    if schema == "league_table":
        tables.append(df)

if tables:
    pd.concat(tables, ignore_index=True).to_csv(OUT / "k_league_tables_combined.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(manifest).to_csv(OUT / "export_manifest.csv", index=False, encoding="utf-8-sig")
print(pd.DataFrame(manifest).to_string(index=False))
