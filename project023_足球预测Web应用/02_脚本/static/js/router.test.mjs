import test from "node:test";
import assert from "node:assert/strict";
import { bindSidebarRouteClosure, closeSidebarOnRoute, createSidebarController, escapeHtml, normalizeRoute } from "./router.js";

function element() {
  const attributes = new Map();
  const classes = new Set();
  return {
    inert: false,
    classList: {
      toggle(name, force) { if (force) classes.add(name); else classes.delete(name); },
      contains(name) { return classes.has(name); },
    },
    setAttribute(name, value) { attributes.set(name, String(value)); },
    removeAttribute(name) { attributes.delete(name); },
    getAttribute(name) { return attributes.get(name) ?? null; },
  };
}

test("retired scanner and unknown routes fall back to overview", () => {
  assert.deepEqual(normalizeRoute("#scanner?status=missing"), {
    page: "overview",
    params: {},
  });
  assert.deepEqual(normalizeRoute("#unknown"), { page: "overview", params: {} });
});

test("route-filter values are safe to render in the page shell", () => {
  assert.equal(escapeHtml('<script>alert("x")</script>'), "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;");
});

test("collapsed mobile sidebar is inert and hidden from assistive technology", () => {
  const sidebar = element();
  const toggle = element();
  const controller = createSidebarController({ sidebar, toggle, isMobile: () => true });
  controller.sync();
  assert.equal(sidebar.inert, true);
  assert.equal(sidebar.getAttribute("aria-hidden"), "true");
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.getAttribute("aria-label"), "打开导航");
});

test("open mobile sidebar is focusable and exposes close semantics", () => {
  const sidebar = element();
  const toggle = element();
  const controller = createSidebarController({ sidebar, toggle, isMobile: () => true });
  controller.toggle();
  assert.equal(sidebar.inert, false);
  assert.equal(sidebar.getAttribute("aria-hidden"), null);
  assert.equal(sidebar.classList.contains("is-open"), true);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(toggle.getAttribute("aria-label"), "关闭导航");
});

test("route-link closure restores the collapsed mobile sidebar state", () => {
  const sidebar = element();
  const toggle = element();
  const controller = createSidebarController({ sidebar, toggle, isMobile: () => true });
  controller.toggle();
  controller.close();
  assert.equal(sidebar.inert, true);
  assert.equal(sidebar.getAttribute("aria-hidden"), "true");
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.getAttribute("aria-label"), "打开导航");
});

test("route-link closure invokes the shared sidebar close state", () => {
  let handler;
  const link = { addEventListener(name, callback) { if (name === "click") handler = callback; } };
  let closes = 0;
  bindSidebarRouteClosure([link], { close() { closes += 1; } });
  handler();
  assert.equal(closes, 1);
});

test("every route dispatch closes an open mobile sidebar before rendering", () => {
  const events = [];
  const route = { page: "export", params: {} };
  const handler = closeSidebarOnRoute(
    { close() { events.push("close"); } },
    (next) => events.push(next),
  );
  handler(route);
  assert.deepEqual(events, ["close", route]);
});
