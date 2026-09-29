---
name: terminal-opener
description: "Open an executable plus argv in a visible terminal window via a shell-free launch plan with dry-run, JSON, detection, fallback and recovery modes. Use to open an interactive CLI, SSH session or dev process in a new terminal, or check terminal support."
---

<!-- Adapted from affaan-m/ECC (MIT), commit d3b8a3e. Merged for Neva. -->

# Terminal Opener

requires: node (the launcher is `scripts/open-terminal.js`; paths below are relative to the `neva-ops` plugin root). Set `NEVA_TERMINAL` to choose the adapter.

Use `scripts/open-terminal.js` to preserve an executable and every argument as
separate process entries. Never interpolate a shell command string. Keep every
spawn on `shell: false`. Default to a non-launching plan. Use `--launch` only
after the user explicitly requests a real window and the argv has been reviewed.
The launched process inherits the full environment of the calling process,
including secret-bearing variables. The launcher does not filter the
environment. Run it from a shell whose environment is safe to expose to the
target command.

## Launch a command

Pass launcher options before `--`, then pass exactly one executable followed by
its argument array:

```bash
node skills/terminal-opener/scripts/open-terminal.js \
  --launch \
  --cwd /absolute/host/path \
  -- ssh -t example.test command-with-arguments
```

Run normal mode first. Let WezTerm try its mux with a new window, then let the
launcher fall back to a detached `wezterm start` process if the mux is not
available. When fallback is used, read `muxFailure` from JSON output (or the
human-readable failure line) to diagnose why the mux path failed.

## Recover from terminal configuration

Add `--recover` or `--standalone` when user configuration or mux state may
interfere with the requested command. Start a detached WezTerm process with:

```text
--skip-config start --always-new-process
```

Expect recovery mode to skip all user terminal configuration intentionally.

## Inspect before launch

Omit `--launch` (or add `--dry-run`) and add `--json` to inspect the exact
executable, argv, working directory, terminal adapter, primary launch, and
fallback without opening a window. Treat the JSON plan as the composition
boundary for callers.

Run `--detect --json` without a command to probe terminal availability. Follow
the returned `action` when the adapter is missing or unsupported. Use WezTerm
for the current adapter; treat other requested terminals as unsupported plans,
not as commands to execute.
