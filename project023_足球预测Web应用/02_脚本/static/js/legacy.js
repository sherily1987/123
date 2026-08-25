const byId = (id) => document.getElementById(id);
const status = byId("status");
const salesDayInput = byId("sales-day");

function node(name, text, className) {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== undefined && text !== null) element.textContent = String(text);
  return element;
}

function clear(target) { target.replaceChildren(); }

async function read(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`读取失败 (${response.status})`);
  return response.json();
}

function display(value, fallback = "未提供") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function addTable(target, columns, rows) {
  const table = node("table");
  const head = node("thead");
  const headRow = node("tr");
  columns.forEach((column) => headRow.append(node("th", column)));
  head.append(headRow);
  const body = node("tbody");
  rows.forEach((row) => body.append(row));
  table.append(head, body);
  target.append(table);
}

function detailButton(matchId) {
  const button = node("button", "查看详情");
  button.type = "button";
  button.addEventListener("click", () => { void openDetail(matchId); });
  return button;
}

function renderMatches(payload) {
  const target = byId("matches");
  clear(target);
  const rows = Array.isArray(payload.matches) ? payload.matches : [];
  if (!rows.length) { target.append(node("p", "该销售日没有可浏览比赛。", "muted")); return; }
  const body = rows.map((match) => {
    const row = node("tr");
    row.append(node("td", display(match.match_num)), node("td", `${display(match.home)} vs ${display(match.away)}`));
    row.append(node("td", display(match.kickoff)), node("td", display(match.status_name || match.bucket)));
    const action = node("td");
    action.append(detailButton(match.match_id));
    row.append(action);
    return row;
  });
  addTable(target, ["编号", "比赛", "开球", "状态", "详情"], body);
}

function renderStrategy(plan) {
  const target = byId("strategy");
  clear(target);
  const budget = plan.budget || {};
  target.append(node("p", `${display(plan.selected_day)} · 预算 ${display(budget.daily_budget_amount, "0")} 元 · 已分配 ${display(budget.allocated_amount, "0")} 元`));
  target.append(node("p", display(plan.display?.warning, "只读策略预览；不生成、不持久化。"), "muted"));
}

function renderHistory(payload) {
  const target = byId("history");
  clear(target);
  const matches = (Array.isArray(payload.sections) ? payload.sections : []).flatMap((section) => section.matches || []);
  if (!matches.length) { target.append(node("p", "没有匹配的历史记录。", "muted")); return; }
  const body = matches.slice(0, 100).map((match) => {
    const row = node("tr");
    row.append(node("td", display(match.day)), node("td", `${display(match.home)} vs ${display(match.away)}`));
    row.append(node("td", display(match.result?.score_90?.join("-") || match.actual, "待结算")));
    const action = node("td");
    action.append(detailButton(match.match_id));
    row.append(action);
    return row;
  });
  addTable(target, ["日期", "比赛", "90分钟赛果", "详情"], body);
}

async function openDetail(matchId) {
  const drawer = byId("drawer");
  clear(drawer);
  drawer.hidden = false;
  const close = node("button", "关闭");
  close.type = "button";
  close.addEventListener("click", () => { drawer.hidden = true; clear(drawer); });
  drawer.append(close, node("h2", "比赛详情"), node("p", "正在读取…", "muted"));
  try {
    const match = await read(`/api/match/${encodeURIComponent(matchId)}`);
    clear(drawer);
    drawer.append(close, node("h2", display(match.match_id, "比赛详情")));
    drawer.append(node("p", `${display(match.home)} vs ${display(match.away)} · ${display(match.kickoff)}`));
    drawer.append(node("p", `量化方向：${display(match.quant?.direction)}；LLM 方向：${display(match.llm?.direction)}`));
    const facts = Array.isArray(match.evidence_facts) ? match.evidence_facts : [];
    const list = node("ul");
    facts.forEach((fact) => list.append(node("li", fact)));
    drawer.append(list);
  } catch (error) {
    clear(drawer);
    drawer.append(close, node("p", `详情读取失败：${error.message}`, "error"));
  }
}

async function loadSelectedDay() {
  const day = salesDayInput.value;
  if (!day) return;
  status.textContent = `正在读取 ${day} 的只读数据…`;
  try {
    const [matches, strategy, history] = await Promise.all([
      read(`/api/matches?sales_day=${encodeURIComponent(day)}`),
      read(`/api/daily-strategy/preview?day=${encodeURIComponent(day)}`),
      read(`/api/history?full=1`),
    ]);
    renderMatches(matches);
    renderStrategy(strategy);
    renderHistory({ sections: (history.sections || []).filter((section) => section.day === day) });
    status.textContent = `${day} 已按只读接口加载。`;
  } catch (error) {
    status.textContent = `读取失败：${error.message}`;
    status.className = "error";
  }
}

byId("refresh").addEventListener("click", () => { void loadSelectedDay(); });
salesDayInput.addEventListener("change", () => { void loadSelectedDay(); });
void read("/api/current-sale-day").then((authority) => {
  salesDayInput.value = authority.sales_day || "";
  return loadSelectedDay();
}).catch((error) => { status.textContent = `当前销售日读取失败：${error.message}`; status.className = "error"; });
