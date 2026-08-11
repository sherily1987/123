import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

import { buildSlide05 } from "./layout/slide-05.mjs";
import { buildSlide19 } from "./layout/slide-19.mjs";
import { buildSlide26 } from "./layout/slide-26.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = __dirname;
const FINAL_PPTX = path.join(OUT_DIR, "欧冠预测_奥林匹亚科斯vsNEC奈梅亨.pptx");

async function writeBlob(relPath, blob) {
  await fs.writeFile(path.join(OUT_DIR, relPath), new Uint8Array(await blob.arrayBuffer()));
}

const INK = "#000000";
const MUTED = "#4B5563";
const PANEL = "#F2F2F2";
const PANEL_LIGHT = "#EAF5FB";
const RULE = "#B8BCC4";
const ACCENT = "#6DCBF4";
const ACCENT_STRONG = "#3D8DFF";
const FONT = "Helvetica Neue";

function titleToken(text) {
  return {
    runs: [{ run: text, textStyle: { fontSize: "38.67px", typeface: FONT, color: INK } }],
    paragraphStyle: { lineSpacingPercent: 90000 },
  };
}

function run(text, fontSize, color = INK, bold = false) {
  return { run: text, textStyle: { fontSize: `${fontSize}px`, typeface: FONT, color, bold } };
}

function simple(text, fontSize, color = INK, bold = false) {
  return {
    runs: [run(text, fontSize, color, bold)],
    paragraphStyle: { lineSpacingPercent: 110000 },
  };
}

function bodyToken(title, bodyLines, titleSize = 24, bodySize = 21.33) {
  const titleHere = {
    runs: [run(title, titleSize, INK, true)],
    spaceAfter: 800,
    paragraphStyle: { lineSpacingPercent: 114000 },
  };
  const runs = [];
  for (const line of bodyLines) {
    runs.push({ run: line, textStyle: { fontSize: `${bodySize}px`, typeface: FONT, color: "#1F2937" } });
    runs.push({ run: "\n", textStyle: { fontSize: `${bodySize}px`, typeface: FONT } });
  }
  const loremIpsumDolorSitAmetConsecteturAdipiscing = {
    runs,
    paragraphStyle: { lineSpacingPercent: 114000 },
  };
  return { titleHere, loremIpsumDolorSitAmetConsecteturAdipiscing };
}

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

