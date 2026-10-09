# Memory persistence

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

What survives a session, where it lives, who writes it, and when it is deleted. The why is in [03-memory-and-learning.md](03-memory-and-learning.md); the hook modules are in [hooks.md](hooks.md).

## Two places, on purpose

| Place | Holds | Leaves the machine |
|---|---|---|
| The vault (`NEVA_VAULT`, else `VAULT_PATH` in `~/.config/neva/identity.env`) | what you should be able to read and edit: journal lines, inbox actions, instinct notes, proposals | only if you sync the vault |
| Machine folders (`~/.local/share/neva`, `~/.local/state/neva`) | raw machine data: session state, tool observations, costs, counters | never |

Raw tool traces never go into the vault, and only instincts can be exported.

The learning engine's own writes (the promotion event log, the analyzer lock, temp batches, archives) refuse to pass through a symlink anywhere below their configured root and name the path to fix. If archiving fails part way, the batch goes back to `observations.pending/`: a line may be analysed twice, never lost.

## Everything that persists

| What | Path | Written by | Read by | Deleted |
|---|---|---|---|---|
| Session state | `~/.local/share/neva/sessions/YYYY-MM-DD-<short-id>-session.tmp` | Stop and PreCompact hooks | the next session start, same worktree or repo | after `NEVA_SESSION_RETENTION_DAYS` (30) |
| Tool observations, live | `~/.local/share/neva/observations/<project-id>/observations.jsonl` | `observe` hook | nightly `instinct-analyze`; the same-day trigger counts them | each analysed batch moves to `observations.archive/`; at 10 MB (`NEVA_OBSERVE_MAX_MB`) the whole file moves to `observations.pending/` unread |
| Tool observations, pending | `.../<project-id>/observations.pending/observations-<YYYYmmdd-HHMMSS>-<pid>.jsonl` | `observe` hook at rotation; the nightly job when it recovers an interrupted run | nightly `instinct-analyze`, before the live file; the same-day trigger counts them | never pruned: a pending file leaves only once every line in it is analysed, so unread data waits as long as analysis is off |
| Tool observations, analysed | `.../<project-id>/observations.archive/processed-<ts>-<pid>.jsonl` | nightly `instinct-analyze`, only after the model printed its completion record for that batch | nothing | after 30 days, at session start |
| Project registry | `~/.local/share/neva/observations/projects.json` | hook and instinct CLI | CLI, nightly job | `instinct-cli.py projects gc` |
| Project instincts | `<vault>/06 Memory/instincts/project/<project-id>/<id>.md` | nightly job, `add`, `import` | session start (0.7 and up), `/instinct-status` | never; retired by `status: archived` |
| Global instincts | `<vault>/06 Memory/instincts/global/<id>.md` | `apply-promotions` after your approval | every project | never; retired by `status: archived` |
| Pending instincts | `.../pending/<id>.md` under global or a project | `import --pending` | `/instinct-status` | after 30 days |
| Proposals | `Instinct promotions YYYY-MM-DD.md` in the proposals folder | nightly `propose`, `/evolve --propose`, `/promote` | you; `apply-promotions` | never; `status: done` when resolved |
| Proposal pointer | one line under `## Open actions` in the inbox note | `propose`; ticked by `apply-promotions` | session start | you |
| Proposal ledger | `~/.local/state/neva/instincts/promotions.json` | `propose`, `apply-promotions` | same | never (keeps rejections from coming back) |
| ck project context | `~/.local/share/neva/ck/contexts/<name>/context.json` | `/ck:save` | `/ck:resume`, ck session start | `/ck:forget` |
| Journal lines | the day's note under `08 Journal/` | PreCompact, SessionEnd, journal nudge | session start | you |
| Cost log | `~/.local/share/neva/metrics/costs.jsonl` | `cost_tracker` | `/cost-report`, cost-tracking skill | never |
| Hook counters and markers | `~/.local/state/neva/hooks/` | several hooks | same | after `COMPACT_STATE_TTL_DAYS` (14) |

## Where the inbox is

The inbox note is `NEVA_INBOX` (absolute, or relative to the vault). When unset it is the template's `00 Inbox/inbox.md`; a vault that only has a root `inbox.md` uses that. Session start injects its `## Open actions` section (`NEVA_INBOX_SECTION`), so anything the agent must not forget goes there as a checkbox line.

Proposal files go to `NEVA_PROPOSALS_DIR` when set, else the inbox note's folder. When the inbox note sits at the vault root, proposals go to `06 Memory/instincts/proposals/` so the root stays clean; the pointer line still lands in the root inbox.

## The approval gate

Nothing learned becomes durable memory on its own:

1. The nightly job writes project-scoped instinct notes and proposal blocks, nothing else.
2. You tick `approve` or `reject` in a block, or say "apply instinct promotions" to accept every block you did not reject.
3. `apply-promotions` (nightly, or when you ask) writes exactly the fenced text to the named destination, which must be inside the vault, `~/.claude`, or a registered project's `.claude/`. A destination that already exists is never overwritten.
4. A rejected block is recorded in the ledger and never proposed again.

Agents never tick boxes and never apply on their own.

## Overrides

| Variable | Moves |
|---|---|
| `NEVA_DATA_DIR` | every machine data folder (sessions, observations, metrics, hook log) |
| `NEVA_OBSERVATIONS_DIR` | observations only |
| `NEVA_METRICS_DIR` | the cost log only |
| `NEVA_STATE_DIR` | hook state, gateguard, safety-guard, plan-canvas, the instinct ledger |
| `NEVA_INSTINCT_STATE_DIR` | the instinct ledger only |
| `NEVA_CK_HOME` | ck data |
| `NEVA_INBOX`, `NEVA_INBOX_SECTION`, `NEVA_PROPOSALS_DIR` | the inbox note, its actions heading, the proposals folder |
| `NEVA_SESSION_RETENTION_DAYS` | session file lifetime (`off` keeps them) |

`XDG_DATA_HOME` and `XDG_STATE_HOME` are honoured when the Neva variables are unset.

## Turning parts off

| To stop | Do |
|---|---|
| recording tool observations | `NEVA_SKIP_OBSERVE=1`, or create `~/.local/share/neva/observations/disabled` |
| recording in one tree | add a path fragment to `NEVA_OBSERVE_SKIP_PATHS` |
| nightly analysis | do not enable the `instinct-analyze` timer (it ships disabled) |
| same-day analysis | leave `NEVA_INSTINCT_SAMEDAY` unset (it ships off; only `1` turns it on) |
| context at session start | `NEVA_SESSION_START_CONTEXT=off` |
| any single hook | `NEVA_DISABLED_HOOKS=<id>` |

## Privacy

- Observations are scrubbed of secret-shaped values before they touch disk and cut to 5000 characters per field.
- Instincts describe patterns, never code, file contents, secrets or names.
- Export (`/instinct-export`) carries instincts only.
- Imported instincts are untrusted: review them before they can reach 0.7 confidence.
