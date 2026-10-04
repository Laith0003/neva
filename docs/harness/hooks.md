# Hooks

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

Neva's hooks live in the `neva-core` plugin: `plugins/neva-core/hooks/`. Python 3.9 or newer, standard library only. The canonical process they enforce is [process.md](../../plugins/neva-core/rules/process.md).

## How they run

- `hooks.json` registers each Claude Code event once. Tool events use matcher `*`, so one tool call starts one Python process per event, never one per rule.
- That process is `dispatch.py <Event>`. It reads the hook JSON, picks the modules from `hooks.meta.json` that listen on the event, match the tool name (`tools`, fnmatch patterns) and the active profile, and runs them in table order.
- Results merge: any `block` exits 2 with every reason; otherwise `ask` becomes `permissionDecision: ask`, `context` becomes `additionalContext`, and anything else a system message.
- A module that raises is logged to `~/.local/share/neva/hooks.log` and skipped. A hook error never breaks the session.

## Controls

| Variable | Default | Effect |
|---|---|---|
| `NEVA_HOOK_PROFILE` | `standard` | `minimal`, `standard` or `strict`; picks the modules in the table below |
| `NEVA_DISABLED_HOOKS` | unset | comma list of module ids to skip |
| `NEVA_HEADLESS` | unset | `1` makes every hook a no-op (set by tools that call `claude -p` themselves, including the nightly instinct job) |

Set them in the `env` block of your Claude Code settings.

## Modules

In run order. "Tools: all" means the module sees every tool call of that event and filters inside, or the event has no tool.

