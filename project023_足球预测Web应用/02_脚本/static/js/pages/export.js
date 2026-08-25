import { esc } from "../format.js";

const REPORT_PATH = "/api/export/report";

export function exportStatusText(report = {}) {
  if (report.state === "ready") return `已生成 · ${report.generatedAt || "时间未记录"}`;
  if (report.state === "error") return `生成失败 · ${report.message || "未知错误"}`;
  if (report.state === "loading") return "正在生成";
  return "尚未生成";
}

function browserDownload(href, filename) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
}

export async function downloadExportReport({
  request = (path) => fetch(path, { cache: "no-store" }),
  createObjectUrl = (blob) => URL.createObjectURL(blob),
  revokeObjectUrl = (url) => URL.revokeObjectURL(url),
  triggerDownload = browserDownload,
  now = () => new Date().toISOString(),
} = {}) {
  const response = await request(REPORT_PATH);
  if (!response.ok) throw new Error(`请求失败 (${response.status || "未知"}): ${REPORT_PATH}`);
  const blob = await response.blob();
  const href = createObjectUrl(blob);
  try {
    triggerDownload(href, "体彩看板.md");
  } finally {
    setTimeout(() => revokeObjectUrl(href), 0);
  }
  return { generatedAt: now() };
}

export function renderExport(root, context = {}) {
  const report = context.exportReport || { state: "idle" };
  const stale = report.state === "error" && report.generatedAt;
  const generated = report.generatedAt
    ? `<p><strong>上次成功生成：</strong>${esc(report.generatedAt)}${stale ? "（可能已过期）" : ""}</p>`
    : "";
  const failure = report.state === "error"
    ? `<p role="alert">${esc(exportStatusText(report))}</p>`
    : "";
  root.innerHTML = `<section class="page-intro" aria-labelledby="page-title"><p class="eyebrow">足球预测工作台 / B3</p><h1 id="page-title">导出报告</h1><p>范围：当前体彩看板、正式登记的 market_only 量化输出，以及独立 LLM 证据方向。报告不合并两条轨道，不会写入生产模型。</p><p><strong>状态：</strong>${esc(exportStatusText(report))}</p>${generated}${failure}<div class="export-actions"><button class="button button--primary" type="button" data-export-generate${report.state === "loading" ? " disabled" : ""}>生成并下载报告</button><a class="button" href="${REPORT_PATH}" download="体彩看板.md" data-export-direct>直接下载报告</a></div><p class="route-filter">文件接口：${REPORT_PATH}；下载为同源 Markdown 文件，不按 JSON 解析。</p></section>`;
}
