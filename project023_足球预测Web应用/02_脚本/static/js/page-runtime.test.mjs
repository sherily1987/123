import test from "node:test";
import assert from "node:assert/strict";
import { createAsyncPageRuntime, renderPageLoadError } from "./page-runtime.js";
import { createStore } from "./store.js";

test("a rejected page import renders a local retry error while shell state and another route remain usable", async () => {
  const root = { innerHTML: "" };
  const store = createStore({ page: "overview", cache: { board: { matches: ["kept"] } } });
  const runtime = createAsyncPageRuntime({
    root,
    loadPage: async (page) => {
      if (page === "overview") throw new Error("broken page dependency");
      return { source: "/js/pages/scanner.js", render: (target) => { target.innerHTML = "<main>scanner ready</main>"; } };
    },
    contextFor: () => ({ store: store.get() }),
    renderError: renderPageLoadError,
    titleFor: (page) => page,
    lastSuccessFor: () => "2026-08-25T12:00:00+08:00",
  });

  const failed = await runtime.render("overview", {});

  assert.equal(failed.state, "error");
  assert.match(root.innerHTML, /来源：\/js\/pages\/overview\.js/);
  assert.match(root.innerHTML, /上次成功：2026-08-25T12:00:00\+08:00/);
  assert.match(root.innerHTML, /data-page-retry="overview"/);
  assert.deepEqual(store.get().cache.board, { matches: ["kept"] });

  store.set((state) => ({ ...state, page: "scanner" }));
  const next = await runtime.render("scanner", {});
  assert.equal(next.state, "ready");
  assert.equal(root.innerHTML, "<main>scanner ready</main>");
  assert.equal(store.get().page, "scanner");
});

test("a late import for an old route cannot overwrite the newer route", async () => {
  const root = { innerHTML: "" };
  let resolveOld;
  const runtime = createAsyncPageRuntime({
    root,
    loadPage: (page) => page === "overview"
      ? new Promise((resolve) => { resolveOld = resolve; })
      : Promise.resolve({ source: "/js/pages/scanner.js", render: (target) => { target.innerHTML = "scanner wins"; } }),
    contextFor: () => ({}),
    renderError: renderPageLoadError,
    titleFor: (page) => page,
    lastSuccessFor: () => null,
  });

  const oldRoute = runtime.render("overview", {});
  const newRoute = await runtime.render("scanner", {});
  resolveOld({ source: "/js/pages/overview.js", render: (target) => { target.innerHTML = "old route"; } });
  const oldResult = await oldRoute;

  assert.equal(newRoute.state, "ready");
  assert.equal(oldResult.state, "stale");
  assert.equal(root.innerHTML, "scanner wins");
});
