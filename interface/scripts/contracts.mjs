import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { compile } from "json-schema-to-typescript";
const dir = new URL("../../schemas/", import.meta.url),
  out = new URL("../src/generated/", import.meta.url);
await mkdir(out, { recursive: true });
const hash = createHash("sha256"),
  schemas = {};
for (const name of (await readdir(dir))
  .filter((n) => n.endsWith(".schema.json"))
  .sort()) {
  const raw = await readFile(new URL(name, dir), "utf8");
  hash.update(name).update(raw);
  const schema = JSON.parse(raw);
  schemas[name.replace(".schema.json", "")] = schema;
  await writeFile(
    new URL(name.replace(".schema.json", ".ts"), out),
    await compile(schema, schema.title),
  );
}
await writeFile(
  new URL("contract.json", out),
  JSON.stringify(
    { protocol: 1, fingerprint: hash.digest("hex"), schemas },
    null,
    2,
  ),
);
// Bundle immutable schema bytes for the packaged host; never regenerate engine schemas.
await writeFile(
  new URL("../companion/questionnaire_host/contract.json", import.meta.url),
  await readFile(new URL("contract.json", out)),
);
