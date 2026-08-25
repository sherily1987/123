const MARKET_STATUS_LABELS = {
  AVAILABLE: "已提供",
  VALID: "已校准",
  UNFITTED: "未拟合",
  MISSING: "未提供",
  NO_ODDS: "无赔率",
  NOT_OFFERED: "未开售",
  RESEARCH_ONLY: "仅研究",
};
const MARKET_CODES = ["HAD", "HHAD", "TTG", "HAFU", "CRS"];
const MARKET_NAMES = { HAD: "胜平负", HHAD: "让球胜平负", TTG: "进球数", HAFU: "半全场", CRS: "比分" };
const TAB_NAMES = { overview: "概览", markets: "盘口", evidence: "证据", audit: "审计" };
const LOADING_SOURCE = "读取中：正在读取工单";

function valueOrMissing(value, fallback = "未提供") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function esc(value) {
  return valueOrMissing(value, "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

function isFiniteValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function valuesText(value) {
  if (Array.isArray(value) && value.length && value.every(isFiniteValue)) return value.map((item) => Number(item).toFixed(1)).join(" / ");
  if (Array.isArray(value)) return value.map((item) => valueOrMissing(item)).join(" / ") || "未提供";
  return valueOrMissing(value);
}

function scoreValues(value) {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 3).map((item) => {
    if (item && typeof item === "object") {
      if (!item.score) return null;
      return isFiniteValue(item.prob_pct) ? `${item.score} ${Number(item.prob_pct).toFixed(1)}%` : String(item.score);
    }
    return item === null || item === undefined || item === "" ? null : String(item);
  }).filter(Boolean);
}

function ouText(value) {
  if (value === null || value === undefined || value === "") return "未提供";
  if (typeof value !== "object") return String(value);
  const under = value.under_pct ?? value.under;
  const over = value.over_pct ?? value.over;
  if (isFiniteValue(under) || isFiniteValue(over)) {
    const underText = isFiniteValue(under) ? `${Number(under).toFixed(1)}%` : "未提供";
    const overText = isFiniteValue(over) ? `${Number(over).toFixed(1)}%` : "未提供";
    return `小2.5 ${underText} / 大2.5 ${overText}`;
  }
  return "未提供";
}

function riskText(quant) {
  const risks = quant?.core_risks ?? quant?.risks ?? quant?.risk_flags ?? quant?.collapse_flags
    ?? quant?.warnings ?? quant?.recommendation_gate?.reasons;
  if (Array.isArray(risks)) return risks.map((item) => (
    item && typeof item === "object"
      ? valueOrMissing(item.label ?? item.code ?? item.reason ?? item.message ?? JSON.stringify(item))
      : valueOrMissing(item)
  )).join(" / ") || "未提供";
  return valueOrMissing(risks);
}

function officialMarketValue(detail, job, code) {
  const lower = code.toLowerCase();
  const input = job?.input || {};
  const jobMarket = code === "HAD" ? input.odds : input[lower];
  return jobMarket ?? detail?.official_markets?.[code] ?? detail?.official_markets?.[lower] ?? null;
}

function hasOfficialOffer(code, value) {
  if (Array.isArray(value)) return value.length > 0;
  if (!value || typeof value !== "object") return false;
  if (Array.isArray(value.odds)) return value.odds.length > 0;
  if (code === "CRS") return Object.keys(value).some((key) => key !== "status");
  return false;
}

function latestOutput(job, track) {
  const outputs = Array.isArray(job?.outputs) ? job.outputs : [];
  return [...outputs].reverse().find((output) => output?.track === track) || null;
}

function hasReadyJob(job) {
  return job !== null && job !== undefined;
}

function resolvedJobState(job, state) {
  return state || (hasReadyJob(job) ? "ready" : "unavailable");
}

export function resolveCurrentQuant(detail = {}, job = null, state) {
  const jobState = resolvedJobState(job, state);
  if (jobState === "ready") return latestOutput(job, "quant") || {};
  return jobState === "unavailable" ? detail.quant || {} : {};
}

function forecastSummary(forecast) {
  if (!forecast) return "未提供";
  if (forecast.model_prob_pct !== undefined) return `${valuesText(forecast.model_prob_pct)}%`;
  if (Array.isArray(forecast.top_scores) && forecast.top_scores.length) return forecast.top_scores.join(" / ");
  return "未提供";
}

export function marketSummary(market) {
  if (!market) return "未提供";
  if (Array.isArray(market)) return valuesText(market);
  if (typeof market !== "object") return valueOrMissing(market);
  const candidate = market.pct ?? market.probabilities ?? market.values ?? market.odds;
  const top = market.top ?? market.pick ?? market.selection;
  if (top !== null && top !== undefined && top !== "") {
    const suffix = candidate === undefined ? "" : ` · ${valuesText(candidate)}${market.pct !== undefined ? "%" : ""}`;
    return `${top}${suffix}`;
  }
  if (candidate !== undefined) return `${valuesText(candidate)}${market.pct !== undefined ? "%" : ""}`;
  const selections = Object.entries(market)
    .filter(([key]) => key !== "status")
    .map(([key, value]) => `${key} ${valueOrMissing(value)}`);
  return selections.length ? selections.join(" / ") : "未提供";
}

function panel(id, active, content) {
  return `<section id="drawer-panel-${id}" role="tabpanel" aria-labelledby="drawer-tab-${id}"${active ? "" : " hidden"}>${content}</section>`;
}

function list(items) {
  return `<dl>${items.map(({ label, value }) => `<dt>${esc(label)}</dt><dd>${esc(valueOrMissing(value))}</dd>`).join("")}</dl>`;
}

export function normalizeMarket(code, market) {
  const status = String(market?.status || (market ? "AVAILABLE" : "MISSING"));
  return { code, status, label: MARKET_STATUS_LABELS[status] || status };
}

export function marketRows(detail = {}, job = null, state) {
  const quant = resolveCurrentQuant(detail, job, state);
  return MARKET_CODES.map((code) => {
    const officialValue = officialMarketValue(detail, job, code);
    const official = normalizeMarket(code, hasOfficialOffer(code, officialValue) ? { status: "AVAILABLE" } : null);
    const forecast = quant.market_forecasts?.[code] || null;
    const model = normalizeMarket(code, forecast?.calibration_status ? { status: forecast.calibration_status } : null);
    return {
      code,
      name: MARKET_NAMES[code],
      official: { ...official, value: marketSummary(officialValue) },
      model: {
        ...model,
        value: forecastSummary(forecast),
        reason: forecast?.calibration_reason ?? forecast?.reason
          ?? (code === "HHAD" ? "HHAD 未纳入模型市场预测" : forecast ? "未提供" : "量化输出未提供该市场预测"),
      },
    };
  });
}

export function llmEvidence(detail = {}, job = null, state) {
  const jobState = resolvedJobState(job, state);
  const canonical = latestOutput(job, "llm");
  if (jobState === "ready") {
    if (!canonical) {
      return {
        direction: "未提供", altDirection: "未提供", topScores: [], ou25: "未提供",
        voteShare: "未提供",
        voteShareLabel: "投票占比（非概率）",
        action: "未提供",
        reason: "工单 outputs 未提供 track=llm",
        source: "缺口：工单 outputs 未提供 track=llm",
      };
    }
    const strength = canonical.strength;
    return {
      direction: canonical.direction ?? canonical.dir ?? "未提供",
      altDirection: canonical.alt_direction ?? canonical.alt ?? "未提供",
      topScores: scoreValues(canonical.top_scores),
      ou25: canonical.llm_ou25 ?? canonical.ou25 ?? canonical.top_ou25 ?? "未提供",
      voteShare: strength?.type === "vote_share" ? strength.value : canonical.vote_share ?? "未提供",
      voteShareLabel: "投票占比（非概率）",
      action: canonical.action ?? "未提供",
      reason: canonical.reason ?? "未提供",
      source: "工单 outputs[].track=llm",
    };
  }
  if (jobState === "loading") {
    return {
      direction: "未提供", altDirection: "未提供", topScores: [], ou25: "未提供",
      voteShare: "未提供",
      voteShareLabel: "投票占比（非概率）",
      action: "未提供",
      reason: LOADING_SOURCE,
      source: LOADING_SOURCE,
    };
  }
  if (jobState === "error") {
    return {
      direction: "未提供", altDirection: "未提供", topScores: [], ou25: "未提供",
      voteShare: "未提供",
      voteShareLabel: "投票占比（非概率）",
      action: "未提供",
      reason: "读取失败：工单资源不可用",
      source: "读取失败：工单资源不可用，详情投影已禁用",
    };
  }
  const fallback = detail.llm || {};
  return {
    direction: fallback.direction ?? fallback.dir ?? "未提供",
    altDirection: fallback.alt_direction ?? fallback.alt ?? "未提供",
    topScores: scoreValues(fallback.top_scores),
    ou25: fallback.llm_ou25 ?? fallback.ou25 ?? fallback.top_ou25 ?? "未提供",
    voteShare: fallback.vote_share ?? "未提供",
    voteShareLabel: "投票占比（非概率）",
    action: fallback.action ?? "未提供",
    reason: fallback.reason ?? "未提供",
    source: "比赛详情 LLM 投影（工单未提供）",
  };
}

export function auditRows(detail = {}, job = null, state) {
  const jobState = resolvedJobState(job, state);
  const jobReady = jobState === "ready";
  const jobUnavailable = jobState === "unavailable";
  const jobLoading = jobState === "loading";
  const quant = resolveCurrentQuant(detail, job, jobState);
  const result = detail.result || {};
  const signature = quant.probability_signature ?? "未提供";
  const identity = jobReady ? job?.identity || {} : {};
  const identityValue = jobReady ? identity.match_id ?? "未提供" : jobUnavailable ? detail.match_id ?? "未提供" : "未提供";
  const version = quant.model_version ?? "未提供";
  return [
    { label: "match_id", value: identityValue },
    { label: "模型版本", value: version },
    { label: "概率签名", value: signature },
    { label: "match_id 来源", value: jobReady
      ? identityValue === "未提供" ? "缺口：工单 identity 未提供 match_id" : "工单 identity.match_id"
      : jobUnavailable ? "比赛详情 match_id 投影（工单未提供）" : jobLoading ? LOADING_SOURCE : "读取失败：工单 identity 不可用" },
    { label: "模型版本来源", value: jobReady
      ? version === "未提供" ? "缺口：工单 quant 输出未提供 model_version" : "工单 quant 输出"
      : jobUnavailable ? "比赛详情 quant 投影（工单未提供）" : jobLoading ? LOADING_SOURCE : "读取失败：工单 quant 输出不可用" },
    { label: "概率签名来源", value: jobLoading ? LOADING_SOURCE : signature === "未提供"
      ? "缺口：工单 quant 输出未提供 probability_signature"
      : jobReady ? "工单 quant 输出" : jobUnavailable ? "比赛详情 quant 投影（工单未提供）" : "读取失败：工单 quant 输出不可用" },
    { label: "prediction_as_of", value: jobReady
      ? quant.prediction_as_of ?? job?.input?.prediction_as_of ?? "未提供"
      : jobUnavailable ? detail.prediction_as_of ?? "未提供" : "未提供" },
    { label: "数据来源", value: jobReady
      ? quant.source ?? job?.input?.field_meta?.odds?.source ?? "未提供"
      : jobUnavailable ? detail.source ?? "未提供" : "未提供" },
    { label: "90分钟赛果", value: Array.isArray(result.score_90) ? result.score_90.join(" - ") : "未提供" },
    { label: "结算范围", value: result.settlement_scope ?? "未提供" },
  ];
}

export async function loadMatchResources(matchId, requestJson) {
  const encodedId = encodeURIComponent(matchId);
  const detailRequest = requestJson(`/api/match/${encodedId}`);
  const jobRequest = requestJson(`/api/job?match_id=${encodedId}`).then(
    (job) => ({ state: "ready", job }),
    (error) => error?.status === 404
      ? { state: "unavailable", message: "工单未提供" }
      : { state: "error", message: `工单读取失败：${valueOrMissing(error?.message, "未知错误")}` },
  );
  const [detail, job] = await Promise.all([detailRequest, jobRequest]);
  return { detail, job };
}

function renderOverview(detail, job, state) {
  const quant = resolveCurrentQuant(detail, job, state);
  const llm = llmEvidence(detail, job, state);
  const result = detail.result || {};
  return panel("overview", true, `<h3>概览</h3><p>赛果只按 <strong>90分钟</strong> 口径显示；量化与 LLM 两轨分列，不合成。</p>${list([
    { label: "量化主 / 平 / 客", value: Array.isArray(quant.final_1x2_pct) ? `${valuesText(quant.final_1x2_pct)}%` : "未提供" },
    { label: "量化模式", value: quant.mode },
    { label: "推荐闸门", value: quant.recommendation_gate?.status ?? quant.gate ?? quant.status },
    { label: "量化 Top 比分", value: scoreValues(quant.top_scores).join(" / ") || "未提供" },
    { label: "量化大小球", value: ouText(quant.ou_2_5) },
    { label: "核心风险", value: riskText(quant) },
    { label: "LLM方向", value: llm.direction },
    { label: "LLM备选方向", value: llm.altDirection },
    { label: "LLM Top 比分", value: llm.topScores.join(" / ") || "未提供" },
    { label: "LLM大小球", value: llm.ou25 },
    { label: "LLM行动", value: llm.action },
    { label: "90分钟赛果", value: Array.isArray(result.score_90) ? result.score_90.join(" - ") : "未提供" },
  ])}`);
}

function renderMarkets(detail, job, state) {
  const rows = marketRows(detail, job, state).map((row) => {
    return `<tr><th scope="row">${esc(row.code)} · ${esc(row.name)}</th><td>${esc(row.official.value)}</td><td>${esc(row.official.label)}</td><td>${esc(row.model.label)}</td><td>${esc(row.model.reason)}</td></tr>`;
  }).join("");
  return panel("markets", false, `<h3>全部体彩盘口</h3><p>官方赔率是否提供，与模型预测的校准状态分开呈现。</p><table><thead><tr><th>市场</th><th>官方赔率</th><th>官方状态</th><th>模型状态</th><th>模型原因</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function quantEvidence(detail, job, state) {
  const jobState = resolvedJobState(job, state);
  const quant = resolveCurrentQuant(detail, job, jobState);
  if (jobState === "loading") return { calibration: "读取中", source: LOADING_SOURCE };
  if (jobState === "error") return { calibration: "读取失败", source: "读取失败：工单 quant 输出不可用，详情投影已禁用" };
  if (jobState === "ready" && !latestOutput(job, "quant")) return { calibration: "未提供", source: "缺口：工单 quant 输出未提供" };
  const calibration = quant.calibration?.applied === true ? "已应用" : quant.calibration?.applied === false ? "未应用" : "未提供";
  return { calibration, source: jobState === "ready" ? "工单 quant 输出" : "比赛详情 quant 投影（工单未提供）" };
}

function renderEvidence(detail, job, state) {
  const quant = quantEvidence(detail, job, state);
  const llm = llmEvidence(detail, job, state);
  const facts = Array.isArray(detail.evidence_facts) ? detail.evidence_facts : [];
  return panel("evidence", false, `<h3>证据</h3><h4>量化证据</h4>${list([
    { label: "证据状态", value: detail.lights?.evidence_status ?? detail.lights?.status },
    { label: "校准", value: quant.calibration },
    { label: "量化来源", value: quant.source },
    { label: "证据文件", value: detail.evidence_file },
  ])}<h4>LLM研究轨</h4>${list([
    { label: "方向", value: llm.direction },
    { label: "备选方向", value: llm.altDirection },
    { label: "Top 比分", value: llm.topScores.join(" / ") || "未提供" },
    { label: "大小球", value: llm.ou25 },
    { label: "行动", value: llm.action },
    { label: "理由", value: llm.reason },
    { label: llm.voteShareLabel, value: llm.voteShare },
    { label: "LLM 来源", value: llm.source },
  ])}<h4>证据事实</h4><ul>${facts.map((fact) => `<li>${esc(fact)}</li>`).join("") || "<li>未提供</li>"}</ul>`);
}

function renderAudit(detail, jobState) {
  const state = jobState?.state || "unavailable";
  const job = state === "ready" ? jobState?.job || {} : null;
  const jobContent = jobState?.state === "ready"
    ? list([{ label: "工单状态", value: "已提供" }, { label: "工单 match_id", value: jobState.job?.identity?.match_id ?? "未提供" }])
    : list([{ label: "工单状态", value: jobState?.message ?? "工单未提供" }]);
  return panel("audit", false, `<h3>审计</h3>${list(auditRows(detail, job, state))}<h4>统一工单</h4>${jobContent}`);
}

export function renderMatchDrawer(root, detail, jobState = { state: "unavailable" }, activeTab = "overview") {
  root.style.pointerEvents = "auto";
  const title = detail.match_id || "比赛详情";
  const state = jobState?.state || "unavailable";
  const job = state === "ready" ? jobState?.job || {} : null;
  root.innerHTML = `<div class="drawer-backdrop" data-drawer-backdrop></div><section class="match-drawer" role="dialog" aria-modal="true" aria-labelledby="match-drawer-title"><header><h2 id="match-drawer-title">${esc(title)}</h2><button type="button" data-drawer-close aria-label="关闭比赛详情">关闭</button></header><div role="tablist" aria-label="比赛详情标签">${Object.entries(TAB_NAMES).map(([id, label]) => `<button id="drawer-tab-${id}" type="button" role="tab" aria-controls="drawer-panel-${id}" aria-selected="${id === activeTab}" tabindex="${id === activeTab ? "0" : "-1"}" data-drawer-tab="${id}">${esc(label)}</button>`).join("")}</div>${renderOverview(detail, job, state)}${renderMarkets(detail, job, state)}${renderEvidence(detail, job, state)}${renderAudit(detail, jobState)}</section>`;
  showTab(root, activeTab);
}

function showTab(root, activeTab) {
  root.querySelectorAll?.("[data-drawer-tab]").forEach((tab) => {
    const selected = tab.dataset.drawerTab === activeTab;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  root.querySelectorAll?.("[role=tabpanel]").forEach((entry) => { entry.hidden = entry.id !== `drawer-panel-${activeTab}`; });
}

function focusCloseButton(root) {
  root.querySelector?.("[data-drawer-close]")?.focus?.({ preventScroll: true });
}

export function createMatchDrawer({ root, requestJson, backgroundElements = null }) {
  let trigger = null;
  let currentMatchId = null;
  let requestId = 0;
  let activeTab = "overview";
  let backgroundRestore = null;
  const modalBackground = () => {
    if (backgroundElements) return [...backgroundElements];
    if (typeof document === "undefined" || !document.body?.children) return [];
    return [...document.body.children].filter((element) => element !== root);
  };
  const setBackgroundInert = (inert) => {
    if (inert) {
      if (backgroundRestore) return;
      backgroundRestore = modalBackground().map((element) => ({
        element,
        inert: Boolean(element.inert),
        hadAriaHidden: element.hasAttribute?.("aria-hidden") || false,
        ariaHidden: element.getAttribute?.("aria-hidden"),
      }));
      backgroundRestore.forEach(({ element }) => {
        element.inert = true;
        element.setAttribute?.("aria-hidden", "true");
      });
      return;
    }
    (backgroundRestore || []).forEach(({ element, inert: oldInert, hadAriaHidden, ariaHidden }) => {
      element.inert = oldInert;
      if (hadAriaHidden) element.setAttribute?.("aria-hidden", ariaHidden);
      else element.removeAttribute?.("aria-hidden");
    });
    backgroundRestore = null;
  };
  const close = () => {
    requestId += 1;
    currentMatchId = null;
    root.innerHTML = "";
    root.style.pointerEvents = "none";
    setBackgroundInert(false);
    trigger?.focus?.({ preventScroll: true });
    trigger = null;
  };
  const setActiveTab = (tab) => {
    if (!TAB_NAMES[tab]) return;
    activeTab = tab;
    showTab(root, tab);
  };
  root?.addEventListener?.("click", (event) => {
    if (event.target?.closest?.("[data-drawer-close]")) close();
    else if (event.target?.matches?.("[data-drawer-backdrop]")) close();
    else {
      const tab = event.target?.closest?.("[data-drawer-tab]");
      if (tab) setActiveTab(tab.dataset.drawerTab);
    }
  });
  root?.addEventListener?.("keydown", (event) => {
    const tab = event.target?.closest?.("[data-drawer-tab]");
    if (!tab || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...root.querySelectorAll("[data-drawer-tab]")];
    const index = tabs.indexOf(tab);
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    const next = tabs[nextIndex];
    setActiveTab(next.dataset.drawerTab);
    next.focus?.();
  });
  if (typeof document !== "undefined") document.addEventListener("keydown", (event) => {
    if (!currentMatchId) return;
    if (event.key === "Escape") { close(); return; }
    if (event.key !== "Tab") return;
    const focusable = [...(root.querySelectorAll?.(
      "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
    ) || [])];
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !focusable.includes(active))) {
      event.preventDefault();
      last.focus?.({ preventScroll: true });
    } else if (!event.shiftKey && (active === last || !focusable.includes(active))) {
      event.preventDefault();
      first.focus?.({ preventScroll: true });
    }
  });
  const open = async (matchId, nextTrigger) => {
    if (!matchId) return;
    trigger = nextTrigger || trigger;
    currentMatchId = String(matchId);
    activeTab = "overview";
    setBackgroundInert(true);
    const id = ++requestId;
    renderMatchDrawer(root, { match_id: currentMatchId }, { state: "loading", message: "正在读取工单" }, activeTab);
    focusCloseButton(root);
    try {
      const result = await loadMatchResources(currentMatchId, requestJson);
      if (id !== requestId || currentMatchId !== String(matchId)) return;
      renderMatchDrawer(root, result.detail, result.job, activeTab);
      focusCloseButton(root);
    } catch (error) {
      if (id !== requestId || currentMatchId !== String(matchId)) return;
      renderMatchDrawer(root, { match_id: currentMatchId }, { state: "error", message: "工单未读取：详情不可用" }, activeTab);
      const overview = root.querySelector?.("#drawer-panel-overview");
      if (overview) overview.innerHTML = `<h3>概览</h3><p role="alert">比赛详情读取失败：${esc(error?.message || "未知错误")}</p>`;
      focusCloseButton(root);
    }
  };
  return { open, close };
}
