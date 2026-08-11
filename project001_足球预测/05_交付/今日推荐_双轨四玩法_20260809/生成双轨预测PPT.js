const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const compare = JSON.parse(fs.readFileSync(path.join(ROOT, 'dual_track_4markets.json'), 'utf8'));
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Hermes Agent';
pptx.subject = '2026-08-09竞彩销售日双轨预测';
pptx.title = '双轨预测｜2026-08-09销售日';
pptx.company = '足球预测项目';
pptx.lang = 'zh-CN';
pptx.theme = {
  headFontFace: 'Arial', bodyFontFace: 'Arial', lang: 'zh-CN'
};
pptx.defineSlideMaster({
  title: 'MASTER',
  background: { color: '0B1220' },
  objects: [
    { text: { text: '双轨预测 · 2026-08-09销售日', options: { x: 0.55, y: 7.12, w: 5.5, h: 0.18, fontFace: 'Arial', fontSize: 8, color: '7F8EA3', margin: 0 } } },
    { text: { text: '概率模型输出，非投注建议', options: { x: 9.7, y: 7.12, w: 3.05, h: 0.18, fontFace: 'Arial', fontSize: 8, color: '7F8EA3', align: 'right', margin: 0 } } }
  ],
  slideNumber: { x: 12.85, y: 7.1, color: '7F8EA3', fontFace: 'Arial', fontSize: 8 }
});

const C = { bg: '0B1220', panel: '141F31', panel2: '19283D', text: 'F4F7FB', muted: 'AAB7C8', cyan: '4DD0E1', lime: 'A7E163', amber: 'FFC857', coral: 'FF7B72', purple: 'B39DDB', line: '2B3B52' };
const shadow = () => ({ type: 'outer', color: '000000', blur: 2, angle: 45, distance: 1, opacity: 0.22 });
function tx(slide, text, x, y, w, h, opts={}) {
  slide.addText(String(text ?? ''), { x, y, w, h, fontFace: 'Arial', color: C.text, margin: 0.04, fit: 'shrink', breakLine: false, ...opts });
}
function pill(slide, text, x, y, w, color, fill=C.panel2) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h: 0.28, rectRadius: 0.08, fill: { color: fill }, line: { color: fill } });
  tx(slide, text, x, y+0.045, w, 0.16, { fontSize: 9, bold: true, color, align: 'center' });
}
function title(slide, kicker, heading, sub='') {
  tx(slide, kicker.toUpperCase(), 0.62, 0.46, 5.8, 0.22, { fontSize: 10, bold: true, color: C.cyan, charSpacing: 1.2 });
  tx(slide, heading, 0.6, 0.78, 11.8, 0.52, { fontSize: 27, bold: true });
  if (sub) tx(slide, sub, 0.62, 1.38, 11.7, 0.28, { fontSize: 11, color: C.muted });
}
function stat(slide, x, y, value, label, accent) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w: 2.7, h: 1.18, rectRadius: 0.08, fill: { color: C.panel }, line: { color: C.line, width: 1 }, shadow: shadow() });
  slide.addShape(pptx.ShapeType.ellipse, { x: x+0.18, y: y+0.18, w: 0.16, h: 0.16, fill: { color: accent }, line: { color: accent } });
  tx(slide, value, x+0.18, y+0.42, 2.3, 0.34, { fontSize: 25, bold: true, color: accent });
  tx(slide, label, x+0.18, y+0.83, 2.35, 0.18, { fontSize: 10, color: C.muted });
}
function matchCard(slide, r, x, y, w, h) {
  slide.addShape(pptx.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: C.panel }, line: { color: C.line, width: 1 }, shadow: shadow() });
  const q = r.quant || {}, l = r.llm || {};
  tx(slide, r.match_num || '', x+0.25, y+0.2, 0.75, 0.22, { fontSize: 10, bold: true, color: C.cyan });
  tx(slide, `${r.home}  vs  ${r.away}`, x+1.05, y+0.18, w-1.3, 0.26, { fontSize: 14, bold: true });
  tx(slide, `${r.league || ''} · ${String(r.kickoff || '').replace('T', ' ').slice(0,16)}`, x+1.05, y+0.49, w-1.3, 0.18, { fontSize: 9, color: C.muted });
  slide.addShape(pptx.ShapeType.line, { x: x+0.25, y: y+0.82, w: w-0.5, h: 0, line: { color: C.line, width: 1 } });
  pill(slide, '量化轨', x+0.25, y+1.02, 0.78, C.cyan);
  tx(slide, `胜平负  ${q.direction || '—'}`, x+1.2, y+1.03, 1.58, 0.2, { fontSize: 11, bold: true });
  const qp = (q.prob_pct || []).map(v => `${Number(v).toFixed(1)}%`).join(' / ');
  tx(slide, qp ? `主/平/客 ${qp}` : '', x+1.2, y+1.29, 2.8, 0.18, { fontSize: 8.5, color: C.muted });
  tx(slide, `比分Top1  ${q.score || '—'}`, x+0.25, y+1.67, 2.2, 0.22, { fontSize: 11, color: C.text });
  tx(slide, `半全场  ${q.hafu || '—'}`, x+2.55, y+1.67, 1.5, 0.22, { fontSize: 11, color: C.text });
  pill(slide, 'LLM轨', x+0.25, y+2.03, 0.78, C.lime, '20352A');
  tx(slide, `胜平负  ${l['1x2'] || '—'}`, x+1.2, y+2.04, 1.58, 0.2, { fontSize: 11, bold: true });
  tx(slide, `比分Top1  ${l.score || '—'}`, x+0.25, y+2.4, 2.2, 0.22, { fontSize: 11, color: C.text });
  tx(slide, `半全场  ${l.hafu || '—'}`, x+2.55, y+2.4, 1.5, 0.22, { fontSize: 11, color: C.text });
  const agree = r.agreement || {};
  const agreeText = `一致性：胜平负 ${agree['1x2'] ? '✓' : '×'}  ·  比分 ${agree.score ? '✓' : '×'}  ·  半全场 ${agree.hafu ? '✓' : '×'}`;
  tx(slide, agreeText, x+0.25, y+h-0.38, w-0.5, 0.2, { fontSize: 9, color: agree['1x2'] ? C.lime : C.amber });
}