/* ============ Slide 1: Cover ============ */
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  const panel = slide.shapes.add({
    geometry: "roundRect",
    name: "cover-accent-panel",
    position: { left: 41.33, top: 500, width: 580, height: 176 },
    fill: PANEL_LIGHT,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const label = slide.shapes.add({
    geometry: "textbox",
    name: "cover-label",
    position: { left: 41.33, top: 36.12, width: 800, height: 40 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  label.text = simple("UEFA CHAMPIONS LEAGUE 2026/27 · QUALIFYING ROUND 3", 20, MUTED, true);
  const title = slide.shapes.add({
    geometry: "textbox",
    name: "cover-title",
    position: { left: 41.33, top: 96, width: 1197.33, height: 130 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  title.text = {
    runs: [
      run("奥林匹亚科斯", 64, INK, true),
      run(" vs ", 64, ACCENT_STRONG, true),
      run("NEC奈梅亨", 64, INK, true),
    ],
    paragraphStyle: { lineSpacingPercent: 90000 },
  };
  const subtitle = slide.shapes.add({
    geometry: "textbox",
    name: "cover-subtitle",
    position: { left: 41.33, top: 250, width: 900, height: 60 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  subtitle.text = simple("赛前量化预测报告 · 首回合", 26, MUTED);
  const line1 = slide.shapes.add({
    geometry: "textbox",
    name: "cover-meta1",
    position: { left: 41.33, top: 340, width: 700, height: 40 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  line1.text = simple("2026年8月4日 21:00（希腊时间）· 卡拉伊斯卡基斯球场", 20, INK);
  const line2 = slide.shapes.add({
    geometry: "textbox",
    name: "cover-meta2",
    position: { left: 41.33, top: 392, width: 700, height: 40 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  line2.text = simple("欧冠资格赛第三轮 · 双回合淘汰制 · 胜者进入附加赛轮", 20, INK);
  const verdict = slide.shapes.add({
    geometry: "textbox",
    name: "cover-verdict",
    position: { left: 72, top: 536, width: 520, height: 110 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  verdict.text = {
    runs: [
      run("预测：主队 2-1 胜", 34, INK, true),
      { run: "\n", textStyle: { fontSize: "34px", typeface: FONT } },
      run("主胜概率 60.5% · 置信度：中", 22, MUTED),
    ],
    paragraphStyle: { lineSpacingPercent: 112000 },
  };
  const footer = slide.shapes.add({
    geometry: "textbox",
    name: "cover-footer",
    position: { left: 41.33, top: 659.24, width: 1197.33, height: 25.33 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  footer.text = simple("1", 13.33, INK);
  footer.text.style = { alignment: "right", verticalAlignment: "bottom" };
  slide.speakerNotes.textFrame.setText("Sources: UEFA Champions League third qualifying round schedule; sport24.gr (kick-off 21:00, Karaiskakis); Novasports (29,000 tickets sold). Prediction for informational purposes only.");
}

/* ============ Slide 2: Match context (module 05, two columns) ============ */
{
  const tokens = {
    title: titleToken("两支球队，一条通往欧冠正赛的路"),
    footer1: "2",
    body1: bodyToken("奥林匹亚科斯（希腊）", [
      "UEFA 俱乐部排名第 29 位，欧战系数约 54-57 分",
      "2023/24 欧协联冠军，欧战经验丰富",
      "上季希腊超第 2 名（66 分），主场 10 胜 4 平 2 负",
      "全队身价接近 2 亿欧元（穆扎基蒂斯、古斯塔沃·萨各值 2500 万欧）",
    ], 26, 21.33),
    body2: bodyToken("NEC奈梅亨（荷兰）", [
      "队史首次参加欧冠资格赛",
      "上季荷甲第 3 名（59 分），拿到欧冠资格",
      "全队身价约 5000-6000 万欧元",
      "夏窗引入塔迪奇、埃姆雷·莫尔、西尔赫伊斯等新援",
    ], 26, 21.33),
  };
  const slide = buildSlide05(presentation, tokens);
  slide.speakerNotes.textFrame.setText("Sources: sportal.gr (UEFA ranking 29th, coefficient 54-57); FBref (Olympiacos 2025-26 league record 19-9-4, 66 pts); VI.nl/ESPN.nl (NEC Eredivisie 3rd, new signings); Transfermarkt/Sportime (squad values).");
}

/* ============ Slide 3: Data quality (custom table) ============ */
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  const title = slide.shapes.add({
    geometry: "textbox",
    name: "dq-title",
    position: { left: 41.33, top: 36.12, width: 1197.33, height: 70 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  title.text = titleToken("数据质量评估：关键字段已交叉验证");
  const intro = slide.shapes.add({
    geometry: "textbox",
    name: "dq-intro",
    position: { left: 41.33, top: 122, width: 1197.33, height: 60 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  intro.text = simple("综合质量 85%，通过但轻微降级：个别伤病与阵容细节存在合理不确定性", 22, MUTED);

  const table = slide.tables.add({
    position: { left: 41.33, top: 210, width: 1197.34, height: 410 },
    rows: 4,
    columns: 4,
    values: [
      ["维度", "状态", "质量评分", "说明"],
      ["主队数据", "⚠️ 需跟踪", "85%", "联赛战绩、身价、欧战系数已核实；塔雷米/亚列姆丘克落选因转会，名单 8/3 可调"],
      ["客队数据", "⚠️ 需跟踪", "80%", "上季荷甲第 3（59 分）已核实；桑德勒伤情来自荷媒，未获官方确认"],
      ["环境与背景", "✅ 通过", "90%", "开球时间、球场、裁判、门票已交叉验证；双方均处夏训末段"],
    ],
    columnWidths: [220, 200, 160, 617.34],
  });
  table.borders.assign({ style: "solid", fill: RULE, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 4 }).assign({
    fill: PANEL,
    textStyle: { bold: true, fontSize: 18, typeface: FONT, color: INK },
  });
  table.cells.block({ row: 1, column: 0, rowCount: 3, columnCount: 4 }).assign({
    fill: "#FFFFFF",
    textStyle: { fontSize: 17, typeface: FONT, color: INK },
  });

  const footer = slide.shapes.add({
    geometry: "textbox",
    name: "dq-footer",
    position: { left: 41.33, top: 659.24, width: 1197.33, height: 25.33 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  footer.text = simple("3", 13.33, INK);
  footer.text.style = { alignment: "right", verticalAlignment: "bottom" };
  slide.speakerNotes.textFrame.setText("Sources: FBref (Olympiacos record); voetbalprimeur.nl/VI.nl (NEC injuries); sport24.gr (referee); novasports.gr (tickets). Data validity windows per ucl-predictor: injuries 3d, lineups 7d, Euro form 14d, coefficients/values 30d.");
}

/* ============ Slide 4: Win/Draw/Loss probability (module 19) ============ */
{
  const tokens = {
    title: titleToken("胜平负概率：主队优势明确，但并非一边倒"),
    footer1: "4",
    body1: {
      topic: simple("基于四因素评分差 0.93 分映射，概率相加为 100%", 21.33, MUTED),
      loremIpsumDolorSitAmetConsecteturAdipiscing: simple("主队阵容深度占优，但锋线减配使平局与客队拿分概率被抬高", 18, MUTED),
    },
    stat1: { runs: [run("60.5%", 56, INK, true)], paragraphStyle: { lineSpacingPercent: 90000 } },
    stat2: { runs: [run("23.5%", 56, INK, true)], paragraphStyle: { lineSpacingPercent: 90000 } },
    stat3: { runs: [run("16.0%", 56, INK, true)], paragraphStyle: { lineSpacingPercent: 90000 } },
    body2: simple("主胜", 30, INK, true),
    body3: simple("平局", 30, INK, true),
    body4: simple("客胜", 30, INK, true),
  };
  const slide = buildSlide19(presentation, tokens);
  slide.speakerNotes.textFrame.setText("Probabilities derived from the four-factor model (fundamentals 35%, personnel/form 25%, environment 20%, psychology 20%). Reference: Football Meets Data supercomputer gives Olympiacos 67% tie-advance probability vs NEC 33% (sportal.gr).");
}

/* ============ Slide 5: Expected scoreline (custom) ============ */
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  const title = slide.shapes.add({
    geometry: "textbox",
    name: "score-title",
    position: { left: 41.33, top: 36.12, width: 1197.33, height: 70 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  title.text = titleToken("预期比分：主队 2-1 取胜，上下半场各进一球");
  const intro = slide.shapes.add({
    geometry: "textbox",
    name: "score-intro",
    position: { left: 41.33, top: 122, width: 1197.33, height: 50 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  intro.text = simple("预期进球：主队约 1.8，客队约 1.1（含主客场修正）", 22, MUTED);

  const leftPanel = slide.shapes.add({
    geometry: "roundRect",
    name: "score-full",
    position: { left: 41.33, top: 200, width: 580, height: 340 },
    fill: PANEL,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const fullLabel = slide.shapes.add({
    geometry: "textbox",
    position: { left: 70, top: 226, width: 500, height: 40 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  fullLabel.text = simple("全场", 22, MUTED, true);
  const fullScore = slide.shapes.add({
    geometry: "textbox",
    position: { left: 70, top: 280, width: 520, height: 110 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  fullScore.text = {
    runs: [run("2", 80, ACCENT_STRONG, true), run("  -  ", 60, MUTED), run("1", 80, INK, true)],
    paragraphStyle: { lineSpacingPercent: 90000 },
  };
  const halves = slide.shapes.add({
    geometry: "textbox",
    position: { left: 70, top: 410, width: 520, height: 90 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  halves.text = {
    runs: [
      run("上半场 1-0　·　下半场 1-1", 24, INK),
      { run: "\n", textStyle: { fontSize: "24px", typeface: FONT } },
      run("最可能比分：2-1 / 2-0 / 1-0", 20, MUTED),
    ],
    paragraphStyle: { lineSpacingPercent: 114000 },
  };

  const rightPanel = slide.shapes.add({
    geometry: "roundRect",
    name: "score-note",
    position: { left: 658.17, top: 200, width: 580, height: 340 },
    fill: PANEL_LIGHT,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const noteTitle = slide.shapes.add({
    geometry: "textbox",
    position: { left: 690, top: 226, width: 520, height: 40 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  noteTitle.text = simple("为什么是 2-1 而不是 3-0？", 24, INK, true);
  const noteBody = slide.shapes.add({
    geometry: "textbox",
    position: { left: 690, top: 282, width: 520, height: 230 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  noteBody.text = {
    runs: [
      run("主队只注册了埃尔卡比一名正印中锋，进攻上限被压缩", 20, "#1F2937"),
      { run: "\n", textStyle: { fontSize: "20px", typeface: FONT } },
      run("客队防线伤情集中，但新援塔迪奇、莫尔具备制造威胁的能力", 20, "#1F2937"),
      { run: "\n", textStyle: { fontSize: "20px", typeface: FONT } },
      run("主场氛围近满场，主队大概率率先进球并带走净胜球", 20, "#1F2937"),
    ],
    paragraphStyle: { lineSpacingPercent: 118000 },
  };

  const footer = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 659.24, width: 1197.33, height: 25.33 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  footer.text = simple("5", 13.33, INK);
  footer.text.style = { alignment: "right", verticalAlignment: "bottom" };
  slide.speakerNotes.textFrame.setText("xG model: home 1.8 vs away 1.1 with home/away adjustment. Sources: onefootball.com.br (Olympiacos registered only El Kaabi as established striker); voetbalprimeur.nl (NEC injuries); novassports.gr (near-sellout crowd).");
}

/* ============ Slide 6: Four-factor model (custom table) ============ */
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  const title = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 36.12, width: 1197.33, height: 70 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  title.text = titleToken("四因素模型：主队 3.92 分 vs 客队 2.99 分");
  const intro = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 122, width: 1197.33, height: 50 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  intro.text = simple("评分差 0.93 分，映射为 60.5% / 23.5% / 16.0% 的胜平负概率", 22, MUTED);

  const table = slide.tables.add({
    position: { left: 41.33, top: 200, width: 1197.34, height: 430 },
    rows: 5,
    columns: 4,
    values: [
      ["因素（权重）", "奥林匹亚科斯", "NEC奈梅亨", "方向与主要证据"],
      ["球队基本面（35%）", "4.0", "2.8", "欧战系数、身价、大赛经验全面占优"],
      ["人员与临场状态（25%）", "3.6", "3.2", "主队锋线减配；客队后防伤病但进攻端有新援"],
      ["场内外环境（20%）", "3.8", "3.0", "主场近满场、高温；客队客场战绩一般"],
      ["竞赛心理（20%）", "4.2", "3.0", "主队欧战经验丰富；客队队史首次参赛"],
    ],
    columnWidths: [300, 220, 220, 457.34],
  });
  table.borders.assign({ style: "solid", fill: RULE, width: 1 });
  table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 4 }).assign({
    fill: PANEL,
    textStyle: { bold: true, fontSize: 18, typeface: FONT, color: INK },
  });
  table.cells.block({ row: 1, column: 0, rowCount: 4, columnCount: 4 }).assign({
    fill: "#FFFFFF",
    textStyle: { fontSize: 17, typeface: FONT, color: INK },
  });

  const footer = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 659.24, width: 1197.33, height: 25.33 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  footer.text = simple("6", 13.33, INK);
  footer.text.style = { alignment: "right", verticalAlignment: "bottom" };
  slide.speakerNotes.textFrame.setText("Weighting per ucl-predictor: fundamentals 35%, personnel/form 25%, environment 20%, psychology 20%. Sources: UEFA club ranking (sportal.gr); Transfermarkt/Sportime (values); FBref (home record); scores24/Goal.com (NEC away form).");
}

/* ============ Slide 7: Key factors (custom, chart + factors) ============ */
{
  const slide = presentation.slides.add();
  slide.background.fill = "#FFFFFF";
  const title = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 36.12, width: 1197.33, height: 70 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  title.text = titleToken("三个关键胜负手");

  slide.charts.add("bar", {
    position: { left: 42.91, top: 130, width: 560, height: 500 },
    categories: ["基本面", "人员状态", "场内外", "心理"],
    series: [
      { name: "奥林匹亚科斯", values: [4.0, 3.6, 3.8, 4.2], fill: ACCENT_STRONG },
      { name: "NEC奈梅亨", values: [2.8, 3.2, 3.0, 3.0], fill: ACCENT },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false },
    dataLabels: { showValue: true },
    chartFill: "#FFFFFF",
    chartLine: { style: "solid", width: 0, fill: "#FFFFFF" },
    plotAreaFill: { type: "none" },
    plotAreaLine: { style: "solid", width: 0, fill: "#FFFFFF" },
    yAxis: { visible: true, deleted: false, max: 5, majorUnit: 1, majorGridlines: { style: "solid", width: 1, fill: PANEL }, line: { style: "solid", width: 0, fill: "#FFFFFF" } },
    xAxis: { visible: true, deleted: false, line: { style: "solid", width: 1, fill: RULE } },
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 80 },
  });

  const factor1 = slide.shapes.add({
    geometry: "roundRect",
    position: { left: 658.17, top: 130, width: 580, height: 150 },
    fill: PANEL,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const t1 = slide.shapes.add({
    geometry: "textbox",
    position: { left: 688.17, top: 150, width: 520, height: 110 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  t1.text = {
    runs: [
      run("1. 经验与实力代差", 24, INK, true),
      { run: "\n", textStyle: { fontSize: "20px", typeface: FONT } },
      run("UEFA 第 29 vs 首次参赛：欧战舞台的熟练度差距，首回合客场最易被放大", 20, "#1F2937"),
    ],
    paragraphStyle: { lineSpacingPercent: 116000 },
  };

  const factor2 = slide.shapes.add({
    geometry: "roundRect",
    position: { left: 658.17, top: 306, width: 580, height: 150 },
    fill: PANEL,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const t2 = slide.shapes.add({
    geometry: "textbox",
    position: { left: 688.17, top: 326, width: 520, height: 110 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  t2.text = {
    runs: [
      run("2. 主队锋线减配 vs 客队防线伤情", 24, INK, true),
      { run: "\n", textStyle: { fontSize: "20px", typeface: FONT } },
      run("主队只剩埃尔卡比一名中锋；客队中卫桑德勒伤退，后防被迫重组", 20, "#1F2937"),
    ],
    paragraphStyle: { lineSpacingPercent: 116000 },
  };

  const factor3 = slide.shapes.add({
    geometry: "roundRect",
    position: { left: 658.17, top: 482, width: 580, height: 150 },
    fill: PANEL,
    line: { style: "solid", width: 1, fill: RULE },
    borderRadius: "rounded-xl",
  });
  const t3 = slide.shapes.add({
    geometry: "textbox",
    position: { left: 688.17, top: 502, width: 520, height: 110 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  t3.text = {
    runs: [
      run("3. 主场氛围与高温", 24, INK, true),
      { run: "\n", textStyle: { fontSize: "20px", typeface: FONT } },
      run("2.9 万+门票近满场；8 月比雷埃夫斯湿热，客队客场近 10 场仅 3 胜", 20, "#1F2937"),
    ],
    paragraphStyle: { lineSpacingPercent: 116000 },
  };

  const footer = slide.shapes.add({
    geometry: "textbox",
    position: { left: 41.33, top: 659.24, width: 1197.33, height: 25.33 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  footer.text = simple("7", 13.33, INK);
  footer.text.style = { alignment: "right", verticalAlignment: "bottom" };
  slide.speakerNotes.textFrame.setText("Chart compares the four-factor scores. Sources: sportal.gr (UEFA ranking); onefootball.com.br (striker registration); voetbalprimeur.nl (Sandler injury); novassports.gr (tickets); scoremates.com (NEC away form).");
}

/* ============ Slide 8: Close (module 26) ============ */
{
  const tokens = {
    title: simple("UCL 2026/27", 22, MUTED, true),
    title2: {
      runs: [run("2-1", 80, ACCENT_STRONG, true), run("　主队胜", 80, INK, true)],
      paragraphStyle: { lineSpacingPercent: 90000 },
    },
    title3: {
      loremIpsumDetails: simple("置信度：中 —— 方向可信，比分幅度受名单变化影响", 21, INK),
      loremIpsumDetails2: simple("关注 8/3 最终名单（Salah-Eddine 是否入队）", 21, INK),
      loremIpsumDetails3: simple("赛后回填实际比分，检验模型", 21, INK),
    },
  };
  const slide = buildSlide26(presentation, tokens);
  slide.speakerNotes.textFrame.setText("Assumptions: NEC squad value estimated from Transfermarkt positional values; Sandler/Moslih/Ouwejan injury severity per Dutch media; Taremi transfer not official. Prediction for informational purposes only, not betting advice.");
}

/* ============ Export ============ */
for (const [index, slide] of presentation.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await presentation.export({ slide, format: "png", scale: 1 });
  await writeBlob(`${stem}.png`, png);
}

const montage = await presentation.export({ format: "webp", montage: true, scale: 1 });
await writeBlob("deck-montage.webp", montage);

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save(FINAL_PPTX);
console.log("DECK_SAVED:", FINAL_PPTX);
