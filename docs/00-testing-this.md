# Testing Neva: what is proven, what is not, and what we need to know

You have landed on a template that ships with an automated harness proving it works. Before
you spend an hour, know what that proof covers and what it does not.

## What is proven (and will not silently break)

- **macOS fresh install.** From "bare homebrew" to talking to the agent, tested in a 38-check
  sandbox that installs the product from scratch, locks down permissions, and runs every
  documented step in sequence. This path is stable.
- **The interview is real.** Your first conversation actually configures the system. You
  answer six questions and the agent is set up. No separate setup commands needed.
- **Grounding works without optional dependencies.** The agent finds notes by content even
  without ripgrep installed. (If you install ripgrep, it speeds up; if you do not, it
  still works.)
- **Core tools are on PATH.** `canon`, `cadence`, `doctor`, and the others are where the
  instructions say they are. (Yes, including on older macOS where `find` is BSD, not GNU.)
- **Integration dependencies are optional.** Neva works fine if you never install `hledger`
  or `syncthing`. They add features; absence is not an error.

## What is not proven (and might be rough)

- **Linux, end-to-end: genuinely untested, not just "less tested."** `install.sh` has a
  non-Darwin branch and 14 systemd unit/timer templates exist under `services/systemd/`, both
  written to the same contract as the macOS path - but neither has ever actually executed.
  Not the full flow, not a partial run, not once, by anyone, on a real Linux machine. Everything
  Linux-specific in this repo is reviewed and believed correct, not proven. If you are on
  Linux, you are the first real run it has ever had. Expect the class of bug that only shows
  up live: file paths, permissions, `systemctl --user` needing `loginctl enable-linger` to
  survive an SSH logout, timers not firing on first boot. Report all of it, including things
  that work - a confirmed-working Linux install is itself useful information nobody has yet.
- **Non-ASCII vault content.** Arabic notes exist in the test vault; searches for Arabic
  text work in the harness. But a real vault with Arabic names, money-tracking in Arabic,
  and mixed-language journal entries has never been lived in. If this is you, test it hard
  and report what breaks.
- **Vault paths with spaces or special characters.** The code should handle them. The harness
  only tests the default `~/Vault`. If you use a path like `~/My Documents/Vault`, report
  what breaks.
- **Long-term vault growth.** The harness runs for minutes. A real vault with 2,000+ notes,
  six months of history, and heavy canon-lint usage has not been stress-tested. If your
  vault is large, monitor performance and report if things slow down.
- **Re-running install.sh over an existing Neva installation.** The script is idempotent
  (it will not overwrite existing files), but the "upgrade" path (pulling the latest Neva
  code and re-running install.sh) is not heavily tested. If you do this, report whether
  your config survived intact.
- **Disaster recovery.** SOUL.local.md and identity.env are never synced and must be backed
  up by you. If you lose them, setup is incomplete. There is no recovery flow documented.
  If you need one, the answer is "restore from backup" and it is not yet written.

## What will definitely be rough

- **Documentation for paid tiers.** This is the free tier. `docs/tier2/hardening-checklist.md`
  and `docs/11-agent-voice.md` are new and have never been used by anyone. Read them carefully;
  they might have steps in the wrong order or assumptions that do not hold on your machine.
  Report specific failures (step 3 failed because X) not vague ones (hardening is confusing).
- **Integrations beyond Telegram.** The agent works in the terminal and on Telegram out of
  the box. SSH, reverse proxies, Tailscale, and self-hosted instances are in the docs but
  not in the main test harness. If you set up any of those, you are on newer ground. Test
  thoroughly.

## What feedback is useful (and what is not)

### Useful feedback:

- **A specific command failed.** "I ran `install.sh` and it printed `python3: command not
  found` on line 42." Tell us the command, the error, and your OS. Include the output of
  `uname -a`.
- **Something works but does not match the docs.** "The docs say to edit `/etc/systemd/...` but
  I am on macOS." Docs might be out of sync with code. Tell us what you expected and what you
  found.
- **doctor says FAIL but you do not understand the fix.** Show us the exact FAIL line and the
  fix it suggested. If the fix does not work, tell us what happened.
- **A scheduled job never fired.** "I enabled cadence via `launchctl` and doctor says it is
  loaded, but no review has drafted in a week." Tell us the job name, when you enabled it,
  and what doctor says about it now. Include the error log:
  `tail ~/.local/state/neva/cadence.err.log`.
- **Performance issue with a specific vault size.** "I have 500 notes and `doctor` now takes
  30 seconds to run." Tell us the vault size (note count, disk size) and what operation is
  slow.
- **Linux blockers specifically.** "I installed on Ubuntu 24.04 and `install.sh` failed
  because X." Tell us the Linux version and the exact failure. We can fix it.

### Not useful:

- **"It does not work."** Tell us what you did, what you expected, and what happened instead.
- **Feature requests or design opinions.** This is a test phase, not a roadmap planning phase.
  Focus on what is broken.
- **Vague security concerns.** "Is it safe to expose the gateway?" is a policy question,
  answered in docs/09-security.md. If the docs are wrong or unclear, say so.
- **"I want voice features" or "I want it to write emails for me."** Those are not this
  product. Report if the agent's *existing* behavior is wrong.

## How to report a bug

Open an issue on GitHub (or, if you are testing privately, send the information to the
author). Include:

1. Your OS (`uname -a`).
2. The command you ran.
3. The exact error or output.
4. What you expected instead.
5. The output of `doctor` (copy the whole thing).
6. The output of `bash build/verify.sh` (from the repo root; if you cloned it, this should
   pass). If it fails, that is the bug report right there; tell us which check failed.

The more specific you are, the faster we can fix it.

## First week expectations

- Day 1: Install, run the interview, set up Telegram. Expect 20 minutes of terminal time.
- Day 2-3: Send it real tasks. See if it gets them right. Wrong answers mean vault setup
  (missing notes) not a product bug.
- Week 1: Run `doctor` if anything feels off. Enable one scheduled job at a time and watch
  it in `~/.local/state/neva/` logs before enabling the next.
- By end of week: You should know whether the core promise (grounded answers from your notes,
  accessible from Telegram, running on your machine) is true for you or false. If it is
  false, that is the bug report we want.

## Thank you

Neva is small because it does one thing (ground answers in your own notes) instead of many
things poorly. That smallness makes testing possible. Your feedback closes the gap between
what we think we built and what is actually out there.
