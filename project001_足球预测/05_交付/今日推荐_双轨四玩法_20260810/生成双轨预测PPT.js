const pptxgen = require('pptxgenjs');
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const report = JSON.parse(fs.readFileSync(path.join(ROOT, 'dual_track_4markets.json'), 'utf8'));
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Hermes Agent';
pptx.company = '足球预测项目';
pptx.title = '双轨预测｜2026-08-10销售日';
pptx.subject = '胜平负、比分与半全场赛前预测';
pptx.lang = 'zh-CN';
pptx.theme = { headFontFace: 'Arial', bodyFontFace: 'Arial', lang: 'zh-CN' };

const C = { bg:'0B1220', panel:'141F31', panel2:'1A2A40', text:'F5F8FC', muted:'AAB7C8', cyan:'4DD0E1', lime:'A7E163', amber:'FFC857', coral:'FF7B72', purple:'B39DDB', line:'2D405B' };
const shadow = () => ({ type:'outer', color:'000000', opacity:0.22, blur:2, angle:45, distance:1 });
pptx.defineSlideMaster({
  title: 'MASTER', background:{ color:C.bg },
  objects: [
    { text:{ text:'双轨预测 · 2026-08-10销售日', options:{ x:0.55,y:7.1,w:4.8,h:0.18,fontFace:'Arial',fontSize:8,color:'7F8EA3',margin:0 } } },
    { text:{ text:'概率模型输出，非投注建议', options:{ x:9.7,y:7.1,w:3.0,h:0.18,fontFace:'Arial',fontSize:8,color:'7F8EA3',align:'right',margin:0 } } }
  ], slideNumber:{ x:12.85,y:7.1,color:'7F8EA3',fontFace:'Arial',fontSize:8 }
});
function text(s,t,x,y,w,h,o={}) { s.addText(String(t ?? ''),{x,y,w,h,fontFace:'Arial',fontSize:12,color:C.text,margin:0.04,fit:'shrink',...o}); }
function heading(s,k,t,sub='') { text(s,k.toUpperCase(),0.62,0.43,6,0.22,{fontSize:10,bold:true,color:C.cyan,charSpacing:1.1}); text(s,t,0.6,0.78,12,0.5,{fontSize:27,bold:true}); if(sub) text(s,sub,0.62,1.36,12,0.25,{fontSize:11,color:C.muted}); }
function tag(s,t,x,y,w,color,fill=C.panel2) { s.addShape(pptx.ShapeType.roundRect,{x,y,w,h:0.3,rectRadius:0.08,fill:{color:fill},line:{color:fill}}); text(s,t,x,y+0.05,w,0.16,{fontSize:9,bold:true,color,align:'center'}); }
function stat(s,x,y,val,label,color) { s.addShape(pptx.ShapeType.roundRect,{x,y,w:2.85,h:1.18,rectRadius:0.08,fill:{color:C.panel},line:{color:C.line},shadow:shadow()}); s.addShape(pptx.ShapeType.ellipse,{x:x+0.2,y:y+0.2,w:0.15,h:0.15,fill:{color},line:{color}}); text(s,val,x+0.2,y+0.42,2.3,0.3,{fontSize:25,bold:true,color}); text(s,label,x+0.2,y+0.83,2.35,0.18,{fontSize:10,color:C.muted}); }
function card(s,r,x,y,w,h) {
  const q=r.quant||{}, l=r.llm||{};
  s.addShape(pptx.ShapeType.roundRect,{x,y,w,h,rectRadius:0.08,fill:{color:C.panel},line:{color:C.line},shadow:shadow()});
  text(s,r.match_num,x+0.28,y+0.22,0.8,0.2,{fontSize:10,bold:true,color:C.cyan});
  text(s,`${r.home}  vs  ${r.away}`,x+1.15,y+0.18,w-1.45,0.28,{fontSize:16,bold:true});
  text(s,`${r.league||''} · ${String(r.kickoff||'').replace('T',' ').slice(0,16)}`,x+1.15,y+0.52,w-1.45,0.17,{fontSize:9,color:C.muted});
  s.addShape(pptx.ShapeType.line,{x:x+0.28,y:y+0.86,w:w-0.56,h:0,line:{color:C.line,width:1}});
  tag(s,'量化轨',x+0.28,y+1.05,0.82,C.cyan);
  text(s,`胜平负  ${q.direction||'—'}`,x+1.3,y+1.06,1.7,0.2,{fontSize:12,bold:true});
  text(s,`主/平/客  ${(q.prob_pct||[]).map(v=>Number(v).toFixed(1)+'%').join(' / ')}`,x+1.3,y+1.35,3.2,0.17,{fontSize:9,color:C.muted});
  text(s,`比分Top3  ${(q.top_scores||[]).join('、')||'—'}`,x+0.28,y+1.78,w-0.56,0.22,{fontSize:11});
  text(s,`半全场  ${q.hafu||'—'}`,x+0.28,y+2.14,2.0,0.22,{fontSize:11});
  tag(s,'LLM轨',x+0.28,y+2.53,0.82,C.lime,'20372B');
  text(s,`胜平负  ${l['1x2']||'—'}`,x+1.3,y+2.54,1.7,0.2,{fontSize:12,bold:true});
  if(l.alt_direction) text(s,`备选：${l.alt_direction}`,x+3.0,y+2.55,1.6,0.18,{fontSize:9,color:C.amber});
  text(s,`比分Top1  ${l.score||'—'}`,x+0.28,y+2.92,2.1,0.22,{fontSize:11});
  text(s,`半全场  ${l.hafu||'—'}`,x+2.55,y+2.92,1.7,0.22,{fontSize:11});
  const a=r.agreement||{};
  text(s,`一致性：胜平负 ${a['1x2']?'✓':'×'} · 比分 ${a.score?'✓':'×'} · 半全场 ${a.hafu?'✓':'×'}`,x+0.28,y+h-0.36,w-0.56,0.18,{fontSize:9,color:a['1x2']?C.lime:C.amber});
}

