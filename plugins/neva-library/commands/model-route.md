---
description: "Recommend the best model tier for the current task based on complexity, risk, and budget."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Model Route Command

Recommend the best model tier for the current task by complexity and budget.

## Usage

`/model-route [task-description] [--budget low|med|high]`

## Routing Heuristic

- `haiku`: deterministic, low-risk mechanical changes
- `sonnet`: default for implementation and refactors
- `opus`: architecture, deep review, ambiguous requirements

## Required Output

- recommended model
- confidence level
- why this model fits
- fallback model if first attempt fails

## Arguments

$ARGUMENTS:
- `[task-description]` optional free-text
- `--budget low|med|high` optional

## Neva Pins

Neva agents follow the same split: `opus` for judgment (planning, architecture, any reviewer, security, evaluators, researchers), `sonnet` for mechanical work (build resolvers, refactor-cleaner, doc-updater, packagers), `haiku` only for pure lookup (docs-lookup).