// Slide 1
{
  const s = pptx.addSlide('MASTER');
  s.background = { color: C.bg };
  s.addShape(pptx.ShapeType.ellipse, { x: 9.3, y: -1.2, w: 5.1, h: 5.1, fill: { color: '15304A', transparency: 20 }, line: { color: '15304A', transparency: 100 } });
  s.addShape(pptx.ShapeType.ellipse, { x: 10.6, y: 0.2, w: 2.4, h: 2.4, fill: { color: '1D5D69', transparency: 20 }, line: { color: '1D5D69', transparency: 100 } });
  tx(s, 'FOOTBALL PREDICTION', 0.7, 1.05, 5.5, 0.25, { fontSize: 11, bold: true, color: C.cyan, charSpacing: 1.5 });
  tx(s, '双轨预测', 0.65, 1.55, 6.7, 0.72, { fontSize: 42, bold: true });
  tx(s, '2026-08-09 竞彩销售日', 0.7, 2.38, 6.8, 0.38, { fontSize: 23, color: C.lime, bold: true });
  tx(s, '胜平负  ·  精确比分  ·  半全场', 0.72, 3.02, 6.4, 0.3, { fontSize: 16, color: C.muted });
  s.addShape(pptx.ShapeType.roundRect, { x: 0.7, y: 4.25, w: 6.45, h: 1.08, rectRadius: 0.08, fill: { color: C.panel }, line: { color: C.line }, shadow: shadow() });
  tx(s, '量化轨', 1.02, 4.55, 1.0, 0.23, { fontSize: 13, bold: true, color: C.cyan });
  tx(s, '市场基线 / market_only', 2.05, 4.55, 2.2, 0.23, { fontSize: 12 });
  tx(s, 'LLM轨', 4.35, 4.55, 0.8, 0.23, { fontSize: 13, bold: true, color: C.lime });
  tx(s, '智谱 + 千问 + DeepSeek投票', 5.12, 4.55, 1.7, 0.23, { fontSize: 10.5 });
  tx(s, '6场赛前预测 · 已分别登记用于后续回测', 0.72, 5.92, 6.8, 0.25, { fontSize: 12, color: C.muted });
  s.addNotes('本PPT基于2026-08-09销售日6场赛前双轨预测。量化轨是MARKET_BASELINE，不代表独立edge；LLM轨单独记录。');
}

