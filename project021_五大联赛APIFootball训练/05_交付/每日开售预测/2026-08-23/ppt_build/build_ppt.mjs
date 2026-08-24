import fs from 'node:fs/promises';
import path from 'node:path';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const ROOT = 'F:/HM足球比赛预测/project021_五大联赛APIFootball训练/05_交付/每日开售预测/2026-08-23';
const OUT = path.join(ROOT, '预测汇报_2026-08-23.pptx');
const PREVIEW = path.join(ROOT, 'ppt_build', 'preview');
const FONT = 'Microsoft YaHei';
const C = { ink:'#0B1220', muted:'#526071', rule:'#CBD5E1', panel:'#F3F6F9', blue:'#2563EB', sky:'#6DCBF4', darkBlue:'#0F3B78', white:'#FFFFFF', red:'#B42318', amber:'#A15C00' };

async function readJson(file) { return JSON.parse(await fs.readFile(path.join(ROOT, file), 'utf8')); }
async function blobSave(file, blob) { await fs.writeFile(file, new Uint8Array(await blob.arrayBuffer())); }

function text(slide, content, left, top, width, height, style={}) {
  const s = slide.shapes.add({ geometry:'textbox', position:{left, top, width, height}, fill:'none', line:{style:'solid', fill:'none', width:0} });
  s.text = content;
  s.text.style = { fontFamily:FONT, fontSize:style.fontSize ?? 18, color:style.color ?? C.ink, bold:style.bold ?? false, alignment:style.alignment ?? 'left', italic:style.italic ?? false };
  return s;
}
function rect(slide, left, top, width, height, fill, lineFill='none', lineWidth=0) {
  return slide.shapes.add({ geometry:'rect', position:{left, top, width, height}, fill, line:{style:'solid', fill:lineFill, width:lineWidth} });
}
function rule(slide, left, top, width, color=C.rule, height=2) { return rect(slide, left, top, width, height, color); }
function title(slide, eyebrow, heading, sub='') {
  text(slide, eyebrow.toUpperCase(), 72, 34, 900, 22, {fontSize:16, bold:true, color:C.blue});
  text(slide, heading, 72, 68, 1110, 55, {fontSize:38, bold:true, color:C.ink});
  if (sub) text(slide, sub, 72, 126, 1100, 34, {fontSize:18, color:C.muted});
  rule(slide, 72, 166, 1136, C.rule, 2);
}
function footer(slide, page, source='数据：体彩官方固定奖金接口；量化轨 m4；生成于 2026-08-22') {
  rule(slide, 72, 675, 1136, C.rule, 1);
  text(slide, source, 72, 684, 930, 20, {fontSize:16, color:C.muted});
  text(slide, String(page).padStart(2,'0'), 1165, 684, 42, 20, {fontSize:16, color:C.muted, alignment:'right'});
}
function pct(v) { return `${Number(v).toFixed(1)}%`; }
function outcomeLabel(k) { return ({H:'主胜',D:'平局',A:'客胜'})[k] ?? k; }
function addTable(slide, rows, left, top, width, height, colWidths, headerFill=C.darkBlue) {
  const table = slide.tables.add({rows:rows.length, columns:rows[0].length, left, top, width, height, columnWidths:colWidths, values:rows});
  table.borders.assign({style:'solid', fill:C.rule, width:1});
  for (let c=0;c<rows[0].length;c++) { const cell=table.getCell(0,c); cell.fill=headerFill; cell.text.style={fontFamily:FONT,fontSize:16,bold:true,color:C.white,alignment:'center'}; }
  for (let r=1;r<rows.length;r++) {
    for (let c=0;c<rows[0].length;c++) {
      const cell=table.getCell(r,c); cell.fill=(r%2===0)?C.panel:C.white; cell.text.style={fontFamily:FONT,fontSize:16,color:C.ink,alignment:c===1?'left':'center'};
    }
  }
  return table;
}

