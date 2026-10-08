# The cockpit: a read-only dashboard over the hooks runtime

`neva cockpit` shows what the hooks runtime (`plugins/neva-core/hooks/neva_hooks/`) already
writes to disk: sessions, their cost and context usage, a short list of risk flags, and the
health of the scheduled jobs, OmniRoute, pending lesson proposals and the nightly instinct job.
Python standard library only, no dependencies, no network beyond the local health probes.

```
neva cockpit            # curses TUI
neva cockpit --json     # one JSON snapshot to stdout, then exit
neva cockpit --web      # read-only web view on 127.0.0.1, token in the URL
```

## What it reads

Nothing here reimplements the hooks runtime's data dir resolution
(`plugins/neva-core/hooks/neva_hooks/common.py`); `lib/neva_cockpit/__init__.py` imports it
directly, so the cockpit always points at the same `NEVA_DATA_DIR` the hooks write into.

| Source | What it gives the cockpit |
|---|---|
| `<data dir>/sessions/*-session.tmp` | project, branch, session id, started/last-updated timestamps |
| `<data dir>/metrics/costs.jsonl` | cumulative cost per session; `transcript_path` feeds `context_pct` via `neva_hooks.common.context_tokens`'s bounded tail read |
| `<data dir>/observations/<project-id>/observations.jsonl` | risk flags: `tool-error:<tool>` on a `tool_error` event, `destructive-bash:*` when a `Bash` command matches a short list of destructive patterns (`rm -rf`, `git push --force`, `git reset --hard`, `DROP TABLE`, `curl \| sh`). The observe hook cuts input at 5000 characters; for a cut command the patterns run over the part that was kept, and `bash-input-truncated` is added so a long command is never shown as clean |
| `~/.codex/sessions/**/rollout-*.jsonl` | only the first line (`session_meta`) is read, for id, cwd and start time. Current Codex writes its whole system prompt into that line (18 KB to 42 KB), so it is read up to a 1 MB cap; a first line over the cap, not JSON, or not a session record becomes a rejected-row note, once per file, never a file silently marked read. The id is `payload.session_id`, falling back to `payload.id` for older records, the same fallback Codex's own reader applies; a first line still being written is retried next run. Last activity is the file's mtime, never the time of ingest |
| `<data dir>/hooks.log` | error records, one panel line each: `log_exception` writes a traceback as indented continuation lines, so the line kept is `<where>: <exception type and message> (at <file>:<line> in <function>)`, at most 400 characters, never the bare "Traceback (most recent call last):" header. Kept in the store's `ingest_notes` table (newest 200) and shown as a standalone panel in the TUI, the web page and `--json` (`hook_errors`). These carry no session id in the log format, so they are never guessed onto a session's risk flags. Rejected source lines are kept the same way (`rejected_rows`). A note is saved in the same transaction that moves its file's offset past the line, so a failed save leaves the offset where it was and the next run records the note exactly once |

