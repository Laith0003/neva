---
name: autonomous-agent-harness
description: Use when the user wants an agent that runs on a schedule, keeps a task queue across sessions, or acts on its own between conversations. Sets up Neva memory, launchd/systemd timers, headless dispatch, and computer use with explicit consent gates.
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Autonomous Agent Harness

Combine Claude Code's session tools with Neva's scheduled jobs, vault memory, and separately configured computer-use integrations. This is a setup pattern, not a bundled always-on runtime.

## Consent and Safety Boundaries

Autonomous operation must be explicitly requested and scoped by the user. Do not create schedules, dispatch remote agents, write persistent memory, use computer control, post externally, modify third-party resources, or act on private communications unless the user has approved that capability and the target workspace for the current setup.

Prefer dry-run plans and local queue files before enabling recurring or event-driven actions. Keep credentials, private workspace exports, personal datasets, and account-specific automations out of reusable Neva artifacts.

Anything that leaves the machine (a PR comment, a message, an email, a post) follows the send gate: a scheduled run drafts it and files a proposal in `$NEVA_VAULT/00 Inbox/`; a human approves each send. A schedule never carries a standing yes for sends, money, deletions, or credential changes.

## When to Activate

- User wants an agent that runs continuously or on a schedule
- Setting up automated workflows that trigger periodically
- Building a personal AI assistant that remembers context across sessions
- User says "run this every day", "check on this regularly", "keep monitoring"
- Wants to replicate functionality from Hermes, AutoGPT, or similar autonomous agent frameworks
- Needs computer use combined with scheduled execution

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Claude Code Runtime                        │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ Timers   │  │ Dispatch │  │ Memory   │  │ Computer    │ │
│  │ launchd/ │  │ Headless │  │ Vault    │  │ Use         │ │
│  │ systemd  │  │ claude -p│  │          │  │             │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬──────┘ │
│       │              │             │                │        │
│       ▼              ▼             ▼                ▼        │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              Neva Plugin Layer                        │    │
│  │                                                      │    │
│  │  skills/     agents/     commands/     hooks/        │    │
│  └──────────────────────────────────────────────────────┘    │
│       │              │             │                │        │
│       ▼              ▼             ▼                ▼        │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              MCP Server Layer                        │    │
│  │                                                      │    │
│  │  memory    github    exa    supabase    browser-use  │    │
│  └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

## Neva Paths

| What | Where |
|------|-------|
| Vault root | `$NEVA_VAULT` (from env, never hardcoded) |
| Agent memory | `$NEVA_VAULT/06 Memory/` (markdown with frontmatter) |
| Instincts | `$NEVA_VAULT/06 Memory/instincts/{project,global}/` |
| Human-review proposals | `$NEVA_VAULT/00 Inbox/` (one proposal block file each) |
| Session transcripts | `~/.local/share/neva/sessions` |
| Observations | `~/.local/share/neva/observations/` |
| State, logs, heartbeats | `~/.local/state/neva/` (heartbeats in `heartbeat/<job>.status`) |
| Rendered job templates | `~/.local/neva/services/` |

## Core Components

### 1. Persistent Memory

Neva's memory is the vault. The agent writes its own distillations to `$NEVA_VAULT/06 Memory/` and reads them back by search, not by loading everything at session start. An MCP memory server is optional, for structured graph data.

**Vault memory** (`$NEVA_VAULT/06 Memory/`):
- Preferences, feedback, project context, what the agent is watching
- Markdown files with frontmatter, one fact per note, indexed by a one-line entry
- Every note traceable to a source note elsewhere in the vault

**MCP memory server** (structured knowledge graph, optional):
- Entities, relations, observations
- Queryable graph structure
- Cross-session persistence

**Memory patterns:**

```
# Short-term: current session context
Use TodoWrite for in-session task tracking

# Medium-term: vault memory files
Write to "$NEVA_VAULT/06 Memory/" for cross-session recall

# Long-term: learned behavior
Write instincts to "$NEVA_VAULT/06 Memory/instincts/{project,global}/"

# Optional structured graph (MCP memory server)
Use mcp__memory__create_entities for permanent structured data
Use mcp__memory__create_relations for relationship mapping
Use mcp__memory__add_observations for new facts about known entities
```

### 2. Scheduled Operations

Two kinds of schedule, for two jobs:

- **In-session polling:** Claude Code's native [scheduled tasks](https://code.claude.com/docs/en/scheduled-tasks) (`/loop`) run recurring prompts inside an open interactive session and stop when it closes. No scheduling MCP server is required.
- **Work that must run with no session open:** a Neva scheduled job. Neva runs these as launchd agents on macOS and systemd user timers on Linux. Every job runs through `heartbeat-wrap.sh`, which appends `<ISO8601 UTC> <exit code> <duration seconds>` to `~/.local/state/neva/heartbeat/<job>.status` on every run and enforces a timeout, so a job that is loaded but has never fired is detectable.

**In-session:**