async function main() {
  const files = (await fs.readdir(ROOT)).filter(x => x.endsWith('_output.json') && !x.endsWith('.registry-core.json')).sort();
  const games = [];
  for (const f of files) {
    const j = await readJson(f); const p=j.forecast.final_1x2_pct; const top=j.forecast.top_scores?.[0] ?? {};
    const max=Math.max(...p); const pick=['H','D','A'][p.indexOf(max)];
    games.push({num:j.match_num, match:j.match, p, pick, max, score:top.score ?? '—', scorePct:top.prob_pct ?? 0, quality:j.data_quality?.overall_pct ?? null, dep:j.market_dependency_pct ?? null});
  }
  const strong = games.filter(g=>g.max>=60).sort((a,b)=>b.max-a.max);
  const byNum = (n) => games.find(g=>g.num===n);
  const pres = Presentation.create({slideSize:{width:1280,height:720}});

  // 1 Cover
  {
    const s=pres.slides.add(); s.background.fill=C.white;
    rect(s,0,0,1280,18,C.blue); rect(s,880,18,400,702,C.darkBlue);
    text(s,'足球量化融合 / 赛前研究简报',72,74,700,28,{fontSize:18,bold:true,color:C.blue});
    text(s,'8月23日开球比赛\n预测汇报',72,145,740,170,{fontSize:54,bold:true,color:C.ink});
    text(s,'27场 · 体彩官方赛程 · 量化轨 m4',76,360,650,34,{fontSize:24,color:C.muted});
    rule(s,76,426,310,C.blue,4);
    text(s,'本报告回答：哪些方向是市场基线？哪些场次应保持克制？',76,456,700,58,{fontSize:24,color:C.ink});
    text(s,'生成时间 2026-08-22  |  仅供研究与决策支持',76,648,720,24,{fontSize:16,color:C.muted});
    text(s,'FUSION\nM4',942,218,260,170,{fontSize:62,bold:true,color:C.white});
    text(s,'SPORTTERY\nPRE-MATCH',944,420,260,80,{fontSize:20,bold:true,color:'#D9E8FF'});
    s.speakerNotes.textFrame.setText('[Sources]\n- 赛程与赔率：体彩官方固定奖金接口，2026-08-22采集。\n- 预测：football-quant-fusion 量化轨 m4 输出。');
  }

  // 2 Executive readout
  {
    const s=pres.slides.add(); title(s,'01 / 先看结论','这批预测首先是市场基线，不是独立信息优势','所有 27 场的市场依赖度为 100%，因此方向应理解为赔率基线。');
    const kpis=[['27','场正式登记'],['7','场最高概率 ≥60%'],['54.4%','平均最高概率'],['55%','输入质量评分']];
    kpis.forEach((k,i)=>{ const x=72+i*278; rect(s,x,205,250,128,i===1?C.darkBlue:C.panel); text(s,k[0],x+20,228,210,52,{fontSize:38,bold:true,color:i===1?C.white:C.blue}); text(s,k[1],x+20,288,210,26,{fontSize:17,color:i===1?'#D9E8FF':C.muted}); });
    text(s,'阅读方式',72,378,230,30,{fontSize:24,bold:true,color:C.ink});
    text(s,'• 最高概率方向 = 量化轨在当前盘口下的主方向\n• Top 比分 = 另一个分布中的单格众数，不等于赛果概率\n• 低于 60% 的方向不应被包装成“强信号”',72,420,650,120,{fontSize:21,color:C.ink});
    rect(s,824,378,384,224,C.panel); text(s,'今天最强的 7 个方向',852,404,330,28,{fontSize:23,bold:true,color:C.ink});
    text(s,strong.slice(0,7).map(g=>`${g.num}  ${outcomeLabel(g.pick)}  ${pct(g.max)}`).join('\n'),852,447,330,138,{fontSize:17,color:C.ink});
    footer(s,2); s.speakerNotes.textFrame.setText('[Sources]\n- 27个 *_output.json：每日开售预测/2026-08-23。\n- 指标由 final_1x2_pct、data_quality、market_dependency_pct 计算。');
  }

  // 3 Probability chart
  {
    const s=pres.slides.add(); title(s,'02 / 概率景观','高概率方向集中在少数场次，其余场次差距并不大','7 场最高概率达到 60% 以上；其余场次更接近“市场倾向”而非强判断。');
    const chart=s.charts.add('bar',{position:{left:72,top:205,width:740,height:390},categories:strong.map(g=>g.num),series:[{name:'最高概率',values:strong.map(g=>g.max),fill:C.blue}],barOptions:{direction:'bar',grouping:'clustered',gapWidth:36},hasLegend:false,xAxis:{min:0,max:100,majorUnit:20,textStyle:{fontSize:16,fill:C.muted},majorGridlines:{style:'solid',fill:'#E2E8F0',width:1}},yAxis:{textStyle:{fontSize:16,fill:C.ink}},dataLabels:{showValue:true,position:'outEnd',textStyle:{fontSize:16,fill:C.ink,bold:true}}});
    rect(s,860,213,348,380,C.panel); text(s,'方向解释',892,245,280,30,{fontSize:24,bold:true,color:C.ink});
    text(s,'主胜\n平局\n客胜',892,313,110,120,{fontSize:20,bold:true,color:C.blue});
    text(s,strong.map(g=>`${g.num}  ${outcomeLabel(g.pick)}  ${pct(g.max)}`).join('\n'),1000,313,180,180,{fontSize:17,color:C.ink});
    text(s,'注意：不是推荐清单；生产推荐与凯利仓位仍关闭。',892,542,280,44,{fontSize:16,bold:true,color:C.red});
    footer(s,3); s.speakerNotes.textFrame.setText('[Sources]\n- 27场量化输出的 final_1x2_pct。\n- 阈值“60%”仅用于本页分层展示，不是生产下注门槛。');
  }

  // 4 Saturday table
  {
    const s=pres.slides.add(); title(s,'03 / 周六场次','周六前半段的共同特征是：平局和第二方向仍有可见概率','表内概率合计 100%；Top 比分仅作为比分分布参考。');
    const nums=['周六018','周六019','周六021','周六022','周六023','周六024','周六025','周六026','周六027','周六028'];
    const rows=[['场次','比赛','主胜','平局','客胜','方向','Top比分']]; nums.forEach(n=>{const g=byNum(n); rows.push([g.num,g.match,pct(g.p[0]),pct(g.p[1]),pct(g.p[2]),outcomeLabel(g.pick),`${g.score} (${g.scorePct}%)`]);});
    addTable(s,rows,72,198,1136,390,[105,350,110,110,110,110,151]); footer(s,4); s.speakerNotes.textFrame.setText('[Sources]\n- 2026-08-23 量化输出：周六018—周六028。\n- 赛程、固定奖金和开球时间来自体彩官方采集快照。');
  }

  // 5 Sunday early table
  {
    const s=pres.slides.add(); title(s,'04 / 周日早场','周日早场的方向分化更明显，但数据质量仍未改善','所有场次仍以赔率为主，输入质量统一为 55%。');
    const nums=['周日001','周日002','周日003','周日004','周日005','周日006','周日007','周日008','周日009'];
    const rows=[['场次','比赛','主胜','平局','客胜','方向','Top比分']]; nums.forEach(n=>{const g=byNum(n); rows.push([g.num,g.match,pct(g.p[0]),pct(g.p[1]),pct(g.p[2]),outcomeLabel(g.pick),`${g.score} (${g.scorePct}%)`]);});
    addTable(s,rows,72,198,1136,360,[105,350,110,110,110,110,151]);
    rect(s,72,584,1136,42,'#FFF7ED'); text(s,'风险提示：方向概率高，不代表阵容、伤停或临场状态已确认。',92,595,1090,22,{fontSize:17,bold:true,color:C.amber}); footer(s,5); s.speakerNotes.textFrame.setText('[Sources]\n- 2026-08-23 量化输出：周日001—周日009。\n- 数据质量与市场依赖度字段来自各场 output JSON。');
  }

  // 6 Sunday late table
  {
    const s=pres.slides.add(); title(s,'05 / 周日重点场次','强方向与高不确定性并存，不能只看单一最大概率','尤其关注概率接近的场次：西布罗姆–伯恩利、大田–江原、纽卡斯尔–利物浦。');
    const nums=['周日010','周日011','周日012','周日013','周日014','周日015','周日016','周日017'];
    const rows=[['场次','比赛','主胜','平局','客胜','方向','Top比分']]; nums.forEach(n=>{const g=byNum(n); rows.push([g.num,g.match,pct(g.p[0]),pct(g.p[1]),pct(g.p[2]),outcomeLabel(g.pick),`${g.score} (${g.scorePct}%)`]);});
    addTable(s,rows,72,198,1136,335,[105,350,110,110,110,110,151]);
    rect(s,72,556,1136,62,C.panel); text(s,'临界场次',92,571,140,24,{fontSize:18,bold:true,color:C.blue}); text(s,'周日003：35.0/31.9/33.1；周日004：32.9/30.8/36.3；周日017：25.4/22.2/52.4',244,571,915,24,{fontSize:17,color:C.ink}); footer(s,6); s.speakerNotes.textFrame.setText('[Sources]\n- 2026-08-23 量化输出：周日010—周日017。\n- 临界场次按三项概率差距与输出字段人工筛选。');
  }

  // 7 Method and derived markets
  {
    const s=pres.slides.add(); title(s,'06 / 怎么读比分与衍生市场','Top 比分不是主方向的替代品，衍生市场要单独看待','量化轨已对比分、大小球和 BTTS 提供分布，但它们的拟合状态不完全相同。');
    const rows=[['输出层','本次用途','当前限制'],['胜平负','主方向基线','100% 市场依赖，不代表独立 edge'],['Top 比分','单格众数','单格概率低，不能与 1X2 直接比较'],['大小球 / BTTS','分布参考','必须按各自校准状态解读'],['让球 / 半全场','研究参考','未完成充分独立盘口回测']];
    addTable(s,rows,72,210,1136,250,[220,360,556]);
    rect(s,72,496,1136,90,C.panel); text(s,'本批统一风控结论',96,520,240,26,{fontSize:22,bold:true,color:C.blue}); text(s,'不生成投注建议、不计算凯利仓位；任何临场结论都必须等首发与伤停刷新后重跑。',338,517,820,38,{fontSize:21,bold:true,color:C.ink}); footer(s,7); s.speakerNotes.textFrame.setText('[Sources]\n- version_manifest.json：m4 版本说明。\n- 各场 output JSON 的 forecast、derived_market_status、recommendation_gate。');
  }

  // 8 K3 and next action
  {
    const s=pres.slides.add(); title(s,'07 / 证据链与下一步','K3 轨已发现证据缺口，正确动作是弃权并在 T−75 分钟刷新','这不是模型失败，而是当前资料不足以支持定性分析。');
    const steps=[['现在','体彩赛程 + 赔率已存档','27 场量化输出已登记'],['T−75','重新拉取首发、伤停、近况','缺一项就保留证据缺口'],['刷新后','再运行 K3 审计','满足证据门槛才给方向'],['赛后','按 90 分钟结算回测','不把加时/点球混入常规赛果']];
    steps.forEach((st,i)=>{const y=210+i*84; rect(s,72,y,90,54,i===1?C.blue:C.panel); text(s,st[0],72,y+16,90,24,{fontSize:18,bold:true,color:i===1?C.white:C.blue,alignment:'center'}); text(s,st[1],194,y+5,330,24,{fontSize:20,bold:true,color:C.ink}); text(s,st[2],194,y+33,720,22,{fontSize:17,color:C.muted}); if(i<3) rule(s,117, y+54, 2, C.rule, 30); });
    rect(s,858,210,350,270,C.darkBlue); text(s,'K3 首场审计结果',890,242,280,28,{fontSize:23,bold:true,color:C.white}); text(s,'弃权\n仅赔率可用\n首发缺失\n伤停缺失\n近况缺失',890,298,290,150,{fontSize:22,bold:true,color:'#D9E8FF'});
    text(s,'证据文件：evidence_2026-08-23/（27 个 MCP 数据块）',72,585,700,24,{fontSize:17,color:C.muted}); footer(s,8); s.speakerNotes.textFrame.setText('[Sources]\n- evidence_2026-08-23/：27个 MCP 证据文件。\n- K3 审计输出：首场 sporttery-2040990，按 evidence_gap 规则弃权。\n- 结算纪律：90分钟赛果优先，延长赛/点球单独处理。');
  }

  await fs.mkdir(PREVIEW,{recursive:true});
  for (let i=0;i<pres.slides.items.length;i++) { const slide=pres.slides.items[i]; await blobSave(path.join(PREVIEW,`slide-${String(i+1).padStart(2,'0')}.png`), await pres.export({slide,format:'png',scale:1})); await fs.writeFile(path.join(PREVIEW,`slide-${String(i+1).padStart(2,'0')}.layout.json`), await (await slide.export({format:'layout'})).text()); }
  await blobSave(path.join(PREVIEW,'deck-montage.webp'), await pres.export({format:'webp',montage:true,scale:1}));
  const pptx=await PresentationFile.exportPptx(pres); await pptx.save(OUT);
  console.log(JSON.stringify({output:OUT, slides:pres.slides.items.length, games:games.length, strong:strong.length}));
}
main().catch(e=>{console.error(e); process.exitCode=1;});
