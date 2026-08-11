from pathlib import Path
import pyreadr

ROOT = Path(__file__).resolve().parents[1]
src = ROOT / "04_素材" / "worldfootballR_data" / "data" / "match_results" / "KOR_match_results.rds"
out = ROOT / "04_素材" / "csv"
out.mkdir(parents=True, exist_ok=True)
df = next(iter(pyreadr.read_r(src).values()))
df.to_csv(out / "KOR_all_fbref_match_results.csv", index=False, encoding="utf-8-sig")

mask = df["Tier"].astype(str).str.contains("1st", case=False, na=False)
df.loc[mask].to_csv(out / "K-League-1_fbref_match_results.csv", index=False, encoding="utf-8-sig")
df["Competition_Name"].value_counts(dropna=False).rename_axis("Competition_Name").reset_index(name="match_rows").to_csv(out / "competition_summary.csv", index=False, encoding="utf-8-sig")
print("all rows:", len(df), "tier-1 rows:", int(mask.sum()))
