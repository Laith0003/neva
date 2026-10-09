---
name: continuous-learning-v2
description: "Use when capturing lessons from sessions, reviewing or searching what has been learned, managing instincts, or deciding which instincts become global, skills, commands, agents, or rules. Hook observes, a nightly job analyzes, a human approves promotions."
metadata:
  version: 2.1.0-neva
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with garrytan/gstack learn (MIT, Garry Tan). -->

# Continuous Learning v2.1: Instincts

Sessions become reusable knowledge through **instincts**: small learned behaviors, each with one trigger, one action, a confidence score, and the evidence behind it. A hook records what happens. A nightly job turns records into instincts. A human decides what becomes durable.

```
Session activity (tool calls, in a git repo or not)
      |
      | observe hook (PreToolUse + PostToolUse, fires on every call)
      v
~/.local/share/neva/observations/<project-id>/observations.jsonl      raw, scrubbed, never in the vault
      |
      | instinct-analyze, nightly timer (not a daemon)
      v
$NEVA_VAULT/06 Memory/instincts/project/<project-id>/<id>.md         one note per instinct
      |
      | decay, then propose (deterministic thresholds)
      v
<proposals dir>/Instinct promotions YYYY-MM-DD.md                   one block per candidate, with a checkbox
  + one pointer line under `## Open actions` in the inbox note         surfaced at every session start
      |
      | human ticks approve, or says "apply instinct promotions"
      v
global instinct | skill | command | agent | rule | retirement
```

**Iron rule:** nothing leaves project scope, and nothing becomes a skill, command, agent, or rule, until a human ticks its block or says "apply instinct promotions". The analyzer writes project-scoped notes only. The proposal step writes proposals only.

## When to Activate

- Setting up or checking automatic learning from sessions
- "What have we learned?", "show learnings", "didn't we fix this before?"
- Searching, pruning, exporting, or manually adding instincts
- Reviewing the instinct promotion proposals in the inbox
- Evolving instincts into skills, commands, or agents
- Tuning confidence thresholds, decay, or the nightly job

**HARD GATE:** this skill manages learnings only. Do not implement code changes while running it.

## The Instinct Model

One instinct per file, named `<id>.md`, readable and editable in Obsidian:

```markdown
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
- Observed 5 instances of functional pattern preference in session abc123
- User corrected class-based approach to functional on 2026-01-15
```

**Properties:**
- **Atomic:** one trigger, one action.
- **Confidence-weighted:** 0.3 tentative to 0.9 near-certain.
- **Domain-tagged:** code-style, testing, git, debugging, workflow, file-patterns, security.
- **Evidence-backed:** `evidence_count` plus Evidence bullets. Never code snippets, only patterns.
- **Scope-aware:** `project` (default) or `global`. `scope_hint: global` marks a project instinct the analyzer thinks is universal; it is a promotion candidate, not a global instinct.
- **Status:** `active`; `promoted` (a global copy exists, see `promoted_to`); `archived` (retired). Only `active` instincts load.
- Optional `files: [path, ...]` for instincts tied to specific files (checked by prune).

Bodies must use `***` or `___` for horizontal rules. A line of `---` is always a frontmatter boundary.

## Storage Layout

| What | Where | Written by |
|---|---|---|
| Project instincts | `$NEVA_VAULT/06 Memory/instincts/project/<project-id>/<id>.md` | nightly analyzer, `add`, `import` |
| Global instincts | `$NEVA_VAULT/06 Memory/instincts/global/<id>.md` | `apply-promotions` only (or `add --scope global` / `import --scope global` run by the human) |
| Pending instincts | `<either dir>/pending/<id>.md` | `import --pending`; pruned after 30 days unless moved out |
| Observations | `<data dir>/observations/<project-id>/observations.jsonl` | observe hook (`hooks/neva_hooks/observe.py`) |
| Rotated and analyzed observations | `.../<project-id>/observations.archive/` (`processed-<ts>-<pid>.jsonl`, written only after the nightly job analysed them; rotated files wait in `observations.pending/`, never pruned); deleted after 30 days at session start | hook, nightly job |
| Project registry | `<data dir>/observations/projects.json` | hook and CLI |
| Proposal ledger | `<state dir>/instincts/promotions.json` | `propose`, `apply-promotions` |
| Job log | `<state dir>/instinct-analyze.log` | nightly job |
| Proposals for the human | `<proposals dir>/Instinct promotions YYYY-MM-DD.md` | `propose` |
| Pointer for the human | one `- [ ] Review instinct proposals: [[...]]` line under `## Open actions` in the inbox note; ticked when the file is done | `propose`, `apply-promotions` |

