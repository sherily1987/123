import test from "node:test";
import assert from "node:assert/strict";
import { autoStrategyChanged, createAutoStrategyRefresh, strategyNeedsGeneration } from "./strategy-auto.js";
import { createStore } from "./store.js";

test("strategy generation waits for an explicit loaded-but-missing plan", () => {
  assert.equal(strategyNeedsGeneration(undefined), false);
  assert.equal(strategyNeedsGeneration({}), true);
  assert.equal(strategyNeedsGeneration({ generated_at: "2026-08-25T22:00:00+08:00" }), false);
});

test("automatic strategy status changes are observable by the page renderer", () => {
  const previous = { autoStrategy: { status: "idle" } };
  assert.equal(autoStrategyChanged({ autoStrategy: { status: "running" } }, previous), true);
  assert.equal(autoStrategyChanged(previous, previous), false);
});

test("automatic strategy refresh posts once and updates only strategy cache", async () => {
  const store = createStore({
    salesDay: "2026-08-26", cache: { board: { marker: 1 }, dailyStrategy: {} },
    cacheTimes: {}, activeRuns: {}, moduleErrors: {},
  });
  const calls = [];
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path, options) => {
      calls.push([path, options]);
      if (path === "/api/current-sale-day") return { sales_day: "2026-08-26" };
      return { selected_day: "2026-08-26", generated_at: "2026-08-25T23:00:00+08:00", budget: { daily_budget_amount: 100 } };
    },
    setStatus: () => {},
    now: () => "2026-08-25T23:00:01+08:00",
  });

  await Promise.all([auto.ensure(), auto.ensure()]);

  assert.deepEqual(calls, [
    ["/api/current-sale-day", undefined],
    ["/api/daily-strategy/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_sales_day: "2026-08-26" }),
    }],
    ["/api/current-sale-day", undefined],
  ]);
  assert.equal(store.get().cache.board.marker, 1);
  assert.equal(store.get().cache.dailyStrategy.budget.daily_budget_amount, 100);
  assert.equal(store.get().cacheTimes.dailyStrategy, "2026-08-25T23:00:01+08:00");
});

test("forced refresh regenerates an existing plan and failure preserves it", async () => {
  const existing = { generated_at: "2026-08-25T22:00:00+08:00", snapshot_id: "old" };
  const store = createStore({
    salesDay: "2026-08-26", cache: { dailyStrategy: existing }, cacheTimes: {},
    activeRuns: {}, moduleErrors: {},
  });
  const statuses = [];
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => {
      if (path === "/api/current-sale-day") return { sales_day: "2026-08-26" };
      throw new Error("生成失败");
    },
    setStatus: (message, tone) => statuses.push([message, tone]),
  });

  await auto.ensure({ force: true });

  assert.equal(store.get().cache.dailyStrategy, existing);
  assert.equal(store.get().autoStrategy.status, "error");
  assert.match(store.get().autoStrategy.message, /生成失败/);
  assert.deepEqual(statuses.at(-1), ["策略自动生成失败，保留上次策略", "warning"]);
});

test("historical sales days never trigger automatic strategy generation", async () => {
  const existing = { generated_at: "2026-08-25T22:00:00+08:00", snapshot_id: "historical" };
  const store = createStore({
    salesDay: "2026-08-24", cache: { dailyStrategy: {} }, cacheTimes: {},
    activeRuns: {}, moduleErrors: {},
  });
  const calls = [];
  const auto = createAutoStrategyRefresh({
    store,
    request: async (...args) => { calls.push(args); return existing; },
    setStatus: () => {},
    isCurrentSalesDay: () => false,
  });

  await auto.ensure({ force: true });

  assert.deepEqual(calls, []);
  assert.equal(store.get().cache.dailyStrategy.generated_at, undefined);
  assert.match(store.get().autoStrategy.message, /只读/);
  const afterFirstRead = store.get();
  await auto.ensure({ force: true });
  assert.equal(store.get(), afterFirstRead);
});

test("a recommend response for another sales day is discarded instead of replacing the current preview", async () => {
  const previous = { selected_day: "2026-08-27", snapshot_id: "preview" };
  const store = createStore({ salesDay: "2026-08-27", cache: { dailyStrategy: previous }, cacheTimes: {}, activeRuns: {}, moduleErrors: {} });
  const statuses = [];
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => path === "/api/current-sale-day"
      ? { sales_day: "2026-08-27" }
      : { selected_day: "2026-08-28", snapshot_id: "wrong-day" },
    setStatus: (...args) => statuses.push(args),
    isCurrentSalesDay: (day) => day === "2026-08-27",
  });

  await auto.ensure({ force: true });

  assert.equal(store.get().cache.dailyStrategy, previous);
  assert.equal(store.get().autoStrategy.status, "error");
  assert.match(store.get().autoStrategy.message, /销售日不一致/);
  assert.deepEqual(statuses.at(-1), ["策略生成结果销售日不一致，已丢弃", "error"]);
});