Every source is read incrementally: `ingest_offsets` (in the cockpit's own sqlite database)
remembers `(path, offset, mtime, size, inode, signature)` per file, so re-running the ingester
after nothing changed inserts zero new rows, and nothing here ever opens a whole transcript. The
signature hashes the first and last 4 KB of the region already read. A file with a new inode
(rotated or replaced), one smaller than what was read (truncated), or one whose read region no
longer hashes the same (rewritten in place, at any size) is read again from the start. A line in a JSONL
source that is not valid JSON, or is valid JSON with the wrong shape or a wrong field type (a
cost that is not a number, a session id that is not a string), is skipped and reported with its
line number and reason; it never takes down the valid lines around it, and the offset moves past
it so the next run makes progress. A database error is not a bad line: it stops the run before
the offset advances, so nothing is lost.

## The store

`lib/neva_cockpit/store.py` is a small sqlite3 wrapper: a `schema_version` table and numbered
migrations applied in order, a `sessions` table (one row per session id, across harnesses), and
`ingest_offsets`. `Store.upsert_session` only changes the columns a call mentions; a column it
does not mention keeps whatever an earlier source already wrote, since different sources own
different columns (the session summary owns project and branch, costs.jsonl owns cost_usd,
observations own risk_flags via `add_risk_flags`, which unions and dedupes rather than
replacing). A source that lacks a field omits it rather than writing an empty value, so a sparse
cost row never blanks the project a session summary recorded. `last_activity` only moves
forward in real time: timestamps are compared as instants, honouring an offset or a trailing
`Z`, and a naive time (session summaries) is read in the timezone the hooks write in
(`NEVA_TIMEZONE`, else `TIMEZONE` in the identity file, else the machine's zone). The same
instant in another offset is not a move, and an empty value never wins. Sessions sort by that
instant (`last_activity_at`), not by the string.

## Health

`lib/neva_cockpit/health.py` probes, each returning a specific failure string rather than an
empty result:

- **Scheduled jobs**: `launchctl list` filtered to Neva's own `com.neva.*` namespace, with
  each job's last exit status. macOS only. To watch jobs from another namespace of your own, set
  `NEVA_COCKPIT_JOB_PREFIXES` (comma-separated) or `COCKPIT_JOB_PREFIXES="..."` in your identity
  file; that keeps a personal namespace out of the tracked code.
- **OmniRoute**: `GET http://127.0.0.1:20128/v1/models`, 3 second timeout, with the key read from
  `~/.omniroute/neva-builder.key`. The key is read only to build the request header; it is never
  put into a log line, a detail string, or an exception message. A key with whitespace, a
  control character or a non-ASCII character is refused before any request is built (the HTTP
  client would otherwise raise with the whole header in its message), and any other transport
  error is reported by its type only.
- **Pending lesson proposals**: the count of open `Instinct promotions *.md` files
  (`neva_hooks.common.open_proposal_files`), or a specific failure when no vault is configured.
- **Last nightly result**: the tail of `<state root>/instinct-analyze.log`, read for the last
  `start (` marker and whether a `done` (or an intentional "previous run still active" skip)
  followed it.

## The web view

`lib/neva_cockpit/web.py` is read-only, on `http.server`. It binds `127.0.0.1` only: anything
else raises rather than being silently rewritten. Every route sits under a random token
(`secrets.token_urlsafe(24)`) in the path; a request missing the token, or carrying the wrong
one, gets 404 with no data, the same as a route that does not exist. There are exactly two
routes, both GET: the JSON snapshot and one HTML page. The page is rendered on the server from
the same snapshot (sessions, hook errors, health), every value HTML-escaped, so it reads
correctly before any script runs; the script then polls the snapshot every five seconds and
says so on the page when a refresh fails. Both the TUI and the web view run an incremental
ingest at every refresh, so a session, cost or risk flag written after the cockpit started shows
up without a restart.

## The TUI

`lib/neva_cockpit/ui.py` is a curses table of sessions (harness, project, branch, started, last
activity, cost, context percentage, risk flags), a hook-error panel (the newest three) and the
health panel, refreshing every two seconds. All three views draw from one
`neva_cockpit.snapshot.build()` call, so they never disagree. It degrades with a specific message instead of a traceback in the two cases curses
cannot handle: stdout is not a terminal at all (`--json` or `--web` suggested instead), or the
terminal is attached but smaller than 80x10 (resize, or press `q`).

## Tests

`python3 -m unittest discover -s lib/neva_cockpit/tests -t lib` runs the suite: migrations,
partial-update semantics on the sessions table, the required ingest negative controls (a
malformed JSONL line is skipped while valid lines on either side still land; re-running the
ingester on an unchanged file inserts zero new rows), the web server's bind guard and token
checks, and the TUI's degrade paths. `build/verify.sh` section 28 runs it, then exercises the
shipped `bin/neva cockpit --json` against fixture data planted exactly where the hooks runtime
would have written it, including one deliberately malformed line in each JSONL source, then runs
the installed `~/.local/bin/neva cockpit --json` from the install prefix against the same data.
Its negative controls only count the specific failure they exist for: the bind guard must raise
its own ValueError naming the refused host (and a 127.0.0.1 bind must succeed, so a sandbox that
denies sockets cannot pass for the guard), and the missing-session control validates the
baseline snapshot before its deliberate assertion. `lib/neva_cockpit/tests/test_installed.py`
installs into a throwaway HOME and runs the installed symlink the same way.