// Slide 2
{
  const s = pptx.addSlide('MASTER');
  title(s, 'methodology', '先看口径，再看方向', '所有预测均在开球前生成；赛后使用官方90分钟结果回填。');
  stat(s, 0.65, 1.95, '6', '可建模场次', C.cyan);
  stat(s, 3.55, 1.95, '6/6', 'LLM三模型成功', C.lime);
  stat(s, 6.45, 1.95, '66.7%', '胜平负一致率', C.amber);
  stat(s, 9.35, 1.95, '6/6', '量化轨已登记', C.purple);
  s.addShape(pptx.ShapeType.roundRect, { x: 0.65, y: 3.55, w: 5.75, h: 2.35, rectRadius: 0.08, fill: { color: C.panel }, line: { color: C.line }, shadow: shadow() });
  tx(s, '本轮双轨的正确用法', 0.95, 3.86, 4.6, 0.28, { fontSize: 18, bold: true });
  tx(s, '01', 0.95, 4.42, 0.35, 0.22, { fontSize: 12, bold: true, color: C.cyan });
  tx(s, '胜平负：分别观察两轨方向，不把一致当成edge', 1.42, 4.42, 4.55, 0.22, { fontSize: 11 });
  tx(s, '02', 0.95, 4.87, 0.35, 0.22, { fontSize: 12, bold: true, color: C.cyan });
  tx(s, '比分：Top1只是一个格子，不替代1X2方向', 1.42, 4.87, 4.55, 0.22, { fontSize: 11 });
  tx(s, '03', 0.95, 5.32, 0.35, 0.22, { fontSize: 12, bold: true, color: C.cyan });
  tx(s, '半全场：单独记录，后续单独回测', 1.42, 5.32, 4.55, 0.22, { fontSize: 11 });
  s.addShape(pptx.ShapeType.roundRect, { x: 6.75, y: 3.55, w: 5.95, h: 2.35, rectRadius: 0.08, fill: { color: '172A2C' }, line: { color: '2C5D5C' }, shadow: shadow() });
  tx(s, '回测登记状态', 7.05, 3.86, 4.4, 0.28, { fontSize: 18, bold: true, color: C.lime });
  tx(s, '量化轨', 7.05, 4.42, 1.0, 0.22, { fontSize: 12, bold: true, color: C.cyan });
  tx(s, '6/6 prematch 已写入共享回测库', 8.15, 4.42, 4.0, 0.22, { fontSize: 12 });
  tx(s, 'LLM轨', 7.05, 4.87, 1.0, 0.22, { fontSize: 12, bold: true, color: C.lime });
  tx(s, '6/6 已写入独立index_llm.json', 8.15, 4.87, 4.0, 0.22, { fontSize: 12 });
  tx(s, '赛果', 7.05, 5.32, 1.0, 0.22, { fontSize: 12, bold: true, color: C.amber });
  tx(s, '等待中国体彩网官方90分钟结果', 8.15, 5.32, 4.0, 0.22, { fontSize: 12 });
  s.addNotes('量化轨当前market_dependency_pct=100%，banker_allowed=false。LLM轨是独立记录，不与量化轨融合成胆。');
}

