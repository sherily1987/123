import { esc, displayMissing, formatPct, isFiniteValue } from "../format.js";
import { evidenceHasGap, normalizeEvidence } from "../evidence-state.js";

const SORT_FIELDS = new Set(["kickoff", "league"]);
const SALE_WINDOW = new Set(["已开售", "暂停销售"]);
export const OVERVIEW_TODO_STATUSES = ["missing", "evidence_missing", "near_kickoff", "identity_conflict"];

export function matchSalesDay(match) {
  return String(match?.sales_day || match?.kickoff || "").slice(0, 10);
}

function matchText(match) {
  return [match?.home, match?.away, match?.match_num, match?.match_id].join(" ").toLocaleLowerCase();
}

export function matchStatusText(match = {}) {
  if (match.quant) return "已登记";
  if (match.has_odds) return "有盘未登记";
  if (match.bucket === "finished" || match.not_kicked === false) return "已结束或已开球";
  return "无 HAD";
}

export function isOnSale(match = {}) {
  return SALE_WINDOW.has(match.status_name)
    && match.bucket !== "finished"
    && match.not_kicked !== false
    && !match.result?.score_90;
}

function hasEvidenceGap(match = {}) {
  return match.evidence_gap === true || evidenceHasGap(match);
}

function hasIdentityConflict(match = {}) {
  return match.identity_conflict === true
    || match.identity?.conflict === true
    || match.identity?.status === "CONFLICT";
}

function timestamp(value) {
  const date = value instanceof Date ? value : new Date(value);
  return Number.isFinite(date.getTime()) ? date.getTime() : null;
}

export function isNearKickoff(match = {}, { now = Date.now(), nearKickoffMinutes = 120 } = {}) {
  const kickoff = timestamp(match.kickoff);
  const reference = timestamp(now);
  const windowMs = Number(nearKickoffMinutes) * 60 * 1000;
  if (kickoff === null || reference === null || !Number.isFinite(windowMs) || windowMs < 0) return false;
  const remaining = kickoff - reference;
  return remaining >= 0 && remaining <= windowMs;
}

export function rowMatchesStatus(match, status, options = {}) {
  if (!status || status === "all") return true;
  if (status === "missing") return Boolean(match.has_odds && !match.quant);
  if (status === "registered") return Boolean(match.quant);
  if (status === "no_odds") return !match.has_odds;
  if (status === "evidence_missing") return hasEvidenceGap(match);
  if (status === "evidence_complete") return !hasEvidenceGap(match);
  if (status === "near_kickoff") return isNearKickoff(match, options);
  if (status === "identity_conflict") return hasIdentityConflict(match);
  if (status === "todo") return OVERVIEW_TODO_STATUSES.some((todoStatus) => rowMatchesStatus(match, todoStatus, options));
  return true;
}

export function filterMatches(matches = [], filters = {}) {
  const query = String(filters.query || "").trim().toLocaleLowerCase();
  const date = String(filters.date || "");
  const league = String(filters.league || "");
  const rows = (Array.isArray(matches) ? matches : []).filter((match) => (
    (!date || matchSalesDay(match) === date)
    && (!query || matchText(match).includes(query))
    && (!league || league === "all" || String(match?.league || "") === league)
    && rowMatchesStatus(match, filters.status, filters)
  ));
  if (!SORT_FIELDS.has(filters.sort)) return rows;
  return rows.sort((left, right) => {
    const field = filters.sort;
    const result = String(left?.[field] || "").localeCompare(String(right?.[field] || ""), "zh-CN");
    return result || String(left?.match_id || "").localeCompare(String(right?.match_id || ""));
  });
}

export function resolveMatchRowCollection(context = {}) {
  const selectedDay = String(context.salesDay || "");
  if (Array.isArray(context.matches?.matches)
      && (!selectedDay || String(context.matches.sales_day || "") === selectedDay)) {
    return { available: true, rows: context.matches.matches };
  }
  if (Array.isArray(context.matches) && !selectedDay) return { available: true, rows: context.matches };
  if (!Array.isArray(context.board?.matches)) return { available: false, rows: [] };
  const rows = selectedDay
    ? context.board.matches.filter((match) => matchSalesDay(match) === selectedDay)
    : context.board.matches;
  return { available: !selectedDay || rows.length > 0, rows };
}

export function resolveMatchRows(context = {}) {
  return resolveMatchRowCollection(context).rows;
}

function formatKickoff(value) {
  const text = displayMissing(value, "未提供");
  return esc(text === "未提供" ? text : String(text).replace("T", " ").slice(0, 16));
}

function formatHad(value) {
  if (!Array.isArray(value) || value.length < 3 || value.slice(0, 3).some((item) => !isFiniteValue(item))) return "未提供";
  return esc(value.slice(0, 3).map((item) => Number(item).toFixed(2)).join(" / "));
}

