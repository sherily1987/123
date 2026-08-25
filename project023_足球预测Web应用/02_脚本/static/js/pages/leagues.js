import { esc } from "../format.js";

function records(history = {}) {
  return (Array.isArray(history.sections) ? history.sections : [])
    .flatMap((section) => Array.isArray(section?.matches) ? section.matches : []);
}

function dayOf(record = {}) {
  return record.day || String(record.kickoff || "").slice(0, 10) || "日期缺失";
}

function scoresText(values) {
  return Array.isArray(values) && values.length ? values.join("、") : "—";
}

function probabilityText(record = {}) {
  const values = record.quant?.final_1x2_pct;
  return Array.isArray(values) && values.length === 3
    ? values.map((value) => `${value}%`).join(" / ") : "—";
}

function scoreText(record = {}) {
  const score = record.result?.score_90;
  return Array.isArray(score) && score.length >= 2
    ? `${score[0]}-${score[1]}（${record.result?.direction || "方向缺失"}）`
    : (record.settled ? "赛果缺失" : "待结算");
}

function badge(record, track) {
  if (!record.settled) return '<span class="result-badge pending">待结算</span>';
  if (track === "llm" && !record.llm_scored) return '<span class="result-badge unavailable">未计分</span>';
  if (track === "quant" && record.quant?.alt_direction) {
    return `<span class="result-badge ${record.hit ? "hit" : "miss"}">单项${record.hit ? "命中" : "未命中"}</span><small><span class="result-badge ${record.quant_double_hit ? "hit" : "miss"}">方向${record.quant_double_hit ? "命中" : "未命中"}</span></small>`;
  }
  const hit = track === "llm" ? record.llm_hit : record.hit;
  return `<span class="result-badge ${hit ? "hit" : "miss"}">${hit ? "命中" : "未命中"}</span>`;
}

function detailRow(record = {}) {
  const time = String(record.kickoff || "").includes("T") ? String(record.kickoff).split("T")[1].slice(0, 5) : "—";
  const llmDirection = record.llm?.direction ? `LLM：${record.llm.direction}` : "未登记";
  const llmAlt = record.llm?.alt_direction ? `备选：${record.llm.alt_direction}` : "备选：—";
  return `<tr><td>${esc(dayOf(record))}</td><td>${esc(record.league || "联赛缺失")}</td><td>${esc(record.match_num || "—")}</td><td>${esc(time)}</td><td class="match-cell">${esc(record.home || "—")} vs ${esc(record.away || "—")}</td><td><strong>${esc(record.quant?.direction_label || record.quant?.direction || "—")}</strong><small>${esc(probabilityText(record))}</small></td><td>${esc(scoresText(record.quant?.top_scores))}</td><td><strong>${esc(llmDirection)}</strong><small>${esc(llmAlt)} · ${esc(scoresText(record.llm?.top_scores))}</small></td><td>${esc(scoreText(record))}</td><td>${badge(record, "quant")}</td><td>${badge(record, "llm")}</td></tr>`;
}

function grouped(allRecords, mode) {
  const groups = new Map();
  allRecords.forEach((record) => {
    const key = mode === "date" ? dayOf(record) : (record.league || "联赛缺失");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  });
  return [...groups.keys()].sort((left, right) => mode === "date"
    ? String(right).localeCompare(String(left))
    : String(left).localeCompare(String(right), "zh-CN"))
    .map((key) => ({
      key,
      matches: groups.get(key).sort((left, right) => {
        if (mode === "date") {
          const order = String(left.league || "").localeCompare(String(right.league || ""), "zh-CN");
          if (order) return order;
        }
        return String(right.kickoff || dayOf(right)).localeCompare(String(left.kickoff || dayOf(left)));
      }),
    }));
}

function detailView(history, mode) {
  const blocks = grouped(records(history), mode).map(({ key, matches }) => `<section class="history-league"><header><div><h3>${esc(key)}</h3><span>${esc(matches.length)} 场</span></div></header><div class="history-table-wrap"><table class="data-table history-table"><thead><tr><th>日期</th><th>联赛</th><th>场次</th><th>时间</th><th>比赛</th><th>量化预测<br><small>主 / 平 / 客</small></th><th>量化 Top 比分</th><th>LLM预测</th><th>官方90分钟赛果</th><th>量化命中</th><th>LLM命中</th></tr></thead><tbody>${matches.map(detailRow).join("")}</tbody></table></div></section>`).join("")
    || '<section class="page-intro"><p>暂无历史预测记录。</p></section>';
  return `<section class="page-intro" aria-labelledby="league-details-title"><h2 id="league-details-title">全部预测明细</h2><p>包含已结算与待结算记录；量化和LLM独立显示，不合并分母。</p><nav class="view-switch" aria-label="预测明细排序"><a class="button" href="#leagues?sort=league"${mode === "league" ? ' aria-current="page"' : ""}>按联赛排序</a> <a class="button" href="#leagues?sort=date"${mode === "date" ? ' aria-current="page"' : ""}>按日期排序</a></nav></section><div class="history-groups">${blocks}</div>`;
}

export function renderLeagues(root, context = {}) {
  const mode = context.params?.sort === "date" ? "date" : "league";
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">联赛表现</h1><p>展示全部历史预测，支持按联赛或日期排序。量化与 LLM 独立显示，不合并。</p></section>
    ${detailView(context.history || {}, mode)}`;
}
