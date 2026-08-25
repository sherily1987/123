const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ESCAPES[character]);
}

export function displayMissing(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

export function isFiniteValue(value) {
  return value !== null
    && value !== undefined
    && !(typeof value === "string" && value.trim() === "")
    && Number.isFinite(Number(value));
}

export function formatPct(values, fallback = "—") {
  if (!Array.isArray(values) || values.length === 0 || values.some((value) => !isFiniteValue(value))) return fallback;
  return `${values.map((value) => Number(value).toFixed(1)).join(" / ")}%`;
}

export function formatMoney(value, fallback = "—") {
  if (!isFiniteValue(value)) return fallback;
  return `¥${Number(value).toFixed(2)}`;
}

export function shanghaiSalesDay(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) throw new TypeError("invalid date");
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  const byType = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${byType.year}-${byType.month}-${byType.day}`;
}
