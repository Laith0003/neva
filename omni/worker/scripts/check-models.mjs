#!/usr/bin/env node
// Are the model ids in src/providers.js still real?
//
// A pinned model id that a provider has retired fails at request time as a 404 from the
// provider, which the fallback chain quietly swallows into "the next one answered". So this
// asks each provider's own /models list, before a deploy, and says which ids are gone.
//
//   GROQ_API_KEY=... GEMINI_API_KEY=... node scripts/check-models.mjs
//
// Exits 0 when every id a key was supplied for is present, 1 when any id is missing. A
// provider with no key is reported as UNCHECKED and does not fail the run: not knowing is a
// different state from knowing it is broken, and it is never hidden inside a green result.

import { PROVIDERS } from "../src/providers.js";

const TIMEOUT_MS = 15000;

async function listModels(provider, key) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(`${provider.baseUrl}/models`, {
      headers: { Authorization: `Bearer ${key}` },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${(await response.text()).slice(0, 200)}`);
    }
    const body = await response.json();
    const models = body?.data ?? body?.models ?? [];
    return models.map(m => String(m.id ?? m.name ?? "").replace(/^models\//, ""));
  } finally {
    clearTimeout(timer);
  }
}

let failed = 0;
let unchecked = 0;

for (const provider of PROVIDERS) {
  const ids = provider.models.map(m => m.id);

  if (provider.kind === "workers-ai") {
    // Workers AI models are listed per account through the Cloudflare API, not an OpenAI
    // /models route, and that needs an account id and an API token this script is not given.
    console.log(`UNCHECKED  ${provider.id}: ${ids.join(", ")} (verify at https://developers.cloudflare.com/workers-ai/models/)`);
    unchecked += 1;
    continue;
  }

  const key = process.env[provider.keyEnv];
  if (!key) {
    console.log(`UNCHECKED  ${provider.id}: no ${provider.keyEnv} in the environment, so nothing was asked`);
    unchecked += 1;
    continue;
  }

  let live;
  try {
    live = await listModels(provider, key);
  } catch (e) {
    console.log(`FAIL       ${provider.id}: could not read ${provider.baseUrl}/models: ${e.message}`);
    failed += 1;
    continue;
  }

  for (const id of ids) {
    if (live.includes(id)) {
      console.log(`OK         ${provider.id}: ${id}`);
    } else {
      console.log(`FAIL       ${provider.id}: ${id} is not in that account's model list. Pick one of: ${live.slice(0, 8).join(", ")}`);
      failed += 1;
    }
  }
}

console.log(`\n${failed} missing, ${unchecked} unchecked.`);
if (unchecked > 0) console.log("UNCHECKED is not a pass: those ids were never asked about.");
process.exit(failed === 0 ? 0 : 1);
