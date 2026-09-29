---
description: "Create hooks to prevent unwanted behaviors from conversation analysis or explicit instructions"
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

Create hook rules to prevent unwanted Claude Code behaviors by analyzing conversation patterns or explicit user instructions.

## Usage

`/hookify [description of behavior to prevent]`

If no arguments are provided, analyze the current conversation to find behaviors worth preventing.

## Workflow

### Step 1: Gather Behavior Info

- With arguments: parse the user's description of the unwanted behavior
- Without arguments: use the `neva-core:conversation-analyzer` agent to find:
  - explicit corrections
  - frustrated reactions to repeated mistakes
  - reverted changes
  - repeated similar issues

### Step 2: Present Findings

Show the user:

- behavior description
- proposed event type
- proposed pattern or matcher
- proposed action

### Step 3: Generate Rule Files

For each approved rule, create a file at `.claude/hookify.{name}.local.md`:

```yaml
---
name: rule-name
enabled: true
event: bash|file|stop|prompt|all
action: block|warn
pattern: "regex pattern"
---
Message shown when rule triggers.
```

### Step 4: Confirm

Report created rules and how to manage them with `/hookify-list` and `/hookify-configure`.

## Enforcement

The neva-core hook runtime reads `.claude/hookify.*.local.md` on every matching event (modules `hookify_pre_tool`, `hookify_prompt`, `hookify_stop`, every profile). Changes apply on the next tool call, no restart. If the user runs without neva-core's hooks, or disabled those ids in `NEVA_DISABLED_HOOKS`, rules are inert: say so when creating or toggling them. A malformed rule is reported once per session and skipped, never enforced.
