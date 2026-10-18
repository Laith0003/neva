import { test } from "node:test";
import assert from "node:assert/strict";
import { runWithFallback, capCheck } from "../src/fallback.js";

const pick = (id, free = true) => ({ provider: { id, free }, model: { id: id + "-m" }, reason: "auto" });
const state = () => ({ breakers: new Map(), now: () => 1000 });

test("falls through a failing provider to the next", async () => {
  const r = await runWithFallback([pick("a"), pick("b")],
    async p => { if (p.provider.id === "a") throw new Error("429 rate limited"); return "hi"; },
    state(), { caps: {}, spent: {}, auto: true });
  assert.equal(r.ok, true); assert.equal(r.pick.provider.id, "b"); assert.equal(r.result, "hi");
});

test("all down returns every failure, nothing invented", async () => {
  const r = await runWithFallback([pick("a"), pick("b")], async () => { throw new Error("503"); },
    state(), { caps: {}, spent: {}, auto: true });
  assert.equal(r.ok, false); assert.equal(r.failures.length, 2);
});

test("breaker opens after 3 failures and skips the provider", async () => {
  const s = state();
  for (let i = 0; i < 3; i++)
    await runWithFallback([pick("a")], async () => { throw new Error("500"); }, s, { caps: {}, spent: {}, auto: true });
  let called = false;
  await runWithFallback([pick("a")], async () => { called = true; return "x"; }, s, { caps: {}, spent: {}, auto: true });
  assert.equal(called, false);
});

test("paid model with cap 0 is refused with the fix", () => {
  const msg = capCheck(pick("openrouter", false), { caps: {}, spent: {} });
  assert.match(msg, /needs a spend cap: set NEVA_CAP_OPENROUTER/);
});
