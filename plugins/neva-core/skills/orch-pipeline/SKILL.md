---
name: orch-pipeline
description: "Use when an orch-* operation skill runs, or when adding an orch operation or tuning its shared phases. The gated Research-Plan-TDD-Review-Commit engine, size classifier, two human gates, and the subagent task loop with two-stage review."
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Merged with obra/superpowers subagent-driven-development and executing-plans (MIT, Jesse Vincent). -->

# Orchestrator Pipeline (shared engine)

The `orch-*` skills are thin wrappers. They do not re-implement any work. They
classify the request, choose which phases of *this* pipeline run, and delegate
each phase to an existing Neva agent or command. This file is that pipeline.

> Invoke an operation skill (`orch-add-feature`, `orch-fix-defect`, ...) rather
> than this engine directly. This file is the reference they point at.

## When to Use

- Loaded indirectly whenever an `orch-*` operation skill runs.
- Read directly only when adding a new operation to the family or tuning the
  shared phases, gates, agent map, or the Phase 4 task loop.

## The operation family

| Skill | Operation | Trigger | First move |
|-------|-----------|---------|------------|
| `orch-add-feature` | feature | capability does not exist yet | research + plan a new slice |
| `orch-change-feature` | tweak | works, but desired behavior differs | amend existing behavior *and its tests* |
| `orch-fix-defect` | fix | broken; behavior is wrong | reproduce as a failing test, then fix |
| `orch-refine-code` | refactor | behavior stays, structure improves | restructure while keeping tests green |
| `orch-build-mvp` | mvp | bootstrap from a design/spec doc | ingest doc, then vertical slices |

> These wrappers **compose** existing Neva commands rather than replace them:
> `/feature-dev`, `/plan`, `/code-review`, `/build-fix`, `/refactor-clean`, and
> `/gan-build`, plus the `tdd-workflow` skill. The orch-* family adds the shared
> size classifier, the two gates, and the Phase 4 task loop on top of them, so
> one umbrella covers all five operations consistently.

## Step 0: Classify size (right-sizing)

Ceremony scales to blast radius. Score the request on three signals, take the
**highest** tier any signal reaches, and state the result in one line so the user
can override:

| Tier | Files touched | New dependency / contract | Design ambiguity | Phases that run |
|------|---------------|---------------------------|------------------|-----------------|
| trivial | 1, a few lines | none | none; the change is obvious | 4 → 5 → 6 |
| small | 1 file / 1 function | none | clear once you read the code | (1 light) → 4 → 5 → 6 |
| standard | 2-5 files | maybe a new internal module | one real choice to make | 1 → 2 → 4 → 5 → 6 |
| large | many / cross-cutting | new external dep, public API, or a spec doc | multiple open questions | 1 → 2 → (3) → 4 → 5 → 6 |

Phase 0 (Intake) always runs and is omitted from the mask column above. The
tie-breaker: anything touching a security trigger (below) or a public API /
contract is **at least** standard, regardless of file count.

The tier also picks the Phase 4 execution mode (see "Phase 4 execution modes"):
trivial and small run **inline**; standard and large run the **subagent task
loop** when the task_list has 2 or more tasks and an isolated worktree exists.

## The phases

Each phase delegates. It does not do the work inline.

- **0. Intake**: restate the request. For `orch-build-mvp`, read the spec/design
  doc and extract scope, locked decisions, and a feature list.
- **1. Research & Reuse**: per the common `development-workflow` rule: `gh search repos` /
  `gh search code`, then Context7 / vendor docs, then package registries, then
  Exa. Prefer adopting a proven implementation over net-new code.
- **2. Plan**: delegate to the `planner` agent (or `architect` /
  `code-architect` for structural decisions). Output a `task_list` ordered as
  thin vertical slices. For standard and large work the task_list is a plan
  file in the `blueprint` format (exact file paths, interfaces, complete code
  and test steps, no placeholders), so the Phase 4 loop can extract one task
  brief per task. → **GATE 1.**
- **3. Scaffold**: `orch-build-mvp` only: stand up the first end-to-end slice.
- **4. Implement (TDD)**: drive each task through the `tdd-guide` agent (or the `tdd-workflow` skill):
  red → green → refactor. Honor the operation's first-move rule. Run it in the
  execution mode the size tier picked (inline or subagent task loop).
- **5. Review**: `code-reviewer` agent / `/code-review`. Add `security-reviewer`
  whenever the diff touches a security trigger (below). In subagent mode this is
  the **final whole-branch review**; the per-task reviews already ran inside Phase 4.
