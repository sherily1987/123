import { requestJson } from "../api.js";
import { esc, displayMissing } from "../format.js";

const TASKS = {
  collect: { idle: "开始采集", running: "采集中", title: "采集" },
  predict: { idle: "开始补登记", running: "登记中", title: "预测登记" },
  llm: { idle: "开始 LLM", running: "LLM 运行中", title: "LLM 研究轨" },
  settle: { idle: "开始结算", running: "结算中", title: "结算" },
  backtest: { idle: "开始回测", running: "回测中", title: "回测" },
};

function activeRunList(activeRuns) {
  if (Array.isArray(activeRuns)) return activeRuns;
  if (Array.isArray(activeRuns?.runs)) return activeRuns.runs;
  return Object.values(activeRuns || {});
}

export function taskActionState(kind, activeRuns = []) {
  const config = TASKS[kind];
  if (!config) return { disabled: true, label: "未知任务" };
  const running = activeRunList(activeRuns).some((run) => (
    (run?.kind || run?.run_type) === kind && run?.status === "running"
  ));
  return { disabled: running, label: running ? config.running : config.idle };
}

export async function startTask(kind, salesDay, request = requestJson) {
  if (!TASKS[kind]) throw new TypeError(`unsupported task kind: ${kind}`);
  const options = { method: "POST" };
  if (kind !== "backtest") {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify({ sales_day: salesDay });
  }
  return request(`/api/${kind}`, options);
}

function abortError() {
  if (typeof DOMException === "function") return new DOMException("Polling aborted", "AbortError");
  const error = new Error("Polling aborted");
  error.name = "AbortError";
  return error;
}

function waitForPoll(intervalMs, signal) {
  if (signal?.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const timer = setTimeout(done, Math.max(0, intervalMs));
    function done() {
      signal?.removeEventListener?.("abort", aborted);
      resolve();
    }
    function aborted() {
      clearTimeout(timer);
      reject(abortError());
    }
    signal?.addEventListener?.("abort", aborted, { once: true });
  });
}

export async function pollRun(runId, {
  signal, onUpdate = () => {}, request = requestJson, intervalMs = 1000,
} = {}) {
  while (true) {
    if (signal?.aborted) throw abortError();
    const run = await request(`/api/run/${encodeURIComponent(runId)}`, { signal });
    onUpdate(run);
    if (run?.status === "done" || run?.status === "error") return run;
    await waitForPoll(intervalMs, signal);
  }
}

export function retryFailed(runId, request = requestJson) {
  return request(`/api/run/${encodeURIComponent(runId)}/retry-failed`, { method: "POST" });
}

function elapsedSeconds(startedAt, finishedAt) {
  const start = Date.parse(startedAt || "");
  const end = finishedAt ? Date.parse(finishedAt) : Date.now();
  return Number.isFinite(start) && Number.isFinite(end) && end >= start
    ? Math.floor((end - start) / 1000) : null;
}

function elapsedText(startedAt, finishedAt) {
  const seconds = elapsedSeconds(startedAt, finishedAt);
  if (seconds === null) return "尚未计时";
  const minutes = Math.floor(seconds / 60);
  return minutes ? `${minutes}分${seconds % 60}秒` : `${seconds}秒`;
}

function remainingText(run, done, total) {
  if (run?.status === "done" || (total > 0 && done >= total)) return "预计剩余：已完成";
  if (run?.status !== "running" || total <= 0 || done <= 0) return "预计剩余：暂无法估算";
  const elapsed = elapsedSeconds(run?.started_at);
  if (elapsed === null || elapsed <= 0) return "预计剩余：暂无法估算";
  const seconds = Math.max(1, Math.round(elapsed / done * (total - done)));
  if (seconds < 60) return "预计剩余约 不到1分钟";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `预计剩余约 ${minutes}分钟`;
  const hours = Math.floor(minutes / 60);
  return `预计剩余约 ${hours}小时${minutes % 60}分钟`;
}

function taskProgressPanel(kind, run, done, total, failed) {
  const status = run?.status || "idle";
  const progress = run?.progress || {};
  const current = progress.current || {};
  const fixture = current.home || current.away
    ? `${displayMissing(current.match_num, current.match_id || "当前场次")} · ${displayMissing(current.home, "主队")} vs ${displayMissing(current.away, "客队")}`
    : displayMissing(current.match_num, "尚未进入逐场处理");
  const elapsed = elapsedText(run?.started_at, run?.finished_at);
  const remaining = remainingText(run, done, total);
  if (status === "running" && total <= 0) {
    return `<aside class="task-progress-panel is-running" aria-label="${esc(TASKS[kind].title)}实时进度"><div class="task-progress-head"><strong>实时进度</strong><span>准备中</span></div><div class="task-progress-bar is-indeterminate" aria-hidden="true"><i></i></div><p>正在准备，目标数确认后显示逐场进度</p><p>${esc(remaining)}</p><dl><div><dt>阶段</dt><dd>${esc(displayMissing(progress.stage, run?.message || "准备"))}</dd></div><div><dt>已运行</dt><dd>${esc(elapsed)}</dd></div></dl></aside>`;
  }
  const percent = total > 0 ? Math.min(100, Math.max(0, Math.round(done / total * 100))) : 0;
  const stateLabel = status === "done" ? "已完成" : status === "error" ? "失败" : status === "running" ? "运行中" : "等待启动";
  const bar = total > 0
    ? `<progress class="task-progress-native" value="${esc(done)}" max="${esc(total)}">${esc(percent)}%</progress>`
    : '<div class="task-progress-track" aria-hidden="true"><i style="width:0%"></i></div>';
  return `<aside class="task-progress-panel is-${esc(status)}" aria-label="${esc(TASKS[kind].title)}实时进度"><div class="task-progress-head"><strong>实时进度</strong><span>${esc(stateLabel)}</span></div>${bar}<p class="task-progress-percent">${esc(percent)}%</p><p>${total > 0 ? `已完成 ${esc(done)}/${esc(total)}` : "等待任务启动"} · 成功 ${esc(done)} · 失败 ${esc(failed)}</p><p>${esc(remaining)}</p><dl><div><dt>阶段</dt><dd>${esc(displayMissing(progress.stage, stateLabel))}</dd></div><div><dt>当前</dt><dd>${esc(fixture)}</dd></div><div><dt>耗时</dt><dd>${esc(elapsed)}</dd></div></dl></aside>`;
}

