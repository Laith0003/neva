---
name: agent-sort
description: Use when a repo should load only the Neva plugins, skills, rules, and hooks it actually needs. Sorts every component into DAILY vs LIBRARY with grep evidence from the repo and returns an install plan.
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Agent Sort

Use this skill when a repo needs a project-specific Neva surface instead of every plugin loaded at once.

The goal is not to guess what "feels useful." The goal is to classify Neva components with evidence from the actual codebase.

## When to Use

- A project only needs a subset of Neva and loading every plugin is too noisy
- The repo stack is clear, but nobody wants to hand-curate skills one by one
- A team wants a repeatable install decision backed by grep evidence instead of opinion
- You need to separate always-loaded daily workflow surfaces from searchable library/reference surfaces
- A repo has drifted into the wrong language, rule, or hook set and needs cleanup

## Non-Negotiable Rules

- Use the current repository as the source of truth, not generic preferences
- Every DAILY decision must cite concrete repo evidence
- LIBRARY does not mean "delete"; it means "keep accessible without loading by default"
- Do not install hooks, rules, or scripts that the current repo cannot use
- Prefer the Claude Code plugin system (`claude plugin install`, project `enabledPlugins`); do not introduce a second install system or hand-copied skills

## Outputs

Produce these artifacts in order:

1. DAILY inventory
2. LIBRARY inventory
3. install plan
4. verification report
5. optional `skill-library` router if the project wants one

## Classification Model

Use two buckets only:

- `DAILY`
  - should load every session for this repo
  - strongly matched to the repo's language, framework, workflow, or operator surface
- `LIBRARY`
  - useful to retain, but not worth loading by default
  - should remain reachable through search, router skill, or selective manual use

## Evidence Sources

Use repo-local evidence before making any classification:

- file extensions
- package managers and lockfiles
- framework configs
- CI and hook configs
- build/test scripts
- imports and dependency manifests
- repo docs that explicitly describe the stack

Useful commands include:

```bash
rg --files
rg -n "typescript|react|next|supabase|django|spring|flutter|swift"
cat package.json
cat pyproject.toml
cat Cargo.toml
cat pubspec.yaml
cat go.mod
```

## Parallel Review Passes

If parallel subagents are available, split the review into these passes:

1. Agents
   - classify `plugins/neva-*/agents/*`
2. Skills
   - classify `plugins/neva-*/skills/*`
3. Commands
   - classify `plugins/neva-*/commands/*`
4. Rules
   - classify `plugins/neva-*/rules/*` (language packs under `rules/<lang>/`)
5. Hooks and scripts
   - classify hook surfaces, MCP health checks, helper scripts, and OS compatibility
6. Extras
   - classify contexts, examples, MCP configs, templates, and guidance docs

If subagents are not available, run the same passes sequentially.

## Core Workflow

### 1. Read the repo

Establish the real stack before classifying anything:

- languages in use
- frameworks in use
- primary package manager
- test stack
- lint/format stack
- deployment/runtime surface
- operator integrations already present

### 2. Build the evidence table

For every candidate surface, record:

- component path
- component type
- proposed bucket
- repo evidence
- short justification

Use this format:

```text
neva-web/skills/frontend-patterns          | skill | DAILY   | 84 .tsx files, next.config.ts present | core frontend stack
neva-backend-langs/skills/django-patterns  | skill | LIBRARY | no .py files, no pyproject.toml       | not active in this repo
neva-web/rules/typescript/*                | rules | DAILY   | package.json + tsconfig.json          | active TS repo
neva-backend-langs/rules/python/*          | rules | LIBRARY | zero Python source files              | keep accessible only
```

### 3. Decide DAILY vs LIBRARY

Promote to `DAILY` when:

- the repo clearly uses the matching stack
- the component is general enough to help every session
- the repo already depends on the corresponding runtime or workflow

Demote to `LIBRARY` when:

- the component is off-stack
- the repo might need it later, but not every day
- it adds context overhead without immediate relevance

### 4. Build the install plan

Translate the classification into action:

Plugins are the install unit, so decide per plugin first, then per component:

- a plugin with any DAILY component -> enable it for this repo in `.claude/settings.json` under `enabledPlugins` (`"neva-web@neva": true`)
- a plugin with only LIBRARY components -> leave it installed user-wide but not enabled for this repo; enable on demand
- `neva-core` -> always enabled
- DAILY rules -> only the matching language packs; note any pack from an enabled plugin that should be ignored for this repo
- DAILY hooks -> keep only hooks whose runtime the repo has (for example a formatter hook needs that formatter installed)
- LIBRARY surfaces -> keep accessible through search or `skill-library`

If the repo already uses selective installs, update that plan instead of creating another system.

### 5. Create the optional library router

If the project wants a searchable library surface, create:

- `.claude/skills/skill-library/SKILL.md`

That router should contain:

- a short explanation of DAILY vs LIBRARY
- grouped trigger keywords
- where the library references live

Do not duplicate every skill body inside the router.

### 6. Verify the result

After the plan is applied, verify:

- every DAILY file exists where expected
- stale language rules were not left active
- incompatible hooks were not installed
- the resulting install actually matches the repo stack

Return a compact report with:

- DAILY count
- LIBRARY count
- removed stale surfaces
- open questions

## Handoffs

If the next step is interactive installation or repair, hand off to:

- `neva-guide` (install guidance)

If the next step is overlap cleanup or catalog review, hand off to:

- `skill-stocktake`

If the next step is broader context trimming, hand off to:

- `strategic-compact`

## Output Format

Return the result in this order:

```text
STACK
- language/framework/runtime summary

DAILY
- always-loaded items with evidence

LIBRARY
- searchable/reference items with evidence

INSTALL PLAN
- what should be installed, removed, or routed

VERIFICATION
- checks run and remaining gaps
```
