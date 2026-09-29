---
name: orch-change-feature
description: "Use when an existing feature works but should behave differently. Updates the existing tests to the new spec first, changes the implementation to green, reviews, and commits behind the orch-pipeline gates."
metadata:
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# orch-change-feature

Actor · action · target: **orch · change · feature**. Thin wrapper over the
shared engine in [`orch-pipeline`](../orch-pipeline/SKILL.md).

## When to Use

- An existing feature **works**, but the desired behavior is different ("change",
  "adjust", "make it also …", "instead of X do Y").
- Distinguish from siblings:
  - **not** broken → not `orch-fix-defect` (no bug to reproduce).
  - **not** new → not `orch-add-feature` (the capability already exists).

## Operation settings

- **Default size floor:** small. Most tweaks are a function or two.
- **Phase mask:** 0 → (1 only if the new behavior needs research) → light 2 →
  4 → 5 → 6.
- **First move (phase 4):** update the *existing* tests to express the new
  desired behavior, then change the implementation until they pass. Changing the
  tests first is what separates a tweak from a fix.

## How It Works

1. Run the `orch-pipeline` engine with the settings above.
2. Keep the plan light. Only `standard`+ size warrants the full `planner` pass.
3. Stop at **Gate 1** (plan / changed-test approval) and **Gate 2** (pre-commit).
4. Add `security-reviewer` if the change touches a security trigger.

## Example

```
orch-change-feature: make nws-poller alert at 2 warnings instead of 3
→ update threshold tests to new spec → change impl to green
→ code-review → commit  [GATE 2: confirm]
```
