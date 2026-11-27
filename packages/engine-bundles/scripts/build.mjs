// Copies the three engines' browser bundles into dist/ and writes versions.json with a SHA-256
// per file. The scanner records these versions on every scan (reproducibility, PROJECT_PLAN 3.2),
// and refuses to run if a bundle's hash does not match versions.json.
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const root = join(dirname(new URL(import.meta.url).pathname), "..");
const dist = join(root, "dist");
const pkgDir = (name) => dirname(require.resolve(`${name}/package.json`));

const engines = [
  { id: "axe", pkg: "axe-core", file: "axe.min.js", out: "axe.js", license: "MPL-2.0" },
  { id: "ibm", pkg: "accessibility-checker-engine", file: "ace.js", out: "ace.js", license: "Apache-2.0" },
  { id: "htmlcs", pkg: "html_codesniffer", file: "build/HTMLCS.js", out: "htmlcs.js", license: "BSD-3-Clause" },
];

mkdirSync(dist, { recursive: true });
const manifest = {};
for (const e of engines) {
  const dir = pkgDir(e.pkg);
  const src = join(dir, e.file);
  if (!existsSync(src)) throw new Error(`${e.pkg}: ${e.file} not found; run pnpm install`);
  copyFileSync(src, join(dist, e.out));
  const buf = readFileSync(src);
  manifest[e.id] = {
    package: e.pkg,
    version: JSON.parse(readFileSync(join(dir, "package.json"), "utf8")).version,
    file: e.out,
    sha256: createHash("sha256").update(buf).digest("hex"),
    license: e.license,
  };
}
const next = JSON.stringify(manifest, null, 2) + "\n";
if (process.argv.includes("--check")) {
  const cur = existsSync(join(dist, "versions.json")) ? readFileSync(join(dist, "versions.json"), "utf8") : "";
  if (cur !== next) { console.error("dist/versions.json is stale: run `pnpm --filter @a11y/engine-bundles build`"); process.exit(1); }
  console.log("engine bundles up to date");
} else {
  writeFileSync(join(dist, "versions.json"), next);
  console.log(next);
}