- **6. Commit**: conventional commits (`feat:` / `fix:` / `refactor:` / ...), one
  per logical chunk. → **GATE 2.**

## The two gates

This family is **gated, not autonomous**:

1. **GATE 1: after Plan.** Present the `task_list`; do not write implementation
   code until the user approves.
2. **GATE 2: before Commit.** Present the diff summary and proposed messages;
   do not commit until the user confirms.

Everything between the gates flows without stopping.

Gate 2 governs every commit that lands on the user's branch. In subagent mode
the implementers make per-task checkpoint commits, and those are allowed only on
the isolated worktree branch, where they are the review mechanism (the review
package is built from `BASE..HEAD`). At Gate 2 the controller presents the
branch diff summary and the proposed conventional commits; on confirmation it
shapes the checkpoint commits into those conventional commits (one per logical
chunk) and hands off to the `git-workflow` finish menu. With no isolated
worktree, subagent mode is not available: run inline and commit nothing until
Gate 2.

## Phase 4 execution modes

### Inline mode (trivial, small, or no isolated worktree)

Execute the task_list in this session.

1. Read the approved task_list once. Review it critically: raise any question
   or concern with the user before starting. If none, create a todo per task.
2. For each task: mark it in progress, follow each step exactly, run the
   verifications the task names, mark it complete.
3. Never start implementation on a main/master branch without the user's
   explicit consent.

**Stop executing immediately when:**
- a blocker appears (missing dependency, test fails, instruction unclear);
- the plan has critical gaps preventing a start;
- you do not understand an instruction;
- verification fails repeatedly.

Ask for clarification rather than guessing. Return to the plan review when the
user updates the plan or the approach needs rethinking. Do not force through
blockers.

### Subagent mode (standard or large, 2+ tasks, isolated worktree)

Dispatch a fresh implementer subagent per task, a task review (spec compliance
plus code quality) after each, and a broad whole-branch review at the end
(Phase 5).

**Why subagents:** each subagent gets isolated context built for exactly its
task. It never inherits the session's history. That keeps it focused and keeps
the controller's context free for coordination.

**Narration:** between tool calls, narrate at most one short line. The ledger
and the tool results carry the record.

**Continuous execution between the gates.** After Gate 1, do not pause to check
in between tasks. "Should I continue?" prompts and progress summaries waste the
user's time. The only exits before Gate 2 are the four stop conditions below,
or all tasks complete.

**Rulings, not stalls.** Conflicts, ambiguities, plan defects, a cap you would
have asked to exceed: decide them. The spec is the binding authority, the plan
is its argument, and your judgment settles what neither answers. Record every
decision in the ledger as `Ruling: <what you decided>; <why>; <what it costs if
wrong>`, and keep going.

**Four things stop you, and only these:** an irreversible or destructive
operation; a security-sensitive action; a side effect outside this worktree that
norms say you ask about first (a merge, a push to a shared branch, a publish);
and a plan so broken that every path forward is a guess. For those, stop and ask.

#### Setup

Confirm the isolated workspace (`git-workflow`, "Isolated workspace"). Never
start implementation on a main/master branch without explicit consent.

Conversation memory does not survive compaction. Controllers that lost their
place have re-dispatched entire completed task sequences, the single most
expensive failure observed. Track progress in a ledger file, not only in todos.

- Each plan owns a workspace: run
  `${CLAUDE_PLUGIN_ROOT}/skills/orch-pipeline/scripts/orch-workspace PLAN_FILE`.
  It prints the plan's git-ignored directory
  (`<repo-root>/.neva/orch/<plan-basename>/`), home to every artifact for THIS
  plan: ledger, briefs, reports, review packages. Another plan's directory is
  never yours to read or write.
- Check for this plan's ledger at `<workspace>/progress.md`. If its first line
  names your plan file, tasks with a `Task <N>: complete` line are DONE: do not
  re-dispatch them; resume at the first task without one. A task whose last
  line is a fix round is mid-loop: resume the loop at the next round. A ledger
  whose first line names a different plan file is another plan's progress:
  leave it and start your own.
- Create the ledger with its identity as the first line:
  `# orch ledger: plan: <plan file path>`.
- After compaction, trust the ledger and `git log` over your own recollection.
  `git clean -fdx` destroys the workspace (git-ignored scratch); recover from
  `git log` if that happens.

Read the plan once, note its context and Global Constraints, and create a todo
per task. If the plan names a Spec, read that too: conflicts inside the plan
resolve against it. A plan with no reachable spec gets a ledger note saying so;
rulings made without one are provisional.

