import test from "node:test";
import assert from "node:assert/strict";
import { evidenceStatus, renderEvidence } from "./evidence.js";
import { pollRun, renderTasks, startTask, taskActionState } from "./tasks.js";
import { renderVersions, versionActions } from "./versions.js";

test("same task is disabled while running", () => {
  assert.deepEqual(taskActionState("collect", [{ kind: "collect", status: "running" }]), { disabled: true, label: "采集中" });
  assert.deepEqual(taskActionState("collect", {
    runs: [{ run_type: "collect", status: "running", id: 91 }],
  }), { disabled: true, label: "采集中" });
});

test("successful terminal tasks without failures do not offer an empty retry", () => {
  const root = { innerHTML: "", addEventListener() {}, dataset: {} };
  renderTasks(root, { activeRuns: { predict: {
    id: 31, kind: "predict", status: "done", total: 2, done: 2, failed: 0,
  } } });
  assert.doesNotMatch(root.innerHTML, /data-task-retry="predict"/);

  renderTasks(root, { activeRuns: { predict: {
    id: 32, kind: "predict", status: "done", total: 2, done: 1, failed: 1,
  } } });
  assert.match(root.innerHTML, /data-task-retry="predict"/);
});

test("running LLM task renders its current fixture, evidence summary, partial output and recent events", () => {
  const root = { innerHTML: "", addEventListener() {}, dataset: {} };
  renderTasks(root, { activeRuns: { llm: {
    id: 44, kind: "llm", status: "running", total: 3, done: 1,
    message: "LLM 1/3",
    progress: {
      stage: "生成分析",
      current: { match_id: "sporttery-2041051", match_num: "周一002", home: "达曼协定", away: "利雅胜利" },
      evidence: { status: "有缺口", available: ["近5场", "伤停"], missing: ["官方首发"] },
      latest_result: { direction: "客胜", top_scores: ["0-2", "1-2"], action: "observe", reason: "证据存在缺口" },
      succeeded: 1, skipped: 0, failed: 0,
    },
    logs: ["证据读取完成", "周一002 开始生成"],
  } } });
  assert.match(root.innerHTML, /LLM 实时进度/);
  assert.match(root.innerHTML, /生成分析/);
  assert.match(root.innerHTML, /周一002 · 达曼协定 vs 利雅胜利/);
  assert.match(root.innerHTML, /可用：近5场、伤停/);
  assert.match(root.innerHTML, /缺口：官方首发/);
  assert.match(root.innerHTML, /临时方向：<\/strong>客胜/);
  assert.match(root.innerHTML, /Top 比分：<\/strong>0-2、1-2/);
  assert.match(root.innerHTML, /行动：<\/strong>observe/);
  assert.match(root.innerHTML, /证据存在缺口/);
  assert.match(root.innerHTML, /证据读取完成/);
});

test("running task with unknown total shows an indeterminate progress panel", () => {
  const root = { innerHTML: "", addEventListener() {}, dataset: {} };
  renderTasks(root, { activeRuns: { llm: {
    id: 45, kind: "llm", status: "running", total: 0, done: 0,
    started_at: "2026-08-25T14:06:01+00:00", message: "LLM 轨准备 2026-08-26…",
    progress: { stage: "准备证据", current: {} },
  } } });
  assert.match(root.innerHTML, /task-card-grid/);
  assert.match(root.innerHTML, /aria-label="LLM 研究轨实时进度"/);
  assert.match(root.innerHTML, /task-progress-bar is-indeterminate/);
  assert.match(root.innerHTML, /正在准备，目标数确认后显示逐场进度/);
  assert.match(root.innerHTML, /预计剩余：暂无法估算/);
  assert.doesNotMatch(root.innerHTML, /0\/—/);
});

