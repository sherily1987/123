import { esc } from "./format.js";

const TONES = new Set(["neutral", "ok", "warning", "error"]);

function toneName(tone) {
  return TONES.has(tone) ? tone : "neutral";
}

export function renderStatus(message, tone = "neutral") {
  return `<p class="module-status module-status--${toneName(tone)}" role="status">${esc(message)}</p>`;
}

export function renderModuleState({ label = "数据模块", loading = false, stale = false, error = null, empty = false } = {}) {
  if (loading) return renderStatus(`${label}正在加载`, "neutral");
  if (error) return renderStatus(`${label}暂不可用：${error}`, "error");
  if (stale) return renderStatus(`${label}显示上次可用数据，等待刷新`, "warning");
  if (empty) return renderStatus(`${label}暂无数据`, "neutral");
  return "";
}
