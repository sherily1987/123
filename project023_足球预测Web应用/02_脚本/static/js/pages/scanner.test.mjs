import test from "node:test";
import assert from "node:assert/strict";
import { filterMatches, isOnSale, matchStatusText, renderScanner, resolveMatchRowCollection, resolveMatchRows } from "./scanner.js";
import { overviewTodoCounts, renderOverview } from "./overview.js";
import { formatPct } from "../format.js";

const rows = [
  { match_id: "sporttery-1", match_num: "周一001", home: "甲", away: "乙", league: "英超", kickoff: "2026-08-25T20:00:00+08:00", quant: null, has_odds: true, not_kicked: true },
  { match_id: "sporttery-2", match_num: "周一002", home: "丙", away: "丁", league: "西甲", kickoff: "2026-08-26T20:00:00+08:00", quant: { mode: "market_only", final_1x2_pct: [44, 28, 28] }, has_odds: true, not_kicked: true },
  { match_id: "sporttery-3", match_num: "周二003", home: "戊", away: "己", league: "英超", kickoff: "2026-08-26T18:00:00+08:00", quant: null, has_odds: false, not_kicked: true },
];

test("scanner combines date search league registration and sort filters", () => {
  assert.deepEqual(
    filterMatches(rows, { date: "2026-08-25", query: "甲", league: "英超", status: "missing", sort: "kickoff" }).map((x) => x.match_id),
    ["sporttery-1"],
  );
  assert.equal(matchStatusText(rows[0]), "有盘未登记");
});

test("scanner only honours documented sort fields", () => {
  assert.deepEqual(
    filterMatches(rows, { sort: "match_id" }).map((x) => x.match_id),
    ["sporttery-1", "sporttery-2", "sporttery-3"],
  );
  assert.deepEqual(
    filterMatches(rows, { sort: "league" }).map((x) => x.match_id),
    ["sporttery-2", "sporttery-1", "sporttery-3"],
  );
});

test("scanner uses explicit missing text and escapes row fields", () => {
  const root = { innerHTML: "", addEventListener() {} };
  renderScanner(root, { matches: { matches: [{ ...rows[0], home: '<img onerror="x">' }] }, params: {} });
  assert.match(root.innerHTML, /有盘未登记/);
  assert.match(root.innerHTML, /&lt;img onerror=&quot;x&quot;&gt;/);
  assert.doesNotMatch(root.innerHTML, /0\.0 \/ 0\.0 \/ 0\.0%/);
});

test("scanner preserves matchselect payload while focusing the exact selected row", () => {
  const root = fakeRoot();
  const selected = [];
  renderScanner(root, { matches: { matches: rows }, params: {}, onMatchSelect: (detail) => selected.push(detail) });
  const row = { dataset: { matchId: "sporttery-2" }, focus: (...args) => selected.push({ focused: args }) };
  root.handlers.click({ target: { closest: () => row } });
  assert.deepEqual(selected, [{ focused: [{ preventScroll: true }] }, { matchId: "sporttery-2" }]);
});

test("null probability and HAD elements remain missing while numeric zero remains valid", () => {
  assert.equal(formatPct([null, null, null], "未提供"), "未提供");
  assert.equal(formatPct([0, 0, 0]), "0.0 / 0.0 / 0.0%");
  assert.equal(formatPct([45, null, 25], "未提供"), "未提供");
  const root = fakeRoot();
  renderScanner(root, { matches: { matches: [{ ...rows[0], odds: [null, null, null], quant: { mode: "market_only", final_1x2_pct: [45, null, 25] } }] }, params: {} });
  assert.doesNotMatch(root.innerHTML, /0\.00 \/ 0\.00 \/ 0\.00|0\.0 \/ 0\.0 \/ 0\.0%/);
  assert.match(root.innerHTML, /<td>未提供<\/td>\s*<td>未提供<\/td>/);
});

