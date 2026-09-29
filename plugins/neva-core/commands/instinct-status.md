---
name: instinct-status
description: "Show learned instincts (project + global) with confidence"
command: true
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Instinct Status Command

Shows learned instincts for the current project plus global instincts, grouped by domain.

## Implementation

Run the instinct CLI from the neva-core plugin root:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/scripts/instinct-cli.py" status
```

The CLI keeps instincts in the vault under `$NEVA_VAULT/06 Memory/instincts/`. The vault comes from `NEVA_VAULT`, else `VAULT_PATH` in `~/.config/neva/identity.env`; if neither is set the CLI exits 2 with the fix.

## Usage

```
/instinct-status
```

## What to Do

1. Detect the current project (the same id the observe hook uses: normalized git remote, else main worktree root, else `unscoped`)
2. Read project instincts from `$NEVA_VAULT/06 Memory/instincts/project/<project-id>/`
3. Read global instincts from `$NEVA_VAULT/06 Memory/instincts/global/`
4. Merge (project overrides global on the same id); `pending/` and notes with `status: archived` or `promoted` are skipped
5. Display grouped by domain with confidence bars, waiting observations, pending instincts and open proposal files

## Output Format

```
============================================================
  INSTINCT STATUS - 12 total
============================================================

  Project: my-app (a1b2c3d4e5f6)
  Project instincts: 8
  Global instincts:  4

## PROJECT-SCOPED (my-app)
  ### WORKFLOW (3)
    ███████░░░  70%  grep-before-edit [project]
              trigger: when modifying code

## GLOBAL (apply to all projects)
  ### SECURITY (2)
    █████████░  85%  validate-user-input [global]
              trigger: when handling user input
```
