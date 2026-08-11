import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PresentationFile } from "@oai/artifact-tool";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pptxPath = path.join(__dirname, "欧冠预测_奥林匹亚科斯vsNEC奈梅亨.pptx");

const presentation = await PresentationFile.importPptx(await (await import("@oai/artifact-tool")).FileBlob.load(pptxPath));

for (const [index, slide] of presentation.slides.items.entries()) {
  const layout = await slide.export({ format: "layout" });
  const json = JSON.parse(await layout.text());
  const out = path.join(__dirname, `slide-${String(index + 1).padStart(2, "0")}.layout.json`);
  await fs.writeFile(out, JSON.stringify(json, null, 2), "utf8");
}

console.log("LAYOUT_EXPORTED");