Resolution, shared with the hook runtime so both sides agree:

| Name | Order |
|---|---|
| vault | `NEVA_VAULT` (absolute), else `VAULT_PATH` in the identity file (`NEVA_CONFIG`, default `~/.config/neva/identity.env`) |
| data dir | `NEVA_OBSERVATIONS_DIR` for observations; else `NEVA_DATA_DIR`; else `$XDG_DATA_HOME/neva`; else `~/.local/share/neva` |
| state dir | `NEVA_INSTINCT_STATE_DIR` for the ledger; else `NEVA_STATE_DIR`; else `$XDG_STATE_HOME/neva`; else `~/.local/state/neva` |
| inbox note | `NEVA_INBOX` (absolute or vault-relative); else `00 Inbox/inbox.md`; else a root `inbox.md` when only that exists. The pointer goes under `## Open actions` (`NEVA_INBOX_SECTION`), created when missing |
| proposals dir | `NEVA_PROPOSALS_DIR` (absolute or vault-relative); else the inbox note's folder; else, for a root inbox, `06 Memory/instincts/proposals` |

Never hardcode a home path. With no vault, every command exits 2 with `NEVA_VAULT is not set (or not absolute) and the identity file has no VAULT_PATH. Fix: export NEVA_VAULT=/absolute/path/to/your/vault`. `CLAUDE_CONFIG_DIR` sets where user-level skills, commands, agents, rules land. From a hook context, `hooks/instincts.py [--cwd DIR] <command>` is a thin shim that fills in the vault and project directory and calls these scripts (`analyze` runs the nightly job).

Sessions outside any project use the bucket id `unscoped` (observations and project instincts alike), so the analyzer never writes to `global/`.

## Project Detection

Same algorithm in the hook and the CLI, so ids agree:

1. `CLAUDE_PROJECT_DIR` if set and a directory: its git toplevel, else its real path (explicit override, honored even outside git).
2. `git rev-parse --show-toplevel` from the session cwd.
3. None: bucket `unscoped`. `NEVA_NO_PROJECT=1` forces this.

Project id = first 12 hex chars of SHA-256 over, in order of preference: the normalized `origin` remote (credentials stripped, scheme stripped, `user@host:` rewritten to `host/`, `.git` and trailing `/` removed, lowercased for network remotes; portable across machines), else the main worktree root path (so linked worktrees share an id). The registry maps id to `{id, name, root, remote (credential-stripped), created_at, last_seen}`.

## Observation Hook Contract

Implemented by the `observe` module of the neva-core hook runtime (`hooks/neva_hooks/observe.py`, registered in `hooks/hooks.meta.json`). The contract it meets:

