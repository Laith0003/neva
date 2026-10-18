import { authorize } from "./auth.js";
import { callModel } from "./call.js";
import { classifyTask, pickModels } from "./router.js";
import { runWithFallback } from "./fallback.js";
import { MemoryStore, D1Store, fitToWindow } from "./threads.js";

// Module scope on purpose. A worker isolate serves many requests, so a breaker opened by a
// provider that just failed three times has to survive into the next request. A Map built per
// request would reset the count every time and the breaker would never open at all.
const breakers = new Map();

// Only the tests call this. Without it, one test's opened breaker silently skips a provider in
// the next test and the failure looks like a routing bug.
export function resetBreakers() {
  breakers.clear();
}

// Used only when no D1 binding is present: a worker that has not had its database created yet
// still answers, it just forgets when the isolate recycles. env.store overrides both, which is
// how the tests hand in their own store.
const scratchStore = new MemoryStore();

const BRAIN_KEY = "pack";

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function storeFor(env) {
  if (env.store) return env.store;
  return env.DB ? new D1Store(env.DB) : scratchStore;
}

function capsFrom(env, prefix) {
  const out = {};
  for (const [key, value] of Object.entries(env)) {
    if (!key.startsWith(prefix)) continue;
    out[key.slice(prefix.length).toLowerCase().replace(/_/g, "-")] = Number(value) || 0;
  }
  return out;
}

// Bigger windows get the bigger pack. The tier names and character limits match
// neva_omni/brainpack.py's TIERS.
const TIER_LIMITS = { small: 8000, medium: 32000, large: 120000 };

function tierFor(windowTokens) {
  if (windowTokens >= 120000) return "large";
  if (windowTokens >= 32000) return "medium";
  return "small";
}

async function brainText(env, windowTokens) {
  if (!env.BRAIN) return "";
  const pack = await env.BRAIN.get(BRAIN_KEY, "json");
  return pack?.tiers?.[tierFor(windowTokens)]?.text ?? "";
}

export async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  const auth = authorize(request, env);
  if (!auth.ok) return json({ error: auth.error }, auth.status);

  if (request.method === "POST" && path === "/chat") return chat(request, env);
  if (request.method === "GET" && path === "/threads") return listThreads(env);
  if (request.method === "GET" && path.startsWith("/threads/")) {
    let id;
    try {
      id = decodeURIComponent(path.slice("/threads/".length));
    } catch {
      return json({ error: "thread id: the path has a broken percent escape; encode the id with encodeURIComponent" }, 400);
    }
    return oneThread(env, id);
  }
  if (request.method === "PUT" && path === "/brainpack") return putBrainPack(request, env);

  return json({ error: `no route for ${request.method} ${path}: use POST /chat, GET /threads, GET /threads/:id, PUT /brainpack` }, 404);
}

