import { requestJson } from "./api.js";
import { esc, shanghaiSalesDay } from "./format.js";
import { createRefreshController } from "./refresh.js";
import { bindSidebarRouteClosure, closeSidebarOnRoute, createRouter, createSidebarController } from "./router.js";
import { createStore } from "./store.js";
import { createMatchDrawer } from "./match-drawer.js";
import { createPageLoader } from "./page-loader.js";
import { createAsyncPageRuntime, renderPageLoadError } from "./page-runtime.js";
import { autoStrategyChanged, createAutoStrategyRefresh } from "./strategy-auto.js";

const pageTitles = {
  overview: ["总览", "开售、登记和回测的总览将在此呈现。"], strategy: ["每日策略", "固定娱乐预算策略与风险提示将在此呈现。"], backtest: ["回测", "已结算样本、指标和版本边界将在此呈现。"], leagues: ["联赛表现", "联赛维度的命中和校准表现将在此呈现。"], evidence: ["证据审计", "赛前证据状态与缺口将在此呈现。"], tasks: ["任务", "采集、预测、LLM、结算和回测任务将在此呈现。"], versions: ["版本治理", "此处只读展示模型版本、概率签名、样本进度和漂移。"], export: ["导出", "可下载的报告和数据导出将在此呈现。"],
};
const root = document.querySelector("#page-root");
const drawerRoot = document.querySelector("#drawer-root");
const status = document.querySelector("#global-status");
const sidebar = document.querySelector("#app-sidebar");
const sidebarToggle = document.querySelector("#sidebar-toggle");
const salesDayInput = document.querySelector("#sales-day");
const mobileSidebar = window.matchMedia("(max-width: 720px)");
const sidebarController = createSidebarController({
  sidebar,
  toggle: sidebarToggle,
  isMobile: () => mobileSidebar.matches,
});
const matchDrawer = createMatchDrawer({ root: drawerRoot, requestJson });

export const store = createStore({
  salesDay: "",
  page: "overview",
  filters: {},
  selectedMatchId: null,
  cache: {},
  cacheTimes: {},
  staleKeys: [],
  moduleErrors: {},
  pageSuccessTimes: {},
  exportReport: { state: "idle" },
  activeRuns: {},
});

const dataModules = [
  { key: "board", path: () => "/api/board" },
  { key: "matches", path: (salesDay) => `/api/matches?sales_day=${encodeURIComponent(salesDay)}` },
  { key: "lateInfo", path: () => "/api/late-info" },
  { key: "dailyStrategy", path: (salesDay) => `/api/daily-strategy?day=${encodeURIComponent(salesDay)}` },
  { key: "strategyBacktest", path: () => "/api/daily-strategy/backtest" },
  { key: "versionProgress", path: () => "/api/version-progress" },
  { key: "versionGovernance", path: () => "/api/version-governance" },
  { key: "history", path: () => "/api/history?full=1" },
  {
    key: "activeRuns",
    path: () => "/api/runs/active",
    apply: (value, state) => ({
      ...state,
      activeRuns: Object.fromEntries((value?.runs || []).map((run) => [run.run_type, {
        ...run, kind: run.run_type, logs: run.message ? [run.message] : [],
      }])),
    }),
  },
];

function setStatus(message, tone = "neutral") { status.textContent = message; status.dataset.tone = tone; }

const refreshController = createRefreshController({ store, modules: dataModules, request: requestJson, setStatus });
export function refreshModules(keys) { return refreshController.refresh(keys); }
const autoStrategy = createAutoStrategyRefresh({ store, request: requestJson, setStatus });

async function refreshWorkbench({ forceStrategy = false } = {}) {
  const next = await refreshModules();
  const dataReady = !next.moduleErrors?.board && !next.moduleErrors?.matches;
  if (dataReady) await autoStrategy.ensure({ force: forceStrategy });
  return store.get();
}
const pageLoader = createPageLoader();

let router;
let taskPageModule;
const pollControllers = new Map();

async function loadPageModule(page) {
  const loaded = await pageLoader.load(page);
  if (page === "tasks") taskPageModule = loaded.module;
  return loaded;
}

async function getTaskPageModule() {
  if (taskPageModule) return taskPageModule;
  return (await loadPageModule("tasks")).module;
}

function updateActiveRun(kind, patch) {
  store.set((state) => {
    const previous = state.activeRuns[kind] || { kind, run_type: kind, logs: [] };
    const next = { ...previous, ...patch, kind, run_type: kind };
    if (patch.message && patch.message !== previous.message) {
      const baseLogs = Array.isArray(patch.logs) ? patch.logs : (previous.logs || []);
      next.logs = [...baseLogs, patch.message].slice(-30);
    }
    return { ...state, activeRuns: { ...state.activeRuns, [kind]: next } };
  });
}

