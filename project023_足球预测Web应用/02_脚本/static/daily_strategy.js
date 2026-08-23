(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.DailyStrategyView = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  "use strict";

  const MARKET_NAMES = { HAD: "胜平负", TTG: "进球数", HAFU: "半全场", CRS: "比分" };

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function amount(value) {
    const n = Number(value || 0);
    return Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  }

  function singleRow(row) {
    return `<tr>
      <td><span class="strategy-market">${esc(MARKET_NAMES[row.market] || row.market)}</span></td>
      <td>${esc(row.match_num || "-")}</td>
      <td class="strategy-match">${esc(row.home)} vs ${esc(row.away)}</td>
      <td><strong>${esc(row.selection)}</strong></td>
      <td>${esc(row.odds)}</td>
      <td><strong>${amount(row.stake_amount)}元</strong></td>
    </tr>`;
  }

  function comboCard(row) {
    const legs = (row.legs || []).map(leg =>
      `<li>${esc(leg.match_num || "-")} ${esc(leg.home)} vs ${esc(leg.away)}：<strong>${esc(leg.selection)}</strong></li>`
    ).join("");
    return `<article class="strategy-combo">
      <div><strong>${esc(row.legs_count)}串1</strong><span>${amount(row.stake_amount)}元</span></div>
      <ul>${legs}</ul>
      <p>组合参考赔率 ${esc(row.combined_odds || "-")}</p>
    </article>`;
  }

  function backtestBlock(report) {
    if (!report) return "";
    const s = report.summary || {};
    if (!report.snapshot_count) {
      return `<div class="strategy-backtest"><strong>长期策略收益回测</strong><span>暂无已持久化的每日策略快照，后续每日打开工作台后开始累计。</span></div>`;
    }
    const profit = Number(s.profit || 0);
    const color = profit > 0 ? "profit" : profit < 0 ? "loss" : "flat";
    const rows = (report.daily || []).flatMap(day => (day.records || []).map(row => ({...row, selected_day: day.selected_day}))).slice(-30).reverse();
    const detail = rows.map(row => `<div class="strategy-backtest-row"><span>${esc(row.selected_day || "")} ${esc(row.market || "")}</span><span>${esc(row.selection || row.combo_id || "-")}</span><b class="${row.status === "won" ? "profit" : row.status === "lost" ? "loss" : "flat"}">${row.status === "won" ? "中了" : row.status === "lost" ? "没中" : "待结算"} ${row.profit == null ? "" : esc(amount(row.profit)) + "元"}</b></div>`).join("");
    return `<div class="strategy-backtest"><div><strong>长期策略收益回测</strong><span>${esc(report.snapshot_count)} 个策略日</span></div><div class="strategy-backtest-metrics"><span>已结算 ${esc(s.settled_count || 0)} 注</span><span>中 ${esc(s.won_count || 0)} / 未中 ${esc(s.lost_count || 0)}</span><span>待结算 ${esc(s.pending_count || 0)}</span><b class="${color}">${amount(profit)}元 · ROI ${s.roi_pct == null ? "-" : esc(s.roi_pct) + "%"}</b></div>${detail ? `<div class="strategy-backtest-details">${detail}</div>` : ""}<small>仅按体彩官方赛果结算；历史策略回测，不代表未来收益。</small></div>`;
  }

  function formatDailyStrategyHtml(plan) {
    const display = plan.display || {};
    const budget = plan.budget || {};
    const singles = plan.single_purchase_recommendations || [];
    const combos = plan.combo_purchase_recommendations || [];
    const evidence = plan.evidence_gap_summary || {};
    const reasonText = Object.entries(evidence.reason_counts || {})
      .slice(0, 3).map(([key, value]) => `${esc(key)} ${esc(value)}`).join("、");
    const tags = (plan.risk_tags || []).map(tag => esc(tag)).join("、");
    const calibrationRows = (plan.market_audit || []).map(row => {
      const status = row.independent_calibration_status || row.model_calibration_status || "UNFITTED";
      return `${esc(MARKET_NAMES[row.market] || row.market)}：${esc(status)}`;
    }).join("、");
    const evidenceBlock = `<div class="strategy-evidence"><strong>证据链状态：</strong>${esc(evidence.evidence_gap_market_rows || 0)} 个市场行存在证据缺口` +
      (reasonText ? `（${reasonText}）` : "") +
      (tags ? ` · 风险标签：${tags}` : "") + `</div>`;
    const calibrationBlock = calibrationRows
      ? `<div class="strategy-evidence"><strong>市场校准状态：</strong>${calibrationRows}</div>`
      : "";
    const llm = plan.llm_calibration || {};
    const llmBlock = `<div class="strategy-evidence"><strong>DeepSeek V4 Flash 校准：</strong>` +
      `已登记 ${esc(llm.llm_rows || 0)} 场，已结算 ${esc(llm.eligible_settled_rows || 0)}/${esc(llm.minimum_review_rows || 100)} 场` +
      ` · ${llm.ready_for_review ? "达到复核门槛" : "未达到复核门槛"} · 仅研究观察</div>`;
    const empty = !singles.length && !combos.length;
    const body = empty
      ? `<div class="banner warn">当天没有足够的未开赛候选，保留 ${amount(budget.preserved_amount)} 元，不用已开赛或缺失数据强行凑单。</div>`
      : `<div class="strategy-grid">
          <div class="strategy-singles">
            <h3>单关分配</h3>
            <div class="strategy-table-wrap"><table>
              <thead><tr><th>项目</th><th>场次</th><th>比赛</th><th>选择</th><th>赔率</th><th>金额</th></tr></thead>
              <tbody>${singles.map(singleRow).join("")}</tbody>
            </table></div>
          </div>
          <div class="strategy-combos"><h3>组合分配</h3>${combos.map(comboCard).join("") || '<p class="muted">没有可用组合。</p>'}</div>
        </div>`;
    return `<section class="daily-strategy-card">
      <div class="strategy-head">
        <div>
          <h2>今日100元娱乐策略</h2>
          <p>${esc(plan.selected_day || "")} · 决策时间 ${esc(display.decision_time || plan.generated_at || "-")}</p>
        </div>
        <div class="strategy-badges"><span>${esc(display.strategy_type || "固定娱乐预算")}</span><span class="risk">${esc(display.edge_label || "未验证正EV")}</span></div>
      </div>
      <div class="strategy-budget">
        <div><b>${amount(budget.daily_budget_amount)}元</b><span>每日预算</span></div>
        <div><b>${amount(budget.allocated_amount)}元</b><span>本次分配</span></div>
        <div><b>${amount(budget.preserved_amount)}元</b><span>保留金额</span></div>
        <div><b>${amount((plan.risk_disclosure || {}).maximum_loss_amount)}元</b><span>最大损失</span></div>
      </div>
      ${evidenceBlock}
      ${calibrationBlock}
      ${llmBlock}
      ${body}
      ${backtestBlock(plan.backtest)}
      <p class="strategy-evidence-warning">${esc(display.evidence_warning || "")}</p>
      <p class="strategy-warning">${esc(display.warning || "固定预算策略不代表统计优势，请勿追损。")}</p>
    </section>`;
  }

  return { formatDailyStrategyHtml };
});
