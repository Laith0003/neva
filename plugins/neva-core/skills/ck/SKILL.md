---
name: ck
description: "Use when work must survive across sessions or branches: saving where you left off, next steps, decisions and blockers (/ck:save), resuming a project without re-explaining it (/ck:resume, 'where was I'), listing projects, or before a /compact."
metadata:
  version: 2.0.0-neva
  origin: neva (adapted from ECC, community skill by sreedhargs89/context-keeper)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with garrytan/gstack context-save and context-restore (MIT, Garry Tan). -->

# ck: Context Keeper

Persistent per-project memory driven by deterministic Node.js scripts. You are the **Context Keeper**: when the user invokes any `/ck:*` command, run the matching script and present its stdout verbatim. Only `/ck:save` needs your judgment.

requires: node (stdlib only, no packages)

Scripts: `${CLAUDE_PLUGIN_ROOT}/skills/ck/commands/<name>.mjs`. Set `CK="${CLAUDE_PLUGIN_ROOT}/skills/ck/commands"` once per Bash call.

**HARD GATE:** ck never modifies code. It reads git state and writes context files only.

## Data Layout

```
${NEVA_CK_HOME:-${XDG_DATA_HOME:-~/.local/share}/neva/ck}/
+-- projects.json              path -> {name, contextDir, lastUpdated}
+-- current-session.json       written by the SessionStart hook: {sessionId, projectPath, projectName, startedAt}
+-- contexts/<name>/
    +-- context.json           SOURCE OF TRUTH (structured JSON, v2)
    +-- CONTEXT.md             generated view, do not hand-edit
```

Every save also writes a native auto-memory note `ck_<date>_<session8>.md` into the Claude Code project memory dir (`~/.claude/projects/<encoded-path>/memory/`, or under `CLAUDE_CONFIG_DIR`). A failure there is a warning, never a failed save.

`context.json` keeps a `sessions` array that only grows: each save appends one session (a re-save of the same session id replaces its own entry). Each session records `id, date, summary, leftOff, nextSteps[], decisions[{what, why}], blockers[], notes[], gitActivity, branch, filesModified[]`. Branch and modified files are captured by the script from git, never typed by you.

## Commands

### `/ck:init`: register a project

```bash
node "$CK/init.mjs"
```

The script prints JSON with auto-detected info. Present it as a confirmation draft:

```
Here's what I found. Confirm or edit anything:
Project:     <name>
Description: <description>
Stack:       <stack>
Goal:        <goal>
Do-nots:     <constraints or "None">
Repo:        <repo or "none">
```

Wait for approval. Apply edits. Then pipe the confirmed JSON through a quoted heredoc (never `echo '<json>'`: a quote inside the JSON would break out of the shell string):

```bash
node "$CK/save.mjs" --init <<'CK_JSON'
{"name":"...","path":"...","description":"...","stack":["..."],"goal":"...","constraints":["..."],"repo":"..."}
CK_JSON
```

### `/ck:save`: save session state

The only command that needs LLM analysis.

**Step 1: gather state** (from gstack context-save):

```bash
echo "=== BRANCH ==="; git rev-parse --abbrev-ref HEAD 2>/dev/null
echo "=== STATUS ==="; git status --short 2>/dev/null
echo "=== DIFF STAT ==="; git diff --stat 2>/dev/null
echo "=== STAGED DIFF STAT ==="; git diff --cached --stat 2>/dev/null
echo "=== RECENT LOG ==="; git log --oneline -10 2>/dev/null
```

**Step 2: analyze** the conversation plus that state:
- `summary`: one sentence, max 10 words, what was accomplished
- `leftOff`: what was actively being worked on (specific file, feature, or bug)
- `nextSteps`: ordered array of concrete next steps, in priority order
- `decisions`: array of `{what, why}` for architectural choices and trade-offs made this session
- `blockers`: array of current blockers (empty array if none)
- `notes`: gotchas, open questions, things tried that did not work (empty array if none)
- `goal`: updated goal string **only if it changed this session**, else omit

Infer, do not interrogate: fill every field from git state and the conversation. Ask only if the summary genuinely cannot be inferred.

**Step 3: confirm.** Show a draft: `Session: '<summary>'. Save this? (yes / edit)`. Wait for the answer.

**Step 4: save.**

