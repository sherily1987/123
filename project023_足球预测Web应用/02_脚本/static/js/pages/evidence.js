import { esc, displayMissing } from "../format.js";
import { normalizeEvidence } from "../evidence-state.js";
import { matchSalesDay } from "./scanner.js";

function evidenceGaps(match = {}) {
  return normalizeEvidence(match).gaps;
}

function evidenceConflicts(match = {}) {
  return normalizeEvidence(match).conflicts;
}

export function evidenceSourceCount(match = {}) {
  return normalizeEvidence(match).sourceCount;
}

export function evidenceStatus(match = {}) {
  return normalizeEvidence(match).status;
}

function playerText(player = {}) {
  return `${displayMissing(player.name, "姓名未提供")}（${displayMissing(player.pos, "位置未提供")}，${displayMissing(player.type, "类型未提供")}）`;
}

function injurySide(label, fallbackTeam, side = {}) {
  const players = Array.isArray(side?.players) ? side.players : [];
  return `<section><h4>${esc(label)} · ${esc(displayMissing(side?.team, fallbackTeam))}</h4>${players.length
    ? `<ul>${players.map((player) => `<li>${esc(playerText(player))}</li>`).join("")}</ul>`
    : '<p class="evidence-empty">没有可展示的伤停球员。</p>'}</section>`;
}

function lineupSide(label, team, side = {}) {
  const starting = Array.isArray(side?.starting) ? side.starting : [];
  const missing = Array.isArray(side?.missing) ? side.missing : [];
  return `<section><h4>${esc(label)} · ${esc(displayMissing(team, "球队未提供"))}</h4>${starting.length
    ? `<p><strong>首发 ${esc(side.starting_count ?? starting.length)} 人：</strong>${esc(starting.join("、"))}</p>`
    : '<p class="evidence-empty">没有可展示的首发名单。</p>'}${missing.length ? `<p><strong>缺席：</strong>${esc(missing.join("、"))}</p>` : ""}</section>`;
}

function sourceMeta(entry = {}) {
  return `状态：${displayMissing(entry.status_zh, "未采集")} · 来源：${displayMissing(entry.source_id, "未提供")} · 采集时间：${displayMissing(entry.refreshed_at, "未提供")}`;
}

function recentRows(rows) {
  return Array.isArray(rows) && rows.length
    ? `<ul>${rows.map((row) => `<li>${esc(displayMissing(row.date, "日期未提供"))} · ${esc(displayMissing(row.league, "赛事未提供"))} · ${esc(displayMissing(row.home, "主队未提供"))} vs ${esc(displayMissing(row.away, "客队未提供"))}：${esc(displayMissing(row.score_90, "比分未提供"))}</li>`).join("")}</ul>`
    : '<p class="evidence-empty">没有可展示的近期比赛。</p>';
}

function collectedEvidence(detail = {}) {
  const stats = detail.team_stats || {};
  const summary = stats.summary || {};
  const form = detail.recent_form || {};
  const suspensions = detail.suspensions || {};
  const suspensionPlayers = [...(Array.isArray(suspensions.home) ? suspensions.home : []), ...(Array.isArray(suspensions.away) ? suspensions.away : [])];
  const suspensionEmpty = suspensions.status === "VALID"
    ? '<p class="evidence-empty evidence-empty--valid">已采集：暂无已报告的停赛球员。</p>'
    : '<p class="evidence-empty">空结果未确认，不能推断无人停赛。</p>';
  return `<section class="collected-evidence" aria-label="已采集证据">
    <h3>已采集证据</h3>
    <div class="collected-evidence-grid">
      <article><header><h4>球队数据</h4><span>${esc(displayMissing(stats.status_zh, "未采集"))}</span></header><p class="evidence-meta">${esc(sourceMeta(stats))}</p>${stats.status === "VALID" || stats.status_zh === "有效" ? `<p>${esc(displayMissing(summary.note, "已采集球队统计"))}</p><ul><li>样本：近 ${esc(displayMissing(summary.sample_legs, "—"))} 场</li><li>主队场均进球 ${esc(displayMissing(summary.home_goal_avg, "—"))}；场均失球 ${esc(displayMissing(summary.home_loss_avg, "—"))}</li><li>客队场均进球 ${esc(displayMissing(summary.away_goal_avg, "—"))}；场均失球 ${esc(displayMissing(summary.away_loss_avg, "—"))}</li></ul>` : '<p class="evidence-empty">球队数据未采集。</p>'}</article>
      <article><header><h4>近期状态</h4><span>${esc(displayMissing(form.status_zh, "未采集"))}</span></header><p class="evidence-meta">${esc(sourceMeta(form))}</p><h5>主队近期比赛</h5>${recentRows(form.home)}<h5>客队近期比赛</h5>${recentRows(form.away)}</article>
      <article><header><h4>停赛信息</h4><span>${esc(displayMissing(suspensions.status_zh, "未采集"))}</span></header><p class="evidence-meta">${esc(sourceMeta(suspensions))}</p>${suspensionPlayers.length ? `<ul>${suspensionPlayers.map((player) => `<li>${esc(typeof player === "string" ? player : displayMissing(player.name || player.personName, "姓名未提供"))}</li>`).join("")}</ul>` : suspensionEmpty}</article>
    </div>
  </section>`;
}