| Item | Contract |
|---|---|
| Events | `PreToolUse`, `PostToolUse` and `PostToolUseFailure` (record `tool_error` with `error`), each registered once with matcher `*`. The module never blocks. |
| Input fields read | `hook_event_name` (or phase argument), `tool_name`, `tool_input`, `tool_response` (fallbacks `tool_output`, `output`), `session_id`, `cwd`, `agent_id` |
| Skip (write nothing) | `CLAUDE_CODE_ENTRYPOINT` set and not in `cli, sdk-ts, sdk-cli, claude-desktop, claude-vscode`; `NEVA_HOOK_PROFILE=minimal`; `NEVA_SKIP_OBSERVE=1` (set by the nightly job, so it never observes itself); `agent_id` present (subagent); cwd contains any entry of `NEVA_OBSERVE_SKIP_PATHS` (default `observer-sessions,.claude-mem`); file `<data dir>/observations/disabled` exists |
| Output | append one JSON line to `<obs-root>/<project-id>/observations.jsonl` |
| Record fields | `timestamp` (UTC `YYYY-MM-DDTHH:MM:SSZ`), `event` (`tool_start` for Pre, `tool_complete` for Post), `tool`, `session`, `project_id`, `project_name`, `input` (tool_start only), `output` (tool_complete only), `path` (Neva addition, `tool_start` only: `tool_input.file_path` or `notebook_path` for Read, Edit, Write, MultiEdit, NotebookEdit; skill-stocktake counts Read of a SKILL.md path plus `Skill` tool starts by name) |
| Truncation | `input` and `output` serialized to JSON when dicts, cut to 5000 chars |
| Secret scrubbing | before writing, replace the value of every match of `(?i)(api[_-]?key\|token\|secret\|password\|authorization\|credentials?\|auth)(["'\s:=]{1,8})((?:bearer\|basic\|token\|bot)\s+)?([A-Za-z0-9_\-/.+=]{8,256})` with `[REDACTED]`, keeping groups 1 to 3. The quantifiers are bounded on purpose (linear time, no catastrophic backtracking). |
| Parse failure | write `{"timestamp", "event": "parse_error", "raw": <first 2000 chars, scrubbed>}` |
| Timeout | the dispatcher's 15 s hook timeout; a module error is logged to `<data dir>/hooks.log` and never reaches the session |
| Rotation | when the live file reaches `NEVA_OBSERVE_MAX_MB` (10), rename it to `observations.pending/observations-<YYYYmmdd-HHMMSS>-<pid>.jsonl`; the nightly job analyses pending files first and archives only what it analysed |
| Retention | at session start, delete archive files older than 30 days |
| Registry | update `projects.json` under an exclusive lock, atomic replace, on each project cache miss (at most every 10 minutes per directory) |

## Nightly Analysis Job: `instinct-analyze`

Scheduled by Neva as a timer (launchd `com.neva.instinct-analyze`, systemd `neva-instinct-analyze.timer`), once a night, for example 03:30 local. The unit runs:

```bash
python3 <install prefix>/plugins/neva-core/skills/continuous-learning-v2/scripts/instinct-analyze.py
```

`install.sh` copies this skill to `~/.local/neva/plugins/neva-core/` and renders the unit templates (`services/launchd/com.neva.instinct-analyze.plist.tmpl`, `services/systemd/neva-instinct-analyze.{service,timer}.tmpl`, 03:30 nightly, through `heartbeat-wrap.sh`). They are not enabled until you enable them. The vault comes from `NEVA_VAULT` or the identity file; the unit's `PATH` must contain the `claude` binary (install bakes in the directory it found), or set `NEVA_CLAUDE_BIN`. The job holds a lock (`~/.local/state/neva/instinct-analyze.lock`); an overlapping run exits 0. Steps, in order:

1. **apply-promotions**: apply blocks the human ticked since the last run.
2. **analyze**, for every observation bucket with at least `min_observations_to_analyze` (20) lines:
   - split the complete lines, oldest first, into near-equal batches of at most `max_analysis_lines` (500) lines and take up to `max_batches_per_run` (4) of them; each batch goes to the model through its own temp file (never pass multi-MB payloads to the model);
   - render `analyzer-prompt.md` and run `claude --model haiku --max-turns N --print --allowedTools Read,Write -p <prompt>` with cwd = the project instinct dir, stdin closed, `NEVA_SKIP_OBSERVE=1 NEVA_HEADLESS=1 NEVA_HOOK_PROFILE=minimal`;
   - `N` = 1 turn per 10 lines in the batch, floor 20, cap 100 (override `NEVA_INSTINCT_MAX_TURNS`, values below 4 fall back to 20);
   - timeout 120 s, then SIGTERM to the process group, then SIGKILL;
   - **accept only** when the exit code is 0 and the last non-empty output line is exactly `{"status":"analysis_complete"}` and it appears once. Exit 0 alone is not success;
   - on success, archive exactly that batch as `processed-<ts>-<pid>.jsonl` and keep everything after it, including anything the hook appended since; on any failure, stop and retain that batch and everything after it for the next run. Observations a run did not reach stay in place; nothing is archived unread.
3. **decay** (below).
4. **prune** pending instincts older than 30 days.
5. **propose** (below).