// 1: cover
{
 const s=pptx.addSlide('MASTER');
 s.addShape(pptx.ShapeType.ellipse,{x:9.25,y:-1.3,w:5.3,h:5.3,fill:{color:'163B53',transparency:15},line:{color:'163B53',transparency:100}});
 s.addShape(pptx.ShapeType.ellipse,{x:10.75,y:0.15,w:2.25,h:2.25,fill:{color:'1B6870',transparency:20},line:{color:'1B6870',transparency:100}});
 text(s,'FOOTBALL PREDICTION',0.7,1.05,5.6,0.23,{fontSize:11,bold:true,color:C.cyan,charSpacing:1.4});
 text(s,'双轨预测',0.65,1.55,6.8,0.7,{fontSize:42,bold:true});
 text(s,'2026-08-10 竞彩销售日',0.7,2.38,6.8,0.36,{fontSize:23,bold:true,color:C.lime});
 text(s,'胜平负  ·  精确比分  ·  半全场',0.72,3.02,6.8,0.3,{fontSize:16,color:C.muted});
 s.addShape(pptx.ShapeType.roundRect,{x:0.7,y:4.22,w:6.55,h:1.1,rectRadius:0.08,fill:{color:C.panel},line:{color:C.line},shadow:shadow()});
 text(s,'量化轨',1.0,4.54,0.95,0.22,{fontSize:13,bold:true,color:C.cyan});
 text(s,'MARKET_BASELINE',1.95,4.54,2.05,0.22,{fontSize:12});
 text(s,'LLM轨',4.22,4.54,0.85,0.22,{fontSize:13,bold:true,color:C.lime});
 text(s,'智谱 + 千问 + DeepSeek',5.05,4.54,1.85,0.22,{fontSize:10.5});
 text(s,'3场赛前预测 · 已冻结登记，等待官方90分钟结果回测',0.72,5.92,7.3,0.24,{fontSize:12,color:C.muted});
 s.addNotes('本PPT是销售日2026-08-10的3场赛前预测。量化轨为市场基线，不代表独立edge；两轨分开登记。');
}
// 2: overview
{
 const s=pptx.addSlide('MASTER'); heading(s,'overview','赛前预测与回测纪律','3场全部在北京时间8月11日凌晨开球。');
 stat(s,0.65,1.92,'3','可建模场次',C.cyan); stat(s,3.7,1.92,'3/3','LLM模型输出成功',C.lime); stat(s,6.75,1.92,'66.7%','胜平负一致率',C.amber); stat(s,9.8,1.92,'3/3','量化轨已登记',C.purple);
 s.addShape(pptx.ShapeType.roundRect,{x:0.65,y:3.55,w:5.85,h:2.28,rectRadius:0.08,fill:{color:C.panel},line:{color:C.line},shadow:shadow()});
 text(s,'输出解读',0.95,3.86,3.8,0.26,{fontSize:18,bold:true});
 text(s,'01',0.95,4.43,0.32,0.2,{fontSize:12,bold:true,color:C.cyan}); text(s,'胜平负看最终1X2方向与完整概率',1.42,4.43,4.5,0.2,{fontSize:11});
 text(s,'02',0.95,4.86,0.32,0.2,{fontSize:12,bold:true,color:C.cyan}); text(s,'比分Top1/Top3只是精确比分候选',1.42,4.86,4.5,0.2,{fontSize:11});
 text(s,'03',0.95,5.29,0.32,0.2,{fontSize:12,bold:true,color:C.cyan}); text(s,'半全场独立登记，赛后独立评分',1.42,5.29,4.5,0.2,{fontSize:11});
 s.addShape(pptx.ShapeType.roundRect,{x:6.8,y:3.55,w:5.9,h:2.28,rectRadius:0.08,fill:{color:'172A2C'},line:{color:'2C5D5C'},shadow:shadow()});
 text(s,'边界条件',7.1,3.86,3.8,0.26,{fontSize:18,bold:true,color:C.lime});
 text(s,'量化轨',7.1,4.43,1.0,0.2,{fontSize:12,bold:true,color:C.cyan}); text(s,'market_only，市场依赖100%',8.2,4.43,3.8,0.2,{fontSize:11});
 text(s,'正式胆',7.1,4.86,1.0,0.2,{fontSize:12,bold:true,color:C.amber}); text(s,'0场；不把市场方向称为独立edge',8.2,4.86,3.8,0.2,{fontSize:11});
 text(s,'结算',7.1,5.29,1.0,0.2,{fontSize:12,bold:true,color:C.purple}); text(s,'移动体彩官方90分钟赛果',8.2,5.29,3.8,0.2,{fontSize:11});
}
// 3-4 matches
{
 const s=pptx.addSlide('MASTER'); heading(s,'matches 1-2','逐场预测 · 1—2','Q=量化轨（市场基线） · L=LLM三模型投票'); card(s,report.rows[0],0.65,1.88,5.95,4.62); card(s,report.rows[1],6.75,1.88,5.95,4.62);
}
{
 const s=pptx.addSlide('MASTER'); heading(s,'match 3','逐场预测 · 3','Q=量化轨（市场基线） · L=LLM三模型投票'); card(s,report.rows[2],3.7,1.88,5.95,4.62);
 s.addShape(pptx.ShapeType.roundRect,{x:0.68,y:2.05,w:2.5,h:3.95,rectRadius:0.08,fill:{color:'172A2C'},line:{color:'2C5D5C'},shadow:shadow()});
 text(s,'今日分歧',0.98,2.4,1.9,0.25,{fontSize:18,bold:true,color:C.amber});
 text(s,'周一002',0.98,3.06,1.2,0.2,{fontSize:11,bold:true,color:C.cyan});
 text(s,'量化：客胜',0.98,3.43,1.75,0.2,{fontSize:12}); text(s,'LLM：主胜',0.98,3.78,1.75,0.2,{fontSize:12});
 text(s,'LLM保留“客胜”备选，赛后单独核验。',0.98,4.35,1.82,0.6,{fontSize:10,color:C.muted});
}
// 5
{
 const s=pptx.addSlide('MASTER'); heading(s,'next step','冻结赛前样本，赛后再评价','预测阶段只登记，不用赛后信息重写预测。');
 stat(s,0.65,1.92,'2/3','胜平负方向一致',C.cyan); stat(s,3.7,1.92,'1/3','比分Top1一致',C.amber); stat(s,6.75,1.92,'0/3','半全场一致',C.coral); stat(s,9.8,1.92,'0','正式胆',C.purple);
 s.addShape(pptx.ShapeType.roundRect,{x:0.65,y:3.62,w:7.2,h:1.9,rectRadius:0.08,fill:{color:C.panel},line:{color:C.line},shadow:shadow()});
 text(s,'回测包',0.95,3.93,2.0,0.26,{fontSize:18,bold:true});
 text(s,'待回测记录/20260810/index.json',0.95,4.44,5.5,0.2,{fontSize:11}); text(s,'待回测记录/20260810/index_llm.json',0.95,4.83,5.5,0.2,{fontSize:11});
 s.addShape(pptx.ShapeType.roundRect,{x:8.15,y:3.62,w:4.55,h:1.9,rectRadius:0.08,fill:{color:'172A2C'},line:{color:'2C5D5C'},shadow:shadow()});
 text(s,'赛后评分',8.45,3.93,2.5,0.26,{fontSize:18,bold:true,color:C.lime});
 text(s,'官方90分钟：1X2、比分',8.45,4.44,3.5,0.2,{fontSize:11}); text(s,'官方半场比分：半全场',8.45,4.83,3.5,0.2,{fontSize:11});
 text(s,'小样本只用于积累与核验；达到样本门槛前，不把结果表述为模型优势。',0.72,6.15,11.9,0.24,{fontSize:12,color:C.muted,italic:true});
 s.addNotes('赛后使用移动体彩官方90分钟赛果回填。半全场需要官方半场比分，不能从终场比分推算。');
}

const output = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.join(ROOT,'双轨预测_20260810销售日.pptx');
pptx.writeFile({fileName:output}).then(()=>console.log(output));