function evidenceText(match) {
  const evidence = normalizeEvidence(match);
  if (evidence.status === "有缺口" && evidence.gaps.length) return `有缺口：${evidence.gaps.join(" / ")}`;
  if (evidence.status === "冲突" && evidence.conflicts.length) return `冲突：${evidence.conflicts.join(" / ")}`;
  return evidence.status;
}

function scannerRows(matches) {
  return matches.map((match) => {
    const quant = match.quant || {};
    return `<tr data-match-id="${esc(match.match_id)}" tabindex="0" role="button" aria-label="查看 ${esc(displayMissing(match.match_num, match.match_id))} 详情">
      <td>${esc(displayMissing(match.match_num, "未提供"))}<br><small>${esc(displayMissing(match.match_id, "未提供"))}</small></td>
      <td>${esc(displayMissing(match.home, "未提供"))} vs ${esc(displayMissing(match.away, "未提供"))}<br><small>${esc(displayMissing(match.league, "未提供"))} · ${formatKickoff(match.kickoff)}</small></td>
      <td>${formatHad(match.odds)}</td>
      <td>${esc(formatPct(quant.final_1x2_pct, "未提供"))}</td>
      <td>${esc(displayMissing(quant.mode, "未提供"))}</td>
      <td>${esc(evidenceText(match))}</td>
      <td>${esc(matchStatusText(match))}</td>
    </tr>`;
  }).join("") || '<tr><td colspan="7">没有符合当前筛选条件的比赛。</td></tr>';
}

function emitMatchSelect(root, matchId, context) {
  if (!matchId) return;
  const detail = { matchId };
  if (typeof context.onMatchSelect === "function") context.onMatchSelect(detail);
  if (typeof globalThis.CustomEvent === "function" && typeof root?.dispatchEvent === "function") {
    root.dispatchEvent(new CustomEvent("matchselect", { detail }));
  }
}

function bindScannerActions(root, context) {
  if (!root?.addEventListener || root.dataset?.scannerActionsBound) return;
  if (root.dataset) root.dataset.scannerActionsBound = "true";
  root.addEventListener("click", (event) => {
    const row = event.target.closest?.("tr[data-match-id]");
    if (row) {
      row.focus?.({ preventScroll: true });
      emitMatchSelect(root, row.dataset.matchId, context);
    }
  });
  root.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest?.("tr[data-match-id]");
    if (row) {
      event.preventDefault();
      row.focus?.({ preventScroll: true });
      emitMatchSelect(root, row.dataset.matchId, context);
    }
  });
  root.addEventListener("change", (event) => {
    const form = event.target.closest?.("[data-scanner-filters]");
    if (!form || typeof context.navigate !== "function") return;
    const values = Object.fromEntries(new FormData(form).entries());
    context.navigate("scanner", Object.fromEntries(Object.entries(values).filter(([, item]) => item && item !== "all")));
  });
}

export function renderScanner(root, context = {}) {
  const filters = context.params || context.filters || {};
  const source = resolveMatchRows(context);
  const leagues = [...new Set(source.map((match) => match?.league).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b), "zh-CN"));
  const rows = filterMatches(source, filters);
  const selected = (name, candidate) => String(filters[name] || "") === candidate ? " selected" : "";
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">预测扫描</h1><p>仅展示已有事实字段；缺失不以 0 填补。选择任一行会派发 <code>matchselect</code> 事件，详情抽屉由后续页面接管。</p></section>
    <form class="page-intro" data-scanner-filters><label>日期<input type="date" name="date" value="${esc(filters.date || context.salesDay || "")}"></label><label>搜索<input type="search" name="query" value="${esc(filters.query || "")}" placeholder="队名、竞彩编号或 match_id"></label><label>联赛<select name="league"><option value="all">全部联赛</option>${leagues.map((league) => `<option value="${esc(league)}"${selected("league", league)}>${esc(league)}</option>`).join("")}</select></label><label>登记<select name="status"><option value="all">全部状态</option><option value="missing"${selected("status", "missing")}>未登记</option><option value="registered"${selected("status", "registered")}>已登记</option><option value="no_odds"${selected("status", "no_odds")}>无 HAD</option><option value="evidence_missing"${selected("status", "evidence_missing")}>证据缺口</option><option value="near_kickoff"${selected("status", "near_kickoff")}>临近开球</option><option value="identity_conflict"${selected("status", "identity_conflict")}>身份冲突</option></select></label><label>排序<select name="sort"><option value="kickoff"${selected("sort", "kickoff")}>开球时间</option><option value="league"${selected("sort", "league")}>联赛</option></select></label></form>
    <section class="table-wrap" aria-label="比赛扫描结果"><table class="data-table"><thead><tr><th>竞彩编号</th><th>比赛 / 联赛 / 开球</th><th>HAD</th><th>量化主 / 平 / 客</th><th>模式</th><th>证据</th><th>登记</th></tr></thead><tbody>${scannerRows(rows)}</tbody></table></section>`;
  bindScannerActions(root, context);
}