| Id | Events | Tools | Profiles | File | What it does |
|---|---|---|---|---|---|
| `session_start` | SessionStart | all | minimal, standard, strict | `session_start.py` | Inject strong instincts (canonical project/<id> and global folders), today's journal head, inbox open actions, open instinct proposals and the last session summary for this worktree or repo (8000 char cap); prune session files older than 30 days. |
| `ck_session_start` | SessionStart | all | standard, strict | `ck.py` | ck skill: record current-session.json and inject the project's saved goal, where it left off and next steps (or the 3 most recent ck projects). No-op when ck data does not exist. |
| `prompt_context` | UserPromptSubmit | all | standard, strict | `prompt_context.py` | Once per session: GOALS.md and project states when a prompt is about direction; the matching project note when the working directory is under its code path. |
| `hookify_prompt` | UserPromptSubmit | all | minimal, standard, strict | `hookify.py` | hookify rules with event prompt or all: warn with context or block the prompt. |
| `no_verify` | PreToolUse | Bash | minimal, standard, strict | `pre_bash.py` | Block git hook bypasses: --no-verify (and prefixes), commit -n clusters, -c core.hooksPath, git config core.hooksPath, HUSKY=0. |
| `safety_careful` | PreToolUse | Bash | minimal, standard, strict | `safety_guard.py` | safety-guard careful mode (on while <NEVA_STATE_DIR>/safety-guard/careful exists): ask before destructive commands. |
| `commit_quality` | PreToolUse | Bash | standard, strict | `pre_bash.py` | On git commit: block secret shapes and debugger statements in the staged diff; warn on console.log, possible hardcoded secrets and non-conventional messages. |
| `push_reminder` | PreToolUse | Bash | standard, strict | `pre_bash.py` | On git push: remind to check what will be published; flag shared branches and force pushes. |
| `tmux_dev` | PreToolUse | Bash | standard, strict | `pre_bash.py` | Dev server started in the foreground outside tmux: warn (standard) or block (strict), with the exact tmux command. run_in_background is allowed. |
| `vault_gate` | PreToolUse | Write, Edit, MultiEdit | minimal, standard, strict | `pre_write.py` | Writes into the vault outside NEVA_VAULT_WRITABLE folders ask the user first. |
| `safety_freeze` | PreToolUse | Write, Edit, MultiEdit | minimal, standard, strict | `safety_guard.py` | safety-guard freeze mode (on while <NEVA_STATE_DIR>/safety-guard/freeze-dir.txt names a directory): deny edits outside it. |
| `config_protection` | PreToolUse | Write, Edit, MultiEdit | standard, strict | `pre_write.py` | Block edits that loosen lint, format or type configs: rules turned off or to warn, strict flags off, new ignores or excludes, removed rules, lowered levels. |
| `doc_file_warning` | PreToolUse | Write, Edit, MultiEdit | standard, strict | `pre_write.py` | Warn on ad-hoc NOTES/TODO/SCRATCH style files outside structured doc folders. |
| `gateguard` | PreToolUse | Write, Edit, MultiEdit | strict | `gateguard.py` | GateGuard first-edit gate: deny the first Edit, Write or MultiEdit of each file until the model lists importers or callers, affected API, data shapes and the user's instruction verbatim; the retry passes. |
| `suggest_compact` | PreToolUse | Write, Edit, MultiEdit | standard, strict | `pre_write.py` | strategic-compact nudge: context size from the transcript (160k of a 200k window, 800k of a 1M window, then every 60k more); edit-count fallback at 50 then every 25 when no usage is recorded yet. |
| `hookify_pre_tool` | PreToolUse | Bash, Write, Edit, MultiEdit | minimal, standard, strict | `hookify.py` | hookify rules from .claude/hookify.*.local.md with event bash, file or all: warn with context or block the call. |
| `mcp_health` | PreToolUse, PostToolUse, PostToolUseFailure | mcp__* | minimal, standard, strict | `mcp_health.py` | Mark an MCP server unhealthy after a transport, auth, rate-limit or availability failure and block calls to it until its backoff passes. Runs for mcp__* tools only. |
| `observe` | PreToolUse, PostToolUse, PostToolUseFailure | all | standard, strict | `observe.py` | continuous-learning-v2 observation hook: append scrubbed, truncated tool events (with `path` on tool_start) to <observations dir>/<project-id>/observations.jsonl for the nightly instinct analyzer. NEVA_SKIP_OBSERVE=1 skips. |
| `edit_accumulator` | PostToolUse | Write, Edit, MultiEdit, NotebookEdit | standard, strict | `observe.py` | Remember files edited this response for the Stop format and typecheck pass. |
| `pre_compact` | PreCompact | all | standard, strict | `pre_compact.py` | Write the summary block into the session file and one line into today's journal log before compaction. |
| `plan_canvas_pending` | Stop | all | minimal, standard, strict | `plan_canvas.py` | plan-canvas: block the stop while canvas feedback is queued with no listener, and hand over up to 20 items. Allows on any error. |
| `session_summary` | Stop | all | standard, strict | `stop.py` | Refresh the per-session summary between NEVA:SUMMARY markers in the session file. |
| `cost_tracker` | Stop | all | standard, strict | `stop.py` | Append a cumulative cost snapshot to <NEVA_METRICS_DIR>/costs.jsonl (default ~/.local/share/neva/metrics) when transcript usage changed. |
| `format_typecheck` | Stop | all | standard, strict | `stop.py` | Once per response, format edited files with the project's own biome, prettier, pint or ruff; strict also runs tsc and feeds errors back once. |
| `hookify_stop` | Stop | all | minimal, standard, strict | `hookify.py` | hookify rules with event stop or all: warn, or refuse the stop once (never twice in a row). |
| `delivery_gate` | Stop | all | strict | `delivery_gate.py` | delivery-gate: block on critical disk space or on a complex task without learning capture; warn on rationalization phrases. |
| `journal_nudge` | Stop | all | standard, strict | `stop.py` | Once per session, block the stop when 5 or more tool calls ran and nothing was written to the journal. |
| `notify` | Stop | all | standard, strict | `stop.py` | Optional macOS notification when a response is ready. Off unless NEVA_NOTIFY=1. |
| `session_audit` | SessionEnd | all | minimal, standard, strict | `session_end.py` | One audit line per session id in today's journal log, updated in place on resume. |

## Environment by module

