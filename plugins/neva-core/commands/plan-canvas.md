---
description: "Open a plan or HTML artifact in the browser Plan Canvas for annotate-and-approve review."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# /plan-canvas

Invoke the `neva-core:plan-canvas` skill with `$ARGUMENTS` (a `.plan.md` or `.html` path; blank means the newest `.claude/plans/*.plan.md`) and follow it exactly.
An `approve` verdict counts as plan confirmation for /plan gates.
