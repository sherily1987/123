import { esc, displayMissing } from "../format.js";
import { filterMatches, isOnSale, OVERVIEW_TODO_STATUSES, resolveMatchRowCollection } from "./scanner.js";

function value(value) {
  return esc(displayMissing(value, "未提供"));
}

export function overviewTodoCounts(matches, options = {}) {
  if (!Array.isArray(matches)) return Object.fromEntries(OVERVIEW_TODO_STATUSES.map((status) => [status, undefined]));
  return Object.fromEntries(OVERVIEW_TODO_STATUSES.map((status) => [status, filterMatches(matches, { ...options, status }).length]));
}

function renderTodo(label, count, description) {
  return `<li class="todo-row"><div class="todo-action"><span>${esc(label)}</span><b>${count}</b></div><small>${esc(description)}</small></li>`;
}

export function workflowProgress(matches) {
  if (!Array.isArray(matches)) return [];
  const total = matches.length;
  return [
    ["采集官方开售信息", total],
    ["确认 HAD 与赛前时点", matches.filter((match) => match?.has_odds).length],
    ["量化预测并正式登记", matches.filter((match) => Boolean(match?.quant)).length],
    ["补齐 LLM 证据研究轨", matches.filter((match) => Boolean(match?.llm)).length],
    ["赛后按 90 分钟结算和回测", matches.filter((match) => Array.isArray(match?.result?.score_90)).length],
  ].map(([label, completed]) => ({ label, completed, total }));
}

function emitMatchSelect(root, matchId, context) {
  if (!matchId) return;
  const detail = { matchId };
  if (typeof context.onMatchSelect === "function") context.onMatchSelect(detail);
  if (typeof globalThis.CustomEvent === "function" && typeof root?.dispatchEvent === "function") {
    root.dispatchEvent(new CustomEvent("matchselect", { detail }));
  }
}

function bindOverviewActions(root, context) {
  if (!root?.addEventListener || root.dataset?.overviewActionsBound) return;
  if (root.dataset) root.dataset.overviewActionsBound = "true";
  root.addEventListener("click", (event) => {
    const trigger = event.target.closest?.("[data-overview-match-id]");
    if (!trigger) return;
    trigger.focus?.({ preventScroll: true });
    emitMatchSelect(root, trigger.dataset.overviewMatchId, context);
  });
}