```
/loop 30m Review open PRs in this repository and summarize CI failures.
```

**One-shot headless run** (what a scheduled job executes). Set the working directory in the scheduler; the CLI has no `--cwd` flag:

```bash
cd "/path/to/repo" && claude -p "Review open PRs and summarize"
```

**A Neva scheduled job** is a template pair rendered into `~/.local/neva/services/`:

```xml
<!-- com.neva.pr-digest.plist (macOS) -->
<plist version="1.0"><dict>
  <key>Label</key><string>com.neva.pr-digest</string>
  <key>WorkingDirectory</key><string>/path/to/repo</string>
  <key>ProgramArguments</key><array>
    <string>@PREFIX@/services/heartbeat-wrap.sh</string><string>pr-digest</string>
    <string>/usr/local/bin/claude</string><string>-p</string><string>Review open PRs and summarize CI failures. Write the digest to the vault. Do not post.</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardErrorPath</key><string>@HOME@/.local/state/neva/pr-digest.err.log</string>
</dict></plist>
```

```ini
# neva-pr-digest.service (Linux)
[Unit]
Description=PR digest
[Service]
Type=oneshot
WorkingDirectory=/path/to/repo
ExecStart=@PREFIX@/services/heartbeat-wrap.sh pr-digest /usr/local/bin/claude -p "Review open PRs and summarize CI failures. Write the digest to the vault. Do not post."

# neva-pr-digest.timer (Linux)
[Timer]
OnCalendar=Mon *-*-* 09:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

Keep the two platforms in step: a launchd `StartCalendarInterval` without `Weekday` fires daily even when the systemd twin is weekly.

Enable one job at a time and watch it fire once before adding the next:
- macOS: `cp ~/.local/neva/services/com.neva.<name>.plist ~/Library/LaunchAgents/ && launchctl load -w ~/Library/LaunchAgents/com.neva.<name>.plist`
- Linux: `cp ~/.local/neva/services/neva-<name>.{service,timer} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now neva-<name>.timer`

Remove:
- macOS: `launchctl bootout gui/$(id -u)/com.neva.<name>` then `rm -f ~/Library/LaunchAgents/com.neva.<name>.plist`. `unload` alone can race a job that is mid-fire. Confirm with `launchctl list | grep neva`.
- Linux: `systemctl --user disable --now neva-<name>.timer && rm -f ~/.config/systemd/user/neva-<name>.{service,timer} && systemctl --user daemon-reload`

When testing a repo rather than installing, set `NEVA_SKIP_SCHEDULE_ENABLE=1`: `launchctl load` and `systemctl --user enable` register against the real logged-in session even when `$HOME` is overridden.

Configure the runner's authentication and tool permissions separately; a headless run cannot answer a permission prompt.

**Useful schedule patterns:**

| Pattern | Schedule (cron notation) | Use Case |
|---------|----------|----------|
| Daily standup | `0 9 * * 1-5` | Review PRs, issues, deploy status |
| Weekly review | `0 10 * * 1` | Code quality metrics, test coverage |
| Hourly monitor | `0 * * * *` | Production health, error rate checks |
| Nightly build | `0 2 * * *` | Run full test suite, security scan |
| Pre-meeting | `*/30 * * * *` | Prepare context for upcoming meetings |

Translate cron notation into `StartCalendarInterval` (launchd) and `OnCalendar` (systemd); `*/30` becomes `StartInterval` 1800 on launchd and `OnCalendar=*:0/30` on systemd.

### 3. Dispatch / Remote Agents

Have an authenticated CI job or webhook receiver invoke Claude Code in a workspace it owns. The supported entrypoint is [programmatic CLI mode](https://code.claude.com/docs/en/headless), not a public Anthropic dispatch endpoint.

**Dispatch patterns:**

```bash
# Run inside the CI workspace
cd "/path/to/repo" && claude -p "Build failed on main. Diagnose the failure."

# Trigger from webhook
# GitHub webhook -> authenticated CI runner -> claude -p -> reviewable result

# Trigger from another agent
claude -p "Analyze the output of the security scan and create issues for findings"
```

Creating issues is an outward action: file the drafts to `$NEVA_VAULT/00 Inbox/` for approval unless the user granted that exact action for that exact repo.

### 4. Computer Use

Computer control needs a separately configured integration. Anthropic's [computer-use tool and reference environment](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool) require an application to execute tool calls in an isolated desktop environment. Adding an MCP package name does not supply that environment.

**Capabilities:**
- Browser automation (navigate, click, fill forms, screenshot)
- Desktop control (open apps, type, mouse control)
- File system operations beyond CLI

**Use cases within the harness:**
- Automated testing of web UIs
- Form filling and data entry
- Screenshot-based monitoring
- Multi-app workflows

### 5. Task Queue

Manage a persistent queue of tasks that survive session boundaries.

**Implementation:**

```
# Task persistence via vault memory
Write task queue to "$NEVA_VAULT/06 Memory/task-queue.md"

# Task format
---
name: task-queue
type: project
description: Persistent task queue for autonomous operation
---

