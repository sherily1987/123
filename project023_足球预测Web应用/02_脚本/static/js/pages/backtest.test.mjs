import test from "node:test";
import assert from "node:assert/strict";
import { renderBacktest } from "./backtest.js";

test("history labels an unregistered cover as research and never scores it", () => {
  const root = { innerHTML: "" };
  const record = {
    day: "2026-08-27", kickoff: "2026-08-27T03:00:00+08:00",
    league: "欧冠", match_num: "周三005", home: "采列", away: "客队",
    settled: true, hit: false, quant_double_scored: false, quant_double_hit: false,
    quant: {
      direction: "主胜", alt_direction: null, direction_label: "主胜",
      final_1x2_pct: [39.4, 29.8, 30.7], top_scores: [],
      research_simulation: {
        direction: "主胜", alt_direction: "平局", label: "主胜略优，防平",
        excluded_from_formal_stats: true,
      },
    },
    result: { score_90: [1, 1], direction: "平局" },
  };

  renderBacktest(root, { params: { view: "history" }, history: { sections: [{ matches: [record] }] } });

  assert.match(root.innerHTML, /研究模拟：主胜略优，防平（不计正式命中）/);
  assert.match(root.innerHTML, />未命中</);
  assert.doesNotMatch(root.innerHTML, /登记双选命中/);
});

test("history scores a complete prediction-time direction registration", () => {
  const root = { innerHTML: "" };
  const record = {
    day: "2026-08-27", kickoff: "2026-08-27T03:00:00+08:00",
    league: "欧冠", match_num: "周三006", home: "主队", away: "客队",
    settled: true, hit: false, quant_double_scored: true, quant_double_hit: true,
    quant: {
      direction: "主胜", alt_direction: "平局", direction_label: "主胜 / 平局",
      direction_policy: "quant-double-direction-v1", direction_policy_version: "1",
      direction_prediction_as_of: "2026-08-26T18:00:00+08:00",
      final_1x2_pct: [39.4, 29.8, 30.7], top_scores: [], research_simulation: null,
    },
    result: { score_90: [1, 1], direction: "平局" },
  };

  renderBacktest(root, { params: { view: "history" }, history: { sections: [{ matches: [record] }] } });

  assert.match(root.innerHTML, /主胜 \/ 平局/);
  assert.match(root.innerHTML, /登记双选命中/);
  assert.doesNotMatch(root.innerHTML, /研究模拟/);
});
