// 生成 2026-08-14 开售预测 PPT（LLM 证据轨 14 场）
const PptxGenJS = require("pptxgenjs");
const fs = require("fs");

const data = JSON.parse(fs.readFileSync("C:/Users/Administrator/football-llm-predictor/data/parsed_2026-08-14.json", "utf-8"));

const pptx = new PptxGenJS();
pptx.layout = "LAYOUT_WIDE"; // 13.3 x 7.5

// 配色：深绿球场主题
const C = {
  bgDark: "0B3D2E",     // 深绿（封面/结论）
  bgLight: "FFFFFF",
  green: "1B6B4A",      // 主绿
  greenDeep: "0B3D2E",
  gold: "E9B44C",       // 金色强调（正EV/推荐）
  red: "C0392B",        // 风险/负EV
  ink: "1A1A1A",        // 正文
  muted: "6B7280",      // 弱化文字
  card: "F3F6F4",       // 卡片底
  line: "D8E0DA",       // 分隔线
};
const F = { head: "Microsoft YaHei", body: "Microsoft YaHei" };

// 工具：方向 → 颜色
function dirColor(d) {
  if (d === "主胜") return C.green;
  if (d === "平局") return C.gold;
  return C.red;
}

// ============ Slide 1 封面 ============
let s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("FOOTBALL PREDICTION", { x: 0.6, y: 1.0, w: 12, h: 0.6, fontFace: F.head, fontSize: 16, color: C.gold, charSpacing: 6, bold: true });
s.addText("LLM 证据轨 · 开售全量预测", { x: 0.6, y: 1.7, w: 12, h: 1.2, fontFace: F.head, fontSize: 44, color: "FFFFFF", bold: true });
s.addText("2026-08-14 竞彩销售日", { x: 0.6, y: 2.9, w: 12, h: 0.6, fontFace: F.head, fontSize: 24, color: "FFFFFF" });
s.addText("胜平负 · 精确比分 · 大小球 · 半全场", { x: 0.6, y: 3.6, w: 12, h: 0.5, fontFace: F.body, fontSize: 14, color: "BFD8CF" });
// 三个关键数字
const stats = [
  ["14", "可建模场次"],
  ["3", "模型投票池"],
  ["71%", "1-0 比分坍缩预警"],
];
stats.forEach((st, i) => {
  const x = 0.6 + i * 4.1;
  s.addText(st[0], { x, y: 4.9, w: 3.5, h: 1.0, fontFace: F.head, fontSize: 54, color: C.gold, bold: true });
  s.addText(st[1], { x, y: 5.95, w: 3.5, h: 0.5, fontFace: F.body, fontSize: 13, color: "BFD8CF" });
});
s.addText("模型池：glm-4-flash(0.3) · deepseek-chat(1.2) · doubao(0.9)", { x: 0.6, y: 6.7, w: 12, h: 0.4, fontFace: F.body, fontSize: 12, color: "8FB0A0" });

