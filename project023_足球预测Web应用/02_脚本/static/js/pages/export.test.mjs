import test from "node:test";
import assert from "node:assert/strict";
import { downloadExportReport, exportStatusText, renderExport } from "./export.js";

test("export states are explicit", () => {
  assert.equal(exportStatusText({ state: "idle" }), "尚未生成");
  assert.equal(exportStatusText({ state: "ready", generatedAt: "2026-08-25T12:00:00+08:00" }), "已生成 · 2026-08-25T12:00:00+08:00");
  assert.equal(exportStatusText({ state: "error", message: "500" }), "生成失败 · 500");
});

test("export keeps the last successful generation information after a later failure", () => {
  const root = {};
  renderExport(root, {
    exportReport: {
      state: "error",
      generatedAt: "2026-08-25T12:00:00+08:00",
      message: '<img onerror="x">',
    },
  });

  assert.match(root.innerHTML, /可能已过期/);
  assert.match(root.innerHTML, /href="\/api\/export\/report"/);
  assert.match(root.innerHTML, /直接下载报告/);
  assert.match(root.innerHTML, /&lt;img onerror=&quot;x&quot;&gt;/);
  assert.doesNotMatch(root.innerHTML, /<img onerror/);
});

test("export download handles the report as a file blob instead of JSON", async () => {
  const triggered = [];
  const result = await downloadExportReport({
    request: async (path) => {
      assert.equal(path, "/api/export/report");
      return { ok: true, blob: async () => new Blob(["# 报告"]), json: () => { throw new Error("must not parse JSON"); } };
    },
    createObjectUrl: () => "blob:report",
    revokeObjectUrl: () => {},
    triggerDownload: (href, filename) => triggered.push([href, filename]),
    now: () => "2026-08-25T12:00:00+08:00",
  });

  assert.deepEqual(result, { generatedAt: "2026-08-25T12:00:00+08:00" });
  assert.deepEqual(triggered, [["blob:report", "体彩看板.md"]]);
});
