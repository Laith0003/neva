import { test } from "node:test";
import assert from "node:assert/strict";
import { classifyTask, pickModels } from "../src/router.js";

test("classifies Arabic, lookups and judgment", () => {
  assert.equal(classifyTask("اكتب لي رسالة للعميل"), "arabic");
  assert.equal(classifyTask("what is the capital of Jordan"), "lookup");
  assert.equal(classifyTask("should I pick Alpha or Beta as the first engine, trade-offs"), "judgment");
});

test("free providers come first and missing keys are skipped", () => {
  const env = { AI: {}, GROQ_API_KEY: "x" };            // no GEMINI key
  const picks = pickModels("lookup", env);
  assert.ok(picks.length > 0);
  assert.ok(picks.every(p => p.provider.id !== "gemini"));
  assert.ok(picks[0].provider.free);
});

test("a pinned model goes first with the reason pinned", () => {
  const env = { AI: {}, GROQ_API_KEY: "x" };
  const picks = pickModels("lookup", env, "groq:llama-3.3-70b-versatile");
  assert.equal(picks[0].model.id, "llama-3.3-70b-versatile");
  assert.equal(picks[0].reason, "pinned");
});
