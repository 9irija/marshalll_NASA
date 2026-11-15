// Render submission/deck.html to submission/Marswalk_demo.pdf (7 slides, 1600x900) and PNG previews.
import { chromium } from "playwright";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const deck = resolve(process.argv[2] ?? "../submission/deck.html");
const out = resolve(process.argv[3] ?? "../submission/Marswalk_demo.pdf");
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
await page.goto(pathToFileURL(deck).href, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
await page.pdf({ path: out, width: "1600px", height: "900px", printBackground: true, preferCSSPageSize: true });
const n = await page.locator(".slide").count();
for (let i = 0; i < n; i++) {
  await page.locator(".slide").nth(i).screenshot({ path: out.replace(/\.pdf$/, `_slide${i + 1}.png`) });
}
console.log(`wrote ${out} (${n} slides)`);
await browser.close();
