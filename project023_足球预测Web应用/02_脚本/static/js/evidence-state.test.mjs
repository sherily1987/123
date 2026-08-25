import test from "node:test";
import assert from "node:assert/strict";
import { evidenceHasGap, normalizeEvidence } from "./evidence-state.js";

test("explicit canonical evidence arrays override heuristic lights consistently", () => {
  const complete = normalizeEvidence({
    llm: { evidence_missing_fields: [], evidence_chain_fields: [] },
    lights: { form: "missing", lineup: "not_written", injury: "none" },
  });
  assert.equal(complete.status, "完整");
  assert.deepEqual(complete.gaps, []);
  assert.equal(complete.sourceCount, 0);

  const gap = normalizeEvidence({
    llm: { evidence_missing_fields: ["starting_xi"], evidence_chain_fields: ["recent_form"] },
    lights: { form: "current", lineup: "two_source", injury: "dual" },
  });
  assert.equal(gap.status, "有缺口");
  assert.deepEqual(gap.gaps, ["starting_xi"]);
  assert.equal(gap.sourceCount, 1);
});

test("canonical evidence metadata projects freshness refs status and conflicts", () => {
  const state = normalizeEvidence({ llm: {
    evidence_status: "GAP",
    evidence_missing_fields: ["injury"],
    evidence_collected_at: "2026-08-25T00:00:00+08:00",
    evidence_age_minutes: 61.5,
    evidence_refs: { snapshot: "a.json", browser: "b.json" },
    evidence_conflicts: ["starting_xi:provider_mismatch"],
  } });
  assert.equal(state.status, "冲突");
  assert.equal(state.canonicalStatus, "GAP");
  assert.equal(state.collectedAt, "2026-08-25T00:00:00+08:00");
  assert.equal(state.ageMinutes, 61.5);
  assert.deepEqual(state.refs, ["a.json", "b.json"]);
  assert.deepEqual(state.conflicts, ["starting_xi:provider_mismatch"]);
});

test("absent evidence metadata is explicitly uncollected", () => {
  assert.equal(normalizeEvidence({}).status, "未采集");
});

test("conflicting evidence is a gap everywhere, even with no missing fields", () => {
  const match = { llm: { evidence_missing_fields: [], evidence_conflicts: ["lineup mismatch"] } };
  assert.equal(normalizeEvidence(match).status, "冲突");
  assert.equal(evidenceHasGap(match), true);
});