test("running task with a known total shows real percentage progress", () => {
  const root = { innerHTML: "", addEventListener() {}, dataset: {} };
  renderTasks(root, { activeRuns: { llm: {
    id: 46, kind: "llm", status: "running", total: 4, done: 1, failed: 0,
    started_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
    message: "LLM 1/4", progress: { stage: "生成分析", current: { match_num: "周二001" } },
  } } });
  assert.match(root.innerHTML, /<progress[^>]*value="1"[^>]*max="4"/);
  assert.match(root.innerHTML, /25%/);
  assert.match(root.innerHTML, /已完成 1\/4/);
  assert.match(root.innerHTML, /预计剩余约 (29|30)分钟/);
});

test("an explicit empty evidence gap list is authoritative", () => {
  assert.equal(evidenceStatus({
    llm: { evidence_missing_fields: [] },
    lights: { form: "missing", lineup: "not_written", injury: "none" },
  }), "完整");
});

test("authoritative gap metadata is collected even without lights or evidence files", () => {
  const root = { innerHTML: "" };

  renderEvidence(root, { board: { matches: [{ llm: { evidence_missing_fields: [] } }] } });
  assert.match(root.innerHTML, /<dt>证据状态<\/dt><dd>完整<\/dd>[\s\S]*<dt>冲突<\/dt><dd>无<\/dd>[\s\S]*<dt>缺口<\/dt><dd>无<\/dd>/);

  renderEvidence(root, { board: { matches: [{ llm: {} }] } });
  assert.match(root.innerHTML, /<dt>证据状态<\/dt><dd>未采集<\/dd>/);

  renderEvidence(root, { board: { matches: [{
    llm: { evidence_missing_fields: ["首发", "伤停"] },
  }] } });
  assert.match(root.innerHTML, /<dt>证据状态<\/dt><dd>有缺口<\/dd>[\s\S]*<dt>缺口<\/dt><dd>首发、伤停<\/dd>/);
  const gapCell = root.innerHTML.match(/<dt>缺口<\/dt><dd>([^<]*)<\/dd>/)?.[1];
  assert.equal(gapCell, "首发、伤停");
  assert.equal(gapCell.split("、").length, 2);
});

test("evidence renderer uses explicit empty API arrays and only falls back when absent", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041050", home: "济州SK", away: "浦项制铁",
    llm: { evidence_missing_fields: [], evidence_chain_fields: [] },
    lights: { form: "missing", lineup: "not_written", injury: "none" },
  }] } });
  assert.match(root.innerHTML, /<dt>证据状态<\/dt><dd>完整<\/dd>[\s\S]*<dt>来源\/维度数<\/dt><dd>0<\/dd>[\s\S]*<dt>冲突<\/dt><dd>无<\/dd>[\s\S]*<dt>缺口<\/dt><dd>无<\/dd>/);

  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041051", home: "甲", away: "乙",
    llm: {},
    lights: { form: "missing", lineup: "not_written", injury: "none" },
  }] } });
  assert.match(root.innerHTML, /<dt>证据状态<\/dt><dd>有缺口<\/dd>[\s\S]*<dt>缺口<\/dt><dd>近5场、首发、伤停<\/dd>/);
});

test("evidence renderer exposes canonical freshness refs status and conflicts", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041052", sales_day: "2026-08-25",
    llm: {
      evidence_status: "GAP",
      evidence_missing_fields: ["starting_xi"],
      evidence_chain_fields: ["recent_form"],
      evidence_collected_at: "2026-08-25T00:00:00+08:00",
      evidence_age_minutes: 61.5,
      evidence_refs: { snapshot: "a.json", browser: "b.json" },
      evidence_conflicts: ["starting_xi:provider_mismatch"],
    },
  }] }, salesDay: "2026-08-25" });
  assert.match(root.innerHTML, /冲突/);
  assert.match(root.innerHTML, /GAP/);
  assert.match(root.innerHTML, /2026-08-25T00:00:00\+08:00/);
  assert.match(root.innerHTML, /61\.5 分钟/);
  assert.match(root.innerHTML, /a\.json、b\.json/);
  assert.match(root.innerHTML, /starting_xi:provider_mismatch/);
});

