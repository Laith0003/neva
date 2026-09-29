---
name: delivery-gate
description: "Use when a session must be mechanically blocked from finishing until deterministic checks pass: rationalization phrases in the transcript (warn), stale learning logs after a complex task (block), and low disk space (block). Stop hook contract."
metadata:
  version: 1.1.1
  origin: neva (adapted from ECC)
---
<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. Optional pattern set derived from obra/superpowers verification-before-completion (MIT, Jesse Vincent). -->

# Delivery Gate: Mechanical Quality Gate

A **Stop hook** that checks three things before a session can finish, using only **deterministic checks**: file modification timestamps, disk usage, and regex patterns on the transcript text. No AI inference.

Implemented by the `delivery_gate` module of the neva-core hook runtime (`hooks/neva_hooks/delivery_gate.py`). It runs in the **strict** profile only (`NEVA_HOOK_PROFILE=strict`); disable it with `NEVA_DISABLED_HOOKS=delivery_gate`. Do not register a copy in settings: it would run twice.

This is distinct from reasoning gates: delivery-gate checks machine-verifiable facts; `neva-core:santa-method` and `neva-core:agent-self-evaluation` check output quality; `neva-core:verification-loop` checks code quality with fresh evidence. Together they form defense in depth:
- **delivery-gate**: "Was the learning library touched today? Is disk space safe?"
- **verification-loop**: "Did build, types, lint, and tests pass in this message?"
- **santa-method / agent-self-evaluation**: "Is the content correct, complete, and honest?"

This is the same pattern as CI pipeline gates: automated, deterministic checks that verify machine-readable facts rather than trusting self-reported status.

## Hook Contract

| Field | Value |
|---|---|
| Event | `Stop`, strict profile |
| Input | Stop hook JSON; reads the file at `transcript_path` |
| Memory dir | `NEVA_MEMORY_DIR`; else the Claude Code project memory dir for `CLAUDE_PROJECT_DIR` or the working directory (`/` `\` `:` replaced by `-`, under `CLAUDE_CONFIG_DIR` or `~/.claude`) |
| Block | exit 2 through the dispatcher, the reason names the stale libraries or the disk level and the fix |
| Warnings | returned as a system message, never a block |
| Retry | a stop that is already a continuation (`stop_hook_active`) is never blocked again; its findings become a warning, so the gate cannot loop |
| Writes | nothing |

## What It Checks

| Check | Mechanism | On Hit |
|-------|-----------|--------|
| Rationalization patterns | Regex on the last 8000 chars of the transcript | **Warning only** (never blocks) |
| Stale learning libraries | mtime on 5 configurable paths | Warning if some stale; **Block** if >=3 stale OR growth-log stale, only when the task is complex |
| Disk space < 50 GB | `shutil.disk_usage` on home | Reminder |
| Disk space < 30 GB | `shutil.disk_usage` on home | Warning |
| Disk space < 15 GB | `shutil.disk_usage` on home | **Block** (exit 2) |

Order of evaluation: disk first (can block even on short sessions), then skip everything else if the transcript is under 40 chars, then rationalization warnings, then learning capture.

A task is **complex** when the transcript contains >= 3 structured `"name": "Edit"` or `"name": "Write"` tool calls. Prose mentions do not count.

Rationalization detection warns about patterns like "skip tests for now" and "pre-existing bug": surface signals that thinking may have been cut short. It never blocks on its own, because regex heuristics can false-positive. The blocking conditions are: disk critical, `>=3 learning libs stale`, OR `growth-log` specifically stale (both library conditions require a complex task).

If no memory directory exists, the hook warns (complex tasks only) and does **not** block: blocking there deadlocks new users who have not created it yet.

### Default rationalization patterns

```
(this|that) is a pre-existing (issue|bug)          (not followed by that/which/and)
skipping (tests|lint|coverage|type-check) for now
(tests|coverage) (are|is) (failing|broken) but (I|we) ('ll|can|will) (fix|address|resolve|handle)
(not addressing|won't fix|leaving) the (failing|broken) (tests|builds|integration tests)
```

### Optional extended set (warn only, off by default)

Claims of success without evidence, from the verification-before-completion red flags. High false-positive rate, so enable only when auditing a session:

```
\b(should|probably|seems to) (work|pass|be fixed)\b
\b(tests?|build|lint) (should|will) pass\b
\bagent (said|reported) (success|done)\b
\bjust this once\b
```

## Why

Built-in checks cover code quality (build, type, lint, test). A different failure mode: the agent produces working code while **session hygiene was neglected**: learning not captured, shortcuts rationalized, disk running out silently.

Over many sessions of "ship and forget", the human has not grown. This hook enforces the habit: complex task, then learning libraries must be touched.

## Learning Libraries

Create these in the project memory directory. The hook checks whether each was updated today:

```
memory/
├── growth-log/               # Daily learning entries (directory; any file with today's mtime counts)
├── decisions/log.md          # Decision log
├── output-index.md           # Index of session outputs
├── ratings-tracker.md        # Skill ratings over time
└── tooling_capabilities.md   # Known tools inventory
```

Missing files count as stale. Customize the `LIBS` dict to match your own structure.

## Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `NEVA_MEMORY_DIR` | project memory dir | where the learning libraries live |
| `NEVA_DELIVERY_DISK_REMIND_GB` | 50 | reminder below this |
| `NEVA_DELIVERY_DISK_WARN_GB` | 30 | warning below this |
| `NEVA_DELIVERY_DISK_CRIT_GB` | 15 | block below this |
| `NEVA_DELIVERY_GATE_EXTENDED` | off | `1` adds the success-without-evidence phrases |

Fixed in the module: 4 rationalization patterns, the 5 learning libraries, 40 characters minimum transcript, 3 Edit or Write calls for a complex task. Change `LIBS` in `delivery_gate.py` to match your own structure.

## Examples

**Simple session: allowed**
```
edit_count=1 (< 3, not complex) -> exit 0
```

**Complex task, learning captured: allowed**
```
edit_count=5 (complex) -> checks LIBS -> growth-log updated today, 2 others stale -> exit 0
```

**Complex task, no learning: BLOCKED**
```
edit_count=4 (complex) -> checks LIBS -> all 5 stale -> exit 2
reason: "Blocked: complex task (4 edits) but 5 learning libraries are stale: ... Update them in <memory dir> before stopping."
```

**Complex task, growth-log skipped: BLOCKED**
```
edit_count=3 (complex) -> growth-log stale, 1 other stale -> exit 2
reason: "Blocked: code changes made but no growth-log update today. Write a growth-log entry in <memory dir>/growth-log before stopping, even if it says no new learnings."
```

**Low disk space: BLOCKED**
```
disk_free=12GB < 15GB critical -> exit 2
reason: "Blocked: disk space at 12GB (<15GB). Free space before continuing."
```

## Limitations

The hook enforces the **habit** of touching learning libraries, not the **quality** of what was recorded. Touching `output-index.md` and `growth-log` today passes even if the entries are thin. This is by design: mechanical gates check machine-verifiable facts. For content quality, pair with `neva-core:santa-method` or `neva-core:agent-self-evaluation`.

## Compatibility

- Python 3.9+, standard library only (the hook runtime's floor)
- macOS and Linux (the hook runtime's platforms)

## See Also

- `neva-core:verification-loop`: fresh-evidence code quality checks (build, type, lint, test)
- `neva-core:santa-method`: adversarial dual-review quality gate
- `neva-core:gateguard`: PreToolUse safety gate
