import { test } from "node:test";
import assert from "node:assert/strict";
import worker, { handle, resetBreakers } from "../src/index.js";
import { MemoryStore } from "../src/threads.js";
import { SIGN_IN } from "../src/auth.js";

const DEVICE_TOKEN = "device-token-for-tests";
const AUTH = { Authorization: `Bearer ${DEVICE_TOKEN}`, "Content-Type": "application/json" };

function makeEnv(extra = {}) {
  return { GROQ_API_KEY: "test-key", DEVICE_TOKEN, store: new MemoryStore(), ...extra };
}

const req = (path, init = {}) =>
  new Request(`https://omni.example.com${path}`, { headers: AUTH, ...init });

const post = (path, body, init = {}) =>
  req(path, { method: "POST", body: JSON.stringify(body), ...init });

const okReply = (content) => async () => ({
  ok: true,
  status: 200,
  json: async () => ({ choices: [{ message: { content } }] }),
});

test("the default export is the Cloudflare fetch handler", async () => {
  resetBreakers();
  assert.equal(typeof worker?.fetch, "function");
  const res = await worker.fetch(req("/nope"), makeEnv());
  assert.equal(res.status, 404);
  assert.match((await res.json()).error, /no route for GET \/nope/);
});

test("forged Access headers refuse reads, writes and model calls", async () => {
  let calls = 0;
  const blocked = async () => { calls++; throw new Error("unauthorized side effect"); };
  const env = makeEnv({ store: new Proxy({}, { get: () => blocked }),
    BRAIN: { get: blocked, put: blocked }, fetchImpl: blocked });
  for (const [path, method, body] of [["/threads", "GET"], ["/brainpack", "PUT", { tiers: {} }],
    ["/chat", "POST", { message: "hello" }]]) {
    const request = new Request(`https://omni.example.com${path}`, { method,
      headers: { "Cf-Access-Authenticated-User-Email": "owner@example.com", "Content-Type": "application/json" },
      ...(body ? { body: JSON.stringify(body) } : {}) });
    assert.equal((await handle(request, env)).status, 401);
  }
  assert.equal(calls, 0);
});

test("a wrong device token is refused with the same fix as no token at all", async () => {
  resetBreakers();
  const request = new Request("https://omni.example.com/threads", {
    headers: { Authorization: "Bearer not-the-token" },
  });
  const res = await handle(request, makeEnv());
  assert.equal(res.status, 401);
  assert.equal((await res.json()).error, SIGN_IN);
});

test("a body that is not JSON names the shape it wanted", async () => {
  resetBreakers();
  const request = req("/chat", { method: "POST", body: "not json at all" });
  const res = await handle(request, makeEnv());
  assert.equal(res.status, 400);
  assert.match((await res.json()).error, /not JSON/);
});

