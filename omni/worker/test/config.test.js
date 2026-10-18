import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const config = () => readFileSync(join(root, "wrangler.toml"), "utf8");

test("wrangler main points at a file that exists", () => {
  const main = config().match(/^main\s*=\s*"([^"]+)"/m);
  assert.ok(main, "wrangler.toml has no main entry");
  assert.ok(existsSync(join(root, main[1])), `main points at a missing file: ${main[1]}`);
});

test("the Workers AI binding is declared as AI", () => {
  // router.js gates the free workers-ai provider on env.AI, so the binding name is load-bearing.
  assert.match(config(), /\[ai\]\s*\nbinding\s*=\s*"AI"/);
});

test("no secret is checked in as a plain var", () => {
  assert.doesNotMatch(config(), /^\s*(GROQ_API_KEY|GEMINI_API_KEY|DEVICE_TOKEN)\s*=/m);
});

test("the brain pack KV namespace is bound as BRAIN", () => {
  // index.js reads the pack from env.BRAIN; a different binding name means no system prompt.
  assert.match(config(), /\[\[kv_namespaces\]\][\s\S]*?binding\s*=\s*"BRAIN"/);
});

test("the thread database is bound as DB and its migrations directory exists", () => {
  const toml = config();
  assert.match(toml, /\[\[d1_databases\]\][\s\S]*?binding\s*=\s*"DB"/);
  const dir = toml.match(/migrations_dir\s*=\s*"([^"]+)"/);
  assert.ok(dir, "no migrations_dir, so wrangler d1 migrations apply has nothing to run");
  assert.ok(existsSync(join(root, dir[1], "0001_threads.sql")),
    `the threads migration is missing from ${dir[1]}`);
});

test("the compatibility date is pinned to the one the worker was tested against", () => {
  assert.match(config(), /^compatibility_date\s*=\s*"2026-09-01"/m);
});
