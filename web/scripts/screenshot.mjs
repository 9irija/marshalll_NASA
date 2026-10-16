// Screenshot the running web app for visual checks.
// node scripts/screenshot.mjs [url] [out.png] [waitMs] [--click=selector ...] [--size=1600x900]
import { chromium } from "playwright";

const args = process.argv.slice(2);
const pos = args.filter((a) => !a.startsWith("--"));
const url = pos[0] ?? "http://localhost:5173/";
const out = pos[1] ?? "screenshot.png";
const wait = Number(pos[2] ?? 15000);
const steps = args.filter((a) => a.startsWith("--click=") || a.startsWith("--eval="));
const size = (args.find((a) => a.startsWith("--size=")) ?? "--size=1600x900").slice(7).split("x").map(Number);

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: size[0], height: size[1] } });
const logs = [];
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") logs.push(`${m.type()}: ${m.text()}`); });
page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(wait);
for (const st of steps) {   // run steps in the order given
  if (st.startsWith("--click=")) { await page.click(st.slice(8)); await page.waitForTimeout(4000); }
  else { await page.evaluate(st.slice(7)); await page.waitForTimeout(3000); }
}
await page.screenshot({ path: out });
console.log(logs.slice(0, 25).join("\n"));
await browser.close();
