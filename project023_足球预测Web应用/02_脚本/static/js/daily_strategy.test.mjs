import test from "node:test";
import assert from "node:assert/strict";
import "../daily_strategy.js";

const { formatDailyStrategyHtml } = globalThis.DailyStrategyView;

test("daily strategy preserves audit evidence, source health, calibration and LLM review fields", () => {
  const html = formatDailyStrategyHtml({
    budget: {}, display: {}, single_purchase_recommendations: [], combo_purchase_recommendations: [],
    evidence_gap_summary: { evidence_gap_market_rows: 2, reason_counts: { lineup: "<missing>" }, stale_market_rows: 1, aging_market_rows: 3 },
    risk_tags: ["伤停待核"],
    source_health: { api_sports: { ok: 4, NOT_REQUESTED: 2, UNAVAILABLE: 1 }, scrapling: { attempted: 3, ok: 2, UNAVAILABLE: 1 } },
    market_audit: [{ market: "HAD", independent_calibration_status: "VALID" }],
    llm_calibration: { llm_rows: 12, eligible_settled_rows: 7, minimum_review_rows: 100, ready_for_review: false },
  });

  for (const text of ["lineup &lt;missing&gt;", "风险标签：伤停待核", "过期 1 行 / 老化 3 行", "API-Sports 成功 4", "Scrapling 尝试 3", "胜平负：VALID", "已登记 12 场，已结算 7/100 场", "仅研究观察"]) {
    assert.match(html, new RegExp(text));
  }
});
