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

  function formatDailyStrategyHtml(plan) {
    const display = plan.display || {};
    const budget = plan.budget || {};
    const singles = plan.single_purchase_recommendations || [];
    const combos = plan.combo_purchase_recommendations || [];
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
          <h2>今日100元购买策略</h2>
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
      ${body}
      <p class="strategy-warning">${esc(display.warning || "固定预算策略不代表统计优势，请勿追损。")}</p>
    </section>`;
  }

  return { formatDailyStrategyHtml };
});