Config: `config.json` next to this file (`analyze.min_observations_to_analyze`, `max_analysis_lines`, `model`, `timeout_seconds`, `max_turns`, `max_batches_per_run`); env overrides `NEVA_INSTINCT_MIN_OBSERVATIONS`, `NEVA_INSTINCT_MAX_ANALYSIS_LINES`, `NEVA_INSTINCT_MODEL` (use `opus` for higher-quality extraction and raise the timeout), `NEVA_INSTINCT_TIMEOUT_SECONDS`, `NEVA_INSTINCT_MAX_TURNS`, `NEVA_INSTINCT_MAX_BATCHES`. Flags: `--dry-run` (calls nothing, logs what would run), `--project <id>`, `--skip-analysis`.

The upstream 5-minute observer daemon, its PID files, SIGUSR1 nudges, active-hours and idle guards, and start/stop scripts are gone: a nightly batch needs none of them.

## Confidence Scoring

| Score | Meaning | Behavior |
|---|---|---|
| 0.3 | Tentative | Suggested but not enforced |
| 0.5 | Moderate | Applied when relevant |
| 0.7 | Strong | Auto-approved for application |
| 0.9 | Near-certain | Core behavior |

**Initial confidence** (by observation count): 1-2 observations 0.3 (the analyzer does not write these; it needs 3+), 3-5 observations 0.5, 6-10 observations 0.7, 11+ observations 0.85.

**Adjustments** (applied by the analyzer when it updates an existing note): +0.05 per confirming observation (cap 0.9), -0.1 per contradicting observation (the user corrected the behavior), and it resets `last_observed` and `decay_weeks_applied: 0`.

**Decay** (deterministic, `instinct-cli.py decay`): -0.02 per full week since `last_observed` (fallback `date`, then file mtime). `decay_weeks_applied` records the weeks already charged, so running decay twice changes nothing. Floor 0.0.

Confidence rises when a pattern is observed again, the user does not correct it, or other sources agree. It falls when the user corrects it, when it goes unobserved, or when contradicting evidence appears.

## Scope Decision Guide

| Pattern Type | Scope | Examples |
|---|---|---|
| Language/framework conventions | **project** | "Use React hooks", "Follow Django REST patterns" |
| File structure preferences | **project** | "Tests in `__tests__`/", "Components in src/components/" |
| Code style | **project** | "Use functional style", "Prefer dataclasses" |
| Error handling strategies | **project** | "Use Result type for errors" |
| Security practices | **global** | "Validate user input", "Sanitize SQL" |
| General best practices | **global** | "Write tests first", "Always handle errors" |
| Tool workflow preferences | **global** | "Grep before Edit", "Read before Write" |
| Git practices | **global** | "Conventional commits", "Small focused commits" |

**When in doubt, stay project-scoped.** It is safer to promote later than to contaminate global scope. In Neva "global" rows mean `scope_hint: global` on a project note; the move itself is a proposal.

## Promotion: the Proposal Contract

`instinct-cli.py propose` (run nightly, or by hand) collects every candidate below, skips any block id already applied or rejected (or already open in an existing proposal file), and appends the rest to `<proposals dir>/Instinct promotions YYYY-MM-DD.md`. A second run the same day appends to the same file. Each new file gets one pointer line under `## Open actions` in the inbox note, so session start surfaces it; `apply-promotions` ticks that line when every block is resolved.

| Kind | Candidate when | Proposed destination | Write mode |
|---|---|---|---|
| `promote-global` | same instinct id active in **2+ projects** with **average confidence >= 0.8**, or one project note with `scope_hint: global` and confidence >= 0.7; not already global | `vault:06 Memory/instincts/global/<id>.md`; then source notes get `status: promoted` and `promoted_to` | create |
| `evolve-skill` | 2+ instincts in one scope whose triggers share 2+ keywords with overlap coefficient >= 0.5 | `<project root>/.claude/skills/<name>/SKILL.md` when every member is from one registered project, else the user config dir (`$HOME/.claude` or `CLAUDE_CONFIG_DIR`) `skills/<name>/SKILL.md` | create |
| `evolve-command` | `workflow` instinct with confidence >= 0.7 | `.../.claude/commands/<name>.md` (same rule) | create |
| `evolve-agent` | skill cluster with 3+ instincts and average confidence >= 0.75 | `.../.claude/agents/<name>.md` (same rule) | create |
| `rule` | global instinct with confidence >= 0.9 (near-certain, core behavior) | `~/.claude/rules/instincts-<domain>.md` | append |
| `retire` | any active instinct whose confidence is below 0.3 (after decay or contradiction) | the instinct note itself | set-frontmatter (`status: archived`) |

