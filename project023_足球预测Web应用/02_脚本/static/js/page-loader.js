import { pageSource } from "./page-runtime.js";

const importers = {
  overview: (specifier) => import(specifier),
  strategy: (specifier) => import(specifier),
  backtest: (specifier) => import(specifier),
  leagues: (specifier) => import(specifier),
  evidence: (specifier) => import(specifier),
  tasks: (specifier) => import(specifier),
  versions: (specifier) => import(specifier),
  export: (specifier) => import(specifier),
};

const renderExports = {
  overview: "renderOverview",
  strategy: "renderStrategy",
  backtest: "renderBacktest",
  leagues: "renderLeagues",
  evidence: "renderEvidence",
  tasks: "renderTasks",
  versions: "renderVersions",
  export: "renderExport",
};

export function createPageLoader({ loaders = importers, renderNames = renderExports } = {}) {
  const failedPages = new Set();
  const retryGenerations = new Map();

  function specifierFor(page) {
    const retry = retryGenerations.get(page) || 0;
    return retry ? `${pageSource(page)}?retry=${retry}` : pageSource(page);
  }

  return {
    invalidate(page) {
      if (!failedPages.has(page)) return false;
      retryGenerations.set(page, (retryGenerations.get(page) || 0) + 1);
      return true;
    },
    async load(page) {
      const load = loaders[page];
      if (!load) throw new Error(`未知页面模块：${page}`);
      const source = specifierFor(page);
      try {
        const module = await load(source);
        const render = module[renderNames[page]];
        if (typeof render !== "function") throw new Error(`页面渲染器不可用：${page}`);
        failedPages.delete(page);
        return { module, render, source };
      } catch (error) {
        failedPages.add(page);
        if (error && typeof error === "object" && !error.source) error.source = source;
        throw error;
      }
    },
  };
}