const reviewRows = [
  { match_id: "sporttery-a", home: "甲", away: "乙", has_odds: true, quant: null, kickoff: "2026-08-25T10:30:00+08:00", status_name: "已开售", lights: { form: "current", lineup: "two_source", injury: "dual" } },
  { match_id: "sporttery-b", home: "丙", away: "丁", has_odds: true, quant: { mode: "market_only" }, kickoff: "2026-08-25T16:00:00+08:00", status_name: "暂停销售", lights: null },
  { match_id: "sporttery-c", home: "戊", away: "己", has_odds: true, quant: null, kickoff: "2026-08-25T17:00:00+08:00", status_name: "已开售", lights: { form: "current", lineup: "two_source", injury: "dual" }, identity_conflict: true },
  { match_id: "sporttery-d", home: "庚", away: "辛", has_odds: true, quant: { mode: "market_only" }, kickoff: "2026-08-25T18:00:00+08:00", status_name: "已开售", lights: { form: "current", lineup: "two_source", injury: "dual" } },
];

function fakeRoot() {
  const handlers = {};
  const dispatched = [];
  return {
    innerHTML: "", dataset: {}, dispatched,
    addEventListener(type, listener) { handlers[type] = listener; },
    dispatchEvent(event) { dispatched.push(event); return true; },
    handlers,
  };
}

test("overview KPI labels and values are exact and missing remains explicit", () => {
  const root = fakeRoot();
  renderOverview(root, {
    now: "2026-08-25T10:00:00+08:00",
    board: { summary: { on_sale: 4, predicted: 2 }, matches: reviewRows },
    versionGovernance: { release: { current_model_version: "m3" } },
  });
  assert.match(root.innerHTML, /<span>已开售<\/span>/);
  assert.match(root.innerHTML, /<span>已登记<\/span>/);
  assert.match(root.innerHTML, /<span>待处理<\/span>/);
  assert.match(root.innerHTML, /<span>证据完成<\/span>/);
  assert.match(root.innerHTML, /<span>当前模型版本<\/span>/);
  assert.match(root.innerHTML, /<b>4<\/b><span>已开售/);
  assert.match(root.innerHTML, /<b>2<\/b><span>已登记/);
  assert.match(root.innerHTML, /<b>3<\/b><span>待处理/);
  assert.match(root.innerHTML, /<b>2<\/b><span>证据完成/);
  assert.match(root.innerHTML, /<b>m3<\/b><span>当前模型版本/);

  const missing = fakeRoot();
  renderOverview(missing, { board: { summary: { on_sale: null }, matches: null }, versionGovernance: {} });
  assert.match(missing.innerHTML, /<b>未提供<\/b><span>已开售/);
  assert.match(missing.innerHTML, /<b>未提供<\/b><span>已登记/);
  assert.match(missing.innerHTML, /<b>未提供<\/b><span>待处理/);
  assert.match(missing.innerHTML, /<b>未提供<\/b><span>证据完成/);
  assert.match(missing.innerHTML, /<b>未提供<\/b><span>当前模型版本/);
});

test("overview renders a command hero and live match cards", () => {
  const root = fakeRoot();
  renderOverview(root, { now: "2026-08-25T10:00:00+08:00", board: { matches: reviewRows } });
  assert.match(root.innerHTML, /class="overview-hero"/);
  assert.match(root.innerHTML, /class="hero-command"/);
  assert.match(root.innerHTML, /class="live-match-card"/);
  assert.match(root.innerHTML, /class="dashboard-grid"/);
});

test("overview live match cards expose a reachable detail action and dispatch matchselect", () => {
  const root = fakeRoot();
  const selected = [];
  renderOverview(root, {
    now: "2026-08-25T10:00:00+08:00", board: { matches: reviewRows },
    onMatchSelect: (detail) => selected.push(detail),
  });
  assert.match(root.innerHTML, /data-overview-match-id="sporttery-a"/);
  assert.match(root.innerHTML, /查看比赛详情/);
  const button = { dataset: { overviewMatchId: "sporttery-a" }, focus() {} };
  root.handlers.click({ target: { closest: () => button } });
  assert.deepEqual(selected, [{ matchId: "sporttery-a" }]);
  assert.equal(root.dispatched.at(-1).type, "matchselect");
  assert.equal(root.dispatched.at(-1).detail.matchId, "sporttery-a");
});

