// Turns the pictures a browser-test run saved into a pull request comment:
// one folded section per test file and screen size, so a reader opens only
// what they want to look at.
//
//   node scripts/screenshot-gallery.mjs --pictures <dir> --out <dir>
//     [--image-url <public URL that <out>/images will be served from>]
//     [--label <commit>] [--run-url <url>]
//
// Writes <out>/comment.md and copies the pictures, renamed flat, into
// <out>/images. Pictures are matched to their test file by Playwright's
// output folder name, which starts with the spec's name.
import { copyFileSync, existsSync, mkdirSync, openSync, readSync, closeSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const MARKER = "<!-- ci-screenshots -->";
// Narrower than this is a phone-width page.
const PHONE_MAX_WIDTH = 500;
// Thinner than this is a crop a test took to measure pixels, not a view of
// the app, and is left out.
const MIN_SIDE = 100;
const MAX_UNSPLIT = 4;

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i].startsWith("--")) throw new Error(`Unexpected argument ${argv[i]}`);
    args[argv[i].slice(2)] = argv[i + 1];
  }
  for (const required of ["pictures", "out"]) {
    if (!args[required]) throw new Error(`--${required} is required`);
  }
  return args;
}

// Width and height from the PNG header, which is all this needs to know.
function pngSize(file) {
  const header = Buffer.alloc(24);
  const fd = openSync(file, "r");
  try {
    readSync(fd, header, 0, 24, 0);
  } finally {
    closeSync(fd);
  }
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) };
}

function collect(root) {
  const found = [];
  if (!existsSync(root)) return found;
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      // Playwright's own failure screenshots only exist when a test failed.
      else if (entry.name.endsWith(".png") && !entry.name.startsWith("test-failed-")) found.push(full);
    }
  };
  walk(root);
  return found;
}

function title(spec) {
  const words = spec.replace(/[-_]+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const args = parseArgs(process.argv.slice(2));
const specs = readdirSync(new URL("../e2e/", import.meta.url))
  .filter((name) => name.endsWith(".spec.ts"))
  .map((name) => name.replace(/\.spec\.ts$/, ""))
  .sort((a, b) => b.length - a.length);

const bySpec = new Map();
for (const file of collect(args.pictures)) {
  const { width, height } = pngSize(file);
  if (Math.min(width, height) < MIN_SIDE) continue;
  const folder = path.basename(path.dirname(file));
  const spec = specs.find((name) => folder.startsWith(`${name}-`)) ?? "other";
  if (!bySpec.has(spec)) bySpec.set(spec, []);
  bySpec.get(spec).push({ file, name: path.basename(file, ".png"), phone: width <= PHONE_MAX_WIDTH });
}
// A test file with only a few pictures keeps them in one section.
const sections = new Map();
for (const [spec, pictures] of bySpec) {
  for (const picture of pictures) {
    const key = pictures.length <= MAX_UNSPLIT ? title(spec) : `${title(spec)} · ${picture.phone ? "phone" : "desktop"}`;
    if (!sections.has(key)) sections.set(key, []);
    sections.get(key).push(picture);
  }
}

const imageUrl = (args["image-url"] ?? "images").replace(/\/$/, "");
mkdirSync(path.join(args.out, "images"), { recursive: true });
const count = [...sections.values()].reduce((total, pictures) => total + pictures.length, 0);
const label = args.label ? ` on ${args.label}` : "";
const lines = [MARKER, "### Screenshots", ""];
if (count === 0) {
  lines.push(`The browser tests saved no pictures${label}.`);
} else {
  lines.push(`${count} pictures from the browser tests${label}, taken with fake test data. Open a section to look.`);
}

let index = 0;
for (const key of [...sections.keys()].sort()) {
  const pictures = sections.get(key).sort((a, b) => a.name.localeCompare(b.name));
  lines.push("", "<details>", `<summary><b>${key}</b> (${pictures.length})</summary>`, "");
  for (const picture of pictures) {
    index += 1;
    const stored = `${String(index).padStart(2, "0")}-${picture.name.replace(/[^A-Za-z0-9._-]+/g, "_")}.png`;
    copyFileSync(picture.file, path.join(args.out, "images", stored));
    lines.push(`**${picture.name}**`, "", `<img src="${imageUrl}/${stored}" alt="${picture.name}">`, "");
  }
  lines.push("</details>");
}
if (args["run-url"]) lines.push("", `<sub>[Test run](${args["run-url"]})</sub>`);
lines.push("");

writeFileSync(path.join(args.out, "comment.md"), lines.join("\n"));
console.log(`${count} pictures in ${sections.size} sections`);
