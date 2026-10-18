-- Threads and their turns. Append-only: a stored turn is never edited, so a reply that fails
-- still leaves the user's own words on the record. Applied with:
--   wrangler d1 migrations apply neva-omni
CREATE TABLE IF NOT EXISTS threads (
  id         TEXT PRIMARY KEY,
  title      TEXT    NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id  TEXT    NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  role       TEXT    NOT NULL,
  content    TEXT    NOT NULL,
  model      TEXT,
  created_at INTEGER NOT NULL
);

-- getThread reads one thread's turns in time order; listThreads reads the newest threads.
CREATE INDEX IF NOT EXISTS messages_thread_created ON messages (thread_id, created_at);
CREATE INDEX IF NOT EXISTS threads_updated ON threads (updated_at DESC);
