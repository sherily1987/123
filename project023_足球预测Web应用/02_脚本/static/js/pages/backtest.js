import "../../league_hit_rates.js";
import { esc, formatMoney } from "../format.js";

export const BACKTEST_VIEW_KEYS = ["history", "league", "version"];
const BACKTEST_VIEW_NAMES = { history: "预测明细", league: "联赛汇总", version: "版本治理" };

const MARKET_NAMES = { HAD: "胜平负", TTG: "进球数", HAFU: "半全场", CRS: "比分", COMBO: "组合" };
const STATUS_NAMES = { won: "已中", lost: "未中", pending: "待结算", void: "作废" };

function moneyNumber(value, { allowNegative = false } = {}) {
  if (value === null || value === undefined || (typeof value === "string" && value.trim() === "")) return null;
  const number = Number(value);
  return Number.isFinite(number) && (allowNegative || number >= 0) ? number : null;
}

function isSettled(record = {}) {
  return record.settled === true || record.status === "won" || record.status === "lost";
}

export function buildStrategyAccounting(records = []) {
  const totals = (Array.isArray(records) ? records : []).reduce((accumulator, record) => {
    if (record?.status === "void") return accumulator;
    const stake = moneyNumber(record?.stake_amount);
    const returned = isSettled(record) ? moneyNumber(record?.return_amount) : 0;
    if (stake === null || (isSettled(record) && returned === null)) {
      accumulator.invalidRecords += 1;
      return accumulator;
    }
    if (!isSettled(record)) {
      accumulator.pendingStake += stake;
      return accumulator;
    }
    accumulator.settledStake += stake;
    accumulator.returned += returned;
    return accumulator;
  }, { settledStake: 0, returned: 0, pendingStake: 0, invalidRecords: 0 });
  const profit = totals.returned - totals.settledStake;
  return {
    ...totals,
    profit,
    roiPct: totals.settledStake ? Math.round(profit / totals.settledStake * 1000) / 10 : null,
  };
}

export function buildStrategyCurve(report = {}) {
  let cumulativeProfit = 0;
  return [...(Array.isArray(report?.daily) ? report.daily : [])]
    .sort((left, right) => String(left?.selected_day || "").localeCompare(String(right?.selected_day || "")))
    .map((day) => {
      const records = Array.isArray(day?.records) ? day.records : [];
      const accounting = buildStrategyAccounting(records);
      cumulativeProfit = Math.round((cumulativeProfit + accounting.profit) * 100) / 100;
      return accounting.settledStake <= 0 ? null : {
        day: day?.selected_day || "—",
        settled: records.filter(isSettled).length,
        pending: records.filter((record) => record?.status === "pending").length,
        dailyProfit: accounting.profit,
        cumulativeProfit,
        invalidRecords: accounting.invalidRecords,
      };
    }).filter(Boolean);
}

export function splitTracks(records = []) {
  const result = { quant: { n: 0, hit: 0 }, llm: { n: 0, hit: 0 } };
  (Array.isArray(records) ? records : []).filter(isSettled).forEach((record) => {
    result.quant.n += 1;
    if (record.hit) result.quant.hit += 1;
    if (record.llm_scored) {
      result.llm.n += 1;
      if (record.llm_hit) result.llm.hit += 1;
    }
  });
  return result;
}

function flattenedRecords(history = {}) {
  return (Array.isArray(history.sections) ? history.sections : []).flatMap((section) => section?.matches || []);
}

function flattenedStrategyRecords(report = {}) {
  return (Array.isArray(report.daily) ? report.daily : []).flatMap((day) =>
    (Array.isArray(day?.records) ? day.records : []).map((record) => ({ ...record, selected_day: day.selected_day })),
  );
}

function strategyRecords(context = {}) {
  const report = context.strategyBacktest?.daily ? context.strategyBacktest : context.dailyStrategy?.backtest;
  return flattenedStrategyRecords(report);
}

function trackMetric(label, metric) {
  const pct = metric.n ? `${Math.round(metric.hit / metric.n * 1000) / 10}%` : "—";
  return `${esc(label)}命中：${esc(pct)}（${esc(metric.hit)}/${esc(metric.n)} 已结算）`;
}

