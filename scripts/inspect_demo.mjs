// Inspect actual Edge recording metadata and retain a frame for visual QA.
import { createRequire } from "node:module";
import { resolve, join, relative } from "node:path";
import { readdirSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { createHash } from "node:crypto";

const root = resolve(process.argv[2] || ".");
const { chromium } = createRequire(join(root, "frontend/package.json"))("@playwright/test");
const artifacts = join(root, "artifacts/m6");
function videos(folder) {
  return readdirSync(folder, { withFileTypes: true }).flatMap((entry) => {
    const file = join(folder, entry.name);
    return entry.isDirectory() ? videos(file) : file.endsWith(".webm") ? [file] : [];
  });
}
const browser = await chromium.launch({ channel: "msedge", headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  const { pathToFileURL } = await import("node:url");
  const inspected = [];
  for (const file of videos(resolve(process.argv[3] || join(artifacts, "recordings")))) {
    await page.goto(pathToFileURL(file).href);
    await page.waitForFunction(() => {
      const video = document.querySelector("video");
      return video && Number.isFinite(video.duration) && video.duration > 0;
    });
    const data = await page.locator("video").evaluate((v) => ({
      duration_seconds: v.duration, width: v.videoWidth, height: v.videoHeight,
    }));
    inspected.push({ file, ...data });
  }
  inspected.sort((a, b) => b.duration_seconds - a.duration_seconds);
  if (!inspected.length) throw new Error("No real recording found");
  const demo = inspected[0];
  copyFileSync(demo.file, join(artifacts, "demo.webm"));
  await page.goto(pathToFileURL(demo.file).href);
  await page.locator("video").evaluate((v) => { v.pause(); v.currentTime = 90; });
  await page.waitForFunction(() => {
    const v = document.querySelector("video");
    return v && !v.seeking && v.readyState >= 2;
  });
  await page.screenshot({ path: join(artifacts, "demo-frame.png") });
  const result = {
    duration_seconds: Math.round(demo.duration_seconds * 1000) / 1000,
    width: demo.width, height: demo.height,
    sha256: createHash("sha256").update(readFileSync(join(artifacts, "demo.webm"))).digest("hex"),
    source_recording: relative(root, demo.file).replaceAll("\\", "/"),
    inspected_recordings: inspected.length,
  };
  writeFileSync(join(artifacts, "demo_metadata.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