test("overview keeps todo counts without linking to the retired scanner page", () => {
  const now = "2026-08-25T10:00:00+08:00";
  assert.deepEqual(overviewTodoCounts(reviewRows, { now }), {
    missing: filterMatches(reviewRows, { status: "missing", now }).length,
    evidence_missing: filterMatches(reviewRows, { status: "evidence_missing", now }).length,
    near_kickoff: filterMatches(reviewRows, { status: "near_kickoff", now }).length,
    identity_conflict: filterMatches(reviewRows, { status: "identity_conflict", now }).length,
  });
  const root = fakeRoot();
  renderOverview(root, { board: { summary: {}, matches: reviewRows }, now });
  assert.doesNotMatch(root.innerHTML, /#scanner|data-scanner-status/);
  assert.match(root.innerHTML, /今日待处理比赛/);
  assert.match(root.innerHTML, /今日待办/);
});

test("near-kickoff is deterministic and lineup conflict is not an identity conflict", () => {
  assert.deepEqual(
    filterMatches([{ ...reviewRows[0], kickoff: "not-a-date" }], { status: "near_kickoff", now: "2026-08-25T10:00:00+08:00" }),
    [],
  );
  assert.deepEqual(
    filterMatches([{ ...reviewRows[0], lights: { form: "current", lineup: "conflict", injury: "dual" } }], { status: "identity_conflict" }),
    [],
  );
  assert.equal(filterMatches([{ ...reviewRows[0], lights: { form: "current", lineup: "conflict", injury: "dual" } }], { status: "evidence_missing" }).length, 1);
  assert.equal(filterMatches([{ ...reviewRows[0], lights: { form: "current", lineup: "conflict", injury: "dual" } }], { status: "evidence_complete" }).length, 0);
});

test("overview counts selected sales-day rows rather than extra board rows", () => {
  const selected = [reviewRows[3]];
  const board = { summary: { on_sale: 99, predicted: 88 }, matches: [...reviewRows, { ...reviewRows[0], match_id: "sporttery-extra-day" }] };
  assert.deepEqual(overviewTodoCounts(selected, { now: "2026-08-25T10:00:00+08:00" }), {
    missing: filterMatches(selected, { status: "missing", now: "2026-08-25T10:00:00+08:00" }).length,
    evidence_missing: filterMatches(selected, { status: "evidence_missing", now: "2026-08-25T10:00:00+08:00" }).length,
    near_kickoff: filterMatches(selected, { status: "near_kickoff", now: "2026-08-25T10:00:00+08:00" }).length,
    identity_conflict: filterMatches(selected, { status: "identity_conflict", now: "2026-08-25T10:00:00+08:00" }).length,
  });
  const root = fakeRoot();
  renderOverview(root, { board, matches: { matches: selected }, now: "2026-08-25T10:00:00+08:00" });
  assert.match(root.innerHTML, /<b>1<\/b><span>已开售/);
  assert.match(root.innerHTML, /<b>1<\/b><span>已登记/);
  assert.match(root.innerHTML, /<b>0<\/b><span>待处理/);
});

test("selected-day KPI counts ignore global summary and preserve an explicit empty cache", () => {
  const dayRows = [
    { ...reviewRows[3], match_id: "sporttery-sale", kickoff: "2026-08-25T18:00:00+08:00" },
    { ...reviewRows[0], match_id: "sporttery-pause", kickoff: "2026-08-25T19:00:00+08:00", quant: null, status_name: "暂停销售" },
    { ...reviewRows[3], match_id: "sporttery-settled", kickoff: "2026-08-25T20:00:00+08:00", status_name: "已开售", bucket: "finished", result: { score_90: [1, 0] } },
  ];
  const nextDay = { ...reviewRows[3], match_id: "sporttery-next", kickoff: "2026-08-26T18:00:00+08:00", status_name: "已开售" };
  const board = { summary: { on_sale: 99, predicted: 88 }, matches: [...dayRows, nextDay] };
  const fallback = { board, salesDay: "2026-08-25" };
  assert.deepEqual(resolveMatchRows(fallback).map((row) => row.match_id), dayRows.map((row) => row.match_id));
  assert.equal(resolveMatchRows(fallback).filter(isOnSale).length, 2);

  const root = fakeRoot();
  renderOverview(root, fallback);
  assert.match(root.innerHTML, /<b>2<\/b><span>已开售/);
  assert.match(root.innerHTML, /<b>2<\/b><span>已登记/);

  const emptyRoot = fakeRoot();
  renderOverview(emptyRoot, { ...fallback, matches: { sales_day: "2026-08-25", matches: [] } });
  assert.match(emptyRoot.innerHTML, /<b>0<\/b><span>已开售/);
  assert.match(emptyRoot.innerHTML, /<b>0<\/b><span>已登记/);
  assert.match(emptyRoot.innerHTML, /<b>0<\/b><span>待处理/);
  assert.match(emptyRoot.innerHTML, /<b>0<\/b><span>证据完成/);
});

test("mismatched cache falls back only to board rows for the selected sales day", () => {
  const selectedDayRow = { ...reviewRows[3], match_id: "sporttery-selected", kickoff: "2026-08-26T18:00:00+08:00" };
  const oldDayRow = { ...reviewRows[0], match_id: "sporttery-old", kickoff: "2026-08-25T18:00:00+08:00" };
  assert.deepEqual(resolveMatchRowCollection({
    salesDay: "2026-08-26",
    matches: { sales_day: "2026-08-25", matches: [oldDayRow] },
    board: { matches: [oldDayRow, selectedDayRow] },
  }), { available: true, rows: [selectedDayRow] });
});

test("mismatched cache without a selected-day board fallback is unavailable", () => {
  const oldDayRow = { ...reviewRows[0], match_id: "sporttery-old", kickoff: "2026-08-25T18:00:00+08:00" };
  assert.deepEqual(resolveMatchRowCollection({
    salesDay: "2026-08-26",
    matches: { sales_day: "2026-08-25", matches: [oldDayRow] },
    board: { matches: [oldDayRow] },
  }), { available: false, rows: [] });
});

test("matching selected-day empty cache is an available known zero", () => {
  assert.deepEqual(resolveMatchRowCollection({
    salesDay: "2026-08-26",
    matches: { sales_day: "2026-08-26", matches: [] },
    board: { matches: [{ ...reviewRows[0], kickoff: "2026-08-26T18:00:00+08:00" }] },
  }), { available: true, rows: [] });
});

test("selected sales day remains authoritative for a cross-midnight kickoff", () => {
  const crossMidnight = {
    ...reviewRows[0], match_id: "sporttery-cross-midnight",
    sales_day: "2026-08-25", kickoff: "2026-08-26T00:30:00+08:00",
  };
  assert.deepEqual(resolveMatchRows({
    salesDay: "2026-08-25", board: { matches: [crossMidnight] },
  }), [crossMidnight]);
  assert.equal(filterMatches([crossMidnight], { date: "2026-08-25" }).length, 1);
});

test("scanner uses canonical explicit evidence state instead of contradictory lights", () => {
  const complete = {
    ...reviewRows[0],
    llm: { evidence_missing_fields: [], evidence_chain_fields: [] },
    lights: { form: "missing", lineup: "not_written", injury: "none" },
  };
  assert.equal(filterMatches([complete], { status: "evidence_complete" }).length, 1);
  assert.equal(filterMatches([complete], { status: "evidence_missing" }).length, 0);
  const root = fakeRoot();
  renderScanner(root, { matches: { matches: [complete] }, params: {} });
  assert.match(root.innerHTML, /<td>完整<\/td>/);
});

test("overview workflow and strategy summary are computed from selected-day data", () => {
  const selected = [
    { ...reviewRows[0], llm: { direction: "主胜" } },
    { ...reviewRows[1], result: { score_90: [1, 0] } },
  ];
  const root = fakeRoot();
  renderOverview(root, {
    matches: { sales_day: "2026-08-25", matches: selected },
    salesDay: "2026-08-25",
    dailyStrategy: {
      display: { strategy_type: "固定娱乐预算", edge_label: "未验证正EV" },
      budget: { daily_budget_amount: 100, allocated_amount: 60, preserved_amount: 40 },
      single_purchase_recommendations: [{ match_id: "sporttery-a" }, { match_id: "sporttery-b" }],
      combo_purchase_recommendations: [{ combo_id: "combo-1" }],
    },
  });
  assert.match(root.innerHTML, /采集官方开售信息[\s\S]*2\/2 完成/);
  assert.match(root.innerHTML, /确认 HAD 与赛前时点[\s\S]*2\/2 完成/);
  assert.match(root.innerHTML, /量化预测并正式登记[\s\S]*1\/2 完成/);
  assert.match(root.innerHTML, /补齐 LLM 证据研究轨[\s\S]*1\/2 完成/);
  assert.match(root.innerHTML, /赛后按 90 分钟结算和回测[\s\S]*1\/2 完成/);
  assert.match(root.innerHTML, /策略项目 3/);
  assert.match(root.innerHTML, /未验证正EV/);
});
