import fs from "node:fs/promises";
import path from "node:path";
import crypto from "node:crypto";
import { pathToFileURL } from "node:url";

// The desktop bundle is not installed into the repository's node_modules. Resolve it
// explicitly for this verification step, while allowing an ordinary package install.
const artifactModule = process.env.OAI_ARTIFACT_TOOL ||
  "C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";
const { Workbook } = await import(pathToFileURL(artifactModule).href);

const project = path.resolve(process.argv[2] || path.join(process.cwd(), "project021_五大联赛APIFootball训练"));
const rawDir = path.resolve(process.argv[3] || path.join(project, "04_素材", "football_data_couk_raw_csv"));
const outDir = path.resolve(process.argv[4] || path.join(project, "05_交付", "英冠历史数据", "2026-08-21"));
const outCsv = path.join(outDir, "championship_2018_2026.csv");
const outJson = path.join(outDir, "championship_2018_2026_quality.json");
const outMd = path.join(outDir, "championship_2018_2026_quality.md");

const seasons = [
  ["1819", "2018-19"], ["1920", "2019-20"], ["2021", "2020-21"], ["2122", "2021-22"],
  ["2223", "2022-23"], ["2324", "2023-24"], ["2425", "2024-25"], ["2526", "2025-26"],
];

// Canonical names are deliberately separate from raw Football-Data names. The existing
// fd_e1 training JSONL remains on its source IDs; this CSV is the auditable modelling view.
const aliases = {
  "Birmingham": "Birmingham City", "Blackburn": "Blackburn Rovers", "Bournemouth": "AFC Bournemouth",
  "Bolton": "Bolton Wanderers", "Cardiff": "Cardiff City", "Charlton": "Charlton Athletic",
  "Coventry": "Coventry City", "Derby": "Derby County", "Huddersfield": "Huddersfield Town",
  "Hull": "Hull City", "Ipswich": "Ipswich Town", "Leeds": "Leeds United", "Leicester": "Leicester City",
  "Luton": "Luton Town", "Norwich": "Norwich City", "Nott'm Forest": "Nottingham Forest",
  "Oxford": "Oxford United", "Peterboro": "Peterborough United", "Plymouth": "Plymouth Argyle",
  "Preston": "Preston North End", "QPR": "Queens Park Rangers", "Rotherham": "Rotherham United",
  "Sheffield Weds": "Sheffield Wednesday", "Stoke": "Stoke City", "Swansea": "Swansea City",
  "West Brom": "West Bromwich Albion", "Wigan": "Wigan Athletic", "Wycombe": "Wycombe Wanderers",
};

const columns = [
  "Season", "Div", "Date", "Time", "HomeTeamRaw", "AwayTeamRaw", "HomeTeam", "AwayTeam",
  "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST", "AST",
  "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
  "B365H", "B365D", "B365A", "PSH", "PSD", "PSA", "MaxH", "MaxD", "MaxA", "AvgH", "AvgD", "AvgA",
  "B365>2.5", "B365<2.5", "P>2.5", "P<2.5", "Max>2.5", "Max<2.5", "Avg>2.5", "Avg<2.5",
  "AHh", "B365AHH", "B365AHA", "PAHH", "PAHA", "MaxAHH", "MaxAHA", "AvgAHH", "AvgAHA",
  "B365CH", "B365CD", "B365CA", "PSCH", "PSCD", "PSCA", "MaxCH", "MaxCD", "MaxCA", "AvgCH", "AvgCD", "AvgCA",
  "B365C>2.5", "B365C<2.5", "PC>2.5", "PC<2.5", "MaxC>2.5", "MaxC<2.5", "AvgC>2.5", "AvgC<2.5",
  "AHCh", "B365CAHH", "B365CAHA", "PCAHH", "PCAHA", "MaxCAHH", "MaxCAHA", "AvgCAHH", "AvgCAHA",
];

const textFields = new Set(["Season", "Div", "Date", "Time", "HomeTeamRaw", "AwayTeamRaw", "HomeTeam", "AwayTeam", "FTR", "HTR", "Referee"]);
const requiredCore = ["Date", "HomeTeamRaw", "AwayTeamRaw", "FTHG", "FTAG", "FTR"];