## Active Tasks
- [ ] PR #123: Review and draft approval if CI green (approval posted by a human)
- [ ] Monitor deploy: check /health every 30 min for 2 hours
- [ ] Research: Find 5 leads in AI tooling space

## Completed
- [x] Daily standup: reviewed 3 PRs, 2 issues
```

After a session reset, read the queue first; an item not marked done is the standing brief. Write each result into the queue before reporting it, so the next session inherits the outcome and not just the plan.

## Replacing Hermes

| Hermes Component | Neva Equivalent | How |
|------------------|---------------|-----|
| Gateway/Router | CLI + launchd/systemd timers | A heartbeat-wrapped job starts agent sessions |
| Memory System | Vault memory + optional MCP memory server | `$NEVA_VAULT/06 Memory/` plus knowledge graph |
| Tool Registry | MCP servers | Dynamically loaded tool providers |
| Orchestration | Neva plugin skills + agents | Skill definitions direct agent behavior |
| Computer Use | Separately configured integration | Browser or desktop control in an isolated environment |
| Context Manager | Sessions + memory | `~/.local/share/neva/sessions`, rotated before long-context degradation |
| Task Queue | Vault-persisted task list | TodoWrite + `task-queue.md` |

## Setup Guide

### Step 1: Configure MCP Servers

Memory MCP is optional; the vault is Neva's primary memory. The [MCP reference memory server](https://github.com/modelcontextprotocol/servers/tree/main/src/memory) is published as `@modelcontextprotocol/server-memory`; version `2026.8.31` was verified on the public npm registry on 2026-09-07. It is a reference implementation, not bundled with Neva.

After reviewing that package and approving its use, merge this entry into Claude Code's user-scoped MCP configuration (`~/.claude.json`), preserving existing settings. Replace `MEMORY_FILE_PATH` with an absolute path in a private directory you own, for example under `~/.local/state/neva/`. See [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp) for CLI registration and Windows `cmd /c npx` configuration.

```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory@2026.8.31"],
      "env": {
        "MEMORY_FILE_PATH": "/absolute/path/to/private/memory.jsonl"
      }
    }
  }
}
```

Do not register guessed or unpublished npm packages: `npx -y` would execute whatever is later published under that name. Verify the exact package, publisher, and version before adding another server. Scheduling and computer use do not require any additional package.

### Step 2: Create Base Schedules

For polling during an interactive session, enter:

```text
/loop 30m Review open PRs in this repository and summarize CI failures.
```

For daily or weekly work that must survive a closed session, add a Neva scheduled job (Core Components, section 2) that runs the one-shot headless command. Calling `claude -p` to request a schedule does not provision an always-on scheduler. Choose the schedule, workspace, and allowed actions explicitly before enabling it, and confirm the first heartbeat line lands in `~/.local/state/neva/heartbeat/<job>.status`.

### Step 3: Initialize Memory

```bash
# Seed the agent's view of priorities from the vault, not from guesses
claude -p "Read the vault's project and goals notes. Write a short note to \"$NEVA_VAULT/06 Memory/\" listing current priorities, each linked to the note it came from."
```

If you enabled the MCP graph, mirror the same entities there; the vault note stays the source of truth.

### Step 4: Enable Computer Use (Optional)

Follow the computer-use reference environment linked above, or the documentation for a specific browser integration you have reviewed. Grant only the required permissions and verify a harmless action in the isolated environment before adding it to scheduled workflows.

## Example Workflows

### Autonomous PR Reviewer
```
Schedule: every 30 min during work hours
1. Check for new PRs on watched repos
2. For each new PR:
   - Pull branch locally
   - Run tests
   - Review changes with code-reviewer agent
   - Draft review comments; file them to "$NEVA_VAULT/00 Inbox/" for approval before posting via GitHub MCP
3. Update memory with review status
```

### Personal Research Agent
```
Schedule: daily at 6 AM
1. Check saved search queries in memory
2. Run Exa searches for each query
3. Summarize new findings
4. Compare against yesterday's results
5. Write digest to memory
6. Flag high-priority items for morning review
```

### Meeting Prep Agent
```
Trigger: 30 min before each calendar event
1. Read calendar event details
2. Search memory for context on attendees
3. Pull recent email/Slack threads with attendees
4. Prepare talking points and agenda suggestions
5. Write prep doc to memory
```

## Constraints

- Native scheduled prompts share their interactive session. Scheduled job invocations start separate sessions unless explicitly resumed.
- Computer use requires explicit permission grants. Don't assume access.
- CLI automation still consumes model usage and is subject to the configured provider's limits. Choose appropriate scheduler intervals.
- Memory files should be kept concise. Archive old data rather than letting files grow unbounded.
- Always verify that scheduled jobs completed successfully. "Loaded" is not "ran": check the heartbeat file, and add error handling to scheduled prompts.
- A scheduled job never sends, pays, deletes, or changes credentials on its own. It drafts and files a proposal.
