// Copy processed layers, terrain and demo results into public/data for static hosting.
import { cpSync, mkdirSync, readdirSync, rmSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../../data/processed/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const out = new URL("../public/data/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
for (const f of readdirSync(join(root, "web"))) {
  if (f === "runtime") continue;
  cpSync(join(root, "web", f), join(out, f));
}
if (existsSync(join(root, "demo"))) cpSync(join(root, "demo"), join(out, "demo"), { recursive: true });
console.log("synced", readdirSync(out).length, "entries to public/data");