test("evidence renderer expands detailed injury and starting lineup in Chinese", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041038", match_num: "周一011", home: "博塔弗戈", away: "巴竞技",
    late_info: {
      injury: "VALID", injury_zh: "有效", injury_collected_at: "2026-08-24T22:30:00+00:00",
      injury_detail: {
        home: { team: "博塔弗戈", players: [{ name: "甲球员", pos: "后卫", type: "伤" }] },
        away: { team: "巴竞技", players: [{ name: "乙球员", pos: "前锋", type: "停赛" }] },
      },
      lineup: "VALID", lineup_zh: "有效", lineup_collected_at: "2026-08-24T22:31:00+00:00",
      lineup_detail: {
        home: { starting_count: 2, starting: ["主门将", "主后卫"], missing: [] },
        away: { starting_count: 2, starting: ["客门将", "客前锋"], missing: ["客中场"] },
      },
    },
  }] } });
  assert.match(root.innerHTML, /<details[^>]*class="evidence-match"/);
  assert.match(root.innerHTML, /伤停信息[\s\S]*博塔弗戈[\s\S]*甲球员（后卫，伤）/);
  assert.match(root.innerHTML, /巴竞技[\s\S]*乙球员（前锋，停赛）/);
  assert.match(root.innerHTML, /首发名单[\s\S]*主门将、主后卫/);
  assert.match(root.innerHTML, /客门将、客前锋[\s\S]*缺席：<\/strong>客中场/);
  assert.match(root.innerHTML, /采集时间：2026-08-24T22:31:00\+00:00/);
});

test("evidence renderer keeps unavailable injury and lineup explicitly uncollected", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041051", home: "达曼协定", away: "利雅胜利",
    late_info: { injury: "EMPTY_UNCONFIRMED", injury_zh: "空结果未确认", lineup: "UNAVAILABLE", lineup_zh: "未采集" },
  }] } });
  assert.match(root.innerHTML, /伤停信息[\s\S]*空结果未确认[\s\S]*没有可展示的伤停球员/);
  assert.match(root.innerHTML, /首发名单[\s\S]*未采集[\s\S]*没有可展示的首发名单/);
});

test("evidence renderer labels an audited valid empty absence response as collected zero", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041053", home: "甲", away: "乙",
    evidence_detail: {
      injury: { status: "VALID", status_zh: "有效", source_id: "API-Sports", refreshed_at: "2026-08-25T14:07:13+00:00", home: { team: "甲", players: [] }, away: { team: "乙", players: [] } },
      suspensions: { status: "VALID", status_zh: "有效", source_id: "API-Sports", refreshed_at: "2026-08-25T14:07:13+00:00", home: [], away: [] },
    },
  }] } });
  assert.match(root.innerHTML, /伤停信息[\s\S]*有效[\s\S]*已采集：暂无已报告的伤停球员/);
  assert.match(root.innerHTML, /停赛信息[\s\S]*有效[\s\S]*已采集：暂无已报告的停赛球员/);
});

test("evidence renderer writes all collected audited facts in Chinese sections", () => {
  const root = { innerHTML: "" };
  renderEvidence(root, { board: { matches: [{
    match_id: "sporttery-2041038", home: "博洛尼亚", away: "拉齐奥",
    evidence_detail: {
      team_stats: { status_zh: "有效", source_id: "体彩官方赛前数据", refreshed_at: "2026-08-24T04:18:25+00:00", summary: { sample_legs: 10, home_goal_avg: 1.6, away_goal_avg: 2.2, home_loss_avg: 1.3, away_loss_avg: 1.5, note: "近10场统计" } },
      recent_form: { status_zh: "有效", source_id: "API-Sports", home: [{ date: "2026-05-23", league: "意甲", home: "博洛尼亚", away: "国际米兰", score_90: "3-3" }], away: [{ date: "2026-05-23", league: "意甲", home: "拉齐奥", away: "比萨", score_90: "2-1" }] },
      suspensions: { status_zh: "空结果未确认", source_id: "API-Sports", home: [], away: [] },
      starting_xi: { status_zh: "待刷新", missing_reason_zh: "官方首发尚未发布或未附加" },
    },
  }] } });
  assert.match(root.innerHTML, /球队数据[\s\S]*近10场[\s\S]*主队场均进球 1\.6[\s\S]*客队场均进球 2\.2/);
  assert.match(root.innerHTML, /近期状态[\s\S]*博洛尼亚 vs 国际米兰：3-3[\s\S]*拉齐奥 vs 比萨：2-1/);
  assert.match(root.innerHTML, /停赛信息[\s\S]*空结果未确认[\s\S]*不能推断无人停赛/);
  assert.match(root.innerHTML, /官方首发尚未发布或未附加/);
});

