import { esc, displayMissing } from "../format.js";

export function versionActions() {
  return [];
}

export function renderVersions(root, context = {}) {
  const governance = context.versionGovernance || {};
  const progress = context.versionProgress || {};
  const identity = governance.identity || {};
  const current = governance.current || progress.current || {};
  const drift = governance.signature_drift || progress.signature_drift || [];
  const load = governance.load || {};
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">只读版本治理</h1><p>这里只展示版本、概率签名、已结算、在途与签名漂移；不提供任何变更操作。</p></section>
    <section class="page-intro" aria-label="当前版本身份"><h2>当前身份</h2><dl><div><dt>模型版本</dt><dd>${esc(displayMissing(identity.model_version || progress.current_model_version, "未加载"))}</dd></div><div><dt>概率签名</dt><dd>${esc(displayMissing(identity.probability_signature || progress.current_probability_signature, "未加载"))}</dd></div><div><dt>已结算</dt><dd>${esc(current.settled ?? "—")}</dd></div><div><dt>在途</dt><dd>${esc(current.pending ?? "—")}</dd></div></dl></section>
    <section class="page-intro" aria-label="签名漂移"><h2>签名漂移</h2><p>身份读取：${esc(displayMissing(load.identity, "未提供"))} · 进度读取：${esc(displayMissing(load.progress, "未提供"))}</p><p>签名漂移 ${esc(drift.length)} 条；${drift.length ? "这些记录不会静默计入当前 cohort。" : "未报告漂移。"}</p><p>样本量只触发复审，不等于可以解禁生产推荐。</p></section>`;
}