function fixture(record = {}) {
  if (record.market === "COMBO") {
    return (Array.isArray(record.legs) ? record.legs : []).map((leg) => `${leg?.match_num || "-"} ${leg?.home || ""} vs ${leg?.away || ""}`).join(" + ") || "组合";
  }
  return `${record.home || "-"} vs ${record.away || "-"}`;
}

function recordMoney(record, field) {
  if (!isSettled(record)) return "—";
  return moneyNumber(record?.[field], { allowNegative: field === "profit" }) === null ? "无效/缺失" : formatMoney(record[field]);
}

function stakeMoney(record) {
  return moneyNumber(record?.stake_amount) === null ? "无效/缺失" : formatMoney(record.stake_amount);
}

function strategyTable(records) {
  const rows = records.map((record) => `<tr><td>${esc(record.selected_day || "—")}</td><td>${esc(record.match_num || record.combo_id || "—")}</td><td>${esc(MARKET_NAMES[record.market] || record.market || "—")}</td><td>${esc(fixture(record))}</td><td>${esc(record.selection || "—")}</td><td>${esc(record.odds ?? "—")}</td><td>${stakeMoney(record)}</td><td>${esc(record.actual || (record.status === "pending" ? "待结算" : "—"))}</td><td>${esc(STATUS_NAMES[record.status] || record.status || "—")}</td><td>${recordMoney(record, "return_amount")}</td><td>${recordMoney(record, "profit")}</td></tr>`).join("")
    || '<tr><td colspan="11">暂无策略结算记录。</td></tr>';
  return `<section class="table-wrap" aria-label="策略逐笔账本"><table class="data-table"><thead><tr><th>策略日</th><th>场次</th><th>市场</th><th>比赛</th><th>选择</th><th>赔率</th><th>投入</th><th>官方赛果</th><th>结算</th><th>返还</th><th>净收益</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function strategyCurveTable(curve) {
  const rows = curve.map((point) => `<tr><td>${esc(point.day)}</td><td>${esc(point.settled)}</td><td>${esc(point.pending)}</td><td>${formatMoney(point.dailyProfit)}</td><td>${formatMoney(point.cumulativeProfit)}</td><td>${esc(point.invalidRecords)}</td></tr>`).join("")
    || '<tr><td colspan="6">暂无可计算的策略日。</td></tr>';
  return `<section class="table-wrap" aria-label="累计收益曲线（表格）"><table class="data-table"><caption>累计收益曲线（表格）</caption><thead><tr><th>策略日</th><th>已结算</th><th>待结算</th><th>当日净收益</th><th>累计净收益</th><th>无效金额</th></tr></thead><tbody>${rows}</tbody></table></section>`;
}

function strategyView(context) {
  const report = context.strategyBacktest?.daily ? context.strategyBacktest : context.dailyStrategy?.backtest;
  if (!report || !Array.isArray(report.daily)) {
    return '<section class="page-intro" aria-label="策略账本"><h2>策略账本</h2><p>策略数据未提供；不以 0 场、0 元或 0% 代替不可用数据。</p></section>';
  }
  const records = strategyRecords(context);
  const accounting = buildStrategyAccounting(records);
  const curve = buildStrategyCurve(report);
  const strategyDays = Number.isFinite(Number(report.snapshot_count))
    ? Number(report.snapshot_count) : (Array.isArray(report.daily) ? report.daily.length : 0);
  const settledCount = records.filter(isSettled).length;
  const pendingCount = records.filter((record) => record?.status === "pending").length;
  return `<section class="page-intro" aria-label="策略账本"><h2>策略账本</h2><p>来源：/api/daily-strategy/backtest；收益只按已结算且金额有效的注计算。</p><p>策略日 ${esc(strategyDays)} · 已结算 ${esc(settledCount)} 注 · 待结算 ${esc(pendingCount)} 注 · 无效金额记录 ${esc(accounting.invalidRecords)}</p><dl><div><dt>已结算投入</dt><dd>${formatMoney(accounting.settledStake)}</dd></div><div><dt>返还</dt><dd>${formatMoney(accounting.returned)}</dd></div><div><dt>净收益</dt><dd>${formatMoney(accounting.profit)}</dd></div><div><dt>待结算投入</dt><dd>${formatMoney(accounting.pendingStake)}</dd></div><div><dt>ROI</dt><dd>${accounting.roiPct === null ? "—" : esc(accounting.roiPct) + "%"}</dd></div></dl><p>待结算投入不进入 ROI 分母；待结算返还和净收益显示为 —；无效或缺失金额不按 0 计入。</p></section>${strategyCurveTable(curve)}${strategyTable(records)}`;
}

function scoreText(record = {}) {
  const score = record.result?.score_90;
  if (!Array.isArray(score) || score.length < 2) return record.settled ? "赛果缺失" : "待结算";
  return `${score[0]}-${score[1]}（${record.result?.direction || "方向缺失"}）`;
}

function probabilityText(record = {}) {
  const values = record.quant?.final_1x2_pct;
  return Array.isArray(values) && values.length === 3
    ? values.map((value) => `${value}%`).join(" / ")
    : "—";
}

function scoresText(scores) {
  return Array.isArray(scores) && scores.length ? scores.join("、") : "—";
}

function resultBadge(record, track) {
  if (!record.settled) return '<span class="result-badge pending">待结算</span>';
  if (track === "llm" && !record.llm_scored) return '<span class="result-badge unavailable">未计分</span>';
  if (track === "quant" && record.quant?.alt_direction) {
    return `<span class="result-badge ${record.hit ? "hit" : "miss"}">单项${record.hit ? "命中" : "未命中"}</span><small><span class="result-badge ${record.quant_double_hit ? "hit" : "miss"}">方向${record.quant_double_hit ? "命中" : "未命中"}</span></small>`;
  }
  const hit = track === "llm" ? record.llm_hit : record.hit;
  return `<span class="result-badge ${hit ? "hit" : "miss"}">${hit ? "命中" : "未命中"}</span>`;
}

function historyRow(record) {
  const kickoff = String(record.kickoff || "");
  const time = kickoff.includes("T") ? kickoff.split("T")[1].slice(0, 5) : "—";
  const llmDirection = record.llm?.direction ? `LLM：${record.llm.direction}` : "未登记";
  return `<tr><td>${esc(record.league || "联赛缺失")}</td><td>${esc(record.match_num || "—")}</td><td>${esc(time)}</td><td class="match-cell">${esc(record.home || "—")} vs ${esc(record.away || "—")}</td><td><strong>${esc(record.quant?.direction_label || record.quant?.direction || "—")}</strong><small>${esc(probabilityText(record))}</small></td><td>${esc(scoresText(record.quant?.top_scores))}</td><td><strong>${esc(llmDirection)}</strong><small>${esc(scoresText(record.llm?.top_scores))}</small></td><td>${esc(scoreText(record))}</td><td>${resultBadge(record, "quant")}</td><td>${resultBadge(record, "llm")}</td></tr>`;
}

function groupedHistory(records = []) {
  const days = new Map();
  records.forEach((record) => {
    const day = record.day || String(record.kickoff || "").slice(0, 10) || "日期缺失";
    if (!days.has(day)) days.set(day, []);
    days.get(day).push(record);
  });
  return [...days.entries()]
    .sort(([left], [right]) => String(right).localeCompare(String(left)))
    .map(([day, matches]) => ({
      day,
      matches: matches.sort((left, right) => String(left.kickoff || "").localeCompare(String(right.kickoff || ""))),
    }));
}

function historySection(records, title, className) {
  const groups = groupedHistory(records);
  const body = groups.map(({ day, matches }) => {
    const rows = matches.map(historyRow).join("");
    return `<section class="history-day" aria-labelledby="history-day-${esc(day)}"><header class="history-day-head"><h2 id="history-day-${esc(day)}">${esc(day)}</h2><span>${esc(matches.length)} 场</span></header><div class="history-table-wrap"><table class="data-table history-table"><thead><tr><th>联赛</th><th>场次</th><th>时间</th><th>比赛</th><th>量化预测<br><small>主 / 平 / 客</small></th><th>量化 Top 比分</th><th>LLM 预测</th><th>官方90分钟赛果</th><th>量化命中</th><th>LLM 命中</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
  }).join("") || '<section class="page-intro"><p>暂无记录。</p></section>';
  return `<section class="history-part ${esc(className)}"><header class="page-intro"><h2>${esc(title)} · ${esc(records.length)} 场</h2></header><div class="history-groups">${body}</div></section>`;
}

