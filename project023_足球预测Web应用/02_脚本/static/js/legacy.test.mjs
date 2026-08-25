import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const legacySource = await readFile(new URL("./legacy.js", import.meta.url), "utf8");

class FakeElement {
  constructor(tagName, id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.listeners = {};
    this._text = "";
    this.value = "";
    this.hidden = false;
  }

  set textContent(value) {
    this._text = String(value ?? "");
    this.children = [];
  }

  set innerHTML(_value) { throw new Error("legacy renderer must not use innerHTML"); }

  get textContent() {
    return [this._text, ...this.children.map((child) => child.textContent)].join("");
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ""; this.children = [...children]; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  click() { this.listeners.click?.({ target: this }); }

  find(tagName, text = "") {
    if (this.tagName === tagName.toUpperCase() && (!text || this.textContent.includes(text))) return this;
    for (const child of this.children) {
      const found = child.find?.(tagName, text);
      if (found) return found;
    }
    return null;
  }
}

function response(payload) {
  return { ok: true, status: 200, json: async () => structuredClone(payload) };
}

async function waitFor(predicate) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  assert.fail("legacy workbench did not finish loading");
}

async function createLegacyHarness({ history, strategy, detail }) {
  const ids = Object.fromEntries([
    "status", "sales-day", "matches", "strategy", "history", "drawer", "refresh",
  ].map((id) => [id, new FakeElement(id === "sales-day" ? "input" : "div", id)]));
  const calls = [];
  const document = {
    getElementById: (id) => ids[id],
    createElement: (name) => new FakeElement(name),
  };
  const fetch = async (path, options = {}) => {
    assert.notEqual(options.method, "POST", "legacy browser must remain read-only");
    calls.push(path);
    if (path === "/api/current-sale-day") return response({ sales_day: "2026-08-26" });
    if (path.startsWith("/api/matches?")) return response({ matches: [{ match_id: "sporttery-current", match_num: "周三001", home: "甲", away: "乙" }] });
    if (path.startsWith("/api/daily-strategy/preview?")) return response(strategy);
    if (path === "/api/history?full=1") return response(history);
    if (path === "/api/match/sporttery-current") return response(detail);
    throw new Error(`unexpected endpoint ${path}`);
  };

  vm.runInNewContext(legacySource, { document, fetch, setTimeout, console }, { filename: "legacy.js" });
  await waitFor(() => ids.status.textContent.includes("已按只读接口加载"));
  return { ids, calls };
}

const completeStrategy = {
  selected_day: "2026-08-26",
  budget: {},
  display: {},
  single_purchase_recommendations: [],
  combo_purchase_recommendations: [],
  evidence_gap_summary: {
    evidence_gap_market_rows: 2,
    reason_counts: { LINEUP_MISSING: 2, INJURY_STALE: 1 },
    age_status_counts: { FRESH: 4, AGING: 1, STALE: 2 },
    stale_market_rows: 2,
    aging_market_rows: 1,
  },
  risk_tags: ["EVIDENCE_GAP", "MARKET_DERIVED_ONLY", '<img onerror="boom">'],
  source_health: {
    matches: 3,
    api_sports: { ok: 2, NOT_REQUESTED: 1, UNAVAILABLE: 0, SOURCE_CONFLICT: 1 },
    scrapling: { attempted: 2, ok: 1, UNAVAILABLE: 1 },
  },
  market_audit: [
    { market: "HAD", independent_calibration_status: "VALID" },
    { market: "TTG", model_calibration_status: "UNFITTED" },
  ],
  llm_calibration: { llm_rows: 12, eligible_settled_rows: 7, minimum_review_rows: 100, ready_for_review: false },
};

const fullHistory = { sections: [
  { day: "2026-08-26", matches: [{ match_id: "sporttery-current", day: "2026-08-26", home: "甲", away: "乙" }] },
  { day: "2026-08-24", matches: [{ match_id: "sporttery-old", day: "2026-08-24", home: "丙", away: "丁" }] },
] };

const detailFixture = {
  match_id: "sporttery-current", home: "甲", away: "乙",
  quant: {
    ou_2_5: { over: 57.5, under: 42.5 },
    hafu: [{ selection: "胜胜", probability_pct: 31.2 }, { selection: "平胜", probability_pct: 18.1 }],
  },
};

test("legacy full-history entry displays every returned date instead of filtering to the selected day", async () => {
  const { ids, calls } = await createLegacyHarness({ history: fullHistory, strategy: completeStrategy, detail: detailFixture });

  assert.ok(calls.includes("/api/history?full=1"));
  assert.match(ids.history.textContent, /2026-08-26/);
  assert.match(ids.history.textContent, /2026-08-24/);
  assert.match(ids.history.textContent, /丙 vs 丁/);
});

test("legacy detail formats structured markets without object coercion", async () => {
  const { ids } = await createLegacyHarness({ history: fullHistory, strategy: completeStrategy, detail: detailFixture });
  ids.matches.find("button", "查看详情").click();
  await waitFor(() => ids.drawer.textContent.includes("大小球"));

  assert.match(ids.drawer.textContent, /over: 57\.5/);
  assert.match(ids.drawer.textContent, /under: 42\.5/);
  assert.match(ids.drawer.textContent, /selection: 胜胜/);
  assert.match(ids.drawer.textContent, /probability_pct: 31\.2/);
  assert.doesNotMatch(ids.drawer.textContent, /\[object Object\]/);
});

test("legacy strategy exposes complete read-only audit diagnostics", async () => {
  const { ids } = await createLegacyHarness({ history: fullHistory, strategy: completeStrategy, detail: detailFixture });
  const text = ids.strategy.textContent;

  for (const expected of [
    "LINEUP_MISSING: 2", "INJURY_STALE: 1",
    "EVIDENCE_GAP", "MARKET_DERIVED_ONLY",
    "FRESH: 4", "AGING: 1", "STALE: 2",
    "API-Sports", "SOURCE_CONFLICT: 1", "Scrapling", "attempted: 2",
    "HAD: VALID", "TTG: UNFITTED",
    "已登记 12", "已结算 7/100", "未达到复核门槛",
  ]) assert.match(text, new RegExp(expected));
  assert.match(text, /<img onerror="boom">/);
  assert.equal(ids.strategy.find("img"), null);
});
