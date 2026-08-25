import test from "node:test";
import assert from "node:assert/strict";
import { createRefreshController } from "./refresh.js";
import { createStore } from "./store.js";

test("a failed module keeps its cache and exposes its local retry provenance", async () => {
  const store = createStore({
    salesDay: "2026-08-25",
    cache: { board: { matches: [] } },
    cacheTimes: { board: "2026-08-25T10:00:00+08:00" },
    staleKeys: [],
    moduleErrors: {},
    activeRuns: {},
  });
  const controller = createRefreshController({
    store,
    modules: [{ key: "board", path: () => "/api/board" }],
    request: async () => { throw new Error("服务暂不可用"); },
    setStatus: () => {},
  });

  await controller.refresh(["board"]);

  assert.deepEqual(store.get().cache.board, { matches: [] });
  assert.deepEqual(store.get().moduleErrors.board, {
    path: "/api/board",
    message: "服务暂不可用",
    lastSuccessfulAt: "2026-08-25T10:00:00+08:00",
  });
  assert.deepEqual(store.get().staleKeys, ["board"]);
});

test("a module apply hook rebuilds authoritative active runs after reload", async () => {
  const store = createStore({
    salesDay: "2026-08-25", cache: {}, cacheTimes: {}, staleKeys: [],
    moduleErrors: {}, activeRuns: {},
  });
  const controller = createRefreshController({
    store,
    modules: [{
      key: "activeRuns",
      path: () => "/api/runs/active",
      apply: (value, state) => ({
        ...state,
        activeRuns: Object.fromEntries(value.runs.map((run) => [run.run_type, run])),
      }),
    }],
    request: async () => ({ runs: [{ id: 91, run_type: "predict", status: "running" }] }),
    setStatus: () => {},
  });

  await controller.refresh(["activeRuns"]);

  assert.equal(store.get().activeRuns.predict.id, 91);
  assert.equal(store.get().activeRuns.predict.status, "running");
});