function evidenceCard(match, index) {
  const evidence = normalizeEvidence(match);
  const late = match.late_info || {};
  const detail = match.evidence_detail || {};
  const snapshotInjury = detail.injury || {};
  const snapshotLineup = detail.starting_xi || {};
  const injuryStatus = displayMissing(late.injury_zh, displayMissing(snapshotInjury.status_zh, "未采集"));
  const lineupStatus = displayMissing(late.lineup_zh, displayMissing(snapshotLineup.status_zh, "未采集"));
  const injury = late.injury_detail || snapshotInjury;
  const lineup = late.lineup_detail || snapshotLineup;
  const injuryPlayers = [...(Array.isArray(injury?.home?.players) ? injury.home.players : []), ...(Array.isArray(injury?.away?.players) ? injury.away.players : [])];
  const injuryEmpty = snapshotInjury.status === "VALID" && injuryPlayers.length === 0
    ? '<p class="evidence-empty evidence-empty--valid">已采集：暂无已报告的伤停球员。</p>'
    : "";
  const gaps = evidence.gaps.length ? evidence.gaps.join("、") : "无";
  const conflicts = evidence.conflicts.length ? evidence.conflicts.join("、") : "无";
  return `<details class="evidence-match"${index === 0 ? " open" : ""}>
    <summary><span><strong>${esc(displayMissing(match.match_num, match.match_id))}</strong><small>${esc(displayMissing(match.match_id, "编号未提供"))}</small></span><span>${esc(displayMissing(match.home, "未提供"))} vs ${esc(displayMissing(match.away, "未提供"))}</span><span class="evidence-summary-status">伤停：${esc(injuryStatus)} · 首发：${esc(lineupStatus)}</span></summary>
    <div class="evidence-detail-grid">
      <article class="evidence-detail-panel"><header><h3>伤停信息</h3><span>${esc(injuryStatus)}</span></header><p class="evidence-meta">采集时间：${esc(displayMissing(late.injury_collected_at, snapshotInjury.refreshed_at || "未采集"))} · 来源：${esc(displayMissing(snapshotInjury.source_id, late.injury_snapshot || "未提供"))}</p>${injuryEmpty}<div class="evidence-sides">${injurySide("主队", match.home, injury.home)}${injurySide("客队", match.away, injury.away)}</div></article>
      <article class="evidence-detail-panel"><header><h3>首发名单</h3><span>${esc(lineupStatus)}</span></header><p class="evidence-meta">采集时间：${esc(displayMissing(late.lineup_collected_at, snapshotLineup.refreshed_at || "未采集"))} · 来源：${esc(displayMissing(snapshotLineup.source_id, late.lineup_snapshot || "未提供"))}</p>${snapshotLineup.missing_reason_zh ? `<p class="evidence-empty">${esc(snapshotLineup.missing_reason_zh)}</p>` : ""}<div class="evidence-sides">${lineupSide("主队", match.home, lineup.home)}${lineupSide("客队", match.away, lineup.away)}</div></article>
    </div>
    ${collectedEvidence(detail)}
    <dl class="evidence-audit"><div><dt>证据状态</dt><dd>${esc(evidence.status)}</dd></div><div><dt>规范状态</dt><dd>${esc(displayMissing(evidence.canonicalStatus, "未提供"))}</dd></div><div><dt>来源/维度数</dt><dd>${esc(evidence.sourceCount)}</dd></div><div><dt>规范采集时间</dt><dd>${esc(displayMissing(evidence.collectedAt, "未提供"))}</dd></div><div><dt>证据年龄</dt><dd>${esc(evidence.ageMinutes === null ? "未提供" : `${evidence.ageMinutes} 分钟`)}</dd></div><div><dt>引用</dt><dd>${esc(evidence.refs.length ? evidence.refs.join("、") : "无")}</dd></div><div><dt>冲突</dt><dd>${esc(conflicts)}</dd></div><div><dt>缺口</dt><dd>${esc(gaps)}</dd></div></dl>
  </details>`;
}

function evidenceCards(matches) {
  return matches.map(evidenceCard).join("") || '<section class="page-intro"><p>当前销售日没有可展示的比赛证据。</p></section>';
}

export function renderEvidence(root, context = {}) {
  const selectedDay = String(context.salesDay || "");
  const source = Array.isArray(context.board?.matches) ? context.board.matches : [];
  const matches = selectedDay
    ? source.filter((match) => matchSalesDay(match) === selectedDay)
    : source;
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">证据研究库</h1><p><strong>研究证据不回流生产概率。</strong>此页只审计来源、时间、冲突与缺口，不改变 market_only 概率、门禁或登记。</p></section>
    <section class="page-intro" aria-label="晚到证据摘要"><h2>晚到信息</h2><p>有效伤停 ${esc(context.lateInfo?.injury_valid ?? "—")} · 有效首发 ${esc(context.lateInfo?.lineup_valid ?? "—")} · 待刷新 ${esc(context.lateInfo?.scheduled_refresh_pending ?? "—")}</p><p>${esc(displayMissing(context.lateInfo?.note, "研究库，不进生产 1X2"))}</p></section>
    <section class="evidence-list" aria-label="逐场伤停与首发证据">${evidenceCards(matches)}</section>`;
}