function taskCard(kind, run, activeRuns) {
  const action = taskActionState(kind, activeRuns);
  const total = Number.isFinite(Number(run?.total)) ? Number(run.total) : 0;
  const done = Number.isFinite(Number(run?.done)) ? Number(run.done) : 0;
  const failed = Number.isFinite(Number(run?.failed))
    ? Number(run.failed)
    : (run?.status === "error" ? Math.max(0, total - done) : 0);
  const logs = Array.isArray(run?.logs) ? run.logs : [];
  const progress = run?.progress || {};
  const reconnect = run?.status === "running" && run?.polling === "disconnected"
    ? `<button class="button" type="button" data-task-reconnect="${esc(kind)}" data-run-id="${esc(run.id)}">重新连接</button>` : "";
  const retry = ["predict", "llm"].includes(kind) && ["done", "error"].includes(run?.status) && failed > 0
    ? `<button class="button" type="button" data-task-retry="${esc(kind)}" data-run-id="${esc(run.id)}">仅重试失败项</button>` : "";
  const llmProgress = kind === "llm" && Object.keys(progress).length ? renderLlmProgress(progress) : "";
  const progressPanel = taskProgressPanel(kind, run, done, total, failed);
  return `<section class="page-intro task-card" data-task-card="${esc(kind)}"><div class="task-card-grid"><div class="task-card-main"><h2>${esc(TASKS[kind].title)}</h2>
    <p>开始：${esc(displayMissing(run?.started_at, "未启动"))} · 状态：${esc(displayMissing(run?.status, "idle"))}</p>
    <p>当前消息：${esc(displayMissing(run?.message, "暂无"))}</p>${llmProgress}
    <button class="button button--primary" type="button" data-task-start="${esc(kind)}"${action.disabled ? " disabled" : ""}>${esc(action.label)}</button> ${reconnect} ${retry}
    <details><summary>日志</summary><ol>${logs.map((line) => `<li>${esc(line)}</li>`).join("") || "<li>暂无日志</li>"}</ol></details></div>${progressPanel}</div></section>`;
}

function joined(values, fallback = "无") {
  return Array.isArray(values) && values.length ? values.map(esc).join("、") : fallback;
}

function renderLlmProgress(progress) {
  const current = progress.current || {};
  const evidence = progress.evidence || {};
  const result = progress.latest_result || {};
  const fixture = current.home || current.away
    ? `${esc(displayMissing(current.match_num, current.match_id || "当前场次"))} · ${esc(displayMissing(current.home, "主队"))} vs ${esc(displayMissing(current.away, "客队"))}`
    : "尚未进入逐场生成";
  const output = result.direction
    ? `<p><strong>临时方向：</strong>${esc(result.direction)} · <strong>Top 比分：</strong>${joined(result.top_scores, "未提供")} · <strong>行动：</strong>${esc(displayMissing(result.action, "observe"))}</p><p><strong>原因：</strong>${esc(displayMissing(result.reason, "研究输出，等待最终保存"))}</p>`
    : `<p>临时结果：尚未生成</p>`;
  return `<section class="task-live" aria-label="LLM 实时进度"><h3>LLM 实时进度</h3>
    <p><strong>阶段：</strong>${esc(displayMissing(progress.stage, "准备"))}</p>
    <p><strong>当前比赛：</strong>${fixture}</p>
    <p><strong>证据：</strong>${esc(displayMissing(evidence.status, "待检查"))} · 可用：${joined(evidence.available)} · 缺口：${joined(evidence.missing)}</p>
    <p><strong>逐场统计：</strong>成功 ${esc(progress.succeeded || 0)} · 跳过 ${esc(progress.skipped || 0)} · 失败 ${esc(progress.failed || 0)}</p>${output}</section>`;
}

function bindTaskActions(root) {
  if (!root?.addEventListener || root.dataset?.taskActionsBound) return;
  if (root.dataset) root.dataset.taskActionsBound = "true";
  root.addEventListener("click", (event) => {
    const context = root.__taskContext || {};
    const start = event.target.closest?.("[data-task-start]");
    if (start && !start.disabled) context.onStartTask?.(start.dataset.taskStart);
    const reconnect = event.target.closest?.("[data-task-reconnect]");
    if (reconnect) context.onReconnect?.(reconnect.dataset.taskReconnect, Number(reconnect.dataset.runId));
    const retry = event.target.closest?.("[data-task-retry]");
    if (retry) context.onRetryFailed?.(retry.dataset.taskRetry, Number(retry.dataset.runId));
  });
}

export function renderTasks(root, context = {}) {
  const activeRuns = context.activeRuns || {};
  root.__taskContext = context;
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">任务中心</h1><p>同类任务运行时不可重复启动。轮询在完成、失败、离页或网络错误时停止；网络中断后可手动重新连接。</p></section>
    ${Object.keys(TASKS).map((kind) => taskCard(kind, activeRuns[kind], activeRuns)).join("")}`;
  bindTaskActions(root);
}
