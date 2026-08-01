# Configuration: identity.env and agent behavior

Your assistant's behavior is configured in `~/.config/neva/identity.env`, created during
install.sh. This file is not tracked in git (it holds sensitive data); edit it any time and
re-run `doctor` to validate.

## Essential config (written during setup)

| Variable | Set by | What it does |
|---|---|---|
| OWNER_NAME | install.sh / BOOTSTRAP | Your name; used in greeting and logs |
| AGENT_NAME | install.sh / BOOTSTRAP | Your assistant's name; you choose it |
| TIMEZONE | install.sh / BOOTSTRAP | Local timezone for scheduling; detected at install |
| VAULT_PATH | install.sh / BOOTSTRAP | Where your vault folder lives (default ~/Vault) |
| WORKSPACE_PATH | install.sh | Where agent state lives (default ~/.openclaw/workspace) |

## Behavior config (from BOOTSTRAP interview)

| Variable | Asked as | What it does |
|---|---|---|
| ACTIVE_HOURS_START | Boundaries (Q6/Beat 6) | When the agent may message you first (default 08:00) |
| ACTIVE_HOURS_END | Boundaries | When the agent must stop messaging (default 22:00) |
| QUIET_DAYS | Boundaries | Days when agent stays silent (optional; format: Mon,Fri) |
| LEDGER_FILE | Auto-set | Path to your money journal (default $VAULT_PATH/05 Money/2026.journal) |
| FOOD_DIR | Auto-set | Path to your food log folder (default $VAULT_PATH/Food) |

## HEARTBEAT: what it is, and what it is not

There is no `HEARTBEAT` setting in `identity.env`, and nothing in this codebase reads one.
An earlier draft of this page documented a `HEARTBEAT_MS` key with a default and a batching
behaviour. That key does not exist and never did. It is removed rather than implemented,
because inventing a setting a buyer can set and watch do nothing is worse than having no
setting at all.

The word appears in two unrelated places, and they are not the same thing:

**1. Proactive check-ins (what the persona files mean).** When your assistant may speak
first, and about what. This is prose, not a variable: the interview writes it into the
Proactivity section of `workspace/SOUL.local.md`, in your words, including the verbatim
sentence you gave about what kind of unsolicited message would annoy you. To change it, edit
that section or just tell your assistant, which is the point of it being prose.

**2. Job heartbeats (what `services/heartbeat-wrap.sh` means).** Every scheduled job runs
through a wrapper that records one line per invocation, so `doctor` can tell a job that ran
and failed apart from a job that has never run at all. That distinction is why the review
nudge could sit dead for six weeks on a real system without any guard noticing. This is
internal plumbing; you never set it.

## Integrations (optional)

| Variable | Integration | What it does |
|---|---|---|
| OWNER_CHAT_ID | Telegram | Your numeric Telegram ID; filled after first Telegram message |
| OWNER_EMAIL | Integrations | Email address (only set if an installed integration needs it) |
| OWNER_PHONE | Integrations | Phone number (only set if an installed integration needs it) |



## Model configuration

Model setup is not done through identity.env. Give your assistant a model before first run:
[docs/01a-model.md](01a-model.md) covers both paths (Claude subscription or API key).

## How to edit

Edit `~/.config/neva/identity.env` in your text editor:
```bash
# macOS
open ~/.config/neva/identity.env

# Linux
$EDITOR ~/.config/neva/identity.env
```

Make changes (one setting per line: `KEY=value`), save, then run `doctor`:
```bash
doctor
```

Doctor will validate your settings and warn you if anything looks wrong.

## Examples

**Change your active hours**
```bash
ACTIVE_HOURS_START=09:00
ACTIVE_HOURS_END=20:00
```

**Track money in a different folder**
```bash
LEDGER_FILE=/Users/you/Shared/money/2026.journal
```

**Restrict the agent to weekdays only**
```bash
QUIET_DAYS=Sat,Sun
```

## Validation with doctor

After editing, run `doctor` to check:
```bash
doctor
```

Doctor will report:
- Missing required keys: `FAIL`
- File permissions wrong (not 600): `FAIL`
- Optional integrations unconfigured: `WARN` (fine to ignore)
- Everything else: `ok`

Exit 0 = your config is valid. Exit 1 = fix the failures above.

---

See [docs/01-first-run.md](01-first-run.md) for setup, [docs/02-telegram.md](02-telegram.md)
for Telegram config, and [docs/03-scheduled-jobs.md](03-scheduled-jobs.md) for timer settings.