function historyView(context) {
  const records = flattenedRecords(context.history);
  const metrics = splitTracks(records);
  const settled = records.filter(isSettled);
  const pending = records.filter((record) => !isSettled(record));
  const title = `全部预测（已结算 ${settled.length} · 待结算 ${pending.length}）`;
  return `<section class="page-intro" aria-label="预测明细"><h2>预测明细</h2><p>来源：/api/history?full=1；${trackMetric("量化", metrics.quant)}；${trackMetric("LLM ", metrics.llm)}。</p><p>全部比赛按日期从新到旧排列；每场保留结算与命中状态。只用官方90分钟赛果结算，量化与 LLM 分母互不合并。</p></section>${historySection(records, title, "all-history")}`;
}

function leagueView(context) {
  const rows = globalThis.LeagueHitRates?.buildLeagueHitRates?.(context.history || {}) || [];
  const body = rows.map((row) => `<tr><td>${esc(row.rank)}</td><td>${esc(row.league)}</td><td>${esc(row.quant?.rate ?? "—")}%（${esc(row.quant?.hit ?? 0)}/${esc(row.quant?.n ?? 0)}）</td><td>${row.llm?.n ? `${esc(row.llm.rate)}%（${esc(row.llm.hit)}/${esc(row.llm.n)}）` : "—"}</td></tr>`).join("")
    || '<tr><td colspan="4">暂无已结算联赛数据。</td></tr>';
  return `<section class="page-intro" aria-label="联赛汇总"><h2>联赛汇总</h2><p>来源：/api/history?full=1；量化与 LLM 分母各自独立。</p></section><section class="table-wrap"><table class="data-table"><thead><tr><th>排名</th><th>联赛</th><th>量化命中</th><th>LLM 命中</th></tr></thead><tbody>${body}</tbody></table></section>`;
}

