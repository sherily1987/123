import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizeMarket, marketSummary, auditRows, loadMatchResources,
  marketRows, llmEvidence, renderMatchDrawer, createMatchDrawer,
} from "./match-drawer.js";

const canonicalJob = {
  identity: { match_id: "sporttery-88" },
  input: {
    odds: [2.2, 3.1, 3.6],
    ttg: { odds: [12, 5.2, 3.5, 3.65] },
    prediction_as_of: "2026-08-25T10:00:00+08:00",
    field_meta: { odds: { source: "中国体彩网移动端官方固定奖金接口" } },
  },
  outputs: [
    {
      track: "quant",
      model_version: "m9",
      probability_signature: "sig-88",
      final_1x2_pct: [42, 30, 28],
      mode: "market_only",
      recommendation_gate: { status: "MARKET_BASELINE" },
      top_scores: [{ score: "1-0", prob_pct: 18.2 }, { score: "1-1", prob_pct: 16.4 }],
      ou_2_5: { under_pct: 53.5, over_pct: 46.5 },
      risks: ["市场同源", "阵容尚未确认"],
      market_forecasts: {
        HAD: { calibration_status: "VALID" },
        TTG: { calibration_status: "UNFITTED", reason: "TTG 未经独立校准" },
        HAFU: { calibration_status: "UNFITTED" },
        CRS: { calibration_status: "UNFITTED" },
      },
    },
    {
      track: "llm",
      direction: "主胜",
      alt_direction: "平局",
      top_scores: ["1-0", "1-1", "2-1"],
      llm_ou25: "小2.5",
      strength: { type: "vote_share", value: 0.5714 },
      action: "skip",
      reason: "证据存在缺口，风险过高",
    },
  ],
};

test("missing markets keep their declared reason", () => {
  assert.deepEqual(normalizeMarket("TTG", { status: "UNFITTED" }), {
    code: "TTG", status: "UNFITTED", label: "未拟合",
  });
  assert.equal(normalizeMarket("CRS", null).label, "未提供");
});

test("provided market data is not mislabeled as missing", () => {
  assert.deepEqual(normalizeMarket("HAD", [2.1, 3.2, 3.8]), {
    code: "HAD", status: "AVAILABLE", label: "已提供",
  });
});

test("score-market odds retain actual selections instead of collapsing to missing", () => {
  assert.equal(marketSummary({ "1-0": 9.5, "0-0": 12 }), "1-0 9.5 / 0-0 12");
});

test("audit identity is never inferred from display labels", () => {
  const rows = auditRows({
    match_id: "sporttery-9",
    quant: { model_version: "m3", probability_signature: "abc" },
  });
  assert.deepEqual(rows.slice(0, 3).map((row) => row.value), ["sporttery-9", "m3", "abc"]);
});

test("a missing job does not block the match card and keeps its explicit state", async () => {
  const paths = [];
  const requestJson = async (path) => {
    paths.push(path);
    if (path.startsWith("/api/job")) {
      const error = new Error("not found");
      error.status = 404;
      throw error;
    }
    return { match_id: "sporttery-9", quant: { model_version: "m3" } };
  };
  const result = await loadMatchResources("sporttery-9", requestJson);
  assert.deepEqual(paths, ["/api/match/sporttery-9", "/api/job?match_id=sporttery-9"]);
  assert.equal(result.detail.match_id, "sporttery-9");
  assert.deepEqual(result.job, { state: "unavailable", message: "工单未提供" });
});

test("TTG separates offered official odds from an unfitted quant forecast", () => {
  const ttg = marketRows({}, canonicalJob).find((row) => row.code === "TTG");
  assert.equal(ttg.official.label, "已提供");
  assert.equal(ttg.model.label, "未拟合");
  assert.equal(ttg.model.reason, "TTG 未经独立校准");
});

test("audit resolves canonical job identity and quant version signature", () => {
  const byLabel = Object.fromEntries(auditRows({ match_id: "display-only" }, canonicalJob).map((row) => [row.label, row.value]));
  assert.equal(byLabel.match_id, "sporttery-88");
  assert.equal(byLabel["模型版本"], "m9");
  assert.equal(byLabel["概率签名"], "sig-88");
  assert.equal(byLabel.prediction_as_of, "2026-08-25T10:00:00+08:00");
  assert.equal(byLabel["数据来源"], "中国体彩网移动端官方固定奖金接口");
});

