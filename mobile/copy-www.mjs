// Copies the web app's static files from the repo root into mobile/www/ (Capacitor's webDir).
// Run via `npm run copy` (or it runs automatically inside `npm run sync`).
import { mkdirSync, copyFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const www = join(here, "www");
// favicon.svg is in here because the pages link it as "/favicon.svg"; in a bundled
// build the root is www/, so leaving it out would 404 the app's own icon.
const files = ["index.html", "login.html", "dashboard.html", "rooms.html", "theme.js", "i18n.js",
               "favicon.svg"];

rmSync(www, { recursive: true, force: true });
mkdirSync(www, { recursive: true });
for (const f of files) copyFileSync(join(root, f), join(www, f));
console.log(`Copied ${files.length} files into mobile/www/`);
