import { build } from "esbuild";
await build({
  entryPoints: ["src/browser/content.ts"],
  outfile: "dist/content.js",
  bundle: true,
  format: "iife",
  target: "chrome116",
});
