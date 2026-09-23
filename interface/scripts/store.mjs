import { mkdir, readFile, writeFile, cp, readdir } from "node:fs/promises";
import { execFileSync } from "node:child_process";
await mkdir("artifacts", { recursive: true });
const manifest = JSON.parse(await readFile("dist/manifest.json", "utf8"));
if (manifest.host_permissions?.length || manifest.externally_connectable)
  throw Error("Unexpected broad access in release manifest");
await cp("LICENSE", "dist/LICENSE");
const lock = JSON.parse(await readFile("package-lock.json", "utf8"));
await writeFile(
  "dist/THIRD-PARTY-NOTICES.txt",
  Object.entries(lock.packages)
    .filter(([p]) => p)
    .map(
      ([p, v]) => `${p} ${v.version}: ${v.license || "review package license"}`,
    )
    .join("\n"),
);
// Preserve license/notice files from all production dependencies, including transitive ones.
await mkdir("dist/dependency-licenses", { recursive: true });
for (const [directory, metadata] of Object.entries(lock.packages)) {
  if (!directory || metadata.dev) continue;
  for (const name of await readdir(directory)) {
    if (/^(license|copying|notice)/i.test(name)) {
      await cp(`${directory}/${name}`, `dist/dependency-licenses/${directory.replaceAll("/", "_")}-${name}`, { recursive: true });
    }
  }
}
execFileSync(
  process.platform === "win32" ? "py" : "python",
  [
    "-c",
    'import shutil; shutil.make_archive("artifacts/questionnaire-extension-0.1.0", "zip", "dist")',
  ],
  { stdio: "inherit" },
);
console.log(
  "Prepared extension zip. Store submission and approval are not performed.",
);