// ============ Slide 2 概览 ============
s = pptx.addSlide();
s.background = { color: C.bgLight };
s.addText("OVERVIEW", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
s.addText("赛前预测概览", { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });

const ov = [
  ["14 / 15", "有赔率可预测场次", "1 场（周五009 利雅新月）无赔率跳过"],
  ["11 / 14", "综合方向为主胜", "赛季初主胜偏见预警（79%）"],
  ["4", "决策层改判场次", "主胜→平局（EV 修正）"],
  ["0", "正式下注推荐", "14 场全部证据缺口风控拦截"],
];
ov.forEach((o, i) => {
  const col = i % 2, row = Math.floor(i / 2);
  const x = 0.6 + col * 6.2, y = 1.9 + row * 2.5;
  s.addShape("roundRect", { x, y, w: 5.8, h: 2.1, fill: { color: C.card }, line: { color: C.line, width: 1 }, rectRadius: 0.1 });
  s.addText(o[0], { x: x + 0.35, y: y + 0.25, w: 3, h: 0.9, fontFace: F.head, fontSize: 36, color: C.green, bold: true });
  s.addText(o[1], { x: x + 0.35, y: y + 1.2, w: 5, h: 0.45, fontFace: F.body, fontSize: 15, color: C.ink, bold: true });
  s.addText(o[2], { x: x + 0.35, y: y + 1.65, w: 5, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });
});
s.addText("本页数据截至 2026-08-14 13:20，赛前冻结。全部场次官方首发未公布，证据含缺口标记。", { x: 0.6, y: 7.0, w: 12, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });

// ============ Slide 3 预测总表 ============
s = pptx.addSlide();
s.background = { color: C.bgLight };
s.addText("PREDICTIONS", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
s.addText("14 场预测总表", { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });

const rows = [
  [{ text: "场次", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "比赛", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "联赛", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "方向", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "强度", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "单选主推", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "比分", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } },
   { text: "EV", options: { bold: true, color: "FFFFFF", fill: { color: C.greenDeep } } }],
];
const leagues = { "周五003":"德乙","周五004":"德乙","周五005":"沙职","周五006":"瑞超","周五007":"挪超","周五008":"沙职","周五010":"荷甲","周五011":"荷乙","周五012":"荷乙","周五013":"法乙","周五014":"法乙","周五015":"法乙","周五016":"英冠","周五017":"葡超" };
data.forEach(r => {
  const topEv = r.evs && Object.keys(r.evs).length ? Object.values(r.evs).reduce((a,b)=>Math.abs(a)>Math.abs(b)?a:b,0) : null;
  const evTxt = topEv === null ? "-" : (topEv > 0 ? "+" : "") + Math.round(topEv*100) + "%";
  const evColor = topEv === null ? C.muted : (topEv > 0 ? C.green : C.red);
  const spMark = r.sp !== r.dir ? " ←改判" : "";
  rows.push([
    { text: r.num, options: { color: C.muted, fontSize: 10 } },
    { text: r.home + " vs " + r.away, options: { color: C.ink, fontSize: 11 } },
    { text: leagues[r.num] || "", options: { color: C.muted, fontSize: 10 } },
    { text: r.dir, options: { color: dirColor(r.dir), bold: true, fontSize: 11 } },
    { text: r.strength + "%", options: { color: C.ink, fontSize: 10 } },
    { text: r.sp + spMark, options: { color: C.greenDeep, bold: true, fontSize: 11 } },
    { text: r.score, options: { color: C.ink, fontSize: 11 } },
    { text: evTxt, options: { color: evColor, bold: true, fontSize: 10 } },
  ]);
});
s.addTable(rows, { x: 0.5, y: 1.7, w: 12.3, colW: [1.0, 3.3, 1.0, 0.9, 0.9, 1.6, 0.9, 0.9], border: { type: "solid", color: C.line, pt: 0.5 }, fontFace: F.body, rowH: 0.32, valign: "middle", align: "center", margin: 0.02 });
s.addText("单选主推 = 决策层从双选里挑的主推方向（EV 差 + 投票差 + 次回合战意加权）。「←改判」表示与综合方向不同。", { x: 0.5, y: 6.9, w: 12, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });

// ============ Slide 4 下注推荐（正EV） ============
s = pptx.addSlide();
s.background = { color: C.bgLight };
s.addText("BETTING PICKS", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
s.addText("正 EV 下注推荐（Top 6）", { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });
s.addText("⚠️ 系统 14 场全部「不下注」（官方首发未公布 → 证据缺口风控）。以下按 EV 排序，仅供参考。", { x: 0.6, y: 1.6, w: 12, h: 0.5, fontFace: F.body, fontSize: 13, color: C.red, bold: true });

const picks = [
  ["🥇", "周五006", "埃夫斯堡 vs 韦斯特罗", "平局", "+67%", "主胜1.65大热但EV-31%，瑞超主队被高估"],
  ["🥈", "周五010", "特尔斯达 vs 鹿斯巴达", "主胜", "+46%", "强度70%，荷甲第2轮"],
  ["🥉", "周五008", "达曼协定 vs 利雅得", "主胜", "+29%", "强度70%，沙职揭幕"],
  ["4", "周五011", "瓦尔韦克 vs 多德勒支", "主胜", "+23%", "强度70%，荷乙"],
  ["5", "周五005", "新未来SC vs 迈季宽广", "主胜", "+20%", "强度70%，沙职揭幕"],
  ["6", "周五003", "基尔 vs 圣保利", "平局", "+55%", "德乙北部德比，近均势"],
];
picks.forEach((p, i) => {
  const y = 2.2 + i * 0.82;
  s.addShape("roundRect", { x: 0.6, y, w: 12.1, h: 0.7, fill: { color: i < 3 ? "FFF7E6" : C.card }, line: { color: C.line, width: 0.75 }, rectRadius: 0.06 });
  s.addText(p[0], { x: 0.75, y, w: 0.8, h: 0.7, fontFace: F.body, fontSize: 20, color: C.gold, align: "center", valign: "middle" });
  s.addText(p[1], { x: 1.6, y: y + 0.12, w: 1.3, h: 0.5, fontFace: F.body, fontSize: 12, color: C.muted });
  s.addText(p[2], { x: 2.9, y, w: 3.6, h: 0.7, fontFace: F.body, fontSize: 15, color: C.ink, bold: true, valign: "middle" });
  s.addText(p[3], { x: 6.5, y, w: 1.2, h: 0.7, fontFace: F.body, fontSize: 15, color: dirColor(p[3]), bold: true, valign: "middle" });
  s.addText(p[4], { x: 7.7, y, w: 1.1, h: 0.7, fontFace: F.head, fontSize: 16, color: C.green, bold: true, valign: "middle" });
  s.addText(p[5], { x: 8.9, y, w: 3.7, h: 0.7, fontFace: F.body, fontSize: 11, color: C.muted, valign: "middle" });
});

// ============ Slide 5 风险提示 ============
s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("RISK ALERTS", { x: 0.6, y: 0.4, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.gold, bold: true, charSpacing: 4 });
s.addText("两个必须警惕的坍缩信号", { x: 0.6, y: 0.95, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: "FFFFFF", bold: true });

const risks = [
  ["比分坍缩换形态", "10 / 14 = 71%", "上轮是「2-1坍缩」，反坍缩规则把 2-1 压下后，模型转向 1-0。反坍缩没根治问题，只是挪了位置。"],
  ["主胜占比 79% 过高", "11 / 14", "赛季初（德乙/荷甲/法乙/英冠/葡超全揭幕或第2轮）主队优势未显现，正是 08-05 回测栽过的坑。"],
];
risks.forEach((r, i) => {
  const y = 1.95 + i * 2.3;
  s.addShape("roundRect", { x: 0.6, y, w: 12.1, h: 2.0, fill: { color: "124A38" }, line: { color: "1F6B4F", width: 1 }, rectRadius: 0.1 });
  s.addText(r[0], { x: 0.9, y: y + 0.2, w: 7, h: 0.5, fontFace: F.head, fontSize: 20, color: "FFFFFF", bold: true });
  s.addText(r[1], { x: 9.0, y: y + 0.15, w: 3.4, h: 0.7, fontFace: F.head, fontSize: 30, color: C.gold, bold: true, align: "right" });
  s.addText(r[2], { x: 0.9, y: y + 0.85, w: 11.3, h: 1.0, fontFace: F.body, fontSize: 14, color: "BFD8CF" });
});
s.addText("对策（下轮）：主胜比例熔断 + 1-0 反坍缩规则。", { x: 0.6, y: 6.7, w: 12, h: 0.4, fontFace: F.body, fontSize: 13, color: C.gold, bold: true });

// ============ Slide 6-10 逐场详情（每页3场） ============
const leagueInfo = {
  "周五003": ["德乙", "基尔 vs 圣保利"],
  "周五004": ["德乙", "不伦瑞克 vs 波鸿"],
  "周五005": ["沙职", "新未来SC vs 迈季宽广"],
  "周五006": ["瑞超", "埃夫斯堡 vs 韦斯特罗"],
  "周五007": ["挪超", "罗森博格 vs 维京"],
  "周五008": ["沙职", "达曼协定 vs 利雅得"],
  "周五010": ["荷甲", "特尔斯达 vs 鹿斯巴达"],
  "周五011": ["荷乙", "瓦尔韦克 vs 多德勒支"],
  "周五012": ["荷乙", "赫拉克勒 vs 登博思"],
  "周五013": ["法乙", "阿纳西 vs 罗德兹"],
  "周五014": ["法乙", "兰斯 vs 敦刻尔克"],
  "周五015": ["法乙", "圣埃蒂安 vs 克莱蒙"],
  "周五016": ["英冠", "伍尔弗 vs 布莱克本"],
  "周五017": ["葡超", "里斯本 vs 吉马良斯"],
};
const perPage = 3;
for (let pg = 0; pg < Math.ceil(data.length / perPage); pg++) {
  s = pptx.addSlide();
  s.background = { color: C.bgLight };
  s.addText("MATCH DETAILS", { x: 0.6, y: 0.35, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.green, bold: true, charSpacing: 4 });
  const start = pg * perPage, end = Math.min(start + perPage, data.length);
  s.addText(`逐场预测 · ${start + 1}—${end}`, { x: 0.6, y: 0.85, w: 12, h: 0.7, fontFace: F.head, fontSize: 30, color: C.ink, bold: true });
  const slice = data.slice(start, end);
  slice.forEach((r, i) => {
    const y = 1.75 + i * 1.85;
    const topEv = r.evs && Object.keys(r.evs).length ? Object.values(r.evs).reduce((a,b)=>Math.abs(a)>Math.abs(b)?a:b,0) : null;
    const evTxt = topEv === null ? "EV -" : "EV " + (topEv > 0 ? "+" : "") + Math.round(topEv*100) + "%";
    const evColor = topEv === null ? C.muted : (topEv > 0 ? C.green : C.red);
    // 卡片
    s.addShape("roundRect", { x: 0.6, y, w: 12.1, h: 1.7, fill: { color: C.card }, line: { color: C.line, width: 0.75 }, rectRadius: 0.08 });
    // 左：场次+队名
    s.addText(r.num, { x: 0.85, y: y + 0.15, w: 1.4, h: 0.45, fontFace: F.body, fontSize: 11, color: C.muted });
    s.addText(r.home + "  vs  " + r.away, { x: 0.85, y: y + 0.55, w: 3.3, h: 0.6, fontFace: F.head, fontSize: 18, color: C.ink, bold: true });
    s.addText(leagueInfo[r.num] ? leagueInfo[r.num][0] : "", { x: 0.85, y: y + 1.2, w: 2, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });
    // 中：方向+强度
    s.addText(r.dir, { x: 4.6, y: y + 0.3, w: 1.6, h: 0.7, fontFace: F.head, fontSize: 26, color: dirColor(r.dir), bold: true });
    s.addText("强度 " + r.strength + "%", { x: 4.6, y: y + 1.15, w: 1.8, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });
    // 中右：单选主推
    s.addText("单选主推", { x: 6.7, y: y + 0.2, w: 2.2, h: 0.4, fontFace: F.body, fontSize: 10, color: C.muted });
    s.addText(r.sp + (r.sp !== r.dir ? " ⚠️改判" : ""), { x: 6.7, y: y + 0.55, w: 2.4, h: 0.6, fontFace: F.head, fontSize: 18, color: C.greenDeep, bold: true });
    s.addText("信心 " + r.sp_conf + "%", { x: 6.7, y: y + 1.2, w: 2, h: 0.4, fontFace: F.body, fontSize: 11, color: C.muted });
    // 右：比分 + EV
    s.addText("比分", { x: 9.4, y: y + 0.2, w: 1.4, h: 0.4, fontFace: F.body, fontSize: 10, color: C.muted });
    s.addText(r.score, { x: 9.4, y: y + 0.55, w: 1.4, h: 0.6, fontFace: F.head, fontSize: 20, color: C.ink, bold: true });
    s.addText(evTxt, { x: 10.9, y: y + 0.5, w: 1.7, h: 0.7, fontFace: F.head, fontSize: 16, color: evColor, bold: true, align: "right" });
  });
}

// ============ 结论页 ============
s = pptx.addSlide();
s.background = { color: C.bgDark };
s.addText("NEXT STEP", { x: 0.6, y: 0.6, w: 6, h: 0.5, fontFace: F.head, fontSize: 16, color: C.gold, bold: true, charSpacing: 4 });
s.addText("冻结赛前样本，赛后回测", { x: 0.6, y: 1.25, w: 12, h: 0.8, fontFace: F.head, fontSize: 34, color: "FFFFFF", bold: true });
const next = [
  ["1", "14 场开球后采官方 90 分钟赛果回测"],
  ["2", "验证：主胜 79% 偏见是否兑现（赛季初陷阱）"],
  ["3", "验证：1-0 坍缩（71%）的比分命中率"],
  ["4", "验证：单选主推决策层在联赛场景的实战命中"],
];
next.forEach((n, i) => {
  const y = 2.5 + i * 1.0;
  s.addText(n[0], { x: 0.9, y, w: 0.9, h: 0.7, fontFace: F.head, fontSize: 30, color: C.gold, bold: true });
  s.addText(n[1], { x: 2.0, y: y + 0.12, w: 10.5, h: 0.6, fontFace: F.body, fontSize: 18, color: "FFFFFF" });
});
s.addText("小样本只用于积累与核验；达到样本门槛前，不把结果表述为模型优势。", { x: 0.6, y: 6.7, w: 12, h: 0.5, fontFace: F.body, fontSize: 12, color: "8FB0A0", italic: true });

const out = "F:/HM足球比赛预测/project001_足球预测/05_交付/2026-08-14_开售预测/LLM证据轨预测_20260814销售日.pptx";
pptx.writeFile({ fileName: out }).then(() => {
  console.log("已生成:", out);
});
