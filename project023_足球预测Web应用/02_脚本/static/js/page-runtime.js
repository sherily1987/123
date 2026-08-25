import { esc } from "./format.js";

export function pageSource(page) {
  return `/js/pages/${page}.js`;
}

export function renderPageLoadError(root, { page, error, source = pageSource(page), title, lastSuccessfulAt } = {}) {
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">${esc(title || page || "页面")}暂不可用</h1><p role="alert">${esc(error?.message || "未知错误")}</p><p>来源：${esc(source)}；上次成功：${esc(lastSuccessfulAt || "无")}</p><button class="button" type="button" data-page-retry="${esc(page)}">重试本模块</button></section>`;
}

export function createAsyncPageRuntime({
  root,
  loadPage,
  contextFor = () => ({}),
  renderError = renderPageLoadError,
  titleFor = (page) => page,
  lastSuccessFor = () => null,
  afterRender = () => {},
  onReady = () => {},
  onError = () => {},
} = {}) {
  let generation = 0;

  return {
    async render(page, params = {}) {
      const requestId = ++generation;
      const source = pageSource(page);
      try {
        const loaded = await loadPage(page);
        if (requestId !== generation) return { state: "stale", page };
        await loaded.render(root, contextFor(page, params, loaded.module));
        if (requestId !== generation) return { state: "stale", page };
        afterRender(page, params, loaded.module);
        onReady(page, params, loaded.module);
        return { state: "ready", page };
      } catch (error) {
        if (requestId !== generation) return { state: "stale", page };
        const details = {
          page,
          error,
          source: error?.source || source,
          title: titleFor(page),
          lastSuccessfulAt: lastSuccessFor(page),
        };
        renderError(root, details);
        onError(details);
        return { state: "error", page, error };
      }
    },
  };
}
