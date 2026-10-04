# Harness philosophy

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->
Source: distilled from Affaan Mustafa's Everything Claude Code guides (the shortform and longform guides, and SOUL.md).

This is what the Neva harness believes about how an agent should work. Each belief below is a rule, a reason, and the mechanics that enforce it. The canonical, step-by-step process lives in [process.md](../../plugins/neva-core/rules/process.md). This page explains why that process looks the way it does.

## The eight beliefs

| # | Belief | One line |
|---|--------|----------|
| 1 | Agent-first | Route work to the right specialist as early as possible. |
| 2 | Research before code | Search for a proven solution before writing a new one. |
| 3 | Plan as artifact | A plan is a file on disk, not a thought in context. |
| 4 | Tests first | Write or refresh the test before trusting the change. |
| 5 | Verify with evidence | "Done" means a command ran and its output says so. |
| 6 | Hooks over reminders | If it must happen every time, a hook does it, not a note. |
| 7 | Security first | Validate inputs, protect secrets, keep safe defaults. |
| 8 | Learn from sessions | A repeated mistake becomes a stored lesson. |

A ninth, quieter rule sits under all of them: do not overcomplicate. Treat configuration like fine-tuning, not architecture. Add a component because a real session needed it, not because it might.

## 1. Agent-first

Rule: delegate domain work to a scoped specialist without waiting to be asked.

Why: a specialist with a narrow prompt and a narrow tool set makes fewer wrong moves, and its work happens in its own context, which keeps the main session lean (see [04-parallelism.md](04-parallelism.md)).

Mechanics, the proactive triggers:

| Situation | Specialist |
|-----------|------------|
| Complex feature or refactor | planner |
| Code just written or modified | code-reviewer |
| Bug fix or new feature | tdd-guide |
| Architectural decision | architect |
| Security-sensitive code (auth, input, secrets, queries, crypto) | security-reviewer |
| Build or type errors | build-error-resolver |

Agents are addressed through the plugin namespace, for example `neva-core:planner`. Scope each one: give it only the tools, MCP servers and permissions its job needs. Limited tools produce focused execution.

## 2. Research before code

Rule: before any new implementation, look for something that already solves it.

Why: the cheapest code is code you adopt. A battle-tested library or an open-source project that covers 80% or more of the need beats a hand-rolled one on correctness and on tokens.

Mechanics, in this order:

1. Code search first: `gh search repos` and `gh search code` for existing implementations and templates.
2. Library docs second: primary vendor docs or a docs lookup to confirm API behaviour and version details.
3. Broader web research only when the first two are not enough.
4. Package registries (npm, PyPI, crates.io and the like) before writing any utility.
5. Decide: adopt as is, extend with a thin wrapper, compose two or three small packages, or build custom informed by what you found.

## 3. Plan as artifact

Rule: complex changes get a written plan, broken into phases, saved to a file before implementation starts.

Why: context is temporary and compaction is lossy. A plan in a file survives compaction, survives a new session, and can be handed to another agent as its single input. The task list is a convenience that may not exist on every harness version; never treat it as the durable record.

Mechanics:

- Identify dependencies and risks, then break the work into phases.
- For larger builds, produce the planning set before coding: requirements, architecture, system design, task list.
- Once the plan is written, clear or compact the exploration context and work from the file (see [02-token-economy.md](02-token-economy.md)).
- Multi-agent work runs as sequential phases where each phase writes one file that the next phase reads:

| Phase | Output |
|-------|--------|
| Research | research-summary.md |
| Plan | plan.md |
| Implement | code changes |
| Review | review-comments.md |
| Verify | done, or loop back |

Never skip a phase.

## 4. Tests first

Rule: RED, GREEN, IMPROVE.

1. Write the test first. It must fail.
2. Write the minimal implementation. The test must pass.
3. Refactor, then confirm coverage.

Why: a test written after the code tends to describe the code, not the requirement.

Mechanics:

| Gate | Value |
|------|-------|
| Minimum coverage | 80% |
| Test types required | unit, integration, end-to-end for critical flows |
| On failure | check test isolation, then mocks, then fix the implementation. Change the test only when the test is wrong. |

## 5. Verify with evidence

Rule: never claim a result you have not observed.

Why: the model's confidence is not evidence. A session summary that says "fixed" without a passing command is a guess.

Mechanics:

- Verification runs in order and stops at the first failure: build, type check, lint, tests with coverage, security scan, diff review.
- Checkpoint evals: set explicit checkpoints, verify against defined criteria, fix before proceeding.
- Continuous evals: rerun the full test suite and lint after major changes or on an interval.
- Choose the metric by what matters:

| Metric | Meaning | k=1 | k=3 | k=5 |
|--------|---------|-----|-----|-----|
| pass@k | at least one of k attempts succeeds | 70% | 91% | 97% |
| pass^k | all k attempts must succeed | 70% | 34% | 17% |

Use pass@k when you just need it to work. Use pass^k when consistency is essential.

- To test whether a skill earns its place: fork the session, run the same task with and without the skill in separate worktrees, diff the results.

## 6. Hooks over reminders

Rule: anything that must happen every time is a hook.

Why: skills and instructions are probabilistic. Upstream measured skill-based observation firing roughly 50 to 80% of the time, at the model's discretion. Hooks fire on every matching event, deterministically.

Mechanics, the lifecycle events:

| Event | Fires | Typical use |
|-------|-------|-------------|
| PreToolUse | before a tool runs | validation, blocking, reminders |
| PostToolUse | after a tool runs | format, type check, feedback loops |
| UserPromptSubmit | on every message you send | use sparingly: it adds latency to every prompt |
| Stop | when the agent finishes responding | final checks, persist learnings |
| PreCompact | before compaction | save state |
| SessionStart | when a session opens | load prior context |
| Notification | on permission requests | alerts |

Prefer Stop over UserPromptSubmit for anything that can wait: Stop runs once, UserPromptSubmit taxes every turn. Neva hooks are Python, one dispatcher process per event; the module table is [hooks.md](hooks.md).

## 7. Security first

Rule: validate at every boundary, never hardcode a secret, and assume hostile text will reach the model.

Why: an agent with tools turns prompt injection into shell execution. The safety boundary is the policy between the model and the action, not the system prompt.

Mechanics live in [05-security.md](05-security.md) and in Neva's own [security page](../09-security.md).

## 8. Learn from sessions

Rule: when the same problem comes up twice, the lesson is stored so it does not come up a third time.

Why: repeating a prompt, or rediscovering the same workaround, wastes tokens, context and time.

Mechanics: session state is saved by hooks, and lessons are distilled into small, confidence-scored instincts, not transcripts. See [03-memory-and-learning.md](03-memory-and-learning.md).

## Supporting principles

- Immutability: prefer explicit state transitions. Create new objects rather than mutating shared ones.
- Small files: 200 to 400 lines typical, 800 maximum. Functions under 50 lines. Nesting no deeper than 4 levels. Organise by feature, not by type. Modular code is cheaper to read and more often right on the first try.
- Skills are the canonical workflow surface. Slash commands are thin entry points onto skills.
- Build reusable patterns early: subagents, skills, commands, planning patterns, context engineering. The effort compounds as models and harnesses improve.