The nightly run proposes at most 5 evolve candidates per kind per scope and prints how many it held back; run `instinct-cli.py evolve --propose --limit 0` for all.

**File format** (exact; `apply-promotions` parses it):

```markdown
---
tags: [inbox, instinct-promotions]
date: YYYY-MM-DD
status: open
generated_by: instinct-analyze
---

# Instinct promotions YYYY-MM-DD

(four lines of instructions)

## promote-global: prefer-explicit-errors
<!-- block_id: promote-global:prefer-explicit-errors -->

- [ ] approve
- [ ] reject

| Field | Value |
| --- | --- |
| Kind | promote-global |
| Instinct | `prefer-explicit-errors` |
| Confidence | 0.88 |
| Evidence count | 14 |
| Projects seen in | api-server (a1b2c3d4e5f6); web-app (f6e5d4c3b2a1) |
| Why | seen in 2 projects, average confidence 0.88 >= 0.80 |
| Proposed destination | `vault:06 Memory/instincts/global/prefer-explicit-errors.md` |
| Write mode | create |
| Source notes | `vault:06 Memory/instincts/project/a1b2c3d4e5f6/prefer-explicit-errors.md`; `vault:...` |
| Then set on source notes | `status: promoted`; `promoted_to: vault:06 Memory/instincts/global/prefer-explicit-errors.md` |

Text to write:

~~~~markdown
(the exact file content, or for retire the exact frontmatter lines)
~~~~
```

Every block carries: instinct id(s), confidence, evidence count, projects seen in, why it qualified, proposed destination, write mode, and the exact text in a `~~~~` fence. `vault:` paths are relative to `NEVA_VAULT`.

**Applying** (`instinct-cli.py apply-promotions`):

| Trigger | What is applied |
|---|---|
| Nightly job, or `apply-promotions` | only blocks with `- [x] approve` in every open proposal file |
| Human says "apply instinct promotions" | run `apply-promotions --all`: every open block not ticked `reject`. Report the counts and destinations afterwards. |
| `- [x] reject` | nothing written; the block id is recorded and never proposed again |
| both boxes ticked | error `block <id>: both approve and reject are ticked. Fix: untick one.` |

Rules the applier enforces:
- It writes exactly the fenced text. The human may edit the fence or the destination row before ticking; the edit wins.
- Destinations must be inside the vault, the user Claude config dir (`~/.claude` or `CLAUDE_CONFIG_DIR`), or a registered project's `.claude/`. Anything else fails with `destination ... is outside ... Fix: edit the 'Proposed destination' row`.
- `create` never overwrites: an existing different file fails with `destination exists: <path>. Fix: rename or remove it, or edit the 'Proposed destination' row.` An identical file counts as applied.
- Each resolved block gets a line `Applied YYYY-MM-DD to <destination>.` or `Rejected YYYY-MM-DD.`; failures get `Failed YYYY-MM-DD: <error>` and stay open for retry.
- When every block is resolved, the file's `status` becomes `done`. Proposal files are never deleted.
- Agents never tick boxes and never pass `--all` or `promote --apply` on their own. Only the human's tick, the human's words "apply instinct promotions", or the human explicitly asking for one named promotion in the conversation authorizes a write.

## Commands

The CLI is Python 3 (stdlib only): `python3 "${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/scripts/instinct-cli.py" <command>`.