**Pre-flight conflict scan.** Before dispatching Task 1, scan the plan once and
write down what you checked:

- tasks that contradict each other or the plan's Global Constraints;
- anything the plan explicitly mandates that the review rubric treats as a
  defect (a test that asserts nothing, verbatim duplication of a logic block).

The scan's output is a table, not a verdict. One row for every pair of tasks
that share a file or an interface: the two tasks, what one produces against what
the other consumes, and what you found. One row for every task: whether its own
text agrees with itself (the tests it specifies against the code it specifies,
the files it creates against the files it later touches). "The scan is clean"
without those rows is not a scan you ran. Write the table to the ledger, rule on
every finding before execution begins, record each ruling beside its row, then
dispatch Task 1.

#### Model selection

Use the least powerful model that can handle each role.

| Role | Tier |
|------|------|
| Implementer, plan text contains the complete code (transcription plus testing), or a single-file mechanical fix | cheapest (haiku) |
| Implementer working from prose, multi-file integration, pattern matching, debugging | standard (sonnet) |
| Architecture or design judgment, broad codebase understanding | most capable (opus) |
| Task reviewer | scaled to diff size, complexity, risk; floor is standard |
| Scoped re-review of a small fix diff | cheap to mid |
| Fix-loop rounds 4-5 implementer | at least one tier above the implementer that got stuck |
| Final whole-branch review (Phase 5) | most capable |

- **Always specify the model explicitly when dispatching.** An omitted model
  inherits the session's model, often the most expensive, which silently
  defeats this table.
- **Turn count beats token price.** The cheapest models routinely take 2-3x the
  turns on multi-step work. Use a mid-tier floor for reviewers and for
  implementers working from prose.

#### The task loop

**Batch small same-shape work.** When several tasks are each a small independent
edit of the same kind (the same one-line fix, constant change, or field addition
across files), compose ONE dispatch brief listing every file and its change,
send it to a single subagent, and review its diff as one unit.

Everything pasted into a dispatch prompt, and everything a subagent prints back,
stays resident in your context. Hand artifacts over as files.

**Waiting on dispatched subagents:** never poll with short timeouts and never
sit in one open-ended wait. While you have local work (ledger updates, packaging
the next review, reading reports), keep working. When idle, wait in bounded
stretches of five to ten minutes; between stretches post one line of status and
reconcile live children, chasing any that finished without reporting.

**1. Dispatch the implementer.** Record BASE (`git rev-parse HEAD`) first.

- Run `${CLAUDE_PLUGIN_ROOT}/skills/orch-pipeline/scripts/task-brief PLAN_FILE N`.
  It extracts the task's full text to a file and prints the path. The dispatch
  contains: (1) one line on where this task fits; (2) the brief path, introduced
  as "read this first: it is your requirements, with the exact values to use
  verbatim"; (3) interfaces and decisions from earlier tasks the brief cannot
  know; (4) your resolution of any ambiguity in the brief; (5) the report-file
  path and report contract. Exact values appear only in the brief. Never make a
  subagent read the whole plan file.
- Report file: named after the brief (`task-N-brief.md` → `task-N-report.md`).
  The implementer writes the full report there and returns only status,
  commits, a one-line test summary, and concerns.
- A dispatch describes one task, not the session's history. Never paste
  accumulated prior-task summaries.
- The implementer never dispatches subagents: no helpers, never a reviewer.
- If an earlier task parked a finding in the area this task touches, carry a
  pointer to that ledger entry.
- Record the implementer's agent identity: fix rounds 1-3 resume it.
- Never dispatch multiple implementation subagents in parallel (conflicts).

Template: [implementer-prompt.md](implementer-prompt.md). The implementer
follows the operation's first-move rule and the `tdd-workflow` discipline.

**2. Handle the report.** Four statuses:

- **DONE:** run `scripts/review-package PLAN_FILE BASE HEAD` (BASE is the commit
  recorded before dispatch, never `HEAD~1`, which silently drops all but the
  last commit of a multi-commit task), then dispatch the task reviewer with the
  printed path.