function parseCsvRows(text) {
  // The source files are RFC4180-compatible and may contain quoted commas in Referee.
  const rows = [];
  let row = [], cell = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n") { row.push(cell.replace(/\r$/, "")); rows.push(row); row = []; cell = ""; }
    else cell += ch;
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row); }
  return rows;
}

function parseDate(value) {
  const s = String(value ?? "").trim();
  const m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/);
  if (!m) return s;
  let year = Number(m[3]);
  if (year < 100) year += year >= 70 ? 1900 : 2000;
  return `${year.toString().padStart(4, "0")}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`;
}

function numberOrBlank(value) {
  const s = String(value ?? "").trim();
  if (!s) return "";
  const n = Number(s);
  return Number.isFinite(n) ? n : s;
}

function canonical(raw) { return aliases[raw] || raw; }
function csvEscape(value) {
  const s = value == null ? "" : String(value);
  return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}
function sha256(buf) { return crypto.createHash("sha256").update(buf).digest("hex"); }

const sourceFingerprints = [];
const sourceChecks = [];
const allRows = [];
const seen = new Set();
const allCanonical = new Set();
const allRaw = new Set();
const fieldCoverage = Object.fromEntries(columns.map(c => [c, { present: 0, nonempty: 0 }]));

for (const [code, season] of seasons) {
  const file = path.join(rawDir, `E1_${code}.csv`);
  const buf = await fs.readFile(file);
  const text = buf.toString("utf8").replace(/^\uFEFF/, "");
  const rows = parseCsvRows(text);
  const header = rows.shift().map(x => x.trim());
  const index = Object.fromEntries(header.map((h, i) => [h, i]));
  const missingHeaders = ["Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"].filter(h => !(h in index));
  if (missingHeaders.length) throw new Error(`${file}: missing core headers ${missingHeaders.join(",")}`);
  const seasonRows = [];
  for (const source of rows) {
    if (!source.some(x => String(x).trim())) continue;
    const rawHome = String(source[index.HomeTeam] ?? "").trim();
    const rawAway = String(source[index.AwayTeam] ?? "").trim();
    const row = {};
    for (const col of columns) {
      let sourceCol = col;
      if (col === "HomeTeamRaw") sourceCol = "HomeTeam";
      if (col === "AwayTeamRaw") sourceCol = "AwayTeam";
      let value = sourceCol in index ? String(source[index[sourceCol]] ?? "").trim() : "";
      if (col === "Season") value = season;
      else if (col === "Date") value = parseDate(value);
      else if (col === "HomeTeamRaw") value = rawHome;
      else if (col === "AwayTeamRaw") value = rawAway;
      else if (col === "HomeTeam") value = canonical(rawHome);
      else if (col === "AwayTeam") value = canonical(rawAway);
      else if (!textFields.has(col)) value = numberOrBlank(value);
      row[col] = value;
      fieldCoverage[col].present += sourceCol in index ? 1 : 0;
      fieldCoverage[col].nonempty += value !== "" ? 1 : 0;
    }
    const key = `${season}|${row.Date}|${row.HomeTeamRaw}|${row.AwayTeamRaw}`;
    if (seen.has(key)) throw new Error(`duplicate_match_key: ${key}`);
    seen.add(key);
    allRows.push(row); seasonRows.push(row);
    allRaw.add(rawHome); allRaw.add(rawAway); allCanonical.add(row.HomeTeam); allCanonical.add(row.AwayTeam);
  }
  const badCore = seasonRows.filter(r => requiredCore.some(c => r[c] === ""));
  const resultMismatches = seasonRows.filter(r => {
    if (![r.FTHG, r.FTAG].every(v => typeof v === "number")) return true;
    const expected = r.FTHG > r.FTAG ? "H" : r.FTHG < r.FTAG ? "A" : "D";
    return r.FTR !== expected;
  });
  const dates = seasonRows.map(r => r.Date).sort();
  if (seasonRows.length !== 552) throw new Error(`${file}: expected 552 rows, got ${seasonRows.length}`);
  if (badCore.length || resultMismatches.length) throw new Error(`${file}: core_missing=${badCore.length}, result_mismatch=${resultMismatches.length}`);
  sourceFingerprints.push({ file: path.basename(file), bytes: buf.length, sha256: sha256(buf) });
  sourceChecks.push({ season, file: path.basename(file), rows: seasonRows.length, fields: header.length,
    teams: new Set(seasonRows.flatMap(r => [r.HomeTeamRaw, r.AwayTeamRaw])).size,
    date_min: dates[0], date_max: dates.at(-1), core_missing: 0, result_mismatch: 0,
    closing_1x2_nonempty: seasonRows.filter(r => r.AvgCH !== "" || r.PSCH !== "").length,
    shots_on_target_nonempty: seasonRows.filter(r => r.HST !== "" && r.AST !== "").length,
  });
}

