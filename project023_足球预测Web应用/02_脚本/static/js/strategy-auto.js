export function strategyNeedsGeneration(plan) {
  if (plan === undefined) return false;
  return !plan?.generated_at && !plan?.snapshot_id;
}

export function autoStrategyChanged(next, previous) {
  return next.autoStrategy !== previous.autoStrategy;
}

export function createAutoStrategyRefresh({ store, request, setStatus, now = () => new Date().toISOString(), isCurrentSalesDay = () => true }) {
  let inFlight = null;

  async function generate() {
    const salesDay = store.get().salesDay;
    if (!isCurrentSalesDay(salesDay)) return store.get();
    store.set((state) => ({
      ...state,
      autoStrategy: { status: "running", message: "正在自动生成当前销售日策略…" },
    }));
    try {
      const plan = await request("/api/daily-strategy/recommend", { method: "POST" });
      if (store.get().salesDay !== salesDay) return store.get();
      store.set((state) => ({
        ...state,
        cache: { ...state.cache, dailyStrategy: plan },
        cacheTimes: { ...state.cacheTimes, dailyStrategy: now() },
        autoStrategy: { status: "done", message: "当前销售日策略已自动生成" },
      }));
      setStatus("当前销售日策略已自动生成", "ok");
    } catch (error) {
      store.set((state) => ({
        ...state,
        autoStrategy: { status: "error", message: `策略自动生成失败：${error?.message || "未知错误"}` },
      }));
      setStatus("策略自动生成失败，保留上次策略", "warning");
    }
    return store.get();
  }

  return {
    ensure({ force = false } = {}) {
      if (!isCurrentSalesDay(store.get().salesDay)) {
        const current = store.get().autoStrategy;
        if (current?.status !== "idle" || current?.message !== "历史销售日只读展示，不自动生成策略。") {
          store.set((state) => ({
            ...state,
            autoStrategy: { status: "idle", message: "历史销售日只读展示，不自动生成策略。" },
          }));
        }
        return Promise.resolve(store.get());
      }
      if (!force && !strategyNeedsGeneration(store.get().cache?.dailyStrategy)) {
        return Promise.resolve(store.get());
      }
      if (!inFlight) inFlight = generate().finally(() => { inFlight = null; });
      return inFlight;
    },
  };
}
