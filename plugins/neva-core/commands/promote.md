---
name: promote
description: "Propose moving project instincts to global scope; nothing is applied until the owner ticks the block"
command: true
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Promote Command

Proposal first. `/promote` files promote-global blocks for the owner to approve. A global instinct is written only after the owner ticks `approve` on its block in the proposal file. No flag replaces the tick.

## Implementation

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/scripts/instinct-cli.py" promote [instinct-id] [--dry-run] [--apply]
```

The vault comes from `NEVA_VAULT`, else `VAULT_PATH` in `~/.config/neva/identity.env`. If the CLI exits 2, show its message: it names the fix.

## Usage

```
/promote                      # file every qualifying candidate as a proposal block
/promote --dry-run            # print the blocks, write nothing
/promote grep-before-edit     # file a block for one instinct from the current project
```

## What happens

1. Candidates, when no id is given:
   - the same instinct id active in 2 or more git projects with average confidence 0.8 or more
     (a folder outside git, and the `unscoped` bucket, never count; `scope_hint` promotes nothing),
   - and not already global.
2. Each becomes a `promote-global` block in `Instinct promotions YYYY-MM-DD.md` in the proposals folder, with a pointer under `## Open actions` in the inbox note. The block names the destination `vault:06 Memory/instincts/global/<id>.md`, the source notes, and the exact text.
3. Nothing global is written yet.

## Applying

| The owner | Run |
|---|---|
| ticks `approve` in the block | nothing now: the nightly job applies it, or run `instinct-cli.py apply-promotions` |
| says "promote <id> now" for one named instinct | `promote <id> --apply`: it files the block, prints the file to tick it in, and stops. Tell the owner where to tick; apply after the tick |

`apply-promotions --all` never applies a promote-global block without its tick (it adds only open retire blocks). On apply the global note is created (never overwritten), recorded with its hash as approved, and each source note gets `status: promoted` and `promoted_to`. Never tick a box yourself.