// Slides 3-5: two matches per slide
for (let i = 0; i < compare.rows.length; i += 2) {
  const s = pptx.addSlide('MASTER');
  const pair = compare.rows.slice(i, i+2);
  title(s, `matches ${i+1}-${i+2}`, `逐场预测 · ${i+1}—${Math.min(i+2, compare.rows.length)}`, 'Q=量化轨（市场基线） · L=LLM三模型投票');
  matchCard(s, pair[0], 0.65, 1.95, 5.95, 4.55);
  if (pair[1]) matchCard(s, pair[1], 6.75, 1.95, 5.95, 4.55);
  s.addNotes(pair.map(r => `${r.match_num} ${r.home} vs ${r.away}：量化${r.quant.direction}/${r.quant.score}/${r.quant.hafu}；LLM${r.llm['1x2']}/${r.llm.score}/${r.llm.hafu}`).join('\n'));
}

// Slide 6
{
  const s = pptx.addSlide('MASTER');
  title(s, 'backtest & caution', '分歧要留下，结果才有价值', '今天的预测不是结论，而是一次可审计的赛前样本。');
  const boxes = [
    ['胜平负一致', '4 / 6', C.cyan],
    ['比分一致', '1 / 6', C.amber],
    ['半全场一致', '0 / 6', C.coral],
    ['正式胆', '0', C.purple]
  ];
  boxes.forEach((b, idx) => stat(s, 0.65 + idx*3.02, 1.9, b[1], b[0], b[2]));
  s.addShape(pptx.ShapeType.roundRect, { x: 0.65, y: 3.65, w: 7.25, h: 1.95, rectRadius: 0.08, fill: { color: C.panel }, line: { color: C.line }, shadow: shadow() });
  tx(s, '需要重点关注的分歧', 0.95, 3.96, 4.5, 0.26, { fontSize: 18, bold: true });
  tx(s, '• 周日017：量化客胜，LLM主胜', 1.0, 4.45, 5.8, 0.22, { fontSize: 12, color: C.amber });
  tx(s, '• 周日022：量化客胜，LLM主胜', 1.0, 4.83, 5.8, 0.22, { fontSize: 12, color: C.amber });
  tx(s, '• 半全场6场全部不一致，必须单独回测，不能由胜平负推断', 1.0, 5.21, 6.6, 0.22, { fontSize: 11, color: C.muted });
  s.addShape(pptx.ShapeType.roundRect, { x: 8.2, y: 3.65, w: 4.5, h: 1.95, rectRadius: 0.08, fill: { color: '172A2C' }, line: { color: '2C5D5C' }, shadow: shadow() });
  tx(s, '回测文件', 8.5, 3.96, 3.6, 0.26, { fontSize: 18, bold: true, color: C.lime });
  tx(s, '双轨四玩法对照_20260809.md', 8.5, 4.47, 3.7, 0.22, { fontSize: 10.5 });
  tx(s, '待回测记录/20260809/', 8.5, 4.85, 3.7, 0.22, { fontSize: 10.5 });
  tx(s, '赛后：移动体彩90分钟结果回填', 8.5, 5.23, 3.7, 0.22, { fontSize: 10.5, color: C.amber });
  tx(s, '结论纪律：赛前只登记，不提前用结果修改预测；赛后分别评估量化轨与LLM轨。', 0.7, 6.15, 11.8, 0.25, { fontSize: 12, color: C.muted, italic: true });
  s.addNotes('赛后使用移动体彩官方90分钟结果回填，并分别评估量化轨和LLM轨。');
}

const output = path.join(ROOT, '双轨预测_20260809销售日.pptx');
pptx.writeFile({ fileName: output });
console.log(output);