test("authority-day failure before recommendation blocks POST and clears stale authority cache", async () => {
  const previous = { selected_day: "2026-08-26", snapshot_id: "preview" };
  const store = createStore({
    salesDay: "2026-08-26",
    cache: { currentSaleDay: { sales_day: "2026-08-26" }, dailyStrategy: previous },
    cacheTimes: { currentSaleDay: "old", dailyStrategy: "old" }, activeRuns: {}, moduleErrors: {},
  });
  let posts = 0;
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => {
      if (path === "/api/current-sale-day") throw new Error("authority unavailable");
      if (path === "/api/daily-strategy/recommend") posts += 1;
      return { selected_day: "2026-08-26", snapshot_id: "unexpected" };
    },
    setStatus: () => {},
    isCurrentSalesDay: () => true,
  });

  await auto.ensure({ force: true });

  assert.equal(posts, 0);
  assert.equal(store.get().cache.currentSaleDay, undefined);
  assert.equal(store.get().cacheTimes.currentSaleDay, undefined);
  assert.equal(store.get().cache.dailyStrategy, previous);
  assert.notEqual(store.get().autoStrategy.status, "running");
});

test("input switching during the post-response authority check discards the plan", async () => {
  const previous = { selected_day: "2026-08-26", snapshot_id: "preview" };
  const store = createStore({
    salesDay: "2026-08-26", cache: { currentSaleDay: { sales_day: "2026-08-26" }, dailyStrategy: previous },
    cacheTimes: {}, activeRuns: {}, moduleErrors: {},
  });
  let authorityReads = 0;
  let latestStarted = false;
  let releaseLatest;
  const latest = new Promise((resolve) => { releaseLatest = resolve; });
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => {
      if (path === "/api/current-sale-day") {
        authorityReads += 1;
        if (authorityReads === 1) return { sales_day: "2026-08-26" };
        latestStarted = true;
        return latest;
      }
      return { selected_day: "2026-08-26", snapshot_id: "generated" };
    },
    setStatus: () => {},
    isCurrentSalesDay: () => true,
  });

  const pending = auto.ensure({ force: true });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(latestStarted, true, "recommend must re-read backend authority after POST");
  store.set((state) => ({ ...state, salesDay: "2026-08-27" }));
  releaseLatest({ sales_day: "2026-08-26" });
  await pending;

  assert.equal(store.get().cache.dailyStrategy, previous);
  assert.notEqual(store.get().autoStrategy.status, "running");
});

test("a discarded response releases running state so a later forced run can succeed", async () => {
  const previous = { selected_day: "2026-08-26", snapshot_id: "preview" };
  const store = createStore({
    salesDay: "2026-08-26", cache: { currentSaleDay: { sales_day: "2026-08-26" }, dailyStrategy: previous },
    cacheTimes: {}, activeRuns: {}, moduleErrors: {},
  });
  let posts = 0;
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => {
      if (path === "/api/current-sale-day") return { sales_day: "2026-08-26" };
      posts += 1;
      return posts === 1
        ? { selected_day: "2026-08-27", snapshot_id: "discarded" }
        : { selected_day: "2026-08-26", snapshot_id: "accepted" };
    },
    setStatus: () => {},
    isCurrentSalesDay: () => true,
  });

  await auto.ensure({ force: true });
  assert.notEqual(store.get().autoStrategy.status, "running");
  await auto.ensure({ force: true });

  assert.equal(posts, 2);
  assert.equal(store.get().cache.dailyStrategy.snapshot_id, "accepted");
  assert.equal(store.get().autoStrategy.status, "done");
});

test("a 409 authority flip never replaces strategy cache and clears stale authority", async () => {
  const previous = { selected_day: "2026-08-26", snapshot_id: "preview" };
  const store = createStore({
    salesDay: "2026-08-26",
    cache: { currentSaleDay: { sales_day: "2026-08-26" }, dailyStrategy: previous },
    cacheTimes: { currentSaleDay: "old", dailyStrategy: "old" }, activeRuns: {}, moduleErrors: {},
  });
  const auto = createAutoStrategyRefresh({
    store,
    request: async (path) => {
      if (path === "/api/current-sale-day") return { sales_day: "2026-08-26" };
      const error = new Error("sales day changed");
      error.status = 409;
      error.code = "sales_day_authority_changed";
      throw error;
    },
    setStatus: () => {},
    isCurrentSalesDay: () => true,
  });

  await auto.ensure({ force: true });

  assert.equal(store.get().cache.dailyStrategy, previous);
  assert.equal(store.get().cacheTimes.dailyStrategy, "old");
  assert.equal(store.get().cache.currentSaleDay, undefined);
  assert.equal(store.get().cacheTimes.currentSaleDay, undefined);
  assert.equal(store.get().autoStrategy.status, "error");
  assert.match(store.get().autoStrategy.message, /销售日已切换/);
});
