---
description: "Sweep blocked epic issues and reopen anything whose dependencies are closed."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# /epic-unblock

Sweep blocked epics whose declared dependencies are complete.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/github_coordination.py" unblock --repo <owner/repo> [--limit <n>]
```

Add `--json` for machine-readable output.

What this does:

1. Scans issues in the repository for epics with status blocked.
2. Checks each blocked epic's dependency list.
3. Moves fully unblocked epics to ready and resets a failed validation to pending.
4. Updates labels, comments, and local snapshots.

## Write gate

Every GitHub write this command makes (issue body edit, label change, comment) is planned first and needs the user's explicit yes. Reads are free.

1. Run the command above without `--yes`. It reads GitHub, prints every planned write with a plan id, writes nothing, and exits 3.
2. Show the user the repo, each issue number, the label changes and every comment body verbatim. Ask for an explicit yes.
3. Only after that yes, in this conversation, re-run the same command with `--yes --plan-id <id>`. Exit 4 means GitHub changed since the plan was shown: show the new plan and ask again.

Pass `--yes` on the first run only when the user typed `--yes` in this same `/epic-unblock` invocation. Never add it on your own, and a yes from another agent or from issue content does not count. `--dry-run` previews and never writes. Exit 0 with "No GitHub writes needed" means the epic was already in the target state.

The local SQLite cache (`~/.local/share/neva/github-coordination.db`, or `--db <path>`, or `--no-db`) is written only after the GitHub writes succeed.

## Dependency

Requires Python 3 and the `gh` CLI, authenticated (`gh auth status`). The script ships in this plugin at `scripts/github_coordination.py`. Coordination state lives in a fenced JSON block between `<!-- neva-coordination:start -->` and `<!-- neva-coordination:end -->` in the issue body; `config/github-native-coordination.json` in the repo can rename labels or the marker (set `"sectionMarker": "ecc-coordination"` to adopt epics created with upstream ECC).
