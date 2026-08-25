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
      return { generated_at: "2026-08-25T23:00:00+08:00", budget: { daily_budget_amount: 100 } };
    },
    setStatus: () => {},
    now: () => "2026-08-25T23:00:01+08:00",
  });

  await Promise.all([auto.ensure(), auto.ensure()]);

  assert.deepEqual(calls, [["/api/daily-strategy/recommend", { method: "POST" }]]);
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
    request: async () => { throw new Error("生成失败"); },
    setStatus: (message, tone) => statuses.push([message, tone]),
  });

  await auto.ensure({ force: true });

  assert.equal(store.get().cache.dailyStrategy, existing);
  assert.equal(store.get().autoStrategy.status, "error");
  assert.match(store.get().autoStrategy.message, /生成失败/);
  assert.deepEqual(statuses.at(-1), ["策略自动生成失败，保留上次策略", "warning"]);
});
