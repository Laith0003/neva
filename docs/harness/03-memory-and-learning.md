# Memory and learning

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
Source: distilled from Affaan Mustafa's Everything Claude Code guides (the longform and security guides).

Memory is distilled lessons, not transcripts. A session leaves behind a short state file and, when it taught something, a small instinct. Nothing else. The canonical process is [process.md](../../plugins/neva-core/rules/process.md).

## Where it lives

| What | Path |
|------|------|
| Session state files | `~/.local/share/neva/sessions/YYYY-MM-DD-<short-id>-session.tmp` |
| Tool observations (machine data) | `~/.local/share/neva/observations/<project-id>/observations.jsonl` |
| Project instincts | `$NEVA_VAULT/06 Memory/instincts/project/<project-id>/<id>.md` |
| Global instincts | `$NEVA_VAULT/06 Memory/instincts/global/<id>.md` |
| Proposals for you | `Instinct promotions YYYY-MM-DD.md` in the inbox folder, plus a pointer under `## Open actions` |

Instinct paths always resolve from the vault (`NEVA_VAULT`, else `VAULT_PATH` in the identity file), never a hardcoded home. The vault's `06 Memory` folder is agent-written; you read it, the agent maintains it. Every path and override is listed in [memory-persistence.md](memory-persistence.md).

## Session persistence

Rule: one file per session, written by hooks, loaded by the next session. Never append to an old session's file.

Why: a fresh file per session keeps yesterday's dead ends out of today's work, and a written file survives compaction, restarts and model changes.

File name: `YYYY-MM-DD-<short-id>-session.tmp`, where the short id is the last 8 characters of the session id. Hooks own the block between `<!-- NEVA:SUMMARY:START -->` and `<!-- NEVA:SUMMARY:END -->` (tasks, files modified, tools used, stats); notes written below it survive every refresh.

Every session file should answer three questions:

1. What worked, with the evidence that shows it worked.
2. What was tried and did not work.
3. What has not been tried yet, and what is left to do.

Plus a "Context to load" list of the files the next session should read first.

## The hooks that save and load state

| Event | Module | Job | Blocks |
|-------|--------|-----|--------|
| SessionStart | `session_start` | inject strong instincts, journal head, inbox open actions, open proposals, the last session summary for this worktree or repo; prune old files | no |
| SessionStart | `ck_session_start` | the ck skill's saved goal, where you left off, next steps | no |
| PreToolUse, PostToolUse, PostToolUseFailure | `observe` | append one scrubbed line per tool event for the nightly analyzer | no |
| PreCompact | `pre_compact` | write the summary block and one journal line before compaction | no |
| Stop | `session_summary` | refresh the summary block in the session file | no |
| SessionEnd | `session_audit` | one audit line per session in the journal | no |

Bounds on what SessionStart injects:

| Setting | Default | Effect |
|---------|---------|--------|
| look-back window | 7 days | only recent session files are considered for the prior summary |
| `NEVA_SESSION_START_MAX_CHARS` | 8000 | injected context is truncated past this, with a marker saying so; `0` disables injection |
| `NEVA_SESSION_START_CONTEXT` | on | `off` disables injected context |
| `NEVA_SESSION_RETENTION_DAYS` | 30 | session files older than this are deleted at session start; `off` keeps them |
| `NEVA_INSTINCT_MIN_CONFIDENCE` | 0.7 | only strong instincts are injected |
| `NEVA_INSTINCT_MAX` | 6 | at most this many, project instincts first on ties |

On `startup` everything above is injected. On `clear` and `compact` the prior-session summary is left out (the current work is still in context). On `resume` nothing is injected: the resumed transcript already holds it.

Why Stop, not UserPromptSubmit, for the heavy work: UserPromptSubmit runs on every message and adds latency to each one. Stop runs once at the end.

Keep persistence local by default. Transcripts and tool traces never leave the machine unless you explicitly enable an integration.

## Continuous learning: instincts

Rule: when the agent discovers something non-trivial (a debugging technique, a workaround, a project pattern), it becomes an instinct. When you have had to repeat a correction, that correction becomes an instinct.

Why: observation by hook is complete. Observation by skill is not: skills fire at the model's discretion, roughly 50 to 80% of the time upstream measured. Hooks fire every time.

An instinct is one trigger and one action, one markdown note per instinct:

```yaml
---
id: prefer-functional-style
trigger: "when writing new functions"
confidence: 0.7
domain: code-style
source: session-observation
scope: project
project_id: a1b2c3d4e5f6
project_name: "my-react-app"
evidence_count: 6
date: 2026-01-15
last_observed: 2026-01-22
decay_weeks_applied: 0
status: active
tags: [instinct, code-style]
---

# Prefer Functional Style

## Action
Use functional patterns over classes when appropriate.

## Evidence
- Observed 5 instances of functional pattern preference
- User corrected a class-based approach to functional
```

