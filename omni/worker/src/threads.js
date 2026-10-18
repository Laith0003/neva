// Thread storage. Two stores behind one interface: MemoryStore for tests and for a worker
// with no D1 binding yet, D1Store for the real thing. Both are append-only; a turn is never
// edited once stored, so a failed reply still leaves the user's own words on the record.

const TITLE_CHARS = 80;

// Rough token accounting. A real tokenizer is not worth shipping into a worker for this:
// the only job is to stop a long thread overflowing a model's window, and under-filling is
// cheap while overflowing is a hard error from the provider.
export const CHARS_PER_TOKEN = 4;
export const REPLY_RESERVE_TOKENS = 1024;

function title(content) {
  const line = String(content).trim().split("\n")[0];
  return line.length > TITLE_CHARS ? `${line.slice(0, TITLE_CHARS - 1)}…` : line;
}

export class MemoryStore {
  constructor(now = () => Date.now()) {
    this.now = now;
    this.threads = new Map();
  }

  async appendMessage(threadId, { role, content, model = null }) {
    const at = this.now();
    const thread = this.threads.get(threadId) ?? { id: threadId, title: "", created_at: at, updated_at: at, messages: [] };
    if (!thread.title && role === "user") thread.title = title(content);
    const message = { role, content, model, created_at: at };
    const next = { ...thread, updated_at: at, messages: [...thread.messages, message] };
    this.threads.set(threadId, next);
    return message;
  }

  async getThread(threadId) {
    const thread = this.threads.get(threadId);
    if (!thread) return null;
    return { id: thread.id, title: thread.title, updated_at: thread.updated_at, messages: [...thread.messages] };
  }

  async listThreads(limit = 50) {
    return [...this.threads.values()]
      .map(t => ({ id: t.id, title: t.title, updated_at: t.updated_at }))
      .sort((a, b) => b.updated_at - a.updated_at)
      .slice(0, limit);
  }
}

export class D1Store {
  constructor(db, now = () => Date.now()) {
    this.db = db;
    this.now = now;
  }

  async appendMessage(threadId, { role, content, model = null }) {
    const at = this.now();
    // The thread row is upserted first so the message's foreign key always has a parent, and
    // so a thread that already exists keeps its original title and only moves its updated_at.
    await this.db.prepare(
      `INSERT INTO threads (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)
       ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at,
         title = CASE WHEN threads.title = '' THEN excluded.title ELSE threads.title END`
    ).bind(threadId, role === "user" ? title(content) : "", at, at).run();
    await this.db.prepare(
      "INSERT INTO messages (thread_id, role, content, model, created_at) VALUES (?, ?, ?, ?, ?)"
    ).bind(threadId, role, content, model, at).run();
    return { role, content, model, created_at: at };
  }

  async getThread(threadId) {
    const head = await this.db.prepare(
      "SELECT id, title, updated_at FROM threads WHERE id = ?"
    ).bind(threadId).first();
    if (!head) return null;
    const rows = await this.db.prepare(
      "SELECT role, content, model, created_at FROM messages WHERE thread_id = ? ORDER BY created_at ASC, id ASC"
    ).bind(threadId).all();
    return { id: head.id, title: head.title, updated_at: head.updated_at, messages: rows.results ?? [] };
  }

  async listThreads(limit = 50) {
    const rows = await this.db.prepare(
      "SELECT id, title, updated_at FROM threads ORDER BY updated_at DESC LIMIT ?"
    ).bind(limit).all();
    return rows.results ?? [];
  }
}

function cost(message) {
  return String(message.content).length + String(message.role).length + 4;
}

function summaryMessage(text, droppedCount, remaining) {
  const prefix = `Earlier in this conversation (summary of ${droppedCount} turns): `;
  const role = "user";
  const maxLen = Math.max(0, remaining - role.length - 4);
  return { role, content: (prefix + text).slice(0, maxLen) };
}

// Reserve summary space before selecting retained turns. Every omitted turn reaches the
// injected local summarizer. Oversized newest messages fail before any provider call.
export function fitToWindow(messages, windowTokens, systemChars = 0, summarize) {
  if (!messages.length) return [];
  const budget = (windowTokens - REPLY_RESERVE_TOKENS) * CHARS_PER_TOKEN - systemChars;
  const total = messages.reduce((n, m) => n + cost(m), 0);
  if (total <= budget) return messages;
  const newestCost = cost(messages.at(-1));
  if (summarize && newestCost > budget) throw new Error("message exceeds the model window: shorten message or brain pack");
  const reserve = summarize && messages.length > 1 ? Math.min(2048, Math.floor(budget / 4), budget - newestCost) : 0;
  // The prefix and role overhead require room for useful summary content.
  if (summarize && messages.length > 1 && reserve < 80) throw new Error("message leaves no summary room in the model window: shorten message or brain pack");
  const kept = [];
  let used = 0;
  let cutIndex = messages.length;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (kept.length && used + cost(messages[i]) > budget - reserve) break;
    kept.unshift(messages[i]);
    used += cost(messages[i]);
    cutIndex = i;
  }
  const dropped = messages.slice(0, cutIndex);
  if (!dropped.length || !summarize) return kept;
  return Promise.resolve(summarize(dropped, budget - used - 8)).then(text => [
    summaryMessage(text, dropped.length, budget - used), ...kept,
  ]);
}