async function chat(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'the request body is not JSON: send {"thread_id": "...", "message": "..."}' }, 400);
  }

  const message = typeof body?.message === "string" ? body.message.trim() : "";
  if (!message) return json({ error: "message is empty: type something to send" }, 400);

  const threadId = typeof body?.thread_id === "string" && body.thread_id.trim()
    ? body.thread_id.trim()
    : crypto.randomUUID();

  const store = storeFor(env);
  const task = classifyTask(message);
  let picks;
  try {
    if (body?.model !== undefined && (typeof body.model !== "string" || !body.model.trim())) {
      return json({ error: "model is invalid: supply a registered provider:model or omit model for automatic routing" }, 400);
    }
    picks = pickModels(task, env, body?.model);
  } catch (error) {
    return json({ error: error.message }, 400);
  }
  if (picks.length === 0) {
    return json({ error: "no model is reachable: add a provider key with wrangler secret put GROQ_API_KEY, or bind Workers AI as AI" }, 503);
  }

  // The user's turn is stored before any provider is called, so a total provider outage still
  // leaves what they typed on the thread instead of losing it.
  await store.appendMessage(threadId, { role: "user", content: message });
  const thread = await store.getThread(threadId);
  const history = thread?.messages ?? [{ role: "user", content: message }];

  const opts = { caps: capsFrom(env, "NEVA_CAP_"), spent: capsFrom(env, "NEVA_SPENT_"), auto: !body?.model };
  const fetchImpl = env.fetchImpl ?? fetch;

  const result = await runWithFallback(
    picks,
    async (pick) => {
      const system = await brainText(env, pick.model.window);
      const turns = await fitToWindow(
        history.map(m => ({ role: m.role, content: m.content })),
        pick.model.window,
        system.length,
        async (old, chars) => {
          const roles = new Map();
          const terms = new Map();
          for (const turn of old) {
            roles.set(turn.role, (roles.get(turn.role) ?? 0) + 1);
            for (const term of turn.content.toLowerCase().match(/[\p{L}\p{N}_-]{3,}/gu) ?? []) {
              terms.set(term, (terms.get(term) ?? 0) + 1);
            }
          }
          const counts = [...roles].map(([role, count]) => `${role}: ${count}`).join(", ");
          const topics = [...terms].sort((a, b) => b[1] - a[1]).map(([term]) => term).join(", ");
          const prefixChars = `Earlier in this conversation (summary of ${old.length} turns): `.length;
          return `${counts}. Topics: ${topics}`.slice(0, Math.max(0, chars - prefixChars));
        }
      );
      const messages = system ? [{ role: "system", content: system }, ...turns] : turns;
      return callModel(pick, messages, env, fetchImpl);
    },
    { breakers, now: () => Date.now() },
    opts
  );

  if (!result.ok) {
    return json({
      error: "every model refused or failed: see failures for each one, then retry",
      thread_id: threadId,
      failures: result.failures,
    }, 502);
  }

  const model = `${result.pick.provider.id}:${result.pick.model.id}`;
  await store.appendMessage(threadId, { role: "assistant", content: result.result, model });
  return json({
    thread_id: threadId,
    reply: result.result,
    model: result.pick.model.id,
    provider: result.pick.provider.id,
    reason: result.pick.reason,
    failures: result.failures,
  });
}

async function listThreads(env) {
  return json({ threads: await storeFor(env).listThreads() });
}

async function oneThread(env, id) {
  const thread = await storeFor(env).getThread(id);
  if (!thread) return json({ error: `no thread ${id}: open GET /threads to see the ones that exist` }, 404);
  return json(thread);
}

async function putBrainPack(request, env) {
  if (!env.BRAIN) {
    return json({ error: 'the BRAIN KV namespace is not bound: add [[kv_namespaces]] binding = "BRAIN" to wrangler.toml and redeploy' }, 503);
  }
  let pack;
  try {
    pack = await request.json();
  } catch {
    return json({ error: "the brain pack body is not JSON: compile it with neva brainpack, then neva omni push" }, 400);
  }
  // Validate everything before touching KV. A pack the chat cannot read would replace the one
  // it can, and every later chat would run without the brain prompt and say nothing about it.
  const problem = brainPackProblem(pack);
  if (problem) return json({ error: `${problem}; recompile with neva brainpack, then neva omni push` }, 400);
  await env.BRAIN.put(BRAIN_KEY, JSON.stringify(pack));
  const tiers = Object.fromEntries(Object.keys(TIER_LIMITS).map(name => [name, pack.tiers[name].chars]));
  return json({ stored: true, generated_at: pack.generated_at ?? null, tiers });
}

const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);

function brainPackProblem(pack) {
  if (!isObject(pack)) return "brain pack body: expected a JSON object";
  const names = Object.keys(TIER_LIMITS);
  if (!isObject(pack.tiers)) return `field tiers: expected an object with ${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  for (const name of Object.keys(pack.tiers)) {
    if (!(name in TIER_LIMITS)) return `field tiers.${name}: unsupported tier, use ${names.join(", ")}`;
  }
  for (const [name, limit] of Object.entries(TIER_LIMITS)) {
    const tier = pack.tiers[name];
    if (tier === undefined) return `field tiers.${name}: missing`;
    if (!isObject(tier)) return `field tiers.${name}: expected an object with text and chars`;
    if (typeof tier.text !== "string") return `field tiers.${name}.text: expected a string`;
    // Code points, not UTF-16 units: Python's len() counts code points, so astral characters
    // would otherwise make an honest pack look miscounted.
    const length = [...tier.text].length;
    if (length === 0) return `field tiers.${name}.text: empty, list files under include in the omni config`;
    if (length > limit) return `field tiers.${name}.text: ${length} chars is over the ${limit} limit`;
    if (tier.chars !== length) return `field tiers.${name}.chars: expected ${length}, the length of its text`;
  }
  return null;
}

export default {
  fetch(request, env) {
    return handle(request, env);
  },
};
