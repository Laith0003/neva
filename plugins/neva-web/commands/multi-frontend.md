---
description: Run a gated frontend workflow (Research, Ideation, Plan, Execute, Optimize, Review) for components, layouts, animation, and UI polish, with an optional second model as UI advisor.
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. The external ccg-workflow runtime is optional here; the phase gates are unchanged. -->

# Frontend: Gated Multi-Phase Workflow

Frontend-focused workflow: Research, Ideation, Plan, Execute, Optimize, Review.

## Usage

```bash
/multi-frontend <UI task description>
```

## Context

- Frontend task: $ARGUMENTS
- Applicable: component design, responsive layout, UI animation, style optimization, RTL and localization work

## Your Role

You are the **Frontend Orchestrator**. You plan, write every file, and deliver. Advisors only advise.

**Advisors** (use what is available, in this order):

1. **External UI model** (optional). If `NEVA_FRONTEND_ADVISOR_CMD` is set, it is a shell command that reads a prompt on stdin and prints an answer (for example a wrapper around another vendor's CLI). Its frontend opinions carry weight; its backend opinions are reference only.
2. **Subagents**. Otherwise dispatch Claude subagents: a design-minded advisor for ideation and planning, and `react-reviewer` / `vue-reviewer` / `php-reviewer` / `a11y-architect` (whichever matches the stack) for the optimize phase.

External models and advisors have **zero filesystem write access**. Claude handles all code writes and file operations.

## Advisor Call Shape

```bash
printf '%s' "ROLE: <analyzer|architect|reviewer>
TASK: <enhanced requirement or \$ARGUMENTS>
CONTEXT: <project context and results of earlier phases>
OUTPUT: <expected format>" | $NEVA_FRONTEND_ADVISOR_CMD
```

If the advisor supports sessions, save the session id from Phase 2 as `ADVISOR_SESSION` and resume it in Phases 3 and 5. With subagents, keep one advisor agent alive and continue it instead of starting a fresh one.

## Communication Guidelines

1. Start each response with a mode label `[Mode: X]`; the first is `[Mode: Research]`.
2. Follow the sequence strictly: Research, Ideation, Plan, Execute, Optimize, Review.
3. Use `AskUserQuestion` whenever the workflow needs a confirmation, selection, or approval.

## Core Workflow

### Phase 0: Prompt Enhancement (optional)

`[Mode: Prepare]` If a prompt-enhancement tool is available, enhance `$ARGUMENTS` and use the enhanced text for every later advisor call. Otherwise use `$ARGUMENTS` as-is.

### Phase 1: Research

`[Mode: Research]` Understand requirements and gather context.

1. Code retrieval: `Glob` for files, `Grep` for components and styles, `Read` for context, an Explore agent for deeper sweeps. Find the design system (tokens, `DESIGN.md`, component library) first; it is the brief.
2. Score requirement completeness from 0 to 10. **7 or higher: continue. Below 7: stop and ask for what is missing.**

### Phase 2: Ideation

`[Mode: Ideation]` Advisor-led analysis.

- Role: analyzer
- Output: UI feasibility analysis, **at least 2** candidate solutions, UX evaluation of each (including accessibility and RTL impact)

Present the solutions and **wait for the user to choose**. Do not pick for them.

### Phase 3: Planning

`[Mode: Plan]` Advisor-led planning (resume the Phase 2 session).

- Role: architect
- Input: the user's chosen solution and the Phase 2 analysis
- Output: component structure, UI flow, styling approach, states (hover, focus, active, loading, empty, error), responsive and direction behavior

Synthesize the plan and, **after the user approves it**, save it to `.claude/plan/<task-name>.md`.

### Phase 4: Implementation

`[Mode: Execute]`

- Follow the approved plan strictly.
- Follow the project's design system and code standards.
- Responsive, accessible, and bidirectional (logical properties, mirrored directional icons) by construction.

### Phase 5: Optimization

`[Mode: Optimize]` Advisor-led review.

- Role: reviewer
- Input: `git diff` or the changed code
- Output: accessibility, responsiveness, performance, direction, and design-consistency issues

Integrate the feedback and **apply optimizations only after the user confirms**.

### Phase 6: Quality Review

`[Mode: Review]` Final evaluation.

- Check completion against the saved plan.
- Render the changed screens, take screenshots (mobile and desktop; LTR and RTL when the product is bidirectional), and look at them.
- Report issues and recommendations.

## Key Rules

1. Advisor frontend opinions carry weight; advisor backend opinions are reference only.
2. Advisors never write files.
3. Claude handles all code writes and file operations.
4. No phase is skipped; every gate that asks the user waits for the answer.
