import test from "node:test";
import assert from "node:assert/strict";
import { esc, formatMoney, formatPct, displayMissing, shanghaiSalesDay } from "./format.js";
import { createStore } from "./store.js";
import { requestJson } from "./api.js";
import { renderModuleState, renderStatus } from "./components.js";
import { createRefreshController } from "./refresh.js";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

test("dynamic text is escaped and missing values are explicit", () => {
  assert.equal(esc('<img onerror="x">'), "&lt;img onerror=&quot;x&quot;&gt;");
  assert.equal(formatPct([45.1, 28, 26.9]), "45.1 / 28.0 / 26.9%");
  assert.equal(formatMoney(100), "¥100.00");
  assert.equal(displayMissing(null, "未提供"), "未提供");
});

test("sales-day defaults use Asia Shanghai across Beijing midnight", () => {
  assert.equal(shanghaiSalesDay(new Date("2026-08-24T16:05:00.000Z")), "2026-08-25");
  assert.equal(shanghaiSalesDay(new Date("2026-08-25T15:59:00.000Z")), "2026-08-25");
  assert.equal(shanghaiSalesDay(new Date("2026-08-25T16:01:00.000Z")), "2026-08-26");
});

test("failed refresh can mark cached data stale", () => {
  const store = createStore({ cache: { board: { summary: {} } }, staleKeys: [] });
  store.set(s => ({ ...s, staleKeys: ["board"] }));
  assert.deepEqual(store.get().cache.board, { summary: {} });
  assert.deepEqual(store.get().staleKeys, ["board"]);
});

test("store subscriptions receive the next immutable state and can unsubscribe", () => {
  const store = createStore({ count: 0 });
  const updates = [];
  const unsubscribe = store.subscribe((next, previous) => updates.push([next.count, previous.count]));
  store.set((state) => ({ ...state, count: 1 }));
  unsubscribe();
  store.set((state) => ({ ...state, count: 2 }));
  assert.deepEqual(updates, [[1, 0]]);
});

test("non-success JSON responses report both status and request path", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "nope" }), { status: 503 });
  try {
    await assert.rejects(requestJson("/api/board"), (error) => (
      error.status === 503 && error.path === "/api/board" && /\/api\/board/.test(error.message)
    ));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("shared status markup escapes dynamic messages", () => {
  assert.match(renderStatus('<img onerror="x">', "error"), /&lt;img onerror=&quot;x&quot;&gt;/);
  assert.match(renderModuleState({ error: '<b>bad</b>' }), /&lt;b&gt;bad&lt;\/b&gt;/);
});

test("an older refresh cannot overwrite a newer sales-day response", async () => {
  const store = createStore({
    salesDay: "2026-08-25", page: "overview", filters: {}, selectedMatchId: null,
    cache: { board: { day: "cached" } }, cacheTimes: { board: "cached-time" },
    staleKeys: ["board"], activeRuns: {},
  });
  const pending = new Map();
  const statuses = [];
  const controller = createRefreshController({
    store,
    modules: [{ key: "board", path: (day) => `/api/board?day=${day}` }],
    request(path) { const job = deferred(); pending.set(path, job); return job.promise; },
    setStatus(message, tone) { statuses.push([message, tone]); },
    now: () => "newer-time",
  });

  const older = controller.refresh();
  store.set((state) => ({ ...state, salesDay: "2026-08-26" }));
  const newer = controller.refresh();
  pending.get("/api/board?day=2026-08-26").resolve({ day: "2026-08-26" });
  await newer;
  pending.get("/api/board?day=2026-08-25").resolve({ day: "2026-08-25" });
  await older;

  assert.deepEqual(store.get().cache.board, { day: "2026-08-26" });
  assert.equal(store.get().cacheTimes.board, "newer-time");
  assert.deepEqual(store.get().staleKeys, []);
  assert.deepEqual(statuses, [["数据已刷新", "ok"]]);
});
