import test from "node:test";
import assert from "node:assert/strict";
import { renderBacktest } from "./backtest.js";

test("history shows single-pick and double-direction settlement separately", () => {
  const root = { innerHTML: "" };
  const record = {
    day: "2026-08-27", kickoff: "2026-08-27T03:00:00+08:00",
    league: "欧冠", match_num: "周三005", home: "采列", away: "客队",
    settled: true, hit: false, quant_double_scored: true, quant_double_hit: true,
    quant: {
      direction: "主胜", alt_direction: "平局", direction_label: "主胜略优，防平",
      final_1x2_pct: [39.4, 29.8, 30.7], top_scores: [],
    },
    result: { score_90: [1, 1], direction: "平局" },
  };

  renderBacktest(root, { params: { view: "history" }, history: { sections: [{ matches: [record] }] } });

  assert.match(root.innerHTML, /主胜略优，防平/);
  assert.match(root.innerHTML, /单项未命中/);
  assert.match(root.innerHTML, /方向命中/);
});