Properties: atomic, confidence-weighted, domain-tagged, evidence-backed, scope-aware. Only `status: active` notes load.

### Pipeline

1. The `observe` hook appends each tool call and outcome to the project's observations file. Secrets are scrubbed, inputs and outputs cut to 5000 characters, file tools carry a `path`.
2. A nightly job (`instinct-analyze`, 03:30, launchd or systemd timer rendered by `install.sh`, not a daemon) takes every project with at least 20 new observations and, oldest first, sends them to a small model in batches of at most 500 lines (up to 4 batches per project per run) to write project-scoped instinct notes. New observations are the live file plus any file the hook rotated unread into `observations.pending/` at 10 MB; pending files go first and are never pruned, only archived once analysed. Each batch is one model call, so a run makes at most 4 calls per qualifying project. A batch counts only when the model prints the exact completion record; then exactly that batch moves to the archive. On any failure that batch and everything after it stay for the next run, and anything a run did not reach stays in place. Nothing is archived unread.
3. The same job decays confidence by 0.02 per week without observation, prunes pending instincts older than 30 days, and files proposals: promote to global, evolve into a skill, command or agent, become a rule, or retire.
4. Nothing leaves project scope and nothing becomes a skill, command, agent or rule until you tick `approve` in the proposal file or say "apply instinct promotions".

| Job setting | Default |
|------------------|---------|
| schedule | nightly, 03:30 (not enabled until you enable it) |
| same-day run | off (`NEVA_INSTINCT_SAMEDAY=1` turns it on, see below) |
| minimum new observations before analysis | 20 (`NEVA_INSTINCT_MIN_OBSERVATIONS`) |
| lines per batch | 500 (`NEVA_INSTINCT_MAX_ANALYSIS_LINES`) |
| batches per project per run | 4 (`NEVA_INSTINCT_MAX_BATCHES`) |
| model | haiku (`NEVA_INSTINCT_MODEL`) |
| timeout per batch | 120 s |

### Same-day trigger

A SessionEnd hook module (`sameday_trigger`, `plugins/neva-core/hooks/neva_hooks/learning_trigger.py`)
can fire `instinct-analyze.py` early when a lot of observations pile up in one day, instead of
waiting for 03:30. It is off by default and stays off until you opt in, whether or not you enabled
the nightly timer. When on, each launch runs `claude --print` once per batch: up to 4
(`NEVA_INSTINCT_MAX_BATCHES`) batches of at most 500 lines for every qualifying project, which
spends model credit and writes instinct notes, proposals and the archive, exactly like a nightly
run. Turn it on by exporting `NEVA_INSTINCT_SAMEDAY=1` in the environment Claude Code starts with
(for example the `env` block of your Claude Code settings). It runs in the `standard` and `strict`
profiles only, the same ones that run `observe`.

| Env var | Default | Effect |
|---|---|---|
| `NEVA_INSTINCT_SAMEDAY` | unset (off) | exactly `1` turns the trigger on; any other value leaves it off |
| `NEVA_INSTINCT_SAMEDAY_MIN` | 200 | observations needed to fire, live plus pending, counted only in project buckets the analyzer would analyze (at least `NEVA_INSTINCT_MIN_OBSERVATIONS`, default 20, each), so many small projects never launch a run that skips them all |
| `NEVA_INSTINCT_SAMEDAY_HOURS` | 6 | hours that must have passed since the analyze lock file was last touched by a real run before firing again |
| `NEVA_HEADLESS` | unset | any truthy value makes the trigger (and every other hook) a no-op |

The trigger only decides and returns: it probes the lock `instinct-analyze.py` takes at startup,
skips when a run already holds it, then launches the job detached
(`subprocess.Popen(start_new_session=True)`) and returns immediately, so a session never waits on
it. The probe is released before the launch, so two sessions ending in the same instant can both
launch; the second job exits at once on the analyzer's own lock, which is what guarantees a
single run.

### Model routing

`instinct-analyze.py` runs its analysis child with `claude --print`. Two env vars route that
child at a different Anthropic-compatible endpoint instead of the default one:

| Env var | Effect |
|---|---|
| `NEVA_INSTINCT_BASE_URL` | sets the child's `ANTHROPIC_BASE_URL` |
| `NEVA_INSTINCT_AUTH_TOKEN` | sets the child's `ANTHROPIC_AUTH_TOKEN` |

Setting `NEVA_INSTINCT_AUTH_TOKEN` also clears the child's `ANTHROPIC_API_KEY` (set to an empty
string), so the token wins over a key already in the environment. `NEVA_INSTINCT_BASE_URL` alone
keeps that key, for a gateway that forwards it. Neither set means the child's environment is
exactly what it was before: no `ANTHROPIC_*` override.

