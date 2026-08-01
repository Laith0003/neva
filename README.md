# Neva

**An assistant that never makes things up.**

Your own AI on Telegram, running on your machine, with a memory you can open in Obsidian.
It answers questions about your world from YOUR notes, cites the file it read, and says
"I don't have that" when the note doesn't exist. It watches its own health, rotates its own
sessions before long-context drift makes it sloppy, and messages you when something needs a
human.

> **Two ways to run this.** The simple one needs only Claude Code and Obsidian: it already has a
> model and already reads this folder, so nothing installs and nothing can be misconfigured. The
> upgrade adds openclaw so the same assistant answers on Telegram while your laptop is shut. Start
> simple; the upgrade is there when you want it.
>
> **First public release, and testers are the point.** The macOS path is proven: 38 checks
> install it from scratch in a stripped sandbox and assert the outcomes you would actually
> notice, and each check is proven able to fail. Linux has never been run end to end, not once,
> so on Linux you are the first. Read [docs/00-testing-this.md](docs/00-testing-this.md) before
> you spend an hour, and tell us what broke: that is worth more to this project right now than
> a star.

Most self-hosted assistants die two deaths: they hallucinate about your life, or they rot
(sessions bloat, syncs wedge silently, gateways end up exposed). This template exists
because both are preventable with structure, not with hope.

Every claim below is asserted by `build/verify.sh`, which installs the product from scratch
in a stripped-down sandbox that deliberately withholds the optional dependencies, then checks
the outcome a buyer would care about rather than an exit code. Every check is also proven able
to fail. If a promise here stops being true, that harness goes red before you ever see it.

## What you get

- **Grounded answers.** People, clients, money, dates: asserted only from vault notes, with
  the source named. Money is read live from your ledger on every question, never from a
  cached total, so a figure it cannot find in the ledger is one it tells you it cannot find.
- **A real setup interview.** Your agent's first conversation configures it. If an AI reads
  START.md, that agent runs the interview. If you install manually, your assistant runs the
  same interview itself the first time you talk to it. Either way it is one interview, six
  questions, once. It is never run twice.
  Either way, the agent learns your writing voice from how you type, not from asking.
- **Guards that watch the assistant itself.** Scheduled checks catch session bloat, locked
  channels, and wedged syncs. Some repair themselves; the rest tell you what broke and what
  to run. You turn them on during setup, one at a time, and `doctor` shows which are live.
- **Closed by default.** Loopback-only gateway, Telegram locked to your id, tokens never in
  tracked files. `doctor` fails loudly on the two mistakes that get self-hosters burned.
- **A vault that is yours.** Plain markdown in Obsidian. One person one note, enforced.
  hledger for money, and a food log the agent can total.

## Start here

**[SETUP GUIDE.md](SETUP%20GUIDE.md)** walks you through it in five steps, prerequisites first.
The short version:

## Quick start: say "start"

**For AI agents:** Open this folder and say **start**. The agent reads START.md, interviews you
with six questions about your work, what you want off your plate, and how you like to be spoken to,
then silently builds the whole system behind your answers. Your goals, projects, and
personality all come from that one conversation. It ends by doing a real task for you.

**For manual setup:** Follow these four steps.
1. Install [openclaw](https://docs.openclaw.ai/install) and [Obsidian](https://obsidian.md)
2. `./install.sh` and answer three identity questions
3. Fix anything `doctor` marks FAIL (each row names its fix)
4. Talk to your agent in the terminal; its first conversation is the interview
Then, and only then: [docs/02-telegram.md](docs/02-telegram.md)

**macOS: proven.** Tested end to end in a real install (see `build/verify.sh`, 38 checks).
**Linux: untested.** The install script has a Linux branch, and 14 systemd unit/timer
templates exist for it, but neither has ever been run - not once, by anyone, on a real Linux
machine. If you install on Linux, you are the first. Read
[docs/00-testing-this.md](docs/00-testing-this.md) before you start, and report what breaks.
**Windows:** WSL2 only, and inherits the Linux caveat above (WSL2 is Linux).

## The honest part

This connects an LLM to your notes and your Telegram. Read
[docs/09-security.md](docs/09-security.md) before exposing anything to the internet; it says
plainly what the defaults protect against and what they cannot.

## Licence

Apache-2.0. Fork it, change it, run it, sell it. See [LICENSE](LICENSE).

The name is separate: the licence covers the code, not the word "Neva". See
[TRADEMARK.md](TRADEMARK.md). A fork may do anything except present itself as this one.

Contributions welcome, including ones that change how this works. Sign commits with
`git commit -s`; that one line is the whole legal process. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Who built this

Neva is by [Laith Aljunaidy](https://laithjunaidy.com), built first as his own assistant and
only later as something to hand over. Background, why it exists, and how to get in touch:
[AUTHOR.md](AUTHOR.md).
