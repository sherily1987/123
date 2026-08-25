import "../../daily_strategy.js";
import { esc } from "../format.js";

function strategyBasis(plan = {}) {
  return plan.model_basis || plan.display?.strategy_type || "固定娱乐预算；仅作为市场与模型候选的筛选参考。";
}

function marketSelection(plan = {}) {
  const markets = (Array.isArray(plan.market_audit) ? plan.market_audit : [])
    .map((row) => row?.market)
    .filter(Boolean);
  return markets.length ? markets.join("、") : "未提供可筛选市场";
}

export function renderStrategy(root, context = {}) {
  const plan = {
    ...(context.dailyStrategy || {}),
    backtest: context.strategyBacktest || context.dailyStrategy?.backtest,
  };
  const renderer = globalThis.DailyStrategyView?.formatDailyStrategyHtml;
  const strategyHtml = typeof renderer === "function"
    ? renderer(plan)
    : '<section class="page-intro"><p>每日策略渲染器未加载。</p></section>';
  const itemCount = (Array.isArray(plan.single_purchase_recommendations) ? plan.single_purchase_recommendations.length : 0)
    + (Array.isArray(plan.combo_purchase_recommendations) ? plan.combo_purchase_recommendations.length : 0);
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">每日策略</h1><p>数据与门禁满足时自动生成固定娱乐预算策略；单关与组合均有明确金额上限，未验证正EV，不能作为生产胆项。</p></section>
    <section class="page-intro" aria-label="策略依据与风险"><h2>依据与风险</h2><p><strong>策略项目：</strong>${esc(itemCount)}</p><p><strong>市场筛选：</strong>${esc(marketSelection(plan))}</p><p><strong>模型关系：</strong>${esc(strategyBasis(plan))}</p><p><strong>风险边界：</strong>${esc(plan.display?.edge_label || "未验证正EV")}；不是生产胆项；组合任一腿失败则组合未中。</p></section>${strategyHtml}`;
}
