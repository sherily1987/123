export function strategyNeedsGeneration(plan) {
  if (plan === undefined) return false;
  return !plan?.generated_at && !plan?.snapshot_id;
}

export function autoStrategyChanged(next, previous) {
  return next.autoStrategy !== previous.autoStrategy;
}

export function createAutoStrategyRefresh({ store, request, setStatus, now = () => new Date().toISOString(), isCurrentSalesDay = () => true }) {
  let inFlight = null;

  function setAutoStrategy(status, message) {
    store.set((state) => ({ ...state, autoStrategy: { status, message } }));
  }

  function applyAuthority(authority) {
    const salesDay = authority?.sales_day;
    if (!salesDay) throw new Error("后端未返回权威销售日");
    store.set((state) => {
      const moduleErrors = { ...(state.moduleErrors || {}) };
      delete moduleErrors.currentSaleDay;
      return {
        ...state,
        cache: { ...state.cache, currentSaleDay: { sales_day: salesDay } },
        cacheTimes: { ...state.cacheTimes, currentSaleDay: now() },
        moduleErrors,
      };
    });
    return salesDay;
  }

  function clearAuthority(error) {
    store.set((state) => {
      const { currentSaleDay, ...cache } = state.cache || {};
      const { currentSaleDay: _timestamp, ...cacheTimes } = state.cacheTimes || {};
      return {
        ...state,
        cache,
        cacheTimes,
        moduleErrors: {
          ...(state.moduleErrors || {}),
          currentSaleDay: { path: "/api/current-sale-day", message: error?.message || "权威销售日读取失败" },
        },
      };
    });
  }

  async function readAuthority() {
    try {
      return applyAuthority(await request("/api/current-sale-day"));
    } catch (error) {
      clearAuthority(error);
      throw error;
    }
  }

  function discard(message) {
    setAutoStrategy("error", message);
    setStatus(message.replace(/[。.]$/, ""), "error");
    return store.get();
  }

  async function generate() {
    const selectedInputDay = store.get().salesDay;
    if (!isCurrentSalesDay(selectedInputDay)) return store.get();
    setAutoStrategy("running", "正在自动生成当前销售日策略…");
    try {
      const requestDay = await readAuthority();
      if (store.get().salesDay !== selectedInputDay || selectedInputDay !== requestDay) {
        return discard("权威销售日与当前输入不一致，已取消策略生成。");
      }
      const plan = await request("/api/daily-strategy/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_sales_day: requestDay }),
      });
      const latestAuthorityDay = await readAuthority();
      const currentInputDay = store.get().salesDay;
      if (currentInputDay !== requestDay
          || plan?.selected_day !== requestDay
          || latestAuthorityDay !== requestDay) {
        return discard("策略生成结果销售日不一致，已丢弃。");
      }
      store.set((state) => ({
        ...state,
        cache: { ...state.cache, dailyStrategy: plan },
        cacheTimes: { ...state.cacheTimes, dailyStrategy: now() },
        autoStrategy: { status: "done", message: "当前销售日策略已自动生成" },
      }));
      setStatus("当前销售日策略已自动生成", "ok");
    } catch (error) {
      if (error?.status === 409 || error?.code === "sales_day_authority_changed") {
        clearAuthority(error);
        setAutoStrategy("error", "销售日已切换，服务端未提交且本地未缓存新策略，请刷新后重试。");
        setStatus("销售日已切换，策略未缓存", "warning");
        return store.get();
      }
      setAutoStrategy("error", `策略自动生成失败：${error?.message || "未知错误"}`);
      setStatus("策略自动生成失败，保留上次策略", "warning");
    } finally {
      if (store.get().autoStrategy?.status === "running") {
        setAutoStrategy("idle", "策略生成未完成，已安全复位，可重新运行。");
      }
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
