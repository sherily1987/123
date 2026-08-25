const DEFAULT_PAGE = "overview";
const DEFAULT_ROUTES = [
  "overview", "strategy", "backtest", "leagues",
  "evidence", "tasks", "versions", "export",
];

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

export function createSidebarController({ sidebar, toggle, isMobile }) {
  let open = false;
  const sync = () => {
    const mobile = isMobile();
    if (!mobile) open = false;
    const visible = mobile && open;
    const collapsed = mobile && !visible;
    sidebar.classList.toggle("is-open", visible);
    sidebar.inert = collapsed;
    if (collapsed) sidebar.setAttribute("aria-hidden", "true");
    else sidebar.removeAttribute("aria-hidden");
    toggle.setAttribute("aria-expanded", String(visible));
    toggle.setAttribute("aria-label", visible ? "关闭导航" : "打开导航");
    return visible;
  };
  return {
    sync,
    toggle() { open = !open; return sync(); },
    close() { open = false; return sync(); },
  };
}

export function bindSidebarRouteClosure(links, controller) {
  links.forEach((link) => link.addEventListener("click", () => controller.close()));
}

export function closeSidebarOnRoute(controller, onRoute) {
  return (route) => {
    controller.close();
    return onRoute(route);
  };
}

function routeNames(routes) {
  if (Array.isArray(routes)) return routes.map((route) => typeof route === "string" ? route : route.page);
  return Object.keys(routes || {});
}

function toParams(search) {
  const params = {};
  for (const [key, value] of new URLSearchParams(search)) params[key] = value;
  return params;
}

export function normalizeRoute(hash, routes = DEFAULT_ROUTES) {
  const raw = String(hash || "").replace(/^#/, "");
  const [candidate = "", search = ""] = raw.split("?", 2);
  const page = routeNames(routes).includes(candidate) ? candidate : DEFAULT_PAGE;
  return { page, params: page === candidate ? toParams(search) : {} };
}

export function createRouter({ routes = DEFAULT_ROUTES, onRoute = () => {} } = {}) {
  let active = normalizeRoute(window.location.hash, routes);
  const dispatch = () => {
    active = normalizeRoute(window.location.hash, routes);
    onRoute(active);
    return active;
  };
  return {
    navigate(page, params = {}) {
      const target = routeNames(routes).includes(page) ? page : DEFAULT_PAGE;
      const query = new URLSearchParams(params).toString();
      const hash = `#${target}${query ? `?${query}` : ""}`;
      if (window.location.hash === hash) return dispatch();
      window.location.hash = hash;
      return { page: target, params: target === page ? toParams(query) : {} };
    },
    start() {
      window.addEventListener("hashchange", dispatch);
      return dispatch();
    },
    current() { return active; },
  };
}
