import test from "node:test";
import assert from "node:assert/strict";
import { BACKTEST_VIEW_KEYS, buildStrategyAccounting, buildStrategyCurve, renderBacktest, splitTracks } from "./backtest.js";
import { renderStrategy } from "./strategy.js";
import { renderLeagues } from "./leagues.js";

test("pending stakes do not enter ROI denominator", () => {
  const got = buildStrategyAccounting([
    { status: "won", stake_amount: 20, return_amount: 36 },
    { status: "pending", stake_amount: 30 },
  ]);
  assert.deepEqual(got, { settledStake: 20, returned: 36, profit: 16, pendingStake: 30, roiPct: 80, invalidRecords: 0 });
});

test("void recommendations do not become pending capital", () => {
  const got = buildStrategyAccounting([
    { status: "void", stake_amount: 20 },
    { status: "pending", stake_amount: 30 },
  ]);
  assert.deepEqual(got, { settledStake: 0, returned: 0, profit: 0, pendingStake: 30, roiPct: null, invalidRecords: 0 });
});

test("missing and invalid money is excluded instead of becoming zero", () => {
  const got = buildStrategyAccounting([
    { status: "won", stake_amount: "bad", return_amount: 50 },
    { status: "lost", stake_amount: 20, return_amount: null },
    { status: "pending", stake_amount: "" },
    { status: "won", stake_amount: 20, return_amount: 36 },
  ]);
  assert.deepEqual(got, {
    settledStake: 20, returned: 36, profit: 16, pendingStake: 0,
    roiPct: 80, invalidRecords: 3,
  });
});

test("strategy curve is computed by strategy day from valid settled money only", () => {
  assert.deepEqual(buildStrategyCurve({ daily: [
    { selected_day: "2026-08-26", records: [
      { status: "lost", stake_amount: 10, return_amount: 0 },
    ] },
    { selected_day: "2026-08-25", records: [
      { status: "won", stake_amount: 20, return_amount: 50 },
      { status: "pending", stake_amount: 30 },
    ] },
  ] }), [
    { day: "2026-08-25", settled: 1, pending: 1, dailyProfit: 30, cumulativeProfit: 30, invalidRecords: 0 },
    { day: "2026-08-26", settled: 1, pending: 0, dailyProfit: -10, cumulativeProfit: 20, invalidRecords: 0 },
  ]);
});

test("negative settled profit is displayed while invalid-only days stay out of the curve", () => {
  const report = { daily: [
    { selected_day: "2026-08-25", records: [{ status: "lost", stake_amount: 10, return_amount: 0, profit: -10 }] },
    { selected_day: "2026-08-26", records: [{ status: "won", stake_amount: "bad", return_amount: 20 }] },
  ] };
  assert.deepEqual(buildStrategyCurve(report), [
    { day: "2026-08-25", settled: 1, pending: 0, dailyProfit: -10, cumulativeProfit: -10, invalidRecords: 0 },
  ]);
});

test("quant and llm denominators stay separate", () => {
  const got = splitTracks([
    { settled: true, hit: true, llm_scored: false },
    { settled: true, hit: false, llm_scored: true, llm_hit: true },
  ]);
  assert.deepEqual(got, { quant: { n: 2, hit: 1 }, llm: { n: 1, hit: 1 } });
});

test("backtest exposes only the approved analysis view keys", () => {
  assert.deepEqual(BACKTEST_VIEW_KEYS, ["history", "league", "version"]);
});

function backtestContext(view) {
  return {
    params: { view },
    strategyBacktest: { daily: [{ selected_day: "2026-08-25", records: [
      { market: "HAD", match_num: "周一001", home: "甲", away: "乙", selection: "胜", odds: 2.5, stake_amount: 20, actual: "胜", status: "won", return_amount: 50, profit: 30 },
      { market: "TTG", match_num: "周一002", home: "丙", away: "丁", selection: "2球", odds: 3.2, stake_amount: 30, status: "pending" },
    ] }] },
    history: { sections: [{ matches: [
      { match_id: "sporttery-1", match_num: "周一001", day: "2026-08-25", league: "英超", home: "甲", away: "乙", kickoff: "2026-08-25T19:30:00+08:00", quant: { direction: "主胜", final_1x2_pct: [50, 30, 20], top_scores: ["1-0", "2-1"] }, result: { score_90: [1, 0], direction: "主胜", settlement_scope: "90min" }, settled: true, hit: true, llm_scored: false },
      { match_id: "sporttery-2", match_num: "周一002", day: "2026-08-25", league: "英超", home: "丙", away: "丁", kickoff: "2026-08-25T21:00:00+08:00", quant: { direction: "平局", final_1x2_pct: [30, 40, 30], top_scores: ["1-1"] }, llm: { direction: "客胜", top_scores: ["0-1"] }, result: { score_90: [1, 0], direction: "主胜", settlement_scope: "90min" }, settled: true, hit: false, llm_scored: true, llm_hit: false },
      { match_id: "sporttery-3", match_num: "周日001", day: "2026-08-24", league: "西甲", home: "戊", away: "己", kickoff: "2026-08-24T20:00:00+08:00", quant: { direction: "客胜", final_1x2_pct: [20, 30, 50], top_scores: [] }, result: null, settled: false, hit: false, llm_scored: false },
    ] }] },
    versionGovernance: { release: { current_model_version: "m3", probability_signature: "abc123" }, current: { settled: 2, pending: 1 } },
  };
}