export function renderOverview(root, context = {}) {
  const board = context.board || {};
  const strategy = context.dailyStrategy || {};
  const budget = strategy.budget || {};
  const matchCollection = resolveMatchRowCollection(context);
  const { available: hasMatchRows, rows: matches } = matchCollection;
  const filterOptions = { now: context.now, nearKickoffMinutes: context.nearKickoffMinutes };
  const todoCounts = overviewTodoCounts(hasMatchRows ? matches : null, filterOptions);
  const pending = hasMatchRows ? filterMatches(matches, { ...filterOptions, status: "todo" }).length : undefined;
  const evidenceComplete = hasMatchRows ? filterMatches(matches, { ...filterOptions, status: "evidence_complete" }).length : undefined;
  const onSale = hasMatchRows ? matches.filter(isOnSale).length : undefined;
  const registered = hasMatchRows ? matches.filter((match) => Boolean(match.quant)).length : undefined;
  const modelVersion = context.versionGovernance?.release?.current_model_version;
  const kpis = [
    ["已开售", onSale],
    ["已登记", registered],
    ["待处理", pending],
    ["证据完成", evidenceComplete],
    ["当前模型版本", modelVersion],
  ];
  const todos = [
    renderTodo("未登记", value(todoCounts.missing), "有 HAD 但尚未正式登记"),
    renderTodo("证据缺口", value(todoCounts.evidence_missing), "证据字段未完成"),
    renderTodo("临近开球", value(todoCounts.near_kickoff), "默认未来两小时内开球"),
    renderTodo("身份冲突", value(todoCounts.identity_conflict), "仅显示明确标记的身份冲突"),
  ];
  const matchSummary = (hasMatchRows ? matches : []).map((match) =>
    `<button type="button" class="live-match-card" data-overview-match-id="${esc(match.match_id)}" aria-label="查看比赛详情：${esc(displayMissing(match.home, "未提供"))} 对 ${esc(displayMissing(match.away, "未提供"))}"><div class="match-meta"><span>${esc(displayMissing(match.match_num, "未编号"))}</span><time>${esc(displayMissing(match.kickoff, "开球时间未提供"))}</time></div><div class="match-line"><strong>${esc(displayMissing(match.home, "未提供"))}</strong><span>VS</span><strong>${esc(displayMissing(match.away, "未提供"))}</strong></div><div class="match-state"><span>${match.has_odds ? "HAD 已开售" : "等待开售"}</span><b>${match.quant ? "已登记" : "待处理"}</b><small>查看比赛详情</small></div></button>`,
  ).join("") || '<div class="empty-panel">当前没有可展示的比赛摘要。</div>';
  const workflow = workflowProgress(hasMatchRows ? matches : null);
  const hasStrategyItems = Array.isArray(strategy.single_purchase_recommendations)
    || Array.isArray(strategy.combo_purchase_recommendations);
  const strategyItemCount = hasStrategyItems
    ? (Array.isArray(strategy.single_purchase_recommendations) ? strategy.single_purchase_recommendations.length : 0)
      + (Array.isArray(strategy.combo_purchase_recommendations) ? strategy.combo_purchase_recommendations.length : 0)
    : undefined;
  const autoStrategyStatus = context.autoStrategy?.status === "running"
    ? '<p class="risk-note" aria-live="polite">正在自动生成当前销售日策略…</p>'
    : context.autoStrategy?.status === "error"
      ? `<p class="risk-note" aria-live="polite">${esc(context.autoStrategy.message)}</p>`
      : "";

  root.innerHTML = `<section class="overview-hero" aria-labelledby="page-title">
      <div class="hero-command"><p class="system-kicker"><span></span> 实时分析系统 · MARKET_ONLY</p><p class="eyebrow">FOOTBALL QUANT INTELLIGENCE</p><h1 id="page-title">专业足球<br><em>预测工作台</em></h1><p class="hero-copy">统一查看体彩开售、正式登记、证据研究和赛后回测。量化与 LLM 两条轨道独立呈现，不合并概率语义。</p><section class="overview-kpis" aria-label="今日关键指标">${kpis.map(([label, count]) => `<article class="stat"><b>${value(count)}</b><span>${esc(label)}</span></article>`).join("")}</section></div>
      <div class="hero-live"><div class="section-heading"><div><p class="eyebrow">LIVE MATCHES</p><h2>今日待处理比赛</h2></div></div><div class="live-match-list">${matchSummary}</div></div>
    </section>
    <section class="dashboard-grid">
      <article class="dashboard-panel panel-todos"><div class="section-heading"><div><p class="eyebrow">ACTION QUEUE</p><h2>今日待办</h2></div></div><ul class="todo-list">${todos.join("")}</ul></article>
      <article class="dashboard-panel panel-strategy"><div class="section-heading"><div><p class="eyebrow">100 CNY PLAN</p><h2>娱乐策略摘要</h2></div></div><p class="strategy-name">${esc(displayMissing(strategy.display?.strategy_type, "策略数据未提供"))}</p><div class="budget-strip"><span><b>${value(budget.daily_budget_amount)}</b>预算</span><span><b>${value(budget.allocated_amount)}</b>已分配</span><span><b>${value(budget.preserved_amount)}</b>保留</span></div><p class="risk-note">策略项目 ${value(strategyItemCount)} · ${esc(displayMissing(strategy.display?.edge_label, "未提供正EV验证状态"))}</p>${autoStrategyStatus}</article>
      <article class="dashboard-panel panel-workflow"><div class="section-heading"><div><p class="eyebrow">PIPELINE</p><h2>执行流程</h2></div></div><ol class="workflow-list">${workflow.length ? workflow.map((step, index) => `<li><i>${index + 1}</i><span>${esc(step.label)}</span><strong>${esc(step.completed)}/${esc(step.total)} 完成</strong></li>`).join("") : "<li>当前销售日数据未提供</li>"}</ol></article>
    </section>`;
  bindOverviewActions(root, context);
}
