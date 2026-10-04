---
name: neva-guide
description: Use when someone asks what Neva includes, which plugin, skill, agent, command, or rule fits a task, how to install, enable, or reset a Neva plugin, or how the pieces relate. Answers from the live repo and install, never from memory.
metadata:
  origin: neva (adapted from ECC ecc-guide)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Neva Guide

Use this skill when a user needs help understanding, navigating, installing, or choosing parts of Neva.

## When To Use

Use this skill when the user:

- asks what Neva includes, or what a given plugin ships
- wants help finding a skill, command, agent, rule, context, or hook
- is new to the repository and needs a guided path
- asks "how do I do X with Neva?"
- asks which Neva plugins fit a project
- needs a lightweight explanation of how commands, skills, agents, hooks, and rules relate
- is confused by install paths, duplicate installs, enabling or disabling a plugin, or reset

## Core Principle

Answer from current files, not memory. Neva changes quickly, so hard-coded catalog counts, feature lists, and install instructions go stale.

When the Neva repository is available (the directory holding `.claude-plugin/marketplace.json`), inspect the relevant files before giving a concrete answer:

```bash
cat .claude-plugin/marketplace.json
find plugins -path '*/skills/*/SKILL.md' | sort
find plugins -path '*/agents/*.md' | sort
find plugins -path '*/commands/*.md' | sort
find plugins -path '*/rules/*' -name '*.md' | sort
```

When only the installed plugins are available, read them from the harness instead:

```bash
claude plugin list --json
claude plugin marketplace list --json
```

Use the smallest set of reads needed for the user's question.

## Repository Map

- `README.md`, `START.md`, `SETUP GUIDE.md`: what Neva is, first run, setup order
- `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`: contributor guidance and project structure
- `.claude-plugin/marketplace.json`: the plugin marketplace, one entry per plugin with its description
- `plugins/neva-core/`: process, memory, and learning core (plan, test, implement, review, verify, remember, improve). Always on.
- `plugins/neva-<name>/`: opt-in plugins (web, mobile, backend-langs, ops, business, media, domains)
- inside each plugin: `skills/<name>/SKILL.md` (workflows and playbooks), `agents/<name>.md` (delegated subagent roles), `commands/<name>.md` (slash commands), `rules/` (always-on guidance, language packs under `rules/<lang>/`), `contexts/` (core only), `hooks/` (Python hook runtime)
- `bin/`: operational tools (`doctor`, `diag-run`, `vault-sync`, `session-guard`, and others)
- `docs/`: numbered guides (first run, scheduled jobs, vault structure, security, configuration)
- `vault/`: the vault template the assistant reads and writes

## Response Style

Lead with the answer, then give the next action. Most users do not need a full catalog dump.

Good first response shape:

1. what to use
2. why it fits
3. exact file or command to inspect
4. one next command or question

Avoid:

- listing every skill or command by default
- repeating large README sections
- recommending a command when a skill is the primary workflow surface
- claiming a component exists without checking the filesystem
- telling users to copy plugin files by hand when the plugin installer supports the target

## Common Tasks

### New User Onboarding

Give a short menu:

- install, enable, or reset a Neva plugin
- pick plugins for a project
- understand commands vs skills vs agents
- inspect hooks and safety behavior
- run the health check (`bin/doctor`)
- find a specific workflow

Point to `SETUP GUIDE.md` for install order and to the `agent-sort` skill for a project-specific DAILY vs LIBRARY plan.

### Feature Discovery

For "what should I use for X?":

1. Search skills, commands, and agents across all plugins.
2. Prefer skills as the primary workflow surface.
3. Use commands only when the user explicitly wants slash-command behavior or a command wraps a skill.
4. Mention agents when delegation is useful.
5. Name the plugin that ships the match and whether it is installed.

Useful searches:

```bash
rg -n "<query>" plugins docs
find plugins -path '*/skills/*/SKILL.md' | xargs grep -l "<query>"
```

### Install Guidance

Use the plugin installer, never manual copies:

```bash
claude plugin marketplace add <path-or-git-url-of-the-neva-repo>
claude plugin install neva-core@neva
claude plugin install neva-web@neva        # only the plugins the project needs
claude plugin list --json                  # verify
```

`neva-core` is the base; every other plugin assumes it. Warn users not to stack a plugin install on top of hand-copied files in `~/.claude/skills` with the same names; the duplicate surface wastes context and makes behavior depend on load order.

### Project Onboarding

When the user wants Neva configured for a target repo, the expected sequence is:

1. detect the stack from project files
2. map the stack to plugins (the `agent-sort` skill produces the evidence-backed plan)
3. inspect existing `CLAUDE.md` and `.claude/settings*.json`
4. ask before installing or changing anything
5. keep generated guidance minimal and repo-specific

### Troubleshooting

Ask for the harness and install scope first, then inspect:

- `claude plugin list --json` (installed, enabled, version)
- the project `.claude/` directory and `~/.claude/settings.json` for disabled plugins or conflicting hooks
- the plugin's `hooks/` directory
- the relevant skill or command file

For assistant health, suggest `bin/doctor` (each FAIL row names its fix) and `bin/diag-run` for the weekly self-test.

## Output Templates

### Short Recommendation

```text
Use <skill-or-command> from <plugin>. It fits because <reason>.

Canonical file: <path>
Verify with: <command>
Next: <one concrete action>
```

### Search Results

```text
Best matches:
- <path>: <why it matters>
- <path>: <why it matters>

Recommendation: <which one to use first and why>
```

### Install Plan Summary

```text
Detected: <stack evidence>
Plugins: <neva-core + ...>
Install: <commands>
Would change: <paths>
Needs approval before apply: <yes/no>
```

## Related Surfaces

- `neva-recipes`: which command group runs a workflow, in what order, and when to stop
- `agent-sort`: evidence-backed DAILY vs LIBRARY plan for one repo
- `prompt-optimizer`: rewrite a draft prompt against the Neva catalogue
- `skill-stocktake`: skill quality review
- `security-scan`: inspect Claude Code configuration security
