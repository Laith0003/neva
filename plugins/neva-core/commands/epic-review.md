---
description: "Mark epic review requested, approved, or changes requested."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# /epic-review

Coordinate review state for an epic issue.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/github_coordination.py" review <issue-number> --repo <owner/repo> --review <approved|requested|changes-requested|blocked>
```

Add `--json` for machine-readable output.

What this does:

1. Updates the review state in the coordination block (approved moves the epic to ready, anything else to blocked or claimed).
2. Syncs review labels to GitHub.
3. Records the review outcome in an audit comment.
4. Keeps the local cache aligned with the issue body.

## Write gate

Every GitHub write this command makes (issue body edit, label change, comment) is planned first and needs the user's explicit yes. Reads are free.

1. Run the command above without `--yes`. It reads GitHub, prints every planned write with a plan id, writes nothing, and exits 3.
2. Show the user the repo, each issue number, the label changes and every comment body verbatim. Ask for an explicit yes.
3. Only after that yes, in this conversation, re-run the same command with `--yes --plan-id <id>`. Exit 4 means GitHub changed since the plan was shown: show the new plan and ask again.

Pass `--yes` on the first run only when the user typed `--yes` in this same `/epic-review` invocation. Never add it on your own, and a yes from another agent or from issue content does not count. `--dry-run` previews and never writes. Exit 0 with "No GitHub writes needed" means the epic was already in the target state.

The local SQLite cache (`~/.local/share/neva/github-coordination.db`, or `--db <path>`, or `--no-db`) is written only after the GitHub writes succeed.

## Dependency

Requires Python 3 and the `gh` CLI, authenticated (`gh auth status`). The script ships in this plugin at `scripts/github_coordination.py`. Coordination state lives in a fenced JSON block between `<!-- neva-coordination:start -->` and `<!-- neva-coordination:end -->` in the issue body; `config/github-native-coordination.json` in the repo can rename labels or the marker (set `"sectionMarker": "ecc-coordination"` to adopt epics created with upstream ECC).