| Command | What it does |
|---|---|
| `status` | Instincts for the current project plus global, grouped by domain; waiting observations; pending count and expiry warnings (5+ pending, or expiring within 7 days); open proposal files |
| `search <query> [--scope project\|global\|all] [--limit 20]` | Match id, trigger, domain, and body; highest confidence first; prints the note path |
| `stats` | UNIQUE, BY_SCOPE, BY_DOMAIN, BY_SOURCE, AVG_CONFIDENCE, PENDING, OBSERVATIONS_WAITING |
| `add --id --trigger --action [--domain] [--confidence 0.1-1 or 1-10] [--scope] [--files ...]` | Record a user-stated instinct (`source: user-stated`). The human asking is the approval, so `--scope global` is allowed here |
| `import <file\|https-url> [--scope] [--min-confidence] [--pending] [--dry-run] [--force]` | One note per instinct, `source: inherited`; keeps the higher confidence on id clashes; https only, public hosts only, 2 MB cap |
| `export [--scope] [--domain] [--min-confidence] [--format instincts\|claude-md] [-o file]` | Instinct bundle for sharing, or a `## Project Learnings` section for CLAUDE.md |
| `evolve [--propose] [--limit N] [--dry-run]` | Print skill, command, agent and promotion candidates; `--propose` files them as blocks |
| `promote [id] [--dry-run] [--apply]` | File promote-global blocks (all qualifying, or one id on request). `--apply` only when the human asked for that exact promotion |
| `propose [--limit N] [--dry-run]` | Everything in the proposal table above |
| `apply-promotions [--file PATH] [--all]` | Apply ticked blocks, or all open blocks |
| `decay [--dry-run] [--quiet]` | Weekly confidence decay |
| `projects [delete <id> \| merge <from> <into> \| gc] [--dry-run] [--force]` | Registry maintenance. Delete removes observations only and leaves the vault notes for the human; merge moves notes and appends observations |
| `prune [--max-age 30] [--dry-run] [--quiet]` | Delete pending instincts past their TTL |

Slash-command mapping: `/instinct-status` is `status`, `/evolve` is `evolve`, `/promote` is `promote`, `/projects` is `projects`, `/instinct-export` and `/instinct-import` are `export` and `import`, `/learn` is the Learnings Manager below.

## Learnings Manager (merged from gstack learn)

Use when the user asks "what have we learned", "show learnings", "prune stale learnings", "export learnings", or wonders "didn't we fix this before?".

- `/learn` (no arguments): run `status`; present the 20 highest-confidence instincts grouped by domain. If none exist: "No learnings recorded yet. They accumulate as the observe hook records sessions and the nightly job analyzes them."
- `/learn search <query>`: run `search`. Present id, trigger, action, confidence, note path.
- `/learn prune`: for each active instinct:
  1. **File existence check:** if it has `files:`, check each path still exists (Glob). Flag `STALE: <id> references deleted file <path>`.
  2. **Contradiction check:** find instincts with overlapping triggers and opposite actions. Flag `CONFLICT: <id-a> vs <id-b>: <action A> vs <action B>`.
  Present each flag and ask: A) retire it (set `status: archived` on the note, never delete), B) keep it, C) update it (the human says what changes; edit the note, append an Evidence bullet dated today). Never resolve a conflict by keeping the longer note: read both, keep the newer truth.
- `/learn export`: `export --format claude-md`; show it; ask whether to append it to CLAUDE.md or save it elsewhere. Writing to CLAUDE.md waits for that answer.
- `/learn stats`: run `stats`; present as a table.
- `/learn add`: ask for type (pattern / pitfall / preference / architecture / tool, mapped to a domain), a 2-5 word kebab-case key, the insight in one sentence, confidence 1-10, related files (optional). Then run `add`.

## Why Hooks, Not Skills, For Observation

Skills are probabilistic: they fire when the model judges them relevant, roughly half to most of the time. Hooks fire on every tool call, deterministically, so no pattern is missed. That is why observation lives in a hook and analysis in a scheduled job.

## Privacy

- Observations stay local, outside the vault, scrubbed of secret shapes, truncated, rotated at 10 MB, and deleted after 30 days in the archive.
- Instincts describe patterns, never code or conversation content.
- Only instincts can be exported, never raw observations.
- You control every promotion through the inbox.

## Related

- `continuous-learning` (v1) is retired: v2 is a strict superset. Its ignore list (simple typos, one-time fixes, external API issues) lives in `analyzer-prompt.md`.
- `growth-log`: human-written pattern entries; instincts are the machine-written counterpart.
- `rules-distill`: distills rules from skills; `rule` proposals here distill them from near-certain instincts.
- `skill-stocktake`, `config-gc`: audit what evolved skills and rules accumulate into.
- Homunculus, the community project that inspired the instinct architecture (atomic observations, confidence scoring, evolution pipeline).