```bash
node "$CK/save.mjs" <<'CK_JSON'
{"summary":"...","leftOff":"...","nextSteps":["..."],"decisions":[{"what":"...","why":"..."}],"blockers":["..."],"notes":["..."]}
CK_JSON
```

Display the script's stdout confirmation verbatim. If the directory is not registered, the script says so: run `/ck:init` first.

### `/ck:resume [name|number]`: full briefing

```bash
node "$CK/resume.mjs" [arg]
```

Display output verbatim. Resume works **across branches** by default (the whole point of a handoff); when the saved branch differs from the current one, the script prints a `NOTE` naming both, and you repeat it. Then ask: "Continue from here? Or has anything changed?" If the user reports changes, run `/ck:save` immediately. If they continue, start with the first next step.

### `/ck:info [name|number]`: quick snapshot

```bash
node "$CK/info.mjs" [arg]
```

Display output verbatim. No follow-up question.

### `/ck:list`: portfolio view

```bash
node "$CK/list.mjs"
```

Display output verbatim. If the user replies with a number or name, run `/ck:resume`. Staleness markers: filled circle active today, half circle within 5 days, empty circle older.

### `/ck:forget [name|number]`: remove a project

Resolve the name first (run `/ck:list` if needed). Ask: `This will permanently delete context for '<name>'. Are you sure? (yes/no)`. Only on yes:

```bash
node "$CK/forget.mjs" [name]
```

This is the only command that deletes. Display the confirmation verbatim.

### `/ck:migrate`: convert v1 data to v2

```bash
node "$CK/migrate.mjs" --dry-run
node "$CK/migrate.mjs"
```

Run the dry run first. Migrates v1 `CONTEXT.md` + `meta.json` files to v2 `context.json`; originals are backed up as `meta.json.v1-backup`, nothing is deleted.

## SessionStart Hook

Implemented by the `ck_session_start` module of the neva-core hook runtime (`hooks/neva_hooks/ck.py`; profiles standard and strict; disable with `NEVA_DISABLED_HOOKS=ck_session_start`). It does nothing when the ck data folder does not exist, and never creates it.

| Item | Behavior |
|---|---|
| Event | `SessionStart` (startup, resume, clear, compact) |
| Input | hook JSON `session_id` and `cwd` |
| Before anything | read the previous `current-session.json`, then overwrite it with `{sessionId, projectPath, projectName, startedAt}` (`/ck:save` uses this id so a re-save updates the same session) |
| Registered project | `ck: <name> \| <N days ago> \| <N> sessions`, `Goal: ...`, `Left off: <first line>`, `Next: <first two steps joined by " \| ">` |
| Unsaved-session warning | the previous session was in this project, its id differs from the new one and is not in `sessions`: `WARNING Last session wasn't saved. Run /ck:save to capture it` |
| Git activity | `git log --oneline --since=<last session date>` count: `Git: N commits since last session` |
| Goal mismatch | first line under `## Current Goal` in the repo's CLAUDE.md differs (case-insensitive) from the saved goal: `WARNING Goal mismatch: ... Run /ck:save with updated goal to sync` |
| Unregistered directory | a table of the 3 most recent projects (name, active / warm / stale, last seen, last summary) and `Run /ck:list, /ck:resume <name>, or /ck:init to register this folder` |
| Output | additionalContext with that block only (about 100 tokens; this SKILL.md is not injected). When a WARNING line is present it asks for a one-sentence mention in the first reply |
| Failure | never blocks; errors go to the hook log |

## Rules

- Always expand `~` as `$HOME` in Bash calls.
- Commands are case-insensitive: `/CK:SAVE`, `/ck:save`, `/Ck:Save` all work.
- If a script exits 1, show its stdout as the error message.
- Never edit `context.json` or `CONTEXT.md` directly. Always use the scripts.
- If `projects.json` is malformed, tell the user and offer to reset it to `{}`.
- Pass JSON only through a quoted heredoc (`<<'CK_JSON'`). Never build shell strings from user-supplied titles or text.
- Before a `/compact` at a phase boundary (see `strategic-compact`), run `/ck:save` first.

## Related

- `strategic-compact`: when to compact; save with ck first.
- `unified-memory`: handoffs between different agents or harnesses, kept in the vault.
- `continuous-learning-v2`: learned behaviors across sessions, as opposed to where a task stands.
