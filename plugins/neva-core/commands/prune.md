---
name: prune
description: "Delete pending instincts older than 30 days that were never promoted"
command: true
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Prune Pending Instincts

Remove expired pending instincts that were auto-generated but never reviewed or promoted.

## Implementation

Run the instinct CLI using the plugin root path:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/scripts/instinct-cli.py" prune
```

Pending instincts live in `pending/` under `$NEVA_VAULT/06 Memory/instincts/global/` and each `project/<project-id>/`. The vault comes from `NEVA_VAULT`, else `VAULT_PATH` in `~/.config/neva/identity.env`; if neither is set the CLI exits 2 with the fix. The nightly job runs this step on its own.

## Usage

```
/prune                    # Delete instincts older than 30 days
/prune --max-age 60      # Custom age threshold (days)
/prune --dry-run         # Preview without deleting
/prune --quiet           # No output (the nightly job uses this)
```