test("backtest defaults to grouped prediction history and keeps track denominators separate", () => {
  const history = {};
  const league = {};
  const version = {};
  renderBacktest(history, backtestContext());
  renderBacktest(league, backtestContext("league"));
  renderBacktest(version, backtestContext("version"));
  assert.match(history.innerHTML, /预测明细/);
  assert.doesNotMatch(history.innerHTML, /策略账本/);
  assert.match(history.innerHTML, /量化命中：50%（1\/2 已结算）/);
  assert.match(history.innerHTML, /LLM 命中：0%（0\/1 已结算）/);
  assert.match(league.innerHTML, /联赛汇总/);
  assert.match(league.innerHTML, /英超/);
  assert.match(version.innerHTML, /版本摘要/);
  assert.match(version.innerHTML, /m3/);
});

test("prediction history groups only by newest date and itemizes leagues in the table", () => {
  const root = {};
  renderBacktest(root, backtestContext("history"));
  const latest = root.innerHTML.indexOf("2026-08-25");
  const older = root.innerHTML.indexOf("2026-08-24");
  assert.ok(latest >= 0 && older > latest);
  assert.match(root.innerHTML, /2026-08-25[\s\S]*2 场[\s\S]*<th>联赛<\/th>[\s\S]*英超/);
  assert.match(root.innerHTML, /周一001[\s\S]*甲 vs 乙[\s\S]*主胜[\s\S]*50% \/ 30% \/ 20%[\s\S]*1-0、2-1[\s\S]*1-0（主胜）[\s\S]*命中/);
  assert.match(root.innerHTML, /周一002[\s\S]*LLM：客胜[\s\S]*未命中/);
  assert.match(root.innerHTML, /2026-08-24[\s\S]*西甲[\s\S]*待结算/);
});

test("prediction history sorts all fixtures by date regardless of settlement status", () => {
  const root = {};
  const context = backtestContext("history");
  context.history.sections[0].matches.push({
    match_id: "sporttery-4", match_num: "周二001", day: "2026-08-26", league: "欧冠",
    home: "庚", away: "辛", kickoff: "2026-08-26T03:00:00+08:00",
    quant: { direction: "主胜", final_1x2_pct: [55, 25, 20], top_scores: ["1-0"] },
    result: null, settled: false, hit: false, llm_scored: false,
  });
  renderBacktest(root, context);
  const newestPending = root.innerHTML.indexOf("2026-08-26");
  const settledDay = root.innerHTML.indexOf("2026-08-25");
  const oldestPending = root.innerHTML.indexOf("2026-08-24");
  assert.ok(newestPending >= 0 && settledDay > newestPending && oldestPending > settledDay);
  assert.match(root.innerHTML, /2026-08-26[\s\S]*周二001[\s\S]*待结算/);
  assert.match(root.innerHTML, /2026-08-25[\s\S]*周一001[\s\S]*命中/);
});

test("prediction history renders one always-visible table per date without league toggles", () => {
  const root = {};
  renderBacktest(root, backtestContext("history"));
  const dayTables = root.innerHTML.match(/<div class="history-table-wrap">/g) || [];
  assert.equal(dayTables.length, 2);
  assert.doesNotMatch(root.innerHTML, /<details|<summary|history-toggle/);
  assert.match(root.innerHTML, /2026-08-25[\s\S]*<th>联赛<\/th>[\s\S]*英超/);
});

test("strategy page keeps budget boundary without a manual recommendation button", () => {
  const root = {};
  renderStrategy(root, {
    dailyStrategy: {
      display: { edge_label: "未验证正EV", warning: "不是生产胆项" },
      budget: { daily_budget_amount: 100, allocated_amount: 70, preserved_amount: 30 },
      risk_disclosure: { maximum_loss_amount: 100 },
      evidence_gap_summary: { evidence_gap_market_rows: 1 },
      market_audit: [{ market: "HAD" }, { market: "<script>" }],
      single_purchase_recommendations: [], combo_purchase_recommendations: [],
      model_basis: "市场定价参考 <风险>",
    },
  });
  assert.match(root.innerHTML, /100元/);
  assert.match(root.innerHTML, /未验证正EV/);
  assert.match(root.innerHTML, /不是生产胆项/);
  assert.match(root.innerHTML, /市场定价参考 &lt;风险&gt;/);
  assert.doesNotMatch(root.innerHTML, /市场定价参考 <风险>/);
  assert.match(root.innerHTML, /市场筛选：<\/strong>HAD、&lt;script&gt;/);
  assert.match(root.innerHTML, /策略项目：<\/strong>0/);
  assert.doesNotMatch(root.innerHTML, /data-recommend-strategy|>推荐策略<\/button>/);
});