const csv = [columns.join(","), ...allRows.map(r => columns.map(c => csvEscape(r[c])).join(","))].join("\n") + "\n";
await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(outCsv, csv, "utf8");

// Load the finished CSV through artifact-tool as a structural verification pass.
const workbook = await Workbook.fromCSV(csv, { sheetName: "championship_2018_2026" });
const sheet = workbook.worksheets.getItem("championship_2018_2026");
const used = sheet.getUsedRange();
const inspectedRows = used.values.length - 1;
const inspectedCols = used.values[0].length;
if (inspectedRows !== allRows.length || inspectedCols !== columns.length) {
  throw new Error(`artifact_tool_shape_mismatch: ${inspectedRows}x${inspectedCols}, expected ${allRows.length}x${columns.length}`);
}

const quality = {
  generated_at: new Date().toISOString(), source: "Football-Data.co.uk E1 CSV",
  source_url_pattern: "https://www.football-data.co.uk/mmz4281/{season_code}/E1.csv",
  output: { path: outCsv, rows: allRows.length, columns: columns.length, sha256: sha256(Buffer.from(csv, "utf8")) },
  seasons: sourceChecks, source_fingerprints: sourceFingerprints,
  unique_teams: { raw: allRaw.size, canonical: allCanonical.size },
  validation: { expected_seasons: seasons.length, expected_rows_per_season: 552,
    duplicate_match_keys: 0, core_missing: 0, result_mismatch: 0,
    artifact_tool_rows: inspectedRows, artifact_tool_columns: inspectedCols },
  field_coverage: Object.fromEntries(columns.map(c => [c, {
    source_header_present: fieldCoverage[c].present, nonempty: fieldCoverage[c].nonempty,
    nonempty_pct: +(100 * fieldCoverage[c].nonempty / allRows.length).toFixed(2),
  }])),
  modelling_notes: [
    "FTHG/FTAG/FTR are full-time labels; HT* are half-time labels.",
    "HS/AS/HST/AST/cards/corners are post-match statistics and must not be used as pre-match features without time-aware lagging.",
    "Canonical team names are a presentation/modeling view; existing fd_e1 JSONL training IDs remain source-stable and are not silently renamed.",
    "Missing closing odds in 2018-19 are preserved as blanks rather than backfilled from later snapshots.",
  ],
};
await fs.writeFile(outJson, JSON.stringify(quality, null, 2), "utf8");

const md = [
  "# 英冠 2018/19—2025/26 数据质量摘要", "", `生成时间：${quality.generated_at}`, "",
  `- 总场次：**${allRows.length}**（8 季 × 552）`, `- 字段：**${columns.length}**`,
  `- 原始球队名：**${allRaw.size}**；标准化球队名：**${allCanonical.size}**`,
  `- 重复比赛键：**0**；核心字段缺失：**0**；比分与 FTR 不一致：**0**`, "",
  "## 分赛季核验", "", "| Season | Rows | Fields | Teams | Date range | Closing 1X2 | Shots on target |", "|---|---:|---:|---:|---|---:|---:|",
  ...sourceChecks.map(s => `| ${s.season} | ${s.rows} | ${s.fields} | ${s.teams} | ${s.date_min}–${s.date_max} | ${s.closing_1x2_nonempty} | ${s.shots_on_target_nonempty} |`),
  "", "## 使用边界", "", ...quality.modelling_notes.map(x => `- ${x}`), "",
  "## 来源指纹", "", ...sourceFingerprints.map(s => `- ${s.file}: ${s.sha256}`), "",
  `标准化文件：\`${outCsv}\``,
].join("\n");
await fs.writeFile(outMd, md, "utf8");
console.log(JSON.stringify({ csv: outCsv, quality_json: outJson, quality_md: outMd, rows: allRows.length, columns: columns.length, unique_teams: allCanonical.size }, null, 2));