function stopPolling({ markDisconnected = false } = {}) {
  for (const [kind, controller] of pollControllers) {
    controller.abort();
    if (markDisconnected && store.get().activeRuns[kind]?.status === "running") {
      updateActiveRun(kind, { polling: "disconnected" });
    }
  }
  pollControllers.clear();
}

function connectRun(kind, runId, taskModule) {
  pollControllers.get(kind)?.abort();
  const controller = new AbortController();
  pollControllers.set(kind, controller);
  updateActiveRun(kind, { id: runId, status: "running", polling: "connected" });
  void taskModule.pollRun(runId, {
    signal: controller.signal,
    onUpdate(run) {
      updateActiveRun(kind, { ...run, kind, polling: "connected" });
      if (["done", "error"].includes(run.status)) controller.abort();
    },
  }).catch((error) => {
    if (error?.name !== "AbortError") {
      updateActiveRun(kind, { polling: "disconnected" });
      setStatus(`${pageTitles.tasks[0]}网络中断，可手动重新连接`, "warning");
    }
  }).finally(() => {
    controller.abort();
    if (pollControllers.get(kind) === controller) pollControllers.delete(kind);
  });
}

async function launchTask(kind) {
  try {
    const taskModule = await getTaskPageModule();
    if (taskModule.taskActionState(kind, store.get().activeRuns).disabled) return;
    const started = await taskModule.startTask(kind, store.get().salesDay);
    updateActiveRun(kind, {
      id: started.run_id, status: "running", total: 0, done: 0,
      started_at: new Date().toISOString(), message: "任务已提交", logs: [],
    });
    connectRun(kind, started.run_id, taskModule);
  } catch (error) {
    if (error?.status === 409) {
      await refreshModules(["activeRuns"]);
      setStatus("同类任务已在运行，已恢复服务端运行状态", "warning");
    } else setStatus(`任务启动失败：${error.message}`, "error");
  }
}

async function launchFailedRetry(kind, runId) {
  try {
    const taskModule = await getTaskPageModule();
    const started = await taskModule.retryFailed(runId);
    updateActiveRun(kind, {
      id: started.run_id, status: "running", total: started.match_ids?.length || 0,
      done: 0, started_at: new Date().toISOString(),
      message: `仅重试 ${started.match_ids?.length || 0} 个失败项`, logs: [],
    });
    connectRun(kind, started.run_id, taskModule);
  } catch (error) {
    if (error?.status === 409) {
      await refreshModules(["activeRuns"]);
      setStatus("同类任务已在运行，未重复提交失败项", "warning");
    } else setStatus(`失败项重试被拒绝：${error.message}`, "error");
  }
}

async function reconnectRun(kind, runId) {
  try {
    connectRun(kind, runId, await getTaskPageModule());
  } catch (error) {
    setStatus(`任务重新连接失败：${error?.message || "未知错误"}`, "error");
  }
}

async function generateExport() {
  const previous = store.get().exportReport || { state: "idle" };
  store.set((state) => ({ ...state, exportReport: { state: "loading", generatedAt: previous.generatedAt || null } }));
  try {
    const exportModule = (await loadPageModule("export")).module;
    const result = await exportModule.downloadExportReport();
    store.set((state) => ({ ...state, exportReport: { state: "ready", ...result } }));
    setStatus("导出报告已生成并开始下载", "ok");
  } catch (error) {
    store.set((state) => ({ ...state, exportReport: {
      state: "error",
      generatedAt: previous.generatedAt || null,
      message: error?.message || "未知错误",
    } }));
    setStatus("导出报告生成失败，保留上次成功信息", "warning");
  }
}

const pageModuleKeys = {
  overview: ["board", "matches", "lateInfo", "dailyStrategy"],
  strategy: ["dailyStrategy", "strategyBacktest"],
  backtest: ["history"],
  leagues: ["history"],
  evidence: ["board", "lateInfo"],
  versions: ["versionProgress", "versionGovernance"],
  tasks: ["activeRuns"],
};

function moduleErrorPanel(page, state) {
  const errors = Object.entries(state.moduleErrors || {})
    .filter(([key]) => (pageModuleKeys[page] || []).includes(key));
  if (!errors.length) return "";
  const rows = errors.map(([key, error]) => `<li><strong>${esc(key)}</strong>：${esc(error.message || "未知错误")}<br>来源：${esc(error.path || "未记录")}；上次成功：${esc(error.lastSuccessfulAt || "无")}<br><button class="button" type="button" data-module-retry="${esc(key)}">重试本模块</button></li>`).join("");
  return `<section class="page-intro" aria-label="模块读取失败"><h2>部分模块暂不可用</h2><p>其他页面和已缓存数据不受影响。</p><ul>${rows}</ul></section>`;
}