test("strategy page renders the separately loaded historical backtest", () => {
  const root = {};
  renderStrategy(root, {
    dailyStrategy: {
      selected_day: "2026-08-25",
      display: { edge_label: "未验证正EV" },
      budget: { daily_budget_amount: 100, allocated_amount: 40, preserved_amount: 60 },
      single_purchase_recommendations: [],
      combo_purchase_recommendations: [],
    },
    strategyBacktest: {
      snapshot_count: 3,
      summary: {
        settled_count: 8,
        won_count: 4,
        lost_count: 4,
        pending_count: 0,
        profit: 72.92,
        roi_pct: 68.79,
      },
      daily: [{
        selected_day: "2026-08-24",
        records: [{
          market: "HAD", match_num: "周日001", home: "甲", away: "乙",
          selection: "胜", odds: 2.1, stake_amount: 20,
          actual: "胜", status: "won", profit: 22,
        }],
      }],
    },
  });
  assert.match(root.innerHTML, /长期策略收益回测/);
  assert.match(root.innerHTML, /3 个策略日/);
  assert.match(root.innerHTML, /已结算 8 注/);
  assert.match(root.innerHTML, /2026-08-24|周日001/);
});

test("league page omits ranking summary and keeps detailed history", () => {
  const root = {};
  renderLeagues(root, {
    history: { sections: [{ matches: [
      { day: "2026-08-25", league: "英超", match_num: "周一001", home: "甲", away: "乙", settled: true, hit: true, llm_scored: true, llm_hit: false },
      { league: "英超", settled: true, hit: false, llm_scored: false },
    ] }] },
  });
  assert.doesNotMatch(root.innerHTML, /aria-label="联赛命中率"/);
  assert.doesNotMatch(root.innerHTML, /<th>排名<\/th>/);
  assert.doesNotMatch(root.innerHTML, /<th>量化命中率<\/th>/);
  assert.match(root.innerHTML, /全部预测明细/);
  assert.match(root.innerHTML, /周一001[\s\S]*甲 vs 乙/);
});

test("league page shows every prediction detail grouped by league by default", () => {
  const root = {};
  renderLeagues(root, { history: { sections: [{ matches: [
    { day: "2026-08-26", league: "西甲", match_num: "周二002", kickoff: "2026-08-26T02:00:00+08:00", home: "丙", away: "丁", settled: false, quant: { direction: "平局", final_1x2_pct: [30, 40, 30], top_scores: ["1-1"] }, llm: { direction: "客胜", alt_direction: "平局", top_scores: ["1-2"] } },
    { day: "2026-08-25", league: "英超", match_num: "周一001", kickoff: "2026-08-25T03:00:00+08:00", home: "甲", away: "乙", settled: true, hit: true, llm_scored: true, llm_hit: false, result: { score_90: [2, 1], direction: "主胜" }, quant: { direction: "主胜", final_1x2_pct: [55, 25, 20], top_scores: ["2-1", "1-0"] }, llm: { direction: "平局", alt_direction: "主胜", top_scores: ["1-1"] } },
  ] }] } });
  const detail = root.innerHTML.slice(root.innerHTML.indexOf("全部预测明细"));
  assert.match(detail, /按联赛排序/);
  assert.match(detail, /按日期排序/);
  assert.ok(detail.indexOf("西甲") < detail.indexOf("英超"));
  assert.match(detail, /周一001[\s\S]*甲 vs 乙[\s\S]*主胜[\s\S]*55% \/ 25% \/ 20%[\s\S]*2-1、1-0[\s\S]*LLM：平局[\s\S]*备选：主胜[\s\S]*2-1（主胜）[\s\S]*命中[\s\S]*未命中/);
  assert.match(detail, /周二002[\s\S]*待结算/);
});

test("league page date mode sorts newest prediction day first", () => {
  const root = {};
  renderLeagues(root, { params: { sort: "date" }, history: { sections: [{ matches: [
    { day: "2026-08-25", league: "英超", match_num: "周一001", home: "甲", away: "乙" },
    { day: "2026-08-26", league: "西甲", match_num: "周二002", home: "丙", away: "丁" },
  ] }] } });
  const detail = root.innerHTML.slice(root.innerHTML.indexOf("全部预测明细"));
  assert.ok(detail.indexOf("2026-08-26") < detail.indexOf("2026-08-25"));
  assert.match(detail, /href="#leagues\?sort=league"/);
  assert.match(detail, /href="#leagues\?sort=date"[^>]*aria-current="page"/);
});
