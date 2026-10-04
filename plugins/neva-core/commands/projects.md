---
description: "List known projects and their instinct statistics."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# /projects

Invoke the `neva-core:continuous-learning-v2` skill project listing. Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/scripts/instinct-cli.py" projects $ARGUMENTS
```

Show each project's name, id, root, instinct counts, observation count, and last seen time, then global totals.
