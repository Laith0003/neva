import { test } from "node:test";
import assert from "node:assert/strict";
import { handle, resetBreakers } from "../src/index.js";
import { MemoryStore } from "../src/threads.js";

const DEVICE_TOKEN = "device-token-for-tests";

// env.fetchImpl is the one seam for the outside world: no global.fetch is ever monkey-patched,
// so two tests running in the same process cannot leak a stub into each other.
function makeEnv({ fetchImpl } = {}) {
  return {
    GROQ_API_KEY: "test-key",
    DEVICE_TOKEN,
    store: new MemoryStore(),
    fetchImpl: fetchImpl ?? (async () => { throw new Error("no provider call expected in this test"); }),
  };
}

function chatRequest(body, { authorized = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (authorized) headers.Authorization = `Bearer ${DEVICE_TOKEN}`;
  return new Request("https://omni.example.com/chat", { method: "POST", headers, body: JSON.stringify(body) });
}

const okReply = (content) => async () => ({
  ok: true,
  status: 200,
  json: async () => ({ choices: [{ message: { content } }] }),
});

test("an unauthenticated chat is refused with the sign-in fix and stores nothing", async () => {
  resetBreakers();
  const env = makeEnv();
  const res = await handle(chatRequest({ thread_id: "t1", message: "hello" }, { authorized: false }), env);
  assert.equal(res.status, 401);
  const body = await res.json();
  assert.equal(body.error, "send the device token matching DEVICE_TOKEN");
  assert.deepEqual(await env.store.listThreads(), [], "an unauthenticated request wrote a thread");
});

test("an empty message is refused with the fix, before any provider is called", async () => {
  resetBreakers();
  let called = false;
  const env = makeEnv({ fetchImpl: async () => { called = true; return okReply("x")(); } });
  const res = await handle(chatRequest({ thread_id: "t1", message: "   " }), env);
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.error, "message is empty: type something to send");
  assert.equal(called, false, "a provider was called for an empty message");
  assert.deepEqual(await env.store.listThreads(), [], "an empty message wrote a thread");
});

test("a chat stores both the user turn and the reply", async () => {
  resetBreakers();
  const env = makeEnv({ fetchImpl: okReply("Amman") });
  const res = await handle(chatRequest({ thread_id: "t1", message: "capital of Jordan" }), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.reply, "Amman");
  assert.equal(body.thread_id, "t1");
  const thread = await env.store.getThread("t1");
  assert.deepEqual(thread.messages.map(m => [m.role, m.content]),
    [["user", "capital of Jordan"], ["assistant", "Amman"]]);
});

test("every provider down returns 502 and keeps the user turn", async () => {
  resetBreakers();
  const env = makeEnv({ fetchImpl: async () => ({ ok: false, status: 503, text: async () => "upstream down" }) });
  const res = await handle(chatRequest({ thread_id: "t1", message: "hello" }), env);
  assert.equal(res.status, 502);
  const body = await res.json();
  assert.ok(body.failures.length > 0, "a 502 named no failing provider");
  const thread = await env.store.getThread("t1");
  assert.deepEqual(thread.messages.map(m => m.role), ["user"], "the user turn was lost when the providers failed");
});