function versionView(context) {
  const governance = context.versionGovernance || {};
  const release = governance.release || {};
  const current = governance.current || context.versionProgress?.current || {};
  const modelVersion = release.current_model_version || context.versionProgress?.current_model_version || "未提供";
  const signature = release.probability_signature || release.current_probability_signature || context.versionProgress?.current_probability_signature || "未提供";
  return `<section class="page-intro" aria-label="版本摘要"><h2>版本摘要</h2><p>来源：/api/version-governance 与已缓存版本进度；不将历史不同版本自动并入当前 cohort。</p><dl><div><dt>当前模型版本</dt><dd>${esc(modelVersion)}</dd></div><div><dt>概率签名</dt><dd>${esc(signature)}</dd></div><div><dt>当前已结算</dt><dd>${esc(current.settled ?? "—")}</dd></div><div><dt>当前在途</dt><dd>${esc(current.pending ?? "—")}</dd></div></dl></section>`;
}

function viewBody(activeView, context) {
  if (activeView === "history") return historyView(context);
  if (activeView === "league") return leagueView(context);
  return versionView(context);
}

export function renderBacktest(root, context = {}) {
  const activeView = BACKTEST_VIEW_KEYS.includes(context.params?.view) ? context.params.view : "history";
  const viewLinks = BACKTEST_VIEW_KEYS.map((view) => `<a href="#backtest?view=${esc(view)}"${view === activeView ? ' aria-current="page"' : ""}>${esc(BACKTEST_VIEW_NAMES[view])}</a>`).join(" · ");
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">回测</h1><p>历史预测按日期排列，逐场展示联赛、预测、官方90分钟赛果及命中情况。</p></section><nav class="page-intro" aria-label="回测视图">${viewLinks}</nav>${viewBody(activeView, context)}`;
}
