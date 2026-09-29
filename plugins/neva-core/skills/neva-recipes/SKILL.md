---
name: neva-recipes
description: Use when asked which Neva command group runs a workflow, the command sequence and stop condition for a task, or to list all pipelines. Advisory only, never executes. Not for single-command docs (neva-guide) or prompt rewrites (prompt-optimizer).
argument-hint: <workflow description | empty=list all>
author: KyawZinLatt
metadata:
  version: "1.0.0"
  origin: neva (adapted from ECC ecc-recipes, community)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Neva Recipes

One entry point for "which group of Neva slash-commands runs my workflow, in what
order, and when do I stop." Also browses every command-group recipe family.

Fills the gap between two existing skills:

- `neva-guide`: lists commands and where to read docs, but as a flat catalog.
- `prompt-optimizer`: matches a task to components, but outputs a single prompt,
  not a multi-command group with run-order and stop condition.

This skill adds: **family grouping + run-order + stop condition.**

## When to Activate

- "Which command group do I run for <workflow>?"
- "What's the command sequence to build an MVP / fix a defect / refactor?"
- "Show me all Neva command-group recipes" (catalog mode)
- "How many workflow pipelines does Neva have?"
- User invokes `/neva-recipes` with or without a description.

### Do Not Use When

- User wants the task done now: route to the actual command, don't describe it.
- User wants deep docs for ONE command: use `neva-guide`.
- User wants a draft prompt rewritten: use `prompt-optimizer`.

## Core Principle

**Answer from current files, not memory.** The command set changes; never
hardcode counts or member lists. Read the live `commands/` directories of every installed Neva plugin each run,
then classify into families.

### Live reads

Commands are spread across plugins (`neva-core` holds the process pipelines,
language plugins hold the per-language triads). Collect every commands directory
that exists, then list names with their plugin:

```bash
CMD_DIRS=()
for D in \
  ./plugins/neva-*/commands \
  "$HOME"/.claude/plugins/marketplaces/neva/plugins/neva-*/commands \
  "$HOME"/.claude/plugins/cache/neva/neva-*/*/commands \
  ./.claude/commands \
  "$HOME"/.claude/commands; do
  [ -d "$D" ] && CMD_DIRS+=("$D")
done
[ ${#CMD_DIRS[@]} -eq 0 ] && { echo "No Neva commands directory found. Install neva-core first."; return 1; }
for D in "${CMD_DIRS[@]}"; do
  find "$D" -maxdepth 1 -name '*.md' -exec basename {} .md \; | sed "s|^|$D\t|"
done | sort -k2
```

If the same command name appears in more than one directory, prefer the repo
copy, then the marketplace copy, then the cache; say which one you read. Read
`.claude-plugin/marketplace.json` if present for plugin descriptions. Use the
smallest set of reads needed.

## Family Classification (by prefix)

Group command names by leading prefix; map known singletons by hand. Families are
derived live: the table below is the *classification rule*, not a frozen list.

| Family prefix | Recipe meaning | Typical run-order |
|---|---|---|
| `orch-*` | gated Research, Plan, TDD, Review, Commit per task type | pick one orch-* by task kind; it runs its own internal phases |
| `multi-*` | multi-model workflow | `multi-plan` then `multi-execute` then review (or `multi-workflow` end-to-end) |
| `prp-*` | PRD to plan to implement to PR pipeline | `prp-prd` then `prp-plan` then `prp-implement` then `prp-commit` then `prp-pr` |
| `epic-*` | large multi-unit epic, parallel | `epic-decompose` then `epic-claim` then `epic-validate` then `epic-review` then `epic-unblock` then `epic-sync` then `epic-publish` |
| `loop-*` | managed autonomous loop and monitor | `loop-start <pattern>` then watch with `loop-status` |
| `gan-*` | generator and evaluator loop | `gan-build` (code) or `gan-design` (UI); self-looping |
| `*-build` / `*-review` / `*-test` | per-language CI triad | `<lang>-test` (TDD) then `<lang>-build` (fix) then `<lang>-review` |
| `hookify-*` | behavior-hook management | `hookify` then `hookify-list` then `hookify-configure` |
| `learn` / `instinct-*` / `evolve` / `promote` / `prune` | continuous-learning | `learn` then `instinct-status` then `evolve` then `promote` |
| singletons | `santa-loop`, `plan`, `plan-prd`, `pr`, `code-review`, `checkpoint`, etc. | standalone or glue between groups |

Any command not matching a prefix rule → list it under **singletons** with its
one-line description.

## How It Works

```
1. Live-read command names from CMD_DIR.
2. Classify into families by prefix and a singleton map.
3. If a workflow description was given -> MATCH MODE.
   If none -> CATALOG MODE.
4. Advisory only: print the plan. Never run the matched commands.
```

### Catalog mode (no description)

Output the family table: each family, member count, members, owning plugin,
one-line meaning, typical run-order. End with the total command count and a prompt to describe a
workflow for a matched recipe.

### Match mode (description given)

1. Restate the workflow in one sentence.
2. Pick the best 1-2 families; say WHY in one line each.
3. **Run-order block**: exact command sequence for the matched family.
4. **Stop condition**: always explicit (max-runs, completion-signal,
   review-passes, or single-shot). For autonomous loops, warn about subscription
   burn and recommend a backstop bound. If a matched family lives in a plugin that is
   not installed, say which plugin to install.
5. **Where to read**: the `plugins/<plugin>/commands/<name>.md` path plus `/neva-guide <name>`.

## Output Template (match mode)

```
Workflow: <one-sentence restatement>

Best fit: <family>: <why>
(Alt: <family>: <why>)

Run-order:
  /<cmd1>   # job
  /<cmd2>   # job
  /<cmd3>   # job
  STOP when: <condition>
  WARNING (autonomous loops only): an unbounded loop burns subscription/credits;
  add a max-iteration or max-cost backstop alongside the completion signal.

Read full docs:
  plugins/<plugin>/commands/<cmd1>.md   (or: /neva-guide <cmd1>)
```

## Examples

**Catalog:** `/neva-recipes` → prints the family table and total count.

**Match:** `/neva-recipes plan a whole app upfront then auto-build with adversarial
review until done` → Best fit: `loop-*` (autonomous) wrapping `gan-*` or
`santa-loop` (adversarial). Run-order: `plan-prd` then
`loop-start rfc-dag --mode safe` then monitor `loop-status`; STOP when all units
pass review N consecutive times (add a max-iteration backstop to bound burn).

**Match:** `/neva-recipes fix a bug in my Go service` → Best fit: `orch-fix-defect`
(reproduce, fix, review, commit). Alt: `go-test` then `go-build` then
`go-review`. STOP: regression test green and review pass.

## Non-Goals

- Not an executor: advisory only.
- Not per-command deep docs: that's `neva-guide`.
- Not prompt rewriting: that's `prompt-optimizer`.
- Never hardcode command counts or member lists: always live-read.