test("LLM vote share, action, and actual reason retain their non-probability semantics", () => {
  assert.deepEqual(llmEvidence({ llm: { vote_share: 0.2, action: "bet", reason: "stale" } }, canonicalJob), {
    direction: "主胜",
    altDirection: "平局",
    topScores: ["1-0", "1-1", "2-1"],
    ou25: "小2.5",
    voteShare: 0.5714,
    voteShareLabel: "投票占比（非概率）",
    action: "skip",
    reason: "证据存在缺口，风险过高",
    source: "工单 outputs[].track=llm",
  });
});

test("a ready job without identity or quant never borrows stale detail audit fields", () => {
  const staleDetail = {
    match_id: "stale-detail-id",
    quant: { model_version: "stale-m", probability_signature: "stale-sig" },
  };
  const readyJobWithOnlyLlm = { outputs: [{ track: "llm", action: "skip" }] };
  const byLabel = Object.fromEntries(auditRows(staleDetail, readyJobWithOnlyLlm).map((row) => [row.label, row.value]));
  assert.equal(byLabel.match_id, "未提供");
  assert.equal(byLabel["模型版本"], "未提供");
  assert.equal(byLabel["概率签名"], "未提供");
  assert.match(byLabel["概率签名来源"], /缺口/);
});

test("a ready canonical LLM output never borrows stale vote share or reason", () => {
  const staleDetail = { llm: { vote_share: 0.8, reason: "stale reason", action: "bet" } };
  const readyJobWithOnlyAction = { outputs: [{ track: "llm", action: "skip" }] };
  assert.deepEqual(llmEvidence(staleDetail, readyJobWithOnlyAction), {
    direction: "未提供",
    altDirection: "未提供",
    topScores: [],
    ou25: "未提供",
    voteShare: "未提供",
    voteShareLabel: "投票占比（非概率）",
    action: "skip",
    reason: "未提供",
    source: "工单 outputs[].track=llm",
  });
});

test("detail projection is explicitly labelled only when the job is unavailable", () => {
  const detail = { match_id: "detail-id", quant: { model_version: "m-detail", probability_signature: "sig-detail" }, llm: { vote_share: 0.8, action: "skip", reason: "detail reason" } };
  const audit = Object.fromEntries(auditRows(detail, null).map((row) => [row.label, row.value]));
  assert.equal(audit["概率签名来源"], "比赛详情 quant 投影（工单未提供）");
  assert.equal(llmEvidence(detail, null).source, "比赛详情 LLM 投影（工单未提供）");
});

function fakeDrawerRoot() {
  return { innerHTML: "", style: {}, querySelectorAll: () => [], querySelector: () => null };
}

test("rendered job error never exposes stale detail quant or LLM values", () => {
  const root = fakeDrawerRoot();
  renderMatchDrawer(root, {
    match_id: "sporttery-500",
    quant: { final_1x2_pct: [80, 10, 10], calibration: { applied: true } },
    llm: { vote_share: 0.8, action: "bet", reason: "stale error reason" },
  }, { state: "error", message: "工单读取失败：请求失败 (500)" });
  assert.match(root.innerHTML, /工单读取失败：请求失败 \(500\)/);
  assert.match(root.innerHTML, /读取失败/);
  assert.doesNotMatch(root.innerHTML, /80\.0 \/ 10\.0 \/ 10\.0%|0\.8|stale error reason|已应用/);
});

test("rendered ready job without quant never exposes stale detail quant evidence", () => {
  const root = fakeDrawerRoot();
  renderMatchDrawer(root, {
    match_id: "sporttery-quant-gap",
    quant: { final_1x2_pct: [80, 10, 10], calibration: { applied: true } },
  }, { state: "ready", job: { identity: { match_id: "sporttery-quant-gap" }, outputs: [] } });
  assert.match(root.innerHTML, /缺口：工单 quant 输出未提供/);
  assert.doesNotMatch(root.innerHTML, /80\.0 \/ 10\.0 \/ 10\.0%|已应用/);
});

test("drawer panel leaves sizing to responsive class styles", () => {
  const root = fakeDrawerRoot();
  renderMatchDrawer(root, { match_id: "sporttery-mobile" });
  const panelTag = root.innerHTML.match(/<section[^>]+role="dialog"[^>]*>/)?.[0] || "";
  assert.match(panelTag, /class="match-drawer"/);
  assert.doesNotMatch(panelTag, /style=/);
});

