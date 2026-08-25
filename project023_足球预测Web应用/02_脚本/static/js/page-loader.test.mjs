import test from "node:test";
import assert from "node:assert/strict";
import { createPageLoader } from "./page-loader.js";

test("retired scanner has no loadable page module", async () => {
  await assert.rejects(createPageLoader().load("scanner"), /未知页面模块：scanner/);
});

test("a failed route retry uses one new specifier while successful routes keep their stable specifier", async () => {
  const requested = [];
  let overviewAttempts = 0;
  const loader = createPageLoader({
    loaders: {
      overview: async (specifier) => {
        requested.push(["overview", specifier]);
        overviewAttempts += 1;
        if (overviewAttempts === 1) throw new Error("cached import failure");
        return { renderOverview: () => {} };
      },
      strategy: async (specifier) => {
        requested.push(["strategy", specifier]);
        return { renderStrategy: () => {} };
      },
    },
  });

  await assert.rejects(loader.load("overview"), /cached import failure/);
  assert.equal(loader.invalidate("overview"), true);
  const retried = await loader.load("overview");
  await loader.load("strategy");
  await loader.load("strategy");

  assert.equal(retried.source, "/js/pages/overview.js?retry=1");
  assert.deepEqual(requested, [
    ["overview", "/js/pages/overview.js"],
    ["overview", "/js/pages/overview.js?retry=1"],
    ["strategy", "/js/pages/strategy.js"],
    ["strategy", "/js/pages/strategy.js"],
  ]);
  assert.equal(loader.invalidate("strategy"), false);
});

test("a retry that fails can advance once more without changing other routes", async () => {
  const requested = [];
  const loader = createPageLoader({
    loaders: {
      overview: async (specifier) => {
        requested.push(specifier);
        if (requested.length < 3) throw new Error("still broken");
        return { renderOverview: () => {} };
      },
    },
  });

  await assert.rejects(loader.load("overview"), /still broken/);
  loader.invalidate("overview");
  await assert.rejects(loader.load("overview"), /still broken/);
  loader.invalidate("overview");
  await loader.load("overview");

  assert.deepEqual(requested, [
    "/js/pages/overview.js",
    "/js/pages/overview.js?retry=1",
    "/js/pages/overview.js?retry=2",
  ]);
});
