# An assistant that never makes things up

Your own AI on Telegram, running on your machine, with a memory you can open in Obsidian.
It answers questions about your world from YOUR notes, cites the file it read, and says
"I don't have that" when the note doesn't exist. It watches its own health, rotates its own
sessions before long-context drift makes it sloppy, and messages you when something needs a
human.

Most self-hosted assistants die two deaths: they hallucinate about your life, or they rot
(sessions bloat, syncs wedge silently, gateways end up exposed). This template exists
because both are preventable with structure, not with hope.

## What you get

- **Grounded answers.** People, clients, money, dates: asserted only from vault notes, with
  the source named. Money figures come only from a plain-text ledger; an amount that is not
  in the ledger does not exist.
- **A real setup interview.** Your agent's first conversation configures it: six questions,
  one at a time, and it learns your writing voice from how you type rather than asking you
  to describe it.
- **Self-healing by default.** Guard timers catch session bloat, locked channels, and sync
  wedges, fix them, and tell you. A weekly self-test messages you its score.
- **Closed by default.** Loopback-only gateway, Telegram locked to your id, tokens never in
  tracked files. `doctor` fails loudly on the two mistakes that get self-hosters burned.
- **A vault that is yours.** Plain markdown in Obsidian. One person one note, enforced.
  hledger for money, a food log the agent can total, reviews it drafts when you go quiet.

## Quick start: say "start"

Open this folder with your AI (Claude Code, or openclaw itself) and say **start**. The
agent reads START.md and drives the whole installation: it runs the commands, you answer
three questions in chat, and it hands over to your new assistant's first conversation.

Prefer doing it yourself? The manual path is the same four steps:
1. Install [openclaw](https://docs.openclaw.ai/install) and [Obsidian](https://obsidian.md)
2. `./install.sh` and answer three questions
3. Fix anything `doctor` marks FAIL (each row names its fix)
4. Talk to your agent in the terminal; its first conversation sets it up
Then, and only then: [docs/02-telegram.md](docs/02-telegram.md)

macOS and Linux. Windows via WSL2 only.

## The honest part

This connects an LLM to your notes and your Telegram. Read
[docs/09-security.md](docs/09-security.md) before exposing anything to the internet; it says
plainly what the defaults protect against and what they cannot.
