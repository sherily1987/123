import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
import { buildSlide19 } from "./layout/slide-19.mjs";

async function writeBlob(path, blob) {
  await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer()));
}

const presentation = Presentation.create({ slideSize: { width: 1280, height: 720 } });

const tokens = {
  title: { runs: [{ run: "测试标题", textStyle: { fontSize: "38.67px", typeface: "Helvetica Neue", color: "#000000" } }], paragraphStyle: { lineSpacingPercent: 90000 } },
  body1: {
    topic: { runs: [{ run: "测试副标题", textStyle: { fontSize: "21.33px", typeface: "Helvetica Neue", color: "#000000" } }], paragraphStyle: { lineSpacingPercent: 110000 } },
    loremIpsumDolorSitAmetConsecteturAdipiscing: { runs: [{ run: "这里是正文内容测试。", textStyle: { fontSize: "21.33px", typeface: "Helvetica Neue", color: "#000000" } }] },
  },
  body2: "60.5%",
  body3: "23.5%",
  body4: "16.0%",
  stat1: "主胜",
  stat2: "平局",
  stat3: "客胜",
  footer1: "3",
};

buildSlide19(presentation, tokens);

const slide = presentation.slides.items[0];
const png = await presentation.export({ slide, format: "png", scale: 1 });
await writeBlob("./test-render.png", png);

const pptx = await PresentationFile.exportPptx(presentation);
await pptx.save("./test-deck.pptx");
console.log("OK");
