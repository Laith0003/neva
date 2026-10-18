import { test } from "node:test";
import assert from "node:assert/strict";
import { MemoryStore, D1Store, fitToWindow, REPLY_RESERVE_TOKENS, CHARS_PER_TOKEN } from "../src/threads.js";

// A fake D1 binding. It records the SQL it was handed and answers from fixed rows, so the
// store's SQL shape is asserted without a real database.
function fakeD1(rows = { all: [], first: null }) {
  const seen = [];
  return {
    seen,
    prepare(sql) {
      const stmt = {
        sql,
        args: [],
        bind(...args) { stmt.args = args; return stmt; },
        async all() { seen.push({ sql, args: stmt.args }); return { results: rows.all }; },
        async first() { seen.push({ sql, args: stmt.args }); return rows.first; },
        async run() { seen.push({ sql, args: stmt.args }); return { success: true }; },
      };
      return stmt;
    },
    async batch(stmts) { return stmts.map(() => ({ success: true })); },
  };
}

test("MemoryStore keeps both turns of a thread in order", async () => {
  const store = new MemoryStore();
  await store.appendMessage("t1", { role: "user", content: "hello" });
  await store.appendMessage("t1", { role: "assistant", content: "hi", model: "groq:m" });
  const thread = await store.getThread("t1");
  assert.equal(thread.messages.length, 2);
  assert.deepEqual(thread.messages.map(m => m.role), ["user", "assistant"]);
  assert.equal(thread.messages[1].model, "groq:m");
});

test("MemoryStore titles a thread from its first user turn", async () => {
  const store = new MemoryStore();
  await store.appendMessage("t1", { role: "user", content: "what is the capital of Jordan" });
  await store.appendMessage("t1", { role: "assistant", content: "Amman" });
  const [thread] = await store.listThreads();
  assert.equal(thread.title, "what is the capital of Jordan");
});

test("MemoryStore lists threads newest first", async () => {
  let clock = 1000;
  const store = new MemoryStore(() => (clock += 10));
  await store.appendMessage("old", { role: "user", content: "first" });
  await store.appendMessage("new", { role: "user", content: "second" });
  const list = await store.listThreads();
  assert.deepEqual(list.map(t => t.id), ["new", "old"]);
});

test("MemoryStore returns null for a thread that does not exist", async () => {
  const store = new MemoryStore();
  assert.equal(await store.getThread("nope"), null);
});

test("D1Store reads a thread's messages oldest first, bound to the thread id", async () => {
  const db = fakeD1({ all: [{ role: "user", content: "hello", model: null, created_at: 5 }],
                       first: { id: "t1", title: "hello", updated_at: 5 } });
  const thread = await new D1Store(db).getThread("t1");
  assert.equal(thread.messages.length, 1);
  const query = db.seen.find(q => /FROM messages/i.test(q.sql));
  assert.ok(query, "D1Store never queried the messages table");
  assert.match(query.sql, /ORDER BY created_at ASC|ORDER BY id ASC/i);
  assert.deepEqual(query.args, ["t1"]);
});

test("D1Store writes the thread row and the message row for an append", async () => {
  const db = fakeD1();
  await new D1Store(db).appendMessage("t1", { role: "user", content: "hello" });
  const sql = db.seen.map(q => q.sql).join("\n");
  assert.match(sql, /INSERT INTO threads/i);
  assert.match(sql, /INSERT INTO messages/i);
});

test("fitToWindow drops the oldest turns so the newest fit the model window", () => {
  const msg = (n) => ({ role: "user", content: "x".repeat(400 * n) });
  // 1200 - 1024 reserved for the reply = 176 tokens = 704 chars, so only one 400-char turn fits.
  const kept = fitToWindow([msg(1), msg(1), msg(1)], 1200);
  assert.ok(kept.length < 3, "nothing was dropped for a window that cannot hold the history");
  assert.equal(kept.at(-1).content.length, 400, "the newest turn was dropped instead of the oldest");
});

test("fitToWindow always keeps the newest turn, even when it alone overflows", () => {
  const huge = { role: "user", content: "x".repeat(500000) };
  const kept = fitToWindow([{ role: "user", content: "old" }, huge], 2000);
  assert.deepEqual(kept, [huge]);
});

test("fitToWindow keeps the whole history when it fits", () => {
  const history = [{ role: "user", content: "a" }, { role: "assistant", content: "b" }];
  assert.deepEqual(fitToWindow(history, 128000), history);
});

test("fitToWindow prepends a summary of dropped turns instead of discarding them", async () => {
  const msg = (n) => ({ role: "user", content: `turn ${n}`.repeat(100) });
  const messages = [msg(1), msg(2), msg(3), { role: "user", content: "newest turn" }];
  const summarize = async (dropped) => dropped.map(m => m.content.slice(0, 10)).join(" | ");
  const windowTokens = 1200;

  const kept = await fitToWindow(messages, windowTokens, 0, summarize);

  const budget = (windowTokens - REPLY_RESERVE_TOKENS) * CHARS_PER_TOKEN;
  const totalContent = kept.reduce((sum, m) => sum + m.content.length + m.role.length + 4, 0);
  assert.ok(totalContent <= budget, "the summary pushed the thread over its budget");
  assert.match(kept[0].content, /summary of \d+ turns/);
  assert.equal(kept.at(-1).content, "newest turn", "the newest turn must survive verbatim");
});

test("summary reserves overhead in a full window and receives every omitted turn", async () => {
  const messages = Array.from({length: 250}, (_, i) => ({role: "user", content: `old-${i} ` + "x".repeat(300)}));
  messages.push({role: "user", content: "newest"});
  let dropped;
  const result = await fitToWindow(messages, 1200, 0, async old => { dropped = old; return old.map(m => m.content).join(" "); });
  assert.ok(result[0].content.length > 60);
  assert.ok(dropped.some(m => m.content.startsWith("old-0 ")));
  assert.ok(result.reduce((n,m) => n + m.content.length + m.role.length + 4, 0) <= 704);
});
test("summary refuses a newest turn with no room instead of sending an over-budget request", async () => {
  await assert.rejects(async () => fitToWindow([{role:"user",content:"old"}, {role:"user",content:"x".repeat(704)}], 1200, 0, async () => "summary"), /message.*window/);
});