test("a chat with no thread_id opens a new thread and returns its id", async () => {
  resetBreakers();
  const env = makeEnv({ fetchImpl: okReply("Amman") });
  const res = await handle(post("/chat", { message: "capital of Jordan" }), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.ok(body.thread_id, "no thread id came back, so the client cannot continue the thread");
  assert.equal((await env.store.getThread(body.thread_id)).messages.length, 2);
});

test("the request carries the key value, not the name of the env var", async () => {
  resetBreakers();
  let seenAuth = null;
  const env = makeEnv({
    fetchImpl: async (_url, init) => { seenAuth = init.headers.Authorization; return okReply("ok")(); },
  });
  const res = await handle(post("/chat", { thread_id: "t1", message: "hello" }), env);
  assert.equal(res.status, 200);
  assert.equal(seenAuth, "Bearer test-key");
});

test("a pinned model is the one that is called", async () => {
  resetBreakers();
  const env = makeEnv({ GEMINI_API_KEY: "g", fetchImpl: okReply("pinned") });
  let seenModel = null;
  env.fetchImpl = async (_url, init) => { seenModel = JSON.parse(init.body).model; return okReply("pinned")(); };
  const res = await handle(post("/chat", {
    thread_id: "t1", message: "hello", model: "groq:llama-3.3-70b-versatile",
  }), env);
  const body = await res.json();
  assert.equal(body.model, "llama-3.3-70b-versatile");
  assert.equal(body.provider, "groq");
  assert.equal(body.reason, "pinned");
  assert.equal(seenModel, "llama-3.3-70b-versatile");
});

test("a failing provider falls through to the next one and the reply still lands", async () => {
  resetBreakers();
  let calls = 0;
  const env = makeEnv({
    GEMINI_API_KEY: "g",
    fetchImpl: async () => {
      calls += 1;
      if (calls === 1) return { ok: false, status: 500, text: async () => "upstream exploded" };
      return okReply("second provider answered")();
    },
  });
  const res = await handle(post("/chat", { thread_id: "t1", message: "hello" }), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.reply, "second provider answered");
  assert.equal(body.failures.length, 1, "the provider that failed was not reported");
});

test("the thread history is replayed to the model, not just the newest turn", async () => {
  resetBreakers();
  let seenMessages = null;
  const env = makeEnv({
    fetchImpl: async (_url, init) => { seenMessages = JSON.parse(init.body).messages; return okReply("ok")(); },
  });
  await handle(post("/chat", { thread_id: "t1", message: "first" }), env);
  await handle(post("/chat", { thread_id: "t1", message: "second" }), env);
  assert.deepEqual(seenMessages.map(m => m.content), ["first", "ok", "second"]);
});

test("the brain pack tier for the model's window is sent as the system turn", async () => {
  resetBreakers();
  const pack = { tiers: { small: { text: "SMALL", chars: 5 }, medium: { text: "MEDIUM", chars: 6 }, large: { text: "LARGE", chars: 5 } } };
  let seenMessages = null;
  const env = makeEnv({
    BRAIN: { get: async () => pack, put: async () => {} },
    fetchImpl: async (_url, init) => { seenMessages = JSON.parse(init.body).messages; return okReply("ok")(); },
  });
  await handle(post("/chat", { thread_id: "t1", message: "hello" }), env);
  // groq's llama-3.3-70b-versatile has a 128k window, so it gets the large tier.
  assert.equal(seenMessages[0].role, "system");
  assert.equal(seenMessages[0].content, "LARGE");
});

test("GET /threads lists what was stored and GET /threads/:id returns its turns", async () => {
  resetBreakers();
  const env = makeEnv({ fetchImpl: okReply("Amman") });
  await handle(post("/chat", { thread_id: "t1", message: "capital of Jordan" }), env);
  const list = await (await handle(req("/threads"), env)).json();
  assert.deepEqual(list.threads.map(t => t.id), ["t1"]);
  const thread = await (await handle(req("/threads/t1"), env)).json();
  assert.deepEqual(thread.messages.map(m => m.role), ["user", "assistant"]);
});

test("a thread that does not exist is a 404 that says where to look", async () => {
  resetBreakers();
  const res = await handle(req("/threads/missing"), makeEnv());
  assert.equal(res.status, 404);
  assert.match((await res.json()).error, /no thread missing: open GET \/threads/);
});

test("a thread id with a broken percent escape is a 400 naming the field, not a crash", async () => {
  resetBreakers();
  const env = makeEnv();
  const res = await handle(req("/threads/%E0%A4%A"), env);
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.match(body.error, /^thread id: /);
  assert.match(body.error, /encodeURIComponent/);
});

const FULL_PACK = { generated_at: "2026-10-05T00:00:00+00:00", tiers: {
  small: { text: "a", chars: 1 }, medium: { text: "ab", chars: 2 }, large: { text: "abc", chars: 3 } } };

test("PUT /brainpack stores the pack and reports the tier sizes", async () => {
  resetBreakers();
  let stored = null;
  const env = makeEnv({ BRAIN: { get: async () => null, put: async (_k, v) => { stored = v; } } });
  const res = await handle(req("/brainpack", { method: "PUT", body: JSON.stringify(FULL_PACK) }), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.stored, true);
  assert.deepEqual(body.tiers, { small: 1, medium: 2, large: 3 });
  assert.equal(JSON.parse(stored).tiers.small.text, "a");
});

test("PUT /brainpack counts declared chars in code points, as the compiler does", async () => {
  resetBreakers();
  const env = makeEnv({ BRAIN: { get: async () => null, put: async () => {} } });
  const astral = "\u{1D400}\u0628";
  const pack = { tiers: { ...FULL_PACK.tiers, small: { text: astral, chars: 2 } } };
  const res = await handle(req("/brainpack", { method: "PUT", body: JSON.stringify(pack) }), env);
  assert.equal(res.status, 200);
});

test("PUT /brainpack refuses a wrong-shaped pack, names the field and keeps the stored pack", async () => {
  const previous = JSON.stringify(FULL_PACK);
  const big = "x".repeat(8001);
  const cases = [
    [[], /brain pack body: expected a JSON object/],
    [{ tiers: [] }, /field tiers: expected an object with small, medium and large/],
    [{ tiers: {} }, /field tiers\.small: missing/],
    [{ tiers: { small: FULL_PACK.tiers.small, large: FULL_PACK.tiers.large } }, /field tiers\.medium: missing/],
    [{ tiers: { ...FULL_PACK.tiers, huge: { text: "a", chars: 1 } } }, /field tiers\.huge: unsupported tier/],
    [{ tiers: { ...FULL_PACK.tiers, small: "a" } }, /field tiers\.small: expected an object/],
    [{ tiers: { ...FULL_PACK.tiers, small: [] } }, /field tiers\.small: expected an object/],
    [{ tiers: { ...FULL_PACK.tiers, small: { text: 5, chars: 1 } } }, /field tiers\.small\.text: expected a string/],
    [{ tiers: { ...FULL_PACK.tiers, small: { text: "", chars: 0 } } }, /field tiers\.small\.text: empty/],
    [{ tiers: { ...FULL_PACK.tiers, small: { text: "a", chars: "1" } } }, /field tiers\.small\.chars: expected 1/],
    [{ tiers: { ...FULL_PACK.tiers, small: { text: "a", chars: 9 } } }, /field tiers\.small\.chars: expected 1/],
    [{ tiers: { ...FULL_PACK.tiers, small: { text: big, chars: big.length } } }, /field tiers\.small\.text: 8001 chars is over the 8000 limit/],
  ];
  const problems = [];
  for (const [pack, error] of cases) {
    resetBreakers();
    let value = previous;
    let puts = 0;
    const env = makeEnv({ BRAIN: { get: async () => JSON.parse(value), put: async (_k, v) => { puts++; value = v; } } });
    const res = await handle(req("/brainpack", { method: "PUT", body: JSON.stringify(pack) }), env);
    const body = await res.json();
    const shape = JSON.stringify(pack).slice(0, 60);
    if (res.status !== 400) problems.push(`${shape}: status ${res.status}, stored ${body.stored}`);
    else if (!error.test(body.error) || !/neva brainpack/.test(body.error)) problems.push(`${shape}: error "${body.error}"`);
    if (body.stored !== undefined) problems.push(`${shape}: reported stored ${body.stored}`);
    if (puts !== 0 || value !== previous) problems.push(`${shape}: overwrote the stored pack`);
  }
  assert.deepEqual(problems, []);
});

test("after a refused push the next chat still sends the stored brain prompt", async () => {
  resetBreakers();
  let value = JSON.stringify(FULL_PACK);
  let seenMessages = null;
  const env = makeEnv({
    BRAIN: { get: async () => JSON.parse(value), put: async (_k, v) => { value = v; } },
    fetchImpl: async (_url, init) => { seenMessages = JSON.parse(init.body).messages; return okReply("ok")(); },
  });
  const refused = await handle(req("/brainpack", { method: "PUT", body: JSON.stringify({ tiers: [] }) }), env);
  assert.equal(refused.status, 400);
  await handle(post("/chat", { thread_id: "t1", message: "hello" }), env);
  assert.equal(seenMessages[0].role, "system");
  assert.equal(seenMessages[0].content, "abc");
});

test("PUT /brainpack refuses a pack with no tiers and names the command that makes one", async () => {
  resetBreakers();
  const env = makeEnv({ BRAIN: { get: async () => null, put: async () => {} } });
  const res = await handle(req("/brainpack", { method: "PUT", body: JSON.stringify({ hello: "world" }) }), env);
  assert.equal(res.status, 400);
  assert.match((await res.json()).error, /field tiers: expected an object.*recompile with neva brainpack/);
});

test("PUT /brainpack without the KV binding says which binding is missing", async () => {
  resetBreakers();
  const res = await handle(req("/brainpack", { method: "PUT", body: "{}" }), makeEnv());
  assert.equal(res.status, 503);
  assert.match((await res.json()).error, /BRAIN KV namespace is not bound/);
});

test("with no provider key and no AI binding the chat says how to add one", async () => {
  resetBreakers();
  const res = await handle(post("/chat", { message: "hello" }), { DEVICE_TOKEN, store: new MemoryStore() });
  assert.equal(res.status, 503);
  assert.match((await res.json()).error, /wrangler secret put GROQ_API_KEY/);
});

test("the breaker opens across requests, so a dead provider is skipped on the fourth call", async () => {
  resetBreakers();
  let calls = 0;
  const env = makeEnv({
    fetchImpl: async () => { calls += 1; return { ok: false, status: 503, text: async () => "down" }; },
  });
  for (let i = 0; i < 3; i++) await handle(post("/chat", { thread_id: `t${i}`, message: "hello" }), env);
  assert.equal(calls, 3);
  const res = await handle(post("/chat", { thread_id: "t4", message: "hello" }), env);
  assert.equal(calls, 3, "the breaker reset between requests, so a dead provider was called again");
  assert.equal(res.status, 502);
  assert.match((await res.json()).failures[0].error, /circuit open/);
});

test("history beyond the old turn limit survives into the model request", async () => {
  resetBreakers();
  const env = makeEnv({fetchImpl: okReply("ok")});
  for (let i=0;i<250;i++) await env.store.appendMessage("long", {role:"user",content:`old-${i}`});
  let messages;
  env.fetchImpl = async (_,init) => { messages=JSON.parse(init.body).messages; return okReply("ok")(); };
  const res=await handle(post("/chat",{thread_id:"long",message:"newest"}),env);
  assert.equal(res.status,200);
  assert.ok(messages.some(m => m.content.includes("old-0")));
});

test("unknown and unavailable model pins refuse before reads writes or calls", async () => {
  for (const model of ["unknown:model", "gemini:gemini-2.5-flash"]) {
    resetBreakers(); let calls=0;
    const blocked=async () => { calls++; throw new Error("side effect"); };
    const env=makeEnv({store:new Proxy({}, {get:()=>blocked}), BRAIN:{get:blocked}, fetchImpl:blocked});
    const res=await handle(post("/chat",{message:"hello",model}),env);
    assert.equal(res.status,400);
    assert.match((await res.json()).error,/model.*(unknown|unavailable)/);
    assert.equal(calls,0);
  }
});
test("a valid pin never falls back without separate automatic routing consent", async () => {
  resetBreakers(); let calls=0;
  const env=makeEnv({GEMINI_API_KEY:"g",fetchImpl:async () => { calls++; return {ok:false,status:500,text:async()=>"down"}; }});
  const res=await handle(post("/chat",{thread_id:"pin",message:"hello",model:"groq:llama-3.3-70b-versatile"}),env);
  assert.equal(res.status,502);
  assert.equal(calls,1);
  assert.equal((await res.json()).failures.length,1);
  assert.equal((await env.store.getThread("pin")).messages.length,1);
});


test("overflow summary aggregates all omitted turns locally", async () => {
  resetBreakers();
  let messages;
  const env = makeEnv({ fetchImpl: async (_, init) => {
    messages = JSON.parse(init.body).messages;
    return okReply("ok")();
  }});
  for (let i = 0; i < 160; i++) {
    await env.store.appendMessage("overflow", {role: "user", content: "sharedtopic ".repeat(400)});
  }
  const response = await handle(post("/chat", {thread_id: "overflow", message: "newest"}), env);
  assert.equal(response.status, 200);
  const summary = messages.find(m => m.content.startsWith("Earlier in this conversation"));
  assert.ok(summary);
  assert.match(summary.content, /user: [0-9]+\. Topics: sharedtopic/);
  assert.equal(messages.at(-1).content, "newest");
});