test("ordinary version page exposes no mutation action", () => {
  assert.deepEqual(versionActions({ read_only_version_governance: true }), []);
});

test("task start posts the selected sales day to the exact endpoint", async () => {
  const calls = [];
  const result = await startTask("llm", "2026-08-25", async (path, options) => {
    calls.push([path, options]);
    return { run_id: 17, status: "started" };
  });
  assert.equal(result.run_id, 17);
  assert.deepEqual(calls, [["/api/llm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sales_day: "2026-08-25" }),
  }]]);
});

test("polling stops immediately on terminal state", async () => {
  const updates = [];
  let calls = 0;
  const result = await pollRun(23, {
    request: async () => {
      calls += 1;
      return { id: 23, run_type: "predict", status: "done", done: 2, total: 2, message: "ok" };
    },
    onUpdate: (run) => updates.push(run.status),
    intervalMs: 0,
  });
  assert.equal(result.status, "done");
  assert.equal(calls, 1);
  assert.deepEqual(updates, ["done"]);
});

test("polling stops on network error and honors an already-aborted signal", async () => {
  let networkCalls = 0;
  await assert.rejects(pollRun(24, {
    request: async () => { networkCalls += 1; throw new Error("offline"); }, intervalMs: 0,
  }), /offline/);
  assert.equal(networkCalls, 1);

  const controller = new AbortController();
  controller.abort();
  let abortedCalls = 0;
  await assert.rejects(pollRun(25, {
    signal: controller.signal, request: async () => { abortedCalls += 1; }, intervalMs: 0,
  }), (error) => error.name === "AbortError");
  assert.equal(abortedCalls, 0);
});

test("evidence and task output escapes all dynamic user-visible text", () => {
  const root = { innerHTML: "", addEventListener() {}, dataset: {} };
  renderEvidence(root, { board: { matches: [{
    match_id: '<img onerror="x">', home: "<b>主</b>", away: "客", lights: null,
  }] } });
  assert.doesNotMatch(root.innerHTML, /<img|<b>主/);
  assert.match(root.innerHTML, /&lt;img onerror=&quot;x&quot;&gt;/);

  renderTasks(root, { activeRuns: { predict: {
    id: 3, kind: "predict", status: "error", message: '<svg onload="x">',
    logs: ["<script>bad</script>"], total: 2, done: 1,
  } } });
  assert.doesNotMatch(root.innerHTML, /<svg|<script>/);
  assert.match(root.innerHTML, /&lt;svg onload=&quot;x&quot;&gt;/);
});

test("version page renders drift but never renders release mutation controls", () => {
  const root = { innerHTML: "" };
  renderVersions(root, { versionGovernance: {
    read_only_version_governance: true,
    identity: { model_version: '<m5>', probability_signature: "abc" },
    current: { settled: 9, pending: 2 },
    signature_drift: [{ match_id: '<bad>' }],
    release_lock: { status: "MISMATCH" },
    actions: ["release-lock"],
  } });
  assert.match(root.innerHTML, /&lt;m5&gt;/);
  assert.match(root.innerHTML, /签名漂移 1 条/);
  assert.doesNotMatch(root.innerHTML, /MISMATCH|发布锁/);
  assert.doesNotMatch(root.innerHTML, /<(?:button|form)[^>]*(?:release|version)/);
});
