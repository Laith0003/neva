---
name: parallel-execution-optimizer
description: "Use when 2+ independent tasks or failures can run at once, or a task must go much faster through concurrent agents, batched reads and checks, or isolated worktrees without losing correctness. Lane matrix, one agent per domain, verification table."
license: MIT
metadata:
  origin: neva (adapted from ECC)
tools: Read, Write, Edit, Bash, Grep, Glob
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with obra/superpowers dispatching-parallel-agents (MIT, Jesse Vincent). -->

# Parallel Execution Optimizer

Use this skill when speed comes from doing independent work at the same time:
repo inspection, file reads, API checks, browser checks, build/test lanes,
deploy readbacks, multi-worktree implementation passes, or several unrelated
failures that can each be investigated alone.

**Core principle:** one agent per independent problem domain, isolated context,
concurrent dispatch. Each agent gets exactly the context its lane needs and
never the session's history; the controller keeps its own context for
coordination.

## Is it parallel? (decide before acting)

```
Multiple tasks or failures?
  └─ Are they independent? ── no (related) ──> one agent investigates all
       └─ yes ─> Can they run without shared state? ── no ──> sequential agents
                  └─ yes ──> parallel dispatch
```

**Use when:**
- 3+ test files failing with different root causes
- multiple subsystems broken independently
- each problem can be understood without context from the others
- no shared state between the lanes (files, tables, services, ports)

**Do not use when:**
- failures are related (fixing one might fix others): investigate together first
- understanding requires seeing the whole system state
- the work is exploratory debugging and you do not yet know what is broken
- agents would interfere (same files, same resources, same table)

## Core Pattern

Turn urgency into a dependency graph before acting.

1. Define the objective and done signal.
2. Split work into lanes (group by what is broken or what is being built, not by file count).
3. Mark each lane as parallel, sequential, or gated.
4. Run independent reads/checks together.
5. Keep writes isolated by file, worktree, branch, service, or dataset.
6. Merge only after evidence shows the lanes are compatible.
7. End with a verification table, not a vague speed claim.

## Lane Matrix

Before a large push, write a compact matrix:

```text
Lane | Can run in parallel? | Write surface | Risk | Verification
Repo scan | yes | none | low | rg/git status outputs
Backend patch | maybe | src/api | medium | unit tests
Frontend patch | maybe | app/components | medium | browser screenshot
Deploy readback | after build | remote service | high | live URL + logs
```

Only run lanes in parallel when their write surfaces do not collide.

## Dispatching agent lanes

**Issue every lane's dispatch in the same response.** Multiple dispatch calls in
one response run in parallel; one per response runs sequentially.

```text
Agent (general-purpose): "Fix agent-tool-abort.test.ts failures"
Agent (general-purpose): "Fix batch-completion-behavior.test.ts failures"
Agent (general-purpose): "Fix tool-approval-race-conditions.test.ts failures"
# all three run concurrently
```

Each lane prompt is:
1. **Focused:** one clear problem domain (one test file, one subsystem).
2. **Self-contained:** all context needed: the error messages, test names, file paths.
3. **Constrained:** what it must not touch ("do NOT change production code", "fix tests only").
4. **Specific about output:** what it returns (root cause and the changes made).

Example lane prompt:

```markdown
Fix the 3 failing tests in src/agents/agent-tool-abort.test.ts:

1. "should abort tool with partial output capture": expects 'interrupted at' in message
2. "should handle mixed completed and aborted tools": fast tool aborted instead of completed
3. "should properly track pendingToolCount": expects 3 results but gets 0

These are timing/race condition issues. Your task:
1. Read the test file and understand what each test verifies
2. Identify root cause: timing issues or actual bugs?
3. Fix by replacing arbitrary timeouts with event-based waiting, fixing bugs in
   the abort implementation if found, or adjusting expectations only if the
   tested behavior changed on purpose

Do NOT just increase timeouts. Find the real issue.
Return: root cause, files changed, test command and result.
```

| Mistake | Fix |
|---------|-----|
| Too broad: "Fix all the tests" (agent gets lost) | One file or subsystem per lane |
| No context: "Fix the race condition" | Paste the errors and test names |
| No constraints (agent refactors everything) | Name what must not change |
| Vague output: "Fix it" | Name the return: root cause, changes, evidence |

## Execution Rules

- Batch file reads, searches, status checks, and metadata queries.
- Use isolated worktrees for large unrelated implementation lanes (`git-workflow`, "Isolated workspace").
- Start long-running tests, builds, backfills, and deploys in separate sessions,
  then poll them deliberately.
- If a lane discovers a blocker that changes the plan, pause dependent lanes
  and update the matrix.
- Never let a background process outlive the turn unless the user explicitly
  asked for a continuing service.
- Do not parallelize destructive commands, migrations, writes to the same table,
  or live customer-impacting deploys without an explicit gate.
- Implementation lanes that edit the same files never run in parallel. For a
  planned multi-task build, use `orch-pipeline` subagent mode (one implementer
  at a time, reviewed) instead.

## Integrating lanes

When agents return:
1. **Read each summary:** understand what changed and why.
2. **Check for conflicts:** did two lanes edit the same code?
3. **Run the full suite:** the lanes must work together, not only alone.
4. **Spot check:** agents make systematic errors; open at least one diff per lane.

## Output Shape

Use this when reporting:

```text
Parallel execution result:
- Lanes run: 5
- Lanes completed: 4
- Blocked lane: deploy readback, waiting on DNS propagation
- Fast path found: batched repo scan + focused tests
- Verification: lint pass, unit pass, live smoke pass
```

## Failure Modes

- More concurrency that creates conflicting edits.
- Benchmarking the tool instead of the task.
- Treating "fast" as done before correctness is proven.
- Forgetting to poll running sessions.
- Hiding skipped checks behind a success summary.
- Splitting related failures across lanes, so each agent patches a symptom of one root cause.