function pageContext(params) {
  const state = store.get();
  return {
    board: state.cache.board,
    matches: state.cache.matches,
    dailyStrategy: state.cache.dailyStrategy,
    strategyBacktest: state.cache.strategyBacktest,
    history: state.cache.history,
    lateInfo: state.cache.lateInfo,
    versionProgress: state.cache.versionProgress,
    versionGovernance: state.cache.versionGovernance,
    cacheTimes: state.cacheTimes,
    moduleErrors: state.moduleErrors,
    activeRuns: state.activeRuns,
    autoStrategy: state.autoStrategy,
    salesDay: state.salesDay,
    now: state.cache.board?.as_of,
    params,
    navigate: (target, targetParams) => router.navigate(target, targetParams),
    onStartTask: (kind) => { void launchTask(kind); },
    onReconnect: (kind, runId) => { void reconnectRun(kind, runId); },
    onRetryFailed: (kind, runId) => { void launchFailedRetry(kind, runId); },
    exportReport: state.exportReport,
    onGenerate: () => { void generateExport(); },
  };
}

const pageRuntime = createAsyncPageRuntime({
  root,
  loadPage: loadPageModule,
  contextFor: (_page, params) => pageContext(params),
  renderError: renderPageLoadError,
  titleFor: (page) => pageTitles[page]?.[0] || "页面",
  lastSuccessFor: (page) => store.get().pageSuccessTimes?.[page],
  afterRender: (page) => root.insertAdjacentHTML("beforeend", moduleErrorPanel(page, store.get())),
  onReady: (page) => store.set((current) => ({ ...current, pageSuccessTimes: { ...current.pageSuccessTimes, [page]: new Date().toISOString() } })),
  onError: ({ page }) => setStatus(`${pageTitles[page]?.[0] || "页面"}读取失败，可重试本模块`, "error"),
});

function renderContent(page, params) {
  return pageRuntime.render(page, params);
}

function renderPage({ page, params }) {
  const current = store.get();
  if (current.page === "tasks" && page !== "tasks") stopPolling({ markDisconnected: true });
  if (current.page !== page || JSON.stringify(current.filters) !== JSON.stringify(params)) {
    store.set((state) => ({ ...state, page, filters: params }));
  }
  document.querySelectorAll("[data-route]").forEach((link) => {
    const isCurrent = link.dataset.route === page;
    link.classList.toggle("is-current", isCurrent);
    if (isCurrent) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
  const rendered = renderContent(page, params);
  root.focus({ preventScroll: true });
  void rendered.then((result) => {
    if (result.state === "ready" && store.get().page === page) {
      setStatus(`${pageTitles[page][0]} 已打开`, "ok");
      if (["overview", "strategy"].includes(page)) void autoStrategy.ensure();
    }
  });
}
router = createRouter({ routes: pageTitles, onRoute: closeSidebarOnRoute(sidebarController, renderPage) });
root.addEventListener("matchselect", (event) => {
  const matchId = event.detail?.matchId;
  if (!matchId) return;
  store.set((state) => ({ ...state, selectedMatchId: matchId }));
  void matchDrawer.open(matchId, document.activeElement);
});
store.subscribe((next, previous) => {
  if ((next.cache !== previous.cache || next.salesDay !== previous.salesDay
       || next.activeRuns !== previous.activeRuns || next.moduleErrors !== previous.moduleErrors
       || next.exportReport !== previous.exportReport || autoStrategyChanged(next, previous))
      && ["overview", "strategy", "backtest", "leagues", "evidence", "tasks", "versions", "export"].includes(next.page)) {
    void renderContent(next.page, next.filters);
  }
});
root.addEventListener("click", (event) => {
  const moduleRetry = event.target.closest?.("[data-module-retry]");
  if (moduleRetry) { void refreshModules([moduleRetry.dataset.moduleRetry]); return; }
  const pageRetry = event.target.closest?.("[data-page-retry]");
  if (pageRetry) {
    const page = pageRetry.dataset.pageRetry;
    if (page === store.get().page) pageLoader.invalidate(page);
    void renderContent(page, store.get().filters);
    return;
  }
  if (event.target.closest?.("[data-export-generate]")) void generateExport();
});
bindSidebarRouteClosure(document.querySelectorAll("[data-route]"), sidebarController);
sidebarToggle.addEventListener("click", () => sidebarController.toggle());
mobileSidebar.addEventListener("change", () => sidebarController.sync());
document.querySelector("#refresh-shell").addEventListener("click", () => { void refreshWorkbench({ forceStrategy: true }); });
salesDayInput.value = shanghaiSalesDay();
store.set((state) => ({ ...state, salesDay: salesDayInput.value }));
salesDayInput.addEventListener("change", () => {
  store.set((state) => ({ ...state, salesDay: salesDayInput.value }));
  void refreshWorkbench({ forceStrategy: true });
});
sidebarController.sync();
router.start();
setStatus("正在刷新工作台数据", "neutral");
void refreshWorkbench();
