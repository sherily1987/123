export function createRefreshController({ store, modules, request, setStatus, now = () => new Date().toISOString() }) {
  let generation = 0;

  return {
    async refresh(keys = modules.map((module) => module.key)) {
      const requestId = ++generation;
      const { salesDay } = store.get();
      const selected = modules.filter((module) => keys.includes(module.key));
      if (!selected.length) return store.get();
      store.set((state) => ({ ...state, activeRuns: { ...state.activeRuns, refresh: true } }));
      const results = await Promise.allSettled(selected.map((module) => request(module.path(salesDay))));
      if (requestId !== generation || store.get().salesDay !== salesDay) return store.get();

      const failures = [];
      let successful = 0;
      store.set((state) => {
        let nextState = state;
        const cache = { ...state.cache };
        const cacheTimes = { ...state.cacheTimes };
        const moduleErrors = { ...(state.moduleErrors || {}) };
        const staleKeys = new Set(state.staleKeys);
        results.forEach((result, index) => {
          const module = selected[index];
          const key = module.key;
          if (result.status === "fulfilled") {
            cache[key] = result.value;
            cacheTimes[key] = now();
            staleKeys.delete(key);
            delete moduleErrors[key];
            successful += 1;
            if (typeof module.apply === "function") nextState = module.apply(result.value, nextState);
          } else {
            staleKeys.add(key);
            failures.push(key);
            moduleErrors[key] = {
              path: result.reason?.path || module.path(salesDay),
              message: result.reason?.message || "未知错误",
              lastSuccessfulAt: cacheTimes[key] || null,
            };
          }
        });
        const { refresh, ...activeRuns } = nextState.activeRuns;
        return { ...nextState, cache, cacheTimes, moduleErrors, staleKeys: [...staleKeys], activeRuns };
      });
      if (failures.length === 0) setStatus("数据已刷新", "ok");
      else if (successful > 0) setStatus(`已刷新 ${successful} 个模块；${failures.length} 个模块保留上次可用数据`, "warning");
      else setStatus("数据刷新失败，保留上次可用数据", "error");
      return store.get();
    },
  };
}