test("loading drawer provenance is reading-in-progress rather than projection or failure", () => {
  const root = fakeDrawerRoot();
  renderMatchDrawer(root, { match_id: "sporttery-loading" }, { state: "loading", message: "正在读取工单" });
  assert.match(root.innerHTML, /读取中/);
  assert.doesNotMatch(root.innerHTML, /投影|读取失败/);
});

test("ready drawer maps complete quant and LLM summaries from canonical outputs", () => {
  const root = fakeDrawerRoot();
  renderMatchDrawer(root, {
    match_id: "sporttery-88",
    quant: { risks: ["stale quant risk"] },
    llm: { direction: "客胜", top_scores: ["0-3"], llm_ou25: "大2.5" },
  }, { state: "ready", job: canonicalJob });

  assert.match(root.innerHTML, /推荐闸门<\/dt><dd>MARKET_BASELINE/);
  assert.match(root.innerHTML, /量化 Top 比分<\/dt><dd>1-0 18\.2% \/ 1-1 16\.4%/);
  assert.match(root.innerHTML, /量化大小球<\/dt><dd>小2\.5 53\.5% \/ 大2\.5 46\.5%/);
  assert.match(root.innerHTML, /核心风险<\/dt><dd>市场同源 \/ 阵容尚未确认/);
  assert.match(root.innerHTML, /LLM方向<\/dt><dd>主胜/);
  assert.match(root.innerHTML, /LLM备选方向<\/dt><dd>平局/);
  assert.match(root.innerHTML, /LLM Top 比分<\/dt><dd>1-0 \/ 1-1 \/ 2-1/);
  assert.match(root.innerHTML, /LLM大小球<\/dt><dd>小2\.5/);
  assert.doesNotMatch(root.innerHTML, /stale quant risk|0-3/);
});

test("modal drawer traps focus and restores inert background and trigger", async () => {
  const originalDocument = globalThis.document;
  const handlers = {};
  let firstFocused = 0;
  let lastFocused = 0;
  let triggerFocused = 0;
  const first = { focus: () => { firstFocused += 1; } };
  const last = { focus: () => { lastFocused += 1; } };
  const background = {
    inert: false,
    attributes: new Map([["aria-hidden", "false"]]),
    hasAttribute(name) { return this.attributes.has(name); },
    getAttribute(name) { return this.attributes.get(name) ?? null; },
    setAttribute(name, value) { this.attributes.set(name, String(value)); },
    removeAttribute(name) { this.attributes.delete(name); },
  };
  const root = {
    innerHTML: "", style: {},
    addEventListener(type, handler) { handlers[`root:${type}`] = handler; },
    querySelector(selector) { return selector === "[data-drawer-close]" ? first : null; },
    querySelectorAll(selector) {
      if (selector === "[data-drawer-tab]" || selector === "[role=tabpanel]") return [];
      return [first, last];
    },
  };
  const fakeDocument = {
    activeElement: last,
    addEventListener(type, handler) { handlers[`document:${type}`] = handler; },
  };
  globalThis.document = fakeDocument;
  try {
    const drawer = createMatchDrawer({
      root,
      backgroundElements: [background],
      requestJson: async (path) => path.startsWith("/api/match/")
        ? { match_id: "sporttery-88" } : canonicalJob,
    });
    await drawer.open("sporttery-88", { focus: () => { triggerFocused += 1; } });

    assert.equal(background.inert, true);
    assert.equal(background.getAttribute("aria-hidden"), "true");
    let prevented = 0;
    handlers["document:keydown"]({ key: "Tab", shiftKey: false, preventDefault: () => { prevented += 1; } });
    assert.equal(firstFocused >= 1, true);
    assert.equal(prevented, 1);

    fakeDocument.activeElement = first;
    handlers["document:keydown"]({ key: "Tab", shiftKey: true, preventDefault: () => { prevented += 1; } });
    assert.equal(lastFocused, 1);
    drawer.close();
    assert.equal(background.inert, false);
    assert.equal(background.getAttribute("aria-hidden"), "false");
    assert.equal(triggerFocused, 1);
  } finally {
    globalThis.document = originalDocument;
  }
});
