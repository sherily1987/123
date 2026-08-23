// project023 Web 版 PPT 生成（通用化）
// 用法: node build_ppt_web.js --parsed <parsed.json> --out <输出.pptx> --title <销售日>
const PptxGenJS = require("pptxgenjs");
const fs = require("fs");

const args = {};
process.argv.slice(2).forEach((a, i, arr) => {
  if (a.startsWith("--")) args[a.slice(2)] = arr[i + 1];
});
const data = JSON.parse(fs.readFileSync(args.parsed, "utf-8"));
const title = args.title || "";
const out = args.out;

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE";

const C = {
  bgDark: "0B3D2E", bgLight: "FFFFFF",
  green: "1B6B4A", greenDeep: "0B3D2E", gold: "E9B44C",
  red: "C0392B", ink: "1A1A1A", muted: "6B7280",
  card: "F3F6F4", line: "D8E0DA",
};
const F = { head: "Microsoft YaHei", body: "Microsoft YaHei" };

function dirColor(d) {
  if (d === "主胜") return C.green;
  if (d === "平局") return C.gold;
  return C.red;
}
const topEvOf = r => {
  const evs = r.evs || {};
  const keys = Object.keys(evs);
  if (!keys.length) return null;
  return keys.reduce((a, b) => Math.abs(evs[a]) > Math.abs(evs[b]) ? a : b);
};
// New records carry an explicit single_pick action.  Keep a compatibility
// fallback for older parsed files, but never treat a positive EV alone as a
// bettable pick.
const isBettable = r => r.sp_bettable === true ||
  (r.sp_bettable == null && r.ev_action === "bet" && !r.sp_skip);

const nH = data.filter(r => r.dir === "主胜").length;
const nBet = data.filter(isBettable).length;
const nCollapse = data.filter(r => (r.collapse_flags || []).length).length;
const nGap = data.filter(r => r.evidence_gap).length;
const posEv = data.filter(r => { const t = topEvOf(r); return t && r.evs[t] > 0 && isBettable(r); })
  .sort((a, b) => b.evs[topEvOf(b)] - a.evs[topEvOf(a)]);

// Slide 1 封面
let s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("FOOTBALL PREDICTION", { x: 0.6, y: 1.0, w: 12, h: 0.6, fontFace: F.head, fontSize: 16, color: C.gold, charSpacing: 6, bold: true });
s.addText("LLM 证据轨 · 开售全量预测", { x: 0.6, y: 1.7, w: 12, h: 1.2, fontFace: F.head, fontSize: 44, color: "FFFFFF", bold: true });
s.addText(title + " 竞彩销售日", { x: 0.6, y: 2.9, w: 12, h: 0.6, fontFace: F.head, fontSize: 24, color: "FFFFFF" });
s.addText("胜平负 · 精确比分 · 大小球 · 半全场 · 由预测工作台生成", { x: 0.6, y: 3.6, w: 12, h: 0.5, fontFace: F.body, fontSize: 14, color: "BFD8CF" });
const stats = [
  [String(data.length), "全量可建模场次"],
  ["3", "模型投票池"],
  [String(nBet), "下注建议场次"],
];
stats.forEach((st, i) => {
  const x = 0.6 + i * 4.1;
  s.addText(st[0], { x, y: 4.9, w: 3.5, h: 1.0, fontFace: F.head, fontSize: 54, color: C.gold, bold: true });
  s.addText(st[1], { x, y: 5.95, w: 3.5, h: 0.5, fontFace: F.body, fontSize: 13, color: "BFD8CF" });
});
s.addText("模型池：glm-4-flash · deepseek-chat · doubao-seed-evolving", { x: 0.6, y: 6.7, w: 12, h: 0.4, fontFace: F.body, fontSize: 12, color: "8FB0A0" });