| Module | Variables (default) |
|---|---|
| paths, every module | `NEVA_DATA_DIR` (`~/.local/share/neva`), `NEVA_STATE_DIR` (`~/.local/state/neva`), `NEVA_VAULT` (else `VAULT_PATH` in `NEVA_CONFIG`, default `~/.config/neva/identity.env`), `NEVA_TIMEZONE`, `NEVA_DAY_ROLLOVER_HOUR` (0) |
| journal (`session_start`, `pre_compact`, `journal_nudge`, `session_audit`) | `NEVA_JOURNAL_PATTERN` (`08 Journal/{date}.md`), `NEVA_JOURNAL_TEMPLATE` (`Templates/Daily Note.md`), `NEVA_JOURNAL_LOG_HEADING` (`## Log`), `NEVA_JOURNAL_NUDGE_MIN_TOOLS` (5) |
| inbox (`session_start`, instinct proposals) | `NEVA_INBOX` (`00 Inbox/inbox.md`, else a root `inbox.md` when only that exists), `NEVA_INBOX_SECTION` (`Open actions`), `NEVA_PROPOSALS_DIR` (the inbox note's folder) |
| `session_start` | `NEVA_SESSION_START_CONTEXT` (on), `NEVA_SESSION_START_MAX_CHARS` (8000), `NEVA_SESSION_RETENTION_DAYS` (30, `off` keeps files), `NEVA_INSTINCT_MIN_CONFIDENCE` (0.7), `NEVA_INSTINCT_MAX` (6), `COMPACT_STATE_TTL_DAYS` (14) |
| `ck_session_start` | `NEVA_CK_HOME` (`~/.local/share/neva/ck`) |
| `prompt_context` | `NEVA_GOALS_FILE`, `NEVA_PROJECTS_DIR`, `NEVA_STRATEGY_KEYWORDS` |
| `hookify_*` | rule files in the nearest `.claude/` folder and `CLAUDE_PROJECT_DIR/.claude` |
| `safety_careful`, `safety_freeze` | state files `<NEVA_STATE_DIR>/safety-guard/careful` and `freeze-dir.txt`; log `<NEVA_STATE_DIR>/safety-guard.log` |
| `vault_gate` | `NEVA_VAULT_WRITABLE` (`08 Journal,00 Inbox,06 Memory,09 Reviews,inbox.md`) |
| `gateguard` | `NEVA_GATEGUARD`, `GATEGUARD_DISABLED`, `GATEGUARD_EXEMPT_GLOBS`, `GATEGUARD_FACT_FORCE_FULL_DENIALS` (3), `GATEGUARD_STATE_DIR` (`<NEVA_STATE_DIR>/gateguard`) |
| `suggest_compact` | `COMPACT_CONTEXT_THRESHOLD` (160000 on 200k, 800000 on 1M), `COMPACT_CONTEXT_INTERVAL` (60000), `COMPACT_THRESHOLD` (50), `NEVA_CONTEXT_WINDOW_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW` |
| `mcp_health` | `NEVA_MCP_HEALTH_BACKOFF_MS`, `NEVA_MCP_HEALTH_MAX_BACKOFF_MS`, `NEVA_MCP_HEALTH_FAIL_OPEN` |
| `observe` | `NEVA_OBSERVATIONS_DIR` (`<data dir>/observations`), `NEVA_SKIP_OBSERVE`, `NEVA_OBSERVE_SKIP_PATHS` (`observer-sessions,.claude-mem`), `NEVA_OBSERVE_MAX_MB` (10), `CLAUDE_CODE_ENTRYPOINT`, `NEVA_NO_PROJECT` |
| `cost_tracker` | `NEVA_METRICS_DIR` (`<data dir>/metrics`) |
| `format_typecheck` | `NEVA_FORMAT_BUDGET_S` (240) |
| `plan_canvas_pending` | `NEVA_PLAN_CANVAS_STATE_DIR` (`<NEVA_STATE_DIR>/plan-canvas`), `NEVA_PLAN_CANVAS_STOP_SCOPE` (`all` widens past the working directory) |
| `delivery_gate` | `NEVA_MEMORY_DIR`, `NEVA_DELIVERY_DISK_REMIND_GB` (50), `NEVA_DELIVERY_DISK_WARN_GB` (30), `NEVA_DELIVERY_DISK_CRIT_GB` (15), `NEVA_DELIVERY_GATE_EXTENDED` |
| `notify` | `NEVA_NOTIFY` (off) |

## Files the hooks write

| Path | Written by | Pruned |
|---|---|---|
| `~/.local/share/neva/sessions/*-session.tmp` | `session_summary`, `pre_compact` | after 30 days |
| `~/.local/share/neva/observations/<project-id>/observations.jsonl` | `observe` | rotated at 10 MB; archives after 30 days |
| `~/.local/share/neva/observations/projects.json` | `observe` (and the instinct CLI) | never |
| `~/.local/share/neva/metrics/costs.jsonl` | `cost_tracker` | never |
| `~/.local/share/neva/hooks.log` | dispatcher | rotated at 1 MB |
| `~/.local/state/neva/hooks/` | per-session counters and markers | after `COMPACT_STATE_TTL_DAYS` |
| `~/.local/state/neva/gateguard/<session>.json` | `gateguard` | never (small) |
| `~/.local/state/neva/safety-guard.log` | `safety_careful`, `safety_freeze` | never |
| vault journal, inbox | `session_audit`, `pre_compact`, journal nudges | never |

## Tests

```bash
python3 plugins/neva-core/hooks/tests/test_hooks.py
python3 -m pytest plugins/neva-core/skills/continuous-learning-v2/scripts/test_instinct_cli.py
```

The hook suite runs every module end to end against a copied plugin, a temporary home and vault, and realistic hook JSON, including the instinct round trip: observe, nightly analysis with a fake `claude`, instinct note, session start injection, proposal, approval.
