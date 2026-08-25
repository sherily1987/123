export function createStore(initial) {
  let state = initial;
  const listeners = new Set();

  return {
    get() { return state; },
    set(update) {
      const previous = state;
      state = typeof update === "function" ? update(previous) : update;
      listeners.forEach((listener) => listener(state, previous));
      return state;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
