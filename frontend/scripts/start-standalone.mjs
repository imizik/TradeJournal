// Local production/Playwright launcher. The Linux artifact copies these assets
// during packaging and executes server.js directly under systemd.
import { cpSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);
for (const name of [".next/static", "public"]) {
  const source = new URL(name, root);
  if (existsSync(source)) cpSync(source, new URL(`.next/standalone/${name}`, root), { recursive: true });
}
process.env.HOSTNAME = "127.0.0.1";
await import(fileURLToPath(new URL(".next/standalone/server.js", root)));