// Slide 2 概览
s = pptx.addSlide();
s.background = { color: C.bgLight };
s.addText("OVERVIEW", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
s.addText("赛前预测概览", { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });
const ov = [
  [data.length + " 场", "全量场次", "证据门禁 + 3 模型投票聚合"],
  [nH + " / " + data.length, "综合方向为主胜", Math.round(nH / Math.max(data.length, 1) * 100) + "%"],
  [String(nBet), "下注建议", "证据缺口风控拦截其余"],
  [String(nCollapse), "坍缩标记场次", "比分/大小球动态检测"],
];
ov.forEach((o, i) => {
  const col = i % 2, row = Math.floor(i / 2);
  const x = 0.6 + col * 6.2, y = 1.9 + row * 2.5;
  s.addShape("roundRect", { x, y, w: 5.8, h: 2.1, fill: { color: C.card }, line: { color: C.line, width: 1 }, rectRadius: 0.1 });
  s.addText(o[0], { x: x + 0.35, y: y + 0.25, w: 3, h: 0.9, fontFace: F.head, fontSize: 36, color: C.green, bold: true });
  s.addText(o[1], { x: x + 0.35, y: y + 1.2, w: 5, h: 0.45, fontFace: F.body, fontSize: 15, color: C.ink, bold: true });
  s.addText(o[2], { x: x + 0.35, y: y + 1.65, w: 5, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });
});
s.addText(`${nGap}/${data.length} 场含证据缺口标记（轻量证据口径，官方首发未公布）。`, { x: 0.6, y: 7.0, w: 12, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });

// 总表 ×N 页
function tableSlide(label, slice) {
  s = pptx.addSlide();
  s.background = { color: C.bgLight };
  s.addText("PREDICTIONS", { x: 0.6, y: 0.3, w: 6, h: 0.45, fontFace: F.head, fontSize: 15, color: C.green, bold: true, charSpacing: 4 });
  s.addText(label, { x: 0.6, y: 0.72, w: 12, h: 0.6, fontFace: F.head, fontSize: 26, color: C.ink, bold: true });
  const rows = [
    [{ text: "场次", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "比赛", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "联赛", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "方向", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "强度", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "下注建议", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "比分", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "大小球", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
     { text: "EV", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } }],
  ];
  slice.forEach(r => {
    const t = topEvOf(r);
    const evTxt = t === null ? "-" : (r.evs[t] > 0 ? "+" : "") + Math.round(r.evs[t] * 100) + "%";
    const evColor = t === null ? C.muted : (r.evs[t] > 0 ? C.green : C.red);
    const spMark = r.sp !== r.dir ? " ←改判" : "";
    const gapMark = r.evidence_gap ? " ⚠" : "";
    rows.push([
      { text: r.num, options: { color: C.muted, fontSize: 9 } },
      { text: r.home + " vs " + r.away, options: { color: C.ink, fontSize: 10 } },
      { text: r.league || "", options: { color: C.muted, fontSize: 9 } },
      { text: r.dir, options: { color: dirColor(r.dir), bold: true, fontSize: 10 } },
      { text: r.strength + "%", options: { color: C.ink, fontSize: 9 } },
      { text: (r.sp || "-") + spMark + gapMark, options: { color: isBettable(r) ? C.greenDeep : C.muted, bold: true, fontSize: 10 } },
      { text: r.score || "-", options: { color: C.ink, fontSize: 10 } },
      { text: r.ou25 || "-", options: { color: C.ink, fontSize: 9 } },
      { text: evTxt, options: { color: evColor, bold: true, fontSize: 9 } },
    ]);
  });
  s.addTable(rows, { x: 0.35, y: 1.45, w: 12.6, colW: [1.0, 2.9, 0.9, 0.85, 0.8, 1.75, 0.85, 0.95, 0.85], border: { type: "solid", color: C.line, pt: 0.5 }, fontFace: F.body, rowH: 0.215, valign: "middle", align: "center", margin: 0.01 });
  s.addText("下注建议 = 决策层从投票+EV 推出的主推方向；「←改判」=与综合方向不同；⚠=证据缺口。", { x: 0.35, y: 7.0, w: 12.5, h: 0.35, fontFace: F.body, fontSize: 10, color: C.muted });
}
const perTable = 24;
for (let i = 0; i < data.length; i += perTable) {
  tableSlide(`预测总表（${i + 1}-${Math.min(i + perTable, data.length)}）`, data.slice(i, i + perTable));
}

// 下注推荐
s = pptx.addSlide();
s.background = { color: C.bgLight };
s.addText("BETTING PICKS", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
s.addText("正 EV 下注推荐（Top 8）", { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });
if (!posEv.length) {
  s.addText("🚫 全部场次被证据缺口风控拦截，无正 EV 下注推荐。", { x: 0.6, y: 2.2, w: 12, h: 0.6, fontFace: F.body, fontSize: 16, color: C.red, bold: true });
} else {
  const medals = ["🥇", "🥈", "🥉", "4", "5", "6", "7", "8"];
  posEv.slice(0, 8).forEach((r, i) => {
    const t = topEvOf(r);
    const y = 2.05 + i * 0.6;
    s.addShape("roundRect", { x: 0.6, y, w: 12.1, h: 0.52, fill: { color: i < 3 ? "FFF7E6" : C.card }, line: { color: C.line, width: 0.75 }, rectRadius: 0.05 });
    s.addText(medals[i], { x: 0.75, y, w: 0.6, h: 0.52, fontFace: F.body, fontSize: 16, color: C.gold, align: "center", valign: "middle" });
    s.addText(r.num, { x: 1.45, y, w: 1.1, h: 0.52, fontFace: F.body, fontSize: 11, color: C.muted, valign: "middle" });
    s.addText(r.home + " vs " + r.away, { x: 2.55, y, w: 3.6, h: 0.52, fontFace: F.body, fontSize: 13, color: C.ink, bold: true, valign: "middle" });
    s.addText(r.sp || "-", { x: 6.2, y, w: 1.3, h: 0.52, fontFace: F.body, fontSize: 14, color: dirColor(r.sp), bold: true, valign: "middle" });
    s.addText("+" + Math.round(r.evs[t] * 100) + "%", { x: 7.55, y, w: 1.0, h: 0.52, fontFace: F.head, fontSize: 15, color: C.green, bold: true, valign: "middle" });
    s.addText((r.ev_reason || "").slice(0, 60), { x: 8.6, y, w: 3.9, h: 0.52, fontFace: F.body, fontSize: 9.5, color: C.muted, valign: "middle" });
  });
}
s.addText("注：EV 基于 3 模型投票聚合概率 × 体彩官方赔率。", { x: 0.6, y: 7.0, w: 12, h: 0.4, fontFace: F.body, fontSize: 10, color: C.muted });

// 逐场卡片（每页 6 场）
const perPage = 6;
for (let pg = 0; pg < Math.ceil(data.length / perPage); pg++) {
  s = pptx.addSlide();
  s.background = { color: C.bgLight };
  s.addText("MATCH DETAILS", { x: 0.6, y: 0.28, w: 6, h: 0.42, fontFace: F.head, fontSize: 14, color: C.green, bold: true, charSpacing: 4 });
  const start = pg * perPage, end = Math.min(start + perPage, data.length);
  s.addText(`逐场预测 · ${start + 1}—${end}`, { x: 0.6, y: 0.68, w: 12, h: 0.6, fontFace: F.head, fontSize: 26, color: C.ink, bold: true });
  data.slice(start, end).forEach((r, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.55 + col * 6.35, y = 1.45 + row * 1.95;
    const t = topEvOf(r);
    const evTxt = t === null ? "EV -" : "EV " + (r.evs[t] > 0 ? "+" : "") + Math.round(r.evs[t] * 100) + "%";
    const evColor = t === null ? C.muted : (r.evs[t] > 0 ? C.green : C.red);
    s.addShape("roundRect", { x, y, w: 6.1, h: 1.8, fill: { color: C.card }, line: { color: C.line, width: 0.75 }, rectRadius: 0.07 });
    s.addText(r.num + " " + (r.league || ""), { x: x + 0.18, y: y + 0.08, w: 3.4, h: 0.35, fontFace: F.body, fontSize: 10, color: C.muted });
    s.addText(r.home + "  vs  " + r.away, { x: x + 0.18, y: y + 0.38, w: 4.0, h: 0.5, fontFace: F.head, fontSize: 15, color: C.ink, bold: true });
    const gapMark = r.evidence_gap ? " ⚠缺口" : "";
    s.addText(r.sp || "-", { x: x + 0.18, y: y + 0.95, w: 1.5, h: 0.45, fontFace: F.head, fontSize: 17, color: isBettable(r) ? dirColor(r.sp) : C.muted, bold: true });
    s.addText("强度 " + r.strength + "%" + gapMark, { x: x + 0.18, y: y + 1.42, w: 2.6, h: 0.35, fontFace: F.body, fontSize: 9.5, color: C.muted });
    s.addText(r.dir + (r.dir !== r.sp && r.sp ? "→改判" : ""), { x: x + 2.35, y: y + 0.98, w: 1.6, h: 0.4, fontFace: F.body, fontSize: 11, color: dirColor(r.dir) });
    s.addText(r.score || "-", { x: x + 4.15, y: y + 0.42, w: 1.0, h: 0.45, fontFace: F.head, fontSize: 16, color: C.ink, bold: true });
    s.addText(r.ou25 || "", { x: x + 4.15, y: y + 0.9, w: 1.3, h: 0.4, fontFace: F.body, fontSize: 10, color: C.muted });
    s.addText(evTxt, { x: x + 4.15, y: y + 1.3, w: 1.75, h: 0.4, fontFace: F.head, fontSize: 12, color: evColor, bold: true });
  });
}

// 风险页
s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("RISK ALERTS", { x: 0.6, y: 0.4, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.gold, bold: true, charSpacing: 4 });
s.addText("本轮必须警惕的风险", { x: 0.6, y: 0.95, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: "FFFFFF", bold: true });
const scores = {};
data.forEach(r => { const sc = r.score || "?"; scores[sc] = (scores[sc] || 0) + 1; });
const topScore = Object.entries(scores).sort((a, b) => b[1] - a[1])[0] || ["?", 0];
const risks = [
  ["赛季初主胜偏见", nH + " / " + data.length, "历史教训：赛季初（揭幕轮+第2轮）主队优势未显现，主胜偏多必亏。08-14 回测主胜之夜反主胜改造反而压低命中。"],
  ["比分坍缩检测", topScore[0] + " ×" + topScore[1], "上轮坍缩 1-0（71%）→ 2-0（64%）。本轮动态阈值检测已标记场次，比分偏好只做参考不可用于下注。"],
  ["轻量证据口径", nGap + " / " + data.length, "一键预测未做伤停新闻深度搜索，证据含缺口 → EV 风控偏保守。深度证据可上传后重跑。"],
];
risks.forEach((r, i) => {
  const y = 1.85 + i * 1.75;
  s.addShape("roundRect", { x: 0.6, y, w: 12.1, h: 1.55, fill: { color: "124A38" }, line: { color: "1F6B4F", width: 1 }, rectRadius: 0.08 });
  s.addText(r[0], { x: 0.9, y: y + 0.15, w: 7, h: 0.45, fontFace: F.head, fontSize: 18, color: "FFFFFF", bold: true });
  s.addText(r[1], { x: 9.0, y: y + 0.1, w: 3.4, h: 0.6, fontFace: F.head, fontSize: 24, color: C.gold, bold: true, align: "right" });
  s.addText(r[2], { x: 0.9, y: y + 0.68, w: 11.3, h: 0.8, fontFace: F.body, fontSize: 12, color: "BFD8CF" });
});
s.addText("对策：主胜比例熔断 + 平局双选例外 + 证据缺口强制不下注。", { x: 0.6, y: 7.05, w: 12, h: 0.4, fontFace: F.body, fontSize: 12, color: C.gold, bold: true });

// 结论页
s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("NEXT STEP", { x: 0.6, y: 0.6, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.gold, bold: true, charSpacing: 4 });
s.addText("冻结赛前样本，赛后回测", { x: 0.6, y: 1.25, w: 12, h: 0.8, fontFace: F.head, fontSize: 34, color: "FFFFFF", bold: true });
const next = [
  ["1", "全部场次开球后，在工作台点「③ 回测赛果」自动结算"],
  ["2", "验证：主胜比例与赛季初陷阱是否再次兑现"],
  ["3", "验证：坍缩标记场次的比分命中率（动态阈值有效性）"],
  ["4", "对比：轻量证据口径 vs 深度证据口径的命中差异"],
];
next.forEach((n, i) => {
  const y = 2.5 + i * 1.0;
  s.addText(n[0], { x: 0.9, y, w: 0.9, h: 0.7, fontFace: F.head, fontSize: 30, color: C.gold, bold: true });
  s.addText(n[1], { x: 2.0, y: y + 0.12, w: 10.5, h: 0.6, fontFace: F.body, fontSize: 17, color: "FFFFFF" });
});
s.addText("小样本只用于积累与核验；达到样本门槛前，不把结果表述为模型优势。", { x: 0.6, y: 6.7, w: 12, h: 0.5, fontFace: F.body, fontSize: 12, color: "8FB0A0", italic: true });

pptx.writeFile({ fileName: out }).then(() => {
  console.log("已生成:", out);
});