- **DONE_WITH_CONCERNS:** read the concerns first. Correctness or scope
  concerns get addressed before review. Observations ("this file is getting
  large") get noted, then review proceeds.
- **NEEDS_CONTEXT:** provide the missing context and re-dispatch.
- **BLOCKED:** a context problem gets more context on the same model; a
  reasoning problem gets a more capable model; a too-large task gets split; a
  wrong plan gets a ruling, ledgered, carried in the re-dispatch.

Never ignore an escalation or force the same model to retry without a change.
Answer implementer questions fully before it implements.

**3. Review the task.** Per-task reviews are task-scoped gates. Never skip one,
and never accept a report missing either verdict: spec compliance AND task
quality are both required. Implementer self-review never replaces it.

- Hand the reviewer its diff as a file (the review package). It never enters
  your own context. Never dispatch a task reviewer without a diff file.
- Reviewer inputs: the brief, the report file, the review package, plus the
  global constraints copied verbatim from the plan's Global Constraints or the
  spec (exact values, formats, stated relationships between components).
- Do not add open-ended directives ("check all uses") without a concrete,
  task-specific reason. Do not ask the reviewer to re-run tests the implementer
  already ran on the same code.
- Never pre-judge findings. If your prompt contains "do not flag", "don't treat
  X as a defect", "at most Minor", or "the plan chose", stop: you are
  pre-judging to spare yourself a review loop.
- "CANNOT VERIFY from diff" items (requirements in unchanged code or spanning
  tasks) do not block the rest of the review, but you resolve each one before
  marking the task complete. A confirmed real gap is a failed spec review.

Template: [task-reviewer-prompt.md](task-reviewer-prompt.md)

**4. The fix loop.** Triggers on spec FAIL, any Critical or Important finding,
or a CANNOT VERIFY item you confirmed as a real gap. Two routes leave first:

- Minor findings go to the ledger as `Task <N>: minor (deferred): <one-liner>`
  and to the final review's triage list. They never enter the loop.
- A plan-mandated finding (or any finding that conflicts with the plan text) is
  yours to rule on against the spec, ledgered before you act. Do not dismiss it
  because the plan mandates it; do not dispatch a fix that contradicts the plan
  without a recorded ruling.

A fix round is one fix dispatch plus one scoped re-review. **Five rounds maximum
per task.**

- **Rounds 1-3:** resume the original implementer with the open findings
  verbatim. If the harness cannot message a live subagent, dispatch a fresh one
  with the brief path, the report-file path, and the findings.
- **Rounds 4-5:** fresh implementer on a more capable model, framed: "A prior
  implementer attempted this task [N] times; you own it now. Read the report
  file for what was tried."
- **Every round:** the implementer fixes, re-runs the tests covering the amended
  code, appends a fix report (covering tests, command, output) to the same
  report file. Dispatch the re-review only once all three are present.
- **The re-review is scoped:** `scripts/review-package PLAN_FILE FIX_BASE HEAD`
  (FIX_BASE = the head the previous review saw) plus
  [re-review-prompt.md](re-review-prompt.md). It verdicts each finding ADDRESSED
  or NOT ADDRESSED and flags new breakage in the fix diff only. Out-of-scope
  observations go to the ledger as deferred minors.
- After each round, append:
  `Task <N>: fix round <R>/5 (<X> addressed, <Y> open; <finding one-liners>; commits <a7>..<b7>)`
- Never fix findings yourself in the controller session: controller fixes skip
  review and pollute your context.

**The breaker.** When round 5 still leaves findings open, stop dispatching and
adjudicate each one:

- reviewer wrong or point contestable: `Task <N>: parked; <finding>; Ruling: <why the code stands>`;
- real but nothing downstream builds on it: park it the same way, marked real and deferred;
- real and load-bearing (a later task builds on it, or it reveals a plan
  defect): rule on the smallest change that unblocks dependent work, ledger it
  as `Task <N>: Ruling: <finding>; <decision and why>`, and carry it into the
  next dispatch. Stop only when every path forward is a guess.

Adjudicate only at the cap. Every adjudication is a ledger entry; a silent
discard is forbidden.

**5. Complete the task.** Append `Task <N>: complete (commits <base7>..<head7>, review clean)`
or `Task <N>: complete (commits <base7>..<head7>, <K> parked)`, mark the todo
complete, move on. Never move to the next task while open Critical/Important
issues are neither fixed nor parked with a ruling at the cap.

#### Phase 5 in subagent mode: final whole-branch review

Run `scripts/review-package PLAN_FILE MERGE_BASE HEAD` (MERGE_BASE =
`git merge-base <base-branch> HEAD`) and dispatch the `code-reviewer` agent on
the most capable model with the printed path, plus `security-reviewer` when a
security trigger was touched. Point it at the ledger's deferred-minor and parked
lines so it triages which must be fixed before Gate 2.

If it returns findings, dispatch ONE fix subagent with the complete findings
list (never one fixer per finding), then exactly one scoped re-review of the fix
wave. Adjudicate residuals as in the breaker. There is no second fix wave:
residual load-bearing findings surface to the user at Gate 2.

#### Before Gate 2: rulings I made

Collect every ledger line containing `Ruling:` (pre-flight rulings, parked
findings, breaker adjudications) into the Gate 2 message under "Rulings I made",
in order, each with what it costs if wrong. The list is exhaustive. It is the
only place the decisions taken on the user's behalf reach them.

After Gate 2 lands and the final review is clean, delete this plan's workspace
(`rm -rf <workspace>`); git history is the record. Leave sibling plan
directories alone.

## Agent / command map

| Phase | Primary | Fallback / escalation |
|-------|---------|----------------------|
| Intake / understand | `code-explorer` | trace existing paths before a tweak, fix, or refactor |
| Plan | `planner` | `architect`, `code-architect` for structural calls; `blueprint` for multi-PR plans |
| Implement | `tdd-guide` (or `tdd-workflow` skill); in subagent mode via [implementer-prompt.md](implementer-prompt.md) | `build-error-resolver` / `/build-fix` on build breaks |
| Task review (subagent mode) | [task-reviewer-prompt.md](task-reviewer-prompt.md), then [re-review-prompt.md](re-review-prompt.md) per fix round | language reviewer for the diff's language |
| Review | `code-reviewer` / `/code-review` | language reviewer (`python-reviewer`, `typescript-reviewer`, ...) |
| Security | `security-reviewer` | none |
| MVP inner loop | `/gan-build "<brief>" --skip-planner` | drives `gan-generator` → `gan-evaluator`; tune `--max-iterations` / `--pass-threshold` |

Match the language reviewer to the repo (see the repo's own `CLAUDE.md`).

## Security-review trigger

Pull in `security-reviewer` when the diff touches any of: authentication or
authorization, user-input handling, database queries, file-system paths,
external API calls, cryptography, or secrets / credentials. (Per the common
`security` rule.)

## Handoff artifacts

The pipeline carries no hidden state. The planning docs *are* the handoff:

- `task_list` (from Plan) drives the Implement loop.
- In subagent mode, `<workspace>/progress.md` (the ledger), per-task briefs,
  report files, and review packages are the recovery map.
- Larger work may also emit PRD / architecture / system_design under the repo's
  `docs/` per the common `development-workflow` rule.
- Review findings (CRITICAL / HIGH) must be resolved before Gate 2.

## Scripts

`scripts/orch-workspace`, `scripts/task-brief`, `scripts/review-package`
(bash, need git). Adapted from obra/superpowers (MIT, Jesse Vincent); the
workspace moved to `.neva/orch/<plan-basename>/` with a self-ignoring
`.gitignore`.

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "The task is small, skip Gate 1" | Size picks which phases run. It never removes a gate. |
| "Close enough on spec compliance" | Reviewer found spec gaps = not done. Fix, or hit the cap and adjudicate. |
| "I'll fix it myself, dispatching is overhead" | Controller fixes pollute context and skip review. Resume the implementer. |
| "One more round will converge" | Past the cap, rounds don't converge; the failure is structural. Adjudicate and route. |
| "The reviewer will just find something new anyway" | Scoped re-reviews verify fixes; they cannot wander. New findings on untouched code go to the ledger. |
| "This finding is obviously wrong, I'll drop it" | You adjudicate only at the cap, and every ruling is a ledger entry. |
| "The fix was small, skip the re-review" | Unreviewed fixes are how regressions land. |
| "Ledger bookkeeping is overhead" | The ledger is what survives compaction. |
| "The implementer spawned its own reviewer: free extra assurance" | A duplicate seat on the same diff. The task review is the gate; flag it as a defect. |
| "Checkpoint commits are commits, so Gate 2 already passed" | Gate 2 governs what lands on the user's branch. Worktree checkpoints are scratch until confirmed. |

## Verification

- size tier was stated and matched the work
- execution mode matched the tier (inline for trivial/small; subagent loop only with 2+ tasks and an isolated worktree)
- Gate 1 (plan) and Gate 2 (commit) were both honored
- in subagent mode: every task has a `complete` ledger line with both review verdicts, and every `Ruling:` line reached the user at Gate 2
- `security-reviewer` ran iff a security trigger was touched
- commits are conventional and scoped to one logical change
- new / changed behavior has tests; coverage ≥ 80% per the common `testing` rule