### Confidence

| Score | Meaning | Behaviour |
|-------|---------|-----------|
| 0.3 | tentative | suggested, not enforced |
| 0.5 | moderate | applied when relevant |
| 0.7 | strong | injected at session start |
| 0.9 | near certain | core behaviour, candidate for a rule |

Initial confidence by observations: 3 to 5 gives 0.5, 6 to 10 gives 0.7, 11 or more gives 0.85. Goes up 0.05 per confirming observation (cap 0.9), down 0.1 per correction, down 0.02 per week unobserved. Below 0.3 it is proposed for retirement.

### Scope

Project scope is the default, so one codebase's conventions do not leak into another.

Project detection, the same in the hook and the CLI:

1. `CLAUDE_PROJECT_DIR` when set (its git toplevel, else its path; honoured outside git).
2. Else the git toplevel of the working directory.
3. Else the bucket `unscoped`, treated as a project so nothing is ever written straight to global.

The id is the first 12 hex characters of SHA-256 over the normalized `origin` remote (so the same repo on two machines gets the same id), else over the main worktree root (so linked worktrees share one id).

| Pattern type | Scope |
|--------------|-------|
| language or framework conventions | project |
| file structure preferences | project |
| code style | project |
| error handling strategy | project |
| security practices | global |
| general practices such as tests first | global |
| tool workflow such as read before write | global |
| git practices | global |

Promotion to global: the same instinct id active in 2 or more projects with average confidence of 0.8 or higher, or one project instinct the analyzer marked `scope_hint: global` at 0.7 or higher. Both are proposals you approve.

Layout under `$NEVA_VAULT/06 Memory/instincts/`:

```
instincts/
  global/<id>.md                 every project
  global/pending/<id>.md         imports waiting for review, pruned after 30 days
  project/<project-id>/<id>.md   one project
  project/<project-id>/pending/  same, per project
  proposals/                     only when the inbox note sits at the vault root
```

Raw observation logs are machine data and stay under `~/.local/share/neva/`, not in the vault. Only instincts are exported, never raw observations, code or conversation content.

### Stats

`instinct-cli.py stats` prints one `KEY: value` line per metric, plus two JSON lines:

```
Project: <name> (<project-id>)
UNIQUE: <n>
BY_SCOPE: {"project": <n>, "global": <n>}
BY_DOMAIN: {"<domain>": <n>, ...}
BY_SOURCE: {"<source>": <n>, ...}
AVG_CONFIDENCE: <0.00-1.00>
PENDING: <n>
OBSERVATIONS_WAITING: <n>
PROMOTIONS_APPLIED: <n>
PROMOTIONS_REJECTED: <n>
PROMOTIONS_APPROVE_RATE: <0.00-1.00 or n/a>
PROPOSALS_MADE: <n>
PROPOSALS_APPROVED: <n>
PROPOSALS_REJECTED: <n>
PROPOSALS_APPROVE_RATE: <0.00-1.00 or n/a>
PROPOSALS_BY_WEEK: {"<YYYY-Www>": {"made": <n>, "approved": <n>, "rejected": <n>}, ...}
```

`PROMOTIONS_*` reads the ledger (`<state dir>/instincts/promotions.json`): one entry per block,
its most recent outcome only. `PROPOSALS_*` reads an append-only event log instead
(`<state dir>/instincts/promotion-events.jsonl`, one JSON line per proposal made, approved or
rejected), so it is a full history rather than a snapshot, and `PROPOSALS_BY_WEEK` breaks it down
by ISO week (`YYYY-Www`). A block counts as rejected either from an explicit `- [x] reject` tick
or from the whole block, including its `<!-- block_id: ... -->` marker, being deleted from the
proposal file without a tick. A block whose marker is still there but no longer sits directly
under its `## ` heading is not a rejection: `apply-promotions` names the block, exits 1, leaves
its status alone and keeps the file open until the heading is restored. A line in the event
log that is not valid JSON is skipped rather than failing the command.

## Memory is an attack surface

Persistent memory is useful, and a payload does not need to win in one shot: it can plant fragments, wait, and assemble later. Keep memory narrow:

- never store secrets in memory files
- keep project memory separate from global memory
- reset or rotate memory after a run that touched untrusted content
- disable long-lived memory entirely for high-risk workflows (all-day web, email attachments, foreign documents)
- review any instinct imported from someone else before it can reach 0.7

More in [05-security.md](05-security.md).

## Where knowledge goes

| Kind | Home |
|------|------|
| personal debugging notes, preferences, temporary context | session files and instincts |
| team or project knowledge: architecture decisions, API changes, runbooks | the project's own docs |
| something the current task already documents | nowhere else; do not duplicate |
| no obvious home | ask before creating a new top-level file |
