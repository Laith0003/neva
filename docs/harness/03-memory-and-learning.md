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
2. A nightly job (`instinct-analyze`, 03:30, launchd or systemd timer rendered by `install.sh`, not a daemon) takes every project with at least 20 new observations, samples the newest 500 lines, and asks a small model to write project-scoped instinct notes. A run counts only when the model prints the exact completion record; then the analyzed lines move to the archive. On any failure the observations stay for the next night.
3. The same job decays confidence by 0.02 per week without observation, prunes pending instincts older than 30 days, and files proposals: promote to global, evolve into a skill, command or agent, become a rule, or retire.
4. Nothing leaves project scope and nothing becomes a skill, command, agent or rule until you tick `approve` in the proposal file or say "apply instinct promotions".

| Job setting | Default |
|------------------|---------|
| schedule | nightly, 03:30 (not enabled until you enable it) |
| minimum new observations before analysis | 20 (`NEVA_INSTINCT_MIN_OBSERVATIONS`) |
| lines sampled per project | 500 |
| model | haiku (`NEVA_INSTINCT_MODEL`) |
| timeout per project | 120 s |

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
